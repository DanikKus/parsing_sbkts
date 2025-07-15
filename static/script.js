let siteData = null;
let pdfData = null;
let errorFields = {};

function fetchFromSite() {
  const url = document.getElementById("siteUrl").value.trim();
  if (!url) return;

  document.getElementById("status").innerText = "⏳ Загружаем данные с сайта...";

  fetch("/parse_site", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url })
  })
    .then(res => res.json())
        .then(data => {
      // data.fields — твои поля, data.violation_point5 — результат проверки
      siteData = data.fields;
      document.getElementById("status").innerText = "✅ Данные с сайта загружены.";
      compareData();
    })

    .catch(err => {
      document.getElementById("status").innerText = "❌ Ошибка при получении данных с сайта.";
    });
}

function isPhysicalPerson(applicant) {
  if (!applicant) return false;
  applicant = applicant.toLowerCase();

  // Явно указано физ лицо
  if (
    applicant.includes("физ.лицо") ||
    applicant.includes("физ лицо") ||
    applicant.includes("[физ") // на всякий случай
  ) return true;

  // Слова/аббревиатуры для юр.лиц (дополняй по необходимости!)
  const orgWords = [
    "тоо", "ип", "ооо", "зао", "пао", "ао", "бин", "компания", "фирма",
    "organization", "company", "corp", "corporation", "inc",
    "товарищество с ограниченной ответственностью",
    "общество с ограниченной ответственностью"
  ];
  for (const word of orgWords) {
    if (applicant.includes(word)) return false; // юр.лицо
  }

  return true; // не найдено ничего из списка, считаем физлицом
}


function checkViolationPoint4(fields) {
  // Категория ТС
  const category = (fields["КАТЕГОРИЯ"] || "").toUpperCase();
  // Заявитель
  const applicant = (fields["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] || "").toUpperCase();
  // Масса
  let maxWeight = fields["Технически допустимая максимальная масса транспортного средства, кг"] || "";
  // Преобразуем массу в число (убираем пробелы, символы)
  maxWeight = parseFloat((maxWeight + "").replace(/[^\d.,]/g, "").replace(",", "."));
  // Исключения
  const extraInfo = (fields["ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ"] || "").toLowerCase();

  // Проверка на категорию N
  if (!category.includes("N")) return null;
  // Проверка на физическое лицо
  const isPerson = isPhysicalPerson(applicant);
  if (!isPerson) return null;
  // Проверка массы
  if (!(maxWeight > 5000)) return null;
  // Проверка исключения
  if (extraInfo.includes("радиоактив") || extraInfo.includes("высокорадиоактив")) return null;

  // Если все условия выполнены — нарушение
  return {
    violation: true,
    explanation: "❌ Нарушение пункта 4 Перечня: Категория N, заявитель физлицо, масса более 5 тонн."
  };
}

function checkViolationPoint5(fields) {
  // 1. Категория ТС
  const category = (fields["КАТЕГОРИЯ"] || "").toUpperCase();

  // 2. Заявитель
  const applicant = (fields["ЗАЯВИТЕЛЬ И ЕГО АДРЕС"] || "");

  // 3. Масса
  let maxWeight = fields["Технически допустимая максимальная масса транспортного средства, кг"] || "";
  maxWeight = parseFloat((maxWeight + "").replace(/[^\d.,]/g, "").replace(",", "."));

  // 4. Исключения
  const extraInfo = (fields["ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ"] || "").toLowerCase();
  const exceptionWords = [
    "прицеп для перевозки автомобилей",
    "дом-автоприцеп",
    "дом автоприцеп",
    "дом-прицеп",
    "дом прицеп",
    "прицеп для проживания",
    "прицеп для автотуристов"
  ];
  const hasException = exceptionWords.some(word => extraInfo.includes(word));

  // Условие — если категория не "O" — не рассматриваем
  if (!category.includes("O")) return null;
  // Условие — не физ лицо
  if (!isPhysicalPerson(applicant)) return null;
  // Условие — масса <= 3500 кг
  if (!(maxWeight > 3500)) return null;
  // Исключение
  if (hasException) return null;

  // Нарушение!
  return {
    violation: true,
    explanation: "❌ Нарушение пункта 5 Перечня: Категория O, заявитель физлицо, масса более 3,5 тонн (без исключений)."
  };
}


function fetchFromPDF() {
  const url = document.getElementById("pdfUrl").value.trim();
  if (!url) return;

  document.getElementById("status").innerText = "⏳ Загружаем PDF и извлекаем данные...";

  fetch("/parse_pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url })
  })
    .then(res => res.json())
    .then(data => {
      pdfData = data;
      document.getElementById("status").innerText = "✅ Данные из PDF загружены.";
      compareData();
    })
    .catch(err => {
      document.getElementById("status").innerText = "❌ Ошибка при обработке PDF.";
    });
}

function uploadPDF() {
    const fileInput = document.getElementById("pdfFile");
    const file = fileInput.files[0];
    if (!file) return;
  
    const formData = new FormData();
    formData.append("file", file);
  
    document.getElementById("status").innerText = "⏳ Загружаем и обрабатываем PDF...";
  
    fetch("/parse_pdf_file", {
      method: "POST",
      body: formData
    })
      .then(res => res.json())
      .then(data => {
        pdfData = data;
        document.getElementById("status").innerText = "✅ PDF успешно распознан.";
        compareData();
      })
      .catch(err => {
        document.getElementById("status").innerText = "❌ Ошибка при обработке PDF-файла.";
      });
  }
  
  // Функция для генерации id из названия поля (ключа)
function makeRowId(fieldName) {
  return "row-" + fieldName.replace(/[^a-zA-Z0-9а-яА-Я]+/g, "_");
}


function compareData() {
  if (!siteData || !pdfData) return;

  const tbody = document.getElementById("comparisonBody");
  tbody.innerHTML = "";

  const priorityFields = [
    "ИСПЫТАТЕЛЬНАЯ ЛАБОРАТОРИЯ", "МАРКА", "КОММЕРЧЕСКОЕ НАИМЕНОВАНИЕ", "ТИП", "ШАССИ",
    "ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)", "ГОД ВЫПУСКА", "КАТЕГОРИЯ", "ЭКОЛОГИЧЕСКИЙ КЛАСС",
    "ЗАЯВИТЕЛЬ И ЕГО АДРЕС", "ИЗГОТОВИТЕЛЬ И ЕГО АДРЕС", "СБОРОЧНЫЙ ЗАВОД И ЕГО АДРЕС",
    "Колесная формула/ведущие колеса", "Схема компоновки транспортного средства",
    "Тип кузова/количество дверей (для категории М1)", "Количество мест спереди/ cзади (для категории М1)",
    "Исполнение загрузочного пространства (для категории N)", "Кабина (для категории N)",
    "Пассажировместимость (для категорий М2, М3)", "Общий объем багажных отделений (для категории М3 класса III)",
    "Количество мест для сидения (для категорий М2, M3, L)", "Рама (для категории L)",
    "Количество осей/колес (для категории О)", "Масса транспортного средства в снаряженном состоянии, кг",
    "Технически допустимая максимальная масса транспортного средства, кг",
    "Габаритные размеры, мм", "- длина", "- ширина", "- высота",
    "База, мм", "Колея передних/задних колес, мм",
    "Двигатель",
    "Двигатель внутреннего сгорания (марка, тип)",
    "Описание гибридного транспортного средства", 
    "- количество и расположение цилиндров",
    "- рабочий объем цилиндров, см3", "- степень сжатия", "- максимальная мощность, кВт (мин.-1)",
    "Топливо", "Система питания (тип)", "Система зажигания (тип)", "Система выпуска и нейтрализации отработавших газов",
    "Электродвигатель электромобиля", "Рабочее напряжение, В", "Максимальная 30-минутная мощность, кВт",
    "Вид электромашины", "Электромашина (марка, тип)", "Рабочее напряжение, В (электромашина)",
    "Максимальная 30-минутная мощность, кВт (электромашина)",
    "Устройство накопления энергии", "Сцепление (марка, тип)", "Трансмиссия", "Коробка передач (марка, тип)",
    "Редуктор", "Подвеска(тип)", "- передняя", "- задняя",
    "Рулевое управление (марка, тип)", "Тормозные системы (тип)", "- рабочая", "- запасная", "- стояночная",
    "Шины", "Дополнительное оборудование транспортного средства", "Дата оформления"
  ];

  let mismatchCount = 0;
  errorFields = {}; // Сбрасываем ошибки перед новым сравнением
  
  const v4 = checkViolationPoint4(siteData);
  if (v4 && v4.violation) {
    // Добавляем отдельным пунктом с ключом
    errorFields["Нарушение пункта 4"] = v4.explanation;
  }

  const v5 = checkViolationPoint5(siteData);
  if (v5 && v5.violation) {
    errorFields["Нарушение пункта 5"] = v5.explanation;
  }

  for (const key of priorityFields) {
    let siteVal = siteData[key];
    let pdfVal = pdfData[key];

    // Если поле объект (например, Габаритные размеры, Подвеска, Тормозные системы)
    if (key === "Габаритные размеры, мм" && typeof siteVal === "object") {
      // В основной строке оставляем пусто, или можно написать "см. ниже"
      const rowId = makeRowId(key);
      const row = document.createElement("tr");
      row.id = rowId;
      row.innerHTML = `<td>${key}</td><td colspan="3" style="font-style:italic;">см. ниже</td>`;
      tbody.appendChild(row);
      continue;
    }
    if (key === "Подвеска(тип)" && typeof siteVal === "object") {
      const rowId = makeRowId(key);
      const row = document.createElement("tr");
      row.id = rowId;
      row.innerHTML = `<td>${key}</td><td colspan="3" style="font-style:italic;">см. ниже</td>`;
      tbody.appendChild(row);
      continue;
    }
    if (key === "Тормозные системы (тип)" && typeof siteVal === "object") {
      const rowId = makeRowId(key);
      const row = document.createElement("tr");
      row.id = rowId;
      row.innerHTML = `<td>${key}</td><td colspan="3" style="font-style:italic;">см. ниже</td>`;
      tbody.appendChild(row);
      continue;
    }
    // Подполя для вложенных
    if (key === "- длина" || key === "- ширина" || key === "- высота") {
      siteVal = siteData["Габаритные размеры, мм"]?.[key.replace('- ', '')] ?? "";
      pdfVal = pdfData["Габаритные размеры, мм"]?.[key.replace('- ', '')] ?? "";
    }
    if (key === "- передняя" || key === "- задняя") {
      siteVal = siteData["Подвеска(тип)"]?.[key.replace('- ', '')] ?? "";
      pdfVal = pdfData["Подвеска(тип)"]?.[key.replace('- ', '')] ?? "";
    }
    if (key === "- рабочая" || key === "- запасная" || key === "- стояночная") {
      siteVal = siteData["Тормозные системы (тип)"]?.[key.replace('- ', '')] ?? "";
      pdfVal = pdfData["Тормозные системы (тип)"]?.[key.replace('- ', '')] ?? "";
    }

    const isEmptyBoth = !siteVal && !pdfVal;
    const isMatch = isEmptyBoth || fuzzyMatch(siteVal, pdfVal, key);

    const rowId = makeRowId(key);
    const row = document.createElement("tr");
    row.id = rowId;
    row.className = isMatch ? "match" : "mismatch";

    // 🆕 Проставляем ошибку, если не совпало
    let errorText = "";
    if (!isMatch) {
      // Здесь пишем правила ошибок, например:
      if (!siteVal && pdfVal) errorText = "Нет значения на сайте, но есть в PDF";
      else if (siteVal && !pdfVal) errorText = "Нет значения в PDF, но есть на сайте";
      else if (typeof siteVal === "string" && typeof pdfVal === "string") {
        // Проверка на спец. ошибки по шаблону
        if (key.toLowerCase().includes("дата") && !normalizeDate(siteVal) && !normalizeDate(pdfVal)) {
          errorText = "Неправильный формат даты";
        } else {
          errorText = "Значения различаются";
        }
      } else {
        errorText = "Несовпадение данных";
      }
      errorFields[key] = errorText; // сохраняем ошибку
    } else {
      errorFields[key] = "";
    }

    row.innerHTML = `
      <td>${key}</td>
      <td>${formatValue(siteVal)}</td>
      <td>${formatValue(pdfVal)}</td>
      <td>${isMatch ? "✔" : "❌"}</td>
      <td>${errorText}</td> <!-- Новое поле -->
    `;
    if (!isMatch) mismatchCount++;
    tbody.appendChild(row);
  }

  showAllErrorsBlock(errorFields);


  const result = document.getElementById("finalResult");
  result.innerText = mismatchCount === 0
    ? "✔ Все поля совпадают!"
    : `❌ Несовпадение по ${mismatchCount} полям.`;


}

function showAllErrorsBlock(errorFields) {
  const allErrDiv = document.getElementById("allErrors");
  if (!allErrDiv) return;

  const errorsList = Object.entries(errorFields)
  .filter(([_, v]) => v)
  .map(([k, v]) => {
    const rowId = makeRowId(k);
    return `<li>
      <a href="#" onclick="scrollToRow('${rowId}'); return false;"><b>${k}:</b></a> ${v}
    </li>`;
  })
  .join("");
  if (!errorsList) {
    allErrDiv.style.display = "none";
    return;
  }

  allErrDiv.innerHTML = `
  <div class="error-summary-header" onclick="toggleErrorsAccordion()">
    🚨 Обнаружены ошибки (${Object.keys(errorFields).filter(k => errorFields[k]).length})
    <span id="errorAccordionArrow">&#9660;</span>
  </div>
  <div class="error-summary-content" id="errorAccordionContent" style="display:block;">
    <div class="error-hint">
      💡 <b>Совет:</b> нажмите на название поля с ошибкой, чтобы быстро перейти к нему в таблице сравнения.
    </div>
    <ul>${errorsList}</ul>
  </div>
`;
  allErrDiv.style.display = "block";
}

// Функция сворачивания/раскрытия
function toggleErrorsAccordion() {
  const content = document.getElementById("errorAccordionContent");
  const arrow = document.getElementById("errorAccordionArrow");
  if (!content) return;
  if (content.style.display === "none") {
    content.style.display = "block";
    arrow.innerHTML = "&#9660;";
  } else {
    content.style.display = "none";
    arrow.innerHTML = "&#9654;";
  }
}
   
function formatValue(val) {
  if (Array.isArray(val)) {
    // Красиво показываем каждый элемент массива на новой строке
    return val.join("<br>");
  }
  if (typeof val === "object" && val !== null) {
    return JSON.stringify(val);
  }
  return val ?? "";
}



function clearComparison() {
  siteData = null;
  pdfData = null;
  errorFields = {}; // сбрасываем ошибки!

  document.getElementById("comparisonBody").innerHTML = "";
  document.getElementById("finalResult").innerText = "";
  document.getElementById("status").innerText = "🧹 Данные очищены.";
  document.getElementById("siteUrl").value = "";

    // 🟡 Очищаем и скрываем блок ошибок:
  const allErrDiv = document.getElementById("allErrors");
  if (allErrDiv) {
    allErrDiv.innerHTML = "";
    allErrDiv.style.display = "none";
  }
}

function normalizeDate(dateStr) {
  dateStr = (dateStr ?? "").trim();

  if (!dateStr) return "";

  // Убираем лишние символы кроме цифр и разделителей
  dateStr = dateStr.replace(/[^0-9.\-\/]/g, '');

  if (dateStr.includes('-')) {
    // Преобразуем YYYY-MM-DD → 20250407
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      return parts[0] + parts[1].padStart(2, '0') + parts[2].padStart(2, '0');
    }
  } else if (dateStr.includes('.')) {
    // Преобразуем DD.MM.YYYY → 20250407
    const parts = dateStr.split('.');
    if (parts.length === 3) {
      return parts[2] + parts[1].padStart(2, '0') + parts[0].padStart(2, '0');
    }
  } else if (dateStr.includes('/')) {
    // Преобразуем DD/MM/YYYY → 20250407
    const parts = dateStr.split('/');
    if (parts.length === 3) {
      return parts[2] + parts[1].padStart(2, '0') + parts[0].padStart(2, '0');
    }
  }

  return ""; // если дата не распознана
}

function extractEcoClassNum(str) {
  if (!str) return "";
  str = str.toLowerCase();

  // 1. Если только цифра (4, 5, 6 и т.д.)
  let m = str.match(/\b[1-9]\d?\b/);
  if (m) return m[0];

  // 2. Если слово — переводим в цифру
  const dict = {
    "нулевой": "0", "ноль": "0",
    "первый": "1", "второй": "2", "третий": "3",
    "четвертый": "4", "четвёртый": "4",
    "пятый": "5", "шестой": "6", "седьмой": "7", "восьмой": "8", "девятый": "9", "десятый": "10"
  };
  for (const [k, v] of Object.entries(dict)) {
    if (str.includes(k)) return v;
  }

  return "";
}

function normalizeNumberList(str) {
  if (!str) return [];
  // Заменяем " мм", пробелы перед/после, и делим по / или запятой
  return str
    .replace(/мм/g, '')
    .split(/[\/,]/)
    .map(x => x.replace(/[^\d.-]/g, '')) // Оставляем только цифры, точку и минус
    .filter(x => x) // убираем пустые
    .map(x => {
      // Если есть точка, приводим к float → строке
      let num = parseFloat(x);
      if (!isNaN(num)) return num.toString();
      return x;
    });
}


function fuzzyMatch(a, b, fieldName = "") {
  a = (a ?? "").toString().trim();
  b = (b ?? "").toString().trim();

  if (
    (a.includes('/') || a.includes(',')) &&
    (b.includes('/') || b.includes(','))
  ) {
    const arrA = normalizeNumberList(a);
    const arrB = normalizeNumberList(b);
    if (
      arrA.length === arrB.length &&
      arrA.every((val, idx) => val === arrB[idx])
    ) return true;
  }

  if(
    (a === "-" && b === "") ||
    (a === "" && b === "-")
  ) return true;

    // --- Новое спецусловие для поля "ЭКОЛОГИЧЕСКИЙ КЛАСС" ---
  if (
    fieldName &&
    fieldName.toLowerCase().includes("экологический класс")
  ) {
    const numA = extractEcoClassNum(a);
    const numB = extractEcoClassNum(b);
    if (numA && numB && numA === numB) return true;
  }


  if (!a && !b) return true; // ✅ Оба пустые — совпадение
  if (!a || !b) return false; // ❌ Один пустой, другой нет

  // ✨ Проверка на даты
  const normalizedA = normalizeDate(a);
  const normalizedB = normalizeDate(b);
  if (normalizedA && normalizedB && normalizedA.length === 8 && normalizedB.length === 8) {
    return normalizedA === normalizedB;
  }

  // ✨ Сравнение чисел
  const numA = parseFloat(a.replace(/[^\d.,]/g, '').replace(',', '.'));
  const numB = parseFloat(b.replace(/[^\d.,]/g, '').replace(',', '.'));
  if (!isNaN(numA) && !isNaN(numB)) {
    return Math.abs(numA - numB) < 1e-2;
  }

  // ✨ Сравнение строк
  const cleanA = a.toLowerCase().replace(/[^а-яa-z0-9]/gi, '').trim();
  const cleanB = b.toLowerCase().replace(/[^а-яa-z0-9]/gi, '').trim();
  if (cleanA.startsWith(cleanB) || cleanB.startsWith(cleanA)) return true;

  try {
    const objA = JSON.parse(a);
    const objB = JSON.parse(b);
    if (typeof objA === 'object' && typeof objB === 'object') {
      return JSON.stringify(objA) === JSON.stringify(objB);
    }
  } catch {}

  return cleanA === cleanB;
}

function checkTokenStatus() {
  fetch("/check_token_status")
    .then(res => res.json())
    .then(data => {
      const statusEl = document.getElementById("tokenStatus");
      const refreshBtn = document.getElementById("refreshBtn");

      if (data.status === "valid") {
    statusEl.textContent = "✅ Токен действителен";
    statusEl.style.color = "green";
    // refreshBtn всегда видна!
    } else if (data.status === "expired") {
        statusEl.textContent = "❌ Токен истёк. Требуется повторная авторизация.";
        statusEl.style.color = "red";
    } else {
        statusEl.textContent = `❌ Ошибка проверки токена: ${data.message || data.code}`;
        statusEl.style.color = "darkred";
    }
    // Кнопка всегда показывается
    refreshBtn.style.display = "inline-block";

    })
    .catch(err => {
      const statusEl = document.getElementById("tokenStatus");
      statusEl.textContent = "❌ Ошибка при запросе токена";
      statusEl.style.color = "darkred";
      document.getElementById("refreshBtn").style.display = "inline-block";
    });
}


function scrollToRow(rowId) {
  const row = document.getElementById(rowId);
  if (!row) return;

  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.add("highlight-error-row");
  setTimeout(() => row.classList.remove("highlight-error-row"), 1500);
}


// Автоматическая проверка токена каждые 60 секунд
setInterval(checkTokenStatus, 60000);
window.onload = checkTokenStatus;

function refreshToken() {
  if (!confirm("Запустить браузер для повторной авторизации на pts.gov.kz?")) return;

  fetch("/relogin", { method: "POST" })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        alert("✅ Авторизация успешна. Новый токен получен.");
        window.location.reload();
      } else {
        alert("❌ Ошибка авторизации: " + data.error);
      }
    })
    .catch(() => {
      alert("❌ Не удалось обновить токен.");
    });
}

