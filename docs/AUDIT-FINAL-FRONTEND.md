# Auditoría Frontend — Likida AI Enterprise

**Fecha:** 2026-08-01  
**Alcance:** Landing page, Portal (SPA + templates), Dashboard (admin + cliente), Service Worker, Manifest  
**Archivos auditados:** landing/index.html, landing/sw.js, landing/manifest.json, b2b_ai/api/portal.py, b2b_ai/api/static/portal.html, b2b_ai/api/static/dashboard.html, b2b_ai/portal/templates/{login.html, base.html, dashboard.html}, b2b_ai/features/dashboard/{routes.py, service.py, models.py}

---

## RESUMEN EJECUTIVO

| Severidad | Cantidad |
|-----------|----------|
| 🔴 CRÍTICA | 5 |
| 🟠 ALTA | 8 |
| 🟡 MEDIA | 10 |
| 🟢 BAJA | 7 |
| **TOTAL** | **30** |

---

## 1. LANDING PAGE (landing/index.html)

### 🔴 C-01 · Formulario de leads no envía datos al backend
- **Archivo:** landing/index.html:831-837
- **Descripción:** `handleSubmit()` solo muestra un `alert()` y resetea el formulario. No hay POST a ningún endpoint — los leads se pierden.
- **Impacto:** Pérdida total de leads comerciales.
- **Fix:** Implementar `fetch('/api/v1/leads', {method:'POST', body: JSON.stringify(Object.fromEntries(formData))})` y mostrar estado de éxito/error real.

### 🟠 A-01 · Video hero probablemente no carga (404)
- **Archivo:** landing/index.html:240-242
- **Descripción:** `<source src="/assets/hero-ai-dashboard.mp4">` — el archivo debe existir en el servidor estático. Sin verificación de que el asset existe. El poster `/assets/hero.jpg` también puede faltar.
- **Impacto:** Hero section vacío en producción si los assets no se sirven.
- **Fix:** Verificar que los archivos existen en el build. Añadir fallback con `onerror` en el video.

### 🟠 A-02 · Sin Open Graph / Twitter Cards
- **Archivo:** landing/index.html:3-10
- **Descripción:** Solo `<meta name="description">`. Faltan: `og:title`, `og:description`, `og:image`, `og:url`, `og:type`, `twitter:card`, `twitter:image`.
- **Impacto:** Links compartidos en redes sociales no muestran preview.
- **Fix:** Añadir meta tags OG y Twitter Card completo en `<head>`.

### 🟠 A-03 · Sin structured data (JSON-LD)
- **Archivo:** landing/index.html (head)
- **Descripción:** No hay `<script type="application/ld+ld+json">` con Schema.org (Organization, SoftwareApplication, FAQPage).
- **Impacto:** SEO desfavorecido — sin rich snippets en Google.
- **Fix:** Añadir JSON-LD con `Organization`, `SoftwareApplication` y `FAQPage`.

### 🟡 M-01 · Favicon no declarado
- **Archivo:** landing/index.html:3-10
- **Descripción:** No hay `<link rel="icon">`. Los navegadores buscan /favicon.ico por defecto pero no está referenciado.
- **Fix:** Añadir `<link rel="icon" href="/assets/favicon.ico">` y versiones PNG/apple-touch-icon.

### 🟡 M-02 · Links de nav en español pero textos en inglés
- **Archivo:** landing/index.html:213-218
- **Descripción:** Hero y copy en español pero nav links dicen "Platform", "Agents", "Security" en inglés. Inconsistente con la audiencia mexicana.
- **Fix:** Traducir a "Plataforma", "Agentes", "Seguridad", "Precios", "Contacto".

### 🟡 M-03 · Contadores animados sin `prefers-reduced-motion`
- **Archivo:** landing/index.html:774-794
- **Descripción:** Los contadores animados y el marquee no respetan `prefers-reduced-motion`. Usuarios con vértigo/migraña pueden verse afectados.
- **Fix:** Envolver animaciones en `if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches)`.

### 🟡 M-04 · Logo apunta a path que puede no existir
- **Archivo:** landing/index.html:210
- **Descripción:** `<img src="/assets/logo-likida.png">` — sin verificación de que el asset existe.
- **Fix:** Verificar asset en build pipeline.

### 🟢 B-01 · Contenido duplicado en stats
- **Archivo:** landing/index.html:257 vs 345
- **Descripción:** "56% menos tiempo" aparece tanto en Hero como en la sección Impacto con el mismo dato.
- **Fix:** Usar datos diferentes o eliminar duplicado.

---

## 2. PORTAL — Autenticación (b2b_ai/api/portal.py)

### 🔴 C-02 · Sin CSRF protection
- **Archivo:** b2b_ai/api/portal.py:180-267 (todo el router)
- **Descripción:** Los endpoints POST (login, logout, upload) no tienen protección CSRF. El token de sesión se envía por header `Authorization`, lo cual mitiga parcialmente para el SPA, pero los templates Jinja usan formularios POST tradicionales sin csrf_token.
- **Impacto:** Ataques cross-site request forgery contra el portal.
- **Fix:** Añadir middleware CSRF (double-submit cookie pattern) o usar `SameSite=Strict` en cookies de sesión.

### 🔴 C-03 · Token de sesión almacenado en localStorage
- **Archivo:** b2b_ai/api/static/portal.html:199,269
- **Descripción:** `localStorage.setItem("portal_token", TOKEN)` — vulnerable a XSS. Si un atacante inyecta JS, roba todas las sesiones.
- **Impacto:** Robo de sesión completo si hay XSS.
- **Fix:** Usar cookies HttpOnly + SameSite=Strict. El SPA debe recibir el token como cookie segura, no en localStorage.

### 🟠 A-04 · Magic link revela si el email existe (enumeración)
- **Archivo:** b2b_ai/api/portal.py:213-217
- **Descripción:** `portal_magic_link` devuelve 404 "No hay una cuenta con ese email" — permite enumerar cuentas. El código dice "No revelamos si el email existe" pero SÍ lo revela con el 404.
- **Impacto:** Enumeración de usuarios.
- **Fix:** Siempre devolver 200 con mensaje genérico "Si existe una cuenta con ese email, recibirás un enlace."

### 🟠 A-05 · Sin rate limit en login
- **Archivo:** b2b_ai/api/portal.py:180-201
- **Descripción:** El endpoint de login no tiene rate limiting. Permite brute-force de contraseñas.
- **Impacto:** Brute force de credenciales.
- **Fix:** Añadir rate limiter (ej: 5 intentos/minuto por IP).

### 🟠 A-06 · JobStore en memoria — datos se pierden al reiniciar
- **Archivo:** b2b_ai/api/portal.py:84-118
- **Descripción:** `_JobStore` almacena jobs en un dict de Python. Si el servidor reinicia durante un upload, el usuario pierde el estado y no puede recuperar el resultado.
- **Impacto:** Pérdida de trabajos de procesamiento en curso.
- **Fix:** Persistir jobs en SQLite/Redis o usar la DB como cola.

### 🟠 A-07 · Login template sin CSRF y sin HTTPS enforcement
- **Archivo:** b2b_ai/portal/templates/login.html:39
- **Descripción:** `<form method="POST">` sin token CSRF y sin indicación de que debe servirse sobre HTTPS.
- **Impacto:** Credenciales enviadas en texto plano si HTTP.
- **Fix:** Añadir csrf_token hidden input. Forzar redirect HTTP→HTTPS en el servidor.

### 🟡 M-05 · SESSION_TTL_DAYS = 30 es excesivo
- **Archivo:** b2b_ai/api/portal.py:34
- **Descripción:** Sesiones de 30 días sin sliding expiration ni refresh token rotation.
- **Fix:** Reducir a 7 días con refresh token de 30 días. Implementar rotación de tokens.

---

## 3. PORTAL SPA (b2b_ai/api/static/portal.html)

### 🟡 M-06 · Sin labels ARIA en la tabla de facturas
- **Archivo:** b2b_ai/api/static/portal.html:186-192
- **Descripción:** La tabla no tiene `<caption>`, `scope` en headers, ni `aria-label` en el contenedor.
- **Impacto:** Screen readers no identifican la tabla correctamente.
- **Fix:** Añadir `<caption>Tabla de facturas</caption>` y `scope="col"` en `<th>`.

### 🟡 M-07 · Drag & drop sin feedback ARIA
- **Archivo:** b2b_ai/api/static/portal.html:386-391
- **Descripción:** La zona de drag & drop no tiene `aria-live` para anunciar cambios de estado a screen readers.
- **Fix:** Añadir `aria-live="polite"` al contenedor de jobs.

### 🟢 B-02 · Error messages no son accesibles
- **Archivo:** b2b_ai/api/static/portal.html:258-261
- **Descripción:** Los mensajes de error se muestran en un div sin `role="alert"` ni `aria-live`.
- **Fix:** Añadir `role="alert"` al div de mensajes.

### 🟢 B-03 · Spinner sin texto alternativo
- **Archivo:** b2b_ai/api/static/portal.html:105-107
- **Descripción:** El spinner CSS no tiene texto para screen readers.
- **Fix:** Añadir `<span class="sr-only">Cargando...</span>` dentro del spinner.

---

## 4. DASHBOARD GERENCIAL (b2b_ai/api/static/dashboard.html)

### 🔴 C-04 · API key expuesta en URL (query parameter)
- **Archivo:** b2b_ai/api/static/dashboard.html:96
- **Descripción:** `const API_KEY = params.get('api_key') || '';` — la API key se pasa como query parameter y queda visible en el historial del navegador, logs del servidor, y bookmarks.
- **Impacto:** Filtración de credenciales de admin.
- **Fix:** Usar header `X-API-Key` via login flow, no query parameter. Implementar autenticación por sesión.

### 🟠 A-08 · Chart.js cargado desde CDN sin SRI
- **Archivo:** b2b_ai/api/static/dashboard.html:7
- **Descripción:** `<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js">` sin `integrity` attribute.
- **Impacto:** Si el CDN es comprometido, se inyecta JS malicioso (supply chain attack).
- **Fix:** Añadir `integrity="sha384-..."` y `crossorigin="anonymous"`.

### 🟡 M-08 · Auto-refresh cada 60s sin control del usuario
- **Archivo:** b2b_ai/api/static/dashboard.html:223
- **Descripción:** `setInterval(load, 60000)` — refresca datos cada minuto sin que el usuario pueda pausarlo. Consume bandwidth innecesariamente.
- **Fix:** Añadir toggle de auto-refresh o usar `visibilitychange` para pausar cuando la pestaña no está visible.

### 🟢 B-04 · Sin loading state en carga inicial
- **Archivo:** b2b_ai/api/static/dashboard.html:200-222
- **Descripción:** La función `load()` no muestra spinner durante la carga inicial — KPIs y charts aparecen vacíos hasta que llegan los datos.
- **Fix:** Mostrar skeleton loaders o spinner durante la carga.

---

## 5. DASHBOARD ADMIN BACKEND (b2b_ai/features/dashboard/)

### 🟡 M-09 · datetime.utcnow() deprecated
- **Archivo:** b2b_ai/features/dashboard/service.py:48,120,202,244,303,379
- **Descripción:** `datetime.utcnow()` está deprecated desde Python 3.12. Debe usarse `datetime.now(timezone.utc)`.
- **Fix:** Reemplazar todas las llamadas con `datetime.now(timezone.utc)`.

### 🟡 M-10 · N+1 queries en get_client_list
- **Archivo:** b2b_ai/features/dashboard/service.py:124-127
- **Descripción:** Para cada tenant, hace `count_invoices()` + `list_invoices()` — O(N) queries. Con 100 tenants = 200 queries por petición.
- **Impacto:** Performance degrada linealmente con el número de clientes.
- **Fix:** Hacer una sola query con GROUP BY tenant_id o añadir caché.

### 🟢 B-05 · scope en query parameters no sanitizado
- **Archivo:** b2b_ai/features/dashboard/routes.py:66-71
- **Descripción:** `sort_by` y `sort_order` no se validan contra whitelist explícita antes de pasar al service layer.
- **Fix:** Validar contra lista blanca de campos permitidos.

---

## 6. TEMPLATES JINJA (b2b_ai/portal/templates/)

### 🟢 B-06 · Sidebar desaparece en mobile sin menú alternativo
- **Archivo:** b2b_ai/portal/templates/base.html:92-93
- **Descripción:** `@media (max-width:760px){ .side{display:none} }` — el sidebar se oculta pero no hay hamburger menu ni bottom nav. El usuario pierde navegación.
- **Impacto:** Portal inutilizable en mobile.
- **Fix:** Añadir menú hamburguesa o bottom tab bar para mobile.

### 🟢 B-07 · XSS potencial en templates Jinja
- **Archivo:** b2b_ai/portal/templates/base.html:108, dashboard.html:36
- **Descripción:** `{{ inv.folio_fiscal or inv.id }}` y `{{ inv.emisor_nombre or inv.emisor_rfc }}` — Jinja2 escapa por defecto, pero si algún campo contiene HTML malicioso y se usa con `|safe`, hay XSS.
- **Status:** Seguro POR AHORA (auto-escaping activo), pero documentar que NO se use `|safe` con datos de usuario.

---

## 7. PWA (Service Worker + Manifest)

### 🟡 M-11 · Service worker no tiene update flow
- **Archivo:** landing/sw.js:10
- **Descripción:** `const VERSION = 'v1.0.0'` — hardcodeado. No hay mecanismo para detectar nuevas versiones y notificar al usuario.
- **Fix:** Implementar `updatefound` event listener en el registration para mostrar banner "Nueva versión disponible".

### 🟡 M-12 · Manifest usa start_url de dashboard que requiere auth
- **Archivo:** landing/manifest.json:6
- **Descripción:** `"start_url": "/dashboard"` — si el usuario instala la PWA y no está autenticado, abre una página que requiere login sin flujo de redirección.
- **Fix:** Cambiar `start_url` a `/` o añadir splash screen con login redirect.

---

## 8. PERFORMANCE

### 🟡 M-13 · CSS inline de 49KB en landing
- **Archivo:** landing/index.html:11-202
- **Descripción:** ~6KB de CSS minificado inline. Aunque no es enorme, bloquea el rendering. Los fonts de Google (Inter) añaden 200-400ms.
- **Status:** Aceptable para MVP. Para producción: extraer CSS a archivo externo con preload.

### 🟠 A-09 · Sin lazy loading en iframes/images
- **Archivo:** landing/index.html:703
- **Descripción:** El iframe de YouTube sí tiene `loading="lazy"` ✅, pero las imágenes del logo no tienen dimensiones explícitas (CLS risk).
- **Fix:** Añadir `width` y `height` a las imágenes del logo.

---

## 9. CROSS-BROWSER

### 🟢 B-08 · backdrop-filter no soportado en todos los browsers
- **Archivo:** landing/index.html:45
- **Descripción:** `backdrop-filter: blur(20px)` — no soportado en Firefox < 103. El nav scrolled perderá el efecto blur.
- **Status:** Bajo impacto (fallback: fondo sólido con opacity).

---

## 10. NAVEGACIÓN Y ROUTING

### 🟠 A-10 · Portal SPA sin deep links ni 404
- **Archivo:** b2b_ai/api/static/portal.html:231-234
- **Descripción:** El router del SPA usa visibilidad de divs (`showView`) pero no manipula `history` ni responde a `popstate`. No hay deep links, no hay 404. Refrescar la página siempre muestra auth o app basado en el token.
- **Impacto:** URLs del portal no son compartibles ni bookmarkeables.
- **Fix:** Implementar `history.pushState` + `popstate` listener con hash routing o History API.

---

## TABLA RESUMEN

| ID | Severidad | Categoría | Archivo | Línea | Hallazgo |
|----|-----------|-----------|---------|-------|----------|
| C-01 | 🔴 CRÍTICA | Forms | landing/index.html | 831 | Formulario leads no envía datos |
| C-02 | 🔴 CRÍTICA | Security | b2b_ai/api/portal.py | 180 | Sin CSRF protection |
| C-03 | 🔴 CRÍTICA | Security | b2b_ai/api/static/portal.html | 199 | Token en localStorage (XSS vulnerable) |
| C-04 | 🔴 CRÍTICA | Security | b2b_ai/api/static/dashboard.html | 96 | API key en URL query param |
| C-05 | 🔴 CRÍTICA | Auth | b2b_ai/api/portal.py | 213 | Magic link revela existencia de email |
| A-01 | 🟠 ALTA | Assets | landing/index.html | 240 | Video hero puede dar 404 |
| A-02 | 🟠 ALTA | SEO | landing/index.html | 3 | Sin Open Graph meta tags |
| A-03 | 🟠 ALTA | SEO | landing/index.html | head | Sin structured data JSON-LD |
| A-04 | 🟠 ALTA | Security | b2b_ai/api/portal.py | 213 | Enumeración de usuarios |
| A-05 | 🟠 ALTA | Security | b2b_ai/api/portal.py | 180 | Sin rate limit en login |
| A-06 | 🟠 ALTA | Reliability | b2b_ai/api/portal.py | 84 | JobStore en memoria |
| A-07 | 🟠 ALTA | Security | b2b_ai/portal/templates/login.html | 39 | Login sin CSRF, sin HTTPS |
| A-08 | 🟠 ALTA | Security | b2b_ai/api/static/dashboard.html | 7 | CDN sin SRI hash |
| A-09 | 🟠 ALTA | Performance | landing/index.html | 210 | Imágenes sin dimensiones (CLS) |
| A-10 | 🟠 ALTA | Navigation | b2b_ai/api/static/portal.html | 231 | SPA sin deep links ni 404 |
| M-01 | 🟡 MEDIA | SEO | landing/index.html | head | Favicon no declarado |
| M-02 | 🟡 MEDIA | UX | landing/index.html | 213 | Nav en inglés, contenido en español |
| M-03 | 🟡 MEDIA | A11Y | landing/index.html | 774 | Sin prefers-reduced-motion |
| M-04 | 🟡 MEDIA | Assets | landing/index.html | 210 | Logo path no verificado |
| M-05 | 🟡 MEDIA | Security | b2b_ai/api/portal.py | 34 | Session TTL 30 días sin rotación |
| M-06 | 🟡 MEDIA | A11Y | b2b_ai/api/static/portal.html | 186 | Tabla sin ARIA labels |
| M-07 | 🟡 MEDIA | A11Y | b2b_ai/api/static/portal.html | 386 | Drag & drop sin aria-live |
| M-08 | 🟡 MEDIA | UX | b2b_ai/api/static/dashboard.html | 223 | Auto-refresh sin control |
| M-09 | 🟡 MEDIA | Code | b2b_ai/features/dashboard/service.py | 48 | datetime.utcnow() deprecated |
| M-10 | 🟡 MEDIA | Performance | b2b_ai/features/dashboard/service.py | 124 | N+1 queries |
| M-11 | 🟡 MEDIA | PWA | landing/sw.js | 10 | Sin update notification |
| M-12 | 🟡 MEDIA | PWA | landing/manifest.json | 6 | start_url requiere auth |
| M-13 | 🟡 MEDIA | Performance | landing/index.html | 11 | CSS inline ~6KB |
| B-01 | 🟢 BAJA | Content | landing/index.html | 257 | Stats duplicados |
| B-02 | 🟢 BAJA | A11Y | b2b_ai/api/static/portal.html | 258 | Errors sin role="alert" |
| B-03 | 🟢 BAJA | A11Y | b2b_ai/api/static/portal.html | 105 | Spinner sin sr-only |
| B-04 | 🟢 BAJA | UX | b2b_ai/api/static/dashboard.html | 200 | Sin loading state inicial |
| B-05 | 🟢 BAJA | Security | b2b_ai/features/dashboard/routes.py | 66 | sort_by sin whitelist |
| B-06 | 🟢 BAJA | Mobile | b2b_ai/portal/templates/base.html | 92 | Sidebar desaparece sin menú alt |
| B-07 | 🟢 BAJA | Security | b2b_ai/portal/templates/ | - | Jinja auto-escape OK (documentar) |
| B-08 | 🟢 BAJA | X-Browser | landing/index.html | 45 | backdrop-filter fallback |

---

## CHECKLIST DE VERIFICACIÓN

| Criterio | Estado | Notas |
|----------|--------|-------|
| CSS carga correctamente | ✅ | Inline, no depende de archivos externos |
| Video carga | ⚠️ | Depende de `/assets/hero-ai-dashboard.mp4` existir |
| Formulario envía leads | ❌ | Solo muestra alert(), no envía nada |
| Responsive mobile | ⚠️ | Landing OK, portal Jinja pierde nav en mobile |
| Accesibilidad ARIA | ⚠️ | Parcial: nav toggle tiene aria-label, tablas y forms incompletos |
| Login/logout funciona | ✅ | Flujo completo con bcrypt + token |
| Session management | ⚠️ | Token en localStorage, 30 días sin rotación |
| CSRF protection | ❌ | No implementado |
| Dashboard endpoints correctos | ✅ | Modelos Pydantic validados, multi-tenant filtering |
| Charts/gráficas | ✅ | Chart.js con bar + doughnut charts |
| Assets optimizados | ⚠️ | CSS inline OK, pero CDN sin SRI |
| Lazy loading | ✅ | YouTube iframe tiene loading="lazy" |
| Meta tags SEO | ❌ | Solo description, faltan OG/Twitter/JSON-LD |
| Manifest.json válido | ✅ | Válido, pero start_url requiere auth |
| Service worker | ✅ | Implementado con cache-first + network-first API |
| Validación client-side | ✅ | HTML5 required + type=email en formularios |
| SPA routing | ❌ | Sin History API, sin deep links |
| 404 handling | ❌ | No hay página 404 |
| Keyboard navigation | ⚠️ | Básica (tab order natural), sin skip-links |
| Screen reader | ⚠️ | Parcial, faltan labels en tablas y forms |

---

*Auditoría completada. Las 5 hallazgos críticos deben resolverse antes de producción.*
