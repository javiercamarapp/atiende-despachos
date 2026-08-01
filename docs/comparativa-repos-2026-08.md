# Auditoría comparativa por rubro — `likida.ai` vs `likida-ai-enterprise`

**Fecha:** 2026-08-01
**Revisiones:** `likida.ai` en `0769d77` (233 commits) · `likida-ai-enterprise` en `2015671` (rama de auditoría, ya fusionada con `main` en `f63396e`)
**Método:** medición directa sobre ambos árboles — suites ejecutadas, cobertura instrumentada, auditoría de dependencias, escaneo de aislamiento por tenant y lectura dirigida de los puntos de mayor riesgo.

---

## Resultado

| # | Rubro | `likida.ai` | `enterprise` | Gana |
|---|---|---|---|---|
| 1 | Arquitectura y diseño | **8.5** | 8.0 | likida.ai |
| 2 | Calidad de código y legibilidad | **9.5** | 8.0 | likida.ai |
| 3 | Seguridad | **8.5** | 7.5 | likida.ai |
| 4 | Pruebas | **9.5** | 8.0 | likida.ai |
| 5 | Datos y multi-tenancy | 7.5 | **8.5** | enterprise |
| 6 | Producción y operabilidad | **8.5** | 7.5 | likida.ai |
| 7 | Documentación | **8.0** | **8.0** | empate |
| 8 | Higiene del repo y disciplina de git | **8.0** | 5.5 | likida.ai |
| 9 | Dependencias y cadena de suministro | 6.0 | **9.0** | enterprise |
| 10 | Corrección de dominio (fiscal MX) | **9.0** | 7.5 | likida.ai |
| | **Media** | **8.3** | **7.8** | |

`likida.ai` gana 7 rubros, `enterprise` gana 2 y empatan en 1. La media está más cerca de lo que sugiere ese marcador porque los dos rubros que gana el enterprise los gana por mucho.

---

## 1. Arquitectura y diseño — 8.5 vs 8.0

**`likida.ai`.** Next.js 16 con App Router. El dominio vive en `src/lib/cuadra/` segmentado por fase del negocio: `intake/` (recepción de fotos y CFDI), `cuadre/` (motor de liquidación), `facturacion/`, `periodo/`. Los adaptadores externos están aislados en `src/lib/{supabase,llm,meta}/`. El archivo más grande es `processor.ts` con 915 líneas.

Lo que baja la nota: la capa de repositorio habla Supabase directamente en todo el dominio; no hay puerto que permita cambiar de proveedor sin tocar 12 módulos.

**`enterprise`.** La separación por dominios es limpia y explícita: `cfdi/`, `services/`, `api/`, `db/`, `auth/`, `billing/`, `notifications/`, `sat/`, `computer_use/`. El acierto mayor es la capa de datos con doble backend: el mismo `db.py` corre sobre SQLite y PostgreSQL seleccionando DSN, con Alembic como fuente de verdad en producción y `MIGRATIONS` en SQLite.

Lo que baja la nota son dos god-modules: `db.py` con 1 437 líneas concentra toda la persistencia de 20 dominios, y `app.py` con 1 253 monta doce routers, define el rate limiter, el cache de stats, la resolución de rutas locales y once endpoints inline. `create_app` es una función de más de 800 líneas.

---

## 2. Calidad de código y legibilidad — 9.5 vs 8.0

Este es el rubro con la diferencia más medible.

| | likida.ai | enterprise |
|---|---|---|
| Tipado | TS `strict`, `tsc --noEmit` limpio | type hints en 477 de 1 353 firmas (35 %) |
| Escapes de tipo | 2 `any`, 2 `ts-ignore` en 29 600 líneas | n/a |
| Linter | `eslint` limpio, en CI | ninguno |
| Captura de errores | 0 `catch` vacíos en 85 | 88 `except Exception`, 19 con `pass` silencioso |

Pero la diferencia real no está en los números, está en qué documentan los comentarios. En `enterprise` los docstrings explican **qué hace** el módulo, y son excelentes en eso. En `likida.ai` los comentarios explican **qué se intentó antes y por qué se descartó**. `src/lib/env.ts` abre con veinte líneas contando que ahí vivía un `requireEnv()` que nadie llamaba nunca, por qué lanzar en una función serverless empeora el problema en vez de resolverlo, y qué se puso en su lugar. `ci.yml` registra que dos pruebas de tiempo existían y el CI no las corría ni una sola vez.

Ese segundo tipo de comentario es el que evita que un error se repita.

En `enterprise`, los `except Exception` están razonados donde son best-effort (auditoría, notificaciones) y comentados como tales. Donde duelen es en `api/auth.py:57`: un fallo de base de datos al resolver una API key se convierte en un 401 indistinguible de una clave inválida, así que un incidente de infraestructura se diagnosticará como problema de autenticación.

---

## 3. Seguridad — 8.5 vs 7.5

**`likida.ai`.** Verificación HMAC del webhook con `timingSafeEqual` y sin fallback: si falta `WHATSAPP_APP_SECRET`, `verifySignature` devuelve `false`, no "pasa". El mismo criterio en el challenge del webhook. La migración `0012_seguridad_rls.sql` documenta dos huecos hallados sondeando con cliente anónimo —RLS apagado en `wa_mensaje_procesado` permitía a un anónimo insertar `wa_message_id` falsos y hacer que mensajes reales se descartaran como duplicados— y corrige el detalle que casi todo el mundo pasa por alto: revocar de `anon` no basta, las funciones se otorgan a `PUBLIC` por defecto.

**`enterprise`.** Tras las correcciones de esta rama: API keys en SHA-256, contraseñas bcrypt, comparación en tiempo constante, CSP/HSTS/`frame-ancestors 'none'`, CORS desactivado por defecto, `X-Forwarded-For` no confiable sin configuración, guard de arranque para el secreto JWT y contención de rutas locales. Sin las correcciones este rubro era un 5.0.

**Dónde sigue por debajo.** Tres cosas concretas:

1. **La defensa de prompt injection es una lista negra de regex.** `_INJECTION_PATTERNS` busca `ignore previous instructions`, `act as`, `[SYSTEM]`. Eso se evade parafraseando, en otro idioma, o con codificación. `likida.ai` hace lo contrario en `intake/sanitizar.ts`: charset **permitido** y cap de longitud, de modo que un folio real sobrevive intacto y cualquier otra cosa se recorta. Una lista de permitidos no se evade parafraseando.
2. **El rate limiter es por proceso.** Con N workers el límite efectivo es N veces el configurado, y no cruza réplicas.
3. **El parser de CFDI no está endurecido explícitamente.** `etree.parse(xml_path)` con el parser por defecto. Hoy no es explotable —verifiqué que `lxml==6.1.1` no resuelve entidades externas y que libxml2 corta la expansión exponencial—, pero `pyproject.toml` declara `lxml>=4.9`, y en 4.x sí lo sería.

---

## 4. Pruebas — 9.5 vs 8.0

| | likida.ai | enterprise |
|---|---|---|
| Casos | 1 225 en 122 archivos | 935 en ~80 archivos |
| Estado | todas verdes | todas verdes |
| Cobertura | 85,0 % | 81,0 % |
| ¿Es una puerta? | **sí**, umbral en `vitest.config.ts` | **no**, solo se mide |
| Duración | 24 s | 147 s |

La cobertura está a cuatro puntos. Lo que separa a los dos repos es que en `likida.ai` el 85 % **falla el build si baja** y aquí el 81 % es un número que nadie mira.

`likida.ai` además prueba cosas que aquí no se prueban: guardias de ReDoS en el buscador de fundamentos, crecimiento no lineal del deduplicador de CFDI, y comportamiento temporal de la barrera de intake. La suite es offline y determinista **por diseño** —los arneses que gastan dinero viven fuera del include de vitest— y por eso el CI no necesita secretos.

`enterprise` tiene a cambio una batería E2E y multi-tenant más explícita: aislamiento entre despachos, IDOR por id, forzado de scope cuando el cliente manda `tenant_id`, inyección SQL en filtros, exposición de archivos sensibles por HTTP.

---

## 5. Datos y multi-tenancy — 7.5 vs **8.5**

Primer rubro que gana el enterprise.

**`enterprise`.** El aislamiento está construido y **ejercitado**: `tenant_id` en todas las tablas, una API key por despacho resuelta contra la tabla `api_keys`, y el scope se fuerza desde la clave —un tenant que manda `?tenant_id=otro` sigue viendo lo suyo, con prueba de regresión—. Doble backend con Alembic para PostgreSQL y `MIGRATIONS` para SQLite, tablas idénticas entre ambos.

Los dos defectos que encontré en este rubro (la fuga entre tenants del audit log por precedencia SQL, y la conciliación bancaria en un global de proceso) están corregidos y anclados en pruebas.

**`likida.ai`.** El esquema es multi-tenant de verdad: 34 migraciones numeradas y verificadas contra base real, con las 0027 y 0028 dedicadas a corregir alcance por tenant a posteriori (`gasto_img_hash_por_tenant`, `fks_con_tenant`). RLS activa con deny-all por defecto.

Pero el aislamiento en el pipeline **no lo impone la base**: `supabaseAdmin()` usa el service-role, que salta RLS, y el scope depende de poner `.eq('tenant_id', ...)` a mano en cada consulta. Escaneé las 40 cadenas `.from()` bajo service-role: 11 salieron sin `tenant_id` en la ventana y las revisé una por una — todas resultaron legítimas (sondeos de esquema en `startup.ts`, dedup por `wa_message_id` que es único global, y tres falsos positivos donde `liquidaciones` es el bucket de storage, no la tabla `liquidacion`). **No encontré ningún hueco confirmado.**

Lo que baja la nota es que la capa web es single-tenant por configuración: `TENANT()` es `process.env.DEMO_TENANT_ID ?? '11111111-...'`, una constante. El aislamiento multi-tenant está diseñado pero mucho menos ejercitado que en el enterprise, que lo tiene bajo prueba en cada endpoint.

A favor de `likida.ai` en este rubro, un detalle que dice mucho: `config.ts:197` documenta una fuga entre tenants **real** que encontraron y corrigieron — mutar el objeto de configuración del módulo le aplicaba el RFC de una flota a la siguiente, persistiendo mientras viviera la instancia, que Fluid Compute reutiliza entre peticiones y entre tenants.

---

## 6. Producción y operabilidad — 8.5 vs 7.5

**`likida.ai`.** El CI corre cinco puertas —typecheck, lint, pruebas con umbral de cobertura, pruebas de tiempo sin instrumentar, y build— **en todas las ramas**, no solo en `main` y en PRs. El disparador anterior era `branches: [master, main]` y el propio archivo documenta por qué se cambió: el trabajo autónomo aterriza en ramas `claude/*` y sobre ese código no corría nada. Sentry configurado, reporte de configuración silenciosa en el arranque de cada instancia, y un runbook con pruebas.

**`enterprise`.** El Dockerfile es de los mejores que he visto en un MVP: multi-stage, base fijada, usuario no-root, `HEALTHCHECK`, capas cacheables. Hay métricas Prometheus, motor de alertas por tasa de error y latencia, health-check detallado y logging JSON estructurado con `request_id` — más instrumentación en tiempo de ejecución que `likida.ai`.

Lo que lo deja por debajo es la puerta: el CI ahora corre la suite (antes no corría nada), pero solo la suite. No hay linter, ni typechecker, ni umbral de cobertura. Y los 12 hooks de pre-commit que se añadieron —incluidos `detect-private-key` y `check-added-large-files`— **no están en el CI**, así que solo protegen a quien se acuerde de instalarlos localmente. Es la diferencia entre una política y una puerta.

---

## 7. Documentación — 8.0 vs 8.0

Empate, con perfiles opuestos.

`enterprise` gana en documentación **de producto**: `docs/` está ordenado y es utilizable —`architecture.md`, `api-reference.md`, `admin-guide.md`, `developer-guide.md`, `openapi.json` de 200 KB autogenerado, colección Postman con entornos, SDK de Python—. Es lo que se le entrega a un integrador.

`likida.ai` gana en documentación **de decisiones**: `docs/` tiene seis auditorías previas (`auditoria-2` a `auditoria-7`), una carpeta `conocimiento/`, `DOCUMENTO_MAESTRO.md`, `GUIA_BUILD.md` de 23 KB, `FISCAL_LEGAL.md`. Es lo que necesita quien va a modificar el sistema.

Los dos comparten el mismo defecto: la raíz saturada de markdown solapado. `enterprise` tiene 12 archivos, cinco de ellos `QA_REPORT*`; `likida.ai` tiene más de 20, con `AUDIT`, `AUDIT_V2`, `AUDIT_V3`, `ESTADO_FINAL`, `REPORTE_NOCHE`. En ninguno de los dos se puede saber cuál está vigente.

---

## 8. Higiene del repo y disciplina de git — 8.0 vs 5.5

**`likida.ai`.** 233 commits. Los mensajes no describen el diff, describen el hallazgo: *«barrera: el contador aprende a olvidar un `-1` que nunca llegó (0031)»*, *«ci: las dos pruebas de tiempo existían y CI no las corría ni una vez»*, *«dominio: `cuadra.mx` NO ES NUESTRO — estaba impreso en cada PDF de liquidación»*. Con esa historia se puede hacer `git bisect`, revisar por diff y saber cuándo entró un fallo. Resta un `.DS_Store` versionado.

**`enterprise`.** 10 commits para 27 000 líneas, con mensajes de brocha gorda («✨ feat: demo server, landing assets cleanup, CI/deploy updates, billing & LLM improvements» agrupa cinco cambios sin relación). Y tres problemas concretos de higiene:

- **`b2b_ai/api/portal 2.py`** está versionado: un duplicado de Finder, con contenido distinto a `portal.py`, que no importa nadie.
- **La base SQLite y su WAL estaban versionados.** El WAL llegó a 4,1 MB de páginas con datos de facturas, y se recomitó incluso después de que esta rama lo sacara. Además rompe el árbol de quien lo clona: restaurar un WAL sobre una base que ya avanzó hace fallar SQLite con *malformed database schema*, cosa que verifiqué sin querer durante la auditoría.
- **12 markdown solapados en la raíz.**

---

## 9. Dependencias y cadena de suministro — 6.0 vs **9.0**

Segundo rubro que gana el enterprise, y por mucho.

**`enterprise` — `pip-audit`: sin vulnerabilidades conocidas.** `requirements-production.txt` fija cada versión exacta **y anota la CVE que corrige** (`python-multipart==0.0.31 # fix PYSEC-2026-1852, ...`). La superficie es deliberadamente mínima: los JWT se firman con `hmac`/`hashlib` de la stdlib en vez de traer PyJWT, no hay ORM, y las dependencias opcionales están comentadas y separadas.

**`likida.ai` — 4 vulnerabilidades, 3 de severidad alta:**

| Severidad | Paquete | Problema |
|---|---|---|
| alta | `sharp` <0.35.0 | CVEs heredadas de libvips (CVE-2026-33327/33328/35590/35591) |
| alta | `postcss` ≤8.5.17 | XSS por `</style>` sin escapar; lectura arbitraria de archivos |
| alta | `next` | arrastra `postcss` y `sharp` |
| moderada | `@sentry/nextjs` | depende de la versión vulnerable de `next` |

Son 594 rutas de dependencia. A favor: hay lockfile y el CI usa `npm ci`, que falla si el lockfile se desincronizó. En contra: el CI **no corre `npm audit`**, así que estas cuatro llevan ahí sin que nada avise.

---

## 10. Corrección de dominio (fiscal MX) — 9.0 vs 7.5

**`likida.ai`.** Tiene una carpeta `normas/` con los artículos de ley en YAML estructurado: CFF 29-A, CFF 30, CFF 69-B, CFF 89-90, LFPDPPP 2/15/16/26, y criterios no vinculativos. En el código hay 212 referencias legales, contra 60 en el enterprise. Cada módulo del motor de cuadre tiene su prueba emparejada (`complemento_exigibilidad.test.ts`, `flete_no_ampara.test.ts`, `engine_diesel_medio_pago.test.ts`).

El nivel se ve en el análisis de datos sensibles dentro de `sanitizar.ts`: razonan que el campo `producto` de un ticket puede traer *«METFORMINA 850MG 30 TABS»* —dato de salud del titular, art. 2 fr. VI— y que el art. 8 párrafo segundo prohíbe crear bases con datos sensibles sin justificación, con consentimiento que tiene que ser expreso y por escrito, cosa imposible por WhatsApp. Eso no es cumplimiento de checklist; es haber leído la ley.

**`enterprise`.** La cobertura funcional es más ancha: catálogos SAT, validador CFDI 4.0, nómina, contabilidad electrónica, balanza, DIOT, cancelaciones. Pero la corrección estaba menos verificada, y lo demuestra el propio historial: el commit `4e180a1` corrigió cuatro bugs fiscales **reales** que llevaban en el código desde el inicio — el namespace de nómina era `nomina` en vez de `nomina12` (rechazo seguro del PAC), `SubTotal` se igualaba a `Total` en vez de calcularse como percepciones menos deducciones, el IVA solo aceptaba 16 % sin contemplar el 8 % de frontera ni el 0 % de exentos, y el regex de RFC rechazaba los genéricos como `XAXX010101000`.

Que esos cuatro hayan convivido con 833 pruebas en verde dice que la suite cubría el camino feliz del código, no las reglas del SAT.

---

## Cómo cerrar la distancia, por repo

**`enterprise` (7.8 → ~8.6 con tres cambios de un día):**

1. Añadir `ruff` y `mypy` al job de CI que ya existe, y meter los hooks de pre-commit ahí (rubros 2 y 6).
2. `--cov-fail-under=81` en el paso de pruebas: convierte el 81 % en puerta (rubro 4).
3. `git rm 'b2b_ai/api/portal 2.py'`, consolidar los cinco `QA_REPORT*`, y empezar a escribir mensajes de commit que digan qué se descubrió (rubro 8).

Con más trabajo: cambiar la lista negra de prompt injection por un allowlist, endurecer el parser XML, y respaldar el rate limiter en Redis (rubro 3).

**`likida.ai` (8.3 → ~8.8 con dos cambios):**

1. `npm audit --audit-level=high` como paso del CI, y actualizar `sharp`, `postcss` y `next` (rubro 9, el único donde está claramente por detrás).
2. Ejercitar el multi-tenancy: pruebas de aislamiento entre dos tenants sobre las rutas web, y sacar `TENANT()` del entorno hacia la sesión (rubro 5).

---

## Nota sobre el método

Los dos repos se midieron con las mismas herramientas: suite completa ejecutada, cobertura instrumentada, auditoría de dependencias (`pip-audit` / `npm audit`), escaneo del aislamiento por tenant, y lectura dirigida de los puntos donde uno de los dos ya había fallado.

Donde no hay simetría es en la profundidad de la búsqueda activa de fallos: en `enterprise` encontré y verifiqué con prueba de concepto cuatro defectos de severidad crítica y alta; en `likida.ai` sondeé las mismas clases de fallo —secretos con fallback, aislamiento por tenant, contención de rutas, expansión de entidades XML— y no encontré nada equivalente, pero no ejecuté una campaña de igual intensidad. Su 8.3 significa «resiste los sondeos que el otro no resistía», no «está limpio».
