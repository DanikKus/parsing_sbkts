import requests
import re
from datetime import datetime
import urllib3
import os
from auth_token_selenium import get_token_and_cookies_via_selenium, load_auth_from_cache, save_auth_to_cache
import copy

def validate_token(token, cookies):
    url = "https://pts.gov.kz/api/compliencedocument/get?id=00000000-0000-0000-0000-000000000000"  # заведомо пустой doc_id
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


def get_json(endpoint: str, doc_id: str, label: str = ""):
    # <-- Новое: ВСЕГДА ЧИТАЕМ АКТУАЛЬНЫЕ token и cookies из кэша
    token, cookies = load_auth_from_cache()
    if not token:
        print("❌ Нет токена! Сначала пройди авторизацию.")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://pts.gov.kz/",
        "X-Requested-With": "XMLHttpRequest"
    }
    url = f"https://pts.gov.kz/api/compliencedocument/{endpoint}?id={doc_id}"

    try:
        print(f"➡️ GET {url} с токеном: Bearer {token[:20]}...")
        response = requests.get(url, headers=headers, cookies=cookies, verify=False)
        response.raise_for_status()
        data = response.json().get("data", None)

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

    data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = base.get("applicantName")
        # Заявитель и его адрес
    if base.get("applicantName"):
        data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = base["applicantName"]
    elif base.get("organizationName"):
        data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = base["organizationName"]
    else:
        data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = None

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
        # 🆕 Гибридные установки
    hybrid_info = chars.get("vehicleHybridDesigns")
    if hybrid_info and isinstance(hybrid_info, list) and hybrid_info[0].get("vehicleHybridDesignText"):
        data["Описание гибридного привода"] = hybrid_info[0]["vehicleHybridDesignText"]



    data["МАРКА"] = (vtype.get("makes") or [{}])[0].get("dicName")
    data["КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ"] = (vtype.get("commercialNames") or [{}])[0].get("commercialName")
    data["ТИП"] = (vtype.get("types") or [{}])[0].get("typeValue")
    data["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)"] = (base.get("vinNumbers") or [{}])[0].get("number")
    data["ГОД ВЫПУСКА"] = vtype.get("yearIssue")
    data["КАТЕГОРИЯ"] = (vtype.get("techCategories") or [{}])[0].get("dicName")
    data["ЭКОЛОГИЧЕСКИЙ КЛАСС"] = (vtype.get("ecoClasses") or [{}])[0].get("dicName")
    data["ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ"] = base.get("authorityName")
    data["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] = None  # пока не найден правильный источник
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
        if dimensions.get("lengthRanges"):
            data["Габаритные размеры, мм"]["длина"] = dimensions["lengthRanges"][0].get("length")
        if dimensions.get("widthRanges"):
            data["Габаритные размеры, мм"]["ширина"] = dimensions["widthRanges"][0].get("width")
        height = get_json("GetVehicleHightDetailsByDocId", doc_id)
        if height.get("heightRanges"):
            data["Габаритные размеры, мм"]["высота"] = height["heightRanges"][0].get("height")

        wheelbase = get_json("GetWheelbaseMeasuresByDocId", doc_id)
        if wheelbase.get("wheelbaseMeasureRanges"):
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
            # Для машин
            if axle_details and axle_details.get("vehicleAxleDetails"):
                for a in axle_details["vehicleAxleDetails"]:
                    measure = a.get("axleSweptPathMeasure")
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
            gear = running_gear[0]  # Берем первый элемент
            formula = gear.get("vehicleWheelFormulaName")
            drive = (gear.get("poweredWheelLocations") or [{}])[0].get("wheelLocationName")
            if formula or drive:
                data["Колесная формула/ведущие колеса"] = f"{formula or ''}, {drive or ''}".strip(', ')

            # Новое: Количество осей и колёс для грузовиков (если есть)
            axle_qty = gear.get("vehicleAxleQuantity")
            wheel_qty = gear.get("vehicleWheelQuantity")
            if axle_qty and wheel_qty:
                data["Количество осей/колес (для категории О)"] = f"{axle_qty} / {wheel_qty}"
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
        if steering.get("vehicleSteeringDescriptions"):
            data["Рулевое управление (марка, тип)"] = steering["vehicleSteeringDescriptions"][0].get("description")

        brakes = get_json("GetVehicleBrakingSystemDetailsByDocId", doc_id)
        for b in brakes.get("vehicleBrakingSystemDetails", []):
            kind = b.get("vehicleBrakingSystemKindName", "").lower()
            if kind in data["Тормозные системы (тип)"]:
                data["Тормозные системы (тип)"][kind] = b.get("vehicleBrakingSystemDescription")

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
        if extras.get("vehicleEquipmentInfos"):
            data["Дополнительное оборудование транспортного средства"] = extras["vehicleEquipmentInfos"][0].get("vehicleEquipmentText")

    return data

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

    import json
    input_url = input("Вставь ссылку на страницу ТС: ").strip()
    result = parse_vehicle_data_from_url(input_url)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    output_dir = "test"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "site_data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Результаты сохранены в файл: {output_path}")