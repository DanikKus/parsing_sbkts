# final_processor.py
import json
import pandas as pd
import os
import sys
from datetime import datetime
from techreg_client_fixed import TechRegClient  # Ваш рабочий клиент
from typing import List, Dict, Any

# Конфигурация
INPUT_FILE = "input.xlsx"
OUTPUT_FILE = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
LOG_FILE = "processing_log.txt"

def setup_logging():
    """Настраивает логгирование в файл и консоль"""
    class DualLogger:
        def __init__(self):
            self.console = sys.stdout
            self.file = open(LOG_FILE, "a", encoding="utf-8")
        
        def write(self, message):
            self.console.write(message)
            self.file.write(message)
        
        def flush(self):
            self.console.flush()
            self.file.flush()
    
    sys.stdout = DualLogger()
    sys.stderr = DualLogger()

def load_fresh_cookies():
    """
    Загружает свежие куки из Selenium сессии
    Пробует несколько форматов файлов
    """
    cookie_sources = [
        ("requests_cookies.json", "json"),
        ("manual_auth_selenium.json", "manual"),
        ("fresh_cookies.json", "json"),
        ("techreg_cookies.json", "json")
    ]
    
    for file_path, file_type in cookie_sources:
        if os.path.exists(file_path):
            try:
                print(f"Пробуем загрузить куки из: {file_path}")
                
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                cookies = {}
                
                if file_type == "manual":
                    # Формат manual_auth_selenium.json
                    cookies = data.get("cookies", {})
                elif isinstance(data, dict):
                    # Простой JSON словарь
                    cookies = data
                elif isinstance(data, list):
                    # Список словарей (Selenium формат)
                    cookies = {item["name"]: item["value"] for item in data 
                              if "name" in item and "value" in item}
                
                if cookies:
                    print(f"✓ Успешно загружено {len(cookies)} куков")
                    print(f"  Ключи: {list(cookies.keys())}")
                    
                    # Проверяем наличие важных куков
                    important_cookies = ["constructor_creds_for_index", "JSESSIONID"]
                    missing = [c for c in important_cookies if c not in cookies]
                    
                    if missing:
                        print(f"⚠ Отсутствуют важные куки: {missing}")
                    else:
                        print(f"✓ Все важные куки присутствуют")
                    
                    return cookies
                    
            except Exception as e:
                print(f"✗ Ошибка загрузки {file_path}: {e}")
    
    print("⚠ Куки не найдены. Продолжаем без авторизации.")
    return {}

def get_document_column(df: pd.DataFrame) -> str:
    """Определяет колонку с номерами документов"""
    possible_columns = [
        "Документ", "Номер документа", "Document", "Номер", 
        "№ документа", "Certificate", "Свидетельство", "Номер СБКТС",
        "Document Number", "Cert Number"
    ]
    
    for col in possible_columns:
        if col in df.columns:
            return col
    
    # Если не нашли стандартные названия, покажем что есть
    print("Доступные колонки в файле:")
    for col in df.columns:
        print(f"  - {col}")
    
    raise ValueError(f"Не найдена колонка с номерами документов. Возможные названия: {possible_columns}")

def normalize_document_number(doc_num: str) -> str:
    """Нормализует номер документа для поиска"""
    if not doc_num or pd.isna(doc_num):
        return ""
    
    doc_str = str(doc_num).strip()
    
    # Убираем лишние пробелы и нормализуем
    doc_str = ' '.join(doc_str.split())
    
    # Заменяем разные типы тире
    doc_str = doc_str.replace('–', '-').replace('—', '-')
    
    return doc_str

def process_document(tech_client: TechRegClient, doc_num: str) -> Dict[str, Any]:
    """Обрабатывает один документ и возвращает результат"""
    result = {
        "document_number": doc_num,
        "vin": "",
        "status": "",
        "issue_date": "",
        "category": "",
        "bin": "",
        "test_lab": "",
        "found_number": "",
        "techreg_status": "",
        "error": ""
    }
    
    try:
        print(f"\n🔍 Поиск документа: '{doc_num}'")
        
        # Поиск в TechReg
        search_result = tech_client.get_sbkts_by_number(doc_num)
        
        if not search_result.get("ok"):
            reason = search_result.get("reason", "unknown")
            print(f"  ✗ Не найден: {reason}")
            
            result["techreg_status"] = f"Не найден ({reason})"
            
            # Пробуем альтернативные варианты поиска
            if "not_found" in reason:
                alt_result = try_alternative_search(tech_client, doc_num)
                if alt_result.get("ok"):
                    print(f"  ✓ Найден альтернативным поиском")
                    search_result = alt_result
        
        if search_result.get("ok"):
            record = search_result.get("record", {})
            
            result.update({
                "vin": record.get("VIN", ""),
                "status": record.get("Статус", ""),
                "issue_date": record.get("Дата оформления", ""),
                "category": record.get("Категория", ""),
                "bin": record.get("БИН", ""),
                "test_lab": record.get("Испытательная лаборатория", ""),
                "found_number": record.get("N", doc_num),
                "techreg_status": "Найден"
            })
            
            print(f"  ✓ Найден: {record.get('N', '')}")
            if result["vin"]:
                print(f"  ✓ VIN: {result['vin']}")
            else:
                print(f"  ⚠ VIN не указан в документе")
        
        return result
        
    except Exception as e:
        error_msg = str(e)
        print(f"  ✗ Ошибка обработки: {error_msg}")
        
        result.update({
            "techreg_status": f"Ошибка",
            "error": error_msg[:100]
        })
        
        return result

def try_alternative_search(tech_client: TechRegClient, doc_num: str) -> Dict[str, Any]:
    """Пробует альтернативные варианты поиска"""
    alt_variants = [
        doc_num,  # Оригинал
        doc_num.replace("-", " "),  # Без тире
        doc_num.replace(".", " "),  # Без точек
        ' '.join(doc_num.split()[1:]),  # Без префикса "ТС KZ"
        ''.join(filter(str.isdigit, doc_num)),  # Только цифры
    ]
    
    # Кириллица -> латиница
    cyr_to_lat = {"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H",
                  "О":"O","Р":"P","С":"C","Т":"T","Х":"X","У":"Y"}
    lat_version = ''.join(cyr_to_lat.get(ch, ch) for ch in doc_num)
    if lat_version != doc_num:
        alt_variants.append(lat_version)
    
    for variant in alt_variants:
        if variant and len(variant) > 5:  # Минимальная длина для поиска
            try:
                print(f"  Пробуем вариант: '{variant}'")
                result = tech_client.get_sbkts_by_number(variant)
                if result.get("ok"):
                    return result
            except:
                continue
    
    return {"ok": False, "reason": "not_found"}

def main():
    """Основная функция обработки"""
    print("="*80)
    print("ОБРАБОТКА ДОКУМЕНТОВ TECHREG ИЗ EXCEL")
    print(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    try:
        # Настройка логгирования
        setup_logging()
        
        # 1. Загружаем свежие куки
        print("\n1. ЗАГРУЗКА КУКОВ")
        cookies = load_fresh_cookies()
        
        # 2. Инициализируем клиент TechReg
        print("\n2. ИНИЦИАЛИЗАЦИЯ КЛИЕНТА")
        tech_client = TechRegClient(cookies=cookies, verify=False)
        
        # Тестовый запрос для проверки авторизации
        print("   Тестовый запрос...")
        test_result = tech_client.get_sbkts_by_number("ТС KZ А-CN.2630.37353")
        
        if test_result.get("ok"):
            print(f"   ✓ Авторизация успешна! Тестовый VIN: {test_result.get('record', {}).get('VIN')}")
        else:
            print(f"   ⚠ Авторизация может быть проблемной: {test_result.get('reason')}")
        
        # 3. Загружаем Excel файл
        print(f"\n3. ЗАГРУЗКА ФАЙЛА: {INPUT_FILE}")
        
        if not os.path.exists(INPUT_FILE):
            print(f"✗ Файл {INPUT_FILE} не найден!")
            print(f"Убедитесь, что файл находится в папке: {os.getcwd()}")
            return
        
        df = pd.read_excel(INPUT_FILE)
        print(f"   ✓ Загружено строк: {len(df)}")
        print(f"   Колонки: {', '.join(df.columns.tolist())}")
        
        # 4. Определяем колонку с документами
        doc_column = get_document_column(df)
        print(f"   Колонка документов: '{doc_column}'")
        
        # 5. Создаем колонки для результатов
        result_columns = [
            "VIN", "Статус_СБКТС", "Дата_оформления", "Категория_ТС",
            "БИН_лаборатории", "Испытательная_лаборатория",
            "Найденный_номер", "Статус_поиска", "Ошибка"
        ]
        
        for col in result_columns:
            if col not in df.columns:
                df[col] = ""
        
        # 6. Обработка документов
        print(f"\n4. ОБРАБОТКА ДОКУМЕНТОВ")
        print("-" * 80)
        
        total = len(df)
        processed = 0
        found = 0
        errors = 0
        
        for index, row in df.iterrows():
            processed += 1
            
            # Нормализуем номер документа
            doc_num = normalize_document_number(row[doc_column])
            
            if not doc_num:
                print(f"[{processed}/{total}] Пропуск: пустой номер документа")
                df.at[index, "Статус_поиска"] = "Пропущен (пустой номер)"
                continue
            
            print(f"[{processed}/{total}] Обработка: {doc_num}")
            
            # Обрабатываем документ
            result = process_document(tech_client, doc_num)
            
            # Записываем результаты
            df.at[index, "VIN"] = result["vin"]
            df.at[index, "Статус_СБКТС"] = result["status"]
            df.at[index, "Дата_оформления"] = result["issue_date"]
            df.at[index, "Категория_ТС"] = result["category"]
            df.at[index, "БИН_лаборатории"] = result["bin"]
            df.at[index, "Испытательная_лаборатория"] = result["test_lab"]
            df.at[index, "Найденный_номер"] = result["found_number"]
            df.at[index, "Статус_поиска"] = result["techreg_status"]
            df.at[index, "Ошибка"] = result["error"]
            
            # Статистика
            if result["techreg_status"] == "Найден":
                found += 1
            elif "Ошибка" in result["techreg_status"]:
                errors += 1
            
            # Автосохранение каждые N записей
            if processed % 10 == 0:
                temp_file = f"temp_progress_{processed}.xlsx"
                df.to_excel(temp_file, index=False)
                print(f"   💾 Автосохранение: {temp_file}")
        
        # 7. Сохранение результатов
        print(f"\n5. СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
        print("-" * 80)
        
        # Основной файл
        df.to_excel(OUTPUT_FILE, index=False)
        print(f"✓ Основной файл: {OUTPUT_FILE}")
        
        # CSV для удобства
        csv_file = OUTPUT_FILE.replace(".xlsx", ".csv")
        df.to_csv(csv_file, index=False, encoding="utf-8-sig")
        print(f"✓ CSV файл: {csv_file}")
        
        # Файл только с найденными VIN
        if found > 0:
            vin_df = df[df["VIN"].notna() & (df["VIN"] != "")].copy()
            vin_file = f"found_vins_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            vin_df.to_excel(vin_file, index=False)
            print(f"✓ Файл с найденными VIN: {vin_file}")
        
        # 8. Отчет
        print(f"\n6. ОТЧЕТ О ВЫПОЛНЕНИИ")
        print("=" * 80)
        print(f"Всего документов: {total}")
        print(f"Обработано: {processed}")
        print(f"Найдено в TechReg: {found}")
        print(f"Не найдено: {total - found - errors}")
        print(f"Ошибок: {errors}")
        
        if found > 0:
            unique_vins = df[df["VIN"].notna() & (df["VIN"] != "")]["VIN"].nunique()
            print(f"Уникальных VIN найдено: {unique_vins}")
            
            # Сохраняем текстовый отчет
            report_file = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write("ОТЧЕТ ОБ ОБРАБОТКЕ TECHREG\n")
                f.write("=" * 50 + "\n")
                f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Входной файл: {INPUT_FILE}\n")
                f.write(f"Выходной файл: {OUTPUT_FILE}\n")
                f.write(f"Всего документов: {total}\n")
                f.write(f"Найдено: {found}\n")
                f.write(f"Не найдено: {total - found - errors}\n")
                f.write(f"Ошибок: {errors}\n")
                f.write(f"Уникальных VIN: {unique_vins}\n\n")
                
                if unique_vins > 0:
                    f.write("НАЙДЕННЫЕ VIN:\n")
                    for vin in df[df["VIN"].notna() & (df["VIN"] != "")]["VIN"].unique():
                        f.write(f"- {vin}\n")
            
            print(f"✓ Текстовый отчет: {report_file}")
        
        print(f"\n✅ ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
        
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Восстанавливаем стандартный вывод
        if hasattr(sys.stdout, 'file'):
            sys.stdout.file.close()
            sys.stdout = sys.stdout.console

def quick_test():
    """Быстрая проверка работы"""
    print("БЫСТРЫЙ ТЕСТ РАБОТОСПОСОБНОСТИ")
    print("-" * 40)
    
    # Загружаем куки
    cookies = load_fresh_cookies()
    
    # Тестовый клиент
    client = TechRegClient(cookies=cookies, verify=False)
    
    # Тестовые документы
    test_docs = [
        "ТС KZ А-CN.2630.37353",
        "ТС KZ А-CN.2630.37349",
        "ТС KZ А-CN.2680.37353"
    ]
    
    for doc in test_docs:
        print(f"\nТест: {doc}")
        result = client.get_sbkts_by_number(doc)
        
        if result.get("ok"):
            print(f"  ✓ Найден, VIN: {result.get('record', {}).get('VIN')}")
        else:
            print(f"  ✗ {result.get('reason')}")

if __name__ == "__main__":
    print("Выберите режим:")
    print("1. Полная обработка Excel файла")
    print("2. Быстрый тест (проверка работы)")
    
    choice = input("Введите номер (1 или 2): ").strip()
    
    if choice == "2":
        quick_test()
    else:
        main()