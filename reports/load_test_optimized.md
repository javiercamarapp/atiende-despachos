# Load Test — Enterprise MVP

_Generado el 2026-07-31 20:57:02_

- Endpoints: `stats,invoices,dashboard,dashboard_summary,dashboard_monthly`
- Facturas sembradas: 600
- Peticiones/usuario/endpoint: 2
- Rate limiter: off (mide rendimiento real de la API)

## Resultados

| Usuarios | Peticiones | OK | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (req/s) |
|---|---|---|---|---|---|---|
| 50 | 500 | 500/500 | 2477.78 | 6671.11 | 7773.73 | 17.15 |
| 100 | 1000 | 1000/1000 | 2394.75 | 13858.66 | 15109.7 | 18.01 |
| 200 | 2000 | 1520/2000 | 1894.07 | 17859.3 | 19026.16 | 23.82 |

## Por endpoint

### 50 usuarios

| Endpoint | OK | p50 | p95 | p99 | avg | códigos |
|---|---|---|---|---|---|---|
| stats | 100/100 | 1087.86ms | 2600.3ms | 2713.74ms | 1206.89ms | {200: 100} |
| invoices | 100/100 | 863.59ms | 972.36ms | 1010.64ms | 857.68ms | {200: 100} |
| dashboard | 100/100 | 1592.74ms | 2754.12ms | 2830.74ms | 1326.53ms | {200: 100} |
| dashboard_summary | 100/100 | 6003.81ms | 7774.07ms | 7855.83ms | 5617.03ms | {200: 100} |
| dashboard_monthly | 100/100 | 4605.82ms | 6531.89ms | 6834.68ms | 4884.34ms | {200: 100} |

### 100 usuarios

| Endpoint | OK | p50 | p95 | p99 | avg | códigos |
|---|---|---|---|---|---|---|
| stats | 200/200 | 1374.54ms | 2502.18ms | 2541.31ms | 1266.96ms | {200: 200} |
| invoices | 200/200 | 1400.88ms | 1822.11ms | 2515.74ms | 1368.66ms | {200: 200} |
| dashboard | 200/200 | 2135.99ms | 5038.54ms | 5172.2ms | 2234.84ms | {200: 200} |
| dashboard_summary | 200/200 | 11505.75ms | 15110.13ms | 15548.04ms | 10833.63ms | {200: 200} |
| dashboard_monthly | 200/200 | 9909.75ms | 13113.72ms | 14628.61ms | 9929.9ms | {200: 200} |

### 200 usuarios

| Endpoint | OK | p50 | p95 | p99 | avg | códigos |
|---|---|---|---|---|---|---|
| stats | 304/400 | 757.56ms | 2933.24ms | 3542.21ms | 1092.98ms | {0: 96, 200: 304} |
| invoices | 304/400 | 1697.85ms | 3683.74ms | 4356.9ms | 1624.93ms | {0: 96, 200: 304} |
| dashboard | 304/400 | 974.42ms | 15481.39ms | 18233.32ms | 3313.19ms | {0: 96, 200: 304} |
| dashboard_summary | 304/400 | 15511.57ms | 18868.8ms | 19270.92ms | 10946.58ms | {0: 96, 200: 304} |
| dashboard_monthly | 304/400 | 15732.16ms | 18276.03ms | 19081.37ms | 11032.92ms | {0: 96, 200: 304} |


## Interpretación

- **OK bajo 100%** o **códigos ≠ 200/0**: revisar logs, la autenticación concurrente o locks de SQLite.
- **p99 >> p95**: cola de contención (SQLite WAL o threadpool).
- **Throughput plano al subir usuarios**: el bottleneck es el servidor o la DB, no el cliente.
