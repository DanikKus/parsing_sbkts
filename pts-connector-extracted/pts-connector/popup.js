'use strict';

const btn = document.getElementById('btn');
const state = document.getElementById('state');

btn.onclick = async () => {
  try {
    btn.disabled = true;
    state.textContent = 'Открываю pts.gov.kz...';
    const t = await chrome.tabs.create({ url: 'https://pts.gov.kz/', active: true });
    await chrome.storage.local.set({ pts_connect_tab: t.id });

    chrome.runtime.sendMessage({ action: 'connect-pts' });

    let dots = 0;
    const iv = setInterval(() => {
      dots = (dots + 1) % 4;
      state.textContent = 'Ожидание входа в ПТС' + '.'.repeat(dots);
    }, 600);

    function onMsg(msg) {
      if (msg?.action !== 'capture-done') return;
      chrome.runtime.onMessage.removeListener(onMsg);
      clearInterval(iv);
      if (msg.ok) { state.textContent = 'Готово. Авторизация подключена.'; btn.textContent = 'Подключено'; }
      else { state.textContent = 'Ошибка: ' + (msg.error || 'неизвестно'); btn.disabled = false; }
    }
    chrome.runtime.onMessage.addListener(onMsg);
  } catch (e) {
    state.textContent = 'Ошибка: ' + e.message;
    btn.disabled = false;
  }
};
