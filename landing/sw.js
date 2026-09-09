/* ============================================================
   Likida AI Enterprise — Service Worker
   - App-shell cache-first: landing, dashboard, manifest, icons.
   - API GET network-first con fallback a caché: así las facturas
     ya procesadas quedan disponibles offline (cache de /api/v1/stats
     y /api/v1/invoices).
   ============================================================ */
'use strict';

const VERSION = 'v1.1.0';
const SHELL_CACHE = `b2b-shell-${VERSION}`;
const API_CACHE = `b2b-api-${VERSION}`;

// Fallback de navegación offline cuando la URL pedida no está en caché
// (el manifest usa "/" como start_url para no forzar el login del dashboard
// al abrir la PWA; este fallback sigue siendo el dashboard porque es la
// pantalla útil dentro de una sesión ya autenticada).
const START_URL = '/dashboard';

const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/dashboard',
  '/dashboard.html',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-512.png'
];

/* ---------- Instalación: precache del app-shell ---------- */
// No se llama a skipWaiting() aquí: el SW nuevo se queda "esperando" hasta
// que la página lo confirme (ver flujo de actualización más abajo), así una
// pestaña abierta con la versión vieja nunca queda con caché desincronizada.
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
  );
});

/* ---------- Flujo de actualización ---------- */
// La página (ver index.html) detecta un SW en espera, avisa al usuario y,
// si acepta, manda este mensaje para activar la versión nueva de inmediato.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

/* ---------- Activación: limpiar cachés viejas ---------- */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((k) => (k.startsWith('b2b-') && k !== SHELL_CACHE && k !== API_CACHE))
        .map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

function isNavigation(req) {
  return req.mode === 'navigate';
}

function isAPI(req) {
  return req.url.indexOf('/api/') !== -1 && req.method === 'GET';
}

/* ---------- Estrategias ---------- */

// App-shell: cache-first con revalidación en segundo plano.
function shellStrategy(event) {
  const req = event.request;
  return caches.match(req).then((cached) => {
    const network = fetch(req).then((res) => {
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(SHELL_CACHE).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => cached);
    return cached || network;
  });
}

// Navegación: network-first, fallback a app-shell, luego a caché.
function navigationStrategy(event) {
  return fetch(event.request).then((res) => {
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(SHELL_CACHE).then((c) => c.put(event.request, copy));
    }
    return res;
  }).catch(() => (
    caches.match(event.request)
      .then((c) => c || caches.match(START_URL) || caches.match('/'))
  ));
}

// API GET: network-first con fallback a caché (offline de facturas).
// Solo cacheamos respuestas con status ok (200-299) y content-type json.
function apiStrategy(event) {
  const req = event.request;
  return fetch(req).then((res) => {
    if (res && res.ok) {
      const ct = res.headers.get('content-type') || '';
      if (ct.indexOf('json') !== -1) {
        const copy = res.clone();
        caches.open(API_CACHE).then((c) => c.put(req, copy));
      }
    }
    return res;
  }).catch(() => (
    caches.match(req).then((c) => {
      if (c) return c;
      // Fallback estructural: si no hay caché de /api, devuelve un JSON
      // de error offline reconocible para que el dashboard lo muestre.
      return new Response(JSON.stringify({
        offline: true,
        message: 'Sin conexión y sin datos en caché.'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    })
  ));
}

/* ---------- Fetch router ---------- */
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  // Solo manejamos http(s) (no chrome-extension:, devtools, etc.).
  if (req.url.indexOf('http') !== 0) return;

  if (isNavigation(req)) {
    event.respondWith(navigationStrategy(event));
    return;
  }
  if (isAPI(req)) {
    event.respondWith(apiStrategy(event));
    return;
  }
  // Estáticos + favicon + fonts locales: cache-first.
  event.respondWith(shellStrategy(event));
});
