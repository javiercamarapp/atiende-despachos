# Likida AI Enterprise — Guía de despliegue (DEPLOY.md)

**Última actualización:** 2026-07-31

Guía rápida para poner Likida AI Enterprise en producción. Para el detalle completo
(requisitos, opción VPS vs cloud, variables, rollback) consulta
[`README-DEPLOY.md`](./README-DEPLOY.md) — este archivo es el resumen ejecutivo.

## Arquitectura en producción

| Componente | Qué es | Dónde se sirve |
|---|---|---|
| **API** (FastAPI + SQLite) | Backend real: `/api/v1/*`, `/health`, `/docs` | Railway (managed) o VPS con Docker |
| **Landing A** (`landing/`) | Landing principal + dashboard | Vercel/Netlify (static) o el mismo origen de la API |
| **Landing B** (`landing-b/`) | Landing alternativa estilo usehandle (solo HTML estático + vídeos) | Vercel/Netlify (static, standalone) |

> La landing se sirve desde el **mismo origen** que la API, por lo que el
> `fetch('/api/v1/leads')` de la landing funciona **sin CORS**. CORS solo se
> necesita si hosteas la UI en un dominio distinto al de la API (ver abajo).

---

## Opción 1 — Cloud (recomendada): Vercel + Railway

### API → Railway (ya configurado)

El repo ya trae `railway.json`, `Procfile` y `runtime.txt`. Desde la raíz:

```bash
railway login
railway init
railway up
```

Variables obligatorias en Railway: `B2B_API_KEY` (genera con
`openssl rand -hex 32`), `B2B_PORT=8000`. Ver el health check:
`curl https://<tu-app>.up.railway.app/health`.

### Landings → Vercel (static)

Cada landing es estática y se despliega sola. Ya trae su `vercel.json`.

```bash
# Landing B (estilo usehandle)
cd landing-b
npx vercel --prod        # despliega desde ./landing-b

# Landing A (principal + dashboard)
cd ../landing
npx vercel --prod
```

O desde el dashboard de Vercel: *Add New → Project → importa el repo* y fija
**Root Directory** a `landing/` o `landing-b/`. No necesitas build command ni
output directory (es HTML estático puro).

### CORS (solo si UI y API están en dominios distintos)

En el deploy de la API (Railway/Vercel function), define:

```bash
B2B_CORS_ORIGINS=https://tu-landing.vercel.app,https://www.tu-landing.com
B2B_CORS_ALLOW_CREDENTIALS=false   # la API autentica con X-API-Key, no cookies
```

Vacío = CORS desactivado (solo same-origin). La lista de orígenes permite
llamar a la API desde esos dominios. Se verifica con un preflight `OPTIONS`.

---

## Opción 2 — VPS (Docker Compose)

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
curl http://localhost:8000/health   # health check
```

Sirve API + landing A en el mismo origen. Para landing B, súbela a un static
host o sírvela por Nginx apuntando a la carpeta `landing-b/`.

---

## Arranque local / desarrollo

```bash
./start.sh            # Docker Compose (prod-like) o
./start.sh --local    # uvicorn local sin Docker
```

Para servir la landing B como estática sin la API:

```bash
cd landing-b && python3 -m http.server 8000
# → http://localhost:8000
```

---

## Verificación post-deploy (checklist)

```bash
# 1. Health check de la API
curl -s <API_URL>/health | jq .status            # → "ok"

# 2. Un endpoint protegido (debe dar 401 sin key)
curl -s -o /dev/null -w "%{http_code}\n" <API_URL>/api/v1/stats   # → 401

# 3. Con API key
curl -s -H "X-API-Key: $B2B_API_KEY" <API_URL>/api/v1/stats | jq .invoices_total

# 4. Leads (público) — mismo origen sin CORS
curl -s -X POST <API_URL>/api/v1/leads \
  -H 'Content-Type: application/json' \
  -d '{"nombre":"Demo","email":"demo@x.com"}'    # → {"ok":true,...}

# 5. CORS (si UI separada): el preflight del origen permitido responde 200
#    con access-control-allow-origin; el no permitido NO lo trae.

# 6. Landings: cada una responde 200 y carga sus vídeos assets/
curl -s -o /dev/null -w "%{http_code}\n" <LANDING_B_URL>/        # → 200
```

## Endpoints principales

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | no | Health check + versión + estado DB |
| GET | `/metrics` | no | Métricas operativas (count/latencia) |
| POST | `/api/v1/leads` | no | Alta de lead desde la landing |
| POST | `/api/v1/invoices/process` | sí | Procesa un CFDI |
| GET | `/api/v1/invoices` | sí | Lista facturas con filtros |
| GET | `/api/v1/stats` | sí | Métricas agregadas |
| GET | `/api/v1/accounting/balance` | sí | Balanza de comprobación |
| ... | `/api/v1/*` (resto) | sí | Conciliación, nómina, cobranza, contab. electrónica |
| GET | `/docs` | no | Documentación OpenAPI |
