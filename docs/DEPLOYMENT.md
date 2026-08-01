# Deployment — Likida AI Enterprise (enterprise MVP)

Guía para desplegar el agente contable IA en producción (VPS con Docker).
Stack objetivo: **API FastAPI (uvicorn) + PostgreSQL + Redis + Nginx**.

> **Estado de la base de datos.** La capa de datos (`b2b_ai/db/db.py`) es
> actualmente **SQLite-backed**. El stack de producción provisiona PostgreSQL y
> Redis como infraestructura objetivo, pero **el API todavía persiste en
> SQLite** sobre un volumen. La migración a Postgres requiere escribir el
> adaptador (ver [Base de datos → roadmap](#base-de-datos-roadmap)). Este
> documento describe el deploy que funciona hoy (SQLite en volumen) y deja
> listo el camino hacia el stack completo.

---

## 1. Requisitos del servidor

| Requisito | Mínimo | Recomendado |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2–4 GB |
| Disco | 10 GB | 20 GB (SSD) |
| SO | Ubuntu 22.04 / Debian 12 | idem |
| Docker | 24+ | 26+ |
| Docker Compose | v2 | v2 |

Red: puertos **80** (HTTP) y **443** (HTTPS, opcional) abiertos al público.
Nada más se expone: el API escucha solo en la red interna Docker.

El volumen de datos SQLite (`b2b-data`) crece con las facturas procesadas; los
CFDI suelen pesar pocos KB, pero planifica backup diario (ver §6).

## 2. Estructura de archivos de deploy

```
enterprise/
├── Dockerfile                 # build multi-stage de la API
├── docker-compose.prod.yml    # stack de producción
├── .env.production.example    # plantilla de configuración (copiar a .env.production)
├── .env.production            # config REAL (NO versionar; chmod 600)
├── nginx/
│   └── nginx.conf             # reverse proxy (HTTP + bloque TLS comentado)
├── scripts/
│   ├── health-check.sh        # verifica salud de los servicios
│   └── deploy.sh              # build + up + healthcheck
└── docs/DEPLOYMENT.md         # este documento
```

## 3. Pasos de deploy

### 3.1 En tu máquina de desarrollo

1. Prueba que los tests pasan antes de desplegar:
   ```bash
   ./test.sh
   ```

### 3.2 En el VPS

1. **Instala Docker** (si no está):
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker "$USER"   # y reloguéate
   ```

2. **Sube el código** del repo a `/opt/b2b-ai` (o `git clone`):
   ```bash
   rsync -avz --exclude=.venv --exclude=.git \
     --exclude='*.db*' --exclude=.env \
     /ruta/local/enterprise/ user@IP:/opt/b2b-ai/
   ```

3. **Crea la configuración de producción**:
   ```bash
   cd /opt/b2b-ai
   cp .env.production.example .env.production
   vi .env.production
   chmod 600 .env.production
   ```
   Genera secretos con:
   ```bash
   openssl rand -hex 32   # → B2B_API_KEY
   openssl rand -hex 24   # → POSTGRES_PASSWORD
   ```

4. **Despliega**:
   ```bash
   ./scripts/deploy.sh
   ```
   El script construye la imagen, levanta el stack y espera a que `/health`
   responda 200.

5. **Verifica**:
   ```bash
   ./scripts/health-check.sh
   curl http://127.0.0.1/health
   curl -H "X-API-Key: $B2B_API_KEY" http://127.0.0.1/api/v1/stats
   ```

### 3.3 Actualizaciones

```bash
cd /opt/b2b-ai
# sube el código nuevo (rsync/git pull), después:
./scripts/deploy.sh          # rebuild + up sin downtime total (rolling del API)
```

## 4. Variables de entorno

Todas se documentan en `.env.production.example`. Las críticas:

| Variable | Obligatoria | Descripción |
|---|---|---|
| `B2B_API_KEY` | **Sí** | API key maestra de servicio (`openssl rand -hex 32`) |
| `POSTGRES_PASSWORD` | **Sí** | Password de Postgres (provisionado para el roadmap) |
| `B2B_WORKERS` | No | Workers uvicorn. **1** con SQLite (estado actual) |
| `B2B_RATE_LIMIT` | No | `on`/`off`; `B2B_RATE_LIMIT_PER_MIN=300` por defecto |
| `B2B_LLM_PROVIDER` | No | `openai`/`deepseek`/`anthropic` o vacío (reglas puras) |
| `SMTP_*` | No | Sin ellas, las notificaciones se registran como "simulado" |

> Regla de seguridad: `POSTGRES_PASSWORD` se marca obligatoria en el compose
> (`${POSTGRES_PASSWORD:?...}`). Si falta, `docker compose up` falla antes de
> levantar nada.

## 5. Monitoreo

### Healthcheck integrado

- **`GET /health`** — `status`, `version`, `backend`, `schema_version`,
  `invoices`, `tenants`, `uptime_seconds`, `total_requests`. Lo usa el
  `HEALTHCHECK` de Docker y `scripts/health-check.sh`.
- **`GET /metrics`** — métricas operativas en memoria (por proceso):
  `total_requests`, `errors_5xx`, `requests_by_path`, `status_codes`,
  `latency_ms_by_path` (avg y p95 por ruta).

### Script

```bash
./scripts/health-check.sh            # estado de api + metrics + contenedores
./scripts/health-check.sh --quiet    # solo exit code (para cron)
```

### En Docker

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
docker stats
```

### Sugerencia de cron (cada 5 min)

```cron
*/5 * * * * cd /opt/b2b-ai && ./scripts/health-check.sh --quiet || echo "B2B-AI FUERA DE SERVICIO" | mail -s "ALERTA b2b-ai" ops@tu-dominio.com
```

> **Nota sobre métricas.** `/metrics` es por-proceso: con `B2B_WORKERS>1` cada
> worker reporta las suyas. Para agregación global real, escanea `/metrics`
> desde Prometheus (exponiéndolo vía Nginx) y grafana en Grafana. El formato
> actual es JSON; si necesitas el formato Prometheus de texto plano, es un
> endpoint adicional de bajo coste.

## 6. Backup strategy

### Qué respaldar

1. **Volumen SQLite** `b2b-data` (la base de datos real hoy).
2. **`.env.production`** (secretos — guárdalo en un gestor de contraseñas; no
   debe vivir en backups no cifrados).

### Backup del volumen (ejemplo con `pg_dump`-style, vía docker run)

```bash
# Volcado consistente del SQLite (requiere un momento de pausa de escritura).
docker run --rm \
  -v b2b-ai-prod_b2b-data:/data -v /backups:/backups \
  alpine sh -c "cp /data/b2b_ai.db /backups/b2b_ai_$(date +%F).db"
```

### Backup de la base Postgres (cuando exista el adaptador)

```bash
docker exec b2b-ai-postgres pg_dump -U b2b -d b2b_ai > /backups/b2b_ai_$(date +%F).sql
```

### Retención sugerida

- 7 dailies + 4 semanales + 12 mensuales. Automatiza con `restic` o `borgbackup`
  y sube a almacenamiento off-site (S3/B2/backblaze).

### Restauración

```bash
# 1. Baja el API
docker compose -f docker-compose.prod.yml -p prod stop api
# 2. Sustituye el volumen
docker run --rm -v b2b-ai-prod_b2b-data:/data -v /backups:/backups \
  alpine sh -c "cp /backups/b2b_ai_YYYY-MM-DD.db /data/b2b_ai.db && chown 1000:1000 /data/b2b_ai.db"
# 3. Sube de nuevo
docker compose -f docker-compose.prod.yml -p prod start api
```

## 7. TLS / HTTPS

El bloque HTTPS está **comentado** en `nginx/nginx.conf`. Para habilitarlo:

1. Coloca los certificados en `nginx/certs/fullchain.pem` y
   `nginx/certs/privkey.pem` (emite con certbot `certonly --standalone`, o
   copia los de tu proveedor).
2. Descomenta el bloque `listen 443 ssl` en `nginx/nginx.conf`.
3. `./scripts/deploy.sh --no-build`.

## 8. Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| `up` falla: "POSTGRES_PASSWORD is required" | falta el secreto en `.env.production` | añade `POSTGRES_PASSWORD` |
| `deploy.sh` aborta: "cambiar los secretos" | `.env.production` aún trae `change-me` | edita y genera secretos reales |
| `/health` no responde tras el deploy | build lento / SQLite arrancando | `docker compose logs api` y re-ejecuta el healthcheck |
| `database is locked` en logs | SQLite + múltiples workers | asegura `B2B_WORKERS=1` |
| 429 en la API | rate-limit | sube `B2B_RATE_LIMIT_PER_MIN` o `B2B_RATE_LIMIT=off` |

## 9. Roadmap / deudas técnicas

- **Adaptador PostgreSQL.** `db.py` usa `sqlite3` directamente (PRAGMA,
  `?`/`ON CONFLICT`, `lastrowid`). Escribir una capa que resuelva a
  `sqlite3` o `psycopg` según `B2B_DB_PATH` (URL `postgresql://…`).
- **Rate-limiting distribuido.** El limiter actual es en memoria (por worker).
  Moverlo a Redis (`REDIS_URL` ya se inyecta).
- **Métricas agregadas.** Exponer formato Prometheus y agregar por worker.
- **Backup automático.** Empaquetar §6 en un script con retención.

---

*Documento generado como parte de la preparación de producción del enterprise
MVP (tarea t_8be7f1ba).*
