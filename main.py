import requests
import json
import time
import io
import gzip
from datetime import datetime
from requests.adapters import HTTPAdapter, Retry
from http.client import IncompleteRead
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === Настройки ===
CACHE_FILE = "auth_cache.json"
OUTPUT_FILE = "filtered_passports_by_lab.json"
BASE_URL = "https://www.pts.gov.kz/api/DigitalPassport/getList"
PAGE_SIZE = 50

# === HTTP-сессия с retry ===
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)


# === Загрузка токена и cookies ===
def load_token_and_cookies():
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
        return cache["token"], cache["cookies"]


# === Читаемый формат даты ===
def format_datetime(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d.%m.%Y")
    except:
        return value


# === Получение страницы с gzip-поддержкой ===
def fetch_page(page, token, cookies):
    payload = {
        "page": page,
        "pageSize": PAGE_SIZE,
        "sortField": [],
        "direction": [],
        "filter": {
            "typeCode": None,
            "search": None
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "gzip"
    }

    try:
        response = session.post(BASE_URL, headers=headers, cookies=cookies, json=payload,
                                verify=False, timeout=30, stream=True)
        response.raise_for_status()

        raw_data = response.raw.read()
        if response.headers.get('Content-Encoding') == 'gzip':
            data = gzip.GzipFile(fileobj=io.BytesIO(raw_data)).read().decode('utf-8')
        else:
            data = raw_data.decode('utf-8')

        json_data = json.loads(data)
        return json_data.get("data", {}).get("data", []), json_data.get("data", {}).get("total", 0)

    except IncompleteRead as e:
        print(f"❌ IncompleteRead: {e}")
        return [], 0
    except Exception as e:
        print(f"❌ Ошибка на странице {page}: {e}")
        return [], 0


# === Главная функция ===
def main():
    token, cookies = load_token_and_cookies()
    result = []

    print("🔄 Загружается первая страница...")
    records, total_records = fetch_page(1, token, cookies)
    total_pages = (total_records + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"ℹ️ Всего записей: {total_records}, страниц: {total_pages}")

    for page in range(1, total_pages + 1):
        print(f"📄 Обработка страницы {page}/{total_pages}")
        records, _ = fetch_page(page, token, cookies)

        for r in records:
            authority = r.get("authorityName", "").lower()
            org_name = (r.get("aspNetUser", {}).get("organization") or {}).get("nameRu", "").lower()
            doc_date = r.get("docDateFrom", "")
            doc_number = (r.get("complienceDocument") or {}).get("docNumber", "")

            result.append({
                "docNumber": doc_number,
                "VIN": r.get("vehicleIdentityNumberId", ""),
                "Марка": (r.get("vehicleMakeNameNsi") or {}).get("nameRu", ""),
                "Коммерческое имя": r.get("vehicleCommercialName", ""),
                "Дата документа": format_datetime(doc_date),
                "Лаборатория": r.get("authorityName", ""),
                "Организация": (r.get("aspNetUser", {}).get("organization") or {}).get("nameRu", "")
            })

        time.sleep(0.2)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Найдено {len(result)} паспортов")
    print(f"💾 Сохранено в файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
