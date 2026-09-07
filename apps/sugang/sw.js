// Daejin Sugang Observer Service Worker
// Handles background push events when browser/tab is closed

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {
    title: '🔥 [빈자리 발생!] 대진대 수강신청 알림',
    body: '목표 과목의 취소표가 감지되었습니다. 즉시 확인하세요!',
    icon: 'https://www.daejin.ac.kr/favicon.ico',
    badge: 'https://www.daejin.ac.kr/favicon.ico',
    url: 'https://daejin.qucord.com',
    tag: 'daejin-vacancy-alert'
  };

  if (event.data) {
    try {
      const parsed = event.data.json();
      data = Object.assign(data, parsed);
    } catch (err) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: data.icon || 'https://www.daejin.ac.kr/favicon.ico',
    badge: data.badge || 'https://www.daejin.ac.kr/favicon.ico',
    vibrate: [200, 100, 200, 100, 200],
    tag: data.tag || 'daejin-vacancy-alert',
    renotify: true,
    requireInteraction: true,
    data: data.data || { url: data.url || 'https://daejin.qucord.com' },
    actions: [
      { action: 'open', title: '🚀 옵저버 열기' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const urlToOpen = (event.notification.data && event.notification.data.url) || 'https://daejin.qucord.com';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes('daejin.qucord.com') && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(urlToOpen);
      }
    })
  );
});
