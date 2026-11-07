# auth.py
from functools import wraps
from flask import request, g, jsonify
import requests, os, re

# ====== Конфиг через окружение ======
API_VERIFY_URL       = os.getenv("API_VERIFY_URL", "http://localhost:8080/api/local-session/verify")
TRUST_HEADER_TOKEN   = os.getenv("TRUST_HEADER_TOKEN", "0") == "1"   # dev: доверять любому присланному токену
DEBUG_AUTH           = os.getenv("DEBUG_AUTH", "0") == "1"
VERIFY_TIMEOUT_SEC   = float(os.getenv("VERIFY_TIMEOUT_SEC", "5"))

# Опционально: список доменов (для инфо/логов)
DEFAULT_TRUSTED_ORIGINS = {
    "https://modulab.kz",
    "https://parser.modulab.kz",
    "http://127.0.0.1:5000",
    "http://localhost:5000",
}
TRUSTED_ORIGINS = set(filter(None, (o.strip() for o in os.getenv(
    "TRUSTED_ORIGINS",
    ",".join(DEFAULT_TRUSTED_ORIGINS)
).split(","))))

# ====== Утилиты ======
_BEARER_RE = re.compile(r"^\s*Bearer\s+(.+)\s*$", re.IGNORECASE)

def _log(*a):
    if DEBUG_AUTH:
        try:
            print("[auth]", *a, flush=True)
        except Exception:
            pass

def _extract_user(p: dict):
    """
    Поддерживаем разные форматы ответа:
      1) { "valid": true, "user": {...}, "expiresAt": ... }
      2) { "status": "success"/"ok", "user": {...} }
      3) { "status": "ok", "action": 1, "data": {...} }  (+ data.user | плоско в data)
      4) { "data": { ... } }
      5) Плоский объект с id/userId
    """
    if not isinstance(p, dict):
        return None

    if p.get("valid") is True and isinstance(p.get("user"), dict):
        return p["user"]

    st = str(p.get("status", "")).lower()
    if st in ("success", "ok") and isinstance(p.get("user"), dict):
        return p["user"]

    if st == "ok" and int(p.get("action", 0)) == 1 and isinstance(p.get("data"), dict):
        d = p["data"]
        if isinstance(d.get("user"), dict):
            return d["user"]
        if ("userId" in d) or ("id" in d):
            return {
                "id": d.get("userId") or d.get("id"),
                "name": d.get("name") or d.get("fullName") or d.get("username") or "",
                "email": d.get("email") or d.get("mail") or "",
            }
        return d

    if isinstance(p.get("data"), dict):
        return p["data"]

    if ("userId" in p) or ("id" in p):
        return p

    return None

def _read_parser_token() -> str:
    """Пробуем все источники: X-Parser-Token, Authorization: Bearer, ?token=, cookie auth_token."""
    tok = (request.headers.get("X-Parser-Token") or "").strip()
    if tok:
        return tok

    auth = request.headers.get("Authorization") or ""
    m = _BEARER_RE.match(auth)
    if m:
        return m.group(1).strip()

    tok = (request.args.get("token") or "").strip()
    if tok:
        return tok

    tok = (request.cookies.get("auth_token") or "").strip()
    if tok:
        return tok

    return ""

def verify_token(token: str):
    """
    DEV-заглушка: никуда не ходим, просто считаем любой токен валидным.
    Если токена нет – считаем, что пользователь не авторизован.
    """
    if not token:
        return None
    return {"id": "dev", "name": "Dev User", "email": ""}


# def verify_token(token: str):
#     """Верификация через апстрим; dev-режим при TRUST_HEADER_TOKEN=1."""
#     if TRUST_HEADER_TOKEN:
#         if not token:
#             _log("TRUST_HEADER_TOKEN=1, но токен пуст → deny")
#             return None
#         _log("TRUST_HEADER_TOKEN=1 → принимаем токен без внешней проверки")
#         return {"id": "dev", "name": "Dev User"}

#     if not token:
#         _log("verify_token: пустой токен")
#         return None

#     try:
#         # Попытка №1: как раньше — ?token=...
#         _log(f"verify_token GET {API_VERIFY_URL}?token=*** (timeout={VERIFY_TIMEOUT_SEC})")
#         r = requests.get(API_VERIFY_URL, params={"token": token}, timeout=VERIFY_TIMEOUT_SEC)
#         try:
#             payload = r.json()
#         except Exception:
#             payload = {}
#         user = _extract_user(payload)
#         if user:
#             _log("verify_token: OK via query param")
#             return user

#         # Попытка №2: некоторые апстримы ждут Authorization: Bearer
#         _log(f"verify_token GET {API_VERIFY_URL} with Authorization: Bearer ***")
#         r2 = requests.get(API_VERIFY_URL, headers={"Authorization": f"Bearer {token}"}, timeout=VERIFY_TIMEOUT_SEC)
#         try:
#             payload2 = r2.json()
#         except Exception:
#             payload2 = {}
#         user2 = _extract_user(payload2)
#         if user2:
#             _log("verify_token: OK via Authorization header")
#             return user2

#         _log("verify_token: FAIL",
#              r.status_code, (r.text or "")[:160], "|", r2.status_code, (r2.text or "")[:160])
#     except requests.exceptions.RequestException as e:
#         _log("verify_token: exception:", e)
#     return None

# ====== Декораторы ======
# def permissive_token(f):
#     """Токен обязателен, но НЕ проверяется (быстрые мосты/стримы и т.п.)."""
#     @wraps(f)
#     def wrapped(*args, **kwargs):
#         tok = _read_parser_token()
#         if not tok:
#             return jsonify({"error": "Token required"}), 401
#         g.parser_token = tok
#         return f(*args, **kwargs)
#     return wrapped

def permissive_token(f):
    """
    DEV-вариант: токен не проверяем и даже не требуем.
    Если токен есть – кладём его в g.parser_token, иначе подставляем фиктивный.
    Также создаём request.user / g.user, чтобы остальной код не падал.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        tok = _read_parser_token()
        if not tok:
            tok = "dev-token"
        g.parser_token = tok

        # фиктивный пользователь для всех ручек, которые ждут request.user
        if not getattr(request, "user", None):
            request.user = {"id": "dev", "name": "Dev User", "email": ""}
        g.user = request.user

        return f(*args, **kwargs)
    return wrapped

def require_token(f):
    """Строгая проверка токена через апстрим (или dev-доверие)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        token = _read_parser_token()
        if not token:
            return jsonify({"error": "Token required"}), 401

        user = verify_token(token)
        if not user:
            return jsonify({"error": "Invalid or expired token"}), 401

        # прокидываем дальше
        request.user = user
        g.parser_token = token
        g.user = user
        return f(*args, **kwargs)
    return wrapped

def get_current_user():
    return getattr(request, "user", None)
