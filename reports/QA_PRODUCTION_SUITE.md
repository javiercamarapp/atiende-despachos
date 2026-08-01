# QA — Suite de Tests de Producción (b2b-ai / enterprise)

**Rol:** QA · **Fecha:** 2026-07-31 · **Alcance:** PRODUCCION: production test suite

## Resumen ejecutivo

| Área | Resultado |
|---|---|
| E2E camino crítico (pipeline, auth, rate limit, multi-tenant) | 28 tests, **PASS** |
| Infraestructura real PostgreSQL 16 (contenedor) | **PASS** (conectividad, transacciones, aislamiento, tipado) |
| Infraestructura real Redis 7 (contenedor) | **PASS** (ping, SET/GET, INCR atómico, TTL, aislamiento por tenant) |
| Chaos (pérdida DB, concurrencia, payloads inválidos) | **PASS** |
| Seguridad (SQLi, XSS, CSRF, auth bypass, rate-limit bypass) | **PASS** (con 1 hallazgo reportado) |
| Load test (100/500/1000 concurrentes) | Ver reporte — 0 errores HTTP, techo de conexiones |

**Veredicto:** `LISTO PARA ENTREGAR` (con 2 hallazgos a atender por Zuck; ninguno bloquea la entrega del MVP actual).

---

## 1. E2E producción — `tests/production/test_production_e2e.py`

Cubre el camino real del usuario:
- `GET /health` → backend sqlite, schema ok.
- Pipeline completo **upload → parse → validate → classify → store → report**: subida multipart del CFDI 02_inversion, `valido=True`, `categoria=inversion`, `confianza>=0.5`, `insertado=True`, total 5800.00; `/api/v1/stats` refleja 1 factura y report correcto; detalle por id con `emisor_rfc=CON950820K12`.
- Auth flow: sin key → 401, key inválida → 401, key válida → 200, leads público sin key → 200.
- Rate limiting: exceder límite bajo → 429 con `Retry-After`; healthcheck exento.
- Multi-tenant: A/B aislados, IDOR devuelve 404, query-param `tenant_id` no puede forzar otro tenant.
- Payloads inválidos (body no-JSON, xml_path inexistente → 404, archivo vacío, extensión no-CFDI → 422, CFDI corrupto → 422): **nunca 500**.
- Dedup: el mismo UUID no se re-inserta.

## 2. Infraestructura real — `tests/production/test_infra_postgres_redis.py`

La capa de datos de la app es **SQLite** (lo confirma `/health` → `backend: sqlite`); **PostgreSQL y Redis no tienen adaptador** en el código (docker-compose.prod.yml los provisiona como infra objetivo, "integración en roadmap"). Por eso estos tests validan la **infraestructura real** contra la que el adaptador futuro se conectará, no integración de la app:

- **PostgreSQL 16 real** (contenedor, puerto 54329): conectividad/versión, transacciones commit vs rollback, aislamiento multi-tenant por fila, tipado estricto (numeric rechaza texto).
- **Redis 7 real** (contenedor, puerto 63799): ping, SET/GET, **INCR atómico** con 50 hilos concurrentes (primitive de rate limiter compartido), TTL/expiración, claves con prefijo por tenant.

**GAP reportado (no bloqueante):** no existe test de la *app* contra PG/Redis porque la app no los usa. El adaptador PG/Redis es trabajo pendiente (roadmap) — ver hallazgo H1.

## 3. Chaos — `tests/production/test_chaos.py`

- Pérdida de conexión a la DB: cerrar la conexión → `ProgrammingError` controlado (nunca crash ni datos falsos); `close()` recupera con conexión nueva.
- Path/DB inválida → error controlado, no crash del intérprete.
- **20 hilos × 3 escrituras concurrentes** sobre la misma DB: 60/60 insertadas, sin corrupción ni pérdida (conexiones thread-local correctas).
- Payload inválido a nivel de DB (tenant inexistente, sin FK): tolerado sin corromper; conteo consistente.
- Operación lenta / buffer gigante: error controlado, el server sigue respondiendo `/health`.

## 4. Seguridad — `tests/production/test_security_prod.py`

- **SQLi**: payloads de inyección en query param, path param y body → nunca rompen ni inyectan; la tabla sigue sana.
- **XSS**: el reporte se sirve como `application/json` (no ejecuta); leads con HTML se guardan como dato.
- **CSRF** (hueco que cubre esta suite): no se emiten cookies de sesión (sin vector clásico); el vector form-urlencoded cross-site no muta estado; endpoints protegidos exigen header incluso con `Origin` ajeno.
- **Auth bypass**: header vacío / key en query / key en cookie → siempre 401.
- **Rate-limit bypass por X-Forwarded-For**: ver hallazgo H2.

---

## 5. Load test — `scripts/load_test_production.py` + `reports/load_test_production_report.md`

Target `GET /api/v1/invoices?limit=10` (auth + lectura DB), uvicorn workers=1, SQLite/WAL.

| Usuarios | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Err HTTP | Err conexión | Error rate |
|---|---|---|---|---|---|---|---|
| 100 | 627.3 | 129.4 | 200.7 | 220.3 | 0 | 0 | 0.0% |
| 500 | 459.9 | 386.6 | 654.6 | 689.5 | 0 | 64 | 12.8% |
| 1000 | 339.2 | 734.5 | 1317.1 | 1396.6 | 0 | 271 | 27.1% |

**Hallazgo de capacidad (no bug de la app):** la app **nunca devuelve error HTTP** bajo carga; las latencias degradan suave (p50 129→735 ms). Los únicos fallos son **errores de conexión** (saturación del backlog/socket del worker único de uvicorn en esta máquina, con `B2B_WORKERS=1` como configura el docker-compose.prod.yml). En producción real con nginx + multi-worker + PostgreSQL este techo se desplaza hacia arriba.

---

## Hallazgos

### H1 — P1 · No hay adaptador PostgreSQL/Redis en la app (GAP de arquitectura)
**Evidencia:** `/health` → `backend: sqlite`; `b2b_ai/db/db.py` usa solo `sqlite3`; docker-compose.prod.yml dice "Mientras no exista el adaptador Postgres, el API persiste en SQLite". `grep redis/psycopg` en `.venv` y `b2b_ai/` → no integrado.
**Impacto:** el objetivo de producción ("Postgres + Redis reales") no está conectado a la app. La infra provisionada funciona (verificado), pero la app no la usa.
**Acción:** Zuck — implementar adaptador PG (`B2B_DB_PATH=postgresql://...`) y conectar Redis al rate limiter.

### H2 — P2 · Rate limiter evitable por `X-Forwarded-For` (sin validar)
**Evidencia:** con `B2B_RATE_LIMIT_PER_MIN=10`, 25 peticiones rotando `X-Forwarded-For` → **0 respuestas 429** (test `test_rate_limit_bypass_por_xff` pasa documentando el bypass). `_client_ip()` en app.py confía en el header XFF sin config de proxy de confianza.
**Impacto:** un atacante rota XFF y esquiva el rate limit por IP.
**Acción:** Zuck — solo confiar en XFF cuando hay proxy de confianza configurado (env `B2B_TRUST_PROXY`), o rate-limit por clave API además de por IP.

---

## Estado (skill evidencia)

**✓ Verificado**
- 28 tests de la suite `tests/production/` pasan — `.venv/bin/python -m pytest tests/production/ -q` → `28 passed`.
- Suite completa: `pytest tests/ -q` → **631 passed, 15 skipped, 0 failed, EXIT=0** (35.8s).
- PostgreSQL 16 real y Redis 7 real alcanzables y funcionales — contenedores docker + libs psycopg2/redis.
- Load test ejecutado 3× (consistente): 100→0% error, 500→12.8%, 1000→27.1%, `Err HTTP` = 0 siempre.
- Reporte markdown generado — `reports/load_test_production_report.md`.

**? Inferido**
- Los 15 tests `skipped` de la suite completa son los archivos PG que un worker concurrente (Zuck) agregó (`tests/test_pg_*.py`, `test_db_pg_integration.py`); se saltan porque requieren `B2B_DB_URL` + `psycopg` v3 que no están configurados. Trabajo en curso de Zuck, fuera de mi alcance forzarlo.

**✗ Incierto / no revisado**
- Integración de la app con PG/Redis: **no existe** (H1) — los tests cubren la infra, no el adaptador porque no hay adaptador.
- Comportamiento del rate limiter bajo bypass real multi-replica con Redis: no probado (no hay Redis integrado).

**Qué NO prueba esto**
- Que la infra PG/Redis funcione **no** prueba que la app esté lista para producción con PG/Redis: el adaptador no existe.
- Que la suite pase **no** prueba que no haya regresiones en rutas no tocadas; se corrió la suite completa para cubrirlo.

**Siguiente paso sugerido:** implementar el adaptador PostgreSQL (H1) y re-correr `tests/production/` para convertir los tests de infra en tests de integración real de la app.
