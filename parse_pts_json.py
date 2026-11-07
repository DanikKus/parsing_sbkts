import requests
import re
from datetime import datetime
import urllib3
import os
from auth_token_selenium import get_token_and_cookies_via_selenium, load_auth_from_cache, save_auth_to_cache
import copy
import json

# --- Локальный справочник организаций ---
def load_organizations_from_file(filename="response.txt"):
    try:
        with open(filename, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("data", [])
    except Exception as e:
        print(f"❌ Не удалось загрузить список организаций из {filename}: {e}")
        return []

# Глобальный список — грузим ОДИН РАЗ при старте (это важно!)
ORG_LIST = load_organizations_from_file()

def get_org_from_file_by_id(org_id, org_list=ORG_LIST):
    # id может быть числом или строкой — сравниваем как строки!
    for org in org_list:
        if str(org["id"]) == str(org_id):
            name = org.get("name") or org.get("shortName") or ""
            address = org.get("factAddressName") or org.get("juridicalAddressName") or ""
            bin_val = org.get("bin", "")
            parts = []
            if name:
                parts.append(name)
            if address:
                parts.append(address)
            if bin_val:
                parts.append(f"БИН: {bin_val}")
            return ", ".join(parts)
    return None


def validate_token(token, cookies):
    url = "https://pts.gov.kz/api/ComplienceDocument/Get?id=00000000-0000-0000-0000-000000000000"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://pts.gov.kz/",
        "X-Requested-With": "XMLHttpRequest"
    }
    try:
        response = requests.get(url, headers=headers, cookies=cookies, verify=False, timeout=10)
        return response.status_code != 401
    except:
        return False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# def get_json(endpoint: str, doc_id: str, label: str = ""):
#     # <-- Новое: ВСЕГДА ЧИТАЕМ АКТУАЛЬНЫЕ token и cookies из кэша
#     token, cookies = load_auth_from_cache()
#     if not token:
#         print("❌ Нет токена! Сначала пройди авторизацию.")
#         return None

#     headers = {
#         "Authorization": f"Bearer {token}",
#         "Accept": "application/json",
#         "User-Agent": "Mozilla/5.0",
#         "Referer": "https://pts.gov.kz/",
#         "X-Requested-With": "XMLHttpRequest"
#     }
#     url = f"https://pts.gov.kz/api/ComplienceDocument/{endpoint}?id={doc_id}"
#     try:
#         print(f"➡️ GET {url} с токеном: Bearer {token[:20]}...")
#         response = requests.get(url, headers=headers, cookies=cookies, verify=False)
#         response.raise_for_status()
#         data = response.json().get("data", None)

#         if data in [None, [], {}]:
#             print(f"⚠️ Нет данных из '{endpoint}' → поле '{label}' останется пустым.")
#         else:
#             print(f"✅ Данные загружены из '{endpoint}' для поля '{label}'")

#         return data

#     except Exception as e:
#         print(f"❌ Ошибка при запросе {url}: {e}")
#         return None

def get_json(endpoint: str, doc_id: str, label: str = ""):
    # Теперь читаем и токен, и cookies, но токен – НЕ обязателен
    token, cookies = load_auth_from_cache()

    if not token and not cookies:
        print("❌ Нет ни токена, ни cookies. Скорее всего, расширение ещё не прикреплено.")
        return None

    url = f"https://pts.gov.kz/api/ComplienceDocument/{endpoint}?id={doc_id}"

    # Базовые заголовки
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://pts.gov.kz/",
        "X-Requested-With": "XMLHttpRequest",
    }

    # Если токен всё-таки есть (например, Selenium или расширение его тоже кладёт) – добавляем
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        print(f"➡️ GET {url} (token={'yes' if token else 'no'}, cookies={'yes' if cookies else 'no'})")
        resp = requests.get(url, headers=headers, cookies=cookies or {}, verify=False, timeout=20)
        print(f"   ↳ status = {resp.status_code}")

        if resp.status_code == 401:
            print("❌ 401 Unauthorized от pts.gov.kz – куки/сессия невалидны. Нужно заново подключить расширение.")
            return None

        resp.raise_for_status()
        data = resp.json().get("data", None)

        if data in [None, [], {}]:
            print(f"⚠️ Нет данных из '{endpoint}' → поле '{label}' останется пустым.")
        else:
            print(f"✅ Данные загружены из '{endpoint}' для поля '{label}'")

        return data

    except Exception as e:
        print(f"❌ Ошибка при запросе {url}: {e}")
        return None


# Шаблон полей
FIELDS_TEMPLATE = {
    "Номер документа": None,  # ← добавить
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
    "Двигатель": None,
    "Описание гибридного привода": None,  # 🆕 ВСТАВИТЬ сюда
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
    "Дата оформления": None
}

def extract_doc_id(url: str) -> str:
    match = re.search(r'/([a-f0-9\-]{36})', url)
    return match.group(1) if match else None


def get_org_name_and_address(org_id, headers=None, cookies=None):
    org_info = get_org_from_file_by_id(org_id)
    if org_info:
        return org_info
    return f"[Организация, id={org_id}]"

def parse_vehicle_data_from_raw(raw: dict) -> dict:
    """
    raw = { base: <ComplienceDocument/Get data|data>, details: {...} }
    details — это .data из всех доп. эндпоинтов (см. fetchAllDetailsById)
    """
    if not isinstance(raw, dict):
        return {}

    raw = raw or {}
    base = raw.get("base") or raw.get("data") or raw
    details = raw.get("details") or {}

    base_data = base.get("data") or base

    data = copy.deepcopy(FIELDS_TEMPLATE)
    data["Габаритные размеры, мм"] = {"длина": None, "ширина": None, "высота": None}
    data["Подвеска(тип)"] = {"передняя": None, "задняя": None}
    data["Тормозные системы (тип)"] = {"рабочая": None, "запасная": None, "стояночная": None}

    # ---- базовый документ
    vtype = (base or {}).get("vehicleTypeDetail", {}) or {}
    chars = vtype.get("characteristicsDetail", {}) or {}

    data["Номер документа"] = base.get("docNumber")
    if base.get("docDate"):
        data["Дата оформления"] = str(base["docDate"]).split("T")[0]
    data["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = base.get("authorityName")
        # --- ЗАЯВИТЕЛЬ ---
    private_person_id = base.get("applicantPPId")
    organization_id = base.get("organizationId")
    applicant_id = base.get("applicantId")

    if base.get("applicantName"):
        applicant_str = base.get("applicantName")
    elif private_person_id:
        applicant_str = f"[физ.лицо id={private_person_id}]"
    elif organization_id:
        applicant_str = get_org_name_and_address(organization_id) or f"[Организация id={organization_id}]"
    elif applicant_id:
        applicant_str = get_org_name_and_address(applicant_id) or f"[Организация id={applicant_id}]"
    else:
        applicant_str = "Заявитель не определён"

    data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = applicant_str


    vins = base.get("vinNumbers") or []
    data["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = (vins[0] or {}).get("number") if vins else None

    makes = vtype.get("makes") or []
    data["МАРКА"] = (makes[0] or {}).get("dicName") if makes else None
    comm  = vtype.get("commercialNames") or []
    data["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] = (comm[0] or {}).get("commercialName") if comm else None
    types = vtype.get("types") or []
    data["ТИП"] = (types[0] or {}).get("typeValue") if types else None

    data["ГОД ВЫПУСКА"] = vtype.get("yearIssue")
    tech = vtype.get("techCategories") or []
    data["КАТЕГОРИЯ"] = (tech[0] or {}).get("dicName") if tech else None
    eco = vtype.get("ecoClasses") or []
    data["ЭКОЛОГИЧЕСКИЙ КЛАСС"] = (eco[0] or {}).get("dicName") if eco else None

    manufacturer = base.get("manufacturerName")
    if not manufacturer:
        plants = base.get("assemblyPlants") or []
        if plants:
            manufacturer = (plants[0] or {}).get("organization")
    data["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] = manufacturer
    plants = base.get("assemblyPlants") or []
    data["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] = (plants[0] or {}).get("organization") if plants else None

    engine_type_map = {5767: "Двигатель внутреннего сгорания", 5768: "Электрический двигатель", 5897: "Гибридное транспортное средство"}
    engine_type_id = chars.get("engineTypeId")
    data["Двигатель"] = engine_type_map.get(engine_type_id)

    # гибрид
    hybrid_text = (chars.get("vehicleHybridDesignText") or "").strip()
    if not hybrid_text:
        arr = chars.get("vehicleHybridDesigns") or []
        seen, acc = set(), []
        for it in arr:
            t = (it.get("vehicleHybridDesignText") or "").strip()
            if t and t not in seen:
                seen.add(t); acc.append(t)
        hybrid_text = ";\n".join(acc) if acc else None
    data["Описание гибридного привода"] = hybrid_text

    # ---- helpers
    def det(key):
        # ключи совпадают с именами в fetchAllDetailsById
        return details.get(key) or {}

    # электромашины
    em = det("machines")
    em_list = em.get("electricalMachineDetails") or []
    if em_list:
        if len(em_list) == 1:
            m = em_list[0]
            full = ", ".join(filter(None, [m.get("vehicleComponentMakeName"), m.get("vehicleComponentText")])).strip(", ")
            data["Электродвигатель электромобиля"] = full or None
            data["Рабочее напряжение, В"] = str(m.get("electricalMachineVoltageMeasure") or "") or None
            data["Максимальная 30-минутная мощность, кВт"] = str(m.get("electricMotorPowerMeasure") or "") or None
        else:
            marks_types = []
            kinds, voltages, powers = [], [], []
            for m in em_list:
                full = ", ".join(filter(None, [m.get("vehicleComponentMakeName"), m.get("vehicleComponentText")])).strip(", ")
                if full: marks_types.append(full)
                if m.get("electricalMachineKindName"): kinds.append(m.get("electricalMachineKindName"))
                if m.get("electricalMachineVoltageMeasure") is not None: voltages.append(str(m.get("electricalMachineVoltageMeasure")))
                if m.get("electricMotorPowerMeasure") is not None: powers.append(str(m.get("electricMotorPowerMeasure")))
            if marks_types: data["Электромашина (марка, тип)"] = ";\n".join(marks_types)
            if kinds:        data["Вид электромашины"] = ";\n".join(kinds)
            if voltages:     data["Рабочее напряжение, В (электромашина)"] = ";\n".join(voltages)
            if powers:       data["Максимальная 30-минутная мощность, кВт (электромашина)"] = ";\n".join(powers)

    # накопитель
    st = det("storage")
    sl = st.get("powerStorageDeviceDetails") or []
    if sl:
        items = []
        for s in sl:
            kind = s.get("powerStorageDeviceTypeName") or ""
            desc = (s.get("powerStorageDeviceDescription") or "").strip()
            items.append(kind if not desc or desc == "-" else f"{kind} ({desc})")
        data["Устройство накопления энергии"] = ";\n".join([i for i in items if i])

    # планировки/кабина/исполнение и пассажировместимость
    ld = det("layoutDetails")
    if ld.get("vehicleCarriageSpaceImplementations"):
        data["Исполнение загрузочного пространства (для категории N)"] = \
            (ld["vehicleCarriageSpaceImplementations"][0] or {}).get("carriageSpaceImplementation")
    if ld.get("vehicleCabins"):
        data["Кабина (для категории N)"] = (ld["vehicleCabins"][0] or {}).get("cabinDescription")
    vpq = (ld or {}).get("vehiclePassengerQuantities") or []
    if vpq:
        q = (vpq[0] or {}).get("passengerQuantity")
        if q is not None:
            data["Пассажировместимость (для категорий М2, М3)"] = q

    # сиденья (М1)
    seats = det("seats")
    if isinstance(seats, list) and seats:
        s0 = seats[0] or {}
        total = s0.get("seatQuantity")
        desc  = (s0.get("seatDescription") or "").strip()
        raws  = s0.get("vehicleSeatRawDetails") or []
        rows  = []
        for r in raws:
            o = r.get("seatRawOrdinal"); q = r.get("seatRawQuantity")
            if o is not None and q is not None: rows.append(f"{o}-{q}")
        parts = []
        if total is not None: parts.append(f"Количество мест для сидения: {total}")
        if desc: parts.append(f"Описание мест для сидения: {desc}")
        if rows: parts.append("Количество мест спереди/сзади:\n" + "\n".join(rows))
        if parts:
            data["Количество мест спереди/ cзади (для категории М1)"] = "\n".join(parts)

    # двигатель ДВС
    eng = det("engine")
    ed = (eng or {}).get("engineDetails") or []
    if ed:
        e = ed[0] or {}
        data["Двигатель внутреннего сгорания (марка, тип)"] = ", ".join(filter(None, [e.get("vehicleComponentMakeName"), e.get("vehicleComponentText")])).strip(", ") or None
        data["- количество и расположение цилиндров"] = " ".join(filter(None, [str(e.get("engineCylinderQuantity") or ""), e.get("engineCylinderArrangementName") or ""])).strip() or None
        data["- рабочий объем цилиндров, см3"] = e.get("engineCapacityMeasure")
        data["- степень сжатия"] = e.get("engineCompressionRate")
        ep = (e.get("enginePowerDetails") or [])
        if ep:
            p = ep[0] or {}
            data["- максимальная мощность, кВт (мин.-1)"] = f"{p.get('engineMaxPowerMeasure')} @ {p.get('engineMaxPowerShaftRotationFrequencyMinMeasure')}"
        fk = (e.get("vehicleFuelKinds") or [])
        if fk: data["Топливо"] = (fk[0] or {}).get("fuelKindName")
        ff = (e.get("engineFuelFeedDetails") or [])
        if ff: data["Система питания (тип)"] = (ff[0] or {}).get("fuelFeedName")
        ig = (e.get("vehicleIgnitionDetails") or [])
        if ig: data["Система зажигания (тип)"] = (ig[0] or {}).get("vehicleIgnitionTypeName")
        ex = (e.get("exhaustDetails") or [])
        if ex: data["Система выпуска и нейтрализации отработавших газов"] = (ex[0] or {}).get("exhaustDescription")

    # массы
    w = det("weight")
    for it in (w.get("vehicleWeightMeasures") or []):
        t = (it.get("massTypeName") or "").lower()
        if "снаряженном" in t:
            data["Масса транспортного средства в снаряженном состоянии, кг"] = it.get("weight")
        if "максимальная" in t:
            data["Технически допустимая максимальная масса транспортного средства, кг"] = it.get("weight")

    # габариты/колёсная база/высота
    dim = det("dimensions"); hgt = det("height"); wb = det("wheelbase")
    if dim.get("lengthRanges"): data["Габаритные размеры, мм"]["длина"]  = (dim["lengthRanges"][0] or {}).get("length")
    if dim.get("widthRanges"):  data["Габаритные размеры, мм"]["ширина"] = (dim["widthRanges"][0] or {}).get("width")
    if hgt.get("heightRanges"): data["Габаритные размеры, мм"]["высота"] = (hgt["heightRanges"][0] or {}).get("height")
    elif hgt.get("hightRanges"):  # опечатка в API
        data["Габаритные размеры, мм"]["высота"] = (hgt["hightRanges"][0] or {}).get("height")
    if wb.get("wheelbaseMeasureRanges"):
        data["База, мм"] = " / ".join(str(x.get("wheelbase")) for x in wb["wheelbaseMeasureRanges"] if x.get("wheelbase"))

    # колея и формула/ведущие колёса
        # колея и формула/ведущие колёса
    ax = det("axles"); rg = det("runningGear")
    parts = []
    for a in (ax.get("vehicleAxleDetails") or []):
        m = (a.get("axleTrackMeasure") or a.get("axleSweptPathMeasure")
             or a.get("frontAxleTrackMeasure") or a.get("rearAxleTrackMeasure"))
        if m is not None:
            label = f"{m} мм"
            if a.get("drivingAxleIndicator") == 1:
                label += " (ведущая)"
            parts.append(label)
    if parts:
        data["Колея передних/задних колес, мм"] = " / ".join(parts)


    if isinstance(rg, list) and rg:
        g = rg[0] or {}
        formula = g.get("vehicleWheelFormulaName")
        drive   = ((g.get("poweredWheelLocations") or [{}])[0] or {}).get("wheelLocationName")
        if formula or drive:
            data["Колесная формула/ведущие колеса"] = ", ".join(filter(None, [formula, drive]))

        axq = g.get("vehicleAxleQuantity"); whq = g.get("vehicleWheelQuantity")
        if axq and whq:
            data["Количество осей/колес (для категории О)"] = f"{axq} / {whq}"

    # кузов
    bw = det("bodywork")
    if isinstance(bw, list) and bw:
        b0 = bw[0] or {}
        tp = b0.get("vehicleBodyWorkTypeName"); dr = b0.get("doorQuantity")
        if tp or dr:
            data["Тип кузова/количество дверей (для категории М1)"] = f"{tp or ''} / {dr or ''}".strip(' /')

    # подвеска
    susp = det("suspension")
    for s in (susp.get("vehicleSuspensionDetails") or []):
        kind = (s.get("vehicleSuspensionKindName") or "").lower()
        desc = s.get("vehicleSuspensionDescription")
        if not desc: continue
        if "1" in kind or "передн" in kind: key = "передняя"
        elif any(x in kind for x in ["2", "3", "4", "задн"]): key = "задняя"
        else: continue
        line = f"{s.get('vehicleSuspensionKindName')}: {desc}"
        data["Подвеска(тип)"][key] = (data["Подвеска(тип)"].get(key) + "; " if data["Подвеска(тип)"].get(key) else "") + line

    # рулевое
    stg = det("steering")
    if stg.get("vehicleSteeringDescriptions"):
        data["Рулевое управление (марка, тип)"] = (stg["vehicleSteeringDescriptions"][0] or {}).get("description")

    # тормоза
    br = det("brakes")
    for b in (br.get("vehicleBrakingSystemDetails") or []):
        kind = (b.get("vehicleBrakingSystemKindName") or "").lower()
        target = None
        if "рабоч" in kind:   target = "рабочая"
        elif "запасн" in kind: target = "запасная"
        elif "стояноч" in kind: target = "стояночная"
        if target:
            data["Тормозные системы (тип)"][target] = b.get("vehicleBrakingSystemDescription")

    # шины
    ty = det("tyres")
    sizes = [ (t or {}).get("vehicleTyreKindSize") for t in (ty.get("vehicleTyreKindInfos") or []) ]
    sizes = [s.strip() for s in sizes if s]
    if sizes: data["Шины"] = ";\n".join(sizes)

    # трансмиссия / редукторы / КПП
    tr = det("transmission")
    vt = (tr.get("vehicleTransmissionTypes") or [])
    if vt:
        t0 = vt[0] or {}
        data["Трансмиссия"] = t0.get("transTypeName")
        reducers, gearboxes = [], []
        for unit in (t0.get("transmissionUnitDetails") or []):
            kind = (unit.get("unitKindName") or "").lower()
            desc = (unit.get("transmissionUnitMakeName") or "").strip()
            box  = (unit.get("transmissionBoxTypeName") or "").strip()
            if "редуктор" in kind:
                reducers.append(desc or "Редуктор")
            elif "коробка" in kind:
                gearboxes.append(desc or box)
        if reducers:  data["Редуктор"] = ";\n".join([r for r in reducers if r])
        if gearboxes: data["Коробка передач (марка, тип)"] = ";\n".join([g for g in gearboxes if g])

    # сцепление
    cl = det("clutch")
    vcd = cl.get("vehicleClutchDetails") or []
    if vcd:
        data["Сцепление (марка, тип)"] = (vcd[0] or {}).get("vehicleClutchDescription")

    # доп. оборудование
    ex = det("extras")
    if ex.get("vehicleEquipmentInfos"):
        data["Дополнительное оборудование транспортного средства"] = (ex["vehicleEquipmentInfos"][0] or {}).get("vehicleEquipmentText")

    # вернуть только непустые значения
    # (вкладыши оставим, если внутри хоть что-то заполнилось)
    def _empty(v):
        return v in (None, "", []) or (isinstance(v, dict) and all(x in (None, "", []) for x in v.values()))
    return {k: v for k, v in data.items() if not _empty(v)}

def parse_vehicle_data_from_url(url: str):
    doc_id = extract_doc_id(url)
    if not doc_id:
        return {"error": "Invalid URL or missing doc_id."}

    data = copy.deepcopy(FIELDS_TEMPLATE)
    # Обнуляем вложенные поля (иначе copy() делает неглубокую копию)
    data["Габаритные размеры, мм"] = {"длина": None, "ширина": None, "высота": None}
    data["Подвеска(тип)"] = {"передняя": None, "задняя": None}
    data["Тормозные системы (тип)"] = {"рабочая": None, "запасная": None, "стояночная": None}
    base = get_json("get", doc_id)
    if not base:
        print("❌ Ошибка: основной документ не найден. Проверь токен, ссылку или ID.")
        return {"error": "Ошибка загрузки данных с сайта."}

      # --- Универсальный блок заявителя ---
        # --- Универсальный блок заявителя ---
    data["Номер документа"] = base.get("docNumber")
    private_person_id = base.get("applicantPPId")   # для физлица
    organization_id = base.get("organizationId")    # основной заявитель-организация
    applicant_id = base.get("applicantId")          # заявитель по справочнику (основной случай)
    applicant_str = None
    private_person_id = base.get("applicantPPId")
    organization_id = base.get("organizationId")
    applicant_id = base.get("applicantId")

    if base.get("applicantName"):
        applicant_str = base.get("applicantName")
    elif private_person_id:
        # без сетевых запросов: ставим понятный маркер
        applicant_str = f"[физ.лицо id={private_person_id}]"
    elif organization_id:
        applicant_str = get_org_name_and_address(organization_id) or f"[Организация id={organization_id}]"
    elif applicant_id:
        applicant_str = get_org_name_and_address(applicant_id) or f"[Организация id={applicant_id}]"
    else:
        applicant_str = "Заявитель не определён"

    data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = applicant_str

    token, cookies = load_auth_from_cache()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    if private_person_id:
    # Физлицо — оставляем как есть
        try:
            person_url = f"https://pts.gov.kz/api/PrivatePerson/getPersonById/{private_person_id}"
            resp = requests.get(person_url, headers=headers, cookies=cookies, verify=False, timeout=10)
            person = resp.json().get("data", {})
            fio = " ".join(str(person.get(k, "")) for k in ["surName", "nameOfPerson", "patronymic"]).strip()
            iin = person.get("iin", "")
            applicant_str = f"{fio} (ИИН: {iin}) [физ.лицо]"
        except Exception as e:
            print(f"❌ Не удалось получить ФИО заявителя: {e}")
            applicant_str = f"[Физлицо, id={private_person_id}]"
    elif organization_id:
        applicant_str = get_org_name_and_address(organization_id)
    elif applicant_id:
        applicant_str = get_org_name_and_address(applicant_id)
    elif base.get("applicantName"):
        applicant_str = base.get("applicantName")
    else:
        applicant_str = "Заявитель не определён"

    data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = applicant_str

    vtype = base.get("vehicleTypeDetail", {})
    chars = vtype.get("characteristicsDetail", {})

    # === Тип двигателя ===
    # === Тип двигателя по engineTypeId ===
    # === Тип двигателя по engineTypeId ===
    engine_type_map = {
        5767: "Двигатель внутреннего сгорания",
        5768: "Электрический двигатель",
        5897: "Гибридное транспортное средство"
    }

    engine_type_id = chars.get("engineTypeId")  # <-- ВОТ ТУТ ЗАМЕНИТЬ
    data["Двигатель"] = engine_type_map.get(engine_type_id)

        # Описание гибридного привода
    hybrid_text = (chars.get("vehicleHybridDesignText") or "").strip()

    if hybrid_text:
        data["Описание гибридного привода"] = hybrid_text
    else:
        arr = chars.get("vehicleHybridDesigns")
        if isinstance(arr, list) and arr:
            # Берём только непустые тексты и убираем дубли
            seen = set()
            texts = []
            for item in arr:
                t = (item.get("vehicleHybridDesignText") or "").strip()
                if t and t not in seen:
                    seen.add(t)
                    texts.append(t)
            if texts:
                data["Описание гибридного привода"] = ";\n".join(texts)


    data["МАРКА"] = (vtype.get("makes") or [{}])[0].get("dicName")
    data["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] = (vtype.get("commercialNames") or [{}])[0].get("commercialName")
    data["ТИП"] = (vtype.get("types") or [{}])[0].get("typeValue")
    data["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = (base.get("vinNumbers") or [{}])[0].get("number")
    data["ГОД ВЫПУСКА"] = vtype.get("yearIssue")
    data["КАТЕГОРИЯ"] = (vtype.get("techCategories") or [{}])[0].get("dicName")
    data["ЭКОЛОГИЧЕСКИЙ КЛАСС"] = (vtype.get("ecoClasses") or [{}])[0].get("dicName")
    data["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = base.get("authorityName")
    # Попробуем определить ИЗГОТОВИТЕЛЯ по fallback
    manufacturer = base.get("manufacturerName")
    if not manufacturer:
        plants = base.get("assemblyPlants") or []
        if plants:
            manufacturer = plants[0].get("organization")

    data["ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС"] = manufacturer
    data["СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС"] = (base.get("assemblyPlants") or [{}])[0].get("organization")
    if base.get("docDate"):
        data["Дата оформления"] = base["docDate"].split("T")[0]

    char_id = chars.get("id")
    if char_id:

        # === Электромашины ===
        machines = get_json("GetElectricalMachineDetailsByDocId", doc_id)
        em_list = machines.get("electricalMachineDetails", []) if machines else []

        if em_list:
            if len(em_list) == 1:
                # 👉 Один электродвигатель
                m = em_list[0]
                mark = m.get("vehicleComponentMakeName", "")
                desc = m.get("vehicleComponentText", "")
                full_name = f"{mark},{desc}".strip(", ")

                data["Электродвигатель электромобиля"] = full_name
                data["Рабочее напряжение, В"] = str(m.get("electricalMachineVoltageMeasure", ""))
                data["Максимальная 30-минутная мощность, кВт"] = str(m.get("electricMotorPowerMeasure", ""))

                # 👉 А эти оставляем пустыми
                data["Электромашина (марка, тип)"] = None
                data["Вид электромашины"] = None
                data["Рабочее напряжение, В (электромашина)"] = None
                data["Максимальная 30-минутная мощность, кВт (электромашина)"] = None

            else:
                # 👉 Два и более электродвигателей (как сейчас)
                marks_types = []
                kinds = []
                voltages = []
                powers = []

                for m in em_list:
                    mark = m.get("vehicleComponentMakeName", "")
                    desc = m.get("vehicleComponentText", "")
                    full_name = f"{mark},{desc}".strip(", ")
                    marks_types.append(full_name)
                    kinds.append(m.get("electricalMachineKindName", ""))
                    voltages.append(str(m.get("electricalMachineVoltageMeasure", "")))
                    powers.append(str(m.get("electricMotorPowerMeasure", "")))

                data["Электромашина (марка, тип)"] = ";\n".join(marks_types)
                data["Вид электромашины"] = ";\n".join(kinds)
                data["Рабочее напряжение, В (электромашина)"] = ";\n".join(voltages)
                data["Максимальная 30-минутная мощность, кВт (электромашина)"] = ";\n".join(powers)

                # 👉 А эти оставляем пустыми
                data["Электродвигатель электромобиля"] = None
                data["Рабочее напряжение, В"] = None
                data["Максимальная 30-минутная мощность, кВт"] = None

        else:
            print("⚠️ Электромашина отсутствует.")

        # === Устройство накопления энергии ===
        storage = get_json("getPowerStorageDeviceDetailsByDocId", doc_id)
        storage_list = storage.get("powerStorageDeviceDetails", []) if storage else []

        if storage_list:
            storage_items = []
            for s in storage_list:
                kind = s.get("powerStorageDeviceTypeName", "")
                desc = s.get("powerStorageDeviceDescription", "")
                full = kind if not desc or desc == "-" else f"{kind} ({desc})"
                storage_items.append(full)
            data["Устройство накопления энергии"] = ";\n".join(storage_items)
        else:
            print("⚠️ Устройство накопления энергии отсутствует.")


        layout_details = get_json("GetVehicleLayoutDetailsByDocId", doc_id)
        if layout_details:
            if layout_details.get("vehicleCarriageSpaceImplementations"):
                data["Исполнение загрузочного пространства (для категории N)"] = \
                    layout_details["vehicleCarriageSpaceImplementations"][0].get("carriageSpaceImplementation")
            if layout_details.get("vehicleCabins"):
                data["Кабина (для категории N)"] = \
                    layout_details["vehicleCabins"][0].get("cabinDescription")

                # 🆕 ПАССАЖИРОВМЕСТИМОСТЬ
            if layout_details.get("vehiclePassengerQuantities"):
                passenger_info = layout_details["vehiclePassengerQuantities"][0]
                quantity = passenger_info.get("passengerQuantity")
                if quantity:
                    data["Пассажировместимость (для категорий М2, М3)"] = quantity
                else:
                    print("⚠️ Пассажировместимость указана, но нет значения.")
            else:
                print("⚠️ Пассажировместимость отсутствует.")


        # === Рама (для мотоциклов категории L) ===
        frames = get_json("GetVehicleLayoutDetailsByDocId", doc_id)
        if frames and frames.get("vehicleFrames"):
            frame_text = frames["vehicleFrames"][0].get("frameText")
            if frame_text:
                data["Рама (для категории L)"] = frame_text
                print(f"✅ Найдена рама: {frame_text}")
        else:
            print("⚠️ Нет данных о раме (vehicleFrames пустой).")


        # === Сцепление ===
        clutch = get_json("GetVehicleClutchDetailsByDocId", doc_id)
        if clutch and clutch.get("vehicleClutchDetails"):
            data["Сцепление (марка, тип)"] = clutch["vehicleClutchDetails"][0].get("vehicleClutchDescription")
        else:
            print("⚠️ Нет данных по сцеплению.")


        # === Блок ТРАНСМИССИИ с поддержкой нескольких редукторов ===
        transmission = get_json("GetTransmissionTypesByDocId", doc_id)
        if transmission and transmission.get("vehicleTransmissionTypes"):
            t = transmission["vehicleTransmissionTypes"][0]
            data["Трансмиссия"] = t.get("transTypeName")

            # Новый блок: обработка редукторов и коробок
            if t.get("transmissionUnitDetails"):
                reducers = []  # список для всех редукторов
                gearboxes = []  # список для всех коробок передач

                for unit in t["transmissionUnitDetails"]:
                    kind = (unit.get("unitKindName") or "").lower()
                    desc = (unit.get("transmissionUnitMakeName") or "").strip()
                    box_type = (unit.get("transmissionBoxTypeName") or "").strip()

                    if "редуктор" in kind:
                        # если описание есть — берём его, иначе просто слово "Редуктор"
                        reducers.append(desc if desc else "Редуктор")

                    elif "коробка" in kind:
                        # если коробка передач
                        if desc:
                            gearboxes.append(desc)
                        elif box_type:
                            gearboxes.append(box_type)

                # сохраняем результаты
                if reducers:
                    data["Редуктор"] = ";\n".join(reducers)
                if gearboxes:
                    data["Коробка передач (марка, тип)"] = ";\n".join(gearboxes)
        else:
            print("⚠️ Нет данных по трансмиссии.")

        def safe_get(endpoint, key, subkey=None, index=0):
            res = get_json(endpoint, doc_id)
            val = res.get(key, [])
            if val and len(val) > index:
                return val[index].get(subkey) if subkey else val[index]
            return None

        # === ВСТАВЛЯЕМ БЛОК seats ЗДЕСЬ ===
        # === БЛОК СИДЕНИЙ (правильный) ===
  # === БЛОК СИДЕНИЙ (обновленный для списка рядов) ===
        seats = get_json("GetVehicleSeatDetailsByDocId", doc_id)
        if isinstance(seats, list) and seats:
            seat_info = seats[0]
            total_seats = seat_info.get("seatQuantity")
            description = (seat_info.get("seatDescription") or "").strip()

            if total_seats:
                data["Количество мест для сидения (для категорий М2, M3, L)"] = total_seats

            raw_details = seat_info.get("vehicleSeatRawDetails", [])
            row_list = []

            for seat in raw_details:
                ordinal = seat.get("seatRawOrdinal")
                quantity = seat.get("seatRawQuantity")
                if ordinal is not None and quantity is not None:
                    row_list.append(f"{ordinal}-{quantity}")

            # Формируем красивое представление
            final_parts = []
            if total_seats:
                final_parts.append(f"Количество мест для сидения: {total_seats}")
            if description:
                final_parts.append(f"Описание мест для сидения: {description}")
            if row_list:
                final_parts.append("Количество мест спереди/сзади:\n" + "\n".join(row_list))

            # Собираем всё в одну строку
            data["Количество мест спереди/ cзади (для категории М1)"] = "\n".join(final_parts)
        else:
            print("⚠️ Нет данных о сиденьях.")
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             


        # 👇 Далее идёт engine, layout, suspension и т.д.


        engine = get_json("GetEngineDetailsByDocId", doc_id)
        if engine and engine.get("engineDetails"):
            e = engine["engineDetails"][0]
            data["Двигатель внутреннего сгорания (марка, тип)"] = f"{e.get('vehicleComponentMakeName', '')}, {e.get('vehicleComponentText', '')}".strip(', ')
            data["- количество и расположение цилиндров"] = f"{e.get('engineCylinderQuantity')} {e.get('engineCylinderArrangementName')}"
            data["- рабочий объем цилиндров, см3"] = e.get("engineCapacityMeasure")
            data["- степень сжатия"] = e.get("engineCompressionRate")
            if e.get("enginePowerDetails"):
                p = e["enginePowerDetails"][0]
                data["- максимальная мощность, кВт (мин.-1)"] = f"{p.get('engineMaxPowerMeasure')} @ {p.get('engineMaxPowerShaftRotationFrequencyMinMeasure')}"
            if e.get("vehicleFuelKinds"):
                data["Топливо"] = e["vehicleFuelKinds"][0].get("fuelKindName")
            if e.get("engineFuelFeedDetails"):
                data["Система питания (тип)"] = e["engineFuelFeedDetails"][0].get("fuelFeedName")
            if e.get("vehicleIgnitionDetails"):
                data["Система зажигания (тип)"] = e["vehicleIgnitionDetails"][0].get("vehicleIgnitionTypeName")
            if e.get("exhaustDetails"):
                data["Система выпуска и нейтрализации отработавших газов"] = e["exhaustDetails"][0].get("exhaustDescription")
        else:
            print("⚠️ Нет данных по двигателю.")


        # Получаем данные по весу транспортного средства
        weight =get_json("GetVehicleWeightDetailsByDocId", doc_id)

        if weight is None:
            print("❌ Ошибка получения данных с GetVehicleWeightDetailsByDocId")
        elif "vehicleWeightMeasures" not in weight:
            print("⚠️ Нет vehicleWeightMeasures в ответе.")
        else:
            for w in weight["vehicleWeightMeasures"]:
                mass_type = w.get("massTypeName", "").lower()
                if "снаряженном" in mass_type:
                    data["Масса транспортного средства в снаряженном состоянии, кг"] = w.get("weight")
                    print(f"✅ Масса в снаряженном состоянии: {w.get('weight')}")
                if "максимальная" in mass_type:
                    data["Технически допустимая максимальная масса транспортного средства, кг"] = w.get("weight")
                    print(f"✅ Максимальная масса: {w.get('weight')}")


        dimensions = get_json("GetVehicleDimensionDetailsByDocId", doc_id)
        if dimensions and dimensions.get("lengthRanges"):
            data["Габаритные размеры, мм"]["длина"] = dimensions["lengthRanges"][0].get("length")
        if dimensions and dimensions.get("widthRanges"):
            data["Габаритные размеры, мм"]["ширина"] = dimensions["widthRanges"][0].get("width")

        height = get_json("GetVehicleHightDetailsByDocId", doc_id)
        if height:
            if height.get("heightRanges"):
                data["Габаритные размеры, мм"]["высота"] = (height["heightRanges"][0] or {}).get("height")
            elif height.get("hightRanges"):
                data["Габаритные размеры, мм"]["высота"] = (height["hightRanges"][0] or {}).get("height")


        wheelbase = get_json("GetWheelbaseMeasuresByDocId", doc_id)
        if wheelbase and wheelbase.get("wheelbaseMeasureRanges"):
            values = [str(i.get("wheelbase")) for i in wheelbase["wheelbaseMeasureRanges"] if i.get("wheelbase")]
            data["База, мм"] = " / ".join(values)



        # === Колея передних/задних колес, мм ===
        axle_details = get_json("GetVehicleAxleDetailsByDocId", doc_id)
        seat_details = get_json("GetVehicleSeatDetailsByDocId", doc_id)

        parts = []

        # Проверяем категорию (мотоцикл или нет)
        is_motorcycle = (data.get("КАТЕГОРИЯ") or "").startswith("L")

        if is_motorcycle:
            # Для мотоциклов
            if isinstance(seat_details, list) and seat_details:
                seat_info = seat_details[0]
                raws = seat_info.get("vehicleSeatRawDetails", [])

                # Ищем ведущую ось
                leading_axle = None
                if axle_details and axle_details.get("vehicleAxleDetails"):
                    for axle in axle_details["vehicleAxleDetails"]:
                        if axle.get("drivingAxleIndicator") == 1:
                            leading_axle = axle.get("axleOrdinal")

                for raw in raws:
                    ordinal = raw.get("seatRawOrdinal")
                    if ordinal is not None:
                        label = f"Ось {ordinal}"
                        if ordinal == leading_axle:
                            label += " (ведущая)"
                        parts.append(label)
        else:
            # Для машин — пробуем все известные поля колеи
            if axle_details and axle_details.get("vehicleAxleDetails"):
                for a in axle_details["vehicleAxleDetails"]:
                    measure = (a.get("axleTrackMeasure") or a.get("axleSweptPathMeasure")
                               or a.get("frontAxleTrackMeasure") or a.get("rearAxleTrackMeasure"))
                    if measure is not None:
                        label = f"{measure} мм"
                        if a.get("drivingAxleIndicator") == 1:
                            label += " (ведущая)"
                        parts.append(label)


        if parts:
            data["Колея передних/задних колес, мм"] = " / ".join(parts)
        else:
            print("⚠️ Нет данных для колеи передних/задних колес.")




        layout = get_json("GetVehicleLayoutsByDocId", doc_id)
        if layout and layout.get("vehicleLayoutPatterns"):
            data["Схема компоновки транспортного средства"] = layout["vehicleLayoutPatterns"][0].get("layoutPatternName")


        suspension = get_json("GetVehicleSuspensionDetailsByDocId", doc_id)
        if suspension and suspension.get("vehicleSuspensionDetails"):
            for s in suspension["vehicleSuspensionDetails"]:
                kind = s.get("vehicleSuspensionKindName", "").lower()
                desc = s.get("vehicleSuspensionDescription")
                if not desc:
                    continue

                # Определяем передняя/задняя
                if "1" in kind or "передн" in kind:
                    key = "передняя"
                elif any(x in kind for x in ["2", "3", "4", "задн"]):
                    key = "задняя"
                else:
                    continue

                # Добавляем с подписью оси
                line = f"{s.get('vehicleSuspensionKindName')}: {desc}"

                if data["Подвеска(тип)"].get(key):
                    data["Подвеска(тип)"][key] += "; " + line
                else:
                    data["Подвеска(тип)"][key] = line
        else:
            print("⚠️ Нет данных по подвеске.")



        running_gear = get_json("GetVehicleRunningGearDetailsByDocId", doc_id)
        if running_gear:
            if isinstance(running_gear, list) and running_gear:
                g = running_gear[0] or {}
            elif isinstance(running_gear, dict):
                g = running_gear
            else:
                g = {}

            formula = g.get("vehicleWheelFormulaName")
            drive   = ((g.get("poweredWheelLocations") or [{}])[0] or {}).get("wheelLocationName")
            if formula or drive:
                data["Колесная формула/ведущие колеса"] = f"{formula or ''}, {drive or ''}".strip(', ')

            axq = g.get("vehicleAxleQuantity"); whq = g.get("vehicleWheelQuantity")
            if axq and whq:
                data["Количество осей/колес (для категории О)"] = f"{axq} / {whq}"
        else:
            print("⚠️ Нет данных по ходовой части (running gear).")



        bodywork = get_json("GetVehicleBodyworkDetailsByDocId", doc_id)
        if bodywork:
            bw = bodywork[0]
            bw_type = bw.get("vehicleBodyWorkTypeName")
            doors = bw.get("doorQuantity")
            if bw_type or doors:
                data["Тип кузова/количество дверей (для категории М1)"] = f"{bw_type or ''} / {doors or ''}".strip(' /')


        steering = get_json("GetVehicleSteeringDetailsByDocId", doc_id)
        if steering and steering.get("vehicleSteeringDescriptions"):
            data["Рулевое управление (марка, тип)"] = steering["vehicleSteeringDescriptions"][0].get("description")


        brakes = get_json("GetVehicleBrakingSystemDetailsByDocId", doc_id)
        if brakes:
            for b in brakes.get("vehicleBrakingSystemDetails", []):
                kind = (b.get("vehicleBrakingSystemKindName") or "").lower()
                target = None
                if "рабоч" in kind:   target = "рабочая"
                elif "запасн" in kind: target = "запасная"
                elif "стояноч" in kind: target = "стояночная"
                if target:
                    data["Тормозные системы (тип)"][target] = b.get("vehicleBrakingSystemDescription")

            # === Шины ===
        tyres = get_json("GetVehicleTyreKindInfosByDocId", doc_id)
        if tyres and tyres.get("vehicleTyreKindInfos"):
            tyre_list = tyres["vehicleTyreKindInfos"]
            sizes = []
            for tyre in tyre_list:
                size = tyre.get("vehicleTyreKindSize")
                if size:
                    sizes.append(size.strip())

            if sizes:
                data["Шины"] = ";\n".join(sizes)  # Разделить шины через ; и перенос строки
            else:
                print("⚠️ Размеры шин отсутствуют.")
        else:
            print("⚠️ Нет данных по шинам.")

        extras = get_json("GetVehicleEquipmentInfosByDocId", doc_id)
        if extras and extras.get("vehicleEquipmentInfos"):
            data["Дополнительное оборудование транспортного средства"] = extras["vehicleEquipmentInfos"][0].get("vehicleEquipmentText")

    return data


def check_violation_point5(data: dict) -> dict:
    is_category_O = (str(data.get("КАТЕГОРИЯ", "")).strip().upper().startswith("O"))

    applicant = data.get("ЗАЯВИТЕЛЬ И ЕГО АДРЕС", "") or ""
    is_individual = "физ.лицо" in applicant.lower()

    try:
        mass = float(str(data.get("Технически допустимая максимальная масса транспортного средства, кг") or "0").replace(",", ".").replace(" ", ""))
    except Exception:
        mass = 0.0
    is_over_3500 = mass > 3500

    description_fields = [
        data.get("ТИП", ""),
        data.get("КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ", ""),
        data.get("Тип кузова/количество дверей (для категории М1)", ""),
        data.get("Дополнительное оборудование транспортного средства", ""),
    ]
    description = " ".join(map(lambda x: str(x or ""), description_fields)).lower()

    is_exception = (
        ("перевозк" in description and "автомоб" in description) or
        ("дом" in description and "прицеп" in description) or
        ("автоприцеп" in description and ("жиль" in description or "турист" in description))
    )

    result = {
        "is_category_O": is_category_O,
        "is_individual": is_individual,
        "is_over_3500": is_over_3500,
        "is_exception": is_exception,
        "violation": False,
        "explanation": ""
    }

    if is_category_O and is_individual and is_over_3500 and not is_exception:
        result["violation"] = True
        result["explanation"] = (
            "Нарушение пункта 5: Категория O, заявитель физ.лицо, масса > 3500 кг, не подпадает под исключения."
        )
    else:
        if not is_category_O:
            reason = "Не категория O."
        elif not is_individual:
            reason = "Заявитель не физ.лицо."
        elif not is_over_3500:
            reason = "Масса не превышает 3500 кг."
        elif is_exception:
            reason = "Подпадает под исключения."
        else:
            reason = "Не нарушение по иным причинам."
        result["explanation"] = reason

    return result


# === ПРИМЕР ИСПОЛЬЗОВАНИЯ ===

if __name__ == "__main__":
    # Проверяем токен перед стартом!
    token, cookies = load_auth_from_cache()
    if not token or not validate_token(token, cookies):
        print("🔁 Токен устарел или отсутствует. Авторизация через браузер...")
        token, cookies = get_token_and_cookies_via_selenium()
        save_auth_to_cache(token, cookies)
    else:
        print("🔒 Используем сохранённый токен.")

    input_url = input("Вставь ссылку на страницу ТС: ").strip()
    result = parse_vehicle_data_from_url(input_url)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    output_dir = "test"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "site_data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Результаты сохранены в файл: {output_path}")