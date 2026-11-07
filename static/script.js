const TOS_KEY = 'sep_tos_accept_v1';
let siteData = null;
let pdfData = null;
let errorFields = {};
let evakData = null; 
let currentDocId = ""; 
let photoItems = [];   // {id, kind, handle?, url?}
let photoIndex = 0;
let decisionInFlight = false; // защита от двойных кликов

// === PROD / DEV ROUTING ===
const PROD_FRONT_ORIGIN = 'https://modulab.kz';
const PROD_API_ORIGIN   = 'https://parser.modulab.kz';

const DEFAULT_API_BASE =
  (location.origin === PROD_FRONT_ORIGIN) ? PROD_API_ORIGIN :
  (location.origin === PROD_API_ORIGIN)   ? PROD_API_ORIGIN :
  ((location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:5000'
    : location.origin);
const API_BASE = window.API_BASE || DEFAULT_API_BASE;
const TOKEN_HEADER = 'X-Parser-Token';
function getParserToken() {
  return window.localStorage.getItem('modulab_token') || '';
}

const TRUSTED_API_ORIGINS = new Set([
  new URL(API_BASE).origin,     // выбранное основание (dev/prod)
  PROD_API_ORIGIN,              // прод API
  PROD_FRONT_ORIGIN,            // прод фронт
  window.location.origin,       // текущий origin (важно!)
  'http://127.0.0.1:5000',
  'http://localhost:5000',
  'http://127.0.0.1:5173',
  'http://localhost:5173',
]);

function apiFetch(url, opts = {}) {
  const absUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const headers = new Headers(opts.headers || {});
  const origin = new URL(absUrl).origin;

  const token = getParserToken();
  if (token && TRUSTED_API_ORIGINS.has(origin)) {
    headers.set(TOKEN_HEADER, token);
  }

  // Для кросс-доменных запросов включаем CORS (куки не нужны — аутентификация по токену)
  const extra = (origin !== location.origin) ? { mode: 'cors', credentials: 'omit' } : {};
  return fetch(absUrl, { ...extra, ...opts, headers });
}


const ApiFetch = apiFetch;
window.ApiFetch = apiFetch;
ensureAgreement();

function extractDocIdFromUrl(url) {
  const m = (url || "").match(/[0-9a-fA-F-]{36}/);
  return m ? m[0] : "";
}

function setParseButtonEnabled(enabled) {
  const btn = document.querySelector('button[onclick="fetchFromSite()"]');
  if (btn) btn.disabled = !enabled;
}

async function fetchFromSite() {
  const url = document.getElementById("siteUrl").value.trim();
  console.log("[fetchFromSite] url =", url);
  if (!url) return;

  const statusEl = document.getElementById("status");
  statusEl.innerText = "⏳ Загружаем данные...";

  const fast = await extensionInstalled();
  console.log("[fetchFromSite] extensionInstalled =", fast);

  // Пытаемся быстрым путём через расширение
  if (fast) {
    try {
      await eptsSetToken();

      const u = new URL(url);
      const tryUuid = (s) => ((s || "").match(/[0-9a-fA-F-]{36}/) || [])[0];
      const path = (u.pathname || "").toLowerCase();

      let apiUrl = null, method = "GET", body = null;

      if (/\/compliencedocument\/sbkts\//i.test(path)) {
        const id = tryUuid(url);
        apiUrl = "https://pts.gov.kz/api/compliencedocument/get?id=" + encodeURIComponent(id);
      } else if (/^\/?api\/compliencedocument\/getlist/i.test(path)) {
        apiUrl = "https://pts.gov.kz/api/compliencedocument/getlist";
        method = "POST";
        const qp = Object.fromEntries(u.searchParams.entries());
        if (!("page" in qp)) qp.page = 1;
        if (!("pageSize" in qp)) qp.pageSize = 1;
        body = qp;
      } else if (/^\/?api\/compliencedocument\/get/i.test(path)) {
        const id = u.searchParams.get("id") || tryUuid(url);
        apiUrl = "https://pts.gov.kz/api/compliencedocument/get?id=" + encodeURIComponent(id);
      } else {
        const anyId = tryUuid(url);
        if (anyId) apiUrl = "https://pts.gov.kz/api/compliencedocument/get?id=" + encodeURIComponent(anyId);
      }

      if (!apiUrl) throw new Error("Эта ссылка не поддерживается в fast-режиме");

      // 1) базовый документ
      let base = await eptsFetch(apiUrl, { method, body });

      // 2) если это был список — добираем id и читаем карточку
      let idForDetails = null;
      if (base?.data?.data && Array.isArray(base.data.data)) {
        const rows = base.data.data;
        if (!rows.length) throw new Error("По запросу ничего не найдено.");
        if (rows.length > 1) {
          statusEl.innerText = "⚠️ Найдено несколько документов. Уточните номер/фильтр.";
          return;
        }
        idForDetails = rows[0].id;
        base = await eptsFetch(`https://pts.gov.kz/api/compliencedocument/get?id=${encodeURIComponent(idForDetails)}`);
      } else {
        // обычный Get вернул карточку
        idForDetails = base?.data?.id || extractDocIdFromUrl(url);
      }
      if (!idForDetails) throw new Error("Не удалось определить id документа.");

      // 3) добираем все дочерние блоки
      const details = await fetchAllDetailsById(idForDetails);

      // 4) отправляем на бэкенд в формате, который ждёт parse_vehicle_data_from_raw(raw)
      const resp = await ApiFetch("/parse_site_from_client", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw: {
            base: base?.data || base,   // 👈 ВАЖНО: отправляем сам объект документа, а не весь ответ API
            details
          }
        })
      });

      const data = await toJSONSafe(resp);
      await afterParsed(data);
      return;
    } catch (e) {
      console.warn("[fast path] fallback to /parse_site:", e);
    }
  }

  // Fallback: сервер сам достанет (HTML/requests-логика)
  try {
    const r = await ApiFetch("/parse_site", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });
    const data = await toJSONSafe(r);
    await afterParsed(data);
  } catch (e) {
    console.error(e);
    statusEl.innerText = "❌ Ошибка при получении данных.";
  }
}


async function afterParsed(data) {
  const fields = normalizeFieldsPayload(data);
  siteData = applyFieldAliases(fields || {});   // <-- было: siteData = data.fields || {}
  evakData = data.evak || null;
  currentDocId = data.docId || extractDocIdFromUrl(document.getElementById("siteUrl")?.value || "");
  window.currentDocId = currentDocId;

  document.getElementById("docIdView").innerText = currentDocId || "—";
  renderEvents(data.events || []);
  if ((!data.events || data.events.length === 0) && currentDocId) {
    setEventsLoading?.(); loadEventsByDocId(currentDocId);
  }

  updateStatusBadge(data.statusLabel, data.statusCode);
  if (data.warning) {
    document.getElementById("status").innerText = `⚠️ ${data.warning}`;
  } else {
    const st = (data.statusLabel || data.statusCode || "").toString();
    document.getElementById("status").innerText = st ? `✅ Статус: ${st}.` : "✅ Данные загружены.";
  }

  renderEvakCard(evakData);
  renderKedenCard(data.keden_kz || null);
  maybeAutoVinFrom(siteData);
  compareData();
  loadPhotos();
}

async function toJSONSafe(res) {
  const ct = (res.headers.get("content-type") || "").toLowerCase();
  if (!ct.includes("application/json")) {
    const text = await res.text();
    const err = new Error(`HTTP ${res.status} ${res.statusText} (non-JSON)`);
    err._text = text;
    err._status = res.status;
    throw err;
  }
  const data = await res.json();
  if (!res.ok) {
    const msg = (data && (data.error || data.message)) || `HTTP ${res.status}`;
    const err = new Error(msg);
    err._json = data;
    err._status = res.status;
    throw err;
  }
  return data;
}

function normalizeFieldsPayload(data){
  return data?.fields ?? data?.site ?? data?.pdf ?? data?.data ?? data;
}

// Перекладываем известные алиасы ключей (чтобы "Номер документа" всегда заполнялся)
function applyFieldAliases(data) {
  const aliases = {
    "Описание гибридного привода": "Описание гибридного транспортного средства",
    "СЕРИЯ KZ №": "Номер документа",
    "Серия KZ №": "Номер документа",
    "№ документа": "Номер документа",
    "Номер документа*": "Номер документа",
    "TC KZ": "Номер документа",
    "ТС KZ": "Номер документа",
  };
  for (const [from, to] of Object.entries(aliases)) {
    if (data && data[from] && !data[to]) data[to] = data[from];
  }
  return data;
}

/** Собрать текст причин отказа из карусели ошибок (если пользователь поле не заполнил) */
function buildRejectMessageFromErrors() {
  const pairs = Object.entries(errorFields).filter(([k, v]) => v);
  if (pairs.length === 0) return "";
  const lines = pairs.map(([k, v]) => `- ${k}: ${v}`);
  return `Причины отказа:\n${lines.join("\n")}`;
}

let lastDecisionKey = "";

async function sendDecision(decision) {
  if (!currentDocId) {
    alert("Не найден DocId. Вставьте ссылку PTS и нажмите «Парсить сайт».");
    return;
  }
  if (decisionInFlight) return;

  decision = (decision || "").toLowerCase();
  if (decision !== "approve" && decision !== "reject") return;

  const approveMsg = (document.getElementById("approveMsg")?.value || "").trim();
  let   rejectMsg  = (document.getElementById("rejectMsg")?.value  || "").trim();

  if (decision === "reject" && !rejectMsg) {
    rejectMsg = buildRejectMessageFromErrors() || "Отказ без пояснения";
  }
  const message = decision === "approve" ? (approveMsg || "Подтверждено") : rejectMsg;

  // идемпотентный ключ (локальный)
  const decisionKey = `${currentDocId}|${decision}|${message}`;
  if (lastDecisionKey === decisionKey) return; // тот же самый — не шлём второй раз
  lastDecisionKey = decisionKey;

  const errCount = Object.values(errorFields || {}).filter(Boolean).length;
  const warnPart = (decision === "approve" && errCount > 0)
    ? `\n\n⚠ Обнаружено несоответствий: ${errCount}. Вы уверены, что хотите ОДОБРИТЬ?`
    : "";

  const actionRu = decision === "approve" ? "одобрить" : "отклонить";
  const previewMsg = message ? `\n\nКомментарий:\n${message.slice(0, 600)}` : "";
  const ok = confirm(`Вы уверены, что хотите ${actionRu} документ?\nDocId: ${currentDocId}${previewMsg}${warnPart}`);
  if (!ok) {
    const out = document.getElementById("decisionStatus");
    if (out) { out.textContent = "Операция отменена."; out.style.color = "#555"; }
    lastDecisionKey = ""; // разрешим повторный клик
    return;
  }

  const btnApprove = document.getElementById("btnApprove");
  const btnReject  = document.getElementById("btnReject");
  [btnApprove, btnReject].forEach(b => b && (b.disabled = true));
  decisionInFlight = true;

  const out = document.getElementById("decisionStatus");
  if (out) { out.textContent = "⏳ Отправляем решение..."; out.style.color = "#444"; }

  // --- попытка применить через расширение ePTS ---
    const applyViaExtension = async (force = false) => {
        const res = await callExtension("EPTS_DECISION", {
          docId: currentDocId,
          decision,
          message,
          force
        });

        console.log("[decision] EPTS_DECISION response:", res);

        if (!res || !res.ok) {
          // кидаем ошибку, чтобы наверху отработал fallback на бэкенд
          throw new Error(res?.error || res?.status || "EXT_ERROR");
        }

        return res; // ожидаем { ok:true, via:"extension"|"already_applied" }
      };

  // --- старый бэковый путь (по желанию можно удалить совсем) ---
  const applyViaBackend = (force = false) =>
    ApiFetch("/decision", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ docId: currentDocId, decision, message, force })
    }).then(r => r.json().then(j => ({ status: r.status, body: j })));

  try {
    const hasExt = await extensionInstalled();

    if (hasExt) {
      // 1) пробуем через расширение
      try {
        const extRes = await applyViaExtension(false);

        if (!out) return;

        if (extRes.via === "already_applied") {
          out.textContent = "ℹ Сервер вернул: уже было применено раньше.";
          out.style.color = "#555";
        } else {
          out.textContent = `✅ Запрос на смену статуса отправлен через расширение, проверяем фактический статус...`;
          out.style.color = "green";
        }

        if (currentDocId) {
          try {
            // подгружаем события
            setEventsLoading?.();
            loadEventsByDocId(currentDocId);

            // и саму карточку из ePTS
            const base = await fetchBaseDocWithFallback(currentDocId);
            const code  = base?.statusCode || base?.data?.statusCode;
            const label = base?.statusName || base?.data?.statusName;

            console.log('[decision] fresh doc after processRequest:', { code, label, base });

            if (code || label) {
              updateStatusBadge(label, code);
            } else {
              appendErrorForField("Статус", "После processRequest не удалось получить статус документа.");
            }
          } catch (e) {
            console.warn('[decision] failed to reload doc:', e);
            appendErrorForField("Статус", "Ошибка при повторном чтении статуса из ePTS.");
          }
        }

        // // Обновим бейджи и события
        // updateStatusBadge(
        //   decision === "approve" ? "Действующий" : "Отклонённый",
        //   decision === "approve" ? "active" : "rejected"
        // );
        // if (currentDocId) {
        //   setEventsLoading?.();
        //   loadEventsByDocId(currentDocId);
        // }

        return; // всё, через расширение получилось — на бэк можно даже не падать
      } catch (extErr) {
        console.warn("[decision] extension path failed, fallback to backend:", extErr);
        // идём в старый путь, если он ещё жив
      }
    }

    // 2) если расширения нет или оно упало — старый backend /decision
    const { status, body } = await applyViaBackend(false);

    if (!out) return;

    if (status === 409 && body.conflict) {
      const okForce = confirm("Для этого DocId уже применено другое решение. Применить новое принудительно?");
      if (!okForce) throw new Error("Отменено пользователем");
      const forced = await applyViaBackend(true);
      handleBackendDecisionResult(forced.status, forced.body, out, decision);
    } else {
      handleBackendDecisionResult(status, body, out, decision);
    }
  } catch (e) {
    console.error("[decision] error:", e);
    if (out) { out.textContent = "❌ Ошибка отправки решения."; out.style.color = "red"; }
  } finally {
    decisionInFlight = false;
    [btnApprove, btnReject].forEach(b => b && (b.disabled = false));
    // lastDecisionKey не сбрасываем — защита от повторной отправки того же payload
  }
}

// вспомогалка только для бэка
function handleBackendDecisionResult(status, body, out, decision) {
  if (body?.ok && body.via === "immediate") {
    out.textContent = `✅ Установлено: ${decision === "approve" ? "Действующий" : "Отклонённый"}.`;
    out.style.color = "green";
  } else if (body?.ok && body.via === "already_applied") {
    out.textContent = "ℹ Уже было применено раньше (идемпотентность).";
    out.style.color = "#555";
  } else if (body?.queued) {
    out.textContent = `⚠️ Не удалось сразу. Поставлено в очередь. Следим за статусом...`;
    out.style.color = "#a65b00";
    pollDecisionStatus(currentDocId, out);
  } else {
    out.textContent = "❌ Ошибка: " + (body?.error || `HTTP ${status}`);
    out.style.color = "red";
  }
}

async function extensionInstalled() {
  console.log('[MODULAB DEBUG] extensionInstalled called');
  try {
    const r = await callExtension('EPTS_PING');
    return !!(r && r.ok);
  } catch {
    return false;
  }
}

async function eptsSetToken() {
  const parserToken = getParserToken();
  if (!parserToken) return false;
  try {
    const r = await callExtension('EPTS_SET_TOKEN', { parserToken });
    return !!(r && r.ok);
  } catch {
    // пусть молча проходит: у вас есть fallback/контент-скрипт
    return false;
  }
}

async function eptsConnect() {
  await eptsSetToken();
  try {
    return await callExtension('connect-pts'); // {ok, statusCode?}
  } catch {
    return { ok: false };
  }
}

async function eptsFetch(url, opts = {}) {
  const res = await callExtension('EPTS_FETCH', {
    url,
    method: opts.method || 'GET',
    headers: opts.headers || { 'Accept': 'application/json', 'Content-Type': 'application/json' },
    body: opts.body || undefined
  });
  if (!res?.ok) throw new Error(res?.error || 'EXT_ERROR');
  if (res.status !== 200) throw new Error(`EPTS HTTP ${res.status}`);
  return res.data; // именно JSON-ответ API (с полем data внутри)
}

async function fetchEPTSWithFallback(name, id) {
  const base = 'https://pts.gov.kz/api/ComplienceDocument/';
  try {
    const r = await eptsFetch(base + name, { method:'POST', body: { id } });
    return (r && r.data) ? r.data : r;
  } catch {
    const r2 = await eptsFetch(base + name + `?id=${encodeURIComponent(id)}`, { method:'GET' });
    return (r2 && r2.data) ? r2.data : r2;
  }
}

async function fetchBaseDocWithFallback(id) {
  try {
    return await eptsFetch('https://pts.gov.kz/api/ComplienceDocument/Get', {
      method:'POST', body:{ id }
    });
  } catch {
    return await eptsFetch(`https://pts.gov.kz/api/ComplienceDocument/Get?id=${encodeURIComponent(id)}`, {
      method:'GET'
    });
  }
}

async function fetchAllDetailsById(id) {
  const EP = [
    ['machines',     'GetElectricalMachineDetailsByDocId'],
    ['storage',      'GetPowerStorageDeviceDetailsByDocId'],
    ['layoutDetails','GetVehicleLayoutDetailsByDocId'],
    ['layouts',      'GetVehicleLayoutsByDocId'],
    ['clutch',       'GetVehicleClutchDetailsByDocId'],
    ['transmission', 'GetTransmissionTypesByDocId'],
    ['engine',       'GetEngineDetailsByDocId'],
    ['weight',       'GetVehicleWeightDetailsByDocId'],
    ['dimensions',   'GetVehicleDimensionDetailsByDocId'],
    ['height',       'GetVehicleHightDetailsByDocId'],
    ['wheelbase',    'GetWheelbaseMeasuresByDocId'],
    ['axles',        'GetVehicleAxleDetailsByDocId'],
    ['seats',        'GetVehicleSeatDetailsByDocId'],
    ['suspension',   'GetVehicleSuspensionDetailsByDocId'],
    ['runningGear',  'GetVehicleRunningGearDetailsByDocId'],
    ['bodywork',     'GetVehicleBodyworkDetailsByDocId'],
    ['steering',     'GetVehicleSteeringDetailsByDocId'],
    ['brakes',       'GetVehicleBrakingSystemDetailsByDocId'],
    ['tyres',        'GetVehicleTyreKindInfosByDocId'],
    ['extras',       'GetVehicleEquipmentInfosByDocId'],
  ];

  const settled = await Promise.allSettled(
    EP.map(([_, name]) => fetchEPTSWithFallback(name, id))
  );

  const out = {};
  EP.forEach(([key, name], i) => {
    const r = settled[i];
    if (r.status === 'fulfilled') out[key] = r.value;
    else { out[key] = null; console.warn('EPTS endpoint failed:', name, r.reason?.message || r.reason); }
  });
  console.log('details health:', Object.fromEntries(Object.entries(out).map(([k,v])=>[k, !!v])));
  return out;
}

document.addEventListener('DOMContentLoaded', async () => {
  console.log('[MODULAB DEBUG] DOMContentLoaded fired');
  if (!(await extensionInstalled())) showExtensionBanner();
  await checkTokenStatus();          // только статус расширения
  const urlParams = new URLSearchParams(window.location.search);
  const urlToken = urlParams.get('token');
  if (urlToken) processNewToken(urlToken); else checkExistingSession();
  const btn = document.getElementById("refreshBtn");
  if (btn) btn.style.display = "none";  // эту кнопку больше не используем
});


function showExtensionBanner() {
  const el = document.getElementById('extBanner');
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = `
    <div><b>Чтобы подключить ПТС, установите расширение «PTS Connector»:</b></div>
    <ol style="margin:6px 0 0 18px">
      <li>Откройте <code>chrome://extensions</code> (или edge://extensions)</li>
      <li>Включите «Режим разработчика»</li>
      <li>Нажмите «Загрузить распакованное» и выберите папку <code>pts-connector</code></li>
    </ol>
    <div style="margin-top:6px">После установки вернитесь и нажмите «Подключить ПТС».</div>
  `;
}

function ensureAgreement() {
  if (localStorage.getItem(TOS_KEY) === '1') return Promise.resolve(true);

  // простая модалка на лету
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position: fixed; inset: 0; background: rgba(0,0,0,.5);
    display: flex; align-items: center; justify-content: center; z-index: 99999;
  `;
  const modal = document.createElement('div');
  modal.style.cssText = `
    max-width: 820px; width: calc(100% - 32px); background: #fff; padding: 20px;
    border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,.2); max-height: 80vh; overflow: auto;
    font: 14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, Arial;
  `;
  modal.innerHTML = `
    <h2 style="margin:0 0 12px">Согласие и ответственность</h2>
    <div style="font-size:13px; color:#333">
      <p>Я, как пользователь ИС «Система электронных паспортов транспортных средств (СЭП)», соглашаюсь с условиями использования и несу полную ответственность за все действия, совершенные с её использованием, включая правильность и законность предоставленных данных. Неправомерные действия могут повлечь административную ответственность.</p>
      <p>ЭЦП является эквивалентом собственноручной подписи (ст. 370 Закона РК «Об электронном документе и ЭЦП»). Я подтверждаю, что не передаю ЭЦП третьим лицам. За нарушение правил использования ЭЦП предусмотрена ответственность (ст. 640 КоАП РК).</p>
      <p><b>Внимание по конфиденциальности:</b> это приложение <b>не хранит ваши логин и пароль</b>. Для работы используются <b>временные технические cookie/токен</b> ПТС, которые сохраняются локально на сервере приложения и автоматически удаляются по истечении срока действия или при выходе (Logout).</p>
    </div>
    <label style="display:flex; gap:8px; align-items:flex-start; margin:14px 0;">
      <input type="checkbox" id="agreeChk">
      <span>Я ознакомлен(а) и принимаю условия.</span>
    </label>
    <div style="display:flex; gap:8px; justify-content:flex-end">
      <button id="agreeBtn" disabled style="padding:8px 14px; border:0; border-radius:8px; background:#0a7; color:#fff; cursor:not-allowed;">Продолжить</button>
    </div>
  `;
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const chk = modal.querySelector('#agreeChk');
  const btn = modal.querySelector('#agreeBtn');
  chk.addEventListener('change', () => {
    btn.disabled = !chk.checked;
    btn.style.cursor = chk.checked ? 'pointer' : 'not-allowed';
    btn.style.background = chk.checked ? '#0a7' : '#999';
  });

  return new Promise(resolve => {
    btn.addEventListener('click', () => {
      localStorage.setItem(TOS_KEY, '1');
      overlay.remove();
      resolve(true);
    });
  });
}

function pollDecisionStatus(docId, outEl, timeoutMs = 120000, everyMs = 5000) {
  const started = Date.now();
  const tick = () => {
    ApiFetch(`/decision/status?docId=${encodeURIComponent(docId)}`)
      .then(r => r.json())
      .then(st => {
        if (st.state === "applied") {
          outEl.textContent = "✅ Применено (из очереди).";
          outEl.style.color = "green";
          return; // стоп
        }
        if (Date.now() - started > timeoutMs) {
          outEl.textContent = "⏳ Всё ещё в очереди. Проверьте позже.";
          outEl.style.color = "#555";
          return;
        }
        setTimeout(tick, everyMs);
      })
      .catch(() => setTimeout(tick, everyMs));
  };
  setTimeout(tick, everyMs);
}

// Хоткеи: A — одобрить, R — отклонить (кроме когда печатаем в инпут/текстарию)
window.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  if (e.key === "a" || e.key === "A") {
    sendDecision("approve");
  } else if (e.key === "r" || e.key === "R") {
    sendDecision("reject");
  }
});

function setCustomsResult(text, isError = false, isHtml = false) {
  const box = document.getElementById("customsResult");
  if (!box) return;
  box.className = "vin-result " + (isError ? "vin-result--error" : "vin-result--ok");
  box.innerHTML = isHtml ? text : escapeHtml(text);
}

function renderCustomsAutoCard(res) {
  const box = document.getElementById("customsResult");
  if (!box || !res) return;

  if (res.error) {
    setCustomsResult("❌ " + res.error, true);
    return;
  }
  if (res.found === false) {
    setCustomsResult("⚠️ " + (res.message || "Данные по VIN не найдены на customs.gov.ru."), true);
    return;
  }

  const d = res.data || {};
  const country = res.country || {};
  const countryRow =
    d["Страна выпуска"] ||
    (country.code ? `${country.code}${country.name ? " — " + country.name : ""}` : "—");

  const html = `
    <div class="vin-card">
      <div style="margin-bottom:6px; color:#2f855a;">✅ Найдено на customs.gov.ru</div>
      <table class="kv">
        <tr><th>VIN</th><td>${escapeHtml(d["Номер VIN"] || res.vin || "")}</td></tr>
        <tr><th>Модель</th><td>${escapeHtml(d["Модель"] || "")}</td></tr>
        <tr><th>Номер кузова</th><td>${escapeHtml(d["Номер кузова"] || "")}</td></tr>
        <tr><th>Номер шасси</th><td>${escapeHtml(d["Номер шасси"] || "—")}</td></tr>
        <tr><th>Дата выпуска в свободное обращение</th><td>${escapeHtml(d["Дата выпуска в свободное обращение"] || "")}</td></tr>
        <tr><th>Страна выпуска</th><td>${escapeHtml(countryRow)}</td></tr>
        <tr><th>Источник ответа</th><td>customs.gov.ru/cars</td></tr>
      </table>
    </div>
  `;
  setCustomsResult(html, false, true);
}



function pickVin(obj) {
  if (!obj) return "";
  for (const key of ["ИДЕНТИФИКАЦИОННЫЙ НОМЕР (VIN)","Идентификационный номер (VIN)","VIN","Vin"]) {
    const v = (obj[key] || "").toString().trim().toUpperCase();
    if (/^[A-HJ-NPR-Z0-9]{17}$/.test(v)) return v;
  }
  // запасной поиск по значениям
  const joined = Object.values(obj).filter(x => typeof x === "string").join(" ").toUpperCase();
  const m = joined.match(/[A-HJ-NPR-Z0-9]{17}/);
  return m ? m[0] : "";
}
function maybeAutoVinFrom(obj) {
  const vin = pickVin(obj);
  if (!vin) return;

  // EVAK (как было)
  ApiFetch("/check_vin", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ vin })
  })
  .then(r => r.json())
  .then(evak => renderEvakCard(evak))
  .catch(() => {});

  // eOKHO — проверка eokno.gov.kz
  ApiFetch("/eokno/check", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ vin })
  })
  .then(r => r.json())
  .then(eokno => renderEoknoCard(eokno))
  .catch(() => {});

  // customs.gov.ru — автоматическая проверка по VIN
  ApiFetch("/customs/check", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ vin })
  })
  .then(r => r.json())
  .then(customs => renderCustomsAutoCard(customs))
  .catch(() => setCustomsResult("❌ Ошибка запроса к customs.gov.ru.", true));

  // keden.kgd.gov.kz — таможня Казахстана
  ApiFetch("/keden/check", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ vin })
  })
  .then(r => r.json())
  .then(keden => renderKedenCard(keden))
  .catch(() => setKedenResult("❌ Ошибка запроса к keden.kgd.gov.kz.", true));
}



// защита от повторных параллельных вызовов
let photosLoading = false;

function loadPhotos() {
  if (photosLoading) return;
  photosLoading = true;

  const url = (document.getElementById("siteUrl")?.value || "").trim();
  const status = document.getElementById("photosStatus");
  if (status) status.textContent = "⏳ Ищем фото...";

  const payload = {
    url: url || undefined,
    docId: (currentDocId || "").trim() || undefined
  };

  ApiFetch("/photos/list", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  })
  .then(r => r.json())
  .then(data => {
    console.log("[photos] list →", data);              // ← ЛОГ 1
    if (status) status.textContent = data.error
      ? ("❌ " + data.error)
      : `Найдено фото: ${(data.items||[]).length}`;

    window.photoItems = data.items || [];
    renderPhotoGrid();
  })
  .catch(err => {
    console.error("[photos] list error", err);
    if (status) status.textContent = "❌ Ошибка загрузки фото.";
  })
  .finally(() => { photosLoading = false; });
}


function normalizePtsStatus(codeOrLabel) {
  const s = (codeOrLabel || '').toString().trim().toLowerCase();
  if (!s) return '';
  if (s.includes('consideration') || s.includes('на рассмотр')) return 'consideration';
  if (s.includes('inrevision')    || s.includes('доработ'))      return 'inrevision';
  if (['active','актив','действ'].some(x => s.includes(x)))      return 'active';
  if (['rejected','отклон'].some(x => s.includes(x)))            return 'rejected';
  if (['closed','закрыт','истек','истёк','expired'].some(x => s.includes(x))) return 'closed';
  if (['cancel','отмен'].some(x => s.includes(x)))               return 'canceled';
  return '';
}


function updateStatusBadgeGeneric(elId, label, code) {
  const el = document.getElementById(elId);
  if (!el) return;

  const norm = normalizePtsStatus(code || label);
  el.className = 'badge';
  if (!label && !code) { el.textContent = '—'; return; }

  const mapping = {
    consideration: 'На рассмотрении',
    inrevision:    'На доработке',
    active:        'Действующий',
    rejected:      'Отклонённый',
    closed:        'Закрытый',
    canceled:      'Отменённый',
  };
  const finalLabel = mapping[norm] || (label || '—');

  if (norm === 'active') el.classList.add('badge--ok');
  else if (norm === 'consideration' || norm === 'inrevision') el.classList.add('badge--wait');
  else if (['rejected','closed','canceled'].includes(norm)) el.classList.add('badge--bad');

  el.textContent = finalLabel;
}

function updateTrBadge(labelOrCode)        { updateStatusBadgeGeneric('trStatusBadge',  labelOrCode, labelOrCode); }
function updatePtsBadge(label, code)       { updateStatusBadgeGeneric('ptsStatusBadge', label, code); }
function resetBadges()                     { updateTrBadge(null); updatePtsBadge(null, null); }

// Универсальная обёртка, чтобы не править все вызовы по проекту
function updateStatusBadge(label, code) {
  updatePtsBadge(label, code);
}
function resetStatusBadge() {
  updatePtsBadge(null, null);
}


function openPhotoModal(i) {
  photoIndex = i;
  const modal = document.getElementById("photoModal");
  const img = document.getElementById("photoModalImg");
  const cnt = document.getElementById("photoCounter");
  const ph = photoItems[photoIndex];

  const t = getParserToken();
  const addAuth = t ? (s => s + (s.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t)) : (s => s);

  let src = "";
  if (ph.kind === "data" && ph.handle) {
    src = `${API_BASE}/photos/stream?variant=full&handle=${encodeURIComponent(ph.handle)}`;
  } else if (ph.kind === "url") {
    const qs = ph.key ? `key=${encodeURIComponent(ph.key)}` : `u=${encodeURIComponent(ph.url)}`;
    src = `${API_BASE}/photos/stream?variant=full&${qs}`;
  }
  img.src = addAuth(src);
  cnt.textContent = `${photoIndex+1}/${photoItems.length}`;
  modal.style.display = "block";
}

function renderPhotoGrid() {
  const grid = document.getElementById("photoGrid");
  if (!grid) return;
  grid.innerHTML = "";
  if (!photoItems.length) return;

  const t = getParserToken();
  const addAuth = t ? (s => s + (s.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t)) : (s => s);

  photoItems.forEach((ph, i) => {
    const img = document.createElement("img");
    img.className = "photo-thumb";
    img.alt = `Фото ${i + 1}`;
    img.loading = "lazy";

    let src = "";
    if (ph.kind === "data" && ph.handle) {
      src = `${API_BASE}/photos/stream?variant=thumb&handle=${encodeURIComponent(ph.handle)}`;
    } else if (ph.kind === "url") {
      const qs = ph.key ? `key=${encodeURIComponent(ph.key)}` : `u=${encodeURIComponent(ph.url || "")}`;
      src = `${API_BASE}/photos/stream?variant=thumb&${qs}`;
    }

    img.src = addAuth(src);
    img.onerror = () => { img.src = addAuth(src.replace("variant=thumb", "variant=orig")); };
    img.addEventListener("click", () => openPhotoModal?.(i));
    grid.appendChild(img);
  });
}

function fetchFromPtsByNumber() {
  const num = (document.getElementById("ptsNumber").value || "").trim();
  const onlyActive = !!document.getElementById("ptsOnlyActive")?.checked; // можете игнорить; бэкенд всё равно фильтрует «На рассмотрении»
  if (!num) return;

  const statusEl = document.getElementById("status");
  statusEl.innerText = "⏳ Загружаем PTS по номеру...";

  ApiFetch("/api/pts/sbkts/fields", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ num, onlyActive}) // ← важно
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      // сервер сказал: документ НЕ «На рассмотрении» — поля не парсим
      updatePtsBadge(data.statusLabel, data.statusCode);
      statusEl.innerText = "⚠️ " + data.error;
      return;
    }

    // всё хорошо: есть ровно один doc и он «На рассмотрении»
    updatePtsBadge(data.statusLabel, data.statusCode);

    siteData     = data.fields || {};
    evakData     = data.evak   || null;
    currentDocId = data.docId  || "";
    window.currentDocId = currentDocId;


    document.getElementById("docIdView").innerText = currentDocId || "—";
    renderEvents([]);       
    if (currentDocId) { setEventsLoading?.(); loadEventsByDocId(currentDocId); }

    statusEl.innerText = "✅ Данные PTS загружены.";
    renderEvakCard(evakData);
    renderKedenCard(data.keden_kz || null);
    maybeAutoVinFrom(siteData);
    compareData();
    loadPhotos();
  })
  .catch(err => {
    console.error(err);
    statusEl.innerText = "❌ Ошибка при получении данных PTS.";
  });
}

// function renderEvents(events) {
//   const el = document.getElementById('eventsPanel');
//   if (!el) return;

//   if (!events || !events.length) {
//     el.innerHTML = '<div class="events-empty">Событий нет.</div>';
//     return;
//   }
//   const html = events.map(ev => {
//     const dt = (ev.eventDateTime || '').toString();
//     const title = (ev.title || ev.eventType || '').toString();
//     const desc = (ev.description || '').toString();
//     const who = (ev.authorName || '').toString();

//     return `
//       <div class="event-item">
//         <div class="event-head">
//           <span class="event-date">${escapeHtml(dt)}</span>
//           <span class="event-title">— ${escapeHtml(title)}</span>
//           ${who ? `<span class="event-author">(${escapeHtml(who)})</span>` : ""}
//         </div>
//         ${desc ? `<div class="event-desc">${escapeHtml(desc)}</div>` : ""}
//       </div>
//     `;
//   }).join('');
//   el.innerHTML = `<div class="events-timeline-list">${html}</div>`;
// }

function renderEvents(events) {
  const el = document.getElementById('eventsPanel');
  if (!el) return;

  if (!events || !events.length) {
    el.innerHTML = '<div class="events-empty">Событий нет.</div>';
    return;
  }

  const html = events.map(ev => {
    const dt =
      ev.eventDateTime ||
      ev.eventDate ||
      ev.date ||
      ev.datetime ||
      ev.createdAt ||
      '';

    const title =
      ev.title ||
      ev.eventType ||
      ev.eventName ||
      ev.statusName ||
      ev.statusCode ||
      '';

    const desc =
      ev.description ||
      ev.comment ||
      ev.details ||
      ev.message ||
      '';

    const who =
      ev.authorName ||
      ev.userName ||
      ev.employeeName ||
      ev.operatorName ||
      '';

    return `
      <div class="event-item">
        <div class="event-head">
          <span class="event-date">${escapeHtml(dt)}</span>
          <span class="event-title"> — ${escapeHtml(title)}</span>
          ${who ? `<span class="event-author">(${escapeHtml(who)})</span>` : ""}
        </div>
        ${desc ? `<div class="event-desc">${escapeHtml(desc)}</div>` : ""}
      </div>
    `;
  }).join('');

  el.innerHTML = `<div class="events-timeline-list">${html}</div>`;
}



function setEventsLoading() {
  const el = document.getElementById('eventsPanel');
  if (el) el.innerHTML = '<div class="events-empty">Загружаем события…</div>';
}

// async function loadEventsByDocId(docId) {
//   try {
//     const r = await ApiFetch('/api/pts/events', {
//       method: 'POST',
//       headers: {'Content-Type': 'application/json'},
//       body: JSON.stringify({ docId })
//     });
//     const j = await r.json();
//     // если бэк когда-нибудь пришлёт статус — обновим
//     if (j && (j.statusLabel || j.statusCode)) {
//       updateStatusBadge(j.statusLabel, j.statusCode);
//     }
//     renderEvents(j.events || []);
//   } catch {
//     renderEvents([]);
//   }
// }

async function loadEventsByDocId(docId) {
  try {
    const r = await ApiFetch('/api/pts/events', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ docId })
    });
    const j = await r.json();

    console.log('[events] raw /api/pts/events response:', j);

    if (j && (j.statusLabel || j.statusCode)) {
      updateStatusBadge(j.statusLabel, j.statusCode);
    }

    let events = [];
    if (Array.isArray(j)) {
      // бэкенд вернул просто список
      events = j;
    } else if (Array.isArray(j.events)) {
      // { events: [...] }
      events = j.events;
    } else if (Array.isArray(j.data)) {
      // { data: [...] }
      events = j.data;
    } else if (j.data && Array.isArray(j.data.events)) {
      // { data: { events: [...] } }
      events = j.data.events;
    } else if (j.data && Array.isArray(j.data.data)) {
      // { data: { data: [...] } } — типичный ответ ПТС, завернутый в data
      events = j.data.data;
    }

    renderEvents(events);
  } catch (e) {
    console.warn('[events] loadEventsByDocId error:', e);
    const el = document.getElementById('eventsPanel');
    if (el) el.innerHTML = '<div class="events-empty">Ошибка при загрузке событий.</div>';
  }
}



function fetchFromPtsByNumberFast() {
  const num = (document.getElementById("ptsNumber").value || "").trim();
  const onlyActive = !!document.getElementById("ptsOnlyActive")?.checked;
  if (!num) return;

  document.getElementById("status").innerText = "⏳ Быстрый режим: тянем JSON по номеру...";

  ApiFetch("/api/pts/by_number_fast", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ num, onlyActive })
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      // несколько совпадений — покажем список так же, как в обычной функции
      if (Array.isArray(data.matches) && data.matches.length) {
        const list = data.matches.map(m => {
          const dt = (m.docDate || "").split("T")[0] || "—";
          return `• ${m.docNumber || "—"} (${dt}) — ${m.brandName || "—"} ${m.type || ""} [${m.statusCode || "—"}], id=${m.id}`;
        }).join("\n");
        document.getElementById("status").innerText =
          "⚠️ " + data.error + "\n" + list + "\n\nУточните номер (или снимите галочку «только действующие»).";
        return;
      }
      document.getElementById("status").innerText = "❌ " + data.error;
      return;
    }

    // успех: уже готовые поля, без парсинга HTML
    siteData = data.fields || {};
    evakData = data.evak || null;
    currentDocId = data.docId || "";
    window.currentDocId = currentDocId;
    document.getElementById("docIdView").innerText = currentDocId || "—";
    renderEvents(data.events || []);
    if ((!data.events || data.events.length === 0) && currentDocId) {
      setEventsLoading();
      loadEventsByDocId(currentDocId);
    }

    const st = (data.statusLabel || data.statusCode || "").toString();
    document.getElementById("status").innerText = st
      ? `✅ Найдено (быстрый режим). Статус: ${st}.`
      : "✅ Данные из PTS загружены (быстрый режим).";

    updateStatusBadge(data.statusLabel, data.statusCode);
    renderEvakCard(evakData);
    renderKedenCard(data.keden_kz || null);
    maybeAutoVinFrom(siteData);
    compareData();
    loadPhotos();
  })
  .catch(() => {
    document.getElementById("status").innerText = "❌ Ошибка при запросе /api/pts/by_number_fast.";
  });
}

function pickDocFromList(matches) {
  const status = document.getElementById("status");
  const list = matches.map(m => {
    const dt = (m.docDate || "").split("T")[0] || "—";
    const label = `${m.docNumber || "—"} | ${m.statusName || m.statusCode || "—"} | ${dt}`;
    return `<li><a href="#" class="pick-doc" data-id="${m.id}">${escapeHtml(label)}</a></li>`;
  }).join("");
  status.innerHTML = `Найдено несколько документов:<ul>${list}</ul>`;

  // по клику загружаем карточку (любой режим)
  document.querySelectorAll(".pick-doc").forEach(a => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const id = a.getAttribute("data-id");
      status.textContent = "⏳ Загружаем выбранный документ...";
      // HTML-режим:
      ApiFetch("/parse_site", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ url: `https://pts.gov.kz/compliencedocument/sbkts/${id}` })
      })
      .then(r => r.json())
      .then(data => {
        siteData = data.fields || {};
        evakData = data.evak || null;
        currentDocId = data.docId || id;
        document.getElementById("docIdView").innerText = currentDocId || "—";
        renderEvakCard(evakData);
        renderKedenCard(data.keden_kz || null);
        maybeAutoVinFrom(siteData);
        compareData();
        status.textContent = "✅ Данные загружены.";
      })
      .catch(() => status.textContent = "❌ Ошибка при загрузке карточки.");
    });
  });
}


function fetchFromTechReg() {
  const num = (document.getElementById("techregNumber").value || "").trim();
  if (!num) return;

  document.getElementById("status").innerText = "⏳ Загружаем данные из TechReg...";

  ApiFetch("/api/techreg/sbkts/fields", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ num })
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      document.getElementById("status").innerText = "❌ " + data.error;
      return;
    }
    pdfData = data.fields || data;
    const trStatus = (pdfData && (pdfData['Статус'] || pdfData['Статус TechReg'])) || '';
    updateTrBadge(trStatus);
    document.getElementById("status").innerText = "✅ Данные TechReg загружены.";
    maybeAutoVinFrom(pdfData);
    compareData();
  })
  .catch(() => {
    document.getElementById("status").innerText = "❌ Ошибка при получении данных из TechReg.";
  });
}

function closePhotoModal() {
  document.getElementById("photoModal").style.display = "none";
}

function prevPhoto() {
  if (!photoItems.length) return;
  photoIndex = (photoIndex - 1 + photoItems.length) % photoItems.length;
  openPhotoModal(photoIndex);
}

function nextPhoto() {
  if (!photoItems.length) return;
  photoIndex = (photoIndex + 1) % photoItems.length;
  openPhotoModal(photoIndex);
}

// стрелки влево/вправо и Esc
window.addEventListener("keydown", (e) => {
  const modalOpen = document.getElementById("photoModal").style.display === "block";
  if (!modalOpen) return;
  if (e.key === "ArrowLeft") prevPhoto();
  if (e.key === "ArrowRight") nextPhoto();
  if (e.key === "Escape") closePhotoModal();
});

async function downloadAllPhotos() {
  if (!currentDocId) {
    alert("Сначала загрузите документ.");
    return;
  }

  const r = await ApiFetch("/photos/zip", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    // лучше передавать уже найденные items — это ускорит и избежит повторного Selenium
    body: JSON.stringify({ docId: currentDocId, items: photoItems || [] })
  });

  const ct = (r.headers.get("content-type") || "").toLowerCase();
  if (!r.ok || !ct.includes("application/zip")) {
    // пытаемся показать человеческую ошибку
    let msg = "Сервер не вернул ZIP.";
    try { const j = await r.json(); if (j && (j.error || j.message)) msg = j.error || j.message; } catch {}
    alert("❌ " + msg);
    return;
  }

  const blob = await r.blob();
  const url  = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `photos_${currentDocId}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
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


function checkVin() {
  const el = document.getElementById("vinInput");
  const vin = (el.value || "").trim().toUpperCase();

  // Базовая проверка перед отправкой
  const vinRe = /^[A-HJ-NPR-Z0-9]{17}$/i;
  if (!vinRe.test(vin)) {
    setVinResult("❌ Введите корректный VIN (17 символов A-Z/0-9; без I,O,Q).", true);
    return;
  }

  setVinResult("⏳ Проверяем VIN на evak.online...", false);

  ApiFetch("/check_vin", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ vin })
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        setVinResult("❌ " + data.error, true);
        return;
      }
      if (!data.found) {
        setVinResult("⚠️ " + (data.message || "Данных по VIN не найдено."), true);
        return;
      }

      // Красивый вывод
      const rows = [];
      const d = data.data || {};
      rows.push(`<tr><th>VIN</th><td>${escapeHtml(d["VIN"] || "")}</td></tr>`);
      rows.push(`<tr><th>Дата регистрации в системе</th><td>${escapeHtml(d["Дата регистрации в системе"] || "")}</td></tr>`);
      rows.push(`<tr><th>Первичное обращение</th><td>${escapeHtml(d["Первичное обращение"] || "")}</td></tr>`);
      rows.push(`<tr><th>Модель</th><td>${escapeHtml(d["Модель"] || "")}</td></tr>`);

      const blockHtml = (data.block || []).map(escapeHtml).join("<br>");
      const html = `
        <div class="vin-card">
          <div class="vin-card__title">✅ Найдено на evak.online</div>
          <table class="vin-table">
            <tbody>${rows.join("")}</tbody>
          </table>
          <details class="vin-raw"><summary>Показать исходный блок</summary><div>${blockHtml}</div></details>
        </div>
      `;
      setVinResult(html, false, true);
    })
    .catch(() => setVinResult("❌ Ошибка запроса к /check_vin.", true));
}

function setVinResult(text, isError = false, isHtml = false) {
  const box = document.getElementById("vinResult");
  if (!box) return;
  box.className = "vin-result " + (isError ? "vin-result--error" : "vin-result--ok");
  box.innerHTML = isHtml ? text : escapeHtml(text);
}
function escapeHtml(s) {
  return (s ?? "").toString().replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
function renderEvakCard(evak) {
  const box = document.getElementById("vinResult");
  if (!box) return;
  if (!evak) {
    // ничего не показываем — не критично
    return;
  }
  if (evak.error) {
    setVinResult("❌ " + evak.error, true);
    return;
  }
  if (evak.found === false) {
    setVinResult("⚠️ " + (evak.message || "Данных по VIN не найдено."), true);
    return;
  }
  const d = evak.data || {};
  const rows = [];
  rows.push(`<tr><th>VIN</th><td>${escapeHtml(d["VIN"] || "")}</td></tr>`);
  rows.push(`<tr><th>Дата регистрации в системе</th><td>${escapeHtml(d["Дата регистрации в системе"] || "")}</td></tr>`);
  rows.push(`<tr><th>Первичное обращение</th><td>${escapeHtml(d["Первичное обращение"] || "")}</td></tr>`);
  rows.push(`<tr><th>Модель</th><td>${escapeHtml(d["Модель"] || "")}</td></tr>`);
  const blockHtml = (evak.block || []).map(escapeHtml).join("<br>");
  const html = `
    <div class="vin-card">
      <div class="vin-card__title">✅ Найдено на evak.online</div>
      <table class="vin-table"><tbody>${rows.join("")}</tbody></table>
      <details class="vin-raw"><summary>Показать исходный блок</summary><div>${blockHtml}</div></details>
    </div>`;
  setVinResult(html, false, true);
}

function setKedenResult(text, isError = false, isHtml = false) {
  const box = document.getElementById("kedenResult");
  if (!box) return;
  box.className = "notice vin-result " + (isError ? "vin-result--error" : "vin-result--ok");
  box.innerHTML = isHtml ? text : escapeHtml(text);
}

function renderKedenCard(res) {
  const box = document.getElementById("kedenResult");
  if (!box || !res) return;

  if (res.error) {
    setKedenResult("❌ " + res.error, true);
    return;
  }
  if (res.found === false) {
    setKedenResult("⚠️ " + (res.message || "Данные по VIN не найдены на keden.kgd.gov.kz."), true);
    return;
  }

  const decls = res.declarations || [];
  const raw = decls[0] || res.data || {};
  const rows = [
    ["Дата поиска",          raw.searchDate],
    ["Номер декларации",     raw.declarationNumber],
    ["Таможенный пост",      raw.customsOfficeName],
    ["Вышестоящий орган",    raw.parentCustomsOfficeName],
    ["Марка",                raw.vehicleMkDescription],
    ["Модель",               raw.vehicleModel],
    ["Дата выпуска",         raw.vehicleIssueDate],
    ["Объем двигателя, см³", raw.vehicleEngineCapacityInCm3],
    ["Номер двигателя",      raw.vehicleEngineNumber],
    ["Номер кузова",         raw.vehicleMtcBody],
    ["VIN код",              raw.vehicleVinCode],
    ["Тип декларации",       raw.declarationTypeName],
  ].map(([k, v]) =>
    `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(v || "—")}</td></tr>`
  ).join("");

  const extra = decls.length > 1
    ? `<details class="vin-raw"><summary>Все декларации (${decls.length})</summary><pre>${escapeHtml(JSON.stringify(decls, null, 2))}</pre></details>`
    : `<details class="vin-raw"><summary>Сырые данные API</summary><pre>${escapeHtml(JSON.stringify(decls[0] || {}, null, 2))}</pre></details>`;

  const html = `
    <div class="vin-card">
      <div style="margin-bottom:6px; color:#2f855a;">✅ Найдено на keden.kgd.gov.kz</div>
      <table class="kv"><tbody>${rows}</tbody></table>
      ${extra}
    </div>`;
  setKedenResult(html, false, true);
}

function setEoknoResult(text, isError = false, isHtml = false) {
  const box = document.getElementById("eoknoResult");
  if (!box) return;
  box.className = "vin-result " + (isError ? "vin-result--error" : "vin-result--ok");
  box.innerHTML = isHtml ? text : escapeHtml(text);
}

function renderEoknoCard(res) {
  const box = document.getElementById("eoknoResult");
  const wrapper = document.getElementById("eoknoWrapper");
  if (!box || !res) return;

  // показываем карточку eokno только при реальном found=true
  if (!res.found) return;

  if (wrapper) wrapper.style.display = "";

  // Красивые строки
  const d = res.data || {};
  const rows = [];
  rows.push(`<tr><th>VIN</th><td>${escapeHtml(res.vin || "")}</td></tr>`);
  rows.push(`<tr><th>№ таможенной декларации</th><td>${escapeHtml(d["№ таможенной декларации"] || "")}</td></tr>`);
  rows.push(`<tr><th>Орган (ДГД)</th><td>${escapeHtml(d["Орган (ДГД)"] || "")}</td></tr>`);
  rows.push(`<tr><th>Описание ТС</th><td>${escapeHtml(d["Описание ТС"] || "")}</td></tr>`);
  rows.push(`<tr><th>Дата поиска</th><td>${escapeHtml(d["Дата поиска"] || "")}</td></tr>`);

  const html = `
    <div class="vin-card">
      <div class="vin-card__title">✅ Найдено на eokno.gov.kz (таможенная очистка)</div>
      <table class="vin-table"><tbody>${rows.join("")}</tbody></table>
      <details class="vin-raw">
        <summary>Подробнее</summary>
        <div>Источник ответа: ${escapeHtml(res.source || "—")}</div>
      </details>
    </div>
  `;
  setEoknoResult(html, false, true);
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

  ApiFetch("/parse_pdf", {
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
  
    ApiFetch("/parse_pdf_file", {
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
    "Шины (типоразмер)", "- шины передние", "- шины задние",
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
  checkEvakVsSbKtsDates();


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
    // Колея — показать "см. ниже"
    if (key === "Колея передних/задних колес, мм" && typeof siteVal === "object") {
      const rowId = makeRowId(key);
      const row = document.createElement("tr");
      row.id = rowId;
      row.innerHTML = `<td>${key}</td><td colspan="3" style="font-style:italic;">см. ниже</td>`;
      tbody.appendChild(row);
      continue;
    }

    // Шины — показать "см. ниже"
    if (key === "Шины (типоразмер)" && typeof siteVal === "object") {
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
    //КОЛЕЯ
    if (key === "- колея передних") {
      siteVal = siteData["Колея передних/задних колес, мм"]?.["передних"] ?? "";
      pdfVal  = pdfData ["Колея передних/задних колес, мм"]?.["передних"] ?? "";
    }
    if (key === "- колея задних") {
      siteVal = siteData["Колея передних/задних колес, мм"]?.["задних"] ?? "";
      pdfVal  = pdfData ["Колея передних/задних колес, мм"]?.["задних"] ?? "";
    }

    //ШИНЫ
    if (key === "- шины передние") {
      siteVal = siteData["Шины (типоразмер)"]?.["передние"] ?? "";
      pdfVal  = pdfData ["Шины (типоразмер)"]?.["передние"] ?? "";
    }
    if (key === "- шины задние") {
      siteVal = siteData["Шины (типоразмер)"]?.["задние"] ?? "";
      pdfVal  = pdfData ["Шины (типоразмер)"]?.["задние"] ?? "";
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

function checkEvakVsSbKtsDates() {
  if (!evakData || !evakData.data) return;

  // Дата СБКТС: предпочтительно из PDF, иначе с сайта
  const sbkts = toYMD(
    (pdfData && pdfData["Дата оформления"]) ||
    (siteData && siteData["Дата оформления"]) ||
    ""
  );

  // Даты EVAK
  const evakReg = toYMD(evakData.data["Дата регистрации в системе"] || "");
  const evakFirst = toYMD(evakData.data["Первичное обращение"] || "");

  if (!sbkts) return; // нечего сравнивать
  const evakCandidates = [evakReg, evakFirst].filter(Boolean);
  if (evakCandidates.length === 0) return;

  // Берём самую раннюю дату со стороны EVAK
  const evakMin = evakCandidates.sort()[0]; // строки YYYYMMDD сравниваются лексикографически

  // ❗ Правило: СБКТС не может быть раньше EVAK
  if (evakMin && sbkts < evakMin) {
    const human = (ymd) => ymd ? `${ymd.slice(6,8)}.${ymd.slice(4,6)}.${ymd.slice(0,4)}` : "";
    const msg = `Документ СБКТС не может быть оформлен раньше, чем кнопка SOS EVAK.
СБКТС: ${human(sbkts)} · EVAK: ${human(evakMin)}`;
    appendErrorForField("Дата оформления", msg); // якорь на строку "Дата оформления"
  }
}


function showAllErrorsBlock(errorFields) {
  const wrap = document.getElementById("allErrors");
  const list = document.getElementById("errorAccordionList");
  const countEl = document.getElementById("errorAccordionCount");
  if (!wrap || !list || !countEl) return;

  const items = Object.entries(errorFields)
    .filter(([_, v]) => v)
    .map(([k, v]) => `<li><a href="#" onclick="scrollToRow('${makeRowId(k)}');return false;"><b>${k}:</b></a> ${v}</li>`)
    .join("");

  if (!items) { wrap.style.display = "none"; return; }
  list.innerHTML = items;
  countEl.textContent = Object.values(errorFields).filter(Boolean).length;
  wrap.style.display = "block";
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
    // Экранируем каждый элемент и соединяем <br>
    return val.map(v => escapeHtml(v)).join("<br>");
  }
  if (val && typeof val === "object") {
    // JSON → экранируем целиком
    return escapeHtml(JSON.stringify(val));
  }
  return escapeHtml(val ?? "");
}

function clearComparison() {
  // память
  siteData = null;
  pdfData = null;
  evakData = null;
  currentDocId = "";
  photoItems = [];
  photoIndex = 0;
  errorFields = {};
  decisionInFlight = false;
  lastDecisionKey = "";      


  // таблица и статусы
  document.getElementById("comparisonBody").innerHTML = "";
  document.getElementById("finalResult").innerText = "";
  document.getElementById("status").innerText = "🧹 Данные очищены.";

  // инпуты
  const siteUrlEl = document.getElementById("siteUrl");
  if (siteUrlEl) siteUrlEl.value = "";
  const pdfUrlEl = document.getElementById("pdfUrl");
  if (pdfUrlEl) pdfUrlEl.value = "";
  const techregEl = document.getElementById("techregNumber");
  if (techregEl) techregEl.value = "";
  const ptsEl = document.getElementById("ptsNumber");
  if (ptsEl) ptsEl.value = "";
  const vinEl = document.getElementById("vinInput");
  if (vinEl) vinEl.value = "";

  // evak карточка
  const vinBox = document.getElementById("vinResult");
  if (vinBox) { vinBox.className = "vin-result"; vinBox.innerHTML = ""; }

  resetResultBox("customsResult");

  // keden — сброс в начальное состояние с подсказкой
  const kedenBox = document.getElementById("kedenResult");
  if (kedenBox) { kedenBox.className = "vin-result notice"; kedenBox.innerHTML = "⏳ Ожидание VIN..."; }

  // eokno — прячем, показывается только при found=true
  const eoknoWrapper = document.getElementById("eoknoWrapper");
  if (eoknoWrapper) eoknoWrapper.style.display = "none";
  const eoknoBox2 = document.getElementById("eoknoResult");
  if (eoknoBox2) { eoknoBox2.className = "vin-result"; eoknoBox2.innerHTML = ""; }

  resetCustomsManual();
  resetErrorsAccordion();   // 👈 добавить ЭТО
  resetPhotos();
  resetDecisionSection();
  
  // DocId и причины отказа
  const docIdView = document.getElementById("docIdView");
  if (docIdView) docIdView.textContent = "—";
  const rejectMsg = document.getElementById("rejectMsg");
  if (rejectMsg) rejectMsg.value = "";

  // Ошибки — учитываем, что у вас вёрстка могла задвоить блок
  // document.querySelectorAll("#allErrors").forEach(div => { div.style.display = "none"; div.innerHTML = ""; });

  // Фото
  const grid = document.getElementById("photoGrid");
  if (grid) grid.innerHTML = "";
  const phStatus = document.getElementById("photosStatus");
  if (phStatus) phStatus.textContent = "";

  // Модалка на всякий случай
  const modal = document.getElementById("photoModal");
  if (modal) modal.style.display = "none";

  const ep = document.getElementById("eventsPanel");
  if (ep) ep.innerHTML = '<div class="events-empty">События будут показаны здесь после загрузки документа.</div>';

  resetStatusBadge();
  resetBadges();

}

function resetResultBox(id) {
  const el = document.getElementById(id);
  if (!el) return;
  // вернуть в «пустое» состояние
  el.className = "vin-result";
  el.innerHTML = "";
}

function resetErrorsAccordion() {
  const wrap    = document.getElementById("allErrors");
  const list    = document.getElementById("errorAccordionList");
  const countEl = document.getElementById("errorAccordionCount");
  const content = document.getElementById("errorAccordionContent");
  const arrow   = document.getElementById("errorAccordionArrow");

  if (list) list.innerHTML = "";
  if (countEl) countEl.textContent = "0";
  if (content) content.style.display = "none";
  if (arrow) arrow.innerHTML = "&#9654;"; // свернуто
  if (wrap) wrap.style.display = "none";
}

function resetPhotos() {
  photoItems = [];
  photoIndex = 0;
  const grid   = document.getElementById("photoGrid");
  const status = document.getElementById("photosStatus");
  if (grid) grid.innerHTML = "";
  if (status) status.textContent = "";
  // если модалка вдруг открыта — закрыть
  const modal = document.getElementById("photoModal");
  if (modal) modal.style.display = "none";
}

function resetDecisionSection() {
  decisionInFlight = false;
  const ds = document.getElementById("decisionStatus");
  if (ds) { ds.textContent = ""; ds.style.color = "#444"; }

  // 🧹 поле причины отклонения (и при желании комментарий к одобрению)
  const rej = document.getElementById("rejectMsg");
  if (rej) rej.value = "";
  const appr = document.getElementById("approveMsg");
  if (appr) appr.value = "";

  // снять возможную блокировку
  const btnApprove = document.getElementById("btnApprove");
  const btnReject  = document.getElementById("btnReject");
  [btnApprove, btnReject].forEach(b => b && (b.disabled = false));
}

function resetCustomsManual() {
  // инпут VIN (ручной)
  const vinManual = document.getElementById("vinInputManual");
  if (vinManual) vinManual.value = "";

  // карточка результата customs.gov.ru
  const box = document.getElementById("vinManualResult");
  if (box) {
    box.className = "vin-result"; // вернуть базовый класс
    box.innerHTML = "";           // очистить содержимое
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

function toYMD(dateStr) {
  if (!dateStr) return "";
  // отбрасываем время
  dateStr = String(dateStr).split(/\s+/)[0];
  return normalizeDate(dateStr); // уже даёт 'YYYYMMDD' либо пусто
}

/** Удобно дописывать ошибку к существующему полю (не ломая якорь "Дата оформления") */
function appendErrorForField(fieldName, msg) {
  if (!msg) return;
  const prev = errorFields[fieldName] || "";
  const next = prev ? (prev + (prev.endsWith('.') ? ' ' : '. ') + msg) : msg;
  errorFields[fieldName] = next;

  // обновим строку в таблице, если уже отрисована
  const row = document.getElementById(makeRowId(fieldName));
  if (row) {
    row.classList.add('mismatch');
    // 5-й столбец — "Описание ошибки"
    const errCell = row.children && row.children[4];
    if (errCell) errCell.textContent = next;
  }

  // перерисуем сводку ошибок
  showAllErrorsBlock(errorFields);
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

// --- Нормализация названия лаборатории (убираем формы собственности, кавычки, скобки, коды и т.п.)
function normalizeLabName(s) {
  s = (s || "").toLowerCase();

  // убрать содержимое скобок
  s = s.replace(/[\(\[\{].*?[\)\]\}]/g, " ");

  // ё → е
  s = s.replace(/ё/g, "е");

  // формы собственности / мусорные слова
  const legal = [
    "товарищество с ограниченной ответственностью",
    "общество с ограниченной ответственностью",
    "тоо", "ооо", "зао", "пао", "ао", "ип",
    "llp", "llc", "inc", "corp", "corporation",
    "company", "компания", "фирма"
  ];
  for (const w of legal) {
    const re = new RegExp("\\b" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "g");
    s = s.replace(re, " ");
  }

  // убрать кавычки, коды вида KZ.T.02.2676
  s = s.replace(/["«»„”“]/g, " ").replace(/\b[A-Z]{2}\.[A-Z0-9.]+\b/g, " ");

  // оставить только буквы/цифры, схлопнуть пробелы
  s = s.replace(/[^a-zа-я0-9]/g, " ").replace(/\s+/g, " ").trim();

  return s;
}

// --- Привод по схеме компоновки (fwd/rwd/awd)
function parseDriveFromLayout(s) {
  s = (s || "").toLowerCase();
  if (/(полноприв|4x4|awd)/.test(s)) return "awd";
  if (/(передн[а-я]*\s*привод|fwd)/.test(s)) return "fwd";
  if (/(задн[а-я]*\s*привод|rwd)/.test(s)) return "rwd";
  return "";
}

// --- Парсер колеи из строки/объекта
function parseTrack(val) {
  const out = { front: null, rear: null, frontLead: false, rearLead: false };
  if (!val) return out;

  if (typeof val === "object") {
    if (val["передних"] != null) out.front = parseFloat(String(val["передних"]).replace(",", "."));
    if (val["задних"]   != null) out.rear  = parseFloat(String(val["задних"]).replace(",", "."));
    return out;
  }

  const s = String(val).toLowerCase();
  const parts = s.split(/[\/|]/);
  if (parts[0]) {
    out.front = parseFloat(parts[0].replace(/[^\d.,-]/g, "").replace(",", "."));
    out.frontLead = /ведущ/.test(parts[0]);
  }
  if (parts[1]) {
    out.rear = parseFloat(parts[1].replace(/[^\d.,-]/g, "").replace(",", "."));
    out.rearLead = /ведущ/.test(parts[1]);
  }
  return out;
}

// --- Проверка "ведущих" осей против схемы компоновки (ошибка добавляется, но совпадение чисел не ломаем)
function ensureLeadingConsistency(fieldName, parsed, layoutStr) {
  const drive = parseDriveFromLayout(layoutStr);
  if (!drive) return;

  if (drive === "awd" && !(parsed.frontLead && parsed.rearLead)) {
    appendErrorForField(fieldName, "Схема: полноприводная — ожидаются обе оси как ведущие.");
  } else if (drive === "fwd" && !parsed.frontLead) {
    appendErrorForField(fieldName, "Схема: переднеприводная — ведущей должна быть передняя ось.");
  } else if (drive === "rwd" && !parsed.rearLead) {
    appendErrorForField(fieldName, "Схема: заднеприводная — ведущей должна быть задняя ось.");
  }
}

// --- Извлечь мощность (кВт) и оценить «сколько чисел в поле»
function extractKwValue(s) {
  s = (s || "").toString().replace(',', '.');

  // число перед "кВт"
  const mKw = s.match(/(\d+(?:\.\d+)?)(?=[^\d]{0,10}квт)/i);
  if (mKw) return parseFloat(mKw[1]);

  // иначе первое число до '@' или '('
  const m1 = s.match(/(\d+(?:\.\d+)?)(?=\s*@|\s*\()/);
  if (m1) return parseFloat(m1[1]);

  // совсем fallback — первое число
  const m2 = s.match(/(\d+(?:\.\d+)?)/);
  return m2 ? parseFloat(m2[1]) : NaN;
}

function countAllNumbers(s) {
  s = (s || "").toString().replace(',', '.');
  const nums = s.match(/\d+(?:\.\d+)?/g) || [];
  return nums.length;
}

function normalizeDocNumber(s) {
  return (s ?? "").toString().toUpperCase().replace(/\s+/g, "").replace(/[^\w]+/g, "");
}

function fuzzyMatch(a, b, fieldName = "") {
  a = (a ?? "").toString().trim();
  b = (b ?? "").toString().trim();

  // Номер документа — сравнение без пробелов/точек/дефисов
  if (fieldName && fieldName.toLowerCase().includes("номер документа")) {
    return normalizeDocNumber(a) === normalizeDocNumber(b);
  }

  // Списки чисел/размеров "x/y/z" или через запятую
  if ((a.includes('/') || a.includes(',')) && (b.includes('/') || b.includes(','))) {
    const A = normalizeNumberList(a), B = normalizeNumberList(b);
    if (A.length === B.length && A.every((v,i)=>v===B[i])) return true;
  }

  // Пуста/дефис — считать равным
  if ((a === "-" && b === "") || (a === "" && b === "-")) return true;

  // ЭКОЛОГИЧЕСКИЙ КЛАСС — извлекаем цифры/слова
  if (fieldName && fieldName.toLowerCase().includes("экологический класс")) {
    const na = extractEcoClassNum(a), nb = extractEcoClassNum(b);
    if (na && nb && na === nb) return true;
  }

  // Оба пустые
  if (!a && !b) return true;
  if (!a || !b) return false;

  // Даты → YYYYMMDD
  const naDate = normalizeDate(a), nbDate = normalizeDate(b);
  if (naDate && nbDate && naDate.length === 8 && nbDate.length === 8) {
    return naDate === nbDate;
  }

  // Числа с локалями
  const naNum = parseFloat(a.replace(/[^\d.,-]/g, '').replace(',', '.'));
  const nbNum = parseFloat(b.replace(/[^\d.,-]/g, '').replace(',', '.'));
  if (!isNaN(naNum) && !isNaN(nbNum)) {
    return Math.abs(naNum - nbNum) < 1e-2;
  }

  // Строки без небуквенных символов
  const ca = a.toLowerCase().replace(/[^а-яa-z0-9]/gi, '').trim();
  const cb = b.toLowerCase().replace(/[^а-яa-z0-9]/gi, '').trim();
  if (ca.startsWith(cb) || cb.startsWith(ca)) return true;
  return ca === cb;
}

// Статус сессии ePTS через расширение
async function checkTokenStatus() {
  console.log('[MODULAB DEBUG] checkTokenStatus started');
  const statusEl = document.getElementById('tokenStatus');
  if (!statusEl) return;
  statusEl.textContent = '⏳ Проверяем авторизацию в ePTS...';
  statusEl.style.color = 'black';
  setParseButtonEnabled(false);

  try {
    await eptsSetToken();
    const r = await callExtension('EPTS_CHECK');  // {ok, hasBearer, bearerAuth, cookieAuth, code?, error?}

    const hasBearer  = !!r?.hasBearer;
    const bearerAuth = !!r?.bearerAuth;
    const cookieAuth = !!r?.cookieAuth;
    const hasAuth    = bearerAuth || cookieAuth;

    const hint = [
      `cookies ${cookieAuth ? '✓' : '✗'}`,
      hasBearer ? `token ${bearerAuth ? '✓' : '✗'}` : 'token —'
    ].join(' · ');

    if (hasAuth) {
      statusEl.textContent = `✅ Вход выполнен в ePTS (${hint})`;
      statusEl.style.color = 'green';
      setParseButtonEnabled(true);
      return;
    }
    if (r?.code === 401 || r?.code === 403) {
      statusEl.textContent = `❌ Не выполнен вход в ePTS (${hint}). Нажмите «Войти» и авторизуйтесь.`;
      statusEl.style.color = 'darkred';
      setParseButtonEnabled(true);
      return;
    }
    if (hasBearer && !bearerAuth && !cookieAuth) {
      statusEl.textContent = `⚠️ Токен найден, но сессия ePTS неактивна (${hint}). Откройте pts.gov.kz и войдите.`;
      statusEl.style.color = 'darkorange';
      setParseButtonEnabled(true);
      return;
    }
    if (r?.error) {
      statusEl.textContent = `❌ Ошибка проверки: ${r.error}`;
      statusEl.style.color = 'darkred';
      setParseButtonEnabled(true);
      return;
    }
    statusEl.textContent = `⚠️ Не удалось определить статус (${hint}). Откройте pts.gov.kz и войдите.`;
    statusEl.style.color = 'darkorange';
    setParseButtonEnabled(true);
  } catch {
    statusEl.textContent = '❌ Расширение недоступно';
    statusEl.style.color = 'darkred';
    setParseButtonEnabled(true);
  }
}


function scrollToRow(rowId) {
  const row = document.getElementById(rowId);
  if (!row) return;

  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.add("highlight-error-row");
  setTimeout(() => row.classList.remove("highlight-error-row"), 1500);
}


// Автоматическая проверка токена каждые 60 секунд
setInterval(checkTokenStatus, 60_000);
window.addEventListener('focus', checkTokenStatus);

async function refreshToken() {   // теперь просто перерисовывает статус расширения
  return checkTokenStatus();
}

function callExtension(type, payload = {}) {
  return new Promise((resolve, reject) => {
    if (!window.crypto?.randomUUID) return reject(new Error('NO_UUID'));
    const id = crypto.randomUUID();
    const to = setTimeout(() => {
      window.removeEventListener('message', onMsg);
      reject(new Error('EXT_TIMEOUT'));
    }, 15000);
    function onMsg(ev) {
      const d = ev.data || {};
      if (d.source !== 'MODULAB_EXTENSION' || d.id !== id) return;
      clearTimeout(to);
      window.removeEventListener('message', onMsg);
      resolve(d.response);
    }
    window.addEventListener('message', onMsg);
    console.log('[MODULAB DEBUG] about to postMessage:', { source: 'MODULAB_PAGE', id, type, ...payload });
    window.postMessage({ source: 'MODULAB_PAGE', id, type, ...payload }, window.origin);
  });
}

// чтобы не переписывать все вызовы extCall, просто алиас:
const extCall = callExtension;


async function connectPts() {
  const statusEl = document.getElementById("tokenStatus");
  try {
    if (statusEl) { statusEl.textContent = "Открываю ПТС..."; statusEl.style.color = "orange"; }

    const t = getParserToken();
    if (!t) {
      alert("Сначала авторизуйтесь в приложении (нет modulab_token).");
      return;
    }

    // передаём токен приложения в расширение
    await callExtension("EPTS_SET_TOKEN", { parserToken: t });
    // просим расширение проверить/подключить ПТС (откроет вкладку, дождётся логина)
    const res = await callExtension("EPTS_CHECK");


    if (res && res.ok) {
      if (statusEl) { statusEl.textContent = "✅ Подключено"; statusEl.style.color = "green"; }
      refreshToken(); // перерисуем бейдж /check_token_status на бэке (не мешает, работает в обоих режимах)
    } else {
      throw new Error(res?.error || "Не удалось подключить ПТС");
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = "❌ Нет соединения с расширением"; statusEl.style.color = "darkred"; }
    alert("Нужно установить расширение «PTS Connector», затем повторить.\n" + (e?.message || e));
  }
}

function checkKedenManual() {
  const vin = (document.getElementById("kedenVinInput").value || "").trim().toUpperCase();
  const vinRe = /^[A-HJ-NPR-Z0-9]{17}$/i;
  if (!vinRe.test(vin)) {
    setKedenResult("❌ Введите корректный VIN (17 символов A-Z/0-9; без I,O,Q).", true);
    return;
  }

  setKedenResult("⏳ Проверяем VIN на keden.kgd.gov.kz...", false);

  ApiFetch("/keden/check", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ vin })
  })
  .then(r => r.json())
  .then(res => renderKedenCard(res))
  .catch(() => setKedenResult("❌ Ошибка запроса к /keden/check.", true));
}

function checkCustomsManual() {
  const vin = (document.getElementById("vinInputManual").value || "").trim().toUpperCase();
  const vinRe = /^[A-HJ-NPR-Z0-9]{17}$/i;
  if (!vinRe.test(vin)) {
    setVinManualResult("❌ Введите корректный VIN (17 символов A-Z/0-9; без I,O,Q).", true);
    return;
  }

  setVinManualResult("⏳ Проверяем VIN на customs.gov.ru...", false);

  ApiFetch("/customs/check", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ vin })
  })
  .then(r => r.json())
  .then(res => renderCustomsCard(res))
  .catch(() => setVinManualResult("❌ Ошибка запроса к /customs/check.", true));
}

function processNewToken(token) {
  localStorage.setItem('modulab_token', token);
  history.replaceState({}, '', location.pathname);
  verifyToken(token);
}

function checkExistingSession() {
  const saved = localStorage.getItem('modulab_token');
  if (!saved) return showTokenInput();
  verifyToken(saved);
}

function initApplication() {
  const app    = document.getElementById('app');
  const tokenS = document.getElementById('token-section');
  if (app)    app.style.display = 'block';
  if (tokenS) tokenS.style.display = 'none';
}

function verifyToken(token) {
  return ApiFetch('/verify_token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token })
  })
  .then(r => r.json().then(j => ({ ok: r.ok, json: j })))
  .then(({ ok, json }) => {
    const good = ok && String(json.status).toLowerCase() === 'success' && json.user;
    if (good) {
      localStorage.setItem('modulab_token', token);
      initApplication?.();
    } else {
      showTokenInput?.();
    }
  })
  .catch(() => showTokenInput?.());
}


function showTokenInput() {
  const app    = document.getElementById('app');
  const tokenS = document.getElementById('token-section');
  if (app)    app.style.display = 'none';
  if (tokenS) tokenS.style.display = 'block';
}


function submitManualToken() {
  const token = document.getElementById('manual-token').value;
  if (!token) return;

  verifyToken(token);
}

function setVinManualResult(htmlOrText, isError=false) {
  const box = document.getElementById("vinManualResult");
  if (!box) return;
  if (typeof htmlOrText === "string") {
    box.innerHTML = `<div class="vin-card ${isError ? "error" : ""}">${htmlOrText}</div>`;
  } else {
    box.innerHTML = htmlOrText;
  }
}

function renderCustomsCard(res) {
  const box = document.getElementById("vinManualResult");
  if (!box) return;

  if (res.error) {
    box.innerHTML = `<div class="vin-card error">❌ ${escapeHtml(res.error)}</div>`;
    return;
  }
  if (res.found === false) {
    box.innerHTML = `<div class="vin-card warn">⚠️ ${escapeHtml(res.message || "Данные по VIN не найдены на customs.gov.ru.")}</div>`;
    return;
  }

  const d = res.data || {};
  const country = res.country || {};
  const countryRow = d["Страна выпуска"] || (country.code ? `${country.code}${country.name ? " — " + country.name : ""}` : "—");

  box.innerHTML = `
    <div class="vin-card">
      <div style="margin-bottom:6px; color:#2f855a;">Запись найдена на customs.gov.ru</div>
      <table class="kv">
        <tr><th>VIN</th><td>${escapeHtml(d["Номер VIN"] || res.vin || "")}</td></tr>
        <tr><th>Модель</th><td>${escapeHtml(d["Модель"] || "")}</td></tr>
        <tr><th>Номер кузова</th><td>${escapeHtml(d["Номер кузова"] || "")}</td></tr>
        <tr><th>Номер шасси</th><td>${escapeHtml(d["Номер шасси"] || "—")}</td></tr>
        <tr><th>Дата выпуска в свободное обращение</th><td>${escapeHtml(d["Дата выпуска в свободное обращение"] || "")}</td></tr>
        <tr><th>Страна выпуска</th><td>${escapeHtml(countryRow)}</td></tr>
        <tr><th>Источник ответа</th><td>customs.gov.ru/cars</td></tr>
      </table>
    </div>
  `;
}
