# techreg_blueprint.py
import re
import time
from flask import Blueprint, request, jsonify
from techreg_client import TechRegClient
import os, urllib3, json  
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
VERIFY_SSL = os.getenv("TECHREG_VERIFY_SSL", "0") == "1"

techreg_bp = Blueprint("techreg", __name__, url_prefix="/api/techreg")

# Кириллица → латиница для похожих букв (чтоб "А-US" с кириллической А тоже работало)
_CYR_TO_LAT = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "У": "Y",
})

# Добавь рядом с _CYR_TO_LAT:
_DASHES = "‐-‒–—―−"  # все основные юникод-дефисы

def _norm_dashes(s: str) -> str:
    # все длинные/нестандартные дефисы → обычный -
    return re.sub(f"[{_DASHES}]", "-", s)

_NUM_PAT = re.compile(
    r"""^
        ([A-Z])            # серия: одна буква (A)
        [-_\s]?            # необязательный дефис/пробел
        ([A-Z]{2})         # регион/код: две буквы (US)
        [.\-_/\\\s]?       # необязательный разделитель
        (\d{1,5})          # блок 1 (обычно 4 цифры)
        [.\-_/\\\s]?       # необязательный разделитель
        (\d{1,6})          # блок 2 (обычно 5 цифр)
        $""",
    re.VERBOSE,
)

def normalize_techreg_num(raw: str) -> str | None:
    """
    Из "ТС KZ А–US.0075.37380", "tc kz a-us 75 37380", "a us-75/37380"
    делаем канон "A-US.0075.37380". Плюс генерим варианты без паддинга.
    """
    if not raw:
        return None
    s = raw.strip().upper().translate(_CYR_TO_LAT)
    s = _norm_dashes(s)
    s = re.sub(r"^(ТС|TC)\s*KZ\s*", "", s).strip()

    # уберём только лишние пробелы: дефисы/точки/слэши нам нужны для паттерна
    s_no_spaces = s.replace(" ", "")
    m = _NUM_PAT.search(s_no_spaces)
    if not m:
        return None

    g1, g2, p1, p2 = m.groups()
    p1_raw, p2_raw = str(int(p1)), str(int(p2))  # «без паддинга»
    p1_pad, p2_pad = p1_raw.zfill(4), p2_raw.zfill(5)

    # основной «канон»
    canon = f"{g1}-{g2}.{p1_pad}.{p2_pad}"

    # сохраним ещё 2 полезных варианта, чтобы клиент мог попробовать оба
    # (некоторые поиски лучше находят без ведущих нулей)
    alt_no_pad = f"{g1}-{g2}.{p1_raw}.{p2_raw}"
    alt_mix    = f"{g1}-{g2}.{p1_pad}.{p2_raw}"

    # вернём через запятую (если вызывающий код ждёт str), либо tuple/list
    # Здесь верну строку «canon», а альтернативы публикуем отдельной функцией:
    return canon

def techreg_number_variants(raw: str) -> list[str]:
    """Вспомогательная: отдаёт пул вариантов для поиска (паддинг/без него)."""
    if not raw:
        return []
    s = raw.strip().upper().translate(_CYR_TO_LAT)
    s = _norm_dashes(s)
    s = re.sub(r"^(ТС|TC)\s*KZ\s*", "", s).strip()
    s_no_spaces = s.replace(" ", "")
    m = _NUM_PAT.search(s_no_spaces)
    if not m:
        return [raw.strip()]
    g1, g2, p1, p2 = m.groups()
    p1_raw, p2_raw = str(int(p1)), str(int(p2))
    p1_pad, p2_pad = p1_raw.zfill(4), p2_raw.zfill(5)
    return list(dict.fromkeys([
        f"{g1}-{g2}.{p1_pad}.{p2_pad}",
        f"{g1}-{g2}.{p1_raw}.{p2_raw}",
        f"{g1}-{g2}.{p1_pad}.{p2_raw}",
        f"{g1}{g2}{p1_raw}{p2_raw}",          # «слепленный» на всякий
        f"{g1}-{g2}-{p1_raw}-{p2_raw}",       # через дефисы
    ]))

def find_value_by_label(soup: BeautifulSoup, label_variants: list[str]) -> str | None:
    """
    Находим <label> с текстом из label_variants (нормализуя пробелы/регистр),
    затем берём value у элемента, на который указывает for=..., либо
    ищем рядом в том же контейнере.
    """
    def _norm(s): return re.sub(r"\s+", " ", (s or "").strip().lower())
    wanted = [ _norm(x) for x in label_variants ]

    for lab in soup.find_all(["label", "span", "div"]):
        txt = _norm(lab.get_text(" "))
        if any(w in txt for w in wanted):
            # 1) по for=
            for_id = lab.get("for")
            if for_id:
                ctrl = soup.find(id=for_id)
                if ctrl and ctrl.get("value"):
                    return ctrl.get("value").strip()
                if ctrl and ctrl.name in ("input","select","textarea"):
                    val = (ctrl.get("value") or ctrl.get_text(" ") or "").strip()
                    if val:
                        return val
            # 2) рядом (родительский контейнер)
            parent = lab.find_parent()
            if parent:
                inp = parent.find(["input","select","textarea"])
                if inp and inp.get("value"):
                    return inp.get("value").strip()
                if inp:
                    val = (inp.get_text(" ") or "").strip()
                    if val:
                        return val
    return None


# -------- Поля вывода (как ты прислал) --------
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
    "Количество мест спереди/cзади (для категории М1)": None,
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
    "Колея передних/задних колес, мм": {"передних": None, "задних": None},
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
    "Статус": None,
    "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ": None,
}

# Нормализация подписи поля
import re
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

# Синонимы меток (на случай различий в формулировках)
LABEL_ALIASES = {
    "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ": ["испытательная лаборатория"],
    "МАРКА": ["марка"],
    "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ": ["коммерческое наименование"],
    "ТИП": ["тип"],
    "ШАССИ": ["шасси", "шасси (рама)", "шасси (рама) номер", "шасси (рама) №"],
    "ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)": ["vin", "идентификационный номер (vin)", "идентификационный номер"],
    "ГОД ВЫПУСКА": ["год выпуска"],
    "КАТЕГОРИЯ": ["категория"],
    "ЭКОЛОГИЧЕСКИЙ КЛАСС": ["экологический класс", "экон. класс", "euro"],
    "ЗАЯВИТЕЛЬ И ЕГО АДРЕС": ["заявитель и его адрес", "заявитель", "адрес заявителя"],
    "ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС": ["изготовитель и его адрес", "изготовитель", "адрес изготовителя"],
    "СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС": ["сборочный завод и его адрес", "сборочный завод", "адрес сборочного завода"],
    "Колесная формула/ведущие колеса": ["колесная формула/ведущие колеса", "колесная формула"],
    "Схема компоновки транспортного средства": ["схема компоновки транспортного средства", "схема компоновки"],
    "Тип кузова/количество дверей (для категории М1)": ["тип кузова/количество дверей", "тип кузова"],
    "Количество мест спереди/ cзади (для категории М1)": ["количество мест спереди/сзади", "кол-во мест (м1)"],
    "Масса транспортного средства в снаряженном состоянии, кг": ["масса в снаряженном состоянии"],
    "Технически допустимая максимальная масса транспортного средства, кг": ["тдмма тс", "технически допустимая максимальная масса"],
    "База, мм": ["база, мм", "колёсная база, мм", "база"],
    "Описание гибридного транспортного средства": ["описание гибридного транспортного средства"],
    "Двигатель": ["двигатель"],
    "Двигатель внутренного сгорания (марка, тип)": ["двигатель внутреннего сгорания (марка, тип)","двс (марка, тип)"],
    "- количество и расположение цилиндров": ["количество и расположение цилиндров"],
    "- рабочий объем цилиндров, см3": ["рабочий объем цилиндров", "рабочий объём цилиндров"],
    "- степень сжатия": ["степень сжатия"],
    "- максимальная мощность, кВт (мин.-1)": ["максимальная мощность, кВт", "максимальная мощность"],
    "Топливо": ["топливо", "вид топлива"],
    "Система питания (тип)": ["система питания (тип)", "система питания"],
    "Система зажигания (тип)": ["система зажигания (тип)", "система зажигания"],
    "Система выпуска и нейтрализации отработавших газов": ["выпуск и нейтрализация отработавших газов", "нейтрализация отработавших газов"],
    "Электродвигатель электромобиля": ["электродвигатель электромобиля"],
    "Рабочее напряжение, В": ["рабочее напряжение, в"],
    "Максимальная 30-минутная мощность, кВт": ["максимальная 30-минутная мощность, кВт"],
    "Вид электромашины": ["вид электромашины"],
    "Электромашина (марка, тип)": ["электромашина (марка, тип)"],
    "Рабочее напряжение, В (электромашина)": ["рабочее напряжение, в (электромашина)"],
    "Максимальная 30-минутная мощность, кВт (электромашина)": ["максимальная 30-минутная мощность, кВт (электромашина)"],
    "Устройство накопления энергии": ["устройство накопления энергии", "аккумуляторная батарея"],
    "Сцепление (марка, тип)": ["сцепление (марка, тип)", "сцепление"],
    "Трансмиссия": ["трансмиссия"],
    "Коробка передач (марка, тип)": ["коробка передач (марка, тип)", "коробка передач"],
    "Редуктор": ["редуктор"],
    "Рулевое управление (марка, тип)": ["рулевое управление (марка, тип)", "рулевое управление"],
    "Дополнительное оборудование транспортного средства": ["дополнительное оборудование транспортного средства", "дополнительное оборудование"],
    "ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ": ["дополнительная информация"],
}

LABEL_ALIASES.setdefault("Исполнение загрузочного пространства (для категории N)", [])
LABEL_ALIASES["Исполнение загрузочного пространства (для категории N)"] += [
    "исполнение загрузочного пространства (для категории n)",
    "исполнение загрузочного пространства",
    "загрузочное пространство",
    "тип загрузочного пространства",
    "тип платформы",
    "платформа/кузов (исполнение)",
    "бортовая платформа",
]

LABEL_ALIASES["МАРКА"] += ["марка транспортного средства", "марка тс", "марка автомобиля"]

LABEL_ALIASES.setdefault("Кабина (для категории N)", [])
LABEL_ALIASES["Кабина (для категории N)"] += [
    "кабина (для категории n)",
    "кабина",
    "тип кабины",
    "исполнение кабины",
]


LABEL_ALIASES.setdefault("Описание гибридного транспортного средства", [])
LABEL_ALIASES["Описание гибридного транспортного средства"] += [
    "описание гибридного тс", "описание гибридного транспортного средства",
    "описание гибридной установки", "описание гибридной системы",
]

# LABEL_ALIASES.setdefault("Двигатель внутреннего сгорания (марка, тип)", [])
# LABEL_ALIASES["Двигатель внутреннего сгорания (марка, тип)"] += [
#     "двигатель внутреннего сгорания (марка, тип)", "двс (марка, тип)"
# ]
# if "Двигатель внутренного сгорания (марка, тип)" in LABEL_ALIASES:
#     LABEL_ALIASES["Двигатель внутреннего сгорания (марка, тип)"] += \
#         LABEL_ALIASES.pop("Двигатель внутренного сгорания (марка, тип)")


k = "Двигатель внутреннего сгорания (марка, тип)"
LABEL_ALIASES.setdefault(k, [])
LABEL_ALIASES[k] = list(dict.fromkeys(
    LABEL_ALIASES[k] + ["двигатель внутреннего сгорания (марка, тип)", "двс (марка, тип)"]
))


LABEL_ALIASES.setdefault("База, мм", [])
LABEL_ALIASES["База, мм"] += ["колёсная база, мм", "колесная база, мм", "колёсная база", "колесная база"]

LABEL_ALIASES.setdefault("Схема компоновки транспортного средства", [])
LABEL_ALIASES["Схема компоновки транспортного средства"] += [
    "схема компоновки", "привод", "тип привода", "компоновка (привод)"
]

LABEL_ALIASES.setdefault("Тип кузова/количество дверей (для категории М1)", [])
LABEL_ALIASES["Тип кузова/количество дверей (для категории М1)"] += [
    "тип кузова/количество дверей", "тип кузова", "количество дверей"
]

LABEL_ALIASES.setdefault("Количество мест спереди/сзади (для категории М1)", [])
LABEL_ALIASES["Количество мест спереди/сзади (для категории М1)"] += [
    "количество мест спереди/сзади",
    "кол-во мест (м1)",
    "количество мест (м1)",
    "мест спереди/сзади"
]

LABEL_ALIASES.setdefault("Рабочее напряжение, В", [])
LABEL_ALIASES["Рабочее напряжение, В"] += [
    "рабочее напряжение, в (электромашина)",
    "напряжение электромашины",
    "напряжение системы",
    "номинальное напряжение, в"
]

LABEL_ALIASES.setdefault("Максимальная 30-минутная мощность, кВт", [])
LABEL_ALIASES["Максимальная 30-минутная мощность, кВт"] += [
    "максимальная 30-минутная мощность, кВт (электромашина)",
    "мощность за 30 мин, кВт",
    "30-минутная мощность электродвигателя, кВт",
    "30 мин мощность, кВт"
]

LABEL_ALIASES.setdefault("Устройство накопления энергии", [])
LABEL_ALIASES["Устройство накопления энергии"] += [
    "устройство накопления энергии (для электромобилей и гибридных транспортных средств)",
    "устройство накопления энергии (только для электромобилей и гибридных транспортных средств)",
    "аккумуляторная батарея (тип)",
    "тип аккумуляторной батареи",
    "тяговая батарея",
    "акб", "тип акб",
]

LABEL_ALIASES.setdefault("Количество осей/колес (для категории О)", [])
LABEL_ALIASES["Количество осей/колес (для категории О)"] += [
    "количество осей/колёс (для категории о)", "количество осей/колес",
    "кол-во осей", "число осей", "осей/колес"
]

# стало:
LABEL_ALIASES.setdefault("Шины", [])
LABEL_ALIASES["Шины"] += [
    # базовые варианты
    "шины", "типоразмер шин", "размерность шин", "размер шин",
    "шины (передние)", "шины (задние)", "передние шины", "задние шины",
    "шины и диски", "шины/диски", "размер шин и дисков", "типоразмер шин и дисков",
    # варианты из форм
    "шины (обозначение размера)", "обозначение размера шин", "шины (обозначение)"
]

LABEL_ALIASES.setdefault("Статус", [])
LABEL_ALIASES["Статус"] += ["статус", "state", "состояние"]


# Возможные ID-поля (если искать по метке не получилось)
ID_ALIASES = {
    "ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)": ["textbox_vin"],
    "КАТЕГОРИЯ": ["listbox_category"],
    "Дата оформления": ["date_registration"],
    "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ": ["reglink_testing_laboratory"],
}


ID_ALIASES.setdefault("Статус", [])
ID_ALIASES["Статус"] += ["listbox_status"]

# Эвристики: если точного ID нет, ищем по подстрокам id (последний сегмент и с точками/подчёркиваниями)
SUBSTR_ID_ALIASES = {
    "Схема компоновки транспортного средства": [
        "vehicle_layout", "layout_diagram", "privod", "drive", "comp_layout"
    ],
    "МАРКА": ["brand", "make", "vehicle_brand", "car_brand"],
    "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ": ["commercial", "trade_name", "model", "kommerc", "naimenov"],
    "ТИП": ["vehicle_type", "type_ts", "type_vehicle"],
    "ШАССИ": ["chassis", "rama"],
    "ГОД ВЫПУСКА": ["release_year", "year", "god_vyp"],
    "ЭКОЛОГИЧЕСКИЙ КЛАСС": ["eco_class", "ecological", "euro"],
    "Колесная формула/ведущие колеса": ["wheel_formula", "kolyos", "vedush", "drivetrain"],
    "Тип кузова/количество дверей (для категории М1)": ["body_type", "doors", "kol_dver", "kuzov"],
    "Масса транспортного средства в снаряженном состоянии, кг": ["mass_curb", "mass_snar", "curb_weight"],
    "Технически допустимая максимальная масса транспортного средства, кг": ["mass_max", "tdmma", "max_mass"],
    "База, мм": ["wheelbase", "baza"],
    "Габаритные размеры, мм": ["length", "width", "height", "gabarit"],
    "Колея передних/задних колес, мм": ["track_front", "track_rear", "koleya"],
    "Топливо": ["fuel"],
    "Двигатель": ["engine"],
    "Двигатель внутренного сгорания (марка, тип)": ["engine_mark", "engine_type", "dvigatel_tip"],
    "- количество и расположение цилиндров": ["cylinders", "cilindr"],
    "- рабочий объем цилиндров, см3": ["engine_volume", "displacement", "rab_obem"],
    "- степень сжатия": ["compression"],
    "- максимальная мощность, кВт (мин.-1)": ["max_power", "power_kw"],
    "Система питания (тип)": ["fuel_system"],
    "Система зажигания (тип)": ["ignition"],
    "Система выпуска и нейтрализации отработавших газов": ["exhaust", "neutralization"],
    "Трансмиссия": ["transmission"],
    "Коробка передач (марка, тип)": ["gearbox", "kpp"],
    "Редуктор": ["reductor", "final_drive"],
    "Подвеска(тип)": ["suspension"],
    "Рулевое управление (марка, тип)": ["steering"],
    "Тормозные системы (тип)": ["brake", "tormozn"],
    "Рабочее напряжение, В": ["voltage", "napryazhenie"],
    "Максимальная 30-минутная мощность, кВт": ["thirty_min_power", "30min_power"],
    "Устройство накопления энергии": ["battery", "accumulator", "energy_storage"],
    "Электродвигатель электромобиля": ["electric_motor"],
    "Электромашина (марка, тип)": ["electromashina", "e_machine"],
}

SUBSTR_ID_ALIASES["Тип кузова/количество дверей (для категории М1)"] = [
    "listbox_type_body", "textbox_body_type", "bodytype", "body_type", "doors", "kol_dver", "kuzov"
]

SUBSTR_ID_ALIASES.setdefault("Шины", [])
SUBSTR_ID_ALIASES["Шины"] += [
    "tire", "tyre", "tyre_size", "tire_size",
    "front_tire", "rear_tire", "tire_front", "tire_rear",
    "front_tyre", "rear_tyre", "tyre_front", "tyre_rear",
]

# --- базовые поля ---
SUBSTR_ID_ALIASES["МАРКА"] = [
    "vehicle_brand", "car_brand",       # безопасные общие
    "textbox_stamp", "reglink_mark", "code_mark",  # твои точные id
    "make"                               # допустимо; «engine_make» почти не встречается
]
SUBSTR_ID_ALIASES.setdefault("КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ", [])
SUBSTR_ID_ALIASES["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] += ["textbox_commercial_name"]

SUBSTR_ID_ALIASES.setdefault("ТИП", [])
SUBSTR_ID_ALIASES["ТИП"] += ["textbox_type"]

SUBSTR_ID_ALIASES.setdefault("ГОД ВЫПУСКА", [])
SUBSTR_ID_ALIASES["ГОД ВЫПУСКА"] += ["textbox_year"]

SUBSTR_ID_ALIASES.setdefault("ЭКОЛОГИЧЕСКИЙ КЛАСС", [])
SUBSTR_ID_ALIASES["ЭКОЛОГИЧЕСКИЙ КЛАСС"] += ["listbox_environmental_class"]

SUBSTR_ID_ALIASES.setdefault("ЗАЯВИТЕЛЬ И ЕГО АДРЕС", [])
SUBSTR_ID_ALIASES["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] += ["textbox_applicant", "textbox_address_applicant"]

SUBSTR_ID_ALIASES.setdefault("ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС", [])
SUBSTR_ID_ALIASES["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] += ["textbox_manufacturer", "textbox_address_manufacturer"]

SUBSTR_ID_ALIASES.setdefault("СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС", [])
SUBSTR_ID_ALIASES["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] += ["textbox_assembly_plant", "textbox_address_assembly_plant"]

SUBSTR_ID_ALIASES.setdefault("Колесная формула/ведущие колеса", [])
SUBSTR_ID_ALIASES["Колесная формула/ведущие колеса"] += [
    "textbox_wheel_formula", "wheel_formula", "listbox_drive_wheels"
]

SUBSTR_ID_ALIASES.setdefault("Схема компоновки транспортного средства", [])
SUBSTR_ID_ALIASES["Схема компоновки транспортного средства"] += ["textbox_vehicle_layout_diagram"]

SUBSTR_ID_ALIASES.setdefault("Тип кузова/количество дверей (для категории М1)", [])
SUBSTR_ID_ALIASES["Тип кузова/количество дверей (для категории М1)"] += [
    "listbox_type_body", "textbox_body_type", "bodytype", "body_type"
]

SUBSTR_ID_ALIASES.setdefault("Описание гибридного транспортного средства", [])
SUBSTR_ID_ALIASES["Описание гибридного транспортного средства"] += [
    "hybrid_description", "description_hybrid", "hev_description",
    "phev_description", "reev_description", "hybrid_vehicle_description"
]

SUBSTR_ID_ALIASES.setdefault("Количество мест спереди/ cзади (для категории М1)", [])
SUBSTR_ID_ALIASES["Количество мест спереди/ cзади (для категории М1)"] += ["textbox_number_of_seats"]

SUBSTR_ID_ALIASES.setdefault("База, мм", [])
SUBSTR_ID_ALIASES["База, мм"] += ["textbox_base", "wheel_base", "wheel-base", "wb"]

SUBSTR_ID_ALIASES.setdefault("Колея передних/задних колес, мм", [])
SUBSTR_ID_ALIASES["Колея передних/задних колес, мм"] += [
    "textbox_track_front_rear_wheels", "rear_tread", "tread_rear", "front_tread", "tread_front", "tread"
]

SUBSTR_ID_ALIASES.setdefault("Масса транспортного средства в снаряженном состоянии, кг", [])
SUBSTR_ID_ALIASES["Масса транспортного средства в снаряженном состоянии, кг"] += ["textbox_vehicle_weight"]

SUBSTR_ID_ALIASES.setdefault("Технически допустимая максимальная масса транспортного средства, кг", [])
SUBSTR_ID_ALIASES["Технически допустимая максимальная масса транспортного средства, кг"] += [
    "textbox_technically_permissible_maximum_weight"
]

SUBSTR_ID_ALIASES.setdefault("Исполнение загрузочного пространства (для категории N)", [])
SUBSTR_ID_ALIASES["Исполнение загрузочного пространства (для категории N)"] += [
    "loading_space", "loading_compartment", "cargo_space",
    "cargo_body", "platform", "body_platform",
    "body_execution", "body_performance",
    "cargo_bed", "bed_type", "loading_area",
]

SUBSTR_ID_ALIASES.setdefault("Кабина (для категории N)", [])
SUBSTR_ID_ALIASES["Кабина (для категории N)"] += [
    "cab", "cabin", "cab_type", "type_cabin", "cab_configuration", "kabin"
]

SUBSTR_ID_ALIASES.setdefault("Сцепление (марка, тип)", [])
SUBSTR_ID_ALIASES["Сцепление (марка, тип)"] += ["clutch"]

# --- двигатель/топливо/зажигание/выпуск ---
SUBSTR_ID_ALIASES.setdefault("Двигатель", [])
SUBSTR_ID_ALIASES["Двигатель"] += ["textbox_engine_brand", "engine_brand"]

SUBSTR_ID_ALIASES.setdefault("- количество и расположение цилиндров", [])
SUBSTR_ID_ALIASES["- количество и расположение цилиндров"] += [
    "numericinput_number_of_engine_cylinders",
    "listbox_description_engine_cylinder_arrangement",
    "listbox_description_engine_cylinder_arrangement_copy1"
]

SUBSTR_ID_ALIASES.setdefault("- рабочий объем цилиндров, см3", [])
SUBSTR_ID_ALIASES["- рабочий объем цилиндров, см3"] += ["numericinput_engine_cylinder_displacement"]

SUBSTR_ID_ALIASES.setdefault("- степень сжатия", [])
SUBSTR_ID_ALIASES["- степень сжатия"] += ["numericinput_engine_compression_ratio"]

SUBSTR_ID_ALIASES.setdefault("- максимальная мощность, кВт (мин.-1)", [])
SUBSTR_ID_ALIASES["- максимальная мощность, кВт (мин.-1)"] += [
    "numericinput_maximum_power", "numericinput_engine_compression_ratio_copy1"  # дубликат с неверным именем, но с данными
]

SUBSTR_ID_ALIASES.setdefault("Топливо", [])
SUBSTR_ID_ALIASES["Топливо"] += ["textbox_name_fuel"]

SUBSTR_ID_ALIASES.setdefault("Система питания (тип)", [])
SUBSTR_ID_ALIASES["Система питания (тип)"] += ["textarea_power_system_description"]

SUBSTR_ID_ALIASES.setdefault("Система зажигания (тип)", [])
SUBSTR_ID_ALIASES["Система зажигания (тип)"] += ["textarea_ignition"]

SUBSTR_ID_ALIASES.setdefault("Система выпуска и нейтрализации отработавших газов", [])
SUBSTR_ID_ALIASES["Система выпуска и нейтрализации отработавших газов"] += ["textarea_exhaust"]

# --- трансмиссия/кпп/руль/подвеска ---
SUBSTR_ID_ALIASES.setdefault("Трансмиссия", [])
SUBSTR_ID_ALIASES["Трансмиссия"] += ["textarea_transmission"]

SUBSTR_ID_ALIASES.setdefault("Коробка передач (марка, тип)", [])
SUBSTR_ID_ALIASES["Коробка передач (марка, тип)"] += ["textbox_cp_type"]

SUBSTR_ID_ALIASES.setdefault("Рулевое управление (марка, тип)", [])
SUBSTR_ID_ALIASES["Рулевое управление (марка, тип)"] += ["textbox_steering_type", "textbox_mark_steering"]

SUBSTR_ID_ALIASES.setdefault("Подвеска(тип)", [])
SUBSTR_ID_ALIASES["Подвеска(тип)"] += ["textarea_front_suspension", "textarea_back_suspension"]

# Вид электромашины (в реальных формах приходит как listbox_type_electric_machine)
SUBSTR_ID_ALIASES.setdefault("Вид электромашины", [])
SUBSTR_ID_ALIASES["Вид электромашины"] += ["listbox_type_electric_machine"]

# Доп. оборудование (встречается id с дефисом)
SUBSTR_ID_ALIASES.setdefault("Дополнительное оборудование транспортного средства", [])
SUBSTR_ID_ALIASES["Дополнительное оборудование транспортного средства"] += ["textarea-5cjdbc"]

# --- электромашины / электромотор / напряжение / 30-мин мощность / батарея ---
SUBSTR_ID_ALIASES.setdefault("Электромашина (марка, тип)", [])
SUBSTR_ID_ALIASES["Электромашина (марка, тип)"] += [
    "textbox_electric_machine", "electric_machine", "electric_machine_type",
    "electric_motor_type", "motor_model", "motor_type", "em_brand",
    "em_type", "e_machine_type", "em_model"
]

SUBSTR_ID_ALIASES.setdefault("Электродвигатель электромобиля", [])
SUBSTR_ID_ALIASES["Электродвигатель электромобиля"] += [
    "electric_motor_desc", "textarea_electric_motor", "e_motor_desc",
    "electric_motor", "emotor_desc"
]

SUBSTR_ID_ALIASES.setdefault("Рабочее напряжение, В (электромашина)", [])
SUBSTR_ID_ALIASES["Рабочее напряжение, В (электромашина)"] += [
    "em_voltage", "electric_machine_voltage", "electric_motor_voltage", "voltage_em"
]

SUBSTR_ID_ALIASES.setdefault("Максимальная 30-минутная мощность, кВт (электромашина)", [])
SUBSTR_ID_ALIASES["Максимальная 30-минутная мощность, кВт (электромашина)"] += [
    "em_30min_power", "power_30min_em", "electric_motor_power_30min", "power_30min_e"
]

SUBSTR_ID_ALIASES.setdefault("Устройство накопления энергии", [])
SUBSTR_ID_ALIASES["Устройство накопления энергии"] += [
    "traction_battery", "battery_type", "hv_battery", "traction",
    "akb", "akb_type", "energy_storage_device"
]


SUBSTR_ID_ALIASES.setdefault("Максимальная 30-минутная мощность, кВт", [])
SUBSTR_ID_ALIASES["Максимальная 30-минутная мощность, кВт"] += [
    "30_min_power", "power_30", "power30", "30minute_power",
]

SUBSTR_ID_ALIASES["Устройство накопления энергии"] += [
    "battery_pack", "traction_battery_type", "hv_pack"
]

# SUBSTR_ID_ALIASES
SUBSTR_ID_ALIASES.setdefault("Рабочее напряжение, В", [])
SUBSTR_ID_ALIASES["Рабочее напряжение, В"] += [
    # общие
    "voltage", "napryazhenie",
    # «электромашина»-варианты
    "em_voltage", "electric_machine_voltage", "electric_motor_voltage", "voltage_em"
]

SUBSTR_ID_ALIASES.setdefault("Максимальная 30-минутная мощность, кВт", [])
SUBSTR_ID_ALIASES["Максимальная 30-минутная мощность, кВт"] += [
    # общие
    "30_min_power", "power_30", "power30", "30minute_power", "thirty_min_power", "30min_power",
    # «электромашина»-варианты
    "em_30min_power", "power_30min_em", "electric_motor_power_30min", "power_30min_e"
]

SUBSTR_ID_ALIASES.setdefault("Рабочее напряжение, В", [])
SUBSTR_ID_ALIASES["Рабочее напряжение, В"] += ["textbox_operating_voltage", "operating_voltage"]

SUBSTR_ID_ALIASES.setdefault("Максимальная 30-минутная мощность, кВт", [])
SUBSTR_ID_ALIASES["Максимальная 30-минутная мощность, кВт"] += ["textbox_power", "max_power"]



SUBSTR_ID_ALIASES.setdefault("Количество осей/колес (для категории О)", [])
SUBSTR_ID_ALIASES["Количество осей/колес (для категории О)"] += [
    "number_of_axles","num_axles","axles_count","axle_count",
    "kol_os","kolichestvo_osey","count_wheels","wheels_count"
]

SUBSTR_ID_ALIASES.setdefault("Статус", [])
SUBSTR_ID_ALIASES["Статус"] += ["status", "listbox_status", "state"]

AMBIGUOUS_LABELS = {"МАРКА", "ТИП"}

@techreg_bp.route("/sbkts/fields", methods=["POST"])
def sbkts_fields():
    """
    Вход: { "num": "SBKTS-2025-000123" | "ТС KZ А-US.0075.37380" | "A-US.0075.37380" }
    Выход: { "fields": <FIELDS_TEMPLATE-like> }
    """
    try:
        payload = request.get_json(silent=True) or {}
        num_raw = (payload.get("num") or "").strip()
        if not num_raw:
            return jsonify({"error": "Не передан номер заявки (num)"}), 400

        # ✅ берём готовый клиент с куками/загревом
        cl = get_client()

        # 1) Пытаемся как есть (подходит для SBKTS-2025-000123 и т.п.)
        res = cl.get_sbkts_by_number(num_raw)

        # 2) Если не нашли — пробуем нормализацию в формат A-US.0075.37380
        if not res.get("ok"):
            num_norm = normalize_techreg_num(num_raw)
            if num_norm and num_norm != num_raw:
                res = cl.get_sbkts_by_number(num_norm)

        if not res.get("ok"):
            return jsonify({
                "error": res.get("reason", "not_found"),
                "input": num_raw
            }), 404

        doc_id = res.get("documentID")
        data_uuid = res.get("dataUUID")

        # Тянем детальную форму (asforms)
        detail = None
        if data_uuid:
            try:
                detail = cl.asforms_data(data_uuid)
            except Exception:
                detail = None
        if detail is None and doc_id:
            try:
                detail = cl.asforms_collate(doc_id)
            except Exception:
                detail = None

        if not detail:
            return jsonify({
                "error": "Не удалось получить детальную форму",
                "documentID": doc_id,
                "dataUUID": data_uuid
            }), 502

        # Базовые поля из «шапки» для постобработки
        base_record = {
            "vin": (res.get("record") or {}).get("VIN"),
            "category": (res.get("record") or {}).get("Категория"),
            "registration_date": (res.get("record") or {}).get("Дата оформления"),
            "testing_laboratory": (res.get("record") or {}).get("Испытательная лаборатория"),
            "status":(res.get("record") or {}).get("Статус"), 
        }

        def _fetch_html():
            try:
                return cl.get_player_html(doc_id)  # см. п.4 ниже
            except Exception:
                return None

        fields = _extract_fields_from_detail(detail, base_record, fetch_html=_fetch_html)

        # Гарантируем структуру как в шаблоне
        import copy
        tpl = copy.deepcopy(FIELDS_TEMPLATE)
        for k in tpl.keys():
            if k in fields:
                tpl[k] = fields[k]

        return jsonify({"fields": tpl}), 200

    except Exception as e:
        return jsonify({"error": f"TechReg error: {e}"}), 500


def _parse_track_combo(txt: str) -> tuple[str | None, str | None]:
    """
    Принимает строку вида:
      "2022/1830", "2022 / 1830 / 1830", " 2022 / 1830/ 1850 "
    Возвращает (передних, задних), где:
      • если нашли 2 числа  -> (a, b)
      • если 3+ чисел       -> (a, b/b) если b == c, иначе (a, b/c)
    Никогда не возвращает слэш в значении "передних".
    """
    if not isinstance(txt, str):
        return (None, None)
    raw = txt.replace(" ", "")
    nums = re.findall(r"\d+(?:[.,]\d+)?", raw)
    if len(nums) < 2:
        return (None, None)

    front = nums[0]
    if len(nums) == 2:
        rear = nums[1]
    else:
        b, c = nums[1], nums[2]
        rear = b if b == c else f"{b}/{c}"
    return (front, rear)




def _norm_category(val) -> str:
    s = str(val or "")
    s = s.replace("\u00A0", " ").strip().upper()
    s = re.sub(r"\s+", "", s)
    s = s.translate(_CYR_TO_LAT)
    if s.startswith("0"):  # common O/0 mixup
        s = "O" + s[1:]
    return s

def _digits_keep_pair_or_single(s: str) -> str | None:
    """
    Нормализует «задние» значения:
      • '1830'              -> '1830'
      • '1830/1830'         -> '1830'
      • '1830/1850'         -> '1830/1850'
      • ' 1830 / 1850 '     -> '1830/1850'
      • '≈1830 мм'          -> '1830'
    """
    if not isinstance(s, str):
        return None
    s = s.replace("\u00A0", " ").strip()
    if "/" in s:
        parts = [p.strip() for p in s.split("/", 2) if p.strip()]
        if not parts:
            return None
        if len(parts) == 1:
            return _digits(parts[0]) or parts[0]
        a = _digits(parts[0]) or parts[0]
        b = _digits(parts[1]) or parts[1]
        return a if a == b else f"{a}/{b}"
    d = _digits(s)
    return d or s

def _scrape_player_values(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    values = {}
    for div in soup.select('div[data-asformid]'):
        aid = div.get("data-asformid") or ""
        txt = div.get_text(strip=True)
        if not txt:
            continue
        # храним под разными ключами (как в JSON и «плоско»)
        values[aid] = txt
        values[aid.replace(".", "_")] = txt
        values[aid.split(".")[-1]] = txt
    return values


def _extract_fields_from_detail(detail: dict, base_record: dict, fetch_html=None) -> dict:
    result = json.loads(json.dumps(FIELDS_TEMPLATE, ensure_ascii=False))
    data_arr = detail.get("data", []) if isinstance(detail, dict) else []

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    def _is_select_like(cid: str) -> bool:
        c = (cid or "").replace(".", "_").lower()
        return c.startswith(("listbox_", "combobox_", "dropdown_", "dictionary_", "reglink_", "radio_", "checkbox_"))

    PLACEHOLDERS = {
    "выберите значения","выберите значение","select...","нет данных",
    "не указано","не выбрано","не применяется","неприменимо",
    "не предусмотрено","n/a","n\\a",
    "— выберите —","- выберите -","select value","please select",
}



    def _coerce_value(item: dict):
            lbl = (item.get("label") or "").strip()
            v = item.get("value")

            if isinstance(v, (int, float)) and v == 0 and _is_select_like(item.get("id","")):
                v = None
            elif isinstance(v, str) and re.fullmatch(r"0+(?:\.0+)?", v.strip()) and _is_select_like(item.get("id","")):
                v = None

            # dict -> достать человекочитаемое
            if isinstance(v, dict):
                for k in ("label", "text", "value", "name", "title"):
                    if v.get(k):
                        v = v[k]; break
                else:
                    v = None

            # list -> склеить
            if isinstance(v, list):
                parts = []
                for x in v:
                    if isinstance(x, dict):
                        parts.append(str(x.get("label") or x.get("text") or x.get("value") or "").strip())
                    else:
                        parts.append(str(x))
                v = ", ".join([p for p in parts if p])

            # строки: вычистить плейсхолдеры/пустышки
            if isinstance(v, str):
                vv = v.strip()
                if vv in ("", "-", "—"):
                    v = None
                else:
                    # если значение совпало с подписью (или подпись без префикса "- ") -> игнор
                    if _norm(vv) in (_norm(lbl), _norm(lbl).lstrip("- ").strip()):
                        v = None
                    # плейсхолдеры
                    elif _norm(vv) in PLACEHOLDERS:
                        v = None

            # select/dictionary: использовать только человекочитаемое значение (НЕ подпись поля)
            cid = item.get("id") or ""
            if _is_select_like(cid):
                raw = item.get("value")
                if isinstance(raw, dict):
                    v = raw.get("label") or raw.get("text") or raw.get("value")
                elif isinstance(raw, list):
                    parts = []
                    for x in raw:
                        if isinstance(x, dict):
                            parts.append((x.get("label") or x.get("text") or x.get("value") or "").strip())
                        else:
                            parts.append(str(x))
                    v = ", ".join([p for p in parts if p]) or None
                else:
                    v = item.get("valueLabel") or item.get("selectedText") or v
                if isinstance(v, str) and _norm(v) in PLACEHOLDERS:
                    v = None

            return v

    by_id, by_label = {}, {}

     # --- HTML fallback (плеер) ---
    html_vals = {}
    if callable(fetch_html):
        try:
            html = fetch_html()
            if html:
                html_vals = _scrape_player_values(html)
        except Exception:
            html_vals = {}

    def _html(*keys):
        # ищем в html_vals разные варианты адресации
        for k in keys:
            for cand in (k, f"textbox.text.{k}", f"numericinput.text.{k}", f"listbox.text.{k}"):
                for kk in (cand, cand.replace(".", "_"), cand.split(".")[-1]):
                    if html_vals.get(kk):
                        return html_vals[kk]
        return None

    def _html_from_substr_aliases(label_key: str):
        """HTML-fallback по SUBSTR_ID_ALIASES: ищем значение в html_vals."""
        try:
            substrs = SUBSTR_ID_ALIASES.get(label_key, [])
        except NameError:
            substrs = []
        if not substrs:
            return None
        for sub in substrs:
            subn = (sub or "").lower()
            for k, v in html_vals.items():
                if not v:
                    continue
                kn = (k or "").lower().replace(".", "_")
                last = kn.split("_")[-1]
                if subn in last or subn in kn:
                    return v
        return None

    def _html_like(*needles):
        """HTML-fallback по свободному соответствию ключей html_vals."""
        nn = [str(n or "").lower() for n in needles if str(n or "").strip()]
        if not nn:
            return None
        for k, v in html_vals.items():
            if not v:
                continue
            kn = (k or "").lower().replace(".", "_")
            if all(n in kn for n in nn):
                return v
        return None


    def _join(*vals, sep=", "):
        parts = []
        for v in vals:
            if isinstance(v, str):
                vv = v.replace("\u00A0", " ").strip()
                if vv: parts.append(re.sub(r"\s+", " ", vv))
        return sep.join(parts) if parts else None


    for it in data_arr:
        _id = it.get("id")
        _label = it.get("label")
        _val = _coerce_value(it)

        # привяжем значение ко всем альтернативам id
        if _id:
            variants = {_id, _id.replace(".", "_"), _id.split(".")[-1]}
            for vid in variants:
                by_id[vid] = _val
        if isinstance(_label, str):
            by_label[_norm(_label)] = _val

    # Внутри _extract_fields_from_detail(), рядом с _first_by_id_contains/_first_by_label_contains:
    def _first_by_id_like(*needles, exclude_prefixes=("listbox_","combobox_","dropdown_","dictionary_","reglink_")):
        for k, v in by_id.items():
            if not v:
                continue
            norm = (k or "").lower().replace(".", "_")
            if any(norm.startswith(p) for p in exclude_prefixes):
                continue
            if all(n in norm for n in needles):
                return v
        return None

    def _looks_like_em_brand_type(s: str) -> bool:
        txt = str(s or "").lower()
        return bool(re.search(r'(квт|kw|hp|синхрон|асинхрон|магнит|переменного|постоянного|[a-z]\d|\d)', txt, re.I))


    def _first_by_label_contains(*needles):
        nn = [n.lower() for n in needles]
        for lbl, val in by_label.items():
            if val and all(j in lbl for j in nn):
                return val
        return None

    def _hybrid_desc():
        parts = []
        v = _first_by_label_contains("подзаряд", "источник")
        if v: parts.append(f"Подзарядка от внешнего источника: {v}")
        v = _first_by_label_contains("предусмотренн", "режим")
        if v: parts.append(f"Предусмотренные режимы работы: {v}")
        v = _first_by_label_contains("краткое", "описан")
        if v: parts.append(f"Краткое описание: {v}")
        return "; ".join(parts) if parts else None

    if not result.get("Описание гибридного транспортного средства"):
        result["Описание гибридного транспортного средства"] = _hybrid_desc()


    def pick_by_label(key: str):
        n = _norm(key)
        # 1) точное совпадение по метке
        if n in by_label and by_label[n] not in (None, ""):
            return by_label[n]
        # 2) синонимы
        for alt in LABEL_ALIASES.get(key, []):
            nn = _norm(alt)
            if nn in by_label and by_label[nn] not in (None, ""):
                return by_label[nn]
        # 3) осторожный фаззи: только для НЕ неоднозначных ключей
        if key not in AMBIGUOUS_LABELS:
            cands = [k for k in by_label.keys() if (n in k or k in n) and by_label[k] not in (None, "")]
            if len(cands) == 1:
                return by_label[cands[0]]
        return None
    
    def pick_by_id(key: str):
        # 1) Строгие алиасы ID
        for i in ID_ALIASES.get(key, []):
            if i in by_id and by_id[i] not in (None, ""):
                return by_id[i]

        substrs = SUBSTR_ID_ALIASES.get(key, [])
        if substrs:
            id_keys = list(by_id.keys())
            norm_pairs = []
            for k in id_keys:
                kn = k.lower().replace(".", "_")
                norm_pairs.append((k, kn, kn.split("_")[-1]))

            # спец-фильтр для «МАРКА»
            def _bad_for_mark(s: str) -> bool:
                s = s.lower()
                return any(t in s for t in ("engine_brand", "engine", "dvig", "motor", "electric", "em_"))

            for sub in substrs:
                subn = sub.lower()
                for orig, kn, last in norm_pairs:
                    if key == "МАРКА" and _bad_for_mark(kn): 
                        continue
                    if subn in last and by_id.get(orig) not in (None, ""):
                        return by_id[orig]
                for orig, kn, last in norm_pairs:
                    if key == "МАРКА" and _bad_for_mark(kn): 
                        continue
                    if subn in kn and by_id.get(orig) not in (None, ""):
                        return by_id[orig]
        return None


    # простые поля
    for k in list(result.keys()):
        if isinstance(result[k], dict):
            continue
        if k == "Дата оформления" and base_record:
            result[k] = base_record.get("registration_date") or pick_by_label(k) or pick_by_id(k)
            continue
        if k == "Статус" and base_record:
            result[k] = (
                base_record.get("status")
                or pick_by_label(k)
                or pick_by_id(k)
                or _html("listbox_status")           # html-fallback из плеера, если есть
            )
            continue
        result[k] = pick_by_label(k) or pick_by_id(k)

    # Габариты (метки + fallback по id)
    for sub, pat in {"длина": "длина", "ширина": "ширина", "высота": "высота"}.items():
        val = None
        for cand in [f"{pat}, мм", f"габаритная {pat}", f"габаритные {pat}", pat, f"- {pat}"]:
            v = pick_by_label(cand)
            if v:
                val = v; break
        if val is None:
            # по id: length/width/height
            sub_map = {"длина":"length","ширина":"width","высота":"height"}
            needle = sub_map[sub]
            for _id, _v in list(by_id.items()):
                kn = _id.lower().replace(".", "_")
                if needle in kn and _v not in (None, ""):
                    val = _v; break
        result["Габаритные размеры, мм"][sub] = val

    # Колея (метки + fallback по id)
    for sub, base_pat in {"передних": "колея передних кол", "задних": "колея задних кол"}.items():
        val = None
        for tail in ("ёс, мм", "ес, мм", "ёс", "ес", " колес, мм", " колес", ""):
            v = pick_by_label(base_pat + tail)
            if v:
                val = v; break
        if val is None:
            needle = "track_front" if sub == "передних" else "track_rear"
            for _id, _v in list(by_id.items()):
                kn = _id.lower().replace(".", "_")
                if needle in kn and _v not in (None, ""):
                    val = _v; break
        result["Колея передних/задних колес, мм"][sub] = val


# Комбинированная «Колея передних/задних колес, мм»: "2022/1830[/1830]"
    combo = (
        pick_by_label("Колея передних/задних колес, мм")
        or pick_by_label("Колея передних/задних колес")
    )
    if isinstance(combo, str):
        fr_val, rr_val = _parse_track_combo(combo)
        if fr_val and not result["Колея передних/задних колес, мм"].get("передних"):
            result["Колея передних/задних колес, мм"]["передних"] = _digits(fr_val) or fr_val
        if rr_val and not result["Колея передних/задних колес, мм"].get("задних"):
            # нормализуем пары/одинаковые значения
            result["Колея передних/задних колес, мм"]["задних"] = _digits_keep_pair_or_single(rr_val)



    # Подвеска
    for sub, pat in {"передняя": "подвеска (передняя)", "задняя": "подвеска (задняя)"}.items():
        val = pick_by_label(pat) or pick_by_label(f"подвеска {sub}")
        if not val:
            # Fallback по ID
            if sub == "передняя":
                val = by_id.get("textarea_front_suspension")
            else:
                val = by_id.get("textarea_back_suspension")
        result["Подвеска(тип)"][sub] = val

    # Тормозные системы (тип)
    def _set_if_empty(key, val):
        if not result["Тормозные системы (тип)"][key]:
            result["Тормозные системы (тип)"][key] = val

    _set_if_empty("рабочая",    by_id.get("textbox_br_work"))
    _set_if_empty("запасная",   by_id.get("textbox_br_spare"))
    _set_if_empty("стояночная", by_id.get("textbox_br_parking"))

    # Тормоза
    # А здесь менять на "только если пусто":
    for sub, pat in {
        "рабочая": "тормозная система (рабочая)",
        "запасная": "тормозная система (запасная)",
        "стояночная": "тормозная система (стояночная)",
    }.items():
        if not result["Тормозные системы (тип)"][sub]:
            result["Тормозные системы (тип)"][sub] = (
                pick_by_label(pat) or pick_by_label(f"тормозные системы ({sub})")
            )


    # Фолбэки из шапки
    if base_record:
        result.setdefault("ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)", base_record.get("vin"))
        if not result.get("ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"):
            result["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = base_record.get("vin")
        if not result.get("КАТЕГОРИЯ"):
            result["КАТЕГОРИЯ"] = base_record.get("category")
        if not result.get("ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"):
            result["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = base_record.get("testing_laboratory")

        # Исполнение загрузочного пространства (для категории N)
    if not result.get("Исполнение загрузочного пространства (для категории N)"):
        val = (
            pick_by_label("Исполнение загрузочного пространства (для категории N)")
            or pick_by_label("Исполнение загрузочного пространства")
            or pick_by_id("Исполнение загрузочного пространства (для категории N)")
            # ключевой word-scan по всем значениям на случай, если оно оказалось не в ожидаемом поле
            or next(
                (v for v in list(by_id.values()) + list(by_label.values())
                if isinstance(v, str) and re.search(r"(платформ\w+|манипулятор)", v, re.I)),
                None
            )
        )
        result["Исполнение загрузочного пространства (для категории N)"] = val

    # Кол-во мест спереди/сзади
    if not result.get("Количество мест спереди/ cзади (для категории М1)"):
        result["Количество мест спереди/ cзади (для категории М1)"] = by_id.get("textbox_number_of_seats")

    # ВМЕСТО блока под "Тип кузова / кол-во дверей: "универсал/5""
    body = by_id.get("listbox_type_body")
    doors = by_id.get("textbox_body_type")
    cur  = result.get("Тип кузова/количество дверей (для категории М1)")

    if body and doors:
        if (not cur) or cur.strip().isdigit() \
        or cur.strip().lower() in {body.strip().lower(), doors.strip().lower()}:
            result["Тип кузова/количество дверей (для категории М1)"] = _join(body, doors, sep="/")



    # Колесная формула/ведущие
    if not result.get("Колесная формула/ведущие колеса"):
        combo = by_id.get("textbox_wheel_formula")
        if not combo:
            combo = _join(by_id.get("wheel_formula"), by_id.get("listbox_drive_wheels"), sep=", ")
        result["Колесная формула/ведущие колеса"] = combo

    # База
    if not result.get("База, мм"):
        result["База, мм"] = by_id.get("textbox_base")

    # Колея: единое поле по ID, могло быть "2022/1830[/1830]"
    fr_id = by_id.get("textbox_track_front_rear_wheels")
    if isinstance(fr_id, str):
        fr_val, rr_val = _parse_track_combo(fr_id)
        if fr_val and not result["Колея передних/задних колес, мм"].get("передних"):
            result["Колея передних/задних колес, мм"]["передних"] = _digits(fr_val) or fr_val
        if rr_val and not result["Колея передних/задних колес, мм"].get("задних"):
            result["Колея передних/задних колес, мм"]["задних"] = _digits_keep_pair_or_single(rr_val)
    # Массы
    if not result.get("Масса транспортного средства в снаряженном состоянии, кг"):
        result["Масса транспортного средства в снаряженном состоянии, кг"] = by_id.get("textbox_vehicle_weight")
    if not result.get("Технически допустимая максимальная масса транспортного средства, кг"):
        result["Технически допустимая максимальная масса транспортного средства, кг"] = by_id.get("textbox_technically_permissible_maximum_weight")

    if not result.get("Дополнительное оборудование транспортного средства"):
        result["Дополнительное оборудование транспортного средства"] = by_id.get("textarea-5cjdbc")

    # Экологический класс
    if not result.get("ЭКОЛОГИЧЕСКИЙ КЛАСС"):
        result["ЭКОЛОГИЧЕСКИЙ КЛАСС"] = by_id.get("listbox_environmental_class")

    # Двигатель: кол-во и расположение цилиндров
    if not result.get("- количество и расположение цилиндров"):
        cyl = by_id.get("numericinput_number_of_engine_cylinders")
        arr = by_id.get("listbox_description_engine_cylinder_arrangement") or by_id.get("listbox_description_engine_cylinder_arrangement_copy1")
        result["- количество и расположение цилиндров"] = _join(cyl, arr, sep=",")

    # Макс. мощность (кВт (мин.-1)) — из "143(5500)"
    if not result.get("- максимальная мощность, кВт (мин.-1)"):
        p = by_id.get("numericinput_maximum_power") or by_id.get("numericinput_engine_compression_ratio_copy1")
        result["- максимальная мощность, кВт (мин.-1)"] = p

    # Сцепка «имя + адрес» для заявителя/изготовителя/сборочного
    def _pair_any(name_id, *addr_ids):
        name = by_id.get(name_id)
        addr = next((by_id.get(a) for a in addr_ids if by_id.get(a)), None)
        return _join(name, addr)

    if not result.get("ЗАЯВИТЕЛЬ И ЕГО АДРЕС"):
        result["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = _pair_any(
            "textbox_applicant",
            "textbox_address_applicant", "textbox_address_applicant_legal",
            "textbox_fact_address1", "textbox_legal_address_ops"
        )

    if not result.get("ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"):
        result["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] = _pair_any(
            "textbox_manufacturer",
            "textbox_address_manufacturer", "textbox_address_manufacturer_legal",
            "textbox_address_manufacturer_kz"
        )

    if not result.get("СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"):
        result["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] = _pair_any(
            "textbox_assembly_plant",
            "textbox_address_assembly_plant", "textbox_address_assembly_plant_kz"
        )

    def _first_by_id_contains(*needles):
        for k, v in by_id.items():
            kk = (k or "").lower()
            if v and all(n in kk for n in needles):
                return v
        return None

    if not result.get("ЗАЯВИТЕЛЬ И ЕГО АДРЕС"):
        result["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = _join(
            by_id.get("textbox_applicant") or pick_by_label("заявитель"),
            _first_by_id_contains("address","applicant") or pick_by_label("адрес заявителя")
        )

    if not result.get("ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"):
        result["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] = _join(
            by_id.get("textbox_manufacturer") or pick_by_label("изготовитель"),
            _first_by_id_contains("address","manufacturer")
        )

    if not result.get("СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"):
        result["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] = _join(
            by_id.get("textbox_assembly_plant") or pick_by_label("сборочный завод"),
            _first_by_id_contains("address","assembly")
        )

    # После основных простых полей:
    if not result.get("Описание гибридного транспортного средства"):
        desc = pick_by_label("Описание гибридного транспортного средства")
        if not desc:
            desc = next((v for v in by_label.values()
                        if isinstance(v, str) and re.search(r"подзарядк|гибрид|рекуперац", v, re.I)), None)
        result["Описание гибридного транспортного средства"] = desc
        

    if not result.get("Электромашина (марка, тип)"):
        # кандидаты из id/label
        em_cands = [
            pick_by_id("Электромашина (марка, тип)"),
            _first_by_id_like("electric", "machine"),
            _first_by_id_like("electric", "motor"),
            _first_by_label_contains("электромаш", "тип"),
            _first_by_label_contains("электродвигател"),
        ]
        em = next((s for s in em_cands if s and _looks_like_em_brand_type(s)), None)
        result["Электромашина (марка, тип)"] = em



    if not result.get("Электродвигатель электромобиля"):
        result["Электродвигатель электромобиля"] = (
            pick_by_id("Электродвигатель электромобиля")
            or _first_by_id_contains("electric", "motor")
            or _first_by_label_contains("электродвигател")
        )

        # Рабочее напряжение (если из JSON не пришло)
    if not result.get("Рабочее напряжение, В"):
        hv = (
            _html("textbox_operating_voltage", "operating_voltage", "voltage")
            or _html_from_substr_aliases("Рабочее напряжение, В")        # em_voltage и пр.
            or _html_like("electric", "motor", "voltage")
        )
        if hv:
            result["Рабочее напряжение, В"] = _digits(str(hv)) or hv

    # 30-минутная мощность (если из JSON не пришла)
    if not result.get("Максимальная 30-минутная мощность, кВт"):
        hp = (
                _html("textbox_power", "max_power", "power")
                or _html_from_substr_aliases("Максимальная 30-минутная мощность, кВт")  # em_30min_power, power_30min_e, …
                or _html_like("30", "min", "power")
        )
        if hp:
            result["Максимальная 30-минутная мощность, кВт"] = _digits(str(hp)) or hp

    # Описание гибридного ТС — добавь HTML-fallback
    if not result.get("Описание гибридного транспортного средства"):
        desc = (
            pick_by_label("Описание гибридного транспортного средства")
            or _html_from_substr_aliases("Описание гибридного транспортного средства")
            or next((v for v in by_label.values()
                    if isinstance(v, str) and re.search(r"подзарядк|гибрид|рекуперац", v, re.I)), None)
        )
        result["Описание гибридного транспортного средства"] = desc

    # Вид электромашины (человекочитаемое, из text-слота)
    if not result.get("Вид электромашины"):
        t = _html("listbox_type_electric_machine")
        if t:
            result["Вид электромашины"] = t

    # Электромашина (марка, тип)
    if not result.get("Электромашина (марка, тип)"):
        em = _html("textbox_electric_machine", "electric_machine", "electric_motor_type")
        if em:
            result["Электромашина (марка, тип)"] = em


    # Блок устройства накопления энергии — сделаем короче/жёстче:
    if not result.get("Устройство накопления энергии"):
        result["Устройство накопления энергии"] = (
            pick_by_label("Устройство накопления энергии")
            or _first_by_id_like("battery")
            or _first_by_label_contains("батар")
            or _first_by_label_contains("аккум")
            or _first_by_label_contains("накоплен", "энерг")
        )


        # --- Шины (единое поле) ------------------------------------------------------
    # Поддерживаем:
    #  • метрический: 315/80 R22.5, 195/65R15
    #  • дюймовый с 'x/×': 31x10.5R15
    #  • дюймовый «узкий»: 12.00 R20, 8.25R16, 12R22.5
    _TIRE_PATS = [
        re.compile(r'\b(?P<w>\d{3})\s*/\s*(?P<ar>\d{2})\s*(?:Z?R)?\s*(?P<rim>\d{2}(?:\.\d)?)\b', re.I),            # 315/80 R22.5
        re.compile(r'\b(?P<w>\d{1,2}(?:\.\d{1,2})?)\s*[x×]\s*(?P<h>\d{1,2}(?:\.\d{1,2})?)\s*(?:Z?R)?\s*(?P<rim>\d{2}(?:\.\d)?)\b', re.I),  # 31x10.5R15
        re.compile(r'\b(?P<w>\d{1,2}(?:\.\d{1,2})?)\s*(?:Z?R)?\s*(?P<rim>\d{2}(?:\.\d)?)\b', re.I),                # 12.00 R20 / 8.25R16 / 12R22.5
    ]
    _PR_RE = re.compile(r'\b(?P<pr>\d{2})\s*PR\b', re.I)

    def _norm_tire_any(s: str) -> str | None:
        if not isinstance(s, str):
            return None
        txt = s.upper().replace("Х", "X").replace("×", "X")
        txt = re.sub(r'\s+', ' ', txt).strip(' ,;')

        # вычленим PR, если есть
        mpr = _PR_RE.search(txt)
        pr = (mpr.group('pr') + "PR") if mpr else None

        for pat in _TIRE_PATS:
            m = pat.search(txt)
            if not m:
                continue
            gd = m.groupdict()
            if 'ar' in gd:       # метрический
                base = f"{gd['w']}/{gd['ar']} R{gd['rim']}"
            elif 'h' in gd:      # дюймовый с 'x'
                base = f"{gd['w']}X{gd['h']} R{gd['rim']}"
            else:                # дюймовый «узкий»
                base = f"{gd['w']} R{gd['rim']}"
            return (f"{base} {pr}".strip() if pr else base)

        # fallback: если похоже на размер (есть 'R' и диаметр), вернём очищенную строку
        if re.search(r'\bR\s*\d{2}(?:\.\d)?\b', txt):
            return txt
        return None

    def _pick_any_tire() -> str | None:
        # 1) единое поле по метке
        for lbl in LABEL_ALIASES.get("Шины", []):
            v = pick_by_label(lbl)
            n = _norm_tire_any(v) if v else None
            if n:
                return n

        # 2) по id (единые поля)
        for _id, _v in by_id.items():
            ik = (_id or "").lower().replace(".", "_")
            if _v and any(k in ik for k in ("tire_size", "tyre_size", "tire", "tyre")) and not any(k in ik for k in ("front", "rear")):
                n = _norm_tire_any(_v)
                if n:
                    return n

        # 3) если раздельно — склеим
        def _side(side_en: str) -> str | None:
            # по id
            for _id, _v in by_id.items():
                ik = (_id or "").lower().replace(".", "_")
                if _v and any(k in ik for k in (f"{side_en}_tire", f"{side_en}_tyre", f"tire_{side_en}", f"tyre_{side_en}", f"{side_en}_tire_size", f"tire_size_{side_en}")):
                    n = _norm_tire_any(_v)
                    if n:
                        return n
            # по метке
            side_ru = "передние" if side_en == "front" else "задние"
            for lbl in (f"шины ({side_ru})", f"типоразмер шин ({side_ru})", f"размер шин ({side_ru})"):
                v = pick_by_label(lbl)
                n = _norm_tire_any(v) if v else None
                if n:
                    return n
            return None

        tf, tr = _side("front"), _side("rear")
        if tf and tr:
            return tf if tf == tr else f"передние: {tf}; задние: {tr}"
        return tf or tr or None

    # записываем в итог по ключу шаблона
    result["Шины"] = _pick_any_tire()

    # --- напряжение: одно поле ---------------------------------
    def _pick_voltage() -> str | None:
        # приоритет: метки → точные id → подстроки id
        v = pick_by_label("Рабочее напряжение, В")
        if not v:
            for i in ID_ALIASES.get("Рабочее напряжение, В", []):
                if by_id.get(i): v = by_id[i]; break
        if not v:
            for sub in SUBSTR_ID_ALIASES.get("Рабочее напряжение, В", []):
                got = next((by_id[k] for k in by_id if sub in k.lower().replace(".", "_") and by_id[k]), None)
                if got: v = got; break
        return v

    result["Рабочее напряжение, В"] = _pick_voltage()

    # --- 30-минутная мощность: одно поле ------------------------
    def _pick_30min_power() -> str | None:
        p = (pick_by_label("Максимальная 30-минутная мощность, кВт")
            or _first_by_label_contains("30", "мин", "мощ")
            or _first_by_label_contains("получас", "мощ"))
        if not p:
            p = (_first_by_id_like("30", "min", "power")
                or _first_by_id_like("power", "30"))
        if not p:
            # Ласт-чанс: любой label с намёком на 30 мин, из значения вытаскиваем число
            for lbl, val in by_label.items():
                if "30" in lbl and "мощ" in lbl and isinstance(val, str):
                    d = _digits(val)
                    if d: 
                        p = d; break
        return p
    
    result["Максимальная 30-минутная мощность, кВт"] = _pick_30min_power()

    # Кол-во осей/колёс для прицепов, если не найдено явно
    if _norm_category(result.get("КАТЕГОРИЯ")).startswith("O") and not result.get("Количество осей/колес (для категории О)"):
        # попробуем оценить по "База, мм": 5700/1310/1310 → 3 оси
        base = result.get("База, мм")
        axles = None
        if isinstance(base, str):
            nums = re.findall(r"\d+(?:[.,]\d+)?", base)
            if nums:
                # эвристика: число осей = число сегментов расстояний в строке
                axles = len(nums) if len(nums) <= 5 else None  # guard
        # оценим колеса по шинам (385/65R22.5 — обычно одиночки → 2 колеса/ось)
        wheels = None
        if axles:
            tires = result.get("Шины") or ""
            if re.search(r"\b(3\d{2}|38\d)\s*/\s*\d{2}\s*R", tires):  # широкие, чаще одиночки
                wheels = axles * 2
            # иначе не гадаем
        if axles:
            result["Количество осей/колес (для категории О)"] = f"{axles}/{wheels}" if wheels else str(axles)


    def _clean_lab(s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip()
        name = s.split("-")[0].strip()
        code = re.search(r"\bKZ\.T\.\d{2}\.\d{4}\b", s)
        dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", s)
        tail = []
        if code: tail.append(code.group(0))
        if len(dates) >= 2:
            tail.append(f"до {dates[1]}")
        elif len(dates) == 1:
           tail.append(f"до {dates[0]}")
        return f"{name} ({', '.join(tail)})" if tail else name

    _postprocess_fields(result)

    # Нормализуем поле "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ" после общей постобработки
    lab = result.get("ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ")
    if isinstance(lab, str):
        result["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = _clean_lab(lab)

    return result

def _classify_electrification(f: dict) -> str:
    t = (f.get("ТИП") or "").upper()
    fuel = (f.get("Топливо") or "").lower()
    volt = _digits(str(
        f.get("Рабочее напряжение, В") or f.get("Рабочее напряжение, В (электромашина)") or ""
    ))
    kpp = (f.get("Коробка передач (марка, тип)") or "").lower()
    trn = (f.get("Трансмиссия") or "").lower()

    # считаем, что ДВС есть, если он явно указан в "ДВС (марка, тип)"
    # ИЛИ если "Двигатель" выглядит как код/описание ДВС и не содержит "электро"
    has_ice = bool(f.get("Двигатель внутреннего сгорания (марка, тип)"))
    if not has_ice:
        dv_any = f.get("Двигатель")
        if isinstance(dv_any, str) and _looks_like_engine_mark(dv_any) and not re.search(r"электродвиг|электро", dv_any, re.I):
            has_ice = True

    has_em = bool(f.get("Электромашина (марка, тип)") or f.get("Электродвигатель электромобиля"))

    if (
        "EREV" in t or "REEV" in t or
        ("редуктор" in kpp and volt and has_ice and not re.search(r"\b(механическ\w*|МКП)\b", trn, re.I))
    ):
        return "EREV"
    if "PHEV" in t: return "PHEV"
    if "HEV"  in t: return "HEV"
    try:
        vnum = float(volt.replace(",", ".")) if volt else None
    except: vnum = None
    if "MHEV" in t or (vnum and 42 <= vnum <= 72 and has_ice):
        return "MHEV"
    if "BEV" in t or ("редуктор" in kpp and volt and not has_ice): return "BEV"
    if has_em and (volt or "электро" in trn or "редуктор" in kpp):
        return "HEV" if has_ice else "BEV"
    return "ICE"



# --- постобработка полей ---
VIN_BRANDS = {
    "KNA": "KIA", "KND": "KIA", "KNM": "KIA",
    "KMH": "HYUNDAI", "KM8": "HYUNDAI", "TMA": "HYUNDAI",
    "JT": "TOYOTA", "JTD": "TOYOTA",
    "JN1": "NISSAN",
    "JHM": "HONDA",
    "WVW": "VOLKSWAGEN",
    "WBA": "BMW",
    "WDB": "MERCEDES-BENZ",
    "WAU": "AUDI",
    "VF1": "RENAULT",
    "VSS": "SEAT",
    "TMB": "SKODA",
    "UU1": "DACIA",
    "SAL": "LAND ROVER",
    "YV1": "VOLVO",
    "ZFA": "FIAT",
    "5YJ": "TESLA",
    "LZZ": "SINOTRUK",   # CNHTC / Sinotruk (HOWO)
    "LRW": "TESLA",      # Shanghai
    "LGX": "BYD",       # BYD (China)
    "XTA": "LADA",
}

MODEL_BRAND = {
    "SELTOS": "KIA",
    "LEOPARD 3": "BYD",      # твой кейс
    "LEOPARD3": "BYD",
    "FANGCHENGBAO": "BYD",   # суббренд BYD
}

_BRAND_CANON = {
    "КИА": "KIA", "KIA": "KIA",
    "ХЁНДЭ": "HYUNDAI", "ХЁНДАЙ": "HYUNDAI", "ХЕНДАЙ": "HYUNDAI", "HYUNDAI": "HYUNDAI",
    "ТОЙОТА": "TOYOTA", "TOYOTA": "TOYOTA",
    "ХОНДА": "HONDA", "HONDA": "HONDA",
    "Ниссан".upper(): "NISSAN", "NISSAN": "NISSAN",
    "ФОЛЬКСВАГЕН".upper(): "VOLKSWAGEN", "VOLKSWAGEN": "VOLKSWAGEN", "VW": "VOLKSWAGEN",
    "БМВ": "BMW", "BMW": "BMW",
    "МЕРСЕДЕС-БЕНЦ": "MERCEDES-BENZ", "МЕРСЕДЕС": "MERCEDES-BENZ", "MERCEDES": "MERCEDES-BENZ", "MERCEDES-BENZ": "MERCEDES-BENZ",
    "АУДИ": "AUDI", "AUDI": "AUDI",
    "РЕНО": "RENAULT", "RENAULT": "RENAULT",
    "ШЕВРОЛЕ": "CHEVROLET", "CHEVROLET": "CHEVROLET",
    "ДЖИЛИ": "GEELY", "GEELY": "GEELY",
    "ЧАНГАН": "CHANGAN", "CHANGAN": "CHANGAN",
    "ЛАДА": "LADA", "ВАЗ": "LADA", "LADA": "LADA",
    "BYD": "BYD", "БИД": "BYD",
    "TESLA": "TESLA",
    "SINOTRUK": "SINOTRUK",
    "CNHTC": "SINOTRUK",
    "HOWO": "HOWO",
    # добавляй при необходимости
}

def _brand_from_text(s: str) -> str | None:
    if not s:
        return None
    up = str(s).upper().translate(_CYR_TO_LAT)
    for k, canon in _BRAND_CANON.items():
        if k in up:
            return canon
    # Игнорируем «хвосты» организационно-правовой формы
    m = re.search(r'([A-ZА-ЯЁ]{2,}(?:-[A-ZА-ЯЁ]{2,})?)\s*$', up)
    if m:
        token = m.group(1).rstrip(".")
        BAD_TOKENS = {"CO","COMPANY","LLC","LTD","INC","GMBH","AG","SA","SAS","SPA","PLC"}
        if token in BAD_TOKENS:
            return None
        return _BRAND_CANON.get(token, token)
    return None

def _digits(s):
    if not isinstance(s, str): return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", s.replace(" ", ""))
    return m.group(1).replace(",", ".") if m else None

def _normalize_year(y):
    if not isinstance(y, str): return y
    m = re.search(r'(?:19|20)\d{2}(?=\D|$)', y)
    return m.group(0) if m else y

def _looks_like_engine_mark(s: str) -> bool:
    s = (s or "").lower()
    if any(w in s for w in ("двигател", "турбонадду", "зажиган", "впрыск")):
        return True
    return bool(re.search(r'[a-zа-я]\d', s, flags=re.I))


def _derive_brand_from_vin(vin):
    if not isinstance(vin, str) or len(vin) < 2: return None
    wmi3 = vin[:3].upper()
    if wmi3 in VIN_BRANDS: return VIN_BRANDS[wmi3]
    wmi2 = vin[:2].upper()
    if wmi2 == "JT": return "TOYOTA"
    return None

def _clean_str(v: str) -> str:
    v = v.replace("\u00A0", " ").strip()
    return re.sub(r"\s+", " ", v)

def _postprocess_fields(f: dict) -> None:
    # Флаги
    mode = _classify_electrification(f)
    cat = _norm_category(f.get("КАТЕГОРИЯ"))
    is_trailer = isinstance(cat, str) and cat.startswith("O")
    is_electric = (mode in ("BEV","PHEV","HEV","EREV","MHEV")) and not is_trailer

    # Если в поле ДВС попалось "электро...", считаем EV и чистим ДВС
    dv_val = f.get("Двигатель внутреннего сгорания (марка, тип)")
    if isinstance(dv_val, str) and re.search(r"электродвиг|электро", dv_val, flags=re.I):
        is_electric = True
        f["Двигатель внутреннего сгорания (марка, тип)"] = None

    # Прицепы не имеют силовой установки
    if is_trailer:
        is_electric = False
        powertrain_keys = (
            "Двигатель","Двигатель внутреннего сгорания (марка, тип)",
            "- количество и расположение цилиндров","- рабочий объем цилиндров, см3",
            "- степень сжатия","- максимальная мощность, кВт (мин.-1)",
            "Топливо","Система питания (тип)","Система зажигания (тип)",
            "Система выпуска и нейтрализации отработавших газов",
            "Сцепление (марка, тип)","Трансмиссия","Коробка передач (марка, тип)","Редуктор",
            "Электродвигатель электромобиля","Вид электромашины","Электромашина (марка, тип)",
            "Рабочее напряжение, В","Максимальная 30-минутная мощность, кВт","Устройство накопления энергии",
        )
        ax_wheels = f.get("Количество осей/колес (для категории О)")
        if ax_wheels and isinstance(ax_wheels, str) and "/" in ax_wheels:
            ax = ax_wheels.split("/", 1)[0].strip()
            if ax.isdigit():
                f["Колесная формула/ведущие колеса"] = f"{int(ax)*2}x0"  # грубо: 2 колеса/ось => 6×0 при 3 осях
            else:
                f["Колесная формула/ведущие колеса"] = None
        else:
            f["Колесная формула/ведущие колеса"] = None
        for k in powertrain_keys:
            f[k] = None

            # --- ВНЕ прицепов: топливо для EV/гибридов ---
        if not is_trailer:
            if mode in ("PHEV", "HEV", "EREV"):
                tv = f.get("Топливо")
                if isinstance(tv, str) and re.fullmatch(r"\s*бензин\s*", tv, re.I):
                    f["Топливо"] = "бензин/электроэнергия"
                elif not tv:
                    f["Топливо"] = "бензин/электроэнергия"
            elif mode == "BEV":
                f["Топливо"] = "электроэнергия"

        # --- Пояснение для EREV ---
        if mode == "EREV" and not f.get("Описание гибридного транспортного средства"):
            f["Описание гибридного транспортного средства"] = (
                "РЭУ (range extender); привод — электрический, ДВС — генератор."
            )

        # --- EV-дублирование полей ---
        if is_electric:
            if not f.get("Рабочее напряжение, В (электромашина)") and f.get("Рабочее напряжение, В"):
                f["Рабочее напряжение, В (электромашина)"] = f["Рабочее напряжение, В"]
            if not f.get("Максимальная 30-минутная мощность, кВт") and f.get("Максимальная 30-минутная мощность, кВт (электромашина)"):
                f["Максимальная 30-минутная мощность, кВт"] = f["Максимальная 30-минутная мощность, кВт (электромашина)"]

    # Год выпуска → YYYY
    f["ГОД ВЫПУСКА"] = _normalize_year(f.get("ГОД ВЫПУСКА"))

    # Нормализуем кириллицу в «ТИП»
    if isinstance(f.get("ТИП"), str):
        f["ТИП"] = f["ТИП"].translate(_CYR_TO_LAT)

    # Если есть «Двигатель», а ДВС пуст/шаблонный — подставим «Двигатель»
    if f.get("Двигатель") and not is_electric:
        dv = (f.get("Двигатель внутреннего сгорания (марка, тип)") or "").strip().lower()
        if not dv or dv == "двигатель внутреннего сгорания":
            f["Двигатель внутреннего сгорания (марка, тип)"] = f["Двигатель"]

    # КПП из «Трансмиссия», если не заполнено
    if not f.get("Коробка передач (марка, тип)"):
        tr = (f.get("Трансмиссия") or "").lower()
        if "гидромехан" in tr:
            f["Коробка передач (марка, тип)"] = "АКП (гидромеханическая)"
        elif "робот" in tr or "dct" in tr:
            f["Коробка передач (марка, тип)"] = "РКП/DCT"
        elif "вариатор" in tr or "cvt" in tr:
            f["Коробка передач (марка, тип)"] = "CVT"
        elif "механ" in tr:
            f["Коробка передач (марка, тип)"] = "МКП"

    # МАРКА: выводим из надежных источников и канонизируем
    val_mark = f.get("МАРКА")
    vin = f.get("ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)")
    model = (f.get("КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ") or "").strip().upper()
    manuf = f.get("ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС")
    assembly = f.get("СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС")
    brand = (_brand_from_text(val_mark) or MODEL_BRAND.get(model) or
             _derive_brand_from_vin(vin) or _brand_from_text(manuf) or _brand_from_text(assembly))
    if brand:
        f["МАРКА"] = brand

    # Числовая нормализация габаритов
    g = f.get("Габаритные размеры, мм") or {}
    for k in ("длина", "ширина", "высота"):
        if isinstance(g.get(k), str):
            d = _digits(g[k])
            if d:
                g[k] = d
    f["Габаритные размеры, мм"] = g

    # База
    v = f.get("База, мм")
    if isinstance(v, str):
        s = v.replace("\u00A0", " ").strip()
        f["База, мм"] = s if "/" in s else (_digits(s) or s)

    # Колея
    kol = f.get("Колея передних/задних колес, мм") or {}
    if isinstance(kol.get("передних"), str) and "/" in kol["передних"]:
        a, b = _parse_track_combo(kol["передних"])
        if a: kol["передних"] = _digits(a) or a
        if b and not kol.get("задних"):
            kol["задних"] = _digits_keep_pair_or_single(b)
    for kk in ("передних", "задних"):
        vv = kol.get(kk)
        if isinstance(vv, str):
            kol[kk] = _digits_keep_pair_or_single(vv) if kk == "задних" else (_digits(vv) or (vv.split("/",1)[0] if "/" in vv else vv))
    f["Колея передних/задних колес, мм"] = kol

    # Массы
    for key in (
        "Масса транспортного средства в снаряженном состоянии, кг",
        "Технически допустимая максимальная масса транспортного средства, кг",
    ):
        if isinstance(f.get(key), str):
            d = _digits(f[key])
            if d:
                f[key] = d

    # Числа из напряжения/30-мин. мощности
    for key in (
        "Рабочее напряжение, В",
        "Рабочее напряжение, В (электромашина)",
        "Максимальная 30-минутная мощность, кВт",
        "Максимальная 30-минутная мощность, кВт (электромашина)",
    ):
        val = f.get(key)
        if isinstance(val, str):
            d = _digits(val)
            if d:
                f[key] = d

    # Взаимная подстановка 30-минутной мощности
    if not f.get("Максимальная 30-минутная мощность, кВт") and f.get("Максимальная 30-минутная мощность, кВт (электромашина)"):
        f["Максимальная 30-минутная мощность, кВт"] = f["Максимальная 30-минутная мощность, кВт (электромашина)"]
    if not f.get("Максимальная 30-минутная мощность, кВт (электромашина)") and f.get("Максимальная 30-минутная мощность, кВт"):
        f["Максимальная 30-минутная мощность, кВт (электромашина)"] = f["Максимальная 30-минутная мощность, кВт"]

    # EV-дублирование полей, если это реально EV/гибрид
    if is_electric:
        if not f.get("Рабочее напряжение, В (электромашина)") and f.get("Рабочее напряжение, В"):
            f["Рабочее напряжение, В (электромашина)"] = f["Рабочее напряжение, В"]
        if not f.get("Максимальная 30-минутная мощность, кВт") and f.get("Максимальная 30-минутная мощность, кВт (электромашина)"):
            f["Максимальная 30-минутная мощность, кВт"] = f["Максимальная 30-минутная мощность, кВт (электромашина)"]

    # Подчистим пробелы и типовые «склейки» в текстах
    def _fix_common_glues(s: str) -> str:
        s = s.replace("диагональнымразделением", "диагональным разделением")
        s = s.replace("сэлектронной", "с электронной")
        s = s.replace("заднихколес", "задних колес")
        s = s.replace("тормозныемеханизмы", "тормозные механизмы")
        s = re.sub(r'шестерня-\s+рейка', 'шестерня-рейка', s, flags=re.I)
        return s

    for k, v in list(f.items()):
        if isinstance(v, str):
            v = v.replace("\u00A0", " ").strip()
            v = re.sub(r"\s+", " ", v)
            f[k] = _fix_common_glues(v)
        elif isinstance(v, dict):
            for kk, vv in list(v.items()):
                if isinstance(vv, str):
                    vv = vv.replace("\u00A0", " ").strip()
                    vv = re.sub(r"\s+", " ", vv)
                    v[kk] = _fix_common_glues(vv)

    if isinstance(f.get("Тормозные системы (тип)"), dict):
        for kk, vv in list(f["Тормозные системы (тип)"].items()):
            if isinstance(vv, str):
                f["Тормозные системы (тип)"][kk] = _fix_common_glues(vv)


                     # Если в поле ДВС затесилось «электродвигатель» — это электромобиль, очищаем ДВС
    if not f.get("Топливо") and not is_trailer and (
        f.get("Электромашина (марка, тип)") or f.get("Электродвигатель электромобиля")
    ):
        f["Топливо"] = "электроэнергия"


@techreg_bp.get("/diag/sbkts/detail")
def diag_sbkts_detail():
    num = (request.args.get("num") or "").strip()
    if not num:
        return jsonify({"ok": False, "reason": "missing_num"}), 400
    cl = get_client()
    base = cl.get_sbkts_by_number(num)
    if not base.get("ok"):
        return jsonify(base), 404
    doc_id = base.get("documentID"); data_uuid = base.get("dataUUID")
    detail = None
    if data_uuid:
        try: detail = cl.asforms_data(data_uuid)
        except: detail = None
    if detail is None and doc_id:
        try: detail = cl.asforms_collate(doc_id)
        except: detail = None
    if not detail:
        return jsonify({"ok": False, "reason": "no_detail"}), 502
    return jsonify({"ok": True, "detail": detail})





@techreg_bp.get("/sbkts/by-number/fields")
def sbkts_fields_by_number():
    num_in = (request.args.get("num") or "").strip()
    if not num_in:
        return jsonify({"ok": False, "reason": "missing_num"}), 400

    cl = get_client()

    # 1) как есть
    base = cl.get_sbkts_by_number(num_in)

    # 2) пробуем нормализацию (ТС KZ/кириллица/пэддинги)
    number_norm = None
    if not base.get("ok"):
        number_norm = normalize_techreg_num(num_in)
        if number_norm and number_norm != num_in:
            base = cl.get_sbkts_by_number(number_norm)

    if not base.get("ok"):
        return jsonify(base), 404

    doc_id = base.get("documentID")
    data_uuid = base.get("dataUUID")

    # 3) детальная форма
    detail = None
    if data_uuid:
        try:
            try:
                detail = cl.asforms_data(data_uuid)
            except:
                if str(data_uuid).isdigit():
                    detail = cl.asforms_data(int(data_uuid))
        except:
            detail = None
    if detail is None and doc_id:
        try:
            detail = cl.asforms_collate(doc_id)
        except:
            detail = None

    if not detail:
        return jsonify({"ok": False, "reason": "no_detail", "documentID": doc_id, "dataUUID": data_uuid}), 502

    # 4) парсинг под шаблон
    rec_en = {
        "vin": (base.get("record") or {}).get("VIN"),
        "category": (base.get("record") or {}).get("Категория"),
        "registration_date": (base.get("record") or {}).get("Дата оформления"),
        "testing_laboratory": (base.get("record") or {}).get("Испытательная лаборатория"),
        "status": (base.get("record") or {}).get("Статус"),
    }

    def _fetch_html():
        try:
            return cl.get_player_html(doc_id)  # см. п.4 ниже
        except Exception:
            return None

    fields_raw = _extract_fields_from_detail(detail, rec_en, fetch_html=_fetch_html)


    import copy
    tpl = copy.deepcopy(FIELDS_TEMPLATE)
    for k in tpl.keys():
        if k in fields_raw:
            tpl[k] = fields_raw[k]

    return jsonify({
        "ok": True,
        "number": (base.get("record") or {}).get("N") or number_norm or num_in,
        "documentID": doc_id,
        "dataUUID": data_uuid,
        "fields": tpl
    })

@techreg_bp.get("/diag/sbkts/labels")
def diag_sbkts_labels():
    num = (request.args.get("num") or "").strip()
    if not num:
        return jsonify({"ok": False, "reason": "missing_num"}), 400

    cl = get_client()
    base = cl.get_sbkts_by_number(num)
    if not base.get("ok"):
        return jsonify(base), 404

    doc_id = base.get("documentID"); data_uuid = base.get("dataUUID")
    detail = None
    if data_uuid:
        try: detail = cl.asforms_data(data_uuid)
        except: detail = None
    if detail is None and doc_id:
        try: detail = cl.asforms_collate(doc_id)
        except: detail = None
    if not detail:
        return jsonify({"ok": False, "reason": "no_detail"}), 502

    items = []
    for it in (detail.get("data") or []):
        cid = it.get("id") or ""
        lbl = it.get("label")
        val = it.get("value")

        # нормализуем значение
        if isinstance(val, dict):
            val = val.get("label") or val.get("text") or val.get("value")
        elif isinstance(val, list):
            val = ", ".join([(x.get("label") if isinstance(x, dict) else str(x)) for x in val if x]) or None

        # для select-подобных — показываем выбранное значение, не подпись поля
        if not val and cid.replace(".", "_").lower().startswith(("listbox_","combobox_","dropdown_","dictionary_","reglink_")):
            raw = it.get("value")
            if isinstance(raw, dict):
                val = raw.get("label") or raw.get("text") or raw.get("value")
            elif isinstance(raw, list):
                val = ", ".join([(x.get("label") if isinstance(x, dict) else str(x)) for x in raw if x]) or None
            else:
                val = it.get("valueLabel") or it.get("selectedText") or None

        items.append({
            "id": cid,
            "id_alts": [cid.replace(".", "_"), cid.split(".")[-1]],
            "label": lbl,
            "value": val,
        })

    contains = (request.args.get("contains") or "").strip()
    if contains:
        needles = [t.strip().lower() for t in contains.split(",") if t.strip()]
        items = [
            it for it in items
            if any(
                n in (str(it.get("label") or "")).lower()
                or n in (it.get("id") or "").lower()
                or any(n in (a or "").lower() for a in it.get("id_alts") or [])
                for n in needles
            )
        ]

    return jsonify({"ok": True, "labels": items, "count": len(items)})




# techreg_blueprint.py (добавь рядом с импортами)
def _normalize_record_ru_to_en(rec: dict) -> dict:
    return {
        "status": rec.get("Статус"),
        "registration_date": rec.get("Дата оформления"),
        "number": rec.get("N"),
        "application": rec.get("Заявка"),
        "testing_laboratory": rec.get("Испытательная лаборатория"),
        "bin": rec.get("БИН"),
        "full_name_ru": rec.get("Полное наименование"),
        "full_name_kz": rec.get("Полное наименование на казахском"),
        "short_name": rec.get("Сокращенное наименование"),
        "lab_head": rec.get("Руководитель ИЛ"),
        "legal_address_ru": rec.get("Юридический адрес"),
        "legal_address_kz": rec.get("Юридический адрес (каз)"),
        "actual_address": rec.get("Фактический адрес"),
        "vin": rec.get("VIN"),
        "category": rec.get("Категория"),
    }

def get_client():
    cookies = None
    if os.path.exists("techreg_cookies.json"):
        try:
            cookies = TechRegClient.load_cookies_from_file("techreg_cookies.json")
        except Exception:
            cookies = None
    cl = TechRegClient(cookies=cookies, verify=VERIFY_SSL)
    cl.warmup()
    return cl

@techreg_bp.get("/ping")
def ping():
    cl = get_client()
    out = {"ok": True, "checks": [], "cookies": sorted(list(cl.session.cookies.get_dict().keys())),
           "has_auth_header": "Authorization" in cl.session.headers}
    try:
        me = cl.person_auth()
        out["checks"].append({"endpoint": "person/auth", "ok": True, "user": me.get("code") if isinstance(me, dict) else None})
    except Exception as e:
        out["checks"].append({"endpoint": "person/auth", "ok": False, "err": str(e)})

    try:
        js = cl.dictionary("ts_category")
        out["checks"].append({"endpoint": "dictionary/ts_category", "ok": True})
    except Exception as e:
        out["checks"].append({"endpoint": "dictionary/ts_category", "ok": False, "err": str(e)})

    return jsonify(out)

# Диагностика: список реестров / фильтры / count
@techreg_bp.get("/diag/registries")
def diag_regs():
    cl = get_client()
    regs = cl.list_registries()
    items_src = regs.get("result", []) if isinstance(regs, dict) else regs
    items = [{"code": (r.get("code") or r.get("registryCode")), "name": r.get("name")} for r in items_src]
    return jsonify({"ok": True, "items": items})


@techreg_bp.get("/diag/sbkts/filters")
def diag_sbkts_filters():
    cl = get_client()
    f = cl.registry_filters(registry_code="registry_certificate_safety_vehicle_structure")
    return jsonify({"ok": True, "filters": f})


# techreg_blueprint.py
@techreg_bp.route("/diag/echo", methods=["POST"])
def techreg_diag_echo():
    data = request.get_json(silent=True) or {}
    raw = (data.get("num") or "").strip()
    return jsonify({
        "raw": raw,
        "canon": normalize_techreg_num(raw),
        "variants": techreg_number_variants(raw),
    })

@techreg_bp.get("/diag/sbkts/count")
def diag_sbkts_count():
    num = (request.args.get("num") or "").strip()
    if not num:
        return jsonify({"ok": False, "reason": "missing_num"}), 400
    cl = get_client()
    cnt = cl.registry_count("registry_certificate_safety_vehicle_structure", searchField="textbox_number", key=num)
    return jsonify({"ok": True, "count": cnt})

@techreg_bp.get("/diag/sbkts/sample")
def diag_sbkts_sample():
    num = (request.args.get("num") or "").strip()
    if not num:
        return jsonify({"ok": False, "reason": "missing_num"}), 400
    cl = get_client()
    data = cl.registry_data(
        "registry_certificate_safety_vehicle_structure",
        page=0, size=1, heavy=True,
        fields=["textbox_number","documentID","dataUUID"],
        field="textbox_number", condition="TEXT_EQUALS", value=num
    )
    return jsonify({"ok": True, "raw": data})

@techreg_bp.post("/sbkts/batch")
def sbkts_batch():
    payload = request.get_json(silent=True) or {}
    nums = payload.get("numbers") or []
    fmt = (payload.get("format") or "ru").lower()
    cl = get_client()
    out = []
    for n in nums:
        try:
            res = cl.get_sbkts_by_number(str(n))
            if res.get("ok") and fmt == "en" and "record" in res:
                res = {**{k:v for k,v in res.items() if k!="record"}, "record": _normalize_record_ru_to_en(res["record"])}
            out.append({"number": n, **res})
        except Exception as e:
            out.append({"number": n, "ok": False, "error": str(e)})
    return jsonify({"ok": True, "results": out})


@techreg_bp.get("/sbkts/by-number")
def sbkts_by_number():
    number = (request.args.get("num") or "").strip()
    fmt = (request.args.get("format") or "ru").lower()
    if not number:
        return jsonify({"ok": False, "reason": "missing_num"}), 400
    cl = get_client()
    try:
        data = cl.get_sbkts_by_number(number)
        if data.get("ok") and fmt == "en" and "record" in data:
            data = {
                **{k: v for k, v in data.items() if k != "record"},
                "record": _normalize_record_ru_to_en(data["record"]),
            }
        return jsonify(data)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "where": "get_sbkts_by_number"}), 500
