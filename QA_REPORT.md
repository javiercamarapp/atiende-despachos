# Billion Company — QA: E2E suite + performance benchmarks + security

Fecha: 2026-07-31 · Autor: Leonardo (QA)
Proyecto: B2B-AI-MVP enterprise MVP (`/Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise/`)

## Resumen

Se construyó la suite E2E, benchmarks de performance y hardening de seguridad
que pedía el ticket. Se encontraron y **FIXEARON 2 hallazgos**:

1. **CRÍTICO — Crash bajo carga concurrente** (`b2b_ai/db/db.py`).
2. **MEDIO — XSS almacenado por escape incompleto** en el dashboard
   (`b2b_ai/api/dashboard.py`).

Suite completa: **386 tests, todos pasan**.

---

## 1. E2E test suite — `tests/test_e2e_suite.py`

| Área | Cobertura | Estado |
|---|---|---|
| Flujo completo API | upload multipart → parse → validate → classify → store → report → export (stats.report + dashboard/data) | ✔ |
| Multi-tenant | **3 tenants**, aislamiento de lecturas, stats, detalle por id, IDOR bloqueado | ✔ |
| Batch processing | **100 CFDI** en lote por `process_batch` (vía API) | ✔ |
| Error recovery | corrupto (422), duplicado (insertado=False, sin re-insertar), cancelado (gate exige confirmación humana) | ✔ |
| CLI coverage | `process`, `batch`, `report`, `status`, error→exit≠0 | ✔ |

## 2. Security hardening — `tests/test_security_hardening.py`

| Área | Estado |
|---|---|
| SQL injection | ✔ (ya existía en `test_e2e_security.py`) |
| **XSS** | ✔ nuevo: breakout `</script>`, escape innerHTML, content-type JSON |
| Auth bypass | ✔ nuevo: query string / cookie / Bearer / key con espacios / POST-body → todos 401 |
| Rate limiting | ✔ (ya existía en `test_e2e_security.py`, 429) |
| Secrets scan | ✔ nuevo: repo + `.env.example` + archivos no servidos vía web |

## 3. Performance benchmarks — `scripts/benchmark.py` (ejecutable)

```
=== Benchmark pipeline (300 CFDI) ===
  Throughput : 132.7 CFDI/s
  Latencia   : 7.54 ms promedio por CFDI
  Memoria    : 12.45 MB pico incremental
  Wall       : 2.261 s

=== DB queries/s (5k cada una) ===
  list_invoices   : 384739.9 q/s
  count_invoices  : 862106.1 q/s
  invoice_stats   : 324168.4 q/s
```
(DB en memoria; los QPS de SQLite en memoria son orientativos, no comparables a PG.)

## 4. Load test — `scripts/load_test.py` (ejecutable)

**100 usuarios concurrentes, 300 peticiones a `GET /api/v1/stats`:**
```
OK = 300/300
p50 = 192.81 ms · p95 = 299.88 ms · p99 = 321.59 ms
```

**Batch 10.000 CFDI:**
```
Procesadas 10.000 (válidas 10.000)
Wall 42.77 s · Throughput 233.81 CFDI/s
```

---

## Hallazgos y fixes

### Hallazgo 1 — CRÍTICO: crash (SIGSEGV) bajo carga concurrente
- **Severidad:** CRÍTICA (bloquea el objetivo de "100 usuarios concurrentes").
- **Reproducción:** `scripts/load_test.py --users 100` → el proceso uvicorn moría
  (`Connection refused / Connection reset`) y el servidor se caía.
- **Causa raíz:** `Database` usaba **una sola `sqlite3.Connection`** (`self.conn`)
  compartida por todos los hilos del threadpool de FastAPI. Una conexión SQLite
  no es segura para uso concurrente aunque `check_same_thread=False`; bajo carga
  concurrente crashea. Los tests secuenciales nunca lo exponían.
- **Fix:** `b2b_ai/db/db.py` — conexiones **thread-local** (una por hilo) con
  WAL + `busy_timeout`, migraciones idempotentes por conexión. `close()` cierra
  todas las conexiones. La API pública (`db.conn`) no cambió.
- **Verificación:** re-corrida del load test → **300/300 OK**.

### Hallazgo 2 — MEDIO: XSS almacenado por escape incompleto
- **Severidad:** MEDIA (baja explotabilidad vía flujo real, porque la categoría
  sale de clasificación determinística por reglas, no de input directo).
- **Reproducción:** inyectar `<img onerror>` / `</script><script>` en una factura
  y renderizar el dashboard → el JSON embebido en `<script>` salía crudo y la
  categoría se insertaba por `innerHTML` sin escapar.
- **Fix:** `b2b_ai/api/dashboard.py` — (a) `esc()` que escapa HTML en todo lo que
  se inyecta por `innerHTML` (categoría, mes, folio, emisor, vía); (b) el JSON
  embebido en `<script>` escapa `<`/`>` (`\u003c`) para impedir `</script>` breakout.
- **Verificación:** 3 tests XSS nuevos pasan + suite completa verde.

---

## Estado (skill evidencia)

**✓ Verificado**
- 386/386 tests pasan — `.venv/bin/python -m pytest tests/ -q` → `386 passed`.
- 100 usuarios concurrentes, 300/300 OK, p50=192ms — `scripts/load_test.py`.
- Batch 10.000 CFDI, 233.81 CFDI/s — `scripts/load_test.py --batch 10000`.
- Benchmark 132.7 CFDI/s, 7.54ms, 12.45MB — `scripts/benchmark.py --n 300`.
- Generador de CFDI produce UUIDs únicos — `scripts/gen_cfdis.py` (5/5 únicos verificado).

**? Inferido**
- El fix thread-local no introduce regresión de aislamiento multi-tenant —
  cubierto por tests, pero no probado contra PostgreSQL real (requiere PG).

**✗ Incierto / no revisado**
- Benchmarks de QPS corren contra SQLite en memoria; no son comparables a una
  base de datos de producción (PostgreSQL). Los números de "queries/s" son
  orientativos.
- No se ejecutó el load test contra un despliegue en contenedor (Docker) ni con
  red real; solo contra uvicorn local en `127.0.0.1`.
- No se revisó el frontend `landing/` para XSS (fuera de alcance; el foco fue el
  MVP enterprise y su API/dashboard).

**Qué NO prueba esto**
- Que la suite pase no prueba que la app aguante la carga en producción real
  (latencia de red, múltiples réplicas, PG real). El load test es local y
  single-node.
- El crash de SQLite quedó resuelto, pero se asume WAL correcto en el sistema de
  archivos de destino (macOS local verificado; en Docker/overlayfs conviene
  re-verificar).
