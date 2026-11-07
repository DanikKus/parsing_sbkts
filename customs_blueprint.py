# customs_blueprint.py
import logging
import re
import threading
import time
from typing import Optional, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify

customs_bp = Blueprint("customs", __name__)

CUSTOMS_URL = "https://customs.gov.ru/cars"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

logger = logging.getLogger(__name__)

CUSTOMS_CACHE: Dict[str, Dict] = {}
CUSTOMS_CACHE_LOCK = threading.Lock()
CUSTOMS_CACHE_TTL = 3600        # 1 час  — для found=True
CUSTOMS_CACHE_TTL_MISS = 300    # 5 минут — для genuine miss (found=False без ошибки)


# ======================== Вспомогательные функции ========================

def _is_valid_vin(vin: str) -> bool:
    return bool(VIN_RE.match((vin or "").strip().upper()))


def _extract_csrf_customs(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    # hidden input
    inp = soup.find("input", {"name": "_token"})
    if inp and inp.get("value"):
        return inp["value"]
    # meta
    meta = soup.find("meta", attrs={"name": re.compile(r"csrf-token", re.I)})
    if meta and meta.get("content"):
        return meta["content"]
    return None


def _extract_country_from_icons(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Флаг+код страны (если есть)."""
    names = {
        "kz": "Казахстан",
        "ru": "Россия",
        "by": "Беларусь",
        "am": "Армения",
        "kg": "Киргизия",
    }

    # --- Новая верстка (2025+): car-register-result__flag-card ---
    flag_card = soup.select_one(".car-register-result__flag-card")
    if flag_card:
        img = flag_card.select_one('img[src*="/flags/"]')
        code_div = flag_card.select_one(".car-register-result__flag-code")

        code: Optional[str] = None
        flag_url: Optional[str] = None

        if img:
            flag_url = img.get("src")
            code = img.get("alt") or None  # alt="kz" — прямой источник кода

        if not code and code_div:
            code = code_div.get_text(strip=True) or None

        if not code and flag_url:
            m = re.search(r"/flags/([a-z]{2,3})\.svg", flag_url, re.I)
            if m:
                code = m.group(1)

        if code:
            code = code.strip().lower()
            return code.upper(), names.get(code), flag_url

    # --- Старая верстка: vin-check__card-icon / vin-check__card-icons ---
    icon = soup.select_one(".vin-check__card-icon") or soup.select_one(".vin-check__card-icons")
    if not icon:
        icon = soup.select_one('[class*="vin-check"] [class*="icon"]')
        if not icon:
            return None, None, None

    code = None
    title = icon.select_one(".vin-check__card-title") or icon.select_one('[class*="title"]')
    if title:
        code = (title.get_text(strip=True) or None)

    img = icon.select_one('img[src*="/flags/"]')
    flag_url = None
    if img and img.get("src"):
        flag_url = img["src"]
        m = re.search(r"/flags/([a-z]{2})\.svg", flag_url, re.I)
        if (not code) and m:
            code = m.group(1)

    if not code:
        return None, None, flag_url

    code = code.strip().lower()
    return code.upper(), names.get(code), flag_url


def _kv(title_el, value_el) -> Tuple[str, str]:
    k = title_el.get_text(" ", strip=True) if title_el else ""
    v = value_el.get_text(" ", strip=True) if value_el else ""
    return k, v


def _parse_customs_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, Any] = {
        "found": False,
        "source": CUSTOMS_URL,
    }

    card = soup.select_one(".vin-check__card") or soup
    pairs = []

    # --- Стратегия 0: новая верстка (2025+): car-register-grid__label/value ---
    new_items = soup.select(".car-register-grid__item")
    for it in new_items:
        label = it.select_one(".car-register-grid__label")
        value = it.select_one(".car-register-grid__value")
        if label or value:
            pairs.append(_kv(label, value))

    # --- Стратегия 1 (старая): пары .vin-check__card-title / .vin-check__card-info ---
    if not pairs:
        for it in card.select(".vin-check__card-item"):
            title = it.select_one(".vin-check__card-title")
            value = it.select_one(".vin-check__card-info")
            if title or value:
                pairs.append(_kv(title, value))

    # --- Более общий вариант: любые элементы с классами, содержащими *title* и *info*
    if not pairs:
        items = card.select('[class*="card"] [class*="item"]') or card.select(
            '[class*="vin-check"] [class*="item"]'
        )
        for it in items:
            t = it.select_one('[class*="title"]')
            v = it.select_one('[class*="info"]')
            if t or v:
                pairs.append(_kv(t, v))

    # --- Фолбэк: dl/dt/dd
    if not pairs:
        for dl in card.find_all("dl"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for i in range(min(len(dts), len(dds))):
                pairs.append(_kv(dts[i], dds[i]))

    # Собираем пары в словарь
    for k, v in pairs:
        if not k or not v:
            continue
        out[k.strip()] = v.strip()

    # Нормализованные ключи
    def get_any(names: list[str]) -> Optional[str]:
        for n in names:
            if n in out and out[n]:
                return out[n]
        # поиск текста по label (если точного ключа нет)
        for lab in names:
            node = soup.find(string=re.compile(rf"^\s*{re.escape(lab)}\s*$", re.I))
            if node:
                parent = node.parent
                info = parent.find_next(class_=re.compile(r"info|value", re.I))
                if info:
                    return info.get_text(" ", strip=True)
                if parent and parent.next_sibling:
                    txt = str(parent.next_sibling).strip()
                    if txt:
                        return txt
        return None

    vin_ = get_any(["Номер VIN", "VIN"])
    model = get_any(["Модель"])
    body = get_any(["Номер кузова", "Кузов"])
    chassis = get_any(["Номер шасси", "Шасси"])
    date_rel = get_any(
        [
            "Дата выпуска в свободное обращение",
            "Дата выпуска в СВО",
            "Дата выпуска в СБО",
        ]
    )
    country = get_any(["Страна выпуска"])

    # Страна (иконки)
    cc, cname, cflag = _extract_country_from_icons(soup)
    if cc and (not country):
        country = f"{cc} — {cname}" if cname else cc

    # Признак "нашли"
    page_text = soup.get_text(" ", strip=True).lower()
    if "сведения отсутствуют" in page_text:
        found = False
    else:
        found = any([vin_, date_rel, model, body, chassis, country])

    return {
        "found": found,
        "vin": vin_,
        "model": model,
        "bodyNumber": body,
        "chassisNumber": chassis,
        "releaseToFreeCirculationDate": date_rel,
        "country": country,
        "countryCode": cc,
        "countryName": cname,
        "countryFlag": cflag,
        "raw": out,
        "source": out.get("source", CUSTOMS_URL),
    }


def _query_customs_by_vin(vin: str, timeout: int = 20) -> Dict[str, Any]:
    vin = (vin or "").strip().upper()
    if not _is_valid_vin(vin):
        return {
            "found": False,
            "error": "VIN должен содержать 17 символов A-Z/0-9 (без I,O,Q).",
            "vin": vin,
            "source": CUSTOMS_URL,
        }

    with requests.Session() as s:
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        # 1) GET: получаем CSRF
        r1 = s.get(CUSTOMS_URL, timeout=timeout)
        r1.raise_for_status()

        # Проверяем требует ли сайт авторизацию (изменение политики customs.gov.ru)
        if "vin-check__auth" in r1.text:
            return {
                "found": False,
                "error": "customs.gov.ru требует авторизацию через личный кабинет — автоматическая проверка недоступна",
                "vin": vin,
                "source": CUSTOMS_URL,
            }

        token = _extract_csrf_customs(r1.text)
        if not token:
            return {
                "found": False,
                "error": "Не найден CSRF _token",
                "step": "GET",
                "vin": vin,
                "source": CUSTOMS_URL,
            }

        # 2) POST: отправляем форму
        data = {"vin": vin, "_token": token}
        headers = {
            "Referer": CUSTOMS_URL,
            "Origin": "https://customs.gov.ru",
            "X-CSRF-TOKEN": token,
            "X-Requested-With": "XMLHttpRequest",
        }
        r2 = s.post(CUSTOMS_URL, data=data, headers=headers, timeout=timeout)
        r2.raise_for_status()

        res = _parse_customs_html(r2.text)
        res["vin"] = res.get("vin") or vin
        return res


# ======================== Публичная функция для других модулей ========================

def check_customs_ru(vin: str) -> Dict[str, Any]:
    """
    Автоматическая проверка VIN на customs.gov.ru.
    Возвращает словарь вида:
    {
      "found": True/False,
      "vin": "...",
      "data": { ... },
      "country": { code, name, flag },
      "source": "customs.gov.ru/cars",
      "error"/"message": "..." (опционально)
    }
    """
    vin = (vin or "").strip().upper()

    if not _is_valid_vin(vin):
        return {
            "found": False,
            "vin": vin,
            "error": "Некорректный VIN (17 символов, без I/O/Q).",
            "source": CUSTOMS_URL,
        }

    # --- Кэш: проверка ---
    now = time.time()
    with CUSTOMS_CACHE_LOCK:
        entry = CUSTOMS_CACHE.get(vin)
        if entry and now < entry["exp"]:
            logger.info("[customs cache] hit for VIN %s", vin)
            return entry["result"]

    try:
        res = _query_customs_by_vin(vin)
    except requests.RequestException as e:
        return {
            "found": False,
            "vin": vin,
            "error": f"HTTP: {e}",
            "source": CUSTOMS_URL,
        }
    except Exception as e:
        return {
            "found": False,
            "vin": vin,
            "error": f"Ошибка: {e}",
            "source": CUSTOMS_URL,
        }

    if not res.get("found"):
        result: Dict[str, Any] = {
            "found": False,
            "vin": vin,
            "message": res.get("error") or "Данные по VIN не найдены на customs.gov.ru.",
            "source": res.get("source") or CUSTOMS_URL,
        }
        # Genuine miss (VIN не в базе) — кэшируем на короткий TTL.
        # Сетевые и HTTP-ошибки сюда не попадают (они перехвачены выше).
        with CUSTOMS_CACHE_LOCK:
            CUSTOMS_CACHE[vin] = {"result": result, "exp": time.time() + CUSTOMS_CACHE_TTL_MISS}
        return result

    result = {
        "found": True,
        "vin": res.get("vin") or vin,
        "data": {
            "Номер VIN": res.get("vin") or "",
            "Модель": res.get("model") or "",
            "Номер кузова": res.get("bodyNumber") or "",
            "Номер шасси": res.get("chassisNumber") or "—",
            "Дата выпуска в свободное обращение": res.get("releaseToFreeCirculationDate") or "",
            "Страна выпуска": res.get("country") or "",
        },
        "country": {
            "code": res.get("countryCode"),
            "name": res.get("countryName"),
            "flag": res.get("countryFlag"),
        },
        "source": res.get("source") or CUSTOMS_URL,
    }
    # --- Кэш: сохранение found=True ---
    with CUSTOMS_CACHE_LOCK:
        CUSTOMS_CACHE[vin] = {"result": result, "exp": time.time() + CUSTOMS_CACHE_TTL}
    return result


# ======================== HTTP-эндпоинт ========================

@customs_bp.route("/customs/check", methods=["POST"])
def customs_check():
    """
    Вход: { "vin": "WDB..." }
    Выход: тот же формат, что и у check_customs_ru(...)
    """
    data = request.get_json(silent=True) or {}
    vin = (data.get("vin") or "").strip().upper()

    result = check_customs_ru(vin)

    # Отдельно даём 400 только за некорректный VIN
    if not result.get("found") and "Некорректный VIN" in str(result.get("error", "")):
        return jsonify(result), 400

    return jsonify(result), 200
