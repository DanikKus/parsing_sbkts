import requests
import json

def send_parsed_result(
    source_type,
    site_json,
    pdf_json,
    errors_json,
    user_comment,
    jwt_token=None   # если потребуется авторизация
):
    url = "http://localhost:8080/api/parsed/save"

    # Объединяем site/pdf для поля resultJson (по аналогии с твоим UI)
    result_json = {
        "site": site_json,
        "pdf": pdf_json
    }

    dto = {
        "sourceType": source_type,              # например, 'PTS'
        "resultJson": json.dumps(result_json),  # СТРОКА!
        "errorsJson": json.dumps(errors_json),  # СТРОКА!
        "userComment": user_comment,
        "status": "pending",                    # или не указывать, если на бэке по умолчанию
        "adminComment": "",
        "rejectReason": ""
    }

    headers = {"Content-Type": "application/json"}
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"

    resp = requests.post(url, data=json.dumps(dto), headers=headers)
    return resp.status_code, resp.text
