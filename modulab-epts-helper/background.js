// === Разрешённые origin'ы твоего фронта ===
const ALLOWED_ORIGINS = [
  'https://modulab.kz',
  'http://localhost:5173',
  'http://127.0.0.1:5000',
  'http://localhost:5000',
  'http://127.0.0.1:8080',   // +
  'http://localhost:8080',   // +
  'http://192.168.16.90:5000'
];

const PROCESS_URL = 'https://pts.gov.kz/api/compliencedocument/processRequest';

// === Белый список эндпоинтов ePTS, которые реально используешь ===
const ALLOWED_ENDPOINTS = [
  // базовые
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetList(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/Get(?:\?.*)?$/i,

  // детали
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetElectricalMachineDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetPowerStorageDeviceDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleLayoutDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleLayoutsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleClutchDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetTransmissionTypesByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetEngineDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleWeightDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleDimensionDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleHightDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetWheelbaseMeasuresByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleAxleDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleSeatDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleSuspensionDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleRunningGearDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleBodyworkDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleSteeringDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleBrakingSystemDetailsByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleTyreKindInfosByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/ComplienceDocument\/GetVehicleEquipmentInfosByDocId(?:\?.*)?$/i,
  /^https:\/\/pts\.gov\.kz\/api\/complienceDocument\/processRequest(?:\?.*)?$/i,


];

function isAllowedUrl(url) {
  if (!url) return { ok: false, reason: 'empty_url' };
  const ok = ALLOWED_ENDPOINTS.some((re) => re.test(url));
  return ok ? { ok: true } : { ok: false, reason: 'endpoint_not_allowed' };
}

// Bearer в сессии (RAM)
async function getBearer() {
  const { eptsBearer } = await chrome.storage.session.get('eptsBearer');
  return eptsBearer || null;
}
async function setBearer(token) {
  if (typeof token !== 'string' || !token) throw new Error('bad_token');
  await chrome.storage.session.set({ eptsBearer: token });
}
async function clearBearer() {
  await chrome.storage.session.remove('eptsBearer');
}

async function eptsFetchOnce({ url, method = 'GET', headers = {}, body, useBearer = true }) {
  const h = new Headers(headers || {});
  const b = useBearer ? await getBearer() : null;
  if (b) h.set('Authorization', `Bearer ${b}`);
  const resp = await fetch(url, {
    method,
    headers: h,
    body: body ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined,
    credentials: 'include',      // тащим куки
  });
  return resp;
}

async function fetchViaEptsTab(payload) {
  const tabs = await chrome.tabs.query({
    url: ['https://pts.gov.kz/*', 'https://www.pts.gov.kz/*']
  });
  if (!tabs?.length) return { ok: false, error: 'epts_tab_not_found' };
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabs[0].id, { type: 'EPTS_FETCH_IN_PAGE', ...payload }, (res) => {
      const err = chrome.runtime.lastError;
      if (err) resolve({ ok: false, error: err.message });
      else resolve(res);
    });
  });
}


async function checkHealth() {
  const hasBearer = !!(await getBearer());

  const listReq = {
    url: 'https://pts.gov.kz/api/ComplienceDocument/GetList',
    method: 'POST',
    headers: { 'Accept':'application/json', 'Content-Type':'application/json' },
    body: { page: 1, pageSize: 1 }
  };

  async function probe(useBearer) {
    try {
      const resp = await eptsFetchOnce({ ...listReq, useBearer });
      const code = resp.status;
      const ct = (resp.headers.get('content-type') || '').toLowerCase();
      const info = { code, ct, url: resp.url, redirected: resp.redirected };

      if (code === 401 || code === 403) return { ok: false, ...info };

      let looksOk = false;
      if (ct.includes('json')) {
        const j = await resp.clone().json();
        const rootOk =
          Array.isArray(j?.items) ||
          typeof j?.totalCount === 'number' ||
          String(j?.status || '').toLowerCase() === 'ok' ||
          j?.status === 1 || j?.action === 1;
        const d = j?.data;
        const dataOk =
          Array.isArray(d?.items) ||
          typeof d?.totalCount === 'number' ||
          String(d?.status || '').toLowerCase() === 'ok' ||
          d?.status === 1 || d?.action === 1;
        looksOk = rootOk || dataOk;
      } else {
        const t = (await resp.clone().text()).toLowerCase();
        const looksLikeLogin = t.includes('login') || t.includes('вход');
        looksOk = !looksLikeLogin;
      }

      return { ok: (code === 200) && looksOk, ...info };
    } catch (e) {
      return { ok: false, error: String(e?.message || e) };
    }
  }

  const [byBearer, byCookies] = await Promise.all([probe(true), probe(false)]);

  // ← ФОЛБЭК ЧЕРЕЗ ВКЛАДКУ: только здесь
  if (!(byBearer.ok || byCookies.ok)) {
    const page = await fetchViaEptsTab(listReq);
    if (page?.ok && page.status === 200 && typeof page.data === 'object') {
      return { ok: true, code: 200, bearerAuth: false, cookieAuth: true, hasBearer };
    }
  }

  return {
    ok: byBearer.ok || byCookies.ok,
    code: byBearer.ok ? byBearer.code : byCookies.code,
    bearerAuth: byBearer.ok,
    cookieAuth: byCookies.ok,
    hasBearer
  };
}


chrome.runtime.onStartup.addListener(() => chrome.storage.session.remove('eptsBearer'));
chrome.runtime.onInstalled.addListener(() => chrome.storage.session.remove('eptsBearer'));

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  console.log('[MODULAB DEBUG] background received:', msg, 'from:', sender);
  const origin = sender.url ? new URL(sender.url).origin : null;
  if (!ALLOWED_ORIGINS.includes(origin)) {
    sendResponse({ ok: false, error: 'forbidden_origin', origin });
    return true;
  }

  (async () => {
    try {
      switch (msg?.type) {
        case 'EPTS_PING':
          sendResponse({ ok: true, data: 'pong' });
          break;

        case 'EPTS_SET_TOKEN': {
          const parserToken = msg.parserToken || msg.token || null;
          if (parserToken) {
            // Можно хранить, если нужно использовать в других местах,
            // например, при /epts/attach
            await chrome.storage.session.set({ parserToken });
          }
          // Никакого setBearer здесь: parserToken ≠ eptsBearer
          sendResponse({ ok: true });
          break;
        }

        case 'EPTS_CLEAR_TOKEN':
          await clearBearer();
          sendResponse({ ok: true });
          break;

         case 'EPTS_FETCH': {
          const { url, method = 'GET', headers = {}, body } = msg;

          // 💡 проверка, что URL входит в белый список
          const check = isAllowedUrl(url);
          if (!check.ok) {
            sendResponse({ ok: false, error: check.reason || 'endpoint_not_allowed', url });
            break;
          }

          let resp = await eptsFetchOnce({ url, method, headers, body });
          let ct = (resp.headers.get('content-type') || '').toLowerCase();
          let isJson = ct.includes('json');

          if (resp.status === 200 && isJson) {
            const data = await resp.json();
            sendResponse({
              ok: true,
              status: 200,
              headers: Object.fromEntries(resp.headers.entries()),
              data
            });
            break;
          }

          // Фолбэк через вкладку (на случай редиректов / login-страницы)
          const page = await fetchViaEptsTab({ url, method, headers, body });
          sendResponse(
            page?.ok
              ? page
              : { ok: false, status: resp.status, error: page?.error || 'not_json_or_login' }
          );
          break;
        }
            case 'EPTS_DECISION': {
              const { docId, decision, message } = msg;

              if (!docId) {
                sendResponse({ ok: false, error: 'no_docId' });
                break;
              }

              const payload = {
                DocId: docId,
                StatusCode: decision === 'approve' ? 'active' : 'rejected',
                Message: message || ''
              };

              // 1) ПЕРВЫЕЙ попыткой — через вкладку PTS (правильный Origin/Referer + куки)
              const page = await fetchViaEptsTab({
                url: PROCESS_URL,
                method: 'POST',
                headers: {
                  'Accept': 'application/json, text/plain, */*',
                  'Content-Type': 'application/json;charset=UTF-8',
                  'X-Requested-With': 'XMLHttpRequest'
                },
                body: payload
              });

              if (page?.ok && (
                page.data?.status === 1 ||
                page.data?.action === 1 ||
                page.data?.data === true ||
                page.data?.result === true
              )) {
                // успех именно на стороне PTS
                sendResponse({
                  ok: true,
                  status: page.status || 200,
                  data: page.data,
                  via: 'page'
                });
                break;
              }

              // 2) Фолбэк — пробуем из background (если вкладка не нашлась/ошибка)
              let resp = await eptsFetchOnce({
                url: PROCESS_URL,
                method: 'POST',
                headers: {
                  'Accept': 'application/json, text/plain, */*',
                  'Content-Type': 'application/json;charset=UTF-8',
                  'X-Requested-With': 'XMLHttpRequest'
                },
                body: payload
              });

              const status = resp.status;
              const ct = (resp.headers.get('content-type') || '').toLowerCase();
              const isJson = ct.includes('json');

              let data = null;
              let text = '';

              if (isJson) {
                try {
                  data = await resp.clone().json();
                } catch (e) {
                  data = null;
                }
              } else {
                try {
                  text = await resp.clone().text();
                } catch (e) {
                  text = '';
                }
              }

              console.log('[EPTS_DECISION] HTTP response:', {
                status,
                isJson,
                data,
                text
              });

              const okFlag =
                status >= 200 && status < 300 &&
                (
                  data?.status === 1 ||
                  data?.action === 1 ||
                  data?.data === true ||
                  data?.result === true
                );

              if (!okFlag) {
                const errMsg =
                  data?.error ||
                  data?.message ||
                  text ||
                  `decision_http_${status}`;

                sendResponse({
                  ok: false,
                  status,
                  error: errMsg,
                  data
                });
                break;
              }

              sendResponse({
                ok: true,
                status,
                data,
                via: 'background'
              });
              break;
            }
                        // <-- и этой скобки

        case 'EPTS_DEBUG_VALIDATE': {
          const { url } = msg;
          sendResponse(isAllowedUrl(url));
          break;
        }

        case 'EPTS_CHECK':
          sendResponse(await checkHealth());
          break;

        default:
          sendResponse({ ok: false, error: 'unknown_command' });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e?.message || String(e) });
    }
  })();

  return true;
});
