# Frontend — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa)

El riesgo mayor hoy: el landing vende como funcional una capacidad que el propio
código admite que no existe (computer use real sobre CONTPAQi/Aspel/QuickBooks/
Xero), y esa es exactamente la clase de afirmación que se cae en la sala de la
demo — no una cosmética menor.

## Hallazgos

### [CRÍTICO] El landing vende "computer use sobre tu ERP" con checkmarks; el código es un mock sin driver real
`landing/index.html:759`, `landing/index.html:787-793`, `landing-b/index.html:1` (feature "Computer use sobre tu ERP", hero-note "Computer use sobre tu ERP actual", marquee con CONTPAQi/SAP/Odoo), `README.md:295-296`, `b2b_ai/computer_use/browser.py:83,227`

Escenario: el contralor lee en el landing "Navega, hace login y sube/extrae CFDI
de cualquier ERP web — sin integraciones API frágiles" junto a una lista de
integraciones con ✓ verde para CONTPAQi, Aspel, QuickBooks y Xero
(`landing/index.html:789-792`). Pide ver una conexión en vivo contra su
CONTPAQi real → `computer_use/browser.py:83` sólo tiene `MockBrowser`, una
simulación en memoria; el propio `README.md:295-296` dice explícitamente
"Qué NO cubre esto: conexión real a CONTPAQi/contaDIGITAL, driver real de
computer use (Playwright/vision)". No hay ningún camino de código que cumpla
lo que el landing promete.

Consecuencia: el contralor o el socio del despacho descubre en la sala que la
funcionalidad central anunciada con checkmarks no existe. Esto no es un typo:
es la promesa de producto más visible de la página, repetida en ambos landings
(`landing-b/index.html:1` tiene la misma frase y el mismo marquee de ERPs).

Causa raíz probable: el copy del landing se escribió para el estado final del
producto, no para el estado actual (mock), y nadie lo revisó contra
`README.md` antes de publicar.

### [CRÍTICO] Landing B tiene testimonio inventado y "56%" repetido sin fuente — vivo en un target de despliegue real, no un borrador
`landing-b/index.html:1` (title, meta description, og:description, twitter:description ×2, hero-stat "56% · menos tiempo en captura"), `landing-b/index.html:18` (blockquote + "— Socio de despacho contable, plan Pro")

Escenario: en `landing/index.html` este mismo problema (documentado antes de
esta ronda) ya se corrigió — el commit `18660c7` ("simplify landing markup",
hoy) quitó el testimonio y el "56%". Pero **nadie tocó `landing-b/index.html`**,
que sigue teniendo el testimonio con atribución falsa (no hay clientes reales,
ver `docs/auditoria-1/MAPA.md` y el hecho de que el proyecto es pre-revenue) y
la cifra "56% menos tiempo en captura" repetida **seis veces** en la misma
página (title, meta description, og:description, twitter:description dos
veces, y el stat destacado del hero) sin una sola nota, footnote o metodología
que la respalde. `landing-b/` no es un experimento descartado: `DEPLOY.md:15`
lo documenta como "Landing alternativa... Vercel/Netlify (static,
standalone)" con su propio `vercel.json` y `netlify.toml` listos para
desplegar tal cual.

Consecuencia: si se despliega o se comparte Landing B — el propio repo lo deja
listo para eso — un prospecto ve un testimonio de un cliente que no existe y
una cifra de ahorro sin ninguna base, exactamente el patrón que ya se sabía
que estaba mal en la otra landing y se corrigió ahí pero no aquí.

Causa raíz probable: el fix de hoy (`18660c7`) se aplicó a un solo archivo
(`landing/index.html`) sin buscar el mismo texto en `landing-b/index.html`.

### [ALTO] El badge "procesado" (verde) no distingue una factura registrada de una atorada esperando aprobación humana
`b2b_ai/portal/routes.py:152-159` (`_estado`), `b2b_ai/db/db.py:266` (`"status": "procesado"` fijo), `b2b_ai/services/pipeline.py:88-97` (`aprobacion["decision"]` / `erp_res["status"]="pending_approval"`), usado en `b2b_ai/portal/templates/dashboard.html:37` e `invoices.html:49`

Escenario: un CFDI cuyo monto dispara el umbral de `evaluate_approval`
(`b2b_ai/tools/tools.py:205-213`) entra al pipeline sin auto-aprobarse →
`pipeline.py:92-97` construye `erp_res = {"poliza": None, "status":
"pending_approval", ...}` (nunca se generó póliza en el ERP). Pero
`db.insert_invoice` (`db.py:238-268`) **hardcodea** `row["status"] =
"procesado"` sin mirar `erp_res["status"]` en absoluto — el campo
`erp_status` sí guarda "pending_approval", pero en una columna distinta que
`_estado()` nunca lee. `_estado()` (`portal/routes.py:152-159`) sólo consulta
`valido` y `requires_human_review` (flags de *validación fiscal*, un concepto
distinto al de *aprobación por monto*) y cae en `status` como default, que
siempre es "procesado". Resultado: en `/portal/dashboard` y `/portal/invoices`
esa factura se ve con el mismo badge verde "procesado" que una factura
realmente registrada con póliza.

Consecuencia: el socio del despacho (o su cliente, usuario del portal) ve una
lista de facturas "procesadas" y asume que su contabilidad está al día.
Justo las facturas de mayor monto — las que cruzan el umbral de aprobación,
las que más importan — pueden estar sin póliza y sin que nadie lo note, salvo
que alguien entre a cada factura individualmente y lea "Estatus ERP" en el
detalle.

Causa raíz probable: `insert_invoice` nunca propaga `erp_res["status"]` a la
columna `status` que el portal usa para el badge.

### [ALTO] En móvil, el portal de cliente pierde toda su navegación — incluido el único botón de cerrar sesión
`b2b_ai/portal/templates/base.html:18-19,92-93`

Escenario: un cliente del despacho (el usuario final que sube facturas, según
el alcance de este rubro) entra al portal desde su celular. La única
navegación del portal vive en `<aside class="side">` (Dashboard / Facturas /
Reportes / Configuración / Cerrar sesión, `base.html:99-111`). La media query
`@media (max-width:760px){ .side{display:none} .main{padding:16px} }`
(`base.html:92-93`) oculta ese `<aside>` por completo y no hay ningún
reemplazo — no hamburguesa, no bottom-nav, ningún otro link a las demás
secciones ni al logout.

Consecuencia: en cualquier viewport típico de celular (menos de 760px, la
inmensa mayoría de los teléfonos), el usuario queda atrapado en la página
donde aterrizó. Para ir a Facturas o cerrar sesión tiene que editar la URL a
mano o borrar cookies — no hay ninguna forma dentro de la interfaz.

Causa raíz probable: el layout se diseñó sidebar-first para escritorio y el
`display:none` de la media query nunca se acompañó de un patrón de
navegación alterno para pantallas chicas.

### [ALTO] Sección "Integraciones" duplicada dos veces seguidas en `landing/index.html`, con `id` repetido
`landing/index.html:769-819` (primer bloque, clases `.integrations`/`.int-grid`) y `landing/index.html:822-874` (segundo bloque, clases `.alt-section`/`.integrations-grid`)

Escenario: quien hace scroll por la landing principal ve la sección
"Integraciones" — mismo título "Se conecta con lo que ya usas", mismo texto,
mismas categorías (SAT & Fiscal, ERPs, Bancos, Nómina) — **dos veces seguidas**,
implementada con dos sistemas de clases CSS distintos (una parece un rediseño
que nunca reemplazó a la anterior). Ambas secciones además comparten
`id="integraciones"` (`landing/index.html:769` y `:822`), un `id` de HTML
duplicado e inválido: el link de navegación `#integraciones` sólo puede
llegar al primero.

Consecuencia: es un defecto visible a simple vista para cualquiera que
navegue la landing completa — el mismo tipo de error que un contralor
detecta sin tener que buscarlo.

Causa raíz probable: una sección se agregó como reemplazo de la otra
(mismo copy, distinta implementación) y nunca se borró la original.

### [ALTO] El toast de notificaciones del portal inyecta contenido del servidor sin escapar, mientras el mismo repo ya tiene el patrón correcto en otro archivo
`b2b_ai/portal/templates/base.html:122-129` (`t.innerHTML = ... + (n.subject||"Notificación") + ... + (n.body||"") + ...`)

Escenario: el portal recibe notificaciones en vivo vía SSE
(`portal/routes.py:473-517`) y las pinta con `showToast()` construyendo
`innerHTML` directamente a partir de `n.subject` y `n.body` — campos que
provienen de plantillas de notificación (`notifications/templates/__init__.py`)
rellenadas con datos derivados de la factura (`{folio}`, `{emisor}`, `{archivo}`),
es decir, texto que en última instancia viene del contenido de un CFDI. Si
alguno de esos campos trae `<img src=x onerror=...>` u otro HTML, se ejecuta
en el navegador del cliente que ve el toast, con la sesión del portal activa
(la cookie es httponly, pero el script corre en el mismo origen y puede leer
el DOM y llamar a las APIs autenticadas del portal). El mismo repo ya conoce
este riesgo y lo resuelve correctamente en otro lugar: `b2b_ai/api/dashboard.py:354-361`
tiene una función `esc()` dedicada, con el comentario explícito "Previene XSS
almacenado... Regresión de auditoría de seguridad" — ese patrón no se aplicó
en `base.html`.

Consecuencia: una vía de inyección hacia el navegador del cliente del
despacho, en el archivo que más widgets de terceros (SSE, toasts) concentra
del portal.

Causa raíz probable: `showToast()` se escribió sin el mismo cuidado que
`dashboard.py`, a pesar de resolver el mismo problema (pintar datos del
servidor en el DOM).

### [ALTO] El dashboard PWA de `landing/` (y `landing-b/`) le pide a cualquier visitante la API key maestra del servidor y la guarda en `localStorage`
`landing/dashboard.html:150-158` (formulario "Ingresa tu API key... Ejemplo dev: `B2B_API_KEY` de la env del servidor", guardada en `localStorage`), idéntico en `landing-b/dashboard.html`

Escenario: `/dashboard.html` es parte del sitio estático público (enlazado
desde la nav de ambos landings, `landing/index.html:387`). La pantalla de
acceso no pide credenciales de un usuario: pide literalmente la
`B2B_API_KEY` del servidor (`landing/dashboard.html:158` la nombra así) y la
persiste indefinidamente en el `localStorage` del navegador de quien la
escriba (`landing/dashboard.html:239,308,316`), sin expiración. Esa clave
viaja luego en cada `fetch` como header `X-API-Key`
(`landing/dashboard.html:301,354`) hacia `/api/v1/*`.

Consecuencia: cualquier vector que lea `localStorage` en ese origen (una
extensión maliciosa, un XSS futuro, un dispositivo compartido) obtiene la
clave que — a juzgar por el propio hint del formulario — es la credencial de
servicio completa, no una API key de usuario acotada. Es tratar un secreto de
backend como si fuera una contraseña de front-end.

Causa raíz probable: el dashboard PWA se construyó para un demo rápido
(pegar la key del `.env` y listo) y ese atajo de desarrollo quedó como el
único método de acceso en producción.

### [MEDIO] "$247K costo anual de vacante" no cuadra con "$18,200/mes" de la misma página
`landing/index.html:409` (`data-count="247" data-prefix="$" data-suffix="K"` → "costo anual de vacante") vs. `landing/index.html:469` ("cada puesto cuesta en promedio **$18,200/mes**")

Escenario: $18,200/mes × 12 = $218,400/año, no $247,000/año — una diferencia
de ~13%. Ambas cifras aparecen en la misma landing describiendo el mismo
concepto (el costo de una vacante de contador) sin que ninguna cite fuente,
así que no hay forma de saber si son dos métricas distintas (p. ej. una
incluye prestaciones) o simplemente no se revisaron juntas.

Consecuencia: es aritmética que cualquier socio de despacho — que trabaja con
números todo el día — puede hacer mentalmente en la landing misma, y que le
resta credibilidad al resto de las cifras de la página (689 vacantes, etc.,
tampoco citan fuente).

Causa raíz probable: las dos cifras se escribieron en momentos distintos sin
cruzarlas.

### [MEDIO] El mismo monto se formatea distinto en tres pantallas del producto
`b2b_ai/api/dashboard.py:386-389` (`Number(m.monto_total).toLocaleString('es-MX')`, sin forzar decimales) vs. `b2b_ai/portal/routes.py:145-149` (`_money` = `"${:,.2f}".format(...)`, siempre 2 decimales) vs. `landing/dashboard.html:329` (`toLocaleString('es-MX', {minimumFractionDigits:2, maximumFractionDigits:2})`, también siempre 2 decimales)

Escenario: para un monto entero como $15,000.00 (frecuente en montos de
factura redondos), el portal de cliente y el dashboard PWA de `landing/`
muestran "$15,000.00" — pero el dashboard operativo en `b2b_ai/api/dashboard.py`
muestra "$15,000" (sin decimales, porque `toLocaleString` sin opciones no los
fuerza); para un monto como $1,234.5 el operativo mostraría "$1,234.5" (un
solo decimal) donde las otras dos pantallas mostrarían "$1,234.50".

Consecuencia: alguien del despacho que compara el dashboard operativo contra
el portal de su cliente para el mismo tenant ve números con distinta cantidad
de decimales — no es un error de monto, pero rompe la lectura de "es
exactamente la misma cifra" a simple vista, justo lo que este rubro pide
vigilar.

Causa raíz probable: `dashboard.py` es el único de los tres que no replicó
las opciones de `toLocaleString` que ya usan las otras dos pantallas.

### [MEDIO] Contraste bajo el mínimo AA en el texto de cuerpo de Landing B
`landing-b/index.html:1` (`--muted:#7A7A76` sobre `--bg:#FFFFFF`, usado en `.lead`, `.prob-card p`, `.feature p`, `.step p`, `.kicker` y más)

Escenario: medí el contraste real de `#7A7A76` sobre blanco: **4.31:1**, por
debajo del mínimo WCAG AA de 4.5:1 para texto normal. Ese color (`--muted`) es
el que usa el cuerpo de texto en la mayoría de las secciones de Landing B —
párrafos de problema, pasos, features — a tamaños de ~15-17px, todos por
debajo del umbral de "texto grande" (18.66px bold / 24px regular) que
bajaría el requisito a 3:1.

Consecuencia: usuarios con baja visión o en condiciones de luz difíciles
tienen más dificultad para leer la mayor parte del copy explicativo de la
página — no es un matiz subjetivo, es una cifra medible bajo el estándar.

Causa raíz probable: la paleta gris-sobre-blanco de Landing B se eligió por
estética (tono "Notion/Linear") sin correr un chequeo de contraste.

### [MEDIO] Los links de exportar/descargar del portal muestran JSON crudo si la sesión expiró, en vez de una pantalla
`b2b_ai/portal/routes.py:126-132` (`_require_user_json` lanza `HTTPException(401)`), usado por los links `<a>` en `invoices.html:30-31` (export CSV/Excel) y `reports.html:17` (descargar PDF); implementación en `routes.py:328-330`, `352-357`, `413-415`

Escenario: `/portal/invoices/export.csv`, `/portal/invoices/export.xlsx` y
`/portal/reports/{id}/download` están enlazados como `<a href=...>` normales
(no `fetch`) pero su autenticación usa `_require_user_json`, que lanza una
`HTTPException` y deja que FastAPI la sirva como JSON. Si la cookie de sesión
expiró (a los 30 días, `SESSION_TTL_DAYS`) y el cliente hace clic en "CSV",
"Excel" o "PDF", el navegador navega a esa URL y renderiza el cuerpo
`{"detail":"Se requiere sesión del portal."}` como texto plano en blanco,
sin ningún estilo del portal ni redirección a `/portal/login`.

Consecuencia: un estado de error que la interfaz nunca aprendió a pintar —
llega crudo a la pantalla del cliente del despacho, justo el patrón que este
rubro pide cazar.

Causa raíz probable: estas tres rutas comparten el helper de auth pensado
para endpoints JSON (`_require_user_json`) en vez del que redirige a login
(`_page_or_redirect` / el patrón usado en las páginas HTML del mismo router).

### [BAJO] El detalle de factura muestra el token interno crudo ("pending_approval") sin traducir
`b2b_ai/portal/templates/invoice_detail.html:36` (`{{ inv.erp_status or '—' }}`)

Escenario: cuando `erp_status` vale `"pending_approval"` (ver hallazgo de
`pipeline.py` arriba), el campo "Estatus ERP" del detalle de factura lo
muestra tal cual — un identificador interno en inglés/snake_case — en una
pantalla en español dirigida al cliente del despacho.

Consecuencia: cosmético pero visible; ninguna otra etiqueta de estado en el
portal se presenta así (todas las demás pasan por `_estado()` y sus clases de
badge con texto en español).

Causa raíz probable: `erp_status` se expone directamente sin pasar por un
diccionario de traducción de estados, a diferencia del resto del portal.

## Lo que revisé y está bien

- **Estados vacíos sí están pintados a propósito** en el portal:
  `portal/templates/dashboard.html:42-44` ("Aún no hay facturas en tu
  cuenta.") y `:59-61` ("No hay notificaciones recientes."),
  `invoices.html:54-56` ("No se encontraron facturas con esos filtros.").
- **Formulario de contacto de ambos landings**: validación cliente completa
  con mensajes de error por campo, `aria-describedby` en cada input
  (`landing/index.html:1000,1005,1010,1015`), `role="status"
  aria-live="polite"` en el mensaje de resultado (`:1029`), y fallback a
  `mailto:` si el POST a `/api/v1/leads` falla (`:1256-1260`) — no deja al
  usuario sin salida si el backend no responde.
- **`prefers-reduced-motion` respetado** en los tres archivos con
  animaciones: `landing/index.html:364-368`, dentro del CSS de
  `landing-b/index.html:1`, y transiciones cortas en el portal.
- **Skip-link al contenido principal** presente en `landing/index.html:372-373`
  ("Saltar al contenido principal").
- **`b2b_ai/api/dashboard.py` sí escapa correctamente** los datos que pinta
  vía `innerHTML`: función `esc()` dedicada (`:354-361`) y escape de `<`/`>`
  en el JSON embebido para evitar breakout de `</script>` (`:448-453`) — el
  patrón correcto existe en el repo, sólo no se replicó en
  `portal/templates/base.html` (ver hallazgo ALTO).
- **CSV del portal exporta con BOM UTF-8** (`routes.py:347`,
  `"﻿" + buf.getvalue()`), evitando el clásico problema de acentos rotos
  al abrir en Excel — un detalle que muchos equipos olvidan.
- **Los assets referenciados existen**: verifiqué contra disco cada imagen y
  video citado en `landing/index.html` y `landing-b/index.html` (`hero.jpg`,
  `hero-ai-dashboard.mp4`, `logo.png`, `logo-likida.png`, `og-image.jpg`,
  `hero-video.mp4`, posters) — ninguno está roto.
- **Login del portal** (`login.html`) tiene labels asociados por `for`/`id`,
  `autocomplete` correcto, y el mensaje de error genérico ("Credenciales
  inválidas.") no filtra si el email existe o no.
- **Botones del dashboard PWA de `landing/` cumplen tamaño de toque**:
  `.btn{min-height:44px}` (`landing/dashboard.html:43`) — el único lugar del
  frontend donde until confirmé el estándar de 44px explícitamente.

## Lo que NO alcancé a revisar

- No ejecuté el portal ni los landings en un navegador real (Playwright/
  gstack) — todo lo anterior es lectura estática de HTML/Jinja2/CSS/JS; los
  hallazgos de contraste y estados están verificados por código y cálculo,
  no por captura de pantalla.
- No revisé `landing/dashboard.html` / `landing-b/dashboard.html` línea por
  línea más allá de la auth gate y el formateo de dinero — son 505 líneas
  cada uno y sólo confirmé que son idénticos entre sí (`diff` sin salida).
- No medí contraste de cada combinación de color de `b2b_ai/api/dashboard.py`
  (tema oscuro) ni de los badges de estado del portal uno por uno — sólo los
  que aparecían como más probables de fallar.
- No probé el flujo de SSE de notificaciones en vivo (`/portal/notifications/stream`)
  contra un servidor corriendo; el hallazgo de XSS en el toast está verificado
  por lectura de código (de dónde viene el dato, cómo se pinta), no por
  explotación real.
- No revisé accesibilidad de lector de pantalla (roles ARIA más allá de los
  explícitos que encontré) ni navegación por teclado completa en ningún de
  los tres frontends.
- No corrí `ruff` sobre `b2b_ai/api/dashboard.py` ni `b2b_ai/portal/routes.py`
  específicamente — son los dos únicos archivos Python de este rubro; el
  `ruff check .` global de 6,365 hallazgos sin config propia no es atribuible
  a este rubro sin filtrar (per instrucción del MAPA).
