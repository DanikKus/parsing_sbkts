from flask import Flask, render_template, request, jsonify
from parse_pts_json import parse_vehicle_data_from_url
from parse_aspose import extract_text_from_pdf   # твоя функция получения текста
from parse_fields import parse_fields  # твой текст→json парсер
import shutil
import requests
import os
import fitz  # pymupdf
import tempfile
import threading
import time
import webbrowser
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')
from auth_token_selenium import get_token_and_cookies_via_selenium, save_auth_to_cache, load_auth_from_cache

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Логин и пароль обязательны'}), 400

    try:
        token, cookies = get_token_and_cookies_via_selenium(username, password)
        return jsonify({'success': True, 'token': token})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

from parse_pts_json import parse_vehicle_data_from_url, check_violation_point5

@app.route('/parse_site', methods=['POST'])
def parse_site():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "Не передан URL"}), 400

    result = parse_vehicle_data_from_url(url)
    violation = check_violation_point5(result)

    # Переставляем дату оформления наверх
    if "Дата оформления" in result:
        reordered = {
            "Дата оформления": result.pop("Дата оформления"),  # сначала дата оформления
            **result  # потом все остальные поля
        }
    else:
        reordered = result

    return jsonify({
        "fields": reordered,
        "violation_point5": violation
    })


@app.route('/check_token_status')
def check_token_status():
    try:
        token, cookies = load_auth_from_cache()
        if not token or not cookies:
            return jsonify({"status": "missing", "message": "Токен или cookies отсутствуют"}), 200

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # ➕ Пустой payload с параметрами, которые сервер ожидает
        payload = {
            "page": 1,
            "pageSize": 1
        }

        response = requests.post(
            "https://pts.gov.kz/api/ComplienceDocument/GetList",
            headers=headers,
            cookies=cookies,
            json=payload,
            timeout=10,
            verify=False
        )

        if response.status_code == 200:
            return jsonify({"status": "valid"}), 200
        elif response.status_code in (401, 403):
            return jsonify({"status": "expired"}), 200
        else:
            return jsonify({"status": "error", "code": response.status_code}), 200

    except Exception as e:
        print(f"❌ Ошибка токен-проверки: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    
@app.route('/reset_token', methods=['POST'])
def reset_token():
    try:
        if os.path.exists("auth_cache.json"):
            os.remove("auth_cache.json")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/relogin', methods=['POST'])
def relogin():
    try:
        cache_file = "auth_cache.json"
        print(f"Попытка удалить кэш: {os.path.abspath(cache_file)}")
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print("✅ Кэш удален!")
        else:
            print("❗️Кэш не найден (может уже удалён).")

        from auth_token_selenium import get_token_and_cookies_via_selenium, save_auth_to_cache

        print("Запуск авторизации через Selenium...")
        token, cookies = get_token_and_cookies_via_selenium()
        print(f"Токен получен: {token[:15]}...")  # Только первые символы
        save_auth_to_cache(token, cookies)
        print("✅ Новый токен сохранён!")

        return jsonify({"success": True, "token": token})
    except Exception as e:
        print(f"❌ Ошибка при relogin: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/parse_pdf_file', methods=['POST'])
def parse_pdf_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400

    file = request.files['file']
    if not file.filename.endswith(".pdf"):
        return jsonify({'error': 'Неверный формат файла'}), 400

    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name  # Сохранили путь

    # !!! Важно: tmp уже закрыт, теперь можно безопасно читать
    text = extract_text_from_pdf(tmp_path)  # aspose → текст

    # Не забудь удалить файл после парса!
    import os
    os.remove(tmp_path)

    data = parse_fields(text)
    return jsonify(data)


@app.route('/parse_pdf', methods=['POST'])
def parse_pdf():
    data = request.get_json()
    pdf_url = data.get('url')

    # Скачиваем PDF во временный файл
    response = requests.get(pdf_url)
    if response.status_code != 200:
        return jsonify({"error": "Ошибка загрузки PDF"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    text = extract_text_from_pdf(tmp_path)  # aspose → текст
    result = parse_fields(text)             # текст → JSON
    # result = postprocess_ev_fields(result, text)  # если надо

    os.remove(tmp_path)
    return jsonify(result)



def open_browser():
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == '__main__':

      # ✅ 2. запускаем браузер в потоке
    threading.Thread(target=open_browser).start()

    app.run(debug=True)
