# -*- coding: utf-8 -*-
"""
Отладочный скрипт: сохраняет сырой HTML-ответ customs.gov.ru для нескольких VIN.
Запускать: python customs_debug.py
"""
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path

CUSTOMS_URL = "https://customs.gov.ru/cars"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

try:
    import truststore
    truststore.inject_into_ssl()
    print("[ssl] truststore injected")
except Exception:
    print("[ssl] truststore not available, using certifi")

VINS = [
    ("LS4ASE2E1SD127308", "Changan (CN) — тестовый"),
    ("XTA211440L2751000", "LADA (RU) — российский"),
    ("WDD2050481R123456", "Mercedes (DE) — европейский"),
]

OUT_DIR = Path("customs_debug")
OUT_DIR.mkdir(exist_ok=True)


def get_csrf(html: str):
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "_token"})
    if inp and inp.get("value"):
        return inp["value"]
    meta = soup.find("meta", attrs={"name": re.compile(r"csrf-token", re.I)})
    if meta and meta.get("content"):
        return meta["content"]
    return None


def fetch_vin(vin: str, label: str):
    print(f"\n{'='*60}")
    print(f"VIN: {vin}  ({label})")

    with requests.Session() as s:
        s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # STEP 1 — GET страницы (получаем CSRF + куки)
        print("  [1] GET", CUSTOMS_URL)
        try:
            r1 = s.get(CUSTOMS_URL, timeout=20)
            r1.raise_for_status()
        except Exception as e:
            print(f"  [1] ОШИБКА GET: {e}")
            return

        print(f"  [1] status={r1.status_code}, "
              f"content-type={r1.headers.get('Content-Type','?')[:60]}, "
              f"len={len(r1.text)}")

        token = get_csrf(r1.text)
        print(f"  [1] CSRF token: {token[:20]+'...' if token else 'НЕ НАЙДЕН'}")
        if not token:
            (OUT_DIR / f"{vin}_step1_no_token.html").write_text(r1.text, encoding="utf-8")
            print("  [!] сохранён step1 HTML для диагностики")
            return

        # STEP 2 — POST с VIN
        data = {"vin": vin, "_token": token}
        headers = {
            "Referer": CUSTOMS_URL,
            "Origin": "https://customs.gov.ru",
            "X-CSRF-TOKEN": token,
            "X-Requested-With": "XMLHttpRequest",
        }
        print(f"  [2] POST {CUSTOMS_URL}  data={{'vin': '{vin}', '_token': '...'}}")
        try:
            r2 = s.post(CUSTOMS_URL, data=data, headers=headers, timeout=20)
            r2.raise_for_status()
        except Exception as e:
            print(f"  [2] ОШИБКА POST: {e}")
            return

        print(f"  [2] status={r2.status_code}, "
              f"content-type={r2.headers.get('Content-Type','?')[:60]}, "
              f"len={len(r2.text)}")

        # Сохраняем полный HTML
        safe_label = re.sub(r"[^\w\-]", "_", label)
        html_path = OUT_DIR / f"{vin}_{safe_label}.html"
        html_path.write_text(r2.text, encoding="utf-8")
        print(f"  [2] HTML saved -> {html_path}")

        # --- Диагностика: ищем блок страны ---
        soup = BeautifulSoup(r2.text, "html.parser")

        print("\n  --- ДИАГНОСТИКА СТРАНЫ ---")

        # 1) img[src*="/flags/"]
        flag_imgs = soup.select('img[src*="/flags/"]')
        if flag_imgs:
            for img in flag_imgs:
                print(f"  [flags-img] src={img.get('src')!r}  "
                      f"alt={img.get('alt')!r}  "
                      f"title={img.get('title')!r}")
                parent = img.parent
                print(f"    parent tag: <{parent.name} class={parent.get('class')}> "
                      f"text={parent.get_text(' ', strip=True)!r}")
        else:
            print("  [flags-img] НЕТ img[src*='/flags/'] на странице")

        # 2) Все .vin-check__card-title
        titles = soup.select(".vin-check__card-title")
        if titles:
            print(f"\n  [.vin-check__card-title] найдено: {len(titles)}")
            for t in titles:
                print(f"    {t.get_text(' ', strip=True)!r}")
        else:
            print("\n  [.vin-check__card-title] НЕТ таких элементов")

        # 3) Все .vin-check__card-info
        infos = soup.select(".vin-check__card-info")
        if infos:
            print(f"\n  [.vin-check__card-info] найдено: {len(infos)}")
            for inf in infos:
                print(f"    {inf.get_text(' ', strip=True)!r}")
        else:
            print("\n  [.vin-check__card-info] НЕТ таких элементов")

        # 4) Поиск любых текстов "страна" / "country"
        print("\n  [текст 'стран'/'country'] поиск в тексте страницы:")
        found_any = False
        for tag in soup.find_all(string=re.compile(r"стран|country", re.I)):
            parent = tag.parent
            sibling_text = ""
            nxt = parent.find_next_sibling()
            if nxt:
                sibling_text = nxt.get_text(" ", strip=True)
            print(f"    text={tag.strip()!r}  "
                  f"tag=<{parent.name} class={parent.get('class')}> "
                  f"→ sibling={sibling_text!r}")
            found_any = True
        if not found_any:
            print("    Слова 'страна'/'country' в тексте страницы НЕ НАЙДЕНЫ")

        # 5) Все dl/dt/dd
        dts = soup.find_all("dt")
        if dts:
            print(f"\n  [dl/dt/dd] найдено dt: {len(dts)}")
            for dt in dts:
                dd = dt.find_next_sibling("dd")
                print(f"    dt={dt.get_text(' ',strip=True)!r}  "
                      f"dd={dd.get_text(' ',strip=True) if dd else 'нет'!r}")
        else:
            print("\n  [dl/dt/dd] НЕТ элементов dt")

        # 6) Проверка «сведения отсутствуют»
        page_lower = soup.get_text(" ", strip=True).lower()
        if "сведения отсутствуют" in page_lower:
            print("\n  [!] Страница содержит 'сведения отсутствуют' — VIN не найден")
        else:
            print("\n  [ok] 'сведения отсутствуют' в тексте нет — запись найдена")

        # 7) Сохраняем фрагмент вокруг .vin-check__card
        card = soup.select_one(".vin-check__card") or soup.select_one('[class*="vin-check"]')
        if card:
            frag_path = OUT_DIR / f"{vin}_{safe_label}_card_fragment.html"
            frag_path.write_text(card.prettify(), encoding="utf-8")
            print(f"\n  [card] fragment saved -> {frag_path}")
        else:
            print("\n  [card] .vin-check__card NOT FOUND -- saving <body>")
            body = soup.find("body")
            frag_path = OUT_DIR / f"{vin}_{safe_label}_body_fragment.html"
            frag_path.write_text((body or soup).prettify()[:50000], encoding="utf-8")
            print(f"  [body] fragment -> {frag_path}")


if __name__ == "__main__":
    for vin, label in VINS:
        fetch_vin(vin, label)
    print(f"\n\nГотово. Все файлы в папке: {OUT_DIR.resolve()}")
