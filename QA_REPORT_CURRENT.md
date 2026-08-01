# QA REPORT — Enterprise MVP · Suite de Tests

Fecha: 2026-07-31 · Responsable: Leonardo (QA) · Alance: reporte, sin fixes

---

## 1. Resumen ejecutivo

La suite completa corre **verde por defecto**: 646 tests colectados →
**631 passed · 0 failed · 15 skipped · 2 warnings** en 27.26s.

PERO ese verde es engañoso. Los **15 skipped** son todos tests del adaptador
PostgreSQL (`test_pg_*.py`, `test_db_pg_integration.py`) que se saltan porque
exigen la variable de entorno `B2B_DB_URL`. Al habilitar esa variable contra el
PostgreSQL **real** que ya corre en docker (puerto 54329), **4–5 de esos 15
fallan**. Son bugs reales del adaptador PG, no tests desactualizados.

**Veredicto: la capa SQLite/API está lista; la capa de producción PostgreSQL NO
está lista para entregar.**

---

## 2. Conteo

| Métrica | Valor |
|---|---|
| Total colectados | 646 |
| **Passed** | **631** |
| **Failed** | **0** (en config por defecto) |
| **Skipped** | **15** (todos tests PG por `B2B_DB_URL` ausente) |
| Errors | 0 |
| Warnings | 2 (DeprecationWarnings, no bloqueantes) |
| Tiempo | 27.26s |

### Con PostgreSQL habilitado (`B2B_DB_URL=...b2b_ai`)
| Corrida | Resultado |
|---|---|
| Corrida 1 | 5 failed / 10 passed |
| Corrida 2 | 4 failed / 11 passed |

La variabilidad 4↔5 confirma **dependencia del estado de la DB compartida**
entre tests (flakiness), además de los bugs de SQL.

---

## 3. Top 5 fallos más críticos (nivel PostgreSQL)

Estos fallos NO aparecen en la corrida por defecto (están saltados). Aparecen al
activar `B2B_DB_URL` contra el PG real de docker.

1. **`test_upsert_contracts_pg` (P1) — SQL inválido en PG**
   `upsert_outstanding_invoice` emite
   `ON CONFLICT DO UPDATE` **sin columna de inferencia/constraint**.
   psycopg: `SyntaxError: ON CONFLICT DO UPDATE requires inference
   specification or constraint name`. SQLite tolera `ON CONFLICT DO UPDATE`
   sin objetivo; PostgreSQL exige `ON CONFLICT (columna)`. Bug real en db.py.

2. **`test_aislamiento_multitenant_pg` (P1) — string vacío en columna JSON**
   `insert_invoice` pasa `''` (o JSON mal formado) a un parámetro de tipo
   `json`. psycopg: `InvalidTextRepresentation: invalid input syntax for type
   json, JSON data line 1: ''`. El adaptador sqlite→PG no serializa JSON vacío.

3. **`test_folio_unico_pg` (P1)** — misma causa raíz que #2: falla en
   `insert_invoice` por el mismo error de representación JSON. Confirmado por
   traceback (fallo dentro de `insert_invoice`, `InvalidTextRepresentation`).

4. **`test_audit_y_notifications_pg` (P1)** — falla en `log_call` con
   `payload` JSON. Mismo patrón: escritura de JSON hacia columna `jsonb`/`json`
   con valor no serializable. Confirmado por traceback.

5. **`test_crud_tenants_pg` (P2, flaky)** — `TypeError` relacionado con el
   wrapper `PGRecord`/`PGPool` en una corrida, **pasa en aislamiento y en otra
   corrida completa**. Indica estado compartido (PK/tenant id) entre tests.

> Nota: los `PGRecord`/`PGCursor`/`PGPool` (b2b_ai/db/pg.py) son el puente
> sqlite→PG. Los fallos #1–#4 son de **SQL emitido por db.py**, no del wrapper.
> `qmark_to_percent` en pg.py traduce `?`→`%s` correctamente (los 10 tests de
> pg_backend que pasan lo confirman).

---

## 4. Tests de integración / infraestructura real

### Requieren PostgreSQL real (via `B2B_DB_URL`) — 15 tests SKIPPED por defecto
- `tests/test_pg_backend.py` — 7 tests (qmark→percent, pool, lastrowid, rowcount)
- `tests/test_pg_migrations.py` — 2 tests (migraciones up/down)
- `tests/test_db_pg_integration.py` — 6 tests (crud tenants, aislamiento,
  folio único, audit, upsert contracts)

**El PostgreSQL SÍ está disponible** (docker, puerto 54329, user b2b / db
b2b_ai). Los tests están saltados por una omisión de configuración
(`B2B_DB_URL` no seteada en el entorno de prueba), no por falta de DB.

### Tests de infraestructura real (docker) — SÍ corren
`tests/production/test_infra_postgres_redis.py` conecta a PG (54329) y Redis
(63799) y **pasan**: validan conectividad, transacciones commit/rollback,
aislamiento multi-tenant y operaciones Redis. Estos NO están saltados y
verifican la infra real correctamente.

### API / pipeline de integración
`tests/integration/` (API full pipeline, DB, LLM, notificaciones) pasan.
Nota: en el `.pytest_cache/v/cache/lastfailed` hay entradas históricas de
fallos en API e integración, pero **la corrida actual los aprueba todos** —
esos cacheos son de runs anteriores y ya están resueltos.

---

## 5. Warnings (no bloqueantes)

1. `httpx._models.py: DeprecationWarning` — `content=` vs `data=` en
   `test_security_prod::test_mutacion_por_form_encoded_rechazada`.
2. `starlette/testclient.py: DeprecationWarning` — `cookies=` por-request
   deprecado en `test_security_hardening::test_auth_bypass_medios_alternativos`.

Ambos son del test client (Starlette/httpx), no de la app. Cosmético.

---

## 6. Hallazgo de entorno

- **`.venv` reporta Python 3.9.6, no 3.11** como indica el brief de la tarea.
  (`.venv/bin/python --version` → Python 3.9.6). Relevante para quien dependa
  de features de 3.11+ o pin de dependencias.

---

## 7. Recomendación: qué arreglar primero

Prioridad P1 (bloquea la capa de producción PostgreSQL):

1. **`upsert_outstanding_invoice`** — arreglar `ON CONFLICT DO UPDATE` añadiendo
   la columna de conflict (`ON CONFLICT (factura_id, tenant_id) ...` o el
   constraint correcto). Un fix de 1 línea en db.py.
2. **Escritura de columnas `json`/`jsonb`** — `insert_invoice` y `log_call`
   pasan `''`/dicts a columnas JSON. Serializar con `json.dumps` y manejar
   vacíos (`NULL` en vez de `''`). Cubre #2, #3, #4 de golpe.
3. **Aislar estado entre tests PG** — usar esquema/DB dedicado o truncar entre
   tests (el conftest de producción ya separa DBs por test; replicar ese patrón
   en `test_db_pg_integration.py`). Elimina la flakiness de #5.

P2 (higiene, no bloqueante):
4. Pinar el venv a Python 3.11 (si el objetivo declarado es 3.11) y aclarar el
   contrato de versiones.
5. Quitar los 2 DeprecationWarnings del test client.

**Orden sugerido de ejecución:** #1 y #2 primero (son los que dejan la capa PG
funcional), luego #3 (fiabilidad de la suite). Ninguno afecta la app SQLite/API
actual, que queda **verde y entregable**.

---

## 8. Cómo reproducir

```
# Suite por defecto (verde)
cd /Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise
.venv/bin/python -m pytest tests/ -v --tb=short
# → 631 passed, 15 skipped, 0 failed

# Activar capa PG real para ver los bugs
B2B_DB_URL="postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai" \
  .venv/bin/python -m pytest tests/test_pg_backend.py \
  tests/test_pg_migrations.py tests/test_db_pg_integration.py -v --tb=short
# → 4-5 failed (dependiente del orden)
```
