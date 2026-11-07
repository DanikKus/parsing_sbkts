// content.js — мост между страницей (modulab) и background

console.log('[MODULAB DEBUG] content.js file loaded on:', window.location.href);

const ALLOWED_PAGE_ORIGINS = [
  'https://modulab.kz',
  'http://localhost:5173',
  'http://127.0.0.1:5000',
  'http://localhost:5000',
  'http://127.0.0.1:8080',
  'http://localhost:8080',
  'http://192.168.16.90:5000',
];

// защита от двойной инициализации
if (!window.__MODULAB_BRIDGE_INIT__) {
  window.__MODULAB_BRIDGE_INIT__ = true;
  console.log('[MODULAB DEBUG] bridge initialized, guard set');

  function safeBgSendMessage(msg, cb) {
    console.log('[MODULAB DEBUG] safeBgSendMessage called, chrome.runtime.id =', chrome?.runtime?.id);
    if (!chrome?.runtime?.id) {
      console.warn('[MODULAB DEBUG] chrome.runtime.id is undefined — aborting silently (this was the bug)');
      return;
    }
    try {
      console.log('[MODULAB DEBUG] calling chrome.runtime.sendMessage with:', msg);
      chrome.runtime.sendMessage(msg, (res) => {
        const err = chrome.runtime.lastError;
        if (err) {
          // глушим шум “context invalidated / receiving end does not exist”
          if (/context invalidated|receiving end does not exist/i.test(err.message)) return;
          console.warn('[bridge] sendMessage error:', err.message);
          return;
        }
        cb && cb(res);
      });
    } catch (e) {
      if (/context invalidated/i.test(String(e))) return;
      console.warn('[bridge] sendMessage threw:', e);
    }
  }

  window.addEventListener('message', (event) => {
    console.log('[MODULAB DEBUG] message event received:', {
      source: event.source === window,
      origin: event.origin,
      allowedOrigins: ALLOWED_PAGE_ORIGINS,
      data: event.data
    });
    if (event.source !== window) return;
    if (!ALLOWED_PAGE_ORIGINS.includes(event.origin)) return;

    const msg = event.data;
    if (!msg || typeof msg !== 'object' || msg.source !== 'MODULAB_PAGE') return;

    // ⬇️ используем ТОЛЬКО безопасную отправку
    safeBgSendMessage(msg, (response) => {
      try {
        window.postMessage({ source: 'MODULAB_EXTENSION', id: msg.id, response }, event.origin);
      } catch {/* no-op */}
    });
  });
}
