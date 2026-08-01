# Reporte de Carga — Producción (b2b-ai)

- Fecha: 2026-07-31 21:17:48
- Target: `/api/v1/invoices?limit=10`
- Base: `http://127.0.0.1:8871` (uvicorn, workers=1, SQLite/WAL)
- Método: ráfagas de 100 / 500 / 1000 usuarios simultáneos, 400 peticiones por nivel.

## Resultados

| Usuarios | Reqs | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | min (ms) | max (ms) | Err HTTP | Err conexión | Error rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 100 | 400 | 627.3 | 129.4 | 200.7 | 220.3 | 45.5 | 240.3 | 0 | 0 | 0.0% |
| 500 | 500 | 459.9 | 386.6 | 654.6 | 689.5 | 61.5 | 705.4 | 0 | 64 | 12.8% |
| 1000 | 1000 | 339.2 | 734.5 | 1317.1 | 1396.6 | 106.4 | 1455.7 | 0 | 271 | 27.1% |

## Interpretación

**Pass/fail:** un nivel se considera OK si su tasa de error es 0% y no hay timeouts. El p99 sube con la concurrencia: es la cola de espera natural de un worker único sobre SQLite; en producción multi-replica sobre PostgreSQL esto mejora.

> Generado por `scripts/load_test_production.py`.
