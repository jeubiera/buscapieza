// ===== BUSCAPIEZA RD — SERVICE WORKER v3 =====
const VERSION      = 'v3';
const CACHE_STATIC = `buscapieza-static-${VERSION}`;
const CACHE_PAGES  = `buscapieza-pages-${VERSION}`;
const OFFLINE_URL  = '/offline';

const PRECACHE_URLS = [
  '/',
  OFFLINE_URL,
  '/static/css/main.css',
  '/static/js/main.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/manifest.json',
];

// ── Instalación: precachea el app shell, NO activa de inmediato ──────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => cache.addAll(PRECACHE_URLS))
  );
});

// ── Activación: limpia cachés viejas y toma control ───────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_STATIC && k !== CACHE_PAGES)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Mensajes desde la página (flujo de actualización controlado) ─────────────
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING' || event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// ── Fetch ──────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Navegación (carga de páginas HTML): network-first con fallback a /offline
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then(resp => {
          const clone = resp.clone();
          caches.open(CACHE_PAGES).then(c => c.put(req, clone));
          return resp;
        })
        .catch(() =>
          caches.match(req).then(cached => cached || caches.match(OFFLINE_URL))
        )
    );
    return;
  }

  // Estáticos same-origin: cache-first, refrescando en segundo plano (SWR)
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then(cached => {
        const fetchPromise = fetch(req).then(resp => {
          const clone = resp.clone();
          caches.open(CACHE_STATIC).then(c => c.put(req, clone));
          return resp;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Resto (APIs, etc.): network-first con fallback a caché si existe
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});

// ── Push Notifications ───────────────────────────────────────────────────────
self.addEventListener('push', event => {
  let data = { title: 'BuscaPieza RD', body: 'Nueva notificación', url: '/' };
  try {
    data = Object.assign(data, event.data.json());
  } catch(e) {
    if (event.data) data.body = event.data.text();
  }

  const options = {
    body   : data.body,
    icon   : '/static/icons/icon-192.png',
    badge  : '/static/icons/badge-96.png',
    image  : data.image || null,
    vibrate: [200, 100, 200, 100, 200],
    tag    : data.tag || 'buscapieza-notif',
    renotify: true,
    requireInteraction: data.requireInteraction || false,
    data   : { url: data.url || '/' },
    actions: data.actions || [
      { action: 'ver',    title: 'Ver ahora' },
      { action: 'cerrar', title: 'Cerrar'    }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// ── Click en notificación ────────────────────────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.action === 'cerrar') return;

  const targetUrl = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(wins => {
      const matched = wins.find(w => w.url.includes(targetUrl));
      if (matched) return matched.focus();
      return clients.openWindow(targetUrl);
    })
  );
});
