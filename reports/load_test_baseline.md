# Load Test — Enterprise MVP

_Generado el 2026-07-31 20:37:28_

- Endpoints: `stats,invoices,dashboard`
- Facturas sembradas: 400
- Peticiones/usuario/endpoint: 2
- Rate limiter: off (mide rendimiento real de la API)

## Resultados

| Usuarios | Peticiones | OK | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (req/s) |
|---|---|---|---|---|---|---|
| 50 | 300 | 300/300 | 1686.85 | 3046.09 | 3590.78 | 1.94 |
| 100 | 600 | 600/600 | 3301.81 | 4691.44 | 4789.52 | 0.94 |
| 200 | 1200 | 928/1200 | 4105.4 | 6699.05 | 6839.98 | 0.8 |

## Por endpoint

### 50 usuarios

| Endpoint | OK | p50 | p95 | p99 | avg | códigos |
|---|---|---|---|---|---|---|
| stats | 100/100 | 1732.81ms | 3572.41ms | 3667.63ms | 1950.87ms | {200: 100} |
| invoices | 100/100 | 809.36ms | 1221.59ms | 1597.46ms | 848.89ms | {200: 100} |
| dashboard | 100/100 | 1968.2ms | 2264.73ms | 2402.08ms | 1827.96ms | {200: 100} |

### 100 usuarios

| Endpoint | OK | p50 | p95 | p99 | avg | códigos |
|---|---|---|---|---|---|---|
| stats | 200/200 | 3668.57ms | 4663.5ms | 4768.78ms | 3387.55ms | {200: 200} |
| invoices | 200/200 | 1850.95ms | 3425.82ms | 3492.01ms | 2144.86ms | {200: 200} |
| dashboard | 200/200 | 4140.26ms | 4755.28ms | 4815.78ms | 4010.76ms | {200: 200} |

### 200 usuarios

| Endpoint | OK | p50 | p95 | p99 | avg | códigos |
|---|---|---|---|---|---|---|
| stats | 307/400 | 4662.0ms | 6647.88ms | 6782.63ms | 3816.52ms | {0: 93, 200: 307} |
| invoices | 304/400 | 2943.72ms | 5350.56ms | 5448.33ms | 2767.58ms | {0: 96, 200: 304} |
| dashboard | 317/400 | 5795.55ms | 6814.56ms | 6878.77ms | 4617.87ms | {0: 83, 200: 317} |


## Interpretación

- **OK bajo 100%** o **códigos ≠ 200/0**: revisar logs, la autenticación concurrente o locks de SQLite.
- **p99 >> p95**: cola de contención (SQLite WAL o threadpool).
- **Throughput plano al subir usuarios**: el bottleneck es el servidor o la DB, no el cliente.
