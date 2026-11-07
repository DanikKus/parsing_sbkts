// pts_content_script.js - для перехвата JWT на pts.gov.kz
console.log('PTS Content Script loaded');

// Функция для извлечения JWT токена из localStorage
// pts_content_script.js - УЛУЧШЕННАЯ функция извлечения JWT
function extractJwtToken() {
  try {
    console.log('🔍 Searching for JWT token...');
    
    // 1. Ищем в localStorage по разным ключам
    const localStorageKeys = ['user', 'token', 'jwt', 'authToken', 'accessToken', 'userData'];
    for (const key of localStorageKeys) {
      try {
        const value = localStorage.getItem(key);
        if (value) {
          console.log(`📁 localStorage key "${key}":`, value.substring(0, 50) + '...');
          
          // Пытаемся распарсить JSON
          try {
            const parsed = JSON.parse(value);
            if (parsed.token && parsed.token.startsWith('eyJ')) {
              console.log('✅ JWT found in parsed JSON:', parsed.token.substring(0, 20) + '...');
              return parsed.token;
            }
            if (parsed.accessToken && parsed.accessToken.startsWith('eyJ')) {
              console.log('✅ JWT found as accessToken:', parsed.accessToken.substring(0, 20) + '...');
              return parsed.accessToken;
            }
          } catch (e) {
            // Если не JSON, проверяем напрямую
            if (value.startsWith('eyJ') && value.includes('.')) {
              console.log('✅ JWT found directly in localStorage:', value.substring(0, 20) + '...');
              return value;
            }
          }
        }
      } catch (e) {
        console.error(`Error reading localStorage key ${key}:`, e);
      }
    }

    // 2. Ищем во всех ключах localStorage
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.toLowerCase().includes('token')) {
        const value = localStorage.getItem(key);
        if (value && value.startsWith('eyJ') && value.includes('.')) {
          console.log(`✅ JWT found in localStorage key "${key}":`, value.substring(0, 20) + '...');
          return value;
        }
      }
    }

    // 3. Ищем в sessionStorage
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      const value = sessionStorage.getItem(key);
      if (value && value.startsWith('eyJ') && value.includes('.')) {
        console.log(`✅ JWT found in sessionStorage key "${key}":`, value.substring(0, 20) + '...');
        return value;
      }
    }

    // 4. Ищем в cookies
    const cookies = document.cookie.split(';');
    for (const cookie of cookies) {
      const [name, value] = cookie.trim().split('=');
      if (name && (name.includes('token') || name.includes('jwt')) && value) {
        if (value.startsWith('eyJ') && value.includes('.')) {
          console.log(`✅ JWT found in cookie "${name}":`, value.substring(0, 20) + '...');
          return value;
        }
      }
    }

    console.log('❌ JWT not found in any storage');
    return null;
  } catch (e) {
    console.error('❌ Error extracting JWT:', e);
    return null;
  }
}

// Отправляем токен в background script
function sendTokenToBackground(jwt) {
  if (!jwt) return;
  
  console.log('📤 Sending JWT to background:', jwt.substring(0, 20) + '...');
  chrome.runtime.sendMessage({
    action: 'jwt-detected',
    jwt: jwt
  });
}

// Периодическая проверка на наличие токена
function startTokenPolling() {
  let lastFoundJwt = null;
  
  const checkToken = () => {
    const jwt = extractJwtToken();
    if (jwt && jwt !== lastFoundJwt) {
      lastFoundJwt = jwt;
      sendTokenToBackground(jwt);
    }
  };

  // Проверяем сразу
  checkToken();
  
  // Затем каждые 2 секунды
  setInterval(checkToken, 2000);
}

// Мониторим изменения в localStorage
function setupStorageMonitor() {
  const originalSetItem = localStorage.setItem;
  const originalRemoveItem = localStorage.removeItem;

  localStorage.setItem = function(key, value) {
    originalSetItem.apply(this, arguments);
    if (typeof value === 'string' && value.startsWith('eyJ') && value.includes('.')) {
      console.log('🔄 JWT token detected in localStorage setItem');
      sendTokenToBackground(value);
    }
  };

  // Также мониторим изменения через StorageEvent (между вкладками)
  window.addEventListener('storage', (e) => {
    if (e.key && e.newValue && e.newValue.startsWith('eyJ') && e.newValue.includes('.')) {
      console.log('🔄 JWT token detected via storage event');
      sendTokenToBackground(e.newValue);
    }
  });
}


// Запускаем при загрузке
setupStorageMonitor();
startTokenPolling();

// Также проверяем сразу при загрузке с небольшой задержкой
setTimeout(() => {
  const jwt = extractJwtToken();
  if (jwt) {
    sendTokenToBackground(jwt);
  }
}, 1000);