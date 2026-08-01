# PG_BUG_REPORT — Adaptador PostgreSQL

Fecha: 2026-07-31 · Responsable: Leonardo (QA) · Alcance: diagnóstico + guía de fixes (NO aplicados)
Base verificada contra: `b2b_ai/db/db.py`, `b2b_ai/db/pg.py`, `migrations/versions/0001_initial.py`,
y el PostgreSQL real en docker (`127.0.0.1:54329`, db `b2b_ai`).

---

## 0. Ejecutivo

La suite PG (`tests/test_db_pg_integration.py`) corre **4 failed / 2 passed** contra el PG real.
Cada fallo fue reproducido con comando real y su traceback está en la sección correspondiente.

**Las causas raíz reales NO son exactamente las que describía `QA_REPORT_CURRENT.md`.** Verificado leyendo el código actual y corriendo los tests:

| # | Bug (este reporte) | Causa real verificada | QA_REPORT_CURRENT.md decía | ¿Era correcto? |
|---|---|---|---|---|
| 1 | `insert_invoice`: placeholders `:name` de sqlite no traducidos | `SyntaxError: syntax error at or near ":"` | "JSON vacío en columna json" | ❌ Incorrecto |
| 2 | `log_call`: payload vacío se escribe como `''` en columna `jsonb` | `InvalidTextRepresentation ... JSON data line 1: ''` | "payload no serializable" | ⚠️ Parcial (el caso que falla es vacío, no no-serializable) |
| 3 | `upsert_outstanding_invoice`: `ON CONFLICT` sin constraint único en la DB | `no unique or exclusion constraint matching the ON CONFLICT` | "ON CONFLICT sin columna de inferencia" | ❌ Desactualizado (el SQL YA tiene el target) |
| 4 | Deriva de esquema: la DB real no coincide con `migrations/` | `alembic_version=0003_seed`, pero `audit_log.payload`=jsonb y `outstanding_invoices` sin constraint | — | (no lo mencionaba) |

**Veredicto: la capa SQLite/API sigue verde; la capa PG no está lista para entregar hasta aplicar los fixes 1 y 3 (bloqueantes) y el 2 (correcto igualmente).**

---

## 1. BUG P1 — `insert_invoice`: placeholders nombrados `:name` rompen en PostgreSQL

### Archivo / línea
`b2b_ai/db/db.py` — método `insert_invoice`, línea **217**; SQL con placeholders nombrados en líneas **269–274**.

### Código actual
```python
cur = self.conn.execute("""
    INSERT INTO invoices (
        tenant_id, folio_fiscal, archivo, fecha, tipo, serie, folio,
        ...
        erp_poliza, erp_status, status, procesado_en)
    VALUES (
        :tenant_id, :folio_fiscal, :archivo, :fecha, :tipo, :serie, :folio,
        :emisor_rfc, :emisor_nombre, :receptor_rfc,
        ...
        :erp_poliza, :erp_status, :status, :procesado_en)
""", row)          # row es dict
```

### Causa raíz
`db.py` pasa a la capa de datos un dict (`row`) con placeholders **estilo sqlite** `:nombre`.
`qmark_to_percent` (`b2b_ai/db/pg.py:33-66`) **solo** traduce `?` → `%s`. No traduce `:nombre` → `%(nombre)s`.
psycopg3 no acepta la sintaxis `:nombre` y lanza un error de sintaxis antes de ejecutar el INSERT.

### Evidencia (comando + salida real)
```
B2B_DB_URL=postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai \
  .venv/bin/python -m pytest tests/test_db_pg_integration.py::test_folio_unico_pg -v --tb=short
→ psycopg.errors.SyntaxError: syntax error at or near ":"
  LINE 10: :tenant_id, :folio_fiscal, :archivo, :fe...
```
Mismo traceback en `test_aislamiento_multitenant_pg` (ambos llaman a `insert_invoice`).

### Fix sugerido (VERIFICADO en PG y en SQLite)
Opción A (recomendada, mínima): convertir el `VALUES (...)` a placeholders posicionales `?` y pasar `row` como lista, **y** ampliar el `except` de deduplicación para atrapar también `psycopg.errors.UniqueViolation` (hoy solo atrapa `sqlite3.IntegrityError`):

```python
try:
    cur = self.conn.execute("""INSERT INTO invoices (
        tenant_id, folio_fiscal, archivo, fecha, tipo, serie, folio,
        emisor_rfc, emisor_nombre, receptor_rfc,
        subtotal, iva, total, moneda, descripcion,
        categoria, confianza, razon_clasificacion,
        valido, requires_human_review, issues,
        erp_poliza, erp_status, status, procesado_en)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        list(row.values()))   # ← posiciónal, mismo orden que el INSERT
    invoice_id = cur.lastrowid
    inserted = True
    self._bump_version()
except (sqlite3.IntegrityError, PGUniqueViolation):   # ← añadir psycopg.errors.UniqueViolation
    self.conn.rollback()
    existing = self.conn.execute(...)
    invoice_id = existing["id"] if existing else None
    inserted = False
```
> `list(row.values())` preserva el orden: las claves del dict `row` coinciden 1:1 con el orden de columnas del INSERT (verificado en db.py:221-247 vs 250-263).

Opción B (genérica): extender `qmark_to_percent` para mapear `:ident` → `%(ident)s` (psycopg3 acepta `%(name)s` con dict). Traducción verificada:
```
INSERT ... VALUES (:tenant_id, :folio_fiscal)
→ INSERT ... VALUES (%(tenant_id)s, %(folio_fiscal)s)
```
⚠️ Cuidado: la implementación debe respetar casts `::tipo`, literales `'...'::timestamp` y `:` dentro de strings, además de los `?` dentro de literales (el parser actual ya maneja comillas; hay que añadir `:`). Requiere más pruebas que la Opción A.

### Test de reproducción
```bash
cd /Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise
B2B_DB_URL="postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai" \
  .venv/bin/python -m pytest tests/test_db_pg_integration.py::test_aislamiento_multitenant_pg \
  tests/test_db_pg_integration.py::test_folio_unico_pg -v --tb=short
```
Esperado tras el fix: **2 passed** (hoy: 2 failed con `SyntaxError`).

### Prioridad / esfuerzo
**P1** — bloquea todo el pipeline de facturas en producción. Esfuerzo: **S** (1 método + 1 cláusula `except`, o ~10 líneas en `qmark_to_percent`). Este bug es la causa real de 2 de los 4 fallos reportados.

---

## 2. BUG P1 — `log_call`: payload vacío se escribe como `''` en columna `jsonb`

### Archivo / línea
`b2b_ai/db/db.py` — método `log_call`, línea **356**; línea crítica **358**.

### Código actual
```python
def log_call(self, tool_name, action, entity="", entity_id="",
             payload=None, status="ok", tenant_id=None):
    payload_txt = json.dumps(payload, default=str, ensure_ascii=False) if payload else ""
    cur = self.conn.execute("""
        INSERT INTO audit_log(tenant_id, tool_name, action, entity,
            entity_id, payload, status) VALUES (?,?,?,?,?,?,?)
    """, (tenant_id, tool_name, action, entity, entity_id, payload_txt, status))
```

### Causa raíz
Cuando `payload` es `None` (o dict vacío), `if payload else ""` produce **`""`**.
En la DB real la columna `audit_log.payload` es **`jsonb`** (verificado), y `""` no es JSON válido → `InvalidTextRepresentation`.
> El `json.dumps(... default=str)` SÍ maneja dicts con valores no serializables; el caso que realmente falla es el **vacío**, no el no-serializable. `QA_REPORT_CURRENT.md` acertaba en el método, no en el disparador exacto.

### Evidencia (comando + salida real)
```
.venv/bin/python -m pytest tests/test_db_pg_integration.py::test_audit_y_notifications_pg --tb=short
→ psycopg.errors.InvalidTextRepresentation: invalid input syntax for type json
  DETAIL:  The input string ended unexpectedly.
  CONTEXT:  JSON data, line 1:  ''   unnamed portal parameter $6 = ''
```
(El primer `log_call` con `payload={"ok":1}` pasa; el segundo, sin payload, falla.)

### Fix sugerido (VERIFICADO en PG jsonb y en SQLite)
```python
payload_txt = json.dumps(payload, default=str, ensure_ascii=False) \
    if payload is not None else None   # NULL en vez de ''
```
Con esto: `None` → `NULL` (válido en jsonb), `{}` → `'{}'` (JSON válido), dict normal → JSON.

### Test de reproducción
```bash
B2B_DB_URL="postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai" \
  .venv/bin/python -m pytest tests/test_db_pg_integration.py::test_audit_y_notifications_pg -v --tb=short
```
Esperado tras el fix: **1 passed** (hoy: failed).

### Prioridad / esfuerzo
**P1** — el audit log escribe cada llamada de tool; sin esto cada payload vacío tira el registro.
Esfuerzo: **XS** (1 línea).

---

## 3. BUG P1 — `upsert_outstanding_invoice`: `ON CONFLICT` exige un constraint único que la DB no tiene

### Archivo / línea
`b2b_ai/db/db.py` — método `upsert_outstanding_invoice`, línea **627**; SQL en **636–645**.

### Código actual
```python
self.conn.execute(
    "INSERT INTO outstanding_invoices(tenant_id, factura_id, monto, "
    "fecha_vencimiento, dias_vencido, score, updated_at) "
    "VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP) "
    "ON CONFLICT (tenant_id, factura_id) DO UPDATE SET "
    "monto=excluded.monto, fecha_vencimiento=excluded.fecha_vencimiento, "
    "dias_vencido=excluded.dias_vencido, score=excluded.score, "
    "updated_at=CURRENT_TIMESTAMP",
    (tenant_id, factura_id, float(monto), fecha_vencimiento,
     int(dias_vencido), float(score)))
```

### Causa raíz
El SQL **YA trae** el target `ON CONFLICT (tenant_id, factura_id)` (contrario a lo que decía el QA report — el código fue corregido desde entonces). El error real es que la **DB en ejecución no tiene** un constraint único sobre `(tenant_id, factura_id)` en `outstanding_invoices`, que es requisito de PostgreSQL para `ON CONFLICT`.
Verificado: la tabla solo tiene `PRIMARY KEY (id)`.

### Evidencia (comando + salida real)
```
.venv/bin/python -m pytest tests/test_db_pg_integration.py::test_upsert_contracts_pg --tb=short
→ psycopg.errors.InvalidColumnReference: there is no unique or exclusion
  constraint matching the ON CONFLICT specification
```
```
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
 WHERE conrelid='outstanding_invoices'::regclass
→ [('outstanding_invoices_pkey', 'PRIMARY KEY (id)')]     # ← falta el UNIQUE
```

### Fix sugerido (VERIFICADO: con el constraint, el upsert funciona → resultado `(250.0, 5)`)
Es un fix **de esquema**, no de SQL. Como `0001_initial.py` ya define `uq_outstanding_unique` pero la DB ya está sellada en `head` (ver Bug 4), **NO se debe editar `0001_initial.py`** (no re-aplica en una DB ya migrada). Hace falta una migración nueva:

```python
# migrations/versions/0004_outstanding_unique.py (nuevo)
def upgrade():
    op.create_unique_constraint(
        "uq_outstanding_unique",
        "outstanding_invoices",
        ["tenant_id", "factura_id"],
    )
```
Después: `alembic upgrade head` (lo lanza automáticamente `Database.migrate()` al conectar).

> Si la DB ya tuviera filas duplicadas de `(tenant_id, factura_id)`, el constraint fallará; habrá que deduplicar antes.

### Test de reproducción
```bash
B2B_DB_URL="postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai" \
  .venv/bin/python -m pytest tests/test_db_pg_integration.py::test_upsert_contracts_pg -v --tb=short
```
Esperado tras el fix: **1 passed** (hoy: failed).

### Prioridad / esfuerzo
**P1** — la cartera de cobranza (FASE 3) depende de este upsert. Esfuerzo: **S** (1 migración).

---

## 4. Hallazgo de entorno — Deriva de esquema en la DB real (raíz de #2 y #3)

La DB compartida `b2b_ai` **no coincide** con `migrations/`:
- `alembic_version = 0003_seed` (está en `head`), pero
- `audit_log.payload` es **`jsonb`** mientras `0001_initial.py:100` la define `sa.Text()`, y
- `outstanding_invoices` **sin** constraint único mientras `0001_initial.py:230-234` lo define.

Causa probable: `0001_initial.py` fue **modificado después** de que la DB quedó sellada en `head`; `alembic upgrade head` es un no-op y la deriva persiste. Corregir con una migración nueva (0004) que añada el constraint único y, si se desea, alinee `payload` a `jsonb` explícitamente. Alternativa: recrear el contenedor de la DB desde `migrations/` actuales.

### Evidencia
```
SELECT version FROM schema_version;            → (vacío)      # tabla obsoleta (sqlite)
SELECT * FROM alembic_version;                 → [('0003_seed',)]
SELECT data_type FROM information_schema.columns
 WHERE table_name='audit_log' AND column_name='payload';       → jsonb
SELECT conname ... outstanding_invoices ... contype='u';       → []  (ninguno)
```

---

## 5. Hallazgo adicional (INFERIDO, no reproducido) — `with self.conn:` no hace commit en PG

`db.py` usa `with self.conn:` en 12 métodos (p.ej. líneas 530, 608, 648, 683, 723, 738, 816, 841, 878, 917, 1031).
- En SQLite, `with conn:` **hace commit** al salir sin error (semántica estándar de `sqlite3.Connection`).
- En PG, `PGConnection.__exit__` (`pg.py:145-147`) **no hace commit**: solo devuelve la conexión al pool vía `close()`. La transacción abierta se revierte al volver al pool → **posible pérdida de persistencia** en PG.

**No lo pude reproducir** porque el upsert (`test_upsert_contracts_pg`) ya falla antes por el Bug 3. Marcar como riesgo a revisar por Zuck: tras arreglar #3, comprobar que las escrituras en `with self.conn:` persisten en PG (añadir `self.conn.commit()` explícito o cambiar la semántica de `PGConnection.__exit__`).

---

## 6. Verificación de no-regresión sobre SQLite (entregable 2)

- **Baseline SQLite de los métodos afectados:** `tests/test_collections.py tests/test_db.py tests/integration/test_db_integration.py` → **39 passed** (incluye `upsert_outstanding_invoice`, `insert_invoice`, `log_call`).
- **Fix completo aplicado en runtime sobre SQLite** (scratch, sin tocar el repo): `insert_invoice` + `log_call` corregidos pasan `folio_unico` (ins2=False, id1==id2), aislamiento multi-tenant y `log_call` con payload vacío → **OK**.
- Los fixes propuestos usan sintaxis/valores válidos en ambos backends: placeholders `?` (sqlite y PG) y `None` (válido en `TEXT` y `jsonb`). El fix #3 es de esquema y no toca código.
- Los fixes de `insert_invoice`/`log_call` **no** cambian el contrato: misma firma, mismas filas escritas; solo cambian cómo se formatea el parámetro (list vs dict) y el valor de payload vacío (`NULL` en vez de `''`).

---

## 7. Estado (bloque de cierre evidencia)

**✓ Verificado**
- 4 failed / 2 passed en `test_db_pg_integration.py` contra PG real — `.venv/bin/python -m pytest tests/test_db_pg_integration.py -v` → `4 failed, 2 passed`.
- Bug 1: `SyntaxError: syntax error at or near ":"` en `insert_invoice` — traceback real.
- Bug 2: `InvalidTextRepresentation ... JSON data line 1: ''` en `log_call` — traceback real.
- Bug 3: `no unique ... constraint matching the ON CONFLICT` en `upsert_outstanding_invoice`; `outstanding_invoices` solo tiene pkey — query real.
- Bug 4: `alembic_version=0003_seed`; `audit_log.payload`=jsonb — queries reales.
- Fixes verificados en PG (scratch): `?`+`UniqueViolation` en insert_invoice, `NULL` en log_call, upsert con constraint → todos OK.
- Fixes verificados en SQLite (scratch): los mismos → OK; baseline 39 passed.

**? Inferido**
- Bug 5 (`with self.conn:` sin commit en PG): riesgo por lectura de código, **no** reproducido (el test falla antes por Bug 3). Comando que lo movería a verificado: arreglar #3 y luego correr `test_upsert_contracts_pg` comprobando persistencia real tras re-conexión.
- "Editar `0001_initial.py` después de sellar `head`" como causa de la deriva: plausible, no probado con historial git (el directorio no es repo git).

**✗ Incierto / no revisado**
- El resto de la suite de producción PG (`test_pg_backend.py`, `test_pg_migrations.py`, `test_production_*`) no se ejecutó en esta corrida (fuera del alcance de los 4 bugs).
- Duplicados preexistentes de `(tenant_id, factura_id)` en `outstanding_invoices` (podrían bloquear la migración 0004).

**Qué NO prueba esto**
- Que los fixes pasen la **suite completa** de PG: solo se verificaron los tests que ejercitan los 4 métodos afectados.
- Que la capa PG esté lista: quedan pendientes los bugs 1 y 3 (bloqueantes), el 2, y la revisión del hallazgo 5.
