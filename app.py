from flask import Flask, render_template, request, jsonify, send_file, Response, session, make_response
from bs4 import BeautifulSoup
import re
from auth_token_selenium import get_token_and_cookies_via_selenium, save_auth_to_cache, load_auth_from_cache
from comparedocs import extract_text_from_pdf, parse_fields, postprocess_ev_fields
from zipfile import ZipFile, ZIP_STORED
from flask import send_file
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from flask import current_app
import mimetypes
import requests
import os
import base64, json
from datetime import datetime, timedelta
import tempfile
import threading
import time
import webbrowser
import urllib3
import json
import base64, io, hashlib, pathlib, json
from parse_pts_json import(
    parse_vehicle_data_from_url,
    parse_vehicle_data_from_raw,
    check_violation_point5,
)
from datetime import datetime
from techreg_blueprint import techreg_bp
from customs_blueprint import customs_bp, check_customs_ru
from keden_blueprint import keden_bp, check_keden_kz
from pathlib import Path
from flask import Blueprint
from flask_cors import CORS
from auth import require_token, permissive_token, verify_token, _extract_user,  get_current_user 
from flask import g, request
from werkzeug.exceptions import Unauthorized
from requests.cookies import RequestsCookieJar
from flask import request, jsonify
from requests.exceptions import RequestException
import requests
import logging, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# --- файловый лог: logs/app.log, ротация 5 МБ, 3 файла ---
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler = RotatingFileHandler(
    os.path.join(_log_dir, "app.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_fmt)
_file_handler.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)
_console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[_file_handler, _console_handler],
)

logger = logging.getLogger(__name__)

for noisy in ("urllib3", "selenium", "WDM", "werkzeug", "requests"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

ENABLE_NUMBER_FEATURES = True  # или False, если хочешь временно вырубить

import random
QUEUE_LOCK = threading.Lock()
SENT_LOCK = threading.Lock()
SESSION_CACHE_LOCK = threading.Lock()

AUTH_STRICT = False  # <<< временно включаем dev-режим, без строгой проверки токена
if not AUTH_STRICT:
    # в dev-режиме снимаем жёсткую проверку токена
    require_token = permissive_token

PTS_ORIGIN = os.getenv("PTS_ORIGIN", "https://pts.gov.kz").rstrip("/")

BASE = PTS_ORIGIN
PTS_LIST_URL = f"{BASE}/api/compliencedocument/getList"
PTS_API_BASE = f"{BASE}/api/compliencedocument"
DOC_BY_ID_URL    = f"{BASE}/api/compliencedocument/getById"
DOC_DETAILS_URL = f"{BASE}/api/compliencedocument/getAllInfo"
UPSTREAM_BASE = os.getenv("UPSTREAM_BASE", "http://localhost:8080").rstrip("/")
API_VERIFY_URL = os.getenv("API_VERIFY_URL", "http://localhost:8080/api/local-session/verify").rstrip("/")

app = Flask(__name__)

app.secret_key = 'dev-secret-key-change-in-production'  # ← ДОБАВЬТЕ ЭТУ СТРОКУ

# Cache-busting: версия статики = max mtime CSS/JS файлов (меняется при изменении файла)
_static_dir = pathlib.Path(__file__).parent / "static"
_STATIC_VERSION = str(int(max(
    ((_static_dir / f).stat().st_mtime for f in ("style.css", "script.js", "vins.js")
     if (_static_dir / f).exists()),
    default=time.time()
)))

@app.context_processor
def _inject_static_version():
    return {"static_v": _STATIC_VERSION}

AUTH_STORE_DIR = Path("./auth_store")
AUTH_STORE_DIR.mkdir(exist_ok=True)
AUTH_TTL_HOURS = int(os.getenv("AUTH_TTL_HOURS", "24"))  # сколько держим cookies
pts_auth_cache = {}

def debug_dump(name, data):
    Path("debug").mkdir(exist_ok=True)
    with open(f"debug/{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _janitor_auth():
    ttl = AUTH_TTL_HOURS * 3600
    while True:
        try:
            now = time.time()
            for p in AUTH_STORE_DIR.glob("*_cookies.json"):
                try:
                    if p.is_file() and now - p.stat().st_mtime > ttl:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(600)  # раз в 10 минут


BIND_TO_IP = True

SESSION_CACHE = {}           # { key: {"sess": requests.Session, "exp": ts} }
SESSION_TTL = 300   

CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                "https://modulab.kz",
                "https://parser.modulab.kz",
                "http://localhost:5173", "http://127.0.0.1:5173",
                "http://localhost:5000", "http://127.0.0.1:5000",
                "http://192.168.16.90:5000",
                r"chrome-extension://.*"   # 👈 важно для вызовов прямо из расширения
            ],
            "allow_headers": ["Content-Type", "X-Parser-Token"],
            "methods": ["GET", "POST", "OPTIONS"],
        }
    },
    supports_credentials=False   # как и было; если начнёте слать cookie — поставьте True
)

SENT_PATH = "decisions_sent.json"      # журнал успешно применённых решений
DEAD_PATH = "decisions_dead.json"      # «мёртвые» задачи после лимита попыток
MAX_ATTEMPTS = 10       

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import truststore
    truststore.inject_into_ssl()  # использовать системные корневые сертификаты (Windows/OS)
except Exception:
    pass

PTS_LIST_URL = f"{BASE}/api/compliencedocument/getList"  # держим один стиль

eokno_bp = Blueprint("eokno", __name__)
pts_bp = Blueprint("pts", __name__)

# Кириллица → латиница для "похожих" букв (ТС KZ А-... → TS KZ A-...)
CYR_TO_LAT = str.maketrans({
    "А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"S","Т":"T","У":"Y","Х":"X",
    "а":"a","е":"e","о":"o","р":"p","с":"s","у":"y","х":"x","к":"k","м":"m","н":"h","т":"t","в":"b",
    "№":"No"
})

DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"  # обычная строка, а не raw


def normalize_doc_number(num: str) -> str:
    s = (num or "").strip()
    # схлопнуть пробелы
    s = re.sub(r"\s+", " ", s)
    # привести к латинице для похожих букв
    s = s.translate(CYR_TO_LAT)
    # унифицировать дефисы и точки
    s = re.sub(f"[{DASHES}]", "-", s)  # все длинные дефисы → обычный -
    s = re.sub(r"\s*-\s*", "-", s)     # убрать пробелы вокруг -
    s = re.sub(r"\s*\.\s*", ".", s)    # убрать пробелы вокруг .
    # убрать "TS/TC KZ" в начале для одного из вариантов
    return s.upper()

def docnumber_variants(num: str) -> list[str]:
    """Генерим пул вариантов для поиска."""
    raw = (num or "").strip()
    norm = normalize_doc_number(raw)
    # без префикса TS/TC KZ
    tail = re.sub(r"^(TS|TC)\s*KZ\s*", "", norm)
    # только «корешок» (буква-серия + цифры/точки), и совсем без точек
    tail_pure = re.sub(r"[^A-Z0-9.]", "", tail)
    tail_digits = tail_pure.replace(".", "")
    # уникальный список
    seen, out = set(), []
    for v in [raw, norm, tail, tail_pure, tail_digits]:
        v = (v or "").strip()
        if v and v not in seen:
            out.append(v); seen.add(v)
    return out

def make_pts_request(endpoint, data=None, method='POST', timeout=30):
    """
    Универсальный вызов PTS API:
    - всегда ходим через сессию с куками конкретного пользователя (_session_with_auth)
    - если JWT есть (в кеше/сессии/файле) — добавляем Authorization: Bearer ...,
      но его отсутствие больше не считается ошибкой.
    """
    try:
        s = _session_with_auth()  # куки уже внутри

        # пробуем найти JWT, но это опционально
        user = getattr(request, "user", {}) or {}
        user_id = user.get("id") or user.get("userId") or "unknown"
        cached = pts_auth_cache.get(user_id) or {}
        pts_token = cached.get("pts_token") or session.get("pts_jwt_token")

        if not pts_token:
            # читаем из файла, если сохраняли через /epts/attach
            try:
                user_key = _user_key()
                jwt_path = AUTH_STORE_DIR / f"{user_key}_jwt.txt"
                if jwt_path.exists():
                    pts_token = jwt_path.read_text(encoding="utf-8").strip()
            except Exception:
                pts_token = None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PTSClient/1.0",
            "Origin": BASE,
            "Referer": BASE + "/",
        }
        if pts_token and _looks_like_jwt(pts_token):
            headers["Authorization"] = f"Bearer {pts_token}"

        url = f"{BASE}{endpoint}"
        if (method or "POST").upper() == "POST":
            r = s.post(url, json=data, headers=headers, timeout=timeout, verify=VERIFY_TLS)
        else:
            r = s.get(url, headers=headers, timeout=timeout, verify=VERIFY_TLS)

        if r.status_code == 200:
            # ответ может быть {"data": ...} или сразу объект — вернём как есть
            try:
                return r.json()
            except ValueError:
                return {"raw": r.text}

        return {"error": f"PTS API error: {r.status_code}", "body": r.text[:200]}

    except requests.exceptions.Timeout:
        return {"error": "PTS API timeout"}
    except requests.exceptions.RequestException as e:
        return {"error": f"PTS API request failed: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


# @app.route('/api/pts/jwt/status', methods=['GET'])
# @require_token
# def check_jwt_status():
#     user_key = _user_key()
#     jwt_path = AUTH_STORE_DIR / f"{user_key}_jwt.txt"
#     has_jwt = jwt_path.exists()

#     has_cookies = _load_cookies_for_user() is not None

#     jwt_preview = None
#     if has_jwt:
#         try:
#             t = jwt_path.read_text(encoding="utf-8").strip()
#             jwt_preview = (t[:20] + "...") if t else None
#         except Exception:
#             pass

#     return jsonify({
#         "has_jwt": has_jwt,
#         "has_cookies": bool(has_cookies),
#         "auth_available": bool(has_jwt or has_cookies),  # ← ВАЖНО: есть чем ходить в PTS
#         "user_key": user_key,
#         "jwt_preview": jwt_preview
#     })

# @app.route("/verify_token", methods=["POST"])
# def verify_token_route():
#     token = (request.get_json(silent=True) or {}).get("token")
#     user = verify_token(token)
#     if user:
#         return jsonify({"status": "success", "user": user})
#     return jsonify({"status": "error", "message": "Invalid or expired token"}), 401

@app.route("/verify_token", methods=["POST"])
def verify_token_route():
    """
    Локальная заглушка: считаем, что токен всегда валиден.
    Modulab здесь вообще не трогаем.
    """
    payload = request.get_json(silent=True) or {}
    token = (payload.get("token") or "").strip()

    user = {
        "id": "dev",
        "name": "Local Dev",
        "email": "",
        "raw_token": token[:10] + "..." if token else None,
    }

    return jsonify({"status": "success", "user": user}), 200


@app.route('/dev/verify', methods=['GET'])
@require_token
def dev_verify():
    return jsonify({"status":"ok", "user": get_current_user()}), 200

@app.route('/api/pts/jwt/status', methods=['GET'])
@require_token
def check_jwt_status():
    user_key = _user_key()
    jwt_path = AUTH_STORE_DIR / f"{user_key}_jwt.txt"
    has_jwt = jwt_path.exists()
    jar = _load_cookies_for_user()
    cookies_count = len(requests.utils.dict_from_cookiejar(jar)) if jar else 0
    return jsonify({
        "has_jwt": has_jwt,
        "cookies_count": cookies_count,
        "auth_available": bool(has_jwt or cookies_count > 0),
    })

def _extract_rows_flex(j: dict):
    """
    Пытается вынуть список документов и total из разных «форматов» ответа PTS:
    - {data: {data: [...], total: N}}
    - {data: [...]}
    - {data: {items: [...], total: N}}
    - {items: [...]}, {rows: [...]}, {list: [...]}, {result: [...]}
    - {data: [], total: N}
    """
    rows, total = [], 0
    if not isinstance(j, dict):
        return rows, total

    box = j.get("data")
    # 1) {data: {data:[...], total}}
    if isinstance(box, dict) and isinstance(box.get("data"), list):
        rows = box.get("data") or []
        total = box.get("total") or len(rows)
        return rows, total

    # 2) {data: [...]}
    if isinstance(box, list):
        rows = box
        total = j.get("total") or len(rows)
        return rows, total

    # 3) {data: {items:[...], total}}
    if isinstance(box, dict) and isinstance(box.get("items"), list):
        rows = box.get("items") or []
        total = box.get("total") or len(rows)
        return rows, total

    # 4) Топ-уровень: items/rows/list/result
    for k in ("items", "rows", "list", "result"):
        if isinstance(j.get(k), list):
            rows = j[k]
            total = j.get("total") or len(rows)
            return rows, total

    # 5) Топ-уровень {data:[...]}
    if isinstance(j.get("data"), list):
        rows = j["data"]
        total = j.get("total") or len(rows)
        return rows, total

    return rows, total

@app.route('/api/debug/auth_status', methods=['GET'])
@require_token
def debug_auth_status():
    """Отладочный эндпоинт для проверки аутентификации"""
    try:
        jar = _load_cookies_for_user()
        s = _session_with_auth()
        
        # Проверим доступность PTS
        test_url = f"{BASE}/api/compliencedocument/getList"
        test_payload = {
            "page": 1, "pageSize": 1,
            "filter": {"typeCode": "sbkts", "showDeleted": False, "search": ""}
        }
            
        r = s.post(test_url, json=test_payload, timeout=10, verify=VERIFY_TLS)
            
        return jsonify({
            "cookies_loaded": bool(jar),
            "cookie_count": len(requests.utils.dict_from_cookiejar(jar)) if jar else 0,
            "pts_api_status": r.status_code,
            "pts_response_type": r.headers.get('Content-Type', ''),
            "session_valid": r.status_code == 200
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _pts_search(num: str, only_active: bool = False, page_size: int = 20):
    s = _session_with_auth()
    variants = docnumber_variants(num)

    def _call(payload):
        r = s.post(PTS_LIST_URL, json=payload, timeout=20, verify=False)
        ct = (r.headers.get('Content-Type', '') or '').lower()
        if 'json' not in ct:
            raise RuntimeError("PTS returned non-JSON (вероятно, нет авторизации)")
        j = r.json() or {}
        rows, total = _extract_rows_flex(j)
        logger.warning("getList payload=%s -> http=%s; rows=%s; total=%s; keys=%s",
                    payload, r.status_code, len(rows), total, list(j.keys()))

        return rows

    # пытаемся разными формами фильтра, потому что у PTS это иногда плавает
    for include_status in ([True] if not only_active else [True, False]):
        for show_deleted in (False, True):
            for q in variants:
                base = {
                    "page": 1, "pageSize": page_size,
                    "sortField": [], "direction": [False]
                }
                filt = {
                    "typeCode": "sbkts",
                    "showDeleted": show_deleted,
                    "statusCode": "active" if (include_status and only_active) else None,
                }

                # 1) как у вас было (filter.search)
                rows = _call({**base, "filter": {**filt, "search": q}})
                if rows: 
                    return _shrink_rows(rows)

                # 2) по номеру документа
                rows = _call({**base, "filter": {**filt, "docNumber": q}})
                if rows:
                    return _shrink_rows(rows)

                # 3) иногда certificateNumber
                rows = _call({**base, "filter": {**filt, "certificateNumber": q}})
                if rows:
                    return _shrink_rows(rows)

                # 4) запасной «плоский» формат (вдруг бек ожидает query на корне)
                rows = _call({**base, "query": q})
                if rows:
                    return _shrink_rows(rows)

    return []


def _shrink_rows(rows):
    """Оставляем только то, что реально используем дальше."""
    out = []
    for it in rows:
        out.append({
            "id": it.get("id"),
            "docNumber": it.get("docNumber"),
            "brandName": it.get("brandName"),
            "type": it.get("type"),
            "categoryName": it.get("categoryName"),
            "statusCode": it.get("statusCode"),
            "statusName": it.get("statusName"),
            "docDate": it.get("docDate"),
            "createDate": it.get("createDate"),
            "vinNumbers": it.get("vinNumbers") or [],
            "authorOrgName": it.get("authorOrgName"),
        })
    return out

@app.route('/api/debug/pts/getList', methods=['POST'])
@require_token
def debug_pts_getlist():
    """Прокси в PTS getList: возвращаем ответ как есть, + короткое summary."""
    s = _session_with_auth()
    data = request.get_json(silent=True) or {}
    r = s.post(PTS_LIST_URL, json=data, timeout=20, verify=False)
    try:
        j = r.json()
    except Exception:
        return jsonify({
            "http": r.status_code,
            "content_type": r.headers.get("Content-Type"),
            "text": r.text[:1000]
        }), r.status_code

    rows, total = _extract_rows_flex(j)
    return jsonify({
        "http": r.status_code,
        "summary": {"rows": len(rows), "total": total, "top_keys": list(j.keys())},
        "raw": j
    }), 200



@app.route('/parse_site', methods=['POST'])
@require_token
def parse_site():
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({"error": "Не передан URL"}), 400

    # 1) Парсим поля как раньше
    fields = parse_vehicle_data_from_url(url)
    violation = check_violation_point5(fields)

    # 2) Внешние проверки по VIN (evak, eokno, customs.ru, keden)
    vin, evak_info, eokno_info, customs_ru, keden_kz = _external_checks_for_fields(fields)

    # 3) Дата оформления — наверх
    if "Дата оформления" in fields:
        fields = {"Дата оформления": fields.pop("Дата оформления"), **fields}

    # 4) docId + события документа
    doc_id = extract_guid_from_url(url)
    events = None
    if doc_id:
        try:
            events = get_document_events(doc_id)
        except Exception as e:
            logger.warning("get_document_events failed: %s", e)
            events = None

    # 5) Собираем ответ
    resp = {
        "fields": fields,
        "violation_point5": violation,
    }
    if vin:
        resp["vin"] = vin
    if evak_info is not None:
        resp["evak"] = evak_info
    if eokno_info is not None:
        resp["eokno"] = eokno_info
    if customs_ru is not None:
        resp["customs_ru"] = customs_ru
    if keden_kz is not None:
        resp["keden_kz"] = keden_kz
    if doc_id:
        resp["docId"] = doc_id
    if events is not None:
        resp["events"] = events

    return jsonify(resp)


@app.route('/parse_site_from_client', methods=['POST'])
@require_token
def parse_site_from_client():
    payload = request.get_json(silent=True) or {}
    raw = payload.get('raw')
    if raw is None:
        return jsonify({"error": "raw payload is required"}), 400

    import json as _json
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except ValueError:
            return jsonify({"error": "raw должен быть объектом или JSON-строкой"}), 400

    # 1) Поля карточки
    fields = parse_vehicle_data_from_raw(raw)
    violation = check_violation_point5(fields)

    # 2) Внешние проверки по VIN
    vin, evak_info, eokno_info, customs_ru, keden_kz = _external_checks_for_fields(fields)

    # 3) docId из raw + события
    doc_id = extract_doc_id_from_raw(raw)
    events = None
    if doc_id:
        try:
            events = get_document_events(doc_id)
        except Exception as e:
            logger.warning("get_document_events (from_client) failed: %s", e)
            events = None

    # 4) Дата оформления наверх
    if "Дата оформления" in fields:
        fields = {"Дата оформления": fields.pop("Дата оформления"), **fields}

    # 5) Ответ
    resp = {
        "fields": fields,
        "violation_point5": violation,
    }
    if vin:
        resp["vin"] = vin
    if evak_info is not None:
        resp["evak"] = evak_info
    if eokno_info is not None:
        resp["eokno"] = eokno_info
    if customs_ru is not None:
        resp["customs_ru"] = customs_ru
    if keden_kz is not None:
        resp["keden_kz"] = keden_kz
    if doc_id:
        resp["docId"] = doc_id
    if events is not None:
        resp["events"] = events

    return jsonify(resp)


@app.route('/api/pts/search', methods=['POST'])
@require_token
def pts_search():
    """Поиск через PTS API с JWT токеном"""
    try:
        data = request.json
        print(f"🔍 PTS search request: {data}")
        
        result = make_pts_request('/api/compliencedocument/search', data=data)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Error in pts_search: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/pts/events', methods=['POST'])
@require_token
def pts_events():
    data = request.get_json(silent=True) or {}
    doc_id = (data.get("docId") or "").strip()
    if not doc_id:
        return jsonify({"events": [], "error": "docId required"}), 400
    events = get_document_events(doc_id)  # уже использует корректный /api/compliencedocument/GetDocumentEvents?docId=
    return jsonify({"events": events}), 200

@app.route("/vin_status", methods=["POST"])
@permissive_token
def vin_status():
    payload = request.get_json(silent=True) or {}
    vin   = (payload.get("vin") or "").strip().upper()
    force = bool(payload.get("force"))
    if not is_valid_vin(vin):
        return jsonify({"ok": False, "status": "invalid_vin", "message": "VIN должен быть 17 символов (без I/O/Q)."}), 400

    res = check_vin_auto(vin)  # твоя новая функция
    # промапим в старую форму ответа
    if res is None:
        return jsonify({"ok": False, "status": "network_error", "message": "evak.online временно недоступен"}), 200
    if res.get("found"):
        d = res.get("data") or {}
        details = {
            "vin": d.get("VIN") or vin,
            "registered_at": d.get("Дата регистрации в системе") or "",
            "first_call_at": d.get("Первичное обращение") or "",
            "make_model": d.get("Модель") or "",
        }
        return jsonify({
            "ok": True,
            "status": "registered",
            "source": "evak.online",
            "checked_at": datetime.utcnow().isoformat()+"Z",
            "details": details,
            "debug": {"reason": "parsed_block"}
        }), 200
    else:
        return jsonify({
            "ok": True,
            "status": "not_registered",
            "source": "evak.online",
            "checked_at": datetime.utcnow().isoformat()+"Z",
            "details": {},
            "debug": {"reason": "not_found"}
        }), 200


@app.route('/api/pts/auth/clear', methods=['POST'])
@require_token
def clear_pts_auth():
    """Очистка PTS аутентификации"""
    user_id = request.user.get('id', 'unknown')
    
    if user_id in pts_auth_cache:
        del pts_auth_cache[user_id]
    
    session.pop('pts_jwt_token', None)
    session.pop('pts_user_info', None)
    
    return jsonify({"status": "success", "message": "PTS auth cleared"})

@app.route('/api/debug/auth', methods=['GET'])
@require_token
def debug_auth():
    """Диагностический endpoint для проверки аутентификации"""
    user_id = request.user.get('id', 'unknown')
    cached_auth = pts_auth_cache.get(user_id)
    
    debug_info = {
        "app_user": request.user,
        "pts_cached_auth": bool(cached_auth),
        "pts_session_token": bool(session.get('pts_jwt_token')),
        "pts_auth_cache_keys": list(pts_auth_cache.keys()),
        "session_keys": list(session.keys())
    }
    
    if cached_auth:
        debug_info["cached_auth_preview"] = {
            "token": cached_auth['pts_token'][:20] + "..." if cached_auth.get('pts_token') else None,
            "user_info": cached_auth.get('user_info'),
            "timestamp": cached_auth.get('timestamp')
        }
    
    return jsonify(debug_info)

@app.route('/check_session')
def check_session():
    token = request.headers.get('X-Parser-Token') or request.args.get('token')
    if not token:
        return jsonify({"authenticated": False}), 401
    user = verify_token(token)
    return (jsonify({"authenticated": True, "token": token, "user": user}), 200) if user else (jsonify({"authenticated": False}), 401)


@pts_bp.route("/api/pts/sbkts/fields", methods=["POST"])
@permissive_token
def api_pts_sbkts_fields():
    """
    Вход: { "num": "ТС KZ А-CN.2731.40599", "onlyActive": true? }
    Логика:
      1) ищем через GetList;
      2) если найден ровно 1 документ -> формируем URL карточки и парсим уже имеющимся парсером;
      3) возвращаем структуру, совместимую с /parse_site:
         { docId, fields, evak, violation_point5 }
    Если найдено 0 или >1 — возвращаем список совпадений.
    """
    if not ENABLE_NUMBER_FEATURES:
        return jsonify({
            "error": "Поиск по номеру СБКТС временно отключён. "
                     "Используйте /parse_site с полной ссылкой на карточку."
        }), 410  # 410 Gone — явный сигнал, что фича выключена

    data = request.get_json(silent=True) or {}
    num = (data.get("num") or "").strip()
    only_active = bool(data.get("onlyActive", False))
    if not num:
        return jsonify({"error": "Не передан номер документа"}), 400

    try:
        rows = _pts_search(num, only_active=only_active)
        if not rows:
            return jsonify({"matches": [], "count": 0, "error": "По данному номеру СБКТС ничего не найдено"}), 200
        if len(rows) > 1:
            # поможем фронту выбрать конкретный docId
            brief = [
                {
                    "id": r["id"],
                    "docNumber": r["docNumber"],
                    "brandName": r["brandName"],
                    "type": r["type"],
                    "categoryName": r["categoryName"],
                    "statusCode": r["statusCode"],
                    "docDate": r["docDate"]
                } for r in rows
            ]
            return jsonify({"error": "Найдено несколько документов, уточните номер", "matches": brief, "count": len(brief)}), 200

        # Ровно один — парсим карточку как раньше (чтобы получить те же 'fields')
           # Ровно один — смотрим статус и парсим карточку
        doc = rows[0]
        doc_id = doc["id"]
        raw_status = (doc.get("statusCode") or "").strip().lower()
        status_label = _status_label(raw_status, doc.get("statusName"))

        # если пришла явная просьба, читаем её; по умолчанию True
        # review_only = bool((request.get_json(silent=True) or {}).get("reviewOnly", True))
        # if review_only and not _is_consideration(raw_status, status_label):
        #     return jsonify({
        #         "error": "Документ не в статусе «На рассмотрении» — такие заявки мы пропускаем.",
        #         "docId": doc_id,
        #         "statusCode": doc.get("statusCode"),
        #         "statusLabel": status_label
        #     }), 200

        review_only = bool((request.get_json(silent=True) or {}).get("reviewOnly", False))
        
        status_label = _status_label(raw_status, doc.get("statusName") or doc.get("statusCode"))

        # Если отклонён/закрыт — вернём предупреждение (но не будем прятать данные)
        warning = None
        if raw_status in ("rejected", "closed", "canceled", "cancelled"):
            warning = f"Документ найден, но его статус: {status_label}."

        card_url = f"https://pts.gov.kz/compliencedocument/sbkts/{doc_id}"

        # РЕЮЗ старого парсера:
        result = parse_vehicle_data_from_url(card_url)

        # проверка нарушения п.5 — как в /parse_site
        violation = check_violation_point5(result)

        # EVAK / EOKNO / CUSTOMS / KEDEN по VIN (параллельно, не блокирует парсинг)
        evak_info  = None
        eokno_info = None
        customs_ru = None
        keden_kz   = None

        vin = extract_vin_from_fields(result)
        if vin:
            evak_info, eokno_info, customs_ru, keden_kz = _run_external_checks_parallel(vin)

        events = get_document_events(doc_id)

        if "Дата оформления" in result:
            fields_out = {"Дата оформления": result.pop("Дата оформления"), **result}
        else:
            fields_out = result

        return jsonify({
            "docId": doc_id,
            "fields": fields_out,
            "violation_point5": violation,
            "evak": evak_info,
            "eokno": eokno_info,
            "customs_ru": customs_ru,
            "keden_kz": keden_kz,
            "statusCode": doc.get("statusCode"),
            "statusLabel": status_label,
            "events": events,
            "warning": warning
        }), 200


    except RuntimeError as e:
        return jsonify({"error": str(e)}), 401   # не авторизованы в PTS
    except requests.HTTPError as e:
        return jsonify({"error": f"HTTP ошибка при обращении к PTS: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Не удалось получить поля по номеру: {e}"}), 500

def _looks_like_jwt(tok: str) -> bool:
    if not tok or tok.count('.') != 2: 
        return False
    h, p, s = tok.split('.')
    # подправляем padding
    def b64d(x): 
        x += "=" * (-len(x) % 4)
        return json.loads(base64.urlsafe_b64decode(x.encode('utf-8')).decode('utf-8'))
    try:
        header = b64d(h); payload = b64d(p)
    except Exception:
        return False
    # необязательные, но полезные проверки
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return False
    # если у ПТС есть iss/aud — можно проверить
    # if 'iss' in payload and 'pts.gov.kz' not in str(payload['iss']).lower(): return False
    return True

@app.route('/my_results', methods=['GET'])
@require_token
def my_results():
    token = request.headers.get('X-Parser-Token') or request.args.get('token') or ''
    upstream_url = f"{UPSTREAM_BASE}/api/parsed/my"
    try:
        r = requests.get(
            upstream_url,
            headers={"X-Parser-Token": token, "Accept": "application/json"},
            params={"token": token},
            timeout=10,
        )
        if r.status_code >= 400:
            return jsonify({
                "ok": False,
                "code": r.status_code,
                "tokenPrefix": token[:8],
                "upstream": upstream_url,
                "body": (r.text or None),
            }), r.status_code

        if not (r.text or "").strip():
            return jsonify([]), 200

        if (r.headers.get('Content-Type','')).lower().startswith('application/json'):
            return (r.text, r.status_code, {'Content-Type': 'application/json'})

        return jsonify({"ok": True, "raw": r.text}), 200

    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route('/save_result', methods=['POST'])
@require_token
def save_result():
    data = request.get_json(silent=True) or {}
    user = getattr(request, "user", {}) or {}
    user_id = user.get("userId") or user.get("id")
    if not user_id:
        return jsonify({"success": False, "error": "Пользователь не авторизован (нет userId)"}), 401

    parser_token = request.headers.get('X-Parser-Token', '')

    try:
        r = requests.post(
            f"{UPSTREAM_BASE}/api/parsed/add",
            headers={
                "X-Parser-Token": parser_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "sourceType": data.get("sourceType", "PTS"),
                "site": data.get("site", {}),
                "pdf": data.get("pdf", {}),
                "errors": data.get("errors", {}),
                "userComment": data.get("userComment", ""),
                "userId": user_id
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            return jsonify({"success": True}), 200
        return jsonify({"success": False, "error": (r.text or f"Upstream responded {r.status_code}"), "code": r.status_code}), r.status_code
    except requests.RequestException as e:
        return jsonify({"success": False, "error": str(e)}), 502


@app.route('/api/pts/auth', methods=['POST'])
@require_token
def receive_pts_auth():
    data = request.json or {}
    pts_token = (data.get('pts_token') or '').strip()
    user_info = data.get('user_info', {}) or {}

    if not _looks_like_jwt(pts_token):
        return jsonify({"error": "Bad pts_token: expected JWT from pts.gov.kz"}), 400

    user_id = request.user.get('id', 'unknown')
    pts_auth_cache[user_id] = {
        'pts_token': pts_token,
        'user_info': user_info,
        'timestamp': datetime.now().isoformat()
    }
    session['pts_jwt_token'] = pts_token
    session['pts_user_info'] = user_info
    return jsonify({
        "status": "success",
        "message": "PTS token stored",
        "user": user_info.get('name', 'Unknown'),
        "token_preview": pts_token[:20] + "..."
    })

# @app.route('/api/pts/auth', methods=['POST'])
# @require_token
# def receive_pts_auth():
#     """Принимаем PTS токен и данные пользователя от расширения"""
#     try:
#         data = request.json
#         if not data:
#             return jsonify({"error": "No JSON data provided"}), 400
        
#         pts_token = data.get('pts_token')
#         user_info = data.get('user_info', {})
        
#         if not pts_token:
#             return jsonify({"error": "PTS token required"}), 400
        
#         # Сохраняем в кеше (временное решение)
#         user_id = request.user.get('id', 'unknown')
#         pts_auth_cache[user_id] = {
#             'pts_token': pts_token,
#             'user_info': user_info,
#             'timestamp': datetime.now().isoformat()
#         }
        
#         print(f"✅ PTS Token received for user {user_id}: {pts_token[:20]}...")
#         print(f"✅ User info: {user_info}")
        
#         # Также сохраняем в сессии для текущего запроса
#         session['pts_jwt_token'] = pts_token
#         session['pts_user_info'] = user_info
        
#         return jsonify({
#             "status": "success", 
#             "message": "PTS token stored successfully",
#             "user": user_info.get('name', 'Unknown'),
#             "token_preview": pts_token[:20] + "..."
#         })
        
#     except Exception as e:
#         print(f"❌ Error in receive_pts_auth: {e}")
#         return jsonify({"error": str(e)}), 500

@app.route('/api/pts/auth/status', methods=['GET'])
@require_token
def check_pts_auth_status():
    """Проверяем статус PTS аутентификации"""
    user_id = request.user.get('id', 'unknown')
    cached_auth = pts_auth_cache.get(user_id)

    status = {
        "authenticated": bool(cached_auth),
        "has_token": bool(session.get('pts_jwt_token')),
        "user": cached_auth.get('user_info', {}) if cached_auth else {},
        "token_preview": cached_auth['pts_token'][:20] + "..." if cached_auth and cached_auth.get('pts_token') else None,
        "timestamp": cached_auth.get('timestamp') if cached_auth else None,
    }
    
    status["is_jwt_like"] = _looks_like_jwt((cached_auth or {}).get('pts_token', ''))

    return jsonify(status)

def _request_token() -> str:
    t = (request.headers.get("X-Parser-Token") or "").strip()
    if not t:
        raise Unauthorized("Missing X-Parser-Token")
    return t

def _client_ip() -> str:
    xf = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    ip = xf or request.remote_addr or ""
    if ip in ("::1", "0:0:0:0:0:0:0:1"):
        ip = "127.0.0.1"
    return ip


def _user_key() -> str:
    t = _request_token()
    ip = _client_ip() if BIND_TO_IP else ""
    raw = f"{t}|{ip}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _cookie_path() -> Path:
    return AUTH_STORE_DIR / f"{_user_key()}_cookies.json"

def _load_cookies_for_user():
    p = _cookie_path()
    # 1) есть новый персональный файл — читаем его
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return requests.utils.cookiejar_from_dict(data)
        except Exception:
            pass
    # 2) миграция со старого глобального кэша (если ещё живёт)
    try:
        tok, ck = load_auth_from_cache()
        if ck:
            jar = requests.utils.cookiejar_from_dict(ck)
            _save_cookies_for_user(jar)
            return jar
    except Exception:
        pass
    return None

def _save_cookies_for_user(jar_or_dict):
    p = _cookie_path()
    tmp = str(p) + ".tmp"
    if isinstance(jar_or_dict, dict):
        data = jar_or_dict
    else:
        data = requests.utils.dict_from_cookiejar(jar_or_dict)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


@pts_bp.route("/api/pts/by_number_fast", methods=["POST"])
@permissive_token
def api_pts_by_number_fast():
    """
    Быстрый режим: ни одного захода на HTML — только JSON-эндпоинты.
    Вход: { "num": "...", "onlyActive": true? }
    Выход (если найден ровно один): { docId, fields, evak, violation_point5, statusCode, statusLabel }
           (если 0 или >1): { error, matches[], count }
    """
    if not ENABLE_NUMBER_FEATURES:
        return jsonify({"error": "Поиск по номеру временно отключён"}), 410

    data = request.get_json(silent=True) or {}
    num = (data.get("num") or data.get("query") or "").strip()
    only_active = bool(data.get("onlyActive", False))
    if not num:
        return jsonify({"error":"Не передан номер"}), 400

    try:
        rows = _pts_search(num, only_active=only_active)  # ← твоя уже готовая функция
    except requests.RequestException as e:
        return jsonify({"error": f"HTTP: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Ошибка: {e}"}), 500

    if not rows:
        return jsonify({"matches": [], "count": 0, "error": "Ничего не найдено"}), 200
    if len(rows) > 1:
        brief = [{
            "id": r["id"],
            "docNumber": r["docNumber"],
            "brandName": r["brandName"],
            "type": r["type"],
            "categoryName": r["categoryName"],
            "statusCode": r["statusCode"],
            "docDate": r["docDate"],
        } for r in rows]
        return jsonify({"error":"Найдено несколько документов, уточните номер", "matches": brief, "count": len(brief)}), 200

    doc = rows[0]
    doc_id = doc["id"]
    raw_status = (doc.get("statusCode") or "").strip().lower()
    status_label = _status_label(raw_status, doc.get("statusName") or doc.get("statusCode"))
    # JSON-детали вместо HTML-парсера:
    try:
        summary = get_doc_summary(doc_id) or {}
        details = get_details(doc_id) or {}
        fields  = compose_fields_from_api(summary, details)
    except requests.RequestException as e:
        return jsonify({"error": f"HTTP при получении данных по docId: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Ошибка обработки JSON: {e}"}), 500

    # проверки и внешние сервисы
    violation = check_violation_point5(fields)
    evak_info   = None
    eokno_info  = None
    customs_ru  = None
    keden_kz    = None

    vin = extract_vin_from_fields(fields)
    events = get_document_events(doc_id)

    if vin:
        evak_info, eokno_info, customs_ru, keden_kz = _run_external_checks_parallel(vin)

    if "Дата оформления" in fields:
        fields = {"Дата оформления": fields.pop("Дата оформления"), **fields}

    return jsonify({
        "docId": doc_id,
        "fields": fields,
        "violation_point5": violation,
        "evak": evak_info,
        "eokno": eokno_info,
        "customs_ru": customs_ru,
        "keden_kz": keden_kz,
        "statusCode": doc.get("statusCode"),
        "events": events,
        "statusLabel": status_label
    }), 200




# ==== МАППЕР JSON → твои поля =================================================
def _pick(d: dict, *names, default=""):
    for n in names:
        if not n: continue
        if isinstance(d, dict) and n in d and d[n] not in (None, ""):
            return d[n]
    return default

def compose_fields_from_api(summary: dict, details: dict) -> dict:
    gen = _first(details.get("general") or {})
    eng = _first(details.get("engine") or {})
    dims= _first(details.get("dimensions") or {})
    mass= _first(details.get("mass") or {}) or _first(details.get("weight") or {})
    tyres=_first(details.get("tyres") or {})
    plat = _first(details.get("platform") or {})

    out = {}

    # базовые
    out["МАРКА"] = _pick(summary, "brandName", default="") or _pick(gen, "brand","marka","brandName","Марка", default="")
    out["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] = _pick(gen, "commercialName","КоммерческоеНаименование","commercial","modelName","tradeName", default="")
    out["ТИП"] = _pick(summary, "type", default="") or _pick(gen, "type","Тип", default="")
    out["КАТЕГОРИЯ"] = _pick(summary, "categoryName","category","Категория", default="")
    out["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = _pick(gen,"vin","VIN","Vin", default="") or _pick(summary,"vin","VIN","Vin", default="")
    out["ГОД ВЫПУСКА"] = _pick(gen,"manufactureYear","year","ГодВыпуска", default="")

    # размеры
    out["Габаритные размеры, мм"] = {
        "длина": _pick(dims,"length","Length","Длина", default=""),
        "ширина": _pick(dims,"width","Width","Ширина", default=""),
        "высота": _pick(dims,"height","Height","Высота", default=""),
    }

    # массы
    out["Масса транспортного средства в снаряженном состоянии, кг"] = _pick(mass,"curbWeight","massCurb","СнаряженнаяМасса", default="")
    out["Технически допустимая максимальная масса транспортного средства, кг"] = _pick(mass,"maxPermissibleMass","ttmm","MaxMass","ТехническиДопустимаяМаксимальнаяМасса", default="")

    # двигатель
    out["Двигатель внутреннего сгорания (марка, тип)"] = _pick(eng,"model","engineModel","МаркаТип","brandModel", default="")
    out["- рабочий объем цилиндров, см3"] = _pick(eng,"displacement","volume","рабочийОбъем", default="")
    out["- максимальная мощность, кВт (мин.-1)"] = _pick(eng,"powerKw","maxPowerKw","мощность", default="")
    out["Топливо"] = _pick(eng,"fuel","Fuel","Топливо", default="")

    # шины
    tyres_front = _pick(tyres,"front","Передние","frontTyres", default="")
    tyres_rear  = _pick(tyres,"rear","Задние","rearTyres", default="")
    out["Шины (типоразмер)"] = {"передние": tyres_front, "задние": tyres_rear}

    # платформы/шасси (если есть)
    out["ШАССИ"] = _pick(plat,"chassis","Шасси","platform","Platform", default="")

    # дата
    doc_date = (_pick(summary,"docDate","createDate","DocDate","ДатаДокумента", default="") or "").split("T")[0]
    if doc_date:
        out["Дата оформления"] = doc_date

    return out



# --- eokno: константы и HTML/XML парсеры ---
EOKNO_URL = "https://eokno.gov.kz/vin/search.xhtml"
EOKNO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)



def _fingerprint_decision(doc_id: str, status_code: str, message: str) -> str:
    raw = f"{doc_id}|{status_code}|{message}".encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()

def _load_json_safe(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def _save_json_safe(path: str, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _load_sent():
    return _load_json_safe(SENT_PATH, {})

def _save_sent(sent):
    _save_json_safe(SENT_PATH, sent)

def _mark_sent(doc_id: str, status_code: str, message: str, api_resp):
    with SENT_LOCK:
        sent = _load_sent()
        sent[doc_id] = {
            "status_code": status_code,
            "message": message,
            "applied_at": time.time(),
            "api": api_resp,
        }
        _save_sent(sent)

def _get_sent_for(doc_id: str):
    sent = _load_sent()
    return sent.get(doc_id)


from bs4 import BeautifulSoup

def _eokno_extract_viewstate(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    vs = soup.find("input", {"name": "javax.faces.ViewState"})
    if vs and vs.get("value"):
        return vs["value"]
    vs_by_id = soup.find("input", id=re.compile(r".*javax\.faces\.ViewState.*"))
    if vs_by_id and vs_by_id.get("value"):
        return vs_by_id["value"]
    return None

def _eokno_parse_from_full(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out = {"found": False, "source": "full_html"}
    box = soup.find(id="vinSearchResult")
    if not box:
        return out

    def tx(i): 
        n = box.find(id=i)
        return n.get_text(strip=True) if n else ""

    out.update({
        "searchDate":               tx("searchDate"),
        "goodsDeclarationNumber":   tx("goodsDeclarationNumber"),
        "bodyIssuedGoodsDeclaration": tx("bodyIssuedGoodsDeclaration"),
        "description":              tx("description"),
    })
    out["found"] = bool(out["goodsDeclarationNumber"] or out["description"])
    return out

def _eokno_parse_from_partial(xml_text: str) -> dict:
    soup_xml = BeautifulSoup(xml_text, "xml")
    update = soup_xml.find("update", {"id": "vinSearch"}) or soup_xml.find("update", {"id": "vinSearchResult"})
    out = {"found": False, "source": "partial_xml"}
    if not update:
        return out

    fragment_html = update.text or ""
    frag = BeautifulSoup(fragment_html, "html.parser")
    container = frag.find(id="vinSearchResult") or frag

    def tx(i):
        n = container.find(id=i)
        return n.get_text(strip=True) if n else ""

    out.update({
        "searchDate":               tx("searchDate"),
        "goodsDeclarationNumber":   tx("goodsDeclarationNumber"),
        "bodyIssuedGoodsDeclaration": tx("bodyIssuedGoodsDeclaration"),
        "description":              tx("description"),
    })
    out["found"] = bool(out["goodsDeclarationNumber"] or out["description"])
    return out

_EOKNO_BLOCKED_UNTIL: float = 0.0
_EOKNO_BLOCK_LOCK = threading.Lock()
_EOKNO_CIRCUIT_COOLDOWN = 1800  # 30 минут


def _check_eokno_safe(vin: str) -> dict:
    """Обёртка с circuit breaker: при таймауте блокирует eokno на 30 мин."""
    global _EOKNO_BLOCKED_UNTIL
    now = time.time()
    with _EOKNO_BLOCK_LOCK:
        if now < _EOKNO_BLOCKED_UNTIL:
            remaining = max(1, int((_EOKNO_BLOCKED_UNTIL - now) // 60))
            return {
                "found": False,
                "error": f"eokno.gov.kz временно недоступен — следующая попытка через ~{remaining} мин.",
                "source": "eokno.gov.kz",
            }
    try:
        return _eokno_query_by_vin(vin)
    except requests.exceptions.Timeout:
        with _EOKNO_BLOCK_LOCK:
            _EOKNO_BLOCKED_UNTIL = time.time() + _EOKNO_CIRCUIT_COOLDOWN
        logger.warning("eokno circuit breaker активирован на %d мин", _EOKNO_CIRCUIT_COOLDOWN // 60)
        return {
            "found": False,
            "error": "eokno.gov.kz недоступен — сервер не отвечает (таймаут).",
            "source": "eokno.gov.kz",
        }


def _eokno_query_by_vin(vin: str, timeout: int = 8) -> dict:
    s = requests.Session()
    s.headers.update({"User-Agent": EOKNO_UA})

    # 1) получаем страницу и ViewState
    r1 = s.get(EOKNO_URL, timeout=timeout, verify=False)
    r1.raise_for_status()
    viewstate = _eokno_extract_viewstate(r1.text)
    if not viewstate:
        return {"found": False, "error": "Не удалось получить ViewState", "step": "GET"}

    # 2) JSF partial-ajax запрос
    ajax_payload = {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "vinSearchForm:j_idt1791",
        "javax.faces.partial.execute": "vinSearchForm:j_idt1791",
        "javax.faces.partial.render": "vinSearch vinSearchResult",
        "vinSearchForm": "vinSearchForm",
        "vinSearchForm:vinSearchInputText": vin,
        "javax.faces.ViewState": viewstate,
    }
    ajax_headers = {
        "User-Agent": EOKNO_UA,
        "Referer": EOKNO_URL,
        "Faces-Request": "partial/ajax",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    r2 = s.post(EOKNO_URL, data=ajax_payload, headers=ajax_headers, timeout=timeout, verify=False)
    r2.raise_for_status()

    if "<partial-response" in r2.text:
        p = _eokno_parse_from_partial(r2.text)
        if p.get("found"):
            p["vin"] = vin
            return p

    # 3) fallback — полная перерисовка формы
    full_payload = {
        "vinSearchForm": "vinSearchForm",
        "vinSearchForm:vinSearchInputText": vin,
        "vinSearchForm:j_idt1791": "vinSearchForm:j_idt1791",
        "javax.faces.ViewState": viewstate,
    }
    r3 = s.post(EOKNO_URL, data=full_payload, headers={"User-Agent": EOKNO_UA, "Referer": EOKNO_URL}, timeout=timeout, verify=False)
    r3.raise_for_status()
    p2 = _eokno_parse_from_full(r3.text)
    p2["vin"] = vin
    return p2

@eokno_bp.route('/eokno/check', methods=['POST'])
@permissive_token
def eokno_check():
    """
    Вход: { vin: "LA..." } — если не передан, вернём 400.
    Выход: { found, vin, data|error } — компактно и дружелюбно к фронту.
    """
    data = request.get_json(silent=True) or {}
    vin = (data.get("vin") or "").strip().upper()

    if not is_valid_vin(vin):
        return jsonify({"found": False, "error": "Некорректный VIN. Должно быть 17 символов A-Z/0-9 (без I,O,Q)."}), 400

    try:
        res = _check_eokno_safe(vin)
    except requests.exceptions.SSLError as e:
        return jsonify({"found": False, "vin": vin, "error": f"TLS/сертификат: {e}"}), 502
    except requests.RequestException as e:
        return jsonify({"found": False, "vin": vin, "error": f"HTTP: {e}"}), 502
    except Exception as e:
        return jsonify({"found": False, "vin": vin, "error": f"Ошибка: {e}"}), 500

    if res.get("error") and not res.get("found"):
        return jsonify({"found": False, "vin": vin, "error": res["error"], "source": res.get("source", "eokno.gov.kz")}), 200

    if not res.get("found"):
        # Нормальный ответ «не найдено»
        return jsonify({
            "found": False,
            "vin": vin,
            "message": res.get("error") or "Данные по VIN не найдены на eokno.gov.kz.",
            "source": res.get("source") or "unknown"
        }), 200

    # Отдаём только нужное фронту
    return jsonify({
        "found": True,
        "vin": vin,
        "data": {
            "Дата поиска": res.get("searchDate") or "",
            "№ таможенной декларации": res.get("goodsDeclarationNumber") or "",
            "Орган (ДГД)": res.get("bodyIssuedGoodsDeclaration") or "",
            "Описание ТС": res.get("description") or "",
        },
        "source": res.get("source") or "unknown"
    }), 200



PHOTO_CACHE = Path("photo_cache")
PHOTO_CACHE.mkdir(exist_ok=True)
PHOTO_TTL_SEC = 60*60*6  # чистим старше 6 часов

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()

def _janitor_photos():
    while True:
        try:
            now = time.time()
            for p in PHOTO_CACHE.glob("*"):
                try:
                    if p.is_file() and now - p.stat().st_mtime > PHOTO_TTL_SEC:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(300)

threading.Thread(target=_janitor_photos, daemon=True).start()

VIN_RE = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$', re.I)
GUID_RE = re.compile(r'[0-9a-fA-F-]{36}')

QUEUE_PATH = "decisions_queue.json"

def is_valid_vin(vin: str) -> bool:
    return bool(VIN_RE.match((vin or '').strip().upper()))


def extract_guid_from_url(url: str) -> str | None:
    if not url: 
        return None
    m = GUID_RE.search(url)
    return m.group(0) if m else None

def extract_doc_id_from_raw(raw):
    """
    Пытается найти docId/id, похожий на GUID, внутри raw структуры,
    которую присылает расширение.
    """
    if not isinstance(raw, dict):
        return None

    # 1) Явные поля docId / id
    for key in ("docId", "DocId", "id", "Id", "ID"):
        v = raw.get(key)
        if isinstance(v, str):
            m = GUID_RE.search(v)
            if m:
                return m.group(0)

    # 2) Типичная структура {base:{data{data{...}}}} / {details:{data{data{...}}}}
    def from_obj(obj):
        if not isinstance(obj, dict):
            return None
        data = obj.get("data") or {}
        inner = data.get("data")
        if isinstance(inner, dict):
            card = inner
        elif isinstance(inner, list) and inner:
            card = inner[0]
        elif isinstance(data, list) and data:
            card = data[0]
        else:
            card = data
        for k in ("docId", "id", "Id", "ID"):
            v = card.get(k)
            if isinstance(v, str):
                m = GUID_RE.search(v)
                if m:
                    return m.group(0)
        return None

    for key in ("details", "base"):
        if key in raw:
            v = from_obj(raw[key])
            if v:
                return v

    # 3) Глубокий рекурсивный поиск
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.lower() in ("docid", "id"):
                    if isinstance(v, str):
                        m = GUID_RE.search(v)
                        if m:
                            return m.group(0)
                res = walk(v)
                if res:
                    return res
        elif isinstance(x, list):
            for v in x:
                res = walk(v)
                if res:
                    return res
        return None

    return walk(raw)


def extract_vin_from_fields(fields: dict) -> str | None:
    # 1) по известным ключам
    for key in [
        "ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)",
        "Идентификационный номер (VIN)",
        "VIN", "Vin"
    ]:
        v = (fields.get(key) or "").strip().upper()
        if is_valid_vin(v):
            return v
    # 2) в значениях (на всякий случай)
    joined = " ".join(
        (str(v) for v in fields.values() if isinstance(v, str))
    ).upper()
    m = re.search(r'[A-HJ-NPR-Z0-9]{17}', joined)
    if m and is_valid_vin(m.group(0)):
        return m.group(0)
    return None

def _run_external_checks_parallel(vin: str):
    """
    Запускает 4 внешние VIN-проверки параллельно.
    Возвращает (evak_info, eokno_info, customs_ru, keden_kz).
    Не трогает основной парсинг TechReg / ePTS.
    """
    def _do_evak():
        return check_vin_auto(vin)

    def _do_eokno():
        eokno_res = _check_eokno_safe(vin)
        if not eokno_res:
            return None
        if eokno_res.get("error") and not eokno_res.get("found"):
            return {"found": False, "vin": vin, "error": eokno_res["error"], "source": eokno_res.get("source", "eokno.gov.kz")}
        return {
            "found": bool(eokno_res.get("found")),
            "vin": vin,
            "data": {
                "Дата поиска": eokno_res.get("searchDate") or "",
                "№ таможенной декларации": eokno_res.get("goodsDeclarationNumber") or "",
                "Орган (ДГД)": eokno_res.get("bodyIssuedGoodsDeclaration") or "",
                "Описание ТС": eokno_res.get("description") or "",
            },
            "source": eokno_res.get("source") or "eokno.gov.kz",
        }

    def _do_customs():
        return check_customs_ru(vin)

    def _do_keden():
        return check_keden_kz(vin)

    results = {"evak": None, "eokno": None, "customs": None, "keden": None}
    tasks = {"evak": _do_evak, "eokno": _do_eokno, "customs": _do_customs, "keden": _do_keden}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.warning("external check '%s' failed for VIN %s: %s", name, vin, e)

    return results["evak"], results["eokno"], results["customs"], results["keden"]


def _external_checks_for_fields(fields: dict):
    """
    Единая точка для внешних проверок по VIN.
    Возвращает: (vin, evak_info, eokno_info, customs_ru, keden_kz)
    """
    vin = extract_vin_from_fields(fields)
    if not vin:
        return None, None, None, None, None
    evak_info, eokno_info, customs_ru, keden_kz = _run_external_checks_parallel(vin)
    return vin, evak_info, eokno_info, customs_ru, keden_kz


# --- canonical: keep only this version ---
def _ensure_orig_bytes_by_item(item):
    """
    На вход item из /photos/list.
    Возвращает (bytes, ext, name_hint) или (None, None, None).
    """
    try:
        if item.get("kind") == "data" and item.get("handle"):
            raw = _orig_path(item["handle"]).read_bytes()
            import imghdr
            t = imghdr.what(None, h=raw[:32]) or "jpg"
            ext = ".webp" if t == "webp" else f".{t}"
            return raw, ext, "data"

        if item.get("kind") == "url":
            key = item.get("key")
            if not key:
                return None, None, None
            mapped_url, saved_ref = _read_url_and_ref(key)
            if not mapped_url:
                return None, None, None

            orig = _orig_path(key)
            if not orig.exists():
                s = _session_with_auth()
                hdrs = {
                    "Referer": saved_ref or "https://pts.gov.kz/",
                    "Origin":  "https://pts.gov.kz",
                    "Accept":  "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "User-Agent": "Mozilla/5.0",
                }
                rr = s.get(mapped_url, timeout=30, verify=False, headers=hdrs, allow_redirects=True)
                raw = rr.content if rr.status_code == 200 and rr.content else _fallback_fetch_image(mapped_url, saved_ref)
                if not raw:
                    return None, None, None
                orig.write_bytes(raw)
            else:
                raw = orig.read_bytes()

            import imghdr
            t = imghdr.what(None, h=raw[:32]) or "jpg"
            ext = ".webp" if t == "webp" else f".{t}"
            return raw, ext, "url"

    except Exception:
        return None, None, None

    return None, None, None


# @app.post("/photos/zip", endpoint="photos_zip")
# @require_token
# def photos_zip():
#     """
#     Вход:
#       { docId?: str, items?: [...] }
#     Если items не переданы — соберём их локально без HTTP-вызовов.
#     """
#     data = request.get_json(silent=True) or {}
#     doc_id = (data.get("docId") or "").strip()
#     items  = data.get("items")

#     try:
#         if not items:
#             if not doc_id:
#                 return jsonify({"error": "Передайте docId или items[]"}), 400
#             # локальный сбор без внешних запросов к нашему же REST
#             items = _collect_photo_items(None, doc_id)

#         if not items:
#             return jsonify({"error": "Фото не найдены"}), 200

#         import tempfile
#         from zipfile import ZipFile, ZIP_DEFLATED

#         tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
#         tmp.close()

#         added = 0
#         used_names = set()
#         with ZipFile(tmp.name, "w", compression=ZIP_DEFLATED) as z:
#             for i, it in enumerate(items, 1):
#                 raw, ext, hint = _ensure_orig_bytes_by_item(it)
#                 if not raw:
#                     continue
#                 base = f"{i:03d}_{hint}"
#                 name = base + ext
#                 k = 2
#                 while name in used_names:
#                     name = f"{base}_{k}{ext}"; k += 1
#                 used_names.add(name)
#                 z.writestr(name, raw)
#                 added += 1

#         if added == 0:
#             os.unlink(tmp.name)
#             return jsonify({"error": "Не удалось скачать ни одного файла"}), 200

#         dl_name = f"photos_{doc_id}.zip" if doc_id else "photos.zip"
#         return send_file(tmp.name, as_attachment=True, download_name=dl_name, mimetype="application/zip")

#     except Exception as e:
#         return jsonify({"error": f"ZIP error: {e}"}), 502

def _collect_photo_items(url: str | None, doc_id: str | None) -> list[dict]:
    from urllib.parse import urljoin
    s = _session_with_auth()
    items, seen_url, seen_handle, idx = [], set(), set(), 0

    def _add_url(u: str, referer: str):
        nonlocal idx
        key = _save_url_mapping(u, referer=referer)
        if key in seen_url: 
            return
        seen_url.add(key)
        items.append({"id": idx, "kind": "url", "key": key})
        idx += 1

    def _add_data(raw: bytes, mime: str):
        nonlocal idx
        h = hashlib.sha1(raw).hexdigest()
        if h in seen_handle:
            return
        seen_handle.add(h)
        _orig_path(h).write_bytes(raw)
        items.append({"id": idx, "kind": "data", "mime": mime, "handle": h})
        idx += 1

    # 0) Карточка
    if not url and doc_id:
        url = f"{BASE}/compliencedocument/sbkts/{doc_id}"
    if not url:
        return items

    # 1) СНАЧАЛА пробуем официальный JSON эндпоинт галереи
    if doc_id:
        ep = f"{BASE}/api/compliencedocument/getGeneralViewList?docId={doc_id}"
        try:
            rr = s.get(ep, timeout=20, verify=False)
            if rr.ok and "application/json" in rr.headers.get("Content-Type", ""):
                j = rr.json() or {}
                # Очень разная форма у ответа — пройдёмся рекурсивно и заберём любые фото
                def walk(x):
                    if isinstance(x, dict):
                        for v in x.values(): 
                            walk(v)
                    elif isinstance(x, list):
                        for v in x: 
                            walk(v)
                    elif isinstance(x, str):
                        val = x.strip()
                        # data:image;base64,...
                        if val.startswith("data:image/") and ";base64," in val:
                            meta, b64 = val.split(",", 1)
                            mime = meta.split(":",1)[1].split(";")[0]
                            try:
                                _add_data(base64.b64decode(b64), mime or "image/jpeg")
                            except Exception:
                                pass
                        else:
                            # ссылки на файлы (jpg/png/webp) или сервисные ручки скачивания
                            if re.search(r'\.(jpe?g|png|webp)(\?.*)?$', val, re.I) or "GetFile" in val or "File" in val:
                                absu = urljoin(BASE + "/", val)
                                _add_url(absu, referer=url)
                walk(j)
                if items:       # если из API что-то получилось, считаем что этого достаточно
                    return items
        except Exception:
            pass

    # 2) Если API не дал фото — аккуратный HTML-парсинг ТОЛЬКО в секции «Общий вид…»
    try:
        r = s.get(url, timeout=25, verify=False)
        r.raise_for_status()
    except Exception:
        return items

    base_url = r.url
    soup = BeautifulSoup(r.text, "html.parser")

    # Находим ближайший контейнер к заголовку "Общий вид транспортного средства"
    header_node = soup.find(string=re.compile(r"Общий\s+вид\s+транспортного\s+средства", re.I))
    section = header_node.find_parent() if header_node else soup  # fallback — вся страница (нежелательно)

    def is_junk(src: str) -> bool:
        src_l = src.lower()
        # отсекаем служебные/декоративные картинки интерфейса
        if any(x in src_l for x in ("/assets/", "/static/", "logo", "favicon", ".svg", "sprite", "placeholder")):
            return True
        return False

    # Собираем только явные IMG внутри секции (без background-image!)
    for img in section.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-original") or "").strip()
        if not src:
            ss = (img.get("srcset") or "").strip()
            if ss:
                src = ss.split(",")[0].split()[0]
        if not src:
            continue

        if src.startswith("data:image/"):
            # именно такие base64 видны у вас в инспекторе
            try:
                meta, b64 = src.split(",", 1)
                mime = meta.split(":",1)[1].split(";")[0]
                _add_data(base64.b64decode(b64), mime or "image/jpeg")
            except Exception:
                pass
        else:
            if is_junk(src):
                continue
            _add_url(urljoin(base_url, src), base_url)

    return items

@app.get('/healthz')
def healthz():
    return jsonify({"ok": True, "ts": time.time()})

def _selenium_collect_images(page_url: str, click_photos_tab=True, wait_sec=8):
    # импортим здесь, чтобы импорт Selenium не тормозил загрузку модуля
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    token, cookies = load_auth_from_cache()

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1280,900")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        # 1) посадим куки на домен
        driver.get("https://pts.gov.kz/")
        if cookies:
            for name, val in cookies.items():
                try:
                    driver.add_cookie({"name": name, "value": val, "domain": ".pts.gov.kz", "path": "/"})
                except Exception:
                    pass
        # если где-то нужен Bearer — можно хранить его в localStorage, если фронт это читает
        driver.get(page_url)

        # 2) иногда нужно открыть вкладку "Фото"
        if click_photos_tab:
            try:
                # пробуем найти кнопку/вкладку с текстом «Фото»/«Фотографии»
                tab = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//button[contains(., 'Фото') or contains(., 'Фотограф') or contains(., 'Фотографии')] | //a[contains(., 'Фото') or contains(., 'Фотограф')]")
                    )
                )
                tab.click()
            except Exception:
                pass

        # 3) подождём появление любых <img> на странице
        try:
            WebDriverWait(driver, wait_sec).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "img"))
            )
        except Exception:
            pass

        # 4) JS: собрать все url из <img>, <source srcset>, background-image
        js_collect = r"""
            const urls = new Set();

            // IMG + srcset
            for (const img of document.querySelectorAll('img')) {
                if (img.currentSrc) urls.add(img.currentSrc);
                if (img.src) urls.add(img.src);
                const ss = (img.getAttribute('srcset') || '').trim();
                if (ss) {
                    const u = ss.split(',')[0].trim().split(' ')[0];
                    if (u) urls.add(u);
                }
            }

            for (const src of document.querySelectorAll('source[srcset]')) {
                const ss = (src.getAttribute('srcset') || '').trim();
                if (ss) {
                    const u = ss.split(',')[0].trim().split(' ')[0];
                    if (u) urls.add(u);
                }
            }

            // background-image
            for (const el of document.querySelectorAll('[style]')) {
                const st = window.getComputedStyle(el).backgroundImage || '';
                const m = [...st.matchAll(/url\(([^)]+)\)/g)];
                for (const mm of m) {
                    let u = (mm[1] || '').trim().replace(/^['"]|['"]$/g, '');
                    if (u) urls.add(u);
                }
            }

            return Array.from(urls);
        """
        raw_urls = driver.execute_script(js_collect) or []

        # 5) blob: → data: (асинхронно)
        blob_urls = [u for u in raw_urls if isinstance(u, str) and u.startswith("blob:")]
        data_from_blob = []
        if blob_urls:
            js_blob_to_data = r"""
                const blobUrls = arguments[0] || [];
                const done = arguments[arguments.length - 1];

                (async () => {
                    const out = [];
                    for (const u of blobUrls) {
                        try {
                            const resp = await fetch(u);
                            const blob = await resp.blob();
                            const dataUrl = await new Promise((res, rej) => {
                                const fr = new FileReader();
                                fr.onload = () => res(fr.result);
                                fr.onerror = rej;
                                fr.readAsDataURL(blob);
                            });
                            if (typeof dataUrl === 'string' && dataUrl.startsWith('data:image')) {
                                out.push(dataUrl);
                            }
                        } catch (e) {}
                    }
                    done(out);
                })();
            """
            data_from_blob = driver.execute_async_script(js_blob_to_data, blob_urls) or []

        # 6) Соберём итог
        out = {"urls": [], "datauris": []}
        for u in raw_urls:
            if not isinstance(u, str): 
                continue
            if u.startswith("data:image"):
                out["datauris"].append(u)
            elif u.startswith("http") or u.startswith("/"):
                out["urls"].append(u)
        out["datauris"].extend([x for x in data_from_blob if isinstance(x, str) and x.startswith("data:image")])

        return out
    finally:
        driver.quit()


@app.post("/logout")
@require_token
def logout():
    try:
        _cookie_path().unlink(missing_ok=True)   # удаляем его файл куков
        (AUTH_STORE_DIR / f"{_user_key()}_jwt.txt").unlink(missing_ok=True)
    except Exception:
        pass
    with SESSION_CACHE_LOCK:
        SESSION_CACHE.pop(_user_key(), None)
    session.clear()
    return jsonify({"success": True})


# def _ensure_orig_bytes_by_item(item):
#     """
#     На вход item из /photos/list.
#     Возвращает (bytes, ext, name_hint) или (None, None, None), если не удалось.
#     """
#     try:
#         # data:image, сохранённые как handle
#         if item.get("kind") == "data" and item.get("handle"):
#             raw = _orig_path(item["handle"]).read_bytes()
#             # попытаемся угадать расширение
#             import imghdr
#             t = imghdr.what(None, h=raw[:32]) or "jpg"
#             return raw, (".webp" if t=="webp" else f".{t}"), "data"
#         # url по короткому key
#         if item.get("kind") == "url" and item.get("key"):
#             url, ref = _read_url_and_ref(item["key"])
#             if not url:
#                 return None, None, None
#             p = _orig_path(item["key"])
#             if not p.exists():
#                 # подтянем так же, как в /photos/stream
#                 s = _session_with_auth()
#                 hdrs = {
#                     "Referer": ref or "https://pts.gov.kz/",
#                     "Origin": "https://pts.gov.kz",
#                     "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#                     "User-Agent": "Mozilla/5.0",
#                 }
#                 r = s.get(url, timeout=30, verify=False, headers=hdrs, allow_redirects=True)
#                 if r.status_code != 200 or not r.content:
#                     raw2 = _fallback_fetch_image(url, ref)
#                     if not raw2:
#                         return None, None, None
#                     p.write_bytes(raw2)
#                 else:
#                     p.write_bytes(r.content)
#             raw = p.read_bytes()
#             import imghdr
#             t = imghdr.what(None, h=raw[:32]) or "jpg"
#             return raw, (".webp" if t=="webp" else f".{t}"), "url"
#     except Exception:
#         return None, None, None
#     return None, None, None

# @app.post("/photos/zip", endpoint="photos_zip")
# def photos_zip():
#     """
#     Вход:
#       { docId?: str, items?: [...] }
#     Если передан docId — соберём items через тот же сборщик, что и /photos/list.
#     """
#     data = request.get_json(silent=True) or {}
#     doc_id = (data.get("docId") or "").strip()
#     items  = data.get("items")

#     if not items:
#         # Подтянем список как в /photos/list
#         if not doc_id:
#             return jsonify({"error":"Передайте docId или items[]"}), 400
#         # URL карточки нужен как referer
#         url = f"https://pts.gov.kz/compliencedocument/sbkts/{doc_id}"
#         # лёгкое переиспользование: дернём наш же REST и возьмём items
#         try:
#             s = _session_with_auth()
#             r = s.post(request.host_url.rstrip("/") + "/photos/list",
#                        json={"docId": doc_id, "url": url}, timeout=60, verify=False)
#             r.raise_for_status()
#             j = r.json()
#             items = j.get("items") or []
#         except Exception as e:
#             return jsonify({"error": f"Не удалось получить список фото: {e}"}), 502

#     if not items:
#         return jsonify({"error":"Фото не найдены"}), 200

#     # Собираем ZIP во временный файл
#     tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
#     tmp.close()
#     added = 0
#     used_names = set()

#     with ZipFile(tmp.name, "w", compression=ZIP_STORED) as z:
#         for i, it in enumerate(items, 1):
#             raw, ext, hint = _ensure_orig_bytes_by_item(it)
#             if not raw:
#                 continue
#             base = f"{i:03d}_{hint}"
#             name = base + ext
#             # уникальность
#             k = 2
#             while name in used_names:
#                 name = f"{base}_{k}{ext}"; k += 1
#             used_names.add(name)
#             z.writestr(name, raw)
#             added += 1

#     if added == 0:
#         os.unlink(tmp.name)
#         return jsonify({"error":"Не удалось скачать ни одного файла"}), 200

#     download_name = (f"photos_{doc_id}.zip" if doc_id else "photos.zip")
#     return send_file(tmp.name, as_attachment=True, download_name=download_name, mimetype="application/zip")

def _fallback_fetch_image(url: str, referer: str | None) -> bytes | None:
    """
    Пытаемся выдернуть байты картинки без прямого GET длинного URL.
    1) Если URL слишком длинный (len>1800) или апстрим вернул не 200,
       пробуем через headless Chrome на странице-реферере:
       - открываем referer (страницу СБКТС)
       - в контексте той же origin делаем fetch(url) -> blob -> base64
    2) Возвращаем bytes или None.
    """
    try:
        if not referer:
            return None

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=1280,900")

        token, cookies = load_auth_from_cache()
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        try:
            # посадим куки на домен
            driver.get("https://pts.gov.kz/")
            if cookies:
                for name, val in cookies.items():
                    try:
                        driver.add_cookie({"name": name, "value": val, "domain": ".pts.gov.kz", "path": "/"})
                    except Exception:
                        pass

            # открываем страницу-реферер (та же origin, чтобы CORS не таинтил canvas)
            driver.get(referer)

            js = r"""
                const url = arguments[0];
                const done = arguments[arguments.length - 1];
                (async () => {
                    try {
                        const resp = await fetch(url, {credentials:'include'});
                        if (!resp.ok) return done(null);
                        const blob = await resp.blob();
                        const arrBuf = await blob.arrayBuffer();
                        const bytes = Array.from(new Uint8Array(arrBuf));
                        done(bytes);
                    } catch (e) {
                        done(null);
                    }
                })();
            """
            bytes_list = driver.execute_async_script(js, url)
            if not bytes_list:
                return None
            return bytes(bytearray(bytes_list))
        finally:
            driver.quit()
    except Exception as e:
        print(f"[fallback] selenium error: {e}")
        return None


def fetch_vin_page(vin: str) -> str:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://evak.online/"
    })
    s.get("https://evak.online/", timeout=10, verify=False)
    r = s.post("https://evak.online/search_reg.php", data={"query_reg": vin}, timeout=15, verify=False)
    r.raise_for_status()
    return r.text

def extract_all_text(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    return lines

def filter_result_block(lines):
    marker = "Ваше транспортное средство зарегистрировано в системе"
    try:
        idx = next(i for i, ln in enumerate(lines) if marker in ln)
        return lines[idx: idx+5]  # заголовок + 4 строки ниже
    except StopIteration:
        return []



# ==== ДОБАВЬ В APP: ====
def _thumb_path(key: str) -> Path:
    return PHOTO_CACHE / f"{key}.thumb.webp"

def _orig_path(key: str, mime_ext="jpg") -> Path:
    return PHOTO_CACHE / f"{key}.orig"

def _ensure_thumb_from_bytes(key: str, raw: bytes, max_w=480):
    if not PIL_OK:
        # нет pillow — не режем, обойдёмся оригиналом
        return None
    p = _thumb_path(key)
    if p.exists():
        return p
    try:
        im = Image.open(io.BytesIO(raw))
        w, h = im.size
        if w > max_w:
            nh = int(h * max_w / w)
            im = im.resize((max_w, nh), Image.LANCZOS)
        im.save(p, format="WEBP", quality=80)
        return p
    except Exception:
        return None

from datetime import datetime
def parse_block_data(block_lines):
    # Ожидаемый формат (может меняться на сайте — тогда часть полей будет None)
    try:
        vin_line = block_lines[1].split(": ", 1)[1]
    except Exception:
        vin_line = None
    try:
        reg_date_str = block_lines[2].split(": ", 1)[1]
        reg_date = datetime.strptime(reg_date_str, "%d.%m.%Y").date()
    except Exception:
        reg_date = None
    try:
        first_call_str = block_lines[3].split(": ", 1)[1]
        first_call = datetime.strptime(first_call_str, "%d.%m.%Y %H:%M:%S")
    except Exception:
        first_call = None
    try:
        model = block_lines[4].split(": ", 1)[1]
    except Exception:
        model = None
    return vin_line, reg_date, first_call, model

def check_vin_auto(vin: str):
    """Вернёт структуру для фронта или None, если ничего не нашли/ошибка."""
    if not is_valid_vin(vin):
        return None
    try:
        html = fetch_vin_page(vin)
        lines = extract_all_text(html)
        block = filter_result_block(lines)
        if not block:
            return {"found": False, "message": "Информация по VIN не найдена на evak.online."}
        vin_parsed, reg_date, first_call, model = parse_block_data(block)
        return {
            "found": True,
            "block": block,
            "data": {
                "VIN": vin_parsed or vin,
                "Дата регистрации в системе": reg_date.strftime("%d.%m.%Y") if reg_date else None,
                "Первичное обращение": first_call.strftime("%d.%m.%Y %H:%M:%S") if first_call else None,
                "Модель": model
            }
        }
    except Exception:
        # сайт может меняться / временно не отвечать — не ломаем основной парсинг
        return None

def _load_queue():
    with QUEUE_LOCK:
        return _load_json_safe(QUEUE_PATH, [])

def _save_queue(q):
    with QUEUE_LOCK:
        _save_json_safe(QUEUE_PATH, q)

def _dedup_in_queue(q, fp):
    return any(it.get("fp") == fp for it in q)

def enqueue_decision(
    doc_id: str,
    status_code: str,
    message: str,
    user_key: str | None = None,
    immediate: bool = False,
) -> dict:
    """
    Кладёт решение в очередь на отправку в PTS.

    - doc_id       — GUID документа (из PTS).
    - status_code  — "active" или "rejected".
    - message      — комментарий к решению.
    - user_key     — ключ пользователя (из _user_key()), чтобы привязать к его cookies/JWT.
    - immediate    — если True, сначала пробуем отправить сразу (_try_send),
                     при ошибке — кладём в очередь с ретраями.
    """
    doc_id = (doc_id or "").strip()
    if not doc_id:
        raise ValueError("doc_id is empty")

    # Идентификатор решения (для идемпотентности и дедупликации):
    fp = _fingerprint_decision(doc_id, status_code, message)

    # Собираем элемент очереди
    item = {
        "doc_id": doc_id,
        "status_code": status_code,
        "message": message or "",
        "fp": fp,
        "attempts": 0,
        "created_at": time.time(),
        "next_try_at": time.time(),
    }
    if user_key:
        item["user_key"] = user_key

    # 1) Если immediate=True — сначала пробуем отправить прямо сейчас
    if immediate:
        ok, resp = _try_send(item)
        if ok:
            return {
                "mode": "immediate",
                "queued": False,
                "success": True,
                "response": resp,
            }
        # если не получилось — упадём в обычную очередь с ретраями
        # и фронту скажем, что поставили в очередь
        # resp здесь — текст ошибки
        err = str(resp)

    # 2) Кладём в очередь (с проверкой, не лежит ли уже такое же решение)
    q = _load_queue()
    if _dedup_in_queue(q, fp):
        return {
            "mode": "queue",
            "queued": False,
            "duplicate": True,
            "success": True,
            "message": "Решение с такими параметрами уже есть в очереди",
        }

    q.append(item)
    _save_queue(q)

    return {
        "mode": "queue",
        "queued": True,
        "duplicate": False,
        "success": True,
        "message": "Решение поставлено в очередь на отправку в PTS",
        **({"last_error": err} if immediate else {}),
    }


def _resolve_pts_auth_for_item(item: dict) -> tuple[str | None, dict]:
    """
    Пытаемся найти токен/куки для отправки решения в PTS.

    Приоритет:
      1) per-user файлы из /epts/attach (по user_key в item);
      2) глобальный auth_cache.json (старый Selenium-логин).
    """
    token = None
    cookies_dict: dict = {}

    user_key = item.get("user_key")

    # 1) Авторизация, привязанная к конкретному пользователю (через расширение)
    if user_key:
        ck_path = AUTH_STORE_DIR / f"{user_key}_cookies.json"
        if ck_path.exists():
            try:
                with open(ck_path, "r", encoding="utf-8") as f:
                    cookies_dict = json.load(f) or {}
            except Exception:
                cookies_dict = {}

        jwt_path = AUTH_STORE_DIR / f"{user_key}_jwt.txt"
        if jwt_path.exists():
            try:
                token = jwt_path.read_text(encoding="utf-8").strip() or None
            except Exception:
                token = None

    # 2) Фоллбек на старый механизм (auth_cache.json), если ничего не нашли
    if not token and not cookies_dict:
        try:
            old_token, old_cookies = load_auth_from_cache()
            if old_cookies:
                cookies_dict = old_cookies
            if old_token:
                token = old_token
        except Exception:
            pass

    return token, cookies_dict


# def process_pts_request(doc_id: str, status_code: str, message: str):
#     """Бьём в /api/compliencedocument/processRequest. При 401/403 делаем relogin и повторяем 1 раз."""
#     # token, cookies = load_auth_from_cache()
#     # if not token or not cookies:
#     #     # Пытаемся сразу пере-логин
#     #     try:
#     #         token, cookies = get_token_and_cookies_via_selenium()
#     #         save_auth_to_cache(token, cookies)
#     #     except Exception:
#     #         raise RuntimeError("Нет токена/куков — выполните повторную авторизацию.")
#     token, cookies = load_auth_from_cache()
#     if not token and not cookies:
#         raise RuntimeError("Нет валидных токенов/куки PTS. Прикрепите через /epts/attach.")


#     def _do_call(tok, ck):
#         headers = {
#             "Authorization": f"Bearer {tok}",
#             "Accept": "application/json",
#             "Content-Type": "application/json",
#             "Origin": "https://pts.gov.kz",
#             "Referer": f"https://pts.gov.kz/compliencedocument/sbkts/{doc_id}",
#             # идемпотентный ключ на стороне апстрима (если вдруг поддержат)
#             "Idempotency-Key": _fingerprint_decision(doc_id, status_code, message),
#         }
#         payload = {"DocId": doc_id, "StatusCode": status_code, "Message": message or ""}
#         r = requests.post(
#             "https://pts.gov.kz/api/compliencedocument/processRequest",
#             headers=headers,
#             cookies=ck,
#             json=payload,
#             timeout=20,
#             verify=False
#         )
#         return r

#     r = _do_call(token, cookies)
#     if r.status_code in (401, 403):
#         raise RuntimeError("Авторизация PTS недействительна. Обновите токен/куки через /epts/attach.")


#     r.raise_for_status()
#     return r.json()
def process_pts_request(doc_id: str, status_code: str, message: str):
    """
    Живой вызов /api/compliencedocument/processRequest.
    Логика такая же, как в консольном app.py: берём токен/куки из Selenium.
    """
    # 1. Пытаемся взять токен + cookies из кэша Selenium
    token, cookies = load_auth_from_cache()

    # Если в кэше ничего нет — можно сразу попробовать перелогиниться через Selenium
    if not token or not cookies:
        try:
            token, cookies = get_token_and_cookies_via_selenium()
            save_auth_to_cache(token, cookies)
        except Exception:
            raise RuntimeError(
                "Нет токена/куков PTS. Выполните авторизацию через Selenium (auth_token_selenium.py)."
            )

    # Ещё раз читаем из кэша — уже после возможного обновления
    token, cookies = load_auth_from_cache()
    if not token and not cookies:
        raise RuntimeError("Нет валидных токенов/куки PTS (auth_cache.json пуст).")

    def _do_call(tok, ck):
        headers = {
            "Authorization": f"Bearer {tok}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": BASE,
            "Referer": f"{BASE}/compliencedocument/sbkts/{doc_id}",
            # идемпотентный ключ — чтобы PTS сам не дублировал решение
            "Idempotency-Key": _fingerprint_decision(doc_id, status_code, message),
        }
        payload = {
            "DocId": doc_id,
            "StatusCode": status_code,
            "Message": message or "",
        }
        r = requests.post(
            f"{BASE}/api/compliencedocument/processRequest",
            headers=headers,
            cookies=ck,
            json=payload,
            timeout=20,
            verify=VERIFY_TLS,
        )
        return r

    # Первый запрос
    r = _do_call(token, cookies)

    # Если авторизация умерла — один раз пробуем перелогиниться
    if r.status_code in (401, 403):
        try:
            token, cookies = get_token_and_cookies_via_selenium()
            save_auth_to_cache(token, cookies)
        except Exception:
            raise RuntimeError(
                "Авторизация PTS недействительна. Повторно залогиньтесь через Selenium."
            )
        r = _do_call(token, cookies)

    # Любая ошибка по HTTP → исключение
    r.raise_for_status()

    # Возвращаем JSON (или текст, если не JSON)
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}


# def _try_send(item: dict):
#     """Пробуем отправить элемент очереди. Возвращает (ok, resp_or_err)."""
#     try:
#         # если уже применено — считаем успехом
#         prev = _get_sent_for(item["doc_id"])
#         if prev and prev.get("status_code") == item["status_code"] and (prev.get("message") or "") == (item.get("message") or ""):
#             return True, {"via": "already_applied", "prev": prev}

#         resp = process_pts_request(item["doc_id"], item["status_code"], item.get("message",""))
#         _mark_sent(item["doc_id"], item["status_code"], item.get("message",""), resp)
#         return True, resp
#     except Exception as e:
#         return False, str(e)

def _try_send(item: dict):
    """Пробуем отправить элемент очереди. Возвращает (ok, resp_or_err)."""
    try:
        # Если по этому doc_id + status_code + message уже есть успешная запись —
        # считаем, что решение уже применено (наша локальная идемпотентность).
        prev = _get_sent_for(item["doc_id"])
        if (
            prev
            and prev.get("status_code") == item["status_code"]
            and (prev.get("message") or "") == (item.get("message") or "")
        ):
            return True, {"via": "already_applied", "prev": prev}

        # Вызываем PTS так же, как в консольной версии
        resp = process_pts_request(
            item["doc_id"],
            item["status_code"],
            item.get("message", ""),
        )

        # Если дошли сюда — HTTP 200/201, считаем, что решение применено
        _mark_sent(item["doc_id"], item["status_code"], item.get("message", ""), resp)
        return True, resp

    except Exception as e:
        return False, str(e)


def _queue_worker():
    """Фоновый ретрай: экспоненциальный бэкофф + джиттер, DEAD PATH после MAX_ATTEMPTS."""
    while True:
        q = _load_queue()
        now = time.time()
        new_q = []
        changed = False

        for it in q:
            next_at = it.get("next_try_at", 0)
            if now < next_at:
                new_q.append(it)
                continue

            ok, resp = _try_send(it)
            if ok:
                changed = True  # удаляем из очереди
            else:
                it["attempts"] = it.get("attempts", 0) + 1
                if it["attempts"] >= MAX_ATTEMPTS:
                    # в мёртвый ящик
                    dead = _load_json_safe(DEAD_PATH, [])
                    it["dead_at"] = time.time()
                    it["last_error"] = resp
                    dead.append(it)
                    _save_json_safe(DEAD_PATH, dead)
                    changed = True
                    continue

                base = min(300, 5 * (2 ** (it["attempts"] - 1)))  # 5,10,20,40,80,160,300...
                jitter = base * random.uniform(-0.2, 0.2)
                it["next_try_at"] = now + base + jitter
                it["last_error"] = resp
                new_q.append(it)
                changed = True

        if changed:
            _save_queue(new_q)

        time.sleep(6)


def _token_path() -> Path:
    return AUTH_STORE_DIR / f"{_user_key()}_bearer.txt"

def _load_bearer_for_user() -> str | None:
    p = _token_path()
    try:
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            return s or None
    except Exception:
        pass
    return None

def _save_bearer_for_user(tok: str | None):
    p = _token_path()
    if not tok:
        p.unlink(missing_ok=True)
        return
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(tok.strip())
    os.replace(tmp, p)

# Стартуем фонового работника
threading.Thread(target=_queue_worker, daemon=True).start()

# ==================  Веб-маршруты  ==================



@app.route("/")
def index():
    token = request.args.get("token") or request.cookies.get("auth_token")
    user_info = {"name": "Гость", "email": ""}

    if token:
        try:
            r = requests.get(f"{API_VERIFY_URL}?token={token}", timeout=10)
            payload = r.json() if r.status_code == 200 else {}
            user_data = _extract_user(payload)
            if user_data:
                user_info = user_data
                resp = make_response(render_template("index.html", user=user_info, pts_status="not_authenticated"))
                is_dev = request.host.startswith(("127.0.0.1", "localhost"))
                resp.set_cookie(
                    "auth_token", token,
                    samesite="Strict",
                    httponly=True,
                    secure=not is_dev,
                    path="/"
                )
                return resp
        except Exception:
            pass
    return render_template("index.html", user=user_info, pts_status="not_authenticated")

from auth_token_selenium import get_token_and_cookies_via_selenium, save_auth_to_cache, load_auth_from_cache

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'error': 'Логин и пароль обязательны'}), 400
    try:
        # получаем PTS-токен/куки через Selenium
        token, cookies = get_token_and_cookies_via_selenium(username, password)

        # сохраняем ТОЛЬКО cookies, привязанные к текущему пользователю (по X-Parser-Token)
        jar = requests.utils.cookiejar_from_dict(cookies or {})
        _save_cookies_for_user(jar)
        # сбрасываем кэш сессии, чтобы новый jar подхватился
        with SESSION_CACHE_LOCK:
            SESSION_CACHE.pop(_user_key(), None)

        # 🔒 Не отдаём PTS-токен на фронт
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({"success": False, "error": "Selenium-логин отключён. Используйте /epts/attach."}), 410

# app.py — замените /check_vin целиком на это
@app.route('/check_vin', methods=['POST'])
@require_token
def check_vin():
    data = request.get_json(silent=True) or {}
    vin = (data.get('vin') or '').strip().upper()

    if not is_valid_vin(vin):
        return jsonify({"error": "Некорректный VIN. Должно быть 17 символов A-Z/0-9 (без I,O,Q)."}), 400

    try:
        html = fetch_vin_page(vin)
        lines = extract_all_text(html)
        block = filter_result_block(lines)

        if not block:
            return jsonify({"found": False, "message": "Информация по VIN не найдена на evak.online."})

        vin_parsed, reg_date, first_call, model = parse_block_data(block)
        return jsonify({
            "found": True,
            "block": block,
            "data": {
                "VIN": vin_parsed or vin,
                "Дата регистрации в системе": reg_date.strftime("%d.%m.%Y") if reg_date else "",
                "Первичное обращение": first_call.strftime("%d.%m.%Y %H:%M:%S") if first_call else "",
                "Модель": model or ""
            }
        })
    except Exception as e:
        return jsonify({"error": f"Ошибка проверки VIN: {e}"}), 500

VERIFY_TLS = os.getenv("VERIFY_TLS", "true").lower() == "true"

# def _session_with_auth(force_new: bool=False) -> requests.Session:
#     key = _user_key()
#     now = time.time()
#     if not force_new:
#         cached = SESSION_CACHE.get(key)
#         if cached and now < cached.get("exp", 0):
#             return cached["sess"]

#     jar = _load_cookies_for_user()
    
#     # ИЗМЕНИТЬ ПРОВЕРКУ: разрешить сессию без кук (для публичных запросов)
#     if not jar:
#         jar = RequestsCookieJar()  # пустая кука
    
#     s = requests.Session()
#     s.verify = VERIFY_TLS
#     s.cookies = jar
#     s.headers.update({
#         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PTSClient/1.0",
#         "Accept": "application/json, text/plain, */*",
#         "Origin": BASE,
#         "Referer": BASE + "/",
#     })
#     SESSION_CACHE[key] = {"sess": s, "exp": now + SESSION_TTL}
#     return s

def _session_with_auth(force_new: bool = False) -> requests.Session:
    """
    Создаёт requests.Session с куками PTS.
    Если нет X-Parser-Token → используем общий ключ 'anon' (для Postman/dev),
    и в этом режиме берём куки из старого auth_cache.json через load_auth_from_cache().
    """
    try:
        key = _user_key()
    except Unauthorized:
        # Нет X-Parser-Token → работаем как один общий пользователь (для Postman/локальных тестов)
        key = "anon"

    now = time.time()
    if not force_new:
        with SESSION_CACHE_LOCK:
            cached = SESSION_CACHE.get(key)
        if cached and now < cached.get("exp", 0):
            return cached["sess"]

    jar = None
    if key != "anon":
        # нормальный путь: per-user cookies из auth_store/<user_key>_cookies.json
        jar = _load_cookies_for_user()

    if not jar:
        # fallback: пробуем старый Selenium-кэш auth_cache.json
        try:
            tok, ck = load_auth_from_cache()
            if ck:
                jar = requests.utils.cookiejar_from_dict(ck)
                # заодно сохраним под текущим ключом, чтобы потом не дергать load_auth_from_cache()
                _save_cookies_for_user(jar)
        except Exception:
            jar = None

    # Если вообще нет кук — создаём пустую jar (на случай публичных эндпоинтов)
    if not jar:
        jar = RequestsCookieJar()

    s = requests.Session()
    s.verify = VERIFY_TLS
    s.cookies = jar
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PTSClient/1.0",
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE,
        "Referer": BASE + "/",
    })
    with SESSION_CACHE_LOCK:
        SESSION_CACHE[key] = {"sess": s, "exp": now + SESSION_TTL}
    return s

@app.post("/debug/pts/raw")
def debug_pts_raw():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    s = _session_with_auth()
    r = s.get(url, timeout=20, verify=VERIFY_TLS)

    return jsonify({
        "status": r.status_code,
        "content_type": r.headers.get("Content-Type"),
        "text_snippet": r.text[:2000]  # первые 2000 символов
    }), 200


def _first(x):
    if isinstance(x, list):
        return x[0] if x else {}
    return x or {}


def _status_label(code: str, fallback: str | None = None) -> str:
    raw = (code or '').strip().lower()
    labels = {
        "active":       "Действующий",
        "consideration":"На рассмотрении",   # ← из HAR
        "inrevision":   "На доработке",      # ← из HAR
        "rejected":     "Отклонённый",
        "closed":       "Закрытый",
        "canceled":     "Отменённый",
        "cancelled":    "Отменённый",
        # на всякий случай совместимость со старыми вариантами
        "onreview":     "На рассмотрении",
        "inreview":     "На рассмотрении",
        "pending":      "На рассмотрении",
    }
    return labels.get(raw, fallback or code or "")

def _is_consideration(code: str, label: str | None = None) -> bool:
    c = (code  or '').strip().lower()
    l = (label or '').strip().lower()
    return ('consideration' in c) or ('на рассмотр' in l)

def _parse_cookie_header(s: str) -> dict:
    # принимает либо всю строку "Cookie: a=b; c=d", либо просто "a=b; c=d"
    s = (s or "").strip()
    if not s:
        return {}
    if s.lower().startswith("cookie:"):
        s = s.split(":",1)[1].strip()
    out = {}
    for part in s.split(";"):
        if "=" in part:
            k,v = part.split("=",1)
            k = k.strip(); v = v.strip()
            if k:
                out[k] = v
    return out

@app.route('/api/debug/set_pts_token', methods=['POST'])
@require_token
def set_pts_token_debug():
    """Временный endpoint для ручной установки PTS токена"""
    data = request.json
    pts_token = data.get('pts_token')
    
    if not pts_token:
        return jsonify({"error": "PTS token required"}), 400
    
    # Сохраняем в сессии (временное решение)
    session['pts_token'] = pts_token
    print(f"🔧 DEBUG: PTS token set: {pts_token[:20]}...")
    
    return jsonify({"message": "PTS token set successfully"})

@app.route('/api/debug/get_pts_token', methods=['GET'])
@require_token
def get_pts_token_debug():
    """Получить текущий PTS токен"""
    return jsonify({"pts_token": session.get('pts_token')})


@app.post("/epts/heartbeat")
@permissive_token
def epts_heartbeat():
    data = request.get_json(silent=True) or {}
    # можно логировать last_seen по _user_key(), если нужно
    return jsonify({"ok": True, "echo": data}), 200


@app.post("/epts/attach")
@permissive_token  # важен! нужен X-Parser-Token
def epts_attach():
    """
    Принимаем авторизацию от расширения.
    Понимаем:
      - {"cookies": "a=b; c=d"} или {"cookie":"a=b; c=d"}
      - {"cookiesByDomain": {"pts.gov.kz": {...}, ...}}
      - {"jwt": "eyJ..."}  (необязательно)
    """
    data = request.get_json(silent=True) or {}

    cookies_str = (data.get("cookies") or data.get("cookie") or "").strip()
    by_domain   = data.get("cookiesByDomain") or {}
    jwt         = (data.get("jwt") or "").strip()

    jar = None
    # из словаря по доменам
    if isinstance(by_domain, dict):
    # пробуем несколько вариантов домена
        for dom in ("pts.gov.kz", "www.pts.gov.kz", ".pts.gov.kz"):
            if by_domain.get(dom):
                dom_cookies = by_domain[dom]
                jar = requests.utils.cookiejar_from_dict(dom_cookies)
                if not cookies_str:
                    cookies_str = "; ".join(f"{k}={v}" for k, v in dom_cookies.items())
                break

    # из строки Cookie
    if not jar and cookies_str:
        jar = requests.utils.cookiejar_from_dict(_parse_cookie_header(cookies_str))

    if not jar and not jwt:
        current_app.logger.debug("[epts_attach] no_credentials")
        return jsonify({"ok": False, "error": "no_credentials"}), 400

    if jar:
        _save_cookies_for_user(jar)          # сохраняем per-user
        with SESSION_CACHE_LOCK:
            SESSION_CACHE.pop(_user_key(), None) # сбрасываем сессию

    if jwt:
        (AUTH_STORE_DIR / f"{_user_key()}_jwt.txt").write_text(jwt, encoding="utf-8")

    return jsonify({"ok": True})



# ==== ЛЁГКИЙ КЛИЕНТ PTS (API-first) ==========================================
import hashlib, json, time, threading

PTS_CACHE_DIR = Path("pts_cache"); PTS_CACHE_DIR.mkdir(exist_ok=True)

# троттлинг: 2 rps на процесс (поставь 1.0 если надо ещё бережнее)
_MIN_INTERVAL = 0.5
_last_t = 0.0
_rate_lock = threading.Lock()
def _throttle():
    global _last_t
    with _rate_lock:
        now = time.monotonic()
        wait = max(0.0, _MIN_INTERVAL - (now - _last_t))
        if wait > 0:
            time.sleep(wait)
        _last_t = time.monotonic()

def _sha1s(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8","ignore")).hexdigest()

def _cache_path(kind, key):
    return PTS_CACHE_DIR / f"{kind}.{_sha1s(key)}.json"

def _cache_read(kind, key, ttl_sec):
    p = _cache_path(kind, key)
    if not p.exists(): return None
    try:
        if time.time() - p.stat().st_mtime > ttl_sec: return None
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None

def _cache_write(kind, key, obj):
    p = _cache_path(kind, key)
    tmp = str(p)+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)

def pts_get(url, params=None, ttl=24*3600, kind="get", key_extra=""):
    """GET с кэшем и троттлингом."""
    params = params or {}
    ck = json.dumps({"u":url,"p":params,"x":key_extra}, ensure_ascii=False)
    cached = _cache_read(kind, ck, ttl)
    if cached is not None:
        return cached
    s = _session_with_auth()
    _throttle()
    r = s.get(url, params=params, timeout=20, verify=VERIFY_TLS)
    r.raise_for_status()
    j = r.json()
    _cache_write(kind, ck, j)
    return j

DOC_BY_ID_URL    = "https://pts.gov.kz/api/compliencedocument/getById"
DOC_DETAILS_URL  = "https://pts.gov.kz/api/compliencedocument/getAllInfo"

def get_doc_summary(doc_id: str) -> dict:
    """Краткое описание документа (бренд, тип, категория, даты, статус...)."""
    s = _session_with_auth()
    r = s.get(f"{BASE}/api/compliencedocument/get", params={"id": doc_id}, timeout=20, verify=False)
    r.raise_for_status()
    j = r.json() or {}
    # API иногда кладёт полезное в .data, иногда на верхнем уровне
    return j.get("data") or j

DETAIL_ENDPOINTS = {
    "general":        f"{PTS_API_BASE}/GetVehicleGeneralDetailsByDocId",
    "engine":         f"{PTS_API_BASE}/GetVehicleEngineDetailsByDocId",
    "transmission":   f"{PTS_API_BASE}/GetVehicleTransmissionDetailsByDocId",
    "running_gear":   f"{PTS_API_BASE}/GetVehicleRunningGearDetailsByDocId",
    "brakes":         f"{PTS_API_BASE}/GetVehicleBrakeSystemDetailsByDocId",
    "dimensions":     f"{PTS_API_BASE}/GetVehicleDimensionsDetailsByDocId",
    "weight":         f"{PTS_API_BASE}/GetVehicleWeightDetailsByDocId",
    "mass":           f"{PTS_API_BASE}/GetVehicleMassDetailsByDocId",
    "seats":          f"{PTS_API_BASE}/GetVehicleSeatsCountDetails",
    "tyres":          f"{PTS_API_BASE}/GetVehicleTyreDetails",
    "platform":       f"{PTS_API_BASE}/GetVehiclePlatformDetailsByDocId",
}


# def get_details(doc_id: str) -> dict:
#     s = _session_with_auth()
#     def grab(path: str, param_name: str = "id"):
#         r = s.get(f"{BASE}{path}", params={param_name: doc_id}, timeout=20, verify=False)
#         r.raise_for_status()
#         j = r.json() or {}
#         return j.get("data") or j or []

#     return {
#         # общий блок характеристик ТС (бренд, модель, VIN, год и т.д.)
#         "general":    grab("/api/compliencedocument/GetVehicleGeneralDetailsByDocId"),
#         "engine":     grab("/api/compliencedocument/GetEngineDetailsByDocId"),
#         "dimensions": grab("/api/compliencedocument/GetVehicleDimensionDetailsByDocId"),
#         "weight":     grab("/api/compliencedocument/GetVehicleWeightDetailsByDocId"),
#         # если у вас реально «tyre kind infos» — оставь как было; иначе чаще встречается такой:
#         # "tyres":      grab("/api/compliencedocument/GetVehicleTyreDetailsByDocId"),
#         "tyres":      grab("/api/compliencedocument/GetVehicleTyreKindInfosByDocId"),
#         "platform":   grab("/api/compliencedocument/GetVehiclePlatformDetailsByDocId"),
#     }
def get_details(doc_id: str) -> dict:
    """
    Тянем блоки характеристик по docId.
    - Используем правильный параметр "docId"
    - 404 по какому-то блоку не роняет всё, а даёт просто пустой список
    """
    s = _session_with_auth()

    def grab(path: str) -> list | dict:
        url = f"{BASE}{path}"
        r = s.get(url, params={"docId": doc_id}, timeout=20, verify=VERIFY_TLS)

        # если для этого docId блок отсутствует или урл не поддерживается —
        # просто считаем, что данных по этому блоку нет
        if r.status_code == 404:
            return []

        r.raise_for_status()
        j = r.json() or {}
        return j.get("data") or j or []

    return {
        # общий блок (марка, модель, VIN, год и т.п.)
        "general":    grab("/api/compliencedocument/GetVehicleGeneralDetailsByDocId"),
        # двигатель
        "engine":     grab("/api/compliencedocument/GetVehicleEngineDetailsByDocId"),
        # габариты
        "dimensions": grab("/api/compliencedocument/GetVehicleDimensionsDetailsByDocId"),
        # массы
        "weight":     grab("/api/compliencedocument/GetVehicleWeightDetailsByDocId"),
        # шины/оси
        "tyres":      grab("/api/compliencedocument/GetVehicleTyreKindInfosByDocId"),
        # шасси/платформа
        "platform":   grab("/api/compliencedocument/GetVehiclePlatformDetailsByDocId"),
    }


def get_photos_meta(doc_id: str):
    try:
        return pts_get(f"{PTS_API_BASE}/getGeneralViewList", params={"docId": doc_id}, ttl=2*3600, kind="photos")
    except Exception:
        return None


# === События документа ========================================================

def _parse_kz_dt(s: str):
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y %H:%M:%S")
    except Exception:
        return None

def _find_events_list(obj):
    """
    Ищет первый список словарей в ответе PTS, в котором реально лежат события.
    Смотрит внутрь data/events/items/... на любой глубине.
    """
    # Если это список
    if isinstance(obj, list):
        # Если список словарей — очень похоже на события
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        # Иначе обходим элементы
        for x in obj:
            found = _find_events_list(x)
            if found is not None:
                return found
        return None

    # Если это словарь
    if isinstance(obj, dict):
        # Сначала — «типичные» ключи
        for key in ("events", "data", "items", "rows", "list", "result"):
            if key in obj:
                found = _find_events_list(obj[key])
                if found is not None:
                    return found
        # Потом — любые остальные значения
        for v in obj.values():
            found = _find_events_list(v)
            if found is not None:
                return found

    return None


def get_document_events(doc_id: str) -> list[dict]:
    """
    События документа из официального эндпоинта:
    GET /api/compliencedocument/GetDocumentEvents?docId=...
    Возвращаем компактный список с нормализованными полями.
    """
    s = _session_with_auth()
    url = f"{BASE}/api/compliencedocument/GetDocumentEvents"
    r = s.get(url, params={"docId": doc_id}, timeout=20, verify=VERIFY_TLS)
    r.raise_for_status()

    j = r.json() or {}
    debug_dump(f"events_{doc_id}", j)

    # универсально ищем список событий
    raw_events = _find_events_list(j) or []

    out: list[dict] = []
    for e in raw_events:
        if not isinstance(e, dict):
            continue
        sc_raw = (e.get("statusCode") or e.get("code") or "").strip().lower()
        out.append({
            "date":        e.get("createDate") or e.get("date") or e.get("createdAt") or "",
            "statusCode":  e.get("statusCode") or e.get("code") or "",
            "statusLabel": _status_label(sc_raw, e.get("statusName") or e.get("name")),
            "user":        e.get("userName") or e.get("author") or "",
            "message":     e.get("message") or e.get("name") or "",
        })

    # при желании можно отсортировать по дате (если форматы нормальные)
    # try:
    #     out.sort(key=lambda ev: _parse_kz_dt(ev["date"]) or ev["date"])
    # except Exception:
    #     pass

    return out



# def get_document_events(doc_id: str) -> list[dict]:
#     """
#     События документа из официального эндпоинта:
#     GET /api/compliencedocument/GetDocumentEvents?docId=...
#     Возвращаем компактный список с нормализованными полями.
#     """
#     s = _session_with_auth()
#     r = s.get(
#         f"{BASE}/api/compliencedocument/GetDocumentEvents",
#         params={"docId": doc_id},
#         timeout=20,
#         verify=VERIFY_TLS
#     )
#     r.raise_for_status()
#     j = r.json() or {}
#     events = j.get("data") or j.get("events") or []
#     out = []
#     for e in events:
#         sc_raw = (e.get("statusCode") or e.get("code") or "").strip().lower()
#         out.append({
#             "date":        e.get("createDate") or e.get("date") or e.get("createdAt") or "",
#             "statusCode":  e.get("statusCode") or e.get("code") or "",
#             "statusLabel": _status_label(sc_raw, e.get("statusName") or e.get("name")),
#             "user":        e.get("userName") or e.get("author") or "",
#             "message":     e.get("message") or e.get("name") or "",
#         })
#     return out

@app.post("/api/pts/details")
@permissive_token
def pts_details():
    """
    Новый вариант: тянем данные из JSON-эндпоинтов PTS, а не через HTML-парсер.
    Вход: { "url": "https://pts.gov.kz/compliencedocument/sbkts/<GUID>" }
    Выход: { ok, docId, fields, violation_point5, evak, events }
    """
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400

    doc_id = extract_guid_from_url(url)
    if not doc_id:
        return jsonify({"ok": False, "error": "Не удалось извлечь docId из url"}), 400

    try:
        # Краткая карточка
        summary = get_doc_summary(doc_id) or {}
        # Детали по блокам (general/engine/dimensions/...)
        details = get_details(doc_id) or {}
        # Маппим JSON → твои поля
        fields = compose_fields_from_api(summary, details)
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": f"HTTP при обращении к PTS: {e}"}), 502
    except Exception as e:
        app.logger.exception("Ошибка в compose_fields_from_api")
        return jsonify({"ok": False, "error": f"Ошибка обработки JSON: {e}"}), 500

    # «Дата оформления» наверх, как в /parse_site
    if "Дата оформления" in fields:
        fields = {"Дата оформления": fields.pop("Дата оформления"), **fields}

    # п.5
    violation = check_violation_point5(fields)

    # EVAK по VIN
    vin = extract_vin_from_fields(fields) or ""
    evak = check_vin_auto(vin) if vin else None

    # События документа (может упасть, поэтому мягко)
    try:
        events = get_document_events(doc_id)
    except Exception:
        events = []

    return jsonify({
        "ok": True,
        "docId": doc_id,
        "fields": fields,
        "violation_point5": violation,
        "evak": evak,
        "events": events
    }), 200

@app.route("/api/pts/events", methods=["POST"])
def api_pts_events():
    body = request.get_json(silent=True) or {}
    doc_id = body.get("docId") or body.get("id")

    if not doc_id:
        return jsonify({"error": "docId is required"}), 400

    token, cookies = load_auth_from_cache()
    if not token:
        return jsonify({"error": "Нет валидного токена PTS"}), 401

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })

    try:
        # сначала POST
        r = session.post(API_GET_EVENTS,
                         json={"id": doc_id},
                         cookies=cookies,
                         timeout=20,
                         verify=False)
        r.raise_for_status()
        raw = r.json()
    except Exception:
        # fallback — GET c ?id=
        r = session.get(API_GET_EVENTS,
                        params={"id": doc_id},
                        cookies=cookies,
                        timeout=20,
                        verify=False)
        r.raise_for_status()
        raw = r.json()

    # Унификация формата
    events = []
    if isinstance(raw, list):
        events = raw
    elif isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict) and isinstance(data.get("data"), list):
            events = data["data"]

    return jsonify({
        "events": events,
        # при желании здесь же можно вернуть statusLabel/statusCode
    })

from urllib.parse import urljoin
from werkzeug.exceptions import Unauthorized

@app.post("/api/pts/decision")
@require_token
def api_pts_decision():
    """
    Унифицированный эндпоинт для одобрения/отклонения СБКТС.

    Вход (JSON):
      {
        "docId":   "d2ced040-f0d9-47d9-8c4a-bc09030b463f",
        "decision": "approve" | "reject",
        "message": "опциональный комментарий",
        "immediate": true|false   // по умолчанию true
      }
    """
    payload = request.get_json(silent=True) or {}

    doc_id = (payload.get("docId") or payload.get("doc_id") or "").strip()
    decision = (payload.get("decision") or "").strip().lower()
    message = (payload.get("message") or "").strip()
    immediate = bool(payload.get("immediate", True))  # по умолчанию сразу бьём в PTS

    if not doc_id:
        return jsonify({"ok": False, "error": "docId is required"}), 400

    if decision not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "decision must be 'approve' or 'reject'"}), 400

    status_code = "active" if decision == "approve" else "rejected"

    # user_key нужен, чтобы process_pts_request смог найти именно твои куки/JWT
    try:
        user_key = _user_key()
    except Unauthorized:
        user_key = None

    try:
        res = enqueue_decision(
            doc_id=doc_id,
            status_code=status_code,
            message=message,
            user_key=user_key,
            immediate=immediate,
        )
    except Exception as e:
        current_app.logger.exception("enqueue_decision failed")
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, **res}), 200

@app.get("/api/pts/queue/debug")
@require_token
def debug_pts_queue():
    return jsonify({
        "queue": _load_queue(),
        "dead": _load_json_safe(DEAD_PATH, []),
        "sent": _load_json_safe(SENT_PATH, {}),
    })


@app.route('/photos/list', methods=['POST'])
@permissive_token
def photos_list():
    """
    Вход: { docId?: str, url?: str }
    - Если передан только docId — построим URL карточки сами.
    - Возвращаем компактный список items, который потом можно скармливать /photos/stream или /photos/zip.
    Формат:
      { docId, url, count, items: [ {id, kind: 'url'|'data', key|handle, ...}, ... ] }
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    doc_id = (data.get("docId") or extract_guid_from_url(url or "") or "").strip()

    if not url and doc_id:
        url = f"{BASE}/compliencedocument/sbkts/{doc_id}"

    if not url and not doc_id:
        return jsonify({"error": "Передайте url или docId"}), 400

    try:
        # Сбор фото централизованной функцией (она уже есть у вас выше)
        items = _collect_photo_items(url, doc_id)
        return jsonify({
            "ok": True,
            "docId": doc_id or None,
            "url": url or None,
            "count": len(items),
            "items": items
        }), 200

    except Unauthorized as e:
        # Нет валидных куков к PTS → подскажем фронту, что нужно заново прикрепить авторизацию
        return jsonify({"ok": False, "error": "missing_auth", "message": str(e)}), 401

    except Exception as e:
        current_app.logger.exception("photos_list failed")
        return jsonify({"ok": False, "error": "photos_list_failed", "message": f"{e}"}), 500


    items = []
    seen_url = set()
    seen_handle = set()
    idx = 0

    def _add_url(u: str):
        nonlocal idx
        if not u:
            return
        u = _abs(u)
        if re.search(r"/img/|/icons?/|/favicon", u):
            return
        # сохраняем соответствие и выдаём короткий ключ
        key = _save_url_mapping(u, referer=base_url)  # ← сохраняем и Referer
        if key in seen_url:
            return
        seen_url.add(key)
        items.append({"id": idx, "kind": "url", "key": key})  # <-- key вместо url
        idx += 1



    def _add_datauri(data_uri: str):
        nonlocal idx
        try:
            meta, b64 = data_uri.split(",", 1)
            mime = meta.split(";")[0].split(":")[1]
            raw = base64.b64decode(b64)
            handle = hashlib.sha1(raw).hexdigest()  # ключ по контенту
            if handle in seen_handle:
                return
            seen_handle.add(handle)
            _orig_path(handle).write_bytes(raw)
            items.append({"id": idx, "kind": "data", "mime": mime, "handle": handle})
            idx += 1
        except Exception:
            pass

    # 1) На самой HTML-странице (если вдруг есть)
    candidate_attrs = ["src", "data-src", "data-original", "data-lazy", "data-lazy-src"]
    for img in soup.find_all("img"):
        src = None
        for attr in candidate_attrs:
            v = img.get(attr)
            if v:
                src = v.strip()
                break
        if not src:
            ss = (img.get("srcset") or "").strip()
            if ss:
                src = ss.split(",")[0].split()[0]
        if not src:
            continue
        if src.startswith("data:image"):
            _add_datauri(src)
        else:
            _add_url(src)

    for src in soup.select("picture source[srcset]"):
        ss = (src.get("srcset") or "").strip()
        if not ss:
            continue
        _add_url(ss.split(",")[0].split()[0])

    for node in soup.select("[style]"):
        st = node.get("style") or ""
        for m in re.findall(r'url\(([^)]+)\)', st):
            u = m.strip().strip("'\"")
            if not u:
                continue
            if u.startswith("data:image"):
                _add_datauri(u)
            else:
                _add_url(u)

    # 2) Любые data:image прямо в HTML
    for m in re.findall(r'(data:image/(?:png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+)', r.text):
        _add_datauri(m)

    import imghdr
    _B64_RE = re.compile(r'^[A-Za-z0-9+/=\s]+$')

    def _extract_images_from_json(obj, base="https://pts.gov.kz/"):
        out = []
        def _maybe_add_b64(s: str):
            s = (s or "").strip()
            if not s:
                return
            if s.startswith("data:image"):
                out.append(("datauri", s))
                return
            # Пытаемся распознать "голый" base64
            if len(s) > 500 and _B64_RE.match(s[:2000] if len(s) > 2000 else s):
                try:
                    raw = base64.b64decode(s, validate=True)
                    t = imghdr.what(None, h=raw[:32])
                    if t in ("jpeg", "png", "gif", "webp"):
                        # сохраняем как "data", чтобы /photos/stream умел отдать байты
                        handle = hashlib.sha1(raw).hexdigest()
                        _orig_path(handle).write_bytes(raw)
                        out.append(("datahandle", (handle, f"image/{'jpeg' if t=='jpeg' else t}")))
                except Exception:
                    pass

        if isinstance(obj, dict):
            # часто встречающиеся поля
            url2 = obj.get("url") or obj.get("fileUrl") or obj.get("href") or obj.get("src")
            data2 = (obj.get("data") or obj.get("file") or obj.get("image") or
                    obj.get("base64") or obj.get("base64String") or obj.get("value") or obj.get("content"))

            if isinstance(data2, str):
                _maybe_add_b64(data2)

            if isinstance(url2, str) and (url2.lower().startswith("http") or url2.startswith("/")):
                out.append(("url", urljoin(base, url2)))

            # рекурсивно
            for v in obj.values():
                out.extend(_extract_images_from_json(v, base))

        elif isinstance(obj, list):
            for x in obj:
                out.extend(_extract_images_from_json(x, base))

        elif isinstance(obj, str):
            if obj.startswith("data:image"):
                out.append(("datauri", obj))
            elif ("http" in obj and any(x in obj.lower() for x in [".jpg",".jpeg",".png",".gif",".webp"])) or obj.startswith("/"):
                out.append(("url", urljoin(base, obj)))
            else:
                _maybe_add_b64(obj)

        return out



#     if doc_id:
#         # Базовые (были)
#         # внутри photos_list(), перед циклом по endpoints
#         # 👉 фото "Общий вид ТС" грузятся отсюда
#         endpoints = [
#             f"https://pts.gov.kz/api/compliencedocument/getGeneralViewList?docId={doc_id}",
#             # было:
#             f"https://pts.gov.kz/api/ComplienceDocument/GetDocViewModelById?id={doc_id}",
#             f"https://pts.gov.kz/api/ComplienceDocument/GetAdditionalDataByDocId?id={doc_id}",
#             f"https://pts.gov.kz/api/ComplienceDocument/GetDetailById?id={doc_id}",
#         ]


#         guesses = [
#             # типовые варианты, которые встречаются в .NET-приложениях для вложений
#             "GetDocFilesByDocId", "GetFilesByDocId", "GetPhotosByDocId", "GetImagesByDocId",
#             "GetAttachmentsByDocId", "GetDocAttachmentsByDocId", "GetScansByDocId",
#             "GetVehicleFilesByDocId", "GetVehiclePhotosByDocId", "GetVehicleImagesByDocId",
#             "GetUploadsByDocId", "GetMediaByDocId", "GetGalleryByDocId",
#         ]
#         endpoints += [f"https://pts.gov.kz/api/compliencedocument/{name}?id={doc_id}" for name in guesses]


#         for ep in endpoints:
#             try:
#                 rr = s.get(ep, timeout=30, verify=False)
#                 if rr.ok and "application/json" in rr.headers.get("Content-Type", ""):
#                     j = rr.json()
#                     for kind, val in _extract_images_from_json(j):
#                         if kind == "url":
#                             _add_url(val)
#                         elif kind == "datauri":
#                             _add_datauri(val)
#                         elif kind == "datahandle":
#                             handle, mime = val
#                             if handle not in seen_handle:
#                                 seen_handle.add(handle)
#                                 items.append({"id": idx, "kind": "data", "mime": mime, "handle": handle})
#                                 idx += 1

#             except Exception:
#                 # просто пропускаем
#                 pass

#     print(f"[photos_list] docId={doc_id or '—'} → urls={len(seen_url)}, datauris={len(seen_handle)}, total={len(items)}")

# # ... после опроса HTML+JSON
#     if not items:
#         try:
#             se = _selenium_collect_images(base_url or url, click_photos_tab=True)
#             for u in se.get("urls", []):
#                 _add_url(u)
#             for du in se.get("datauris", []):
#                 _add_datauri(du)
#         except Exception as e:
#             print(f"[photos_list] selenium fallback error: {e}")

#     return jsonify({"docId": doc_id, "items": items})


def _map_path(key: str) -> Path:
    return PHOTO_CACHE / f"{key}.json"

def _url_map_path(key: str) -> Path:
    return PHOTO_CACHE / f"{key}.url"

def _save_url_mapping(url: str, referer: str | None = None) -> str:
    
    key = _sha1(url)
    data = {"url": url, "referer": referer or ""}
    p = _url_map_path(key)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return key


def _read_url_and_ref(key: str) -> tuple[str | None, str | None]:
    """
    Возвращает (url, referer) по key.

    Поддерживает:
    - новый формат: файл key.url содержит JSON {"url": "...", "referer": "..."}
    - старый формат: файл содержит просто строку с URL.
    """
    p = _url_map_path(key)
    if not p.exists():
        return None, None

    try:
        txt = p.read_text(encoding="utf-8")
        # сначала пробуем JSON
        try:
            obj = json.loads(txt)
            if isinstance(obj, dict):
                return obj.get("url") or None, obj.get("referer") or None
        except ValueError:
            # не JSON → считаем, что это просто URL
            return txt.strip() or None, None
    except Exception:
        return None, None


def _read_url_mapping(key: str) -> str | None:
    """
    Старый helper, оставлен для совместимости — возвращает только URL.
    """
    url, _ = _read_url_and_ref(key)
    return url


@app.get("/check_token_status")
@permissive_token
def check_token_status():
    jar = _load_cookies_for_user()
    if not jar:
        return jsonify({"status": "missing"}), 200
    try:
        s = requests.Session()
        s.cookies = jar
        payload = {
            "page": 1,
            "pageSize": 1,
            "sortField": [],
            "direction": [False],
            "filter": {
                "typeCode": "sbkts",
                "showDeleted": False,
                "search": ""
            }
        }
        r = s.post(PTS_LIST_URL, json=payload, timeout=10, verify=VERIFY_TLS)

        if r.status_code == 200:
            return jsonify({"status": "valid"}), 200
        if r.status_code in (401, 403):
            return jsonify({"status": "expired"}), 200

        return jsonify({
            "status": "error",
            "code": r.status_code,
            "body": (r.text or "")[:300]
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 200


@app.route("/relogin", methods=["POST"])
@permissive_token
def relogin():
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        if not username or not password:
            return jsonify({"success": False, "error": "username/password required"}), 400

        token, cookies = get_token_and_cookies_via_selenium(username, password, headless=True)

        # сохранить per-user (привязка к X-Parser-Token, и к IP если BIND_TO_IP=True)
        jar = requests.utils.cookiejar_from_dict(cookies or {})
        _save_cookies_for_user(jar)
        with SESSION_CACHE_LOCK:
            SESSION_CACHE.pop(_user_key(), None)

        # совместимость со старым кодом (если где-то нужен token/куки)
        try:
            if token:
                save_auth_to_cache(token, cookies)
        except Exception:
            pass

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": "Selenium-логин отключён. Используйте /epts/attach."}), 410

@app.route("/api/local-session/verify", methods=["GET"])
def api_local_session_verify():
    token = (request.args.get("token") or "").strip()
    if not token:
        return jsonify({"status": "error", "action": 0, "data": None}), 400
    # Здесь можно сделать реальную проверку токена, если нужна.
    return jsonify({"status": "ok", "action": 1, "data": {"user": "ok"}})


@app.route('/decision', methods=['POST'])
@require_token
def decision():
    """
    { "docId": "...", "decision": "approve"|"reject", "message": "...", "force": false? }
    """
    data = request.get_json(silent=True) or {}
    doc_id  = (data.get("docId") or "").strip()
    choice  = (data.get("decision") or "").strip().lower()
    message = (data.get("message") or "").strip()
    force   = bool(data.get("force", False))

    if not doc_id or not GUID_RE.fullmatch(doc_id):
        return jsonify({"ok": False, "error": "Неверный или пустой docId."}), 400
    if choice not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "decision должен быть approve|reject"}), 400

    status_code = "active" if choice == "approve" else "rejected"
    if choice == "approve" and not message:
        message = "Подтверждено"
    if choice == "reject" and not message:
        message = "Отказ без пояснения"

    # Конфликт с уже применённым другим статусом
    prev = _get_sent_for(doc_id)
    if prev and (prev.get("status_code") != status_code or (prev.get("message") or "") != message):
        if not force:
            return jsonify({
                "ok": False,
                "conflict": True,
                "message": "Для этого DocId уже применено другое решение.",
                "current": prev
            }), 409

    # Идемпотентность: если уже всё совпадает — сразу успех
    if prev and prev.get("status_code") == status_code and (prev.get("message") or "") == message:
        return jsonify({"ok": True, "via": "already_applied", "api": prev.get("api")}), 200

    # Пытаемся сразу
    user = getattr(request, "user", {}) or {}
    try:
        user_key = _user_key()   # привязка к X-Parser-Token (+IP, если BIND_TO_IP=True)
    except Exception:
        user_key = None

    fp = _fingerprint_decision(doc_id, status_code, message)
    item = {
        "doc_id": doc_id,
        "status_code": status_code,
        "message": message,
        "attempts": 0,
        "next_try_at": 0,
        "created_at": time.time(),
        "fp": fp,
        "user_key": user_key,
        "created_by": {
            "id": user.get("id") or user.get("userId"),
            "name": user.get("name") or user.get("username"),
        },
    }

    ok, resp = _try_send(item)
    if ok:
        return jsonify({"ok": True, "via": "immediate", "api": resp}), 200

    # Не удалось — в очередь (без дублей)
    q = _load_queue()
    if _dedup_in_queue(q, fp):
        # Уже в очереди
        return jsonify({
            "ok": False,
            "queued": True,
            "duplicate": True,
            "error": resp,
        }), 200

    item["last_error"] = resp
    base = 5
    item["next_try_at"] = time.time() + base + base * random.uniform(-0.2, 0.2)
    q.append(item)
    _save_queue(q)
    return jsonify({
        "ok": False,
        "queued": True,
        "error": resp,
        "next_try_sec": base
    }), 200

@app.route('/decision/status')
@require_token
def decision_status():
    doc_id = (request.args.get("docId") or "").strip()
    if not doc_id:
        return jsonify({"error": "docId обязателен"}), 400

    prev = _get_sent_for(doc_id)
    if prev:
        return jsonify({"state": "applied", "data": prev}), 200

    q = _load_queue()
    items = [it for it in q if it.get("doc_id") == doc_id]
    if items:
        it = sorted(items, key=lambda x: x.get("created_at", 0))[0]
        return jsonify({
            "state": "queued",
            "attempts": it.get("attempts", 0),
            "next_try_at": it.get("next_try_at", 0),
            "last_error": it.get("last_error")
        }), 200

    return jsonify({"state": "absent"}), 200


@app.route('/decision/cancel', methods=['POST'])
@require_token
def decision_cancel():
    data = request.get_json(silent=True) or {}
    doc_id = (data.get("docId") or "").strip()
    if not doc_id:
        return jsonify({"ok": False, "error": "docId обязателен"}), 400

    q = _load_queue()
    new_q = [it for it in q if it.get("doc_id") != doc_id]
    if len(new_q) == len(q):
        return jsonify({"ok": False, "error": "В очереди нет задач для этого docId"}), 404
    _save_queue(new_q)
    return jsonify({"ok": True}), 200

@app.route('/photos/stream')
@require_token
def photos_stream():
    """
    Отдаём одну картинку:

      /photos/stream?handle=...   — из локального кеша (data:image → файл)
      /photos/stream?key=...      — по короткому key (URL + Referer хранятся в файловом маппинге)
      /photos/stream?u=...        — прямой URL (debug)

    Параметр variant:
      - thumb (по умолчанию) — отдаём уменьшенный webp, если можем
      - orig                 — отдаём оригинал
    """
    variant = request.args.get("variant", "thumb")
    handle  = (request.args.get("handle") or "").strip()
    key     = (request.args.get("key") or "").strip()
    direct  = (request.args.get("u") or "").strip()

    mime = "image/jpeg"

    # --- 1) by handle (data:image, сохранённые как файлы) ---
    if handle:
        orig = _orig_path(handle)
        if not orig.exists():
            return "Not Found", 404

        raw = orig.read_bytes()
        try:
            import imghdr
            t = imghdr.what(None, h=raw[:32])
            if t == "png":
                mime = "image/png"
            elif t == "gif":
                mime = "image/gif"
            elif t == "webp":
                mime = "image/webp"
        except Exception:
            pass

        if variant == "thumb":
            tp = _ensure_thumb_from_bytes(handle, raw)
            if tp and tp.exists():
                return current_app.response_class(tp.read_bytes(), mimetype="image/webp")
        return current_app.response_class(raw, mimetype=mime)

    # --- 2) by key (основной путь для PTS-фото) ---
    if key:
        mapped_url, saved_ref = _read_url_and_ref(key)
        if not mapped_url:
            return "Not Found", 404

        orig = _orig_path(key)
        if not orig.exists():
            s = _session_with_auth()
            hdrs = {
                "Referer": saved_ref or "https://pts.gov.kz/",
                "Origin":  "https://pts.gov.kz",
                "Accept":  "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "User-Agent": "Mozilla/5.0",
            }
            print(f"[photos_stream] fetch key={key} → {mapped_url}")
            rr = s.get(mapped_url, headers=hdrs, timeout=30, verify=VERIFY_TLS, allow_redirects=True)
            raw = rr.content if rr.status_code == 200 and rr.content else _fallback_fetch_image(mapped_url, saved_ref)
            if not raw:
                return "Not Found", 404
            orig.write_bytes(raw)
        else:
            raw = orig.read_bytes()

        try:
            import imghdr
            t = imghdr.what(None, h=raw[:32])
            if t == "png":
                mime = "image/png"
            elif t == "gif":
                mime = "image/gif"
            elif t == "webp":
                mime = "image/webp"
        except Exception:
            pass

        if variant == "thumb":
            tp = _ensure_thumb_from_bytes(key, raw)
            if tp and tp.exists():
                return current_app.response_class(tp.read_bytes(), mimetype="image/webp")
        return current_app.response_class(raw, mimetype=mime)

    # --- 3) прямой URL (debug/отладка) ---
    if direct:
        s = _session_with_auth()
        rr = s.get(direct, timeout=30, verify=VERIFY_TLS)
        if rr.status_code != 200 or not rr.content:
            return "Not Found", 404
        return current_app.response_class(rr.content, mimetype="image/jpeg")

    return "Bad request", 400



def _ref_map_path(key: str) -> Path:
    return PHOTO_CACHE / f"{key}.ref"

def _save_url_mapping(url: str, referer: str | None = None) -> str:
    """
    Сохраняет длинный URL и реферер в файл по короткому ключу.
    Возвращает key (sha1 от url).
    """
    key = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()
    _map_path(key).write_text(json.dumps({"url": url, "referer": referer}, ensure_ascii=False), encoding="utf-8")
    p = _url_map_path(key)
    data = {"url": url, "referer": referer or None}
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, p)
    return key

def _read_url_and_ref(key: str) -> tuple[str | None, str | None]:
    try:
        p = _url_map_path(key)
        if not p.exists():
            return None, None
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj.get("url"), obj.get("referer")
    except Exception:
        return None, None
    
@app.route('/reset_token', methods=['POST'])
def reset_token():
    try:
        if os.path.exists("auth_cache.json"):
            os.remove("auth_cache.json")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# @app.route('/relogin', methods=['POST'])
# def relogin():
#     try:
#         cache_file = "auth_cache.json"
#         print(f"Попытка удалить кэш: {os.path.abspath(cache_file)}")
#         if os.path.exists(cache_file):
#             os.remove(cache_file)
#             print("✅ Кэш удален!")
#         else:
#             print("❗️Кэш не найден (может уже удалён).")

#         from auth_token_selenium import get_token_and_cookies_via_selenium, save_auth_to_cache

#         print("Запуск авторизации через Selenium...")
#         token, cookies = get_token_and_cookies_via_selenium()
#         print(f"Токен получен: {token[:15]}...")  # Только первые символы
#         save_auth_to_cache(token, cookies)
#         print("✅ Новый токен сохранён!")

#         return jsonify({"success": True, "token": token})
#     except Exception as e:
#         print(f"❌ Ошибка при relogin: {e}")
#         return jsonify({"success": False, "error": str(e)}), 500


# @app.route('/parse_pdf_file', methods=['POST'])
# def parse_pdf_file():
#     if 'file' not in request.files:
#         return jsonify({'error': 'Файл не загружен'}), 400

#     file = request.files['file']
#     if not file.filename.endswith(".pdf"):
#         return jsonify({'error': 'Неверный формат файла'}), 400

#     with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
#         file.save(tmp.name)
#         text = extract_text_from_pdf(tmp.name)
#         data = parse_fields(text)
#         data = postprocess_ev_fields(data, text)   
#     return jsonify(data)

# @app.route('/parse_pdf', methods=['POST'])
# def parse_pdf():
#     data = request.get_json()
#     pdf_url = data.get('url')

#     # Скачиваем PDF во временный файл
#     response = requests.get(pdf_url)
#     if response.status_code != 200:
#         return jsonify({"error": "Ошибка загрузки PDF"}), 400

#     with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
#         tmp.write(response.content)
#         tmp_path = tmp.name

#     text = extract_text_from_pdf(tmp_path)
#     result = parse_fields(text)
#     result = postprocess_ev_fields(result, text) 

#     os.remove(tmp_path)
#     return jsonify(result)


def open_browser():
    try:
        time.sleep(1)
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass

def start_background_workers_once():
    threading.Thread(target=_janitor_photos, daemon=True).start()
    threading.Thread(target=_queue_worker, daemon=True).start()
    threading.Thread(target=_janitor_auth, daemon=True).start()

app.register_blueprint(techreg_bp, url_prefix="/api/techreg")
app.register_blueprint(eokno_bp)
app.register_blueprint(pts_bp)
app.register_blueprint(customs_bp)
app.register_blueprint(keden_bp)

print("=== URL MAP ===")
for r in app.url_map.iter_rules():
    print(r, r.methods)
print("================")

if __name__ == '__main__':
    start_background_workers_once()
    if os.environ.get("RUN_AS_SERVICE") != "1":
        threading.Thread(target=open_browser, daemon=True).start()
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000, threads=16)
