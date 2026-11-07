// pts-connector/content_script.js
// Прокидываем сообщения со страницы в background + даём быстрые ответы

window.addEventListener('message', async (ev) => {
  const d = ev.data || {};
  if (ev.source !== window || d.source !== 'MODULAB_PAGE') return;

  const reply = (payload) => {
    window.postMessage({ source: 'MODULAB_EXTENSION', id: d.id, response: payload }, window.origin);
  };

  const type = d.type;

  // поддерживаем и старые, и новые имена
  if (type === 'ping' || type === 'EPTS_PING') {
    reply({ ok: true });
    return;
  }

  if (type === 'save-parser-token' || type === 'EPTS_SET_TOKEN') {
    await chrome.storage.local.set({ parserToken: d.parserToken || '' });
    reply({ ok: true });
    return;
  }

  if (type === 'connect-pts' || type === 'EPTS_CHECK') {
    chrome.runtime.sendMessage({ action: 'connect-pts' }, (resp) => {
      reply(resp || { ok: false, error: 'no-response' });
    });
    return;
  }

  if (type === 'EPTS_FETCH') {
    // клиентский быстрый fetch к ePTS (с куками)
    chrome.runtime.sendMessage(
      { action: 'epts-fetch', url: d.url, method: d.method || 'GET', body: d.body || null },
      (resp) => reply(resp || { ok: false, error: 'no-response' })
    );
    return;
  }
});

// На всякий случай — снимем токен со страницы, если он уже есть
try {
  const parserToken = localStorage.getItem('modulab_token') || '';
  if (parserToken) chrome.storage.local.set({ parserToken });
} catch (e) {}
