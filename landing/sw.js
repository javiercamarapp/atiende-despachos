/* ============================================================
   Likida AI Enterprise — Service Worker
   - App-shell cache-first: landing, dashboard, manifest, icons.
   - API GET network-first con fallback a caché: así las facturas
     ya procesadas quedan disponibles offline (cache de /api/v1/stats
     y /api/v1/invoices).
   ============================================================ */
'use strict';

const VERSION = 'v1.0.0';
const SHELL_CACHE = `b2b-shell-${VERSION}`;
const API_CACHE = `b2b-api-${VERSION}`;

// Página de inicio de la instalación: el dashboard (o la landing si aún no
// está el dashboard). Se usa como fallback de navegación offline.
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
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
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
      .then((c) => c || caches.match('/dashboard') || caches.match('/'))
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
