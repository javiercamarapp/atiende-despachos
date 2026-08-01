# Despliegue de Likida AI Enterprise — Guía completa

**Última actualización:** 2026-07-31

Esta guía cubre las dos formas de poner Likida AI Enterprise en producción:

| Opción | Landing | API | Costo/mes |
|---|---|---|---|
| **A — VPS (local)** | Nginx proxy | Docker Compose (Dockerfile) | ~$10–20 (VPS) |
| **B — Cloud** | Vercel (static) | Railway (managed) | ~$0–25/mes |

Puedes mezclarlas (landing en Vercel + API en Railway es la combinación más barata).

---

## Requisitos previos

### Para cualquier opción

| Herramienta | Cómo instalarla |
|---|---|
| Git | `brew install git` o `apt install git` |
| Node.js 18+ | `brew install node` o `nvm install 18` |
| Python 3.11 | `brew install python@3.11` o `apt install python3.11` |

### Solo para VPS (Opción A)

| Herramienta | Cómo instalarla |
|---|---|
| Docker | `curl -fsSL https://get.docker.com \| sh` |
| Docker Compose v2 | Viene con Docker Desktop o `apt install docker-compose-plugin` |

### Solo para Cloud (Opción B)

| Herramienta | Cómo instalarla |
|---|---|
| Vercel CLI | `npm i -g vercel` |
| Railway CLI | `npm i -g @railway/cli` |

---

## Opción A: VPS con Docker (local)

**Cuándo usarla:** tienes un servidor (DigitalOcean, Linode, Vultr, etc.) y quieres control total.

### Pasos en el servidor

```bash
# 1. Instalar Docker (si no está)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
# Cierra sesión y vuelve a entrar

# 2. Clonar o subir el código
git clone <tu-repo> /opt/b2b-ai
# O via rsync desde tu máquina:
# rsync -avz --exclude=.venv --exclude=.git --exclude='*.db*' --exclude=.env \
#   /ruta/local/enterprise/ user@IP:/opt/b2b-ai/

# 3. Configurar variables de entorno
cd /opt/b2b-ai
cp .env.production.example .env.production
chmod 600 .env.production
# Edita .env.production — cambia TODOS los "change-me"
#   B2B_API_KEY = openssl rand -hex 32
#   POSTGRES_PASSWORD = openssl rand -hex 24

# 4. Desplegar
./deploy.sh local
```

### Verificar

```bash
curl http://127.0.0.1/health
curl -H "X-API-Key: <tu-api-key>" http://127.0.0.1/api/v1/stats
```

### Actualizar

```bash
cd /opt/b2b-ai
git pull              # o rsync de nuevo
./deploy.sh local     # rebuild automático
```

### TLS/HTTPS

Ver docs/DEPLOYMENT.md → TLS. Necesitas certificados en `nginx/certs/`.

---

## Opción B: Cloud (Vercel + Railway)

**Cuándo usarla:** quieres minimizar administración de servidores. La landing es hosting estático (Vercel, $0/mes) y la API corre en Railway (desde $0/mes — $20/mes con Postgres).

### 1. Landing en Vercel

```bash
cd /ruta/a/enterprise/landing

# Primera vez: login
vercel login

# Deploy a producción
vercel --prod
```

Vercel detecta automáticamente `vercel.json` y configura los rewrites de `/static/*` → `/assets/*`.

**Dominio personalizado** (ej: `b2b-ai.mx`):

```bash
# Agregar dominio
vercel domains add b2b-ai.mx

# Sigue las instrucciones: agrega el registro CNAME en tu DNS
```

**Cada deploy subsecuente:**

```bash
cd landing
vercel --prod
```

O automático conectando el repo de GitHub desde el dashboard de Vercel.

### 2. API en Railway

```bash
cd /ruta/a/enterprise/

# Primera vez: login y crear proyecto
railway login
railway init
```

Railway detecta `railway.json` y `Procfile` automáticamente.

**Variables de entorno en Railway:**

Desde el dashboard de Railway → Variables, agrega:

| Variable | Valor |
|---|---|
| `B2B_API_KEY` | `openssl rand -hex 32` (genera uno nuevo) |
| `B2B_WORKERS` | `1` |
| `B2B_LLM_PROVIDER` | (déjalo vacío si no usas LLM) |
| `B2B_DB_PATH` | `/data/b2b_ai.db` |

**Luego cada vez que subas código:**

```bash
cd /ruta/a/enterprise/
railway up
```

O conecta el repo de GitHub desde el dashboard de Railway → deploy automático al push a `main`.

**Railway PostgreSQL** (opcional, recomendado para producción real):

Desde el dashboard de Railway → New → Database → PostgreSQL. Railway te da una URL de conexión. Agrégala como variable:
- `B2B_DB_PATH` = `postgresql://<user>:<pass>@<host>:<port>/<db>`

Nota: hoy la app usa SQLite nativamente. El adaptador Postgres requiere migración del código (ver Roadmap en docs/DEPLOYMENT.md).

### 3. Un solo comando (cuando ya hayas hecho login y railway init)

```bash
./deploy.sh cloud        # Landing + API
./deploy.sh cloud --landing-only   # Solo landing
./deploy.sh cloud --api-only       # Solo API
```

---

## Variables de entorno — referencia rápida

| Variable | Requerida | Valor recomendado |
|---|---|---|
| `B2B_API_KEY` | **Sí** | `openssl rand -hex 32` |
| `B2B_WORKERS` | No | `1` (con SQLite, siempre 1) |
| `B2B_DB_PATH` | No | `/data/b2b_ai.db` (SQLite) — Railway lo maneja |
| `B2B_LLM_PROVIDER` | No | Déjalo vacío (pipeline 100% reglas) |
| `B2B_RATE_LIMIT` | No | `on` |
| `B2B_RATE_LIMIT_PER_MIN` | No | `300` |
| `POSTGRES_PASSWORD` | Solo VPS | `openssl rand -hex 24` |
| `POSTGRES_DB` | Solo VPS | `b2b_ai` |
| `POSTGRES_USER` | Solo VPS | `b2b` |

---

## Estructura de archivos de deploy

```
enterprise/
├── deploy.sh                     ← script principal (local | cloud)
├── Dockerfile                    ← build multi-stage (VPS)
├── docker-compose.prod.yml       ← stack Docker (VPS)
├── railway.json                  ← config Railway (cloud)
├── Procfile                      ← start command Railway/Heroku
├── runtime.txt                   ← versión Python (cloud)
├── .env.production.example       ← template de variables
├── .env.production               ← NO versionar (se crea en cada deploy)
├── landing/
│   ├── vercel.json               ← config Vercel
│   ├── index.html                ← landing page
│   ├── dashboard.html            ← PWA dashboard
│   ├── assets/                   ← imágenes, videos
│   ├── icons/                    ← PWA icons
│   ├── manifest.json             ← PWA manifest
│   └── sw.js                     ← service worker
├── nginx/
│   └── nginx.conf                ← reverse proxy (solo VPS)
├── scripts/
│   ├── deploy.sh                 ← (antiguo, ahora está en raíz)
│   └── health-check.sh           ← healthcheck script
├── docs/DEPLOYMENT.md            ← documentación detallada VPS
└── README-DEPLOY.md              ← este documento
```

---

## Troubleshooting

### Landing (Vercel)

| Problema | Causa | Solución |
|---|---|---|
| 404 en assets (logo, hero, video) | Los assets se referencian como `/static/assets/...` pero están en `/assets/` | Verifica que `vercel.json` tenga el rewrite: verifica el archivo y redeploy |
| PWA no se instala | `sw.js` no se sirve desde la raíz | El rewrite y los headers están configurados en `vercel.json` — redeploy |
| Dominio no apunta | DNS no propagado o CNAME incorrecto | `vercel domains ls` para ver estado; verifica el CNAME apunte a `cname.vercel-dns.com` |
| 404 en `/dashboard` | Falta rewrite en `vercel.json` | Debe tener `{ "source": "/dashboard", "destination": "/dashboard.html" }` |

### API (Railway)

| Problema | Causa | Solución |
|---|---|---|
| App no arranca | Falta `PORT` o `B2B_API_KEY` | Revisa las variables de entorno en el dashboard de Railway |
| `database is locked` | SQLite + múltiples workers | Railway por defecto pone 1 worker; verifica `B2B_WORKERS=1` |
| Error de compilación | Python version mismatch | `runtime.txt` debe decir `python-3.11` |
| Healthcheck falla | App no responde en `/health` | Railway hace healthcheck automático; revisa logs en el dashboard |
| Conexión lenta | Sin `--proxy-headers` en uvicorn | Ya está configurado en `railway.json` y `Procfile` |

### VPS

| Problema | Causa | Solución |
|---|---|---|
| `change-me` detectado | `.env.production` aún tiene valores dummy | Corre `openssl rand -hex 32` y pon el resultado |
| API no responde tras deploy | Build aún no termina | `docker compose logs -f api` para ver progreso |
| 429 Too Many Requests | Rate limit muy bajo | Sube `B2B_RATE_LIMIT_PER_MIN` o pon `B2B_RATE_LIMIT=off` |

---

## Costos estimados

### Opción A — VPS (con Docker)

| Recurso | Proveedor | Costo/mes |
|---|---|---|
| VPS 1 vCPU, 1GB RAM, 25GB SSD | DigitalOcean / Linode | ~$6–12 |
| (opcional) PostgreSQL | Mismo VPS | incluido |
| **Total** | | **~$6–12/mes** |

### Opción B — Cloud (Vercel + Railway)

| Recurso | Proveedor | Costo/mes |
|---|---|---|
| Landing (static hosting) | Vercel (Free) | **$0** |
| API + SQLite | Railway (Starter) | **$0** (primeros \$5 de crédito) |
| API + Railway PostgreSQL | Railway (Developer) | **$20/mes** |
| Dominio .mx | namecheap / google domains | ~$10/año (~$0.83/mes) |
| **Total (mínimo)** | | **~$0/mes** |
| **Total (con dominio + Postgres)** | | **~$21/mes** |

### Resumen

| Escenario | Costo/mes |
|---|---|
| MVP / primeras pruebas | $0–5/mes (Vercel Free + Railway Starter) |
| Producción real | ~$20–25/mes (Railway Developer + dominio) |
| Producción con VPS propio | ~$6–12/mes (VPS administrado por ti) |

---

## Siguientes pasos recomendados

1. **Primero:** deploy de la landing en Vercel (gratis, 2 min)
2. **Después:** deploy de la API en Railway (gratis, 5 min)
3. **Configurar dominio:** compra un `.mx` o `.ai` y apúntalo a Vercel
4. **Conectar GitHub:** desde los dashboards de Vercel y Railway para deploy automático
5. **Probar:** visita la landing, prueba /health, haz una llamada a la API
6. **Monitorear:** Railway y Vercel tienen dashboards con logs y métricas incluidas

---

*Documento generado como parte de la preparación de deploy multi-entorno del enterprise MVP.*