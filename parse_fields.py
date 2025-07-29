# parse_fields.py

import re
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
    "Электродвигатель электромобиля",
]

FIELD_NAMES = list(FIELDS_TEMPLATE.keys())

STOP_PHRASES = [
    "передняя", "задняя", "рабочая", "запасная", "стояночная",
    "ICCID:", "IMEI:", "МАЯК-01", "Руководитель", "соответствует требованиям технического регламента"
]

def extract_category(lines):
    for idx, line in enumerate(lines):
        norm = line.lower().replace("ё", "е")
        if "категори" in norm:
            parts = re.split(r"категори[яи]:?", norm, maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                value = parts[1].strip(" .:-,;")
                match = re.match(r'([MNOL][0-9]{0,2})', value, re.IGNORECASE)
                if match:
                    return match.group(1).upper()
                return value.split()[0].upper()
            elif idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                match = re.match(r'([MNOL][0-9]{0,2})', next_line, re.IGNORECASE)
                if match:
                    return match.group(1).upper()
                return next_line.split()[0].upper()
    # Если не найдено по слову — ищем отдельную строку
    for line in lines:
        line_clean = line.strip().upper()
        if re.fullmatch(r'[MNOL][0-9]{0,2}', line_clean):
            return line_clean
    return ""

def extract_commercial_name(lines):
    for idx, line in enumerate(lines):
        # Кейс 1: ключ и значение в одной строке
        m = re.search(r"КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ\s*([A-Za-zА-Яа-я0-9\- ]+)", line, re.IGNORECASE)
        if m:
            value = m.group(1).strip(" .:-,;")
            if value:
                return value

        # Кейс 2: разрыв на две строки: "КОММЕРЧЕСКОЕ" [next line] "НАИМЕНОВАНИЕ [X5]"
        if "КОММЕРЧЕСКОЕ" in line.upper():
            # Следующая строка может содержать НАИМЕНОВАНИЕ и значение
            if idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                if next_line.upper().startswith("НАИМЕНОВАНИЕ"):
                    # Может быть: "НАИМЕНОВАНИЕ X5" или "НАИМЕНОВАНИЕ: X5"
                    parts = re.split(r"НАИМЕНОВАНИЕ[:\s]*", next_line, flags=re.IGNORECASE)
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip(" .:-,;")
                    # Может быть значение ещё через строку (если был просто перенос)
                    if idx + 2 < len(lines):
                        after = lines[idx + 2].strip()
                        if after and not after.upper().startswith("ТИП") and len(after) < 30:
                            return after.strip(" .:-,;")
    return ""


def parse_fields(text: str) -> dict:
    lines = [line.rstrip() for line in text.replace('\r', '').split('\n') if line.strip()]
    result = copy.deepcopy(FIELDS_TEMPLATE)

    result["КАТЕГОРИЯ"] = extract_category(lines)

    def parse_lab(text):
        pattern = r"ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ\s*([^\(\n]*)"
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip(":-, \t")
            return value.rstrip(" ,")
        return ""

    def extract_simple_field(lines, key):
        key_low = key.lower()
        for idx, line in enumerate(lines):
            if key_low in line.lower():
                # ключ и значение в одной строке
                m = re.search(rf"{re.escape(key)}\s*([^\n]+)", line, re.IGNORECASE)
                if m:
                    value = cleanup_value(key, m.group(1))
                    if value:
                        return value
                after = line.lower().split(key_low, 1)[1].lstrip(" .:-\t")
                if after:
                    value = cleanup_value(key, after)
                    if value:
                        return value
                if idx + 1 < len(lines):
                    next_line = lines[idx + 1].strip()
                    value = cleanup_value(key, next_line)
                    if value and not any(next_line.startswith(f) for f in FIELD_NAMES):
                        return value
            # спецблок для "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"
            if key == "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ":
                if "коммерческое" in line.lower() and idx + 1 < len(lines):
                    next_line = lines[idx + 1].strip()
                    if "наименование" in next_line.lower():
                        parts = next_line.split("наименование", 1)
                        if len(parts) > 1:
                            value = cleanup_value(key, parts[1])
                            if value:
                                return value
                        if idx + 2 < len(lines):
                            after = lines[idx + 2].strip()
                            value = cleanup_value(key, after)
                            if value:
                                return value
        return ""


   
    def extract_multiline_field(lines, key, stop_fields):
        for idx, line in enumerate(lines):
            if line.strip().startswith(key):
                collected = []
                value = line[len(key):].strip(":- \t")
                if value:
                    value = cleanup_value(key, value)
                    if value:
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
                result_str = " ".join(collected)
                result_str = re.split(r"(СЕРИЯ KZ|Таможенный союз|Свидетельство|^\d+$)", result_str)[0]
                return result_str.strip(" ;\n")
        return ""

    def is_stop_line(line):
        l = line.strip().lower()
        if any(l.startswith(f.lower()) for f in FIELD_NAMES):
            return True
        if any(p in l for p in STOP_PHRASES):
            return True
        if re.match(r"^(серия kz|таможенный союз|свидетельство|^\d+$)", l):
            return True
        return False

    def clean_multiline_prefix(val):
        return re.sub(r"^(ля|ва|ии|ия|ов|п\)|1\)|вт|в|р|ны)[\s.,:;-]+", "", val.strip(), flags=re.IGNORECASE)

    def extract_electric_motor(lines, key):
        for idx, line in enumerate(lines):
            if line.strip().startswith(key):
                value_lines = []
                first_value = line[len(key):].strip(":- \t")
                if first_value:
                    value_lines.append(first_value)
                j = idx + 1
                while j < len(lines):
                    l = lines[j].strip()
                    if is_stop_line(l):
                        break
                    value_lines.append(l)
                    j += 1
                result_str = ' '.join(value_lines)
                result_str = re.sub(r'\s+', ' ', result_str)
                result_str = clean_multiline_prefix(result_str)
                return result_str.strip(" ;\n")
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
        result_ = {k: "" for k in subfields}
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
                    result_[subkey] = " ".join(collected).strip(" ;\n")
        return result_

    def cleanup_value(key, value):
        val = value.strip(" .:-,")
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
        e_motor = cleanup_value("Электродвигатель электромобиля", result.get("Электродвигатель электромобиля") or "")
        ice = cleanup_value("Двигатель внутреннего сгорания (марка, тип)", result.get("Двигатель внутреннего сгорания (марка, тип)") or "")
        hybrid = cleanup_value("Описание гибридного транспортного средства", result.get("Описание гибридного транспортного средства") or "")
        if hybrid:
            return "Гибридное транспортное средство	"
        if e_motor and not ice and not hybrid:
            return "электрический"
        if ice and not e_motor and not hybrid:
            return "Двигатель внутреннего сгорания	"
        return ""

    # --- Алгоритм извлечения ---
    result["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = parse_lab(text)
    FIELD_NAMES_SORTED = sorted(FIELD_NAMES, key=lambda x: -len(x))
    for key in FIELD_NAMES_SORTED:
        if key == "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ":
            result[key] = parse_lab(text)
            continue
        if key == "КАТЕГОРИЯ":
            result[key] = extract_category(lines)
            continue
        if key == "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ":
            result[key] = extract_commercial_name(lines)
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

    return result
