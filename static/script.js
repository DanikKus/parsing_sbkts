let siteData = null;
let pdfData = null;

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
      siteData = data;
      document.getElementById("status").innerText = "✅ Данные с сайта загружены.";
      compareData();
    })
    .catch(err => {
      document.getElementById("status").innerText = "❌ Ошибка при получении данных с сайта.";
    });
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

  for (const key of priorityFields) {
    let siteVal = siteData[key];
    let pdfVal = pdfData[key];

    // Если поле объект (например, Габаритные размеры, Подвеска, Тормозные системы)
    if (key === "Габаритные размеры, мм" && typeof siteVal === "object") {
      // В основной строке оставляем пусто, или можно написать "см. ниже"
      const row = document.createElement("tr");
      row.innerHTML = `<td>${key}</td><td colspan="3" style="font-style:italic;">см. ниже</td>`;
      tbody.appendChild(row);
      continue;
    }
    if (key === "Подвеска(тип)" && typeof siteVal === "object") {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${key}</td><td colspan="3" style="font-style:italic;">см. ниже</td>`;
      tbody.appendChild(row);
      continue;
    }
    if (key === "Тормозные системы (тип)" && typeof siteVal === "object") {
      const row = document.createElement("tr");
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
    const isMatch = isEmptyBoth || fuzzyMatch(siteVal, pdfVal);

    const row = document.createElement("tr");
    row.className = isMatch ? "match" : "mismatch";
    row.innerHTML = `
      <td>${key}</td>
      <td>${formatValue(siteVal)}</td>
      <td>${formatValue(pdfVal)}</td>
      <td>${isMatch ? "✔" : "❌"}</td>
    `;
    if (!isMatch) mismatchCount++;
    tbody.appendChild(row);
  }

  const result = document.getElementById("finalResult");
  result.innerText = mismatchCount === 0
    ? "✔ Все поля совпадают!"
    : `❌ Несовпадение по ${mismatchCount} полям.`;
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

  document.getElementById("comparisonBody").innerHTML = "";
  document.getElementById("finalResult").innerText = "";
  document.getElementById("status").innerText = "🧹 Данные очищены.";
  document.getElementById("siteUrl").value = "";
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

function fuzzyMatch(a, b) {
  a = (a ?? "").toString().trim();
  b = (b ?? "").toString().trim();

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

