// pts-connector/background.js
const API_BASES = ['https://parser.modulab.kz', 'http://127.0.0.1:5000'];

async function openPtsTab() {
  try {
    const { pts_connect_tab } = await chrome.storage.local.get('pts_connect_tab');
    if (pts_connect_tab) {
      await chrome.tabs.update(pts_connect_tab, { active: true, url: 'https://pts.gov.kz/' });
      return;
    }
  } catch {}
  const t = await chrome.tabs.create({ url: 'https://pts.gov.kz/', active: true });
  await chrome.storage.local.set({ pts_connect_tab: t.id });
}

async function getParserToken() {
  const { parserToken } = await chrome.storage.local.get('parserToken');
  return parserToken || '';
}

async function sendToBackend(payload) {
  const tok = await getParserToken();
  if (!tok) throw new Error('Нет токена пользователя (зайдите на parser.modulab.kz).');

  let lastErr;
  for (const base of API_BASES) {
    try {
      const r = await fetch(base + '/epts/attach', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Parser-Token': tok },
        body: JSON.stringify(payload)
      });
      if (r.ok) return true;
      lastErr = new Error(`HTTP ${r.status}`);
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error('Не удалось отправить на бэкенд');
}


async function grabCookies(domain) {
  const list = await chrome.cookies.getAll({ domain });
  const out = {};
  for (const c of list) out[c.name] = c.value;
  return out;
}


async function grabAllPtsCookies() {
  const domains = ['pts.gov.kz', 'epts.gov.kz'];
  const cookiesByDomain = {};
  for (const d of domains) {
    const c = await grabCookies(d);
    if (Object.keys(c).length) cookiesByDomain[d] = c;
  }
  return cookiesByDomain;
}
chrome.runtime.onMessage.addListener((msg, snd, sendResp) => {
  (async () => {
    if (msg?.action === 'connect-pts') {
      await openPtsTab();

      let tries = 0, ok = false, lastErr = null;
      let capturedJwt = null;

      // Слушаем JWT токен
      const jwtListener = (request) => {
        if (request.action === 'jwt-detected') {
          capturedJwt = request.jwt;
          console.log('JWT captured:', capturedJwt?.substring(0, 20) + '...');
        }
      };
      chrome.runtime.onMessage.addListener(jwtListener);

      while (tries++ < 90 && !ok) {
        try {
          const cookiesByDomain = await grabAllPtsCookies();
          
          // Собираем все данные для отправки
          const payload = {};
          
          // Добавляем cookies если есть
          if (Object.keys(cookiesByDomain).length > 0) {
            const allCookies = {};
            for (const domain in cookiesByDomain) {
              Object.assign(allCookies, cookiesByDomain[domain]);
            }
            payload.cookies = allCookies;
          }
          
          // Добавляем JWT если есть
          if (capturedJwt) {
            payload.jwt = capturedJwt;
          }

          // Отправляем только если есть что отправлять
          if (Object.keys(payload).length > 0) {
            await sendToBackend(payload);
            ok = true; 
            break;
          }
        } catch (e) { 
          lastErr = e; 
        }
        await new Promise(r => setTimeout(r, 1000));
      }

      chrome.runtime.onMessage.removeListener(jwtListener);
      
      const resp = { 
        action: 'capture-done', 
        ok, 
        error: lastErr && ('' + (lastErr.message || lastErr)),
        hasJwt: !!capturedJwt,
        hasCookies: ok
      };
      chrome.runtime.sendMessage(resp);
      sendResp(resp);
    }

    // Обработка JWT - просто сохраняем, не отправляем отдельно
    if (msg?.action === 'jwt-detected') {
      // Просто логируем, основной цикл сам отправит
      console.log('JWT detected in background:', msg.jwt?.substring(0, 20) + '...');
      sendResp({ ok: true });
    }

  })();
  return true;
});