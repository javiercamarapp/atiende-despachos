# Likida AI Enterprise — Guía de despliegue (DEPLOY.md)

**Última actualización:** 2026-08-02

Guía paso a paso para poner Likida AI Enterprise en producción. El MVP usa
**FastAPI + PostgreSQL 15** y está listo para **Railway** (recomendado, managed)
o un **VPS con Docker Compose** (más control).

Para el detalle arquitectónico/operativo completo consulta
[`README-DEPLOY.md`](./README-DEPLOY.md). Este archivo es la guía ejecutiva.

---

## Arquitectura en producción

| Componente | Qué es | Dónde se sirve |
|---|---|---|
| **API** (FastAPI + PostgreSQL) | Backend real: `/api/v1/*`, `/health`, `/docs` | Railway (managed) o VPS con Docker Compose |
| **PostgreSQL 15** | Base de datos real (la app la detecta vía `DATABASE_URL`) | Railway Plugin o contenedor `postgres:15` |
| **Nginx** | Reverse proxy + TLS + rate limit (solo en Docker Compose) | Mismo VPS |
| **Landing A / B** (`landing/`, `landing-b/`) | HTML estático | Vercel/Netlify o el mismo origen |

> La app **aplica las migraciones de esquema automáticamente** al arrancar cuando
> detecta PostgreSQL (en un hilo de fondo, sin bloquear el healthcheck). **No hay
> paso manual de migración.** Solo conecta la DB y levanta.

---

## Opción 1 — Railway (recomendada, one-click)

### 1. Requisitos previos (una vez)

```bash
brew install railway        # o: npm i -g @railway/cli
railway login
```

### 2. Deploy one-click

```bash
# Desde la raíz del repo:
./scripts/deploy-railway.sh
```

El script hace todo automáticamente:

1. Verifica CLI + login + proyecto vinculado (crea `b2b-ai-api` si falta).
2. **Crea el plugin PostgreSQL** (inyecta `DATABASE_URL`).
3. **Genera y fija los secretos**: `B2B_JWT_SECRET`, `B2B_ENCRYPTION_KEY`, `B2B_API_KEY`.
4. Fija las variables de configuración (`B2B_ENV=production`, rate limit, CORS…).
5. Sube el build y espera a que `/health` responda.

### 3. Verificación

```bash
curl -s https://<tu-app>.up.railway.app/health | jq .status   # → "ok"
```

### 4. Variables de entorno (Railway)

Railway inyecta automáticamente `DATABASE_URL` (PostgreSQL) y `PORT`. Las demás
las fija el script. Si quieres tocarlas a mano, el panel → **Variables**:

| Variable | Requerida | Ejemplo |
|---|---|---|
| `DATABASE_URL` | ✔ (auto) | Postgres DSN inyectado por el plugin |
| `B2B_JWT_SECRET` | ✔ | `openssl rand -hex 32` |
| `B2B_ENCRYPTION_KEY` | ✔ | `openssl rand -hex 24` |
| `B2B_API_KEY` | ✔ | `openssl rand -hex 32` (dásela a tus clientes) |
| `B2B_ENV` | ✔ | `production` |
| `B2B_CORS_ORIGINS` | solo multi-dominio | `https://app.likida.ai,...` |

> **Importante:** sin `B2B_JWT_SECRET` o `B2B_ENCRYPTION_KEY` la app **falla al
> arrancar** (fail-fast de seguridad) — es intencional.

### 5. Dominio custom (opcional)

```bash
./scripts/deploy-railway.sh --domain api.likida.ai
```

### 6. Debugging

```bash
./scripts/deploy-railway.sh --logs      # logs en tiempo real
./scripts/deploy-railway.sh --status    # estado del servicio
```

---

## Opción 2 — VPS con Docker Compose

### 1. Preparar el entorno

```bash
cp .env.example .env.production
vi .env.production          # rellena POSTGRES_PASSWORD y los secretos
```

Genera los secretos:

```bash
openssl rand -hex 32    # B2B_JWT_SECRET
openssl rand -hex 24    # B2B_ENCRYPTION_KEY
openssl rand -hex 32    # B2B_API_KEY
```

### 2. Levantar el stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Esto levanta: **postgres:15** → **api** (FastAPI) → **nginx** (proxy en :80/:443).

### 3. Verificación

```bash
curl -s http://<IP>/health | jq .status    # → "ok"
```

### 4. TLS con Let's Encrypt (producción con dominio)

1. Instala `certbot` en el VPS.
2. Genera los certs y colócalos en `nginx/certs/fullchain.pem` y `privkey.pem`.
3. Descomenta el bloque `listen 443 ssl` en `nginx/nginx.conf`.
4. Recrea nginx: `docker compose -f docker-compose.prod.yml up -d nginx`.

---

## Variables de entorno — referencia completa

Ver [`.env.example`](./.env.example) para la lista completa con comentarios.
Las obligatorias en producción son:

| Variable | Propósito |
|---|---|
| `DATABASE_URL` | DSN PostgreSQL (Railway la inyecta; Compose la arma desde `POSTGRES_*`) |
| `B2B_JWT_SECRET` | Firma de tokens HS256 (mín 32 chars) |
| `B2B_ENCRYPTION_KEY` | Cifrado AES-GCM de datos en reposo (mín 16 chars) |
| `B2B_API_KEY` | API key de los clientes (header `X-API-Key`) |
| `B2B_ENV` | `production` |

---

## Rollback

**Railway:** `railway up` sobre un commit anterior, o en el dashboard
*Deployments → Restart previous*.

**Docker Compose:**

```bash
# Volver a una imagen anterior (el volumen postgres-data conserva la DB)
docker compose -f docker-compose.prod.yml --env-file .env.production up -d \
  --build --no-recreate
# Si cambiaste solo variables: restart sin rebuild
docker compose -f docker-compose.prod.yml --env-file .env.production restart api
```

> El volumen `postgres-data` persiste la base entre deploys. No lo borres a menos
> que quieras destruir datos.

---

## Checklist post-deploy

```bash
# 1. Health check
curl -s <API_URL>/health | jq .status                    # → "ok"

# 2. Un endpoint protegido (debe dar 401 sin key)
curl -s -o /dev/null -w "%{http_code}\n" <API_URL>/api/v1/stats   # → 401

# 3. Con API key
curl -s -H "X-API-Key: <KEY>" <API_URL>/api/v1/stats | jq .invoices_total

# 4. Leads (público, mismo origen sin CORS)
curl -s -X POST <API_URL>/api/v1/leads \
  -H 'Content-Type: application/json' \
  -d '{"nombre":"Demo","email":"demo@x.com"}'            # → {"ok":true,...}

# 5. CORS (si UI separada): preflight del origen permitido responde 200
# 6. Landings: cada una responde 200
curl -s -o /dev/null -w "%{http_code}\n" <LANDING_URL>/  # → 200
```
