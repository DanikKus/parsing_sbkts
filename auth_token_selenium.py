# auth_token_selenium.py
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import json, os, time

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

def _mk_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    # Если нужен явный путь к Chrome: opts.binary_location = "/usr/bin/google-chrome"

    # Системный chromedriver, если есть; иначе — через webdriver_manager
    drv_path = "/usr/bin/chromedriver"
    service = ChromeService(drv_path) if os.path.exists(drv_path) else ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)

def get_token_and_cookies_via_selenium(username: str | None = None, password: str | None = None, headless: bool = True):
    d = _mk_driver(headless=headless)
    try:
        d.get("https://pts.gov.kz/login")

        if username and password:
            # Найти поля логина/пароля — подгони селекторы под текущую верстку PTS
            WebDriverWait(d, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input")))
            inputs = d.find_elements(By.CSS_SELECTOR, "input")
            user_el = next((i for i in inputs if (i.get_attribute("type") or "").lower() in ("text","email")), None)
            pass_el = next((i for i in inputs if (i.get_attribute("type") or "").lower() == "password"), None)
            if not user_el or not pass_el:
                raise Exception("Не найдено поле логина или пароля")
            user_el.clear(); user_el.send_keys(username)
            pass_el.clear(); pass_el.send_keys(password)

            btn = d.find_element(By.XPATH, "//button[contains(., 'Войти') or contains(., 'Login')]")
            btn.click()

        # Ждём появления JWT в localStorage
        token = None
        for _ in range(60):
            try:
                token = d.execute_script("return JSON.parse(localStorage.getItem('user'))?.token")
                if token:
                    break
            except Exception:
                pass
            time.sleep(1)

        if not token:
            raise Exception("JWT не найден в localStorage после логина")

        cookies = {c["name"]: c["value"] for c in d.get_cookies()}
        save_auth_to_cache(token, cookies)
        return token, cookies
    finally:
        d.quit()
