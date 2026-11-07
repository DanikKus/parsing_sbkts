// pts-content.js — грузится на https://pts.gov.kz/*
// Делает: (1) аккуратно шлёт Bearer в SW; (2) выполняет fetch внутри вкладки ePTS по команде из background.

(() => {
  // Защита от двойной инициализации (SPA/перезапуск расширения)
  if (window.__MODULAB_PTS_CS__) return;
  window.__MODULAB_PTS_CS__ = true;

  // ----- чтение токена из среды ePTS -----
  function readBearer() {
    try {
      // Вариант 1: user в localStorage
      const u = JSON.parse(localStorage.getItem('user') || 'null');
      if (u?.token) return u.token;

      // Вариант 2: прямые ключи
      const direct =
        localStorage.getItem('accessToken') || sessionStorage.getItem('accessToken') ||
        localStorage.getItem('token')       || sessionStorage.getItem('token');
      if (direct) return direct;

      // Вариант 3: cookie access_token / token
      const m = document.cookie.match(/(?:^|;\s*)(access_token|token)=([^;]+)/i);
      if (m) return decodeURIComponent(m[2]);
    } catch {}
    return null;
  }

  // ----- безопасная отправка сообщений в SW -----
  function safeSendMessage(msg, cb) {
    // если расширение перезагружено/выключено — просто выходим
    if (!chrome?.runtime?.id) return;

    try {
      chrome.runtime.sendMessage(msg, (res) => {
        const err = chrome.runtime.lastError;
        if (err) {
          // подавляем шум при рестарте/отсутствии приёмника
          if (/context invalidated|receiving end does not exist/i.test(err.message)) return;
          console.warn('sendMessage error:', err.message);
          return;
        }
        cb && cb(res);
      });
    } catch (e) {
      if (/context invalidated/i.test(String(e))) return;
      console.warn('sendMessage threw:', e);
    }
  }

  // ----- периодическая отправка Bearer в SW -----
  function pushBearer() {
    const t = readBearer();
    safeSendMessage(
      t ? { type: 'EPTS_SET_TOKEN', token: t }
        : { type: 'EPTS_CLEAR_TOKEN' }
    );
  }

  let bearerTimer;
  function loopPush() {
    clearTimeout(bearerTimer);
    pushBearer();
    bearerTimer = setTimeout(loopPush, 10000); // раз в 10 сек достаточно
  }
  loopPush();

  // меньше шума, если вкладка не активна
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearTimeout(bearerTimer);
    else loopPush();
  });
  window.addEventListener('pagehide', () => clearTimeout(bearerTimer));
  window.addEventListener('beforeunload', () => clearTimeout(bearerTimer));

  // ----- ОДИН обработчик команды из background: выполнить fetch "внутри ePTS" -----
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || msg.type !== 'EPTS_FETCH_IN_PAGE') return;

    const { url, method = 'GET', headers = {}, body } = msg;

    fetch(url, {
      method,
      headers,
      body: body ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined,
      credentials: 'include', // важное — тащим куки ePTS
    })
      .then(async (resp) => {
        const ct = (resp.headers.get('content-type') || '').toLowerCase();
        let data;
        try {
          data = ct.includes('json') ? await resp.json() : await resp.text();
        } catch {
          data = await resp.text();
        }
        sendResponse({
          ok: true,
          status: resp.status,
          headers: Object.fromEntries(resp.headers.entries()),
          data
        });
      })
      .catch(err => sendResponse({ ok: false, error: String(err?.message || err) }));

    return true; // async response
  });
})();
