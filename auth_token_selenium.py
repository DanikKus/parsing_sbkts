from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import json
import os
import time

AUTH_CACHE_PATH = "auth_cache.json"

def save_auth_to_cache(token, cookies_dict):
    with open(AUTH_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"token": token, "cookies": cookies_dict}, f, ensure_ascii=False)

def load_auth_from_cache():
    if os.path.exists(AUTH_CACHE_PATH):
        with open(AUTH_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("token"), data.get("cookies")
    return None, None

def get_token_and_cookies_via_selenium():
    options = Options()
    options.add_experimental_option("detach", True)  # Чтобы браузер не закрывался
    driver = webdriver.Chrome(options=options)

    driver.get("https://pts.gov.kz/login")
    print("🌐 Открыл страницу авторизации. Введи логин и пароль и нажми 'Войти'.")

    # Ждём появления токена в localStorage (максимум 120 секунд)
    token = None
    max_wait_time = 120  # секунд
    start_time = time.time()

    while time.time() - start_time < max_wait_time:
        try:
            token = driver.execute_script("return JSON.parse(localStorage.getItem('user'))?.token")
            if token:
                break
        except Exception:
            pass
        time.sleep(2)  # Пауза 2 секунды перед новой проверкой

    if not token:
        driver.quit()
        raise Exception("❌ Токен не найден. Возможно, неправильный логин или пароль.")

    print("✅ Токен успешно получен.")

    cookies = driver.get_cookies()
    cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}

    driver.quit()

    save_auth_to_cache(token, cookies_dict)
    return token, cookies_dict
