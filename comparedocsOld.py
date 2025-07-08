import pdfplumber
import pytesseract
from pdf2image import convert_from_path
import re
import json
import os

FIELDS_TEMPLATE = {
    "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ": None,
    "МАРКА": None,
    "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ": None,
    "ТИП": None,
    "ШАССИ": None, 
    "ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)": None,  
    "ГОД ВЫПУСКА": None,  
    "КАТЕГОРИЯ": None,
    "ЭКОЛОГИЧЕСКИЙ КЛАСС": None,
    "ЗАЯВИТЕЛЬ И ЕГО АДРЕС": None,
    "ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС": None,
    "СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС": None,
    "Колесная формула/ведущие колеса": None,  
    "Схема компоновки транспортного средства": None,
    "Тип кузова/количество дверей (для категории М1)": None,
    "Количество мест спереди/ cзади (для категории М1)": None,
    "Исполнение загрузочного пространства (для категории N)": None,
    "Кабина (для категории N)": None, 
    "Пассажировместимость (для категорий М2, М3)": None,
    "Общий объем багажных отделений (для категории М3 класса III)": None,
    "Количество мест для сидения (для категорий М2, M3, L)": None,
    "Рама (для категории L)": None,
    "Количество осей/колес (для категории О)": None, 
    "Масса транспортного средства в снаряженном состоянии, кг": None,
    "Технически допустимая максимальная масса транспортного средства, кг": None,
    "Габаритные размеры, мм": {"длина": None, "ширина": None, "высота": None},
    "База, мм": None,
    "Колея передних/задних колес, мм": None,
    "Описание гибридного транспортного средства": None,
    "Двигатель": None,
    "Двигатель внутренного сгорания (марка, тип)": None,
    "- количество и расположение цилиндров": None,
    "- рабочий объем цилиндров, см3": None,
    "- степень сжатия": None,
    "- максимальная мощность, кВт (мин.-1)": None,
    "Топливо": None,
    "Система питания (тип)": None,
    "Система зажигания (тип)": None,
    "Система выпуска и нейтрализации отработавших газов": None,
    "Электродвигатель электромобиля": None,
    "Рабочее напряжение, В": None,
    "Максимальная 30-минутная мощность, кВт": None,
    "Вид электромашины": None,
    "Электромашина (марка, тип)": None,
    "Рабочее напряжение, В (электромашина)": None,
    "Максимальная 30-минутная мощность, кВт (электромашина)": None,
    "Устройство накопления энергии": None,
    "Сцепление (марка, тип)": None,
    "Трансмиссия": None,
    "Коробка передач (марка, тип)": None,
    "Редуктор": None,
    "Подвеска(тип)": {"передняя": None, "задняя": None},
    "Рулевое управление (марка, тип)": None,
    "Тормозные системы (тип)": {"рабочая": None, "запасная": None, "стояночная": None},
    "Дополнительное оборудование транспортного средства": None,
    "Дата оформления": None,
    "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ": None

}

def extract_text_pdfplumber(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def extract_text_ocr(file_path):
    images = convert_from_path(file_path)
    text = ""
    for img in images:
        text += pytesseract.image_to_string(img, lang="rus") + "\n"
    return text

def clean_text(text):
    """Очистить текст от лишних пробелов"""
    return re.sub(r"\s+", " ", text.strip())

def is_header(line):
    """Проверка: является ли строка заголовком"""
    headers = [
        "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ", "МАРКА", "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ", "ТИП",
        "ШАССИ", "ИДЕНТИФИКАЦИОННЫЙ НОМЕР", "ГОД ВЫПУСКА", "КАТЕГОРИЯ",
        "ЭКОЛОГИЧЕСКИЙ КЛАСС", "ЗАЯВИТЕЛЬ","- юридический адрес", "ИЗГОТОВИТЕЛЬ", "СБОРОЧНЫЙ ЗАВОД",
         "Колесная формула/ведущие колеса",  # 👈 сюда
        "Схема компоновки транспортного средства",
        "Тип кузова/количество дверей (для категории М1)",
        "Количество мест спереди/ cзади (для категории М1)",
        "Исполнение загрузочного пространства (для категории N)",
        "Кабина (для категории N)",
        "Пассажировместимость (для категорий М2, М3)",
        "Общий объем багажных отделений (для категории М3 класса III)",
        "Количество мест для сидения (для категорий М2, M3, L)",
        "Рама (для категории L)",
        "Количество осей/колес (для категории О)",
        "Масса транспортного средства в снаряженном состоянии, кг",
        "Технически допустимая максимальная масса транспортного средства, кг",
        "Габаритные размеры, мм",
        "База, мм",
        "Колея передних/задних колес, мм",
        "Описание гибридного транспортного средства",
        "Двигатель",
        "Двигатель внутренного сгорания (марка, тип)",
        "- количество и расположение цилиндров",
        "- количество и расположение цилиндров",
        "- рабочий объем цилиндров, см3",
        "- степень сжатия",
        "- максимальная мощность, кВт (мин.-1)",
        "Топливо",
        "Система питания (тип)",
        "Система зажигания (тип)",
        "Система выпуска и нейтрализации отработавших газов",
        "Электродвигатель электромобиля",
        "Рабочее напряжение, В",
        "Максимальная 30-минутная мощность, кВт",
        "Вид электромашины",
        "Электромашина (марка, тип)",
        "Рабочее напряжение, В (электромашина)",
        "Максимальная 30-минутная мощность, кВт (электромашина)",
        "Устройство накопления энергии",
        "Сцепление (марка, тип)",
        "Трансмиссия",
        "Коробка передач (марка, тип)",
        "Редуктор",
        "Подвеска(тип)",
        "Рулевое управление (марка, тип)",
        "Тормозные системы (тип)",
        "-рабочая", 
        "-запасная", 
        "-стояночная",
        "Шины",
        "Дополнительное оборудование транспортного средства",
        "Дата оформления",
        "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ"


        # другие заголовки добавим позже
    ]
    line_clean = line.strip().lower()
    return any(line_clean.startswith(h.lower()) for h in headers)

def extract_value(line, field_name):
    """Ищем заголовок слева и вытаскиваем значение справа"""
    if line.strip().startswith(field_name):
        parts = line.split(field_name, 1)
        if len(parts) > 1:
            return clean_text(parts[1])
    return None

def parse_fields(text):
    """Парсинг ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ, МАРКА, КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ и ТИП"""
    result = json.loads(json.dumps(FIELDS_TEMPLATE))
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    total_lines = len(lines)

    i = 0
    while i < total_lines:
        line = lines[i]
        line = clean_text(line)

        # ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ
        # ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ — многострочная сборка
        if line.startswith("ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"):
            collected_lines = []
            value = extract_value(line, "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ")
            if value:
                collected_lines.append(clean_text(value))

            j = i + 1
            while j < total_lines:
                next_line = lines[j].strip()
                if is_header(next_line):  # Если наткнулись на новый заголовок — остановиться
                    break
                if next_line:
                    collected_lines.append(clean_text(next_line))
                j += 1

            full_text = " ".join(collected_lines)
            result["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = full_text if full_text else ""
            i = j - 1  # Сдвинуть основной индекс

        # МАРКА
        elif line.startswith("МАРКА"):
            value = extract_value(line, "МАРКА")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["МАРКА"] = value

        # КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ
        elif line.startswith("КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"):
            value = extract_value(line, "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] = value

        # ТИП
        elif line.strip() == "ТИП":
            if i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    result["ТИП"] = clean_text(next_line)
                    i += 1
        elif line.startswith("ТИП"):
            value = extract_value(line, "ТИП")
            if value:
                result["ТИП"] = value

                # ШАССИ
        elif line.startswith("ШАССИ"):
            value = extract_value(line, "ШАССИ")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["ШАССИ"] = value

        # ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)
        elif line.startswith("ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"):
            value = extract_value(line, "ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = value

        # ГОД ВЫПУСКА
        elif line.startswith("ГОД ВЫПУСКА"):
            value = extract_value(line, "ГОД ВЫПУСКА")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["ГОД ВЫПУСКА"] = value

        # КАТЕГОРИЯ
        elif line.startswith("КАТЕГОРИЯ"):
            value = extract_value(line, "КАТЕГОРИЯ")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["КАТЕГОРИЯ"] = value

        # ЭКОЛОГИЧЕСКИЙ КЛАСС
        elif line.startswith("ЭКОЛОГИЧЕСКИЙ КЛАСС"):
            value = extract_value(line, "ЭКОЛОГИЧЕСКИЙ КЛАСС")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["ЭКОЛОГИЧЕСКИЙ КЛАСС"] = value

        # ЗАЯВИТЕЛЬ И ЕГО АДРЕС
        elif line.startswith("ЗАЯВИТЕЛЬ И ЕГО АДРЕС"):
            collected_lines = []

            value = extract_value(line, "ЗАЯВИТЕЛЬ И ЕГО АДРЕС")
            if value:
                collected_lines.append(clean_text(value))

            j = i + 1
            lines_read = 0
            line_limit = 2

            while j < total_lines and lines_read < line_limit:
                next_line = lines[j].strip()
                if next_line and not is_header(next_line):
                    collected_lines.append(clean_text(next_line))
                    lines_read += 1
                    j += 1
                else:
                    break

            full_text = " ".join(collected_lines)
            result["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = full_text if full_text else ""
            i = j - 1


        # ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС
        elif line.startswith("ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"):
            value = extract_value(line, "ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] = value

        # СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС
        elif line.startswith("СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"):
            value = extract_value(line, "СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] = value

        # Колесная формула/ведущие колеса
        elif line.startswith("Колесная формула/ведущие колеса"):
            value = extract_value(line, "Колесная формула/ведущие колеса")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["Колесная формула/ведущие колеса"] = value

        # Схема компоновки транспортного средства
        elif line.startswith("Схема компоновки транспортного средства"):
            value = extract_value(line, "Схема компоновки транспортного средства")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["Схема компоновки транспортного средства"] = value

        # Тип кузова/количество дверей (для категории М1)
        elif line.startswith("Тип кузова/количество дверей (для категории М1)"):
            value = extract_value(line, "Тип кузова/количество дверей (для категории М1)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["Тип кузова/количество дверей (для категории М1)"] = value

        # Количество мест спереди/ cзади (для категории М1)
        elif line.startswith("Количество мест спереди/ cзади (для категории М1)"):
            value = extract_value(line, "Количество мест спереди/ cзади (для категории М1)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1]
                if not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
            result["Количество мест спереди/ cзади (для категории М1)"] = value

        elif line.startswith("Исполнение загрузочного пространства (для категории N)"):
            value = extract_value(line, "Исполнение загрузочного пространства (для категории N)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""  # Если это заголовок — значение пустое
            result["Исполнение загрузочного пространства (для категории N)"] = value

        # Кабина (для категории N)
        elif line.startswith("Кабина (для категории N)"):
            value = extract_value(line, "Кабина (для категории N)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Кабина (для категории N)"] = value

        # Пассажировместимость (для категорий М2, М3)
        elif line.startswith("Пассажировместимость (для категорий М2, М3)"):
            value = extract_value(line, "Пассажировместимость (для категорий М2, М3)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Пассажировместимость (для категорий М2, М3)"] = value

        # Общий объем багажных отделений (для категории М3 класса III)
        elif line.startswith("Общий объем багажных отделений (для категории М3 класса III)"):
            value = extract_value(line, "Общий объем багажных отделений (для категории М3 класса III)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Общий объем багажных отделений (для категории М3 класса III)"] = value

        # Количество мест для сидения (для категорий М2, M3, L)
        elif line.startswith("Количество мест для сидения (для категорий М2, M3, L)"):
            value = extract_value(line, "Количество мест для сидения (для категорий М2, M3, L)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Количество мест для сидения (для категорий М2, M3, L)"] = value

        # Рама (для категории L)
        elif line.startswith("Рама (для категории L)"):
            value = extract_value(line, "Рама (для категории L)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Рама (для категории L)"] = value

                # Количество осей/колес (для категории О)
        elif line.startswith("Количество осей/колес (для категории О)"):
            value = extract_value(line, "Количество осей/колес (для категории О)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Количество осей/колес (для категории О)"] = value

        # Масса транспортного средства в снаряженном состоянии, кг
        elif line.startswith("Масса транспортного средства в снаряженном состоянии, кг"):
            value = extract_value(line, "Масса транспортного средства в снаряженном состоянии, кг")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Масса транспортного средства в снаряженном состоянии, кг"] = value

        # Технически допустимая максимальная масса транспортного средства, кг
        elif "Технически допустимая максимальная масса транспортного" in line and i + 1 < total_lines:
            # Склеиваем текущую строку и следующую строку
            merged_line = line + " " + lines[i + 1].strip()

            # Найти место, где заканчивается "Технически допустимая максимальная масса транспортного"
            header_pos = merged_line.find("Технически допустимая максимальная масса транспортного")
            
            if header_pos != -1:
                # Всё, что после этой фразы
                after_header = merged_line[header_pos + len("Технически допустимая максимальная масса транспортного"):].strip()

                # Пытаемся найти первое число
                match = re.search(r"\d+", after_header)
                if match:
                    value = match.group(0)
                else:
                    value = ""
                
                result["Технически допустимая максимальная масса транспортного средства, кг"] = value
                i += 1  # пропускаем следующую строку (склеили!)

        # Габаритные размеры, мм
        elif line.startswith("Габаритные размеры, мм"):
            # После заголовка обычно идут длина, ширина, высота через пробел
            after_header = line[len("Габаритные размеры, мм"):].strip()
            
            if not after_header and i + 1 < total_lines:
                i += 1
                after_header = lines[i].strip()

            # Сначала ищем числа в текущей строке
            dims = re.findall(r"\d+", after_header)

            # Если не хватает чисел, продолжаем искать на следующих строках
            next_i = i
            while len(dims) < 3 and next_i + 1 < total_lines:
                next_i += 1
                next_line = lines[next_i].strip()
                next_dims = re.findall(r"\d+", next_line)
                dims.extend(next_dims)
                i = next_i  # двигаем индекс

            # Теперь заполняем результат
            if dims:
                if len(dims) >= 1:
                    result["Габаритные размеры, мм"]["длина"] = dims[0]
                if len(dims) >= 2:
                    result["Габаритные размеры, мм"]["ширина"] = dims[1]
                if len(dims) >= 3:
                    result["Габаритные размеры, мм"]["высота"] = dims[2]

        # База, мм
        elif line.startswith("База, мм"):
            value = extract_value(line, "База, мм")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["База, мм"] = value

                # Колея передних/задних колес, мм
        elif line.startswith("Колея передних/задних колес, мм"):
            value = extract_value(line, "Колея передних/задних колес, мм")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Колея передних/задних колес, мм"] = value

                    # Описание гибридного транспортного средства
        elif line.startswith("Описание гибридного транспортного средства"):
            collected_lines = []

            # Добавим первую строку, если есть текст сразу после заголовка
            first_value = extract_value(line, "Описание гибридного транспортного средства")
            if first_value:
                collected_lines.append(clean_text(first_value))

            # Собираем строки после заголовка
            j = i + 1
            while j < total_lines:
                next_line = lines[j].strip()

                if is_header(next_line):  # если встретили новый заголовок — выходим
                    break

                collected_lines.append(clean_text(next_line))
                j += 1

            result["Описание гибридного транспортного средства"] = " ".join(collected_lines).strip()
            i = j - 1  # перемещаем указатель, чтобы не повторять


        elif line.lower().startswith("двигатель"):
            # Даже если нет полного "Двигатель внутреннего сгорания" — всё равно пробуем вытащить
            value = extract_value(line, "Двигатель")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Двигатель внутренного сгорания (марка, тип)"] = value

                # - количество и расположение цилиндров
        elif line.startswith("- количество и расположение цилиндров"):
            value = extract_value(line, "- количество и расположение цилиндров")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["- количество и расположение цилиндров"] = value

        # - рабочий объем цилиндров, см3
        elif line.startswith("- рабочий объем цилиндров, см3"):
            value = extract_value(line, "- рабочий объем цилиндров, см3")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["- рабочий объем цилиндров, см3"] = value

        # - степень сжатия
        elif line.startswith("- степень сжатия"):
            value = extract_value(line, "- степень сжатия")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["- степень сжатия"] = value

        # - максимальная мощность, кВт (мин.-1)
        elif line.startswith("- максимальная мощность, кВт (мин.-1)"):
            value = extract_value(line, "- максимальная мощность, кВт (мин.-1)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["- максимальная мощность, кВт (мин.-1)"] = value

                # Топливо
        elif line.startswith("Топливо"):
            value = extract_value(line, "Топливо")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Топливо"] = value

        # Система питания (тип)
        elif line.startswith("Система питания (тип)"):
            value = extract_value(line, "Система питания (тип)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Система питания (тип)"] = value

        # Система зажигания (тип)
        elif line.startswith("Система зажигания (тип)"):
            value = extract_value(line, "Система зажигания (тип)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Система зажигания (тип)"] = value

        # Система выпуска и нейтрализации отработавших газов
        elif line.startswith("Система выпуска и нейтрализации отработавших газов"):
            value = extract_value(line, "Система выпуска и нейтрализации отработавших газов")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Система выпуска и нейтрализации отработавших газов"] = value


        # Электродвигатель электромобиля
        elif line.startswith("Электродвигатель электромобиля"):
            value = extract_value(line, "Электродвигатель электромобиля")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Электродвигатель электромобиля"] = value

        # Рабочее напряжение, В
        elif line.startswith("Рабочее напряжение, В"):
            value = extract_value(line, "Рабочее напряжение, В")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Рабочее напряжение, В"] = value

        # Максимальная 30-минутная мощность, кВт
        elif line.startswith("Максимальная 30-минутная мощность, кВт"):
            value = extract_value(line, "Максимальная 30-минутная мощность, кВт")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Максимальная 30-минутная мощность, кВт"] = value

        # Вид электромашины
        elif line.startswith("Вид электромашины"):
            value = extract_value(line, "Вид электромашины")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Вид электромашины"] = value

        # Электромашина (марка, тип)
        elif line.startswith("Электромашина (марка, тип)"):
            value = extract_value(line, "Электромашина (марка, тип)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Электромашина (марка, тип)"] = value

        # Рабочее напряжение, В (электромашина)
        elif line.startswith("Рабочее напряжение, В (электромашина)"):
            value = extract_value(line, "Рабочее напряжение, В (электромашина)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Рабочее напряжение, В (электромашина)"] = value

        # Максимальная 30-минутная мощность, кВт (электромашина)
        elif line.startswith("Максимальная 30-минутная мощность, кВт (электромашина)"):
            value = extract_value(line, "Максимальная 30-минутная мощность, кВт (электромашина)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Максимальная 30-минутная мощность, кВт (электромашина)"] = value

        # Устройство накопления энергии
        elif line.startswith("Устройство накопления энергии"):
            value = extract_value(line, "Устройство накопления энергии")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Устройство накопления энергии"] = value

        # Сцепление (марка, тип)
        elif line.startswith("Сцепление (марка, тип)"):
            value = extract_value(line, "Сцепление (марка, тип)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Сцепление (марка, тип)"] = value

                # Трансмиссия
        elif line.startswith("Трансмиссия"):
            value = extract_value(line, "Трансмиссия")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Трансмиссия"] = value

        # Коробка передач (марка, тип)
        elif line.startswith("Коробка передач (марка, тип)"):
            value = extract_value(line, "Коробка передач (марка, тип)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Коробка передач (марка, тип)"] = value

        # Редуктор
        elif line.startswith("Редуктор"):
            value = extract_value(line, "Редуктор")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Редуктор"] = value

        # Подвеска(тип) — передняя и задняя
        elif line.startswith("Подвеска(тип)"):
            value_front = ""
            value_rear = ""
            collecting_front = False
            collecting_rear = False

            # Идём по следующим строкам после "Подвеска(тип)"
            j = i + 1
            while j < total_lines:
                current_line = lines[j].strip()

                if is_header(current_line):  # Если новый заголовок — выходим
                    break

                lower_line = current_line.lower()

                # Если нашли "передняя", начинаем собирать переднюю подвеску
                if "передняя" in lower_line:
                    collecting_front = True
                    collecting_rear = False
                    after_keyword = current_line.split("передняя", 1)[-1].strip(":- ")
                    if after_keyword:
                        value_front += " " + after_keyword

                # Если нашли "задняя", переключаемся на заднюю подвеску
                elif "задняя" in lower_line:
                    collecting_front = False
                    collecting_rear = True
                    after_keyword = current_line.split("задняя", 1)[-1].strip(":- ")
                    if after_keyword:
                        value_rear += " " + after_keyword

                # Иначе продолжаем собирать ту подвеску, которую начали
                else:
                    if collecting_front:
                        value_front += " " + current_line
                    elif collecting_rear:
                        value_rear += " " + current_line

                j += 1

            # Сохраняем в результат
            result["Подвеска(тип)"]["передняя"] = clean_text(value_front) if value_front else ""
            result["Подвеска(тип)"]["задняя"] = clean_text(value_rear) if value_rear else ""

            i = j - 1  # Перемещаем основной индекс на конец блока


                # Рулевое управление (марка, тип)
        elif line.startswith("Рулевое управление (марка, тип)"):
            value = extract_value(line, "Рулевое управление (марка, тип)")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Рулевое управление (марка, тип)"] = value

        # Тормозные системы (тип)
        elif line.startswith("Тормозные системы (тип)"):
            value_work = ""
            value_spare = ""
            value_parking = ""

            current_field = None  # какая сейчас система: рабочая / запасная / стояночная

            j = i + 1
            while j < total_lines:
                current_line = lines[j].strip()

                if is_header(current_line):
                    break  # нашли новый заголовок — прекращаем сбор

                lower_line = current_line.lower()

                # Переход к новой подсекции
                if lower_line.startswith("- рабочая"):
                    current_field = "рабочая"
                    after_keyword = current_line.split("рабочая", 1)[-1].strip(":- ")
                    if after_keyword:
                        value_work += " " + after_keyword

                elif lower_line.startswith("- запасная"):
                    current_field = "запасная"
                    after_keyword = current_line.split("запасная", 1)[-1].strip(":- ")
                    if after_keyword:
                        value_spare += " " + after_keyword

                elif lower_line.startswith("- стояночная"):
                    current_field = "стояночная"
                    after_keyword = current_line.split("стояночная", 1)[-1].strip(":- ")
                    if after_keyword:
                        value_parking += " " + after_keyword

                else:
                    # Это продолжение текста предыдущего блока
                    if current_field == "рабочая":
                        value_work += " " + current_line
                    elif current_field == "запасная":
                        value_spare += " " + current_line
                    elif current_field == "стояночная":
                        value_parking += " " + current_line

                j += 1

            # Чистим и сохраняем результаты
            result["Тормозные системы (тип)"]["рабочая"] = clean_text(value_work) if value_work else ""
            result["Тормозные системы (тип)"]["запасная"] = clean_text(value_spare) if value_spare else ""
            result["Тормозные системы (тип)"]["стояночная"] = clean_text(value_parking) if value_parking else ""

            i = j - 1  # Перемещаем основной индекс

                # Шины
        elif line.startswith("Шины"):
            value = extract_value(line, "Шины")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Шины"] = value

        # Дополнительное оборудование транспортного средства
        elif line.startswith("Дополнительное оборудование транспортного средства"):
            collected_lines = []

            value = extract_value(line, "Дополнительное оборудование транспортного средства")
            if value:
                collected_lines.append(clean_text(value))

            j = i + 1
            line_limit = 2  # читаем максимум 2 дополнительные строки
            lines_read = 0

            while j < total_lines and lines_read < line_limit:
                next_line = lines[j].strip()
                if next_line and not is_header(next_line):
                    collected_lines.append(clean_text(next_line))
                    lines_read += 1
                j += 1

            full_text = " ".join(collected_lines)
            result["Дополнительное оборудование транспортного средства"] = full_text if full_text else ""
            i = j - 1


        # Дата оформления
        elif line.startswith("Дата оформления"):
            value = extract_value(line, "Дата оформления")
            if not value and i + 1 < total_lines:
                next_line = lines[i + 1].strip()
                if next_line and not is_header(next_line):
                    value = clean_text(next_line)
                    i += 1
                else:
                    value = ""
            result["Дата оформления"] = value

                # ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ
        elif "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ" in line.upper():
            value = extract_value(line, "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ")
            j = i + 1

            # Собираем несколько строк, пока не встречаем новый заголовок
            collected_lines = []
            if value:
                collected_lines.append(clean_text(value))

            while j < total_lines:
                next_line = lines[j].strip()
                if is_header(next_line):  # Если это новый заголовок — останавливаемся
                    break
                if next_line:  # Только непустые строки добавляем
                    collected_lines.append(clean_text(next_line))
                j += 1

            # Объединяем все собранные строки
            full_text = " ".join(collected_lines)
            result["ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ"] = full_text if full_text else ""

            i = j - 1  # Перемещаем основной индекс


        i += 1
        
    return result

def save_json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    test_folder = os.path.join(os.getcwd(), "test")
    pdf_files = [f for f in os.listdir(test_folder) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print("❌ Нет PDF-документов в папке test")
        exit(1)

    pdf_path = os.path.join(test_folder, pdf_files[0])
    print(f"📄 Обрабатывается файл: {pdf_files[0]}")

    txt = extract_text_pdfplumber(pdf_path)
    if not txt or len(txt) < 100:
        print("⚠️ Текст не найден, пробуем OCR...")
        txt = extract_text_ocr(pdf_path)

    # основной парсинг
    parsed = parse_fields(txt)
    
    # --- 1. ПОСТОБРАБОТКА ДЛЯ ОДНОГО ДВИГАТЕЛЯ (БЕВ/обычный) ---
    m_block = re.search(
        r"Электродвигатель электромобиля\s*(.*?)\nУстройство накопления энергии",
        txt, re.S
    )
    if m_block:
        block = m_block.group(1).strip()
        parsed["Электродвигатель электромобиля"] = [
            s.strip() for s in block.split(";") if s.strip()
        ]

    m1 = re.search(r"Рабочее напряжение, В\s*([\d\.]+)", txt)
    if m1:
        parsed["Рабочее напряжение, В"] = m1.group(1)

    m2 = re.search(r"Максимальная 30-минутная мощность, кВт\s*([\d\.]+)", txt)
    if m2:
        parsed["Максимальная 30-минутная мощность, кВт"] = m2.group(1)

    # --- 2. ФИКС ДЛЯ ДВУХ ДВИГАТЕЛЕЙ (ГИБРИД) ---
    def split_list_from_string(val):
        """Разделяет строку на список по запятой или точке с запятой, убирает пустые"""
        if not val:
            return []
        if isinstance(val, list):  # уже список
            return val
        return [x.strip() for x in re.split(r"[;,]", val) if x.strip()]

    def is_hybrid_motor_case(parsed):
        """
        Определяем, что перед нами гибрид с двумя электродвигателями:
        - В поле Электромашина (марка, тип) — два значения
        - В полях "Рабочее напряжение, В" и "Максимальная 30-минутная мощность, кВт" — по 2 значения
        """
        brands = split_list_from_string(parsed.get("Электромашина (марка, тип)"))
        voltages = split_list_from_string(parsed.get("Рабочее напряжение, В"))
        powers = split_list_from_string(parsed.get("Максимальная 30-минутная мощность, кВт"))
        return len(brands) == 2 and len(voltages) == 2 and len(powers) == 2

    if is_hybrid_motor_case(parsed):
        brands = split_list_from_string(parsed["Электромашина (марка, тип)"])
        voltages = split_list_from_string(parsed["Рабочее напряжение, В"])
        powers = split_list_from_string(parsed["Максимальная 30-минутная мощность, кВт"])
        # Заполняем основные поля для BEV пустыми (если есть)
        parsed["Электродвигатель электромобиля"] = ""
        parsed["Рабочее напряжение, В"] = voltages[0]
        parsed["Максимальная 30-минутная мощность, кВт"] = powers[0]
        parsed["Рабочее напряжение, В (электромашина)"] = voltages[1]
        parsed["Максимальная 30-минутная мощность, кВт (электромашина)"] = powers[1]
        parsed["Электромашина (марка, тип)"] = ", ".join(brands)

    out_path = os.path.splitext(pdf_path)[0] + "_parsed.json"
    save_json(parsed, out_path)

    print(f"✅ Данные сохранены в {os.path.basename(out_path)}")
    for key, val in parsed.items():
        print(f"{key}: {val}")

def extract_text_from_pdf(file_path):
    """Обертка для извлечения текста из PDF: сначала pdfplumber, если не найден текст — OCR"""
    text = extract_text_pdfplumber(file_path)
    if not text or len(text.strip()) < 100:
        print("⚠️ Текст не найден через pdfplumber, пробуем OCR...")
        text = extract_text_ocr(file_path)
    return text
