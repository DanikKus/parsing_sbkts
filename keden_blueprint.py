# keden_blueprint.py
import logging
import re
import threading
import time
from typing import Optional, Dict, Any, List

import requests
from flask import Blueprint, request, jsonify

keden_bp = Blueprint("keden", __name__)

KEDEN_BASE    = "https://keden.kgd.gov.kz"
KEDEN_VIN_URL = f"{KEDEN_BASE}/api/v1/declaration/declarations/integration/public/vin"
KEDEN_INIT_URL = f"{KEDEN_BASE}/api/v1/auth/announcements/actual"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)

logger = logging.getLogger(__name__)

KEDEN_CACHE: Dict[str, Dict] = {}
KEDEN_CACHE_LOCK = threading.Lock()
KEDEN_CACHE_TTL      = 3600   # 1 час для найденных
KEDEN_CACHE_TTL_MISS = 300    # 5 минут для ненайденных


def _is_valid_vin(vin: str) -> bool:
    return bool(VIN_RE.match((vin or "").strip().upper()))


def _query_keden_by_vin(vin: str, timeout: int = 20) -> List[Dict]:
    with requests.Session() as s:
        s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Referer": f"{KEDEN_BASE}/?vinCustomsCheck=true",
        })

        # Получаем XSRF-TOKEN cookie через служебный эндпоинт
        try:
            s.get(KEDEN_INIT_URL, timeout=timeout)
        except Exception:
            pass

        xsrf = s.cookies.get("XSRF-TOKEN")
        if xsrf:
            s.headers["X-XSRF-TOKEN"] = xsrf

        r = s.get(f"{KEDEN_VIN_URL}/{vin}", timeout=timeout)
        r.raise_for_status()
        return r.json() or []


def check_keden_kz(vin: str) -> Dict[str, Any]:
    vin = (vin or "").strip().upper()

    if not _is_valid_vin(vin):
        return {
            "found": False,
            "vin": vin,
            "error": "Некорректный VIN (17 символов, без I/O/Q).",
            "source": KEDEN_VIN_URL,
        }

    now = time.time()
    with KEDEN_CACHE_LOCK:
        entry = KEDEN_CACHE.get(vin)
        if entry and now < entry["exp"]:
            logger.info("[keden cache] hit for VIN %s", vin)
            return entry["result"]

    try:
        records = _query_keden_by_vin(vin)
    except requests.RequestException as e:
        return {"found": False, "vin": vin, "error": f"HTTP: {e}", "source": KEDEN_VIN_URL}
    except Exception as e:
        return {"found": False, "vin": vin, "error": f"Ошибка: {e}", "source": KEDEN_VIN_URL}

    if not records:
        result: Dict[str, Any] = {
            "found": False,
            "vin": vin,
            "message": "Данные по VIN не найдены на keden.kgd.gov.kz.",
            "source": KEDEN_VIN_URL,
        }
        with KEDEN_CACHE_LOCK:
            KEDEN_CACHE[vin] = {"result": result, "exp": time.time() + KEDEN_CACHE_TTL_MISS}
        return result

    rec = records[0]
    result = {
        "found": True,
        "vin": vin,
        "declarations": records,
        "data": {
            "Дата поиска":            rec.get("searchDate", ""),
            "Номер декларации":       rec.get("declarationNumber", ""),
            "Таможенный пост":        rec.get("customsOfficeName", ""),
            "Вышестоящий орган":      rec.get("parentCustomsOfficeName", ""),
            "Марка":                  rec.get("vehicleMkDescription", ""),
            "Модель":                 rec.get("vehicleModel") or "",
            "Дата выпуска":           rec.get("vehicleIssueDate", ""),
            "Объем двигателя, см³":   rec.get("vehicleEngineCapacityInCm3", ""),
            "Номер двигателя":        rec.get("vehicleEngineNumber") or "",
            "Номер кузова":           rec.get("vehicleMtcBody") or "",
            "VIN код":                rec.get("vehicleVinCode", ""),
            "Тип декларации":         rec.get("declarationTypeName", ""),
        },
        "source": KEDEN_VIN_URL,
    }

    with KEDEN_CACHE_LOCK:
        KEDEN_CACHE[vin] = {"result": result, "exp": time.time() + KEDEN_CACHE_TTL}
    return result


@keden_bp.route("/keden/check", methods=["POST"])
def keden_check():
    """
    Вход: { "vin": "W1K..." }
    Выход: { found, vin, data{...}, declarations[...], source }
    """
    body = request.get_json(silent=True) or {}
    vin = (body.get("vin") or "").strip().upper()

    result = check_keden_kz(vin)

    if not result.get("found") and "Некорректный VIN" in str(result.get("error", "")):
        return jsonify(result), 400

    return jsonify(result), 200
