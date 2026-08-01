# Auditoría técnica — Likida AI Enterprise (b2b_ai)

**Fecha:** 2026-08-01
**Revisión auditada:** `8fb951b` (rama `claude/repository-audit-j6mhgp`)
**Alcance:** código de aplicación, pruebas, infraestructura de despliegue, seguridad e higiene del repositorio.

> **Estado de las correcciones (2026-08-01).** Los hallazgos 1, 2, 3, 4, 5, 6, 7 y 8 están corregidos en esta misma rama. La suite quedó en **825 pasan, 23 saltadas, 1 xfail documentado**, y las correcciones están ancladas en `tests/test_hallazgos_auditoria.py` para que no puedan deshacerse en silencio. Cada sección de abajo lleva su estado. Los hallazgos 9 a 12 siguen abiertos.

---

## Calificación global: **6.8 / 10** (B−)

| Dimensión | Nota | Comentario |
|---|---|---|
| Arquitectura y estructura | 8.0 | Separación por dominios muy limpia; capa de datos con doble backend SQLite/Postgres |
| Calidad de código y legibilidad | 8.0 | Docstrings excelentes, estilo consistente, SQL parametrizado |
| Seguridad | 5.0 | Buenas decisiones de base, pero un fallo crítico de autenticación y un LFI |
| Pruebas | 7.0 | 833 pruebas es notable; 8 fallan en `main` y hay dependencia de orden |
| Preparación para producción | 5.0 | Estado global en memoria rompe el escalado horizontal; CI despliega sin correr pruebas |
| Documentación | 8.0 | Muy por encima del promedio; una afirmación desactualizada |
| Higiene del repositorio | 5.0 | Artefactos binarios versionados, duplicación, historia de un solo commit |

**Veredicto:** un MVP con alcance y acabado muy superiores al promedio, pero con defectos que impiden sostener hoy la etiqueta *enterprise* multi-tenant. Los cuatro hallazgos altos son acotados y corregibles en pocos días.

---

## Lo que está bien hecho

Vale la pena decirlo antes de la lista de problemas, porque es mucho:

- **Volumen y acabado.** 108 módulos y ~23 900 líneas de aplicación, más ~11 500 líneas de pruebas (833 casos). No es un esqueleto: hay CFDI 4.0, nómina, conciliación bancaria, contabilidad electrónica, cobranza, billing, portal, RBAC y monitoreo implementados de verdad.
- **Docstrings.** Cada módulo abre explicando qué hace, por qué y con qué criterio de diseño. Es la parte más fuerte del repositorio.
- **SQL parametrizado casi al 100 %.** Los `LIMIT` interpolados pasan por `int()`; la única construcción dinámica de columnas (`db.py:1337`) usa una allowlist fija en código y lo documenta. No encontré inyección SQL.
- **Decisiones de seguridad correctas de base:** API keys guardadas como SHA-256, contraseñas con bcrypt, comparación en tiempo constante (`hmac.compare_digest`), CORS **desactivado** por defecto, `X-Forwarded-For` **no confiable** salvo configuración explícita, cabeceras OWASP (HSTS/CSP/`frame-ancestors 'none'`) en middleware propio.
- **Dockerfile de calidad:** multi-stage, base fijada (`python:3.11-slim-bookworm`), usuario no-root, `HEALTHCHECK`, capas cacheables.
- **Infraestructura operativa real:** migraciones Alembic, logging JSON estructurado con `request_id`, métricas Prometheus, motor de alertas, audit trail automático de mutaciones, feature flags.

---

## Hallazgos

### 🔴 CRÍTICO — 1. Secreto JWT de desarrollo como fallback silencioso · ✅ CORREGIDO

**`b2b_ai/auth/middleware.py:42-47`**

```python
_DEV_SECRET = "b2b-ai-dev-jwt-secret-no-usable-en-produccion"

def jwt_secret() -> str:
    return os.environ.get(_ENV_SECRET, "") or _DEV_SECRET
```

Si `B2B_JWT_SECRET` no está definido, la aplicación **arranca igual** y firma y valida tokens con un secreto público que está en el repositorio. No hay ninguna verificación al inicio (`grep` sobre `app.py` no encuentra ningún guard de entorno).

**Impacto:** cualquiera que lea el repositorio puede forjar un token de acceso con `tenant_id` y `role` arbitrarios y suplantar al administrador de cualquier despacho. Un despliegue con un `.env` incompleto — el fallo de configuración más común que existe — queda totalmente abierto.

Nota: la propia prueba del repositorio lo detecta y está fallando (`tests/test_security_hardening.py::test_secrets_scan_repo`).

**Corrección:** eliminar el fallback. Si `B2B_JWT_SECRET` no existe o mide menos de 32 bytes, abortar el arranque en producción; permitir un secreto efímero generado con `secrets.token_urlsafe()` solo cuando `B2B_ENV` sea explícitamente de desarrollo.

---

### 🟠 ALTO — 2. Lectura de archivos arbitrarios del servidor vía `xml_path` / `folder` · ✅ CORREGIDO

**`b2b_ai/api/app.py:541-546` y `1043-1053`**

```python
xml_path = (payload or {}).get("xml_path")
if xml_path:
    if not os.path.exists(xml_path):
        raise HTTPException(404, ...)
    res = process_file(xml_path, db=db, tenant_id=tenant)
```

La ruta viene del cuerpo de la petición y solo se comprueba que exista. No hay directorio base, ni normalización, ni contención.

**Verificado:** con una API key válida, `POST /api/v1/invoices/process {"xml_path": "/ruta/fuera/de/uploads/otro.xml"}` devolvió **200** y persistió el contenido en la base del atacante. Con `/etc/passwd` la excepción se propaga sin capturar (ver hallazgo 6).

**Impacto:** cualquier tenant autenticado puede leer **cualquier XML del servidor**, incluidos los CFDI en disco de otros despachos, e importarlos a su propio tenant para luego consultarlos vía `GET /api/v1/invoices`. `folder` permite además sondear el sistema de archivos (404 frente a 200 revela existencia de directorios).

**Corrección:** eliminar `xml_path`/`folder` de la API pública — el flujo real es multipart, que ya está bien resuelto — o resolver contra un directorio base fijo y rechazar todo lo que caiga fuera tras `Path.resolve()`.

---

### 🟠 ALTO — 3. Fuga entre tenants en la búsqueda del audit log (precedencia SQL) · ✅ CORREGIDO

**`b2b_ai/audit/trail.py:113-119`**

```python
q = ("SELECT * FROM audit_entries WHERE "
     "action LIKE ? OR resource LIKE ? OR resource_id LIKE ? "
     "OR details LIKE ? OR user_id LIKE ? OR ip LIKE ?")
if tenant_id is not None:
    q += " AND tenant_id=?"
```

`AND` liga más fuerte que `OR`, así que el filtro por tenant solo se aplica a la última rama (`ip LIKE ? AND tenant_id=?`). Las otras cinco condiciones devuelven filas de **todos** los tenants.

**Impacto:** el audit log es precisamente el registro que debe estar aislado. Un despacho que busque "invoice" ve entradas de auditoría de otros despachos: identificadores de factura, usuarios, IPs.

Falla ya en `tests/test_audit.py::test_search_audit_log` (devuelve 3, espera 2).

**Corrección:** envolver el bloque `OR` en paréntesis:
```python
q = ("SELECT * FROM audit_entries WHERE (action LIKE ? OR ... OR ip LIKE ?)")
```

---

### 🟠 ALTO — 4. Estado de conciliación bancaria en un global de proceso · ✅ CORREGIDO

**`b2b_ai/api/reconciliation.py:33-40`**

```python
_SESSIONS: dict = {}

def _session(tenant_id) -> BankReconciliation:
    key = tenant_id if tenant_id is not None else "global"
    if key not in _SESSIONS:
        _SESSIONS[key] = BankReconciliation(...)
    return _SESSIONS[key]
```

El diccionario vive a nivel de módulo, no está ligado a la instancia de aplicación ni a la base de datos, y nunca se purga.

**Consecuencias, en orden de gravedad:**

1. **Se rompe con más de un worker.** El `Dockerfile` documenta `B2B_WORKERS=$(nproc)` con Postgres. Si la subida del estado de cuenta llega al worker A y el informe al worker B, el informe sale vacío. La función entera es inservible en cualquier despliegue multi-worker o con réplicas.
2. **Crecimiento de memoria sin límite.** Los movimientos bancarios se acumulan en RAM por tenant y no se liberan jamás.
3. **Pérdida de datos al reiniciar.**
4. **Fuga de estado entre instancias**, que es lo que hacen visible las pruebas: `test_report_endpoint_sin_movimientos` reporta `movimientos_banco: 9` sobre una base recién creada, y `test_report_endpoint_con_movimientos` espera 3 y obtiene 12.

**Corrección:** persistir los movimientos y los emparejamientos en la base de datos con `tenant_id`, igual que el resto del dominio.

---

### 🟡 MEDIO — 5. El CI despliega a producción sin ejecutar las pruebas · ✅ CORREGIDO

**`.github/workflows/deploy.yml`**

El workflow tiene dos jobs, `deploy-landing` y `deploy-api`, y ninguno instala dependencias ni ejecuta `pytest`. Cualquier push a `main` va directo a Vercel y Railway.

Hoy mismo eso significaría desplegar con **8 pruebas en rojo**, dos de las cuales señalan los hallazgos 3 y 4.

**Corrección:** un job `test` que corra la suite y del que dependan los dos de despliegue (`needs: test`).

---

### 🟡 MEDIO — 6. Excepción sin capturar en la ruta JSON de `/api/v1/invoices/process` · ✅ CORREGIDO

**`b2b_ai/api/app.py:546`**

La rama multipart captura `CFDIError` y responde 422 correctamente (líneas 525-528). La rama JSON llama a `process_file` sin protección, así que un XML malformado — un archivo truncado, el caso más común del mundo — produce una excepción no controlada que atraviesa toda la pila de middleware y termina en un 500.

**Corrección:** reutilizar el mismo `try/except CFDIError` de la rama multipart.

---

### 🟡 MEDIO — 7. El limitador de peticiones crece sin límite y no cruza procesos · ⚠️ CORREGIDO EN PARTE

**`b2b_ai/api/app.py:247-265`**

`self._hits` es un `defaultdict` con clave `(ip, ruta)`. Las marcas de tiempo caducadas se podan, pero **las claves nunca se eliminan**. Un atacante que pida rutas aleatorias hace crecer el diccionario indefinidamente: agotamiento de memoria a través del propio mecanismo antiabuso.

Además, al ser estado por proceso, el límite efectivo se multiplica por el número de workers y no funciona entre réplicas.

**Corrección:** purgar las claves con la lista vacía y respaldarlo en Redis (ya está en `docker-compose.prod.yml`) para el despliegue multi-instancia.

---

### 🟡 MEDIO — 8. Base SQLite versionada en git · ✅ CORREGIDO

`b2b_ai.db-wal` (4,1 MB) y `b2b_ai.db-shm` están rastreados. El `.gitignore` cubre `*.db` pero no los archivos auxiliares del modo WAL.

El contenido inspeccionado es de demostración (RFC ficticios, `despacho@b2b-ai.local`), así que no hay filtración real hoy. El problema es el patrón: el mismo descuido sobre una base de trabajo publica datos fiscales de clientes de forma irreversible en la historia de git.

**Corrección:** `git rm --cached b2b_ai.db-wal b2b_ai.db-shm` y añadir `*.db-wal`, `*.db-shm`, `*.db-journal` al `.gitignore`.

---

### 🔵 BAJO — 9. Manejo de errores demasiado permisivo · ABIERTO

84 bloques `except Exception` en `b2b_ai/`, de los cuales 18 son un `pass` silencioso. En los caminos best-effort (auditoría, notificaciones) es una decisión defendible y está comentada. En `api/auth.py:57`, en cambio, un fallo de base de datos al resolver una API key se convierte en un 401 indistinguible de una key inválida, lo que hará que un incidente de base de datos se diagnostique como problema de autenticación.

---

### 🔵 BAJO — 10. Ruta duplicada y muerta · ABIERTO

`/portal/invoices/export.csv` está definida dos veces: en `api/portal.py:379` y en `portal/routes.py:328`. Como `build_portal_router` se registra antes (`app.py:973`) que `build_portal_pages_router` (`app.py:979`), la segunda nunca se ejecuta.

---

### 🔵 BAJO — 11. Afirmación desactualizada sobre XXE · ABIERTO

`requirements-production.txt` afirma «defusedxml usado para DOMParse». **`defusedxml` no está en las dependencias ni se importa en ningún sitio.** `b2b_ai/cfdi/parser.py:86` usa `etree.parse(xml_path)` con el parser por defecto de lxml.

Para ser justos: **verifiqué que hoy no es explotable.** Con `lxml==6.1.1` las entidades externas no se resuelven (mi prueba con `SYSTEM "file://…"` falló con *Entity not defined*) y libxml2 corta la expansión exponencial (*Maximum entity amplification factor exceeded*). El riesgo es latente: `pyproject.toml` declara `lxml>=4.9`, y en 4.x/5.x el parser por defecto sí resuelve entidades externas, de modo que una instalación desde `pyproject` en lugar de `requirements-production.txt` reintroduce el XXE.

**Corrección:** un parser explícito — `etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)` — y corregir el comentario.

---

### 🔵 BAJO — 12. Higiene del repositorio · ⚠️ ABIERTO EN PARTE

- Cinco informes de QA en la raíz (`QA_REPORT.md`, `QA_REPORT_CURRENT.md`, `QA_REPORT_FINAL.md`, `QA_REPORT_LANDING_FIX.md`, `PG_BUG_REPORT.md`) más `reports/`. Es imposible saber cuál está vigente.
- `landing/` (13 MB) y `landing-b/` (3,8 MB) conviven con `index.html` distintos; el CI solo despliega `landing/`. `landing-b/` está sin usar.
- `deploy.sh` duplicado en la raíz y en `scripts/`; `DEPLOY.md`, `README-DEPLOY.md` y `docs/DEPLOYMENT.md` se solapan.
- Toda la historia es un único commit («Initial commit… 631 tests»). Sin historia no hay `git bisect`, ni revisión por diff, ni forma de saber cuándo se introdujo un fallo. El propio mensaje ya está desactualizado: la suite tiene 833 casos.

---

## Estado de las pruebas

Suite ejecutada con Python 3.11 y las dependencias de `requirements-production.txt`:

```
8 failed, 802 passed, 23 skipped in 125.07s
```

| Prueba fallida | Causa |
|---|---|
| `test_audit.py::test_search_audit_log` | Hallazgo 3 (fuga entre tenants) — **fallo real** |
| `test_bank_reconciliation.py` ×3 | Hallazgo 4 (estado global) — **fallo real**, dependiente del orden |
| `test_security_hardening.py::test_secrets_scan_repo` | Hallazgo 1 (secreto JWT) — **fallo real** |
| `test_portal.py` ×3 | Pruebas desactualizadas: esperan JSON en `/portal/invoices`, que hoy es una página HTML; el endpoint JSON es `/portal/invoices.json` |

Cinco de los ocho fallos apuntan a defectos genuinos de la aplicación, no a ruido de entorno. Las pruebas de conciliación además dependen del orden: pasan en aislamiento y fallan al ejecutarse junto a las demás del mismo archivo, síntoma directo del hallazgo 4.

---

## Qué se corrigió y cómo

Todo lo de abajo está en esta rama. La suite quedó en **825 pasan, 23 saltadas, 1 xfail**.

| # | Corrección | Archivos |
|---|---|---|
| 1 | Se elimina el literal de desarrollo. `jwt_secret()` exige `B2B_JWT_SECRET` de ≥32 caracteres; sin ella lanza salvo en entorno de desarrollo, donde genera un secreto aleatorio por proceso. `create_app` llama a `check_jwt_config()`, así que un despliegue mal configurado muere en el import y no sirve tráfico | `auth/middleware.py`, `api/app.py` |
| 2 | La ingesta por ruta local pasa a ser opt-in y confinada: `B2B_LOCAL_XML_DIRS` lista los roots permitidos, `_resolve_local_path()` resuelve symlinks y `..` antes de comparar y devuelve 403 sin eco de la ruta. Vacía (por defecto) = 400 | `api/app.py` |
| 3 | Paréntesis alrededor del bloque `OR` | `audit/trail.py` |
| 4 | El estado se persiste en `bank_transactions` / `bank_confirmations`, con índice único por `(tenant, tx_id)` para que resubir no duplique. `_session()` reconstruye el servicio desde la base en cada petición. `/report` ya no depende de que alguien haya llamado antes a `/matches` | `api/reconciliation.py`, `db/db.py`, `db/models.py` (migración 13), `migrations/versions/0005_*.py` |
| 5 | Job `test` del que dependen los dos de despliegue (`needs: test`), corriendo también en `pull_request`, contra las dependencias **fijadas** de producción | `.github/workflows/deploy.yml` |
| 6 | La rama JSON captura `CFDIError` → 422, igual que la multipart | `api/app.py` |
| 7 | Barrido periódico de claves caducadas en `RateLimiter` | `api/app.py` |
| 8 | `git rm --cached` de los auxiliares WAL y `*.db-wal`/`*.db-shm`/`*.db-journal` en `.gitignore` | `.gitignore` |

Las correcciones están ancladas en **`tests/test_hallazgos_auditoria.py`** (16 pruebas): que el arranque falle sin secreto, que no quede ningún literal de desarrollo en el código, que una ruta fuera de los roots no importe el archivo ni filtre la ruta en el mensaje, que `..` no escape, que la búsqueda de auditoría no cruce tenants, que la conciliación sobreviva a una instancia nueva y no se filtre entre bases ni entre tenants, y que el limitador no crezca con el número de rutas distintas.

### Lo que deliberadamente NO se tocó

**El hallazgo 7 queda a medias.** El barrido cierra la fuga de memoria, pero el limitador sigue siendo **por proceso**: con N workers el límite efectivo es N veces el configurado, y no cruza réplicas. Respaldarlo en Redis (ya está en `docker-compose.prod.yml`) es un cambio de infraestructura aparte.

**`test_match_ai_fallback_tokens` queda como `xfail`, no arreglado.** Es un fallo real y preexistente, pero salir de él exige decidir entre medir contención en vez de Jaccard en `_token_overlap`, bajar el umbral de 55 del paso IA, o aceptar que ese caso no cruce. Las tres cambian la precisión de la conciliación bancaria, que tiene consecuencias en dinero. La razón está escrita en el propio `xfail`.

**Los hallazgos 9 a 12 siguen abiertos:** los `except Exception` demasiado anchos, la ruta duplicada muerta, el parser XML sin endurecer explícitamente y la duplicación de documentación y de `landing/`.

---

## Plan restante

1. Respaldar el rate limiter en Redis (cierra el hallazgo 7).
2. Decidir la métrica de similitud del cruce bancario y quitar el `xfail`.
3. Parser XML explícito: `etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)` y corregir el comentario de `requirements-production.txt` que menciona un `defusedxml` que no se usa (hallazgo 11).
4. Estrechar los `except Exception` de los caminos que no son best-effort, empezando por `api/auth.py:57`, donde un fallo de base de datos se presenta como un 401 (hallazgo 9).
5. Borrar la ruta duplicada `/portal/invoices/export.csv` de `portal/routes.py`, que está muerta (hallazgo 10).
6. Consolidar los cinco `QA_REPORT*.md` y eliminar `landing-b/` (hallazgo 12).
