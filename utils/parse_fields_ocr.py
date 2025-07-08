import re
from copy import deepcopy
from utils.fields_template import FIELDS_TEMPLATE


def extract(pattern, text, flags=re.IGNORECASE):
    match = re.search(pattern, text, flags)
    if not match:
        return None
    try:
        return match.group(1).strip()
    except IndexError:
        return match.group(0).strip()


def parse_fields(text):
    data = deepcopy(FIELDS_TEMPLATE)

    data["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = extract(r"ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ\s*(.*?)\s+(ТАМОЖЕННЫЙ СОЮЗ|ТРАНСПОРТНОЕ СРЕДСТВО)", text)
    data["МАРКА"] = extract(r"MAPKA\s+([A-ZА-Я0-9\- ]+)", text)
    data["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] = extract(r"КОММЕРЧЕСКОЕ.*?\s+([A-ZА-Я0-9\- ]+)", text)
    data["ТИП"] = extract(r"\bТИП\s+([A-ZА-Я0-9\- ]+)", text)
    data["ШАССИ"] = extract(r"ШАССИ\s+([A-ZА-Я0-9\- ]+)", text)
    data["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = extract(r"VIN\)?\s*([A-Z0-9]{17})", text)
    data["ГОД ВЫПУСКА"] = extract(r"(\d{4})\s*г\.?", text) or extract(r"(\d{4})r", text)
    data["КАТЕГОРИЯ"] = extract(r"КАТЕГОРИЯ\s+([A-ZА-Я0-9]+)", text)
    data["ЭКОЛОГИЧЕСКИЙ КЛАСС"] = extract(r"ЭКОЛОГИЧЕСКИЙ КЛАСС\s*([A-ZА-Я0-9\- ]+)", text)
    data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = extract(r"ACKAPOBA.*?(\n.+?){1,3}", text, re.DOTALL)
    data["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] = extract(r"Changan Automobile Group.*?Province, PRC - Kutan", text, re.DOTALL)
    data["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] = extract(r"СБОРОЧНЫЙ ЗАВОД.*?(Changan Automobile Group.*?)\n", text)
    data["Колесная формула/ведущие колеса"] = extract(r"(\d[xхXХ]\d),\s*(передн[а-я]*)", text)
    data["Схема компоновки транспортного средства"] = extract(r"переменная\s*(.*?)\n", text)
    data["Тип кузова/количество дверей (для категории М1)"] = extract(r"универсал/(\d)", text)
    data["Количество мест спереди/ cзади (для категории М1)"] = extract(r"(\d)/(\d)", text)
    data["Масса транспортного средства в снаряженном состоянии, кг"] = extract(r"(\d{3,5})\s*кг", text)
    data["Габаритные размеры, мм"]["длина"] = extract(r"(\d{4})\s*\n", text)
    data["Габаритные размеры, мм"]["ширина"] = extract(r"\n(\d{4})\n", text)
    data["Габаритные размеры, мм"]["высота"] = extract(r"\n\d{4}\n(\d{4})", text)
    data["Двигатель внутреннего сгорания (марка, тип)"] = extract(r"JL473ZQ7.*", text)
    data["- количество и расположение цилиндров"] = extract(r"(\d),\s*(рядное|v-образное|оппозитное)", text, re.IGNORECASE)
    data["- рабочий объем цилиндров, см3"] = extract(r"рабоч.*?объем.*?(\d+)", text)
    data["- степень сжатия"] = extract(r"СТЕПЕНЬ СЖАТИЯ\s*([0-9.]+)", text)
    data["- максимальная мощность, кВт (мин.-1)"] = extract(r"мощность.*?(\d+\s*\(\d+\))", text)
    data["Топливо"] = extract(r"Топливо\s*([а-яА-Яa-zA-Z]+)", text)
    data["Система питания (тип)"] = extract(r"Система питания.*?([\w\- ]+)", text)
    data["Система зажигания (тип)"] = extract(r"Система зажигания.*?([\w\- ]+)", text)
    data["Система выпуска и нейтрализации отработавших газов"] = extract(r"выпуска.*?отработ.*?:?\s*(.+)", text)
    data["Сцепление (марка, тип)"] = extract(r"Сцепление.*?:?\s*(.+)", text)
    data["Трансмиссия"] = extract(r"Трансмиссия.*?:?\s*(.+)", text)
    data["Коробка передач (марка, тип)"] = extract(r"Коробка передач.*?:?\s*(.+)", text)
    data["Редуктор"] = extract(r"Редуктор.*?:?\s*(.+)", text)
    data["Подвеска(тип)"]["передняя"] = extract(r"передняя.*?:?\s*(.+)", text)
    data["Подвеска(тип)"]["задняя"] = extract(r"задняя.*?:?\s*(.+)", text)
    data["Рулевое управление (марка, тип)"] = extract(r"Рулевое управление.*?:?\s*(.+)", text)
    data["Шины"] = extract(r"Шины\s*([\d/R ]+)", text)
    data["Дополнительное оборудование транспортного средства"] = extract(r"ОСНАЩЕН.*", text)
    data["Дата оформления"] = extract(r"(\d{2}\.\d{2}\.\d{4})", text)

    return data
