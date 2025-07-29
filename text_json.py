import re
import json
import copy

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
    "Двигатель внутреннего сгорания (марка, тип)": None,
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
    "Шины": None,
    "Дополнительное оборудование транспортного средства": None,
    "Дата оформления": None,
    "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ": None
}


MULTILINE_FIELDS = [
    "Описание гибридного транспортного средства",
    "Дополнительное оборудование транспортного средства",
    "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ",
    "Электродвигатель электромобиля",  # <-- вот оно!
]


with open("output.txt", "r", encoding="utf-8") as f:
    text = f.read()

lines = [line.rstrip() for line in text.replace('\r', '').split('\n') if line.strip()]
FIELD_NAMES = list(FIELDS_TEMPLATE.keys())

def parse_lab(text):
    pattern = r"ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ\s*([^\(\n]*)"
    match = re.search(pattern, text)
    if match:
        value = match.group(1).strip(":-, \t")
        return value.rstrip(" ,")
    return ""

def extract_simple_field(lines, key):
    for idx, line in enumerate(lines):
        if key in line:
            print(f'! [DEBUG] {key=}, {line=}')  # Посмотри, что реально лежит в строке!
            m = re.search(rf"{re.escape(key)}\s+(.+)", line)
            if m:
                print(f'! [DEBUG MATCH] {m.group(1)=}')
                value = cleanup_value(key, m.group(1))
                if value:
                    return value
            after = line.split(key, 1)[1].lstrip()
            print(f'! [DEBUG SPLIT] {after=}')
            value = cleanup_value(key, after)
            if value:
                return value
            # Если всё ещё пусто — попробуй следующую строку (как раньше)
            next_idx = idx + 1
            while next_idx < len(lines):
                next_line = lines[next_idx].strip()
                value = cleanup_value(key, next_line)
                if value and not any(next_line.startswith(f) for f in FIELD_NAMES):
                    return value
                if any(next_line.startswith(f) for f in FIELD_NAMES):
                    break
                next_idx += 1
    return ""

def extract_multiline_field(lines, key, stop_fields):
    for idx, line in enumerate(lines):
        if line.strip().startswith(key):
            collected = []
            value = line[len(key):].strip(":- \t")
            if value:
                value = cleanup_value(key, value)
                if value:
                    # ТОЛЬКО ДЛЯ МНОГОСТРОЧНЫХ:
                    value = clean_multiline_prefix(value)
                    collected.append(value)
            j = idx + 1
            while j < len(lines):
                l = lines[j].strip()
                if not l:
                    j += 1
                    continue
                if any(l.startswith(f) for f in stop_fields):
                    break
                if re.match(r"^(СЕРИЯ KZ|Таможенный союз|Свидетельство|^\d+$)", l):
                    break
                lval = cleanup_value(key, l)
                if lval:
                    lval = clean_multiline_prefix(lval)
                    collected.append(lval)
                j += 1
            result = " ".join(collected)
            result = re.split(r"(СЕРИЯ KZ|Таможенный союз|Свидетельство|^\d+$)", result)[0]
            return result.strip(" ;\n")
    return ""




STOP_PHRASES = [
    "передняя", "задняя", "рабочая", "запасная", "стояночная",
    "ICCID:", "IMEI:", "МАЯК-01", "Руководитель", "соответствует требованиям технического регламента"
]

def is_stop_line(line):
    # твои же условия (ключи, стоп-фразы, служебные строки)
    l = line.strip().lower()
    if any(l.startswith(f.lower()) for f in FIELD_NAMES):
        return True
    if any(p in l for p in STOP_PHRASES):
        return True
    if re.match(r"^(серия kz|таможенный союз|свидетельство|^\d+$)", l):
        return True
    return False


def clean_multiline_prefix(val):
    # Убирает паразитные "ва", "п)", "ия", "ны", "ии" и др. из начала значения
    return re.sub(r"^(ля|ва|ии|ия|ов|п\)|1\)|вт|в|р|ны)[\s.,:;-]+", "", val.strip(), flags=re.IGNORECASE)


def extract_electric_motor(lines, key):
    for idx, line in enumerate(lines):
        if line.strip().startswith(key):
            # Сразу забираем часть после ключа (даже если пусто)
            value_lines = []
            first_value = line[len(key):].strip(":- \t")
            if first_value:
                value_lines.append(first_value)
            # Собираем все строки, пока не увидим стоп-фразу или ключ
            j = idx + 1
            while j < len(lines):
                l = lines[j].strip()
                if is_stop_line(l):
                    break
                value_lines.append(l)
                j += 1
            result = ' '.join(value_lines)
            result = re.sub(r'\s+', ' ', result)  # убрать двойные пробелы
            result = clean_multiline_prefix(result)   # <--- вот это главное!
            return result.strip(" ;\n")
    return ""

def extract_special_case(lines, key):
    if key == "Технически допустимая максимальная масса транспортного средства, кг":
        for idx, line in enumerate(lines):
            if line.startswith("Технически допустимая максимальная масса транспортного"):
                combined = line
                if idx+1 < len(lines) and "средства, кг" in lines[idx+1]:
                    combined += " " + lines[idx+1]
                m = re.search(r"масса.*?([\d]+)", combined)
                if m:
                    return m.group(1)
        return ""
    if key == "Габаритные размеры, мм":
        dims = {"длина": None, "ширина": None, "высота": None}
        for idx, line in enumerate(lines):
            if line.startswith(key):
                for j in range(idx+1, idx+6):
                    if j >= len(lines): break
                    for subkey in dims.keys():
                        if subkey in lines[j]:
                            m = re.search(r"(\d+)", lines[j])
                            if m:
                                dims[subkey] = m.group(1)
        return dims
    return None

def extract_subfields_multiline(lines, key, subfields, stop_fields):
    result = {k: "" for k in subfields}
    for subkey in subfields:
        pat = re.compile(r"^\s*-\s*" + re.escape(subkey))
        for idx, line in enumerate(lines):
            if pat.match(line):
                collected = []
                value = line[line.find(subkey)+len(subkey):].strip(":- \t")
                if value and value not in ["-", "—"]:
                    collected.append(value)
                j = idx + 1
                while j < len(lines):
                    l = lines[j].strip()
                    if any(l.startswith(f) for f in stop_fields) or \
                        l.startswith("-") or not l or l.isdigit() or l.startswith("СЕРИЯ KZ"):
                        break
                    collected.append(l)
                    j += 1
                result[subkey] = " ".join(collected).strip(" ;\n")
    return result

def cleanup_value(key, value):
    val = value.strip(" .:-,")
    # НЕ надо clean_multiline_prefix здесь
    if not val:
        return ""
    if val in ["п)", "1)", "ля", "ва", "ии", "ия", "ов", "вт", "в", "р", "ны"]:
        return ""
    key_tail = key[-4:].lower()
    if len(val) <= 4 and val.lower() in key_tail:
        return ""
    bad_values = [
        "не выбрано", "выберите значение", "-", "—"
    ]
    if val.lower() in bad_values:
        return ""
    if len(val) <= 2 and not val.isdigit():
        return ""
    return val

def determine_engine_type(result):
    # Считаем пустым, если там был мусор
    e_motor = cleanup_value("Электродвигатель электромобиля", result.get("Электродвигатель электромобиля") or "")
    ice = cleanup_value("Двигатель внутреннего сгорания (марка, тип)", result.get("Двигатель внутреннего сгорания (марка, тип)") or "")
    hybrid = cleanup_value("Описание гибридного транспортного средства", result.get("Описание гибридного транспортного средства") or "")

    if hybrid:
        return "гибридный"
    if e_motor and not ice and not hybrid:
        return "электрический"
    if ice and not e_motor and not hybrid:
        return "внутреннего сгорания"
    return ""


result = copy.deepcopy(FIELDS_TEMPLATE)
result["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = parse_lab(text)

# ---- Сначала длинные поля, потом короткие!
FIELD_NAMES_SORTED = sorted(FIELD_NAMES, key=lambda x: -len(x))
for key in FIELD_NAMES_SORTED:
    if key == "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ":
        continue
    if key == "Электродвигатель электромобиля":
        result[key] = extract_electric_motor(lines, key)
    elif key in [
        "Описание гибридного транспортного средства",
        "Дополнительное оборудование транспортного средства",
        "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ"
    ]:
        result[key] = extract_multiline_field(lines, key, FIELD_NAMES)
    elif key == "Габаритные размеры, мм" or key == "Технически допустимая максимальная масса транспортного средства, кг":
        sp = extract_special_case(lines, key)
        if sp is not None:
            result[key] = sp
    elif key in ["Подвеска(тип)", "Тормозные системы (тип)"]:
        result[key] = extract_subfields_multiline(lines, key, result[key].keys(), FIELD_NAMES)
    elif isinstance(result[key], dict):
        result[key] = extract_subfields_multiline(lines, key, result[key].keys(), FIELD_NAMES)
    else:
        result[key] = extract_simple_field(lines, key)


# Теперь отдельно проставляем тип двигателя!
result["Двигатель"] = determine_engine_type(result)

# Финальная очистка
for key in result:
    if isinstance(result[key], dict):
        for subkey in result[key]:
            if result[key][subkey]:
                result[key][subkey] = re.sub(r'\s+', ' ', result[key][subkey]).strip()
    elif result[key]:
        result[key] = re.sub(r'\s+', ' ', result[key]).strip()


with open("parsed_output.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("✅ Готово! Парсинг Aspose txt → JSON завершён.")
