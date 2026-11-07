# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import hashlib, json, time, os
from pathlib import Path

app = Flask(__name__)

STORE_PATH = Path(os.getenv("UPSTREAM_STORE", "upstream_store.json"))

def _load():
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {"items": []}

def _save(obj):
    tmp = str(STORE_PATH) + ".tmp"
    Path(tmp).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE_PATH)

def _user_from_token(token: str) -> dict:
    """Детерминированно строим пользователя из любого непустого токена."""
    h = hashlib.sha1(token.encode("utf-8")).hexdigest()
    short = h[:8]
    return {
        "id": f"user_{short}",
        "email": f"user-{short}@local.test",
        "name": f"Local User {short}",
        # любые доп. поля — не помешают
        "roles": ["dev"]
    }

@app.get("/api/local-session/verify")
def verify():
    token = (request.args.get("token") or "").strip()
    if not token:
        # совместимо с твоей проверкой — 400, если совсем нет токена
        return jsonify({"status": "error", "action": 0, "data": None}), 400

    user = _user_from_token(token)
    # Возвращаем в «универсальной» форме, чтобы подошло под _extract_user(...)
    payload = {
        "status": "ok",
        "action": 1,
        "user": user,              # вариант 1
        "data": {"user": user},    # вариант 2
    }
    return jsonify(payload), 200

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "ts": time.time()})

# ====== Хранилище результатов, на которые шлёт твой app.py ======

@app.post("/api/parsed/add")
def parsed_add():
    token = (request.headers.get("X-Parser-Token") or request.args.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "missing X-Parser-Token"}), 401

    try:
        body = request.get_json(silent=True) or {}
        db = _load()
        db["items"].append({
            "ts": time.time(),
            "token": token,
            "record": body
        })
        _save(db)
        return jsonify({"ok": True, "id": len(db["items"]) - 1}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/parsed/my")
def parsed_my():
    token = (request.headers.get("X-Parser-Token") or request.args.get("token") or "").strip()
    if not token:
        return jsonify([]), 200  # пусто, как будто ничего нет
    db = _load()
    items = [it["record"] | {"_ts": it["ts"]} for it in db["items"] if it.get("token") == token]
    return jsonify(items), 200

if __name__ == "__main__":
    # слушаем на 8080, как ждёт твой app.py (UPSTREAM_BASE и API_VERIFY_URL по умолчанию смотрят сюда)
    app.run(host="127.0.0.1", port=8080, debug=True)
