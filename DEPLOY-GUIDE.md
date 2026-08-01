# Guía de Despliegue — Likida AI a Producción (Railway)

**Última actualización:** 2026-08-01  
**Objetivo:** Poner la API de Likida AI en producción usando Railway (Docker), con dominio custom, SSL automático y todas las integraciones activas.

---

## Tabla de contenidos

1. [Prerrequisitos](#1-prerrequisitos)
2. [Creación de cuentas y servicios](#2-creación-de-cuentas-y-servicios)
3. [Primer deploy (Railway)](#3-primer-deploy-railway)
4. [Configurar variables de entorno](#4-configurar-variables-de-entorno)
5. [DNS con Cloudflare](#5-dns-con-cloudflare)
6. [Verificación post-deploy](#6-verificación-post-deploy)
7. [Rollback (deshacer un deploy)](#7-rollback-deshacer-un-deploy)
8. [Actualizaciones futuras](#8-actualizaciones-futuras)
9. [Troubleshooting](#9-troubleshooting)
10. [Checklist rápido](#10-checklist-rápido)

---

## 1. Prerrequisitos

### Herramientas necesarias en tu Mac

| Herramienta | Para qué | Instalar con |
|---|---|---|
| **Railway CLI** | Deploy a Railway | `brew install railway` |
| **Docker** (opcional) | Build local antes de push | `brew install --cask docker` |
| **Git** | Version control | `brew install git` |
| **OpenSSL** | Generar secretos | Ya incluido en macOS |

### Verificar que todo está instalado

```bash
# Railway CLI
railway --version
railway whoami          # Debe mostrar tu usuario

# Git
git --version

# OpenSSL
openssl version
```

### Verificar que el proyecto compila localmente

```bash
cd Desktop/B2B-AI-MVP/enterprise

# Correr el script de verificación
./scripts/verify-deploy.sh

# Verificar prerequisitos del deploy
./scripts/deploy-production.sh --prereqs
```

---

## 2. Creación de cuentas y servicios

### 2.1 Railway (hosting de la API)

1. Crear cuenta en [railway.app](https://railway.app) (plan Pro recomendado)
2. Instalar y autenticar el CLI:
   ```bash
   brew install railway
   railway login
   ```
3. Crear el proyecto:
   ```bash
   railway init likida-api
   ```
4. Agregar add-ons (base de datos + cache):
   ```bash
   railway add --plugin postgresql    # PostgreSQL para datos
   railway add --plugin redis         # Redis para caching
   ```
   > **Nota:** Railway crea automáticamente las variables `DATABASE_URL` y `REDIS_URL`. No las configures manualmente.

### 2.2 Stripe (pagos internacionales)

1. Crear cuenta en [dashboard.stripe.com](https://dashboard.stripe.com)
2. Obtener las claves:
   - **Secret key:** Developers → API keys → `sk_live_...`
   - **Publishable key:** Developers → API keys → `pk_live_...`
   - **Webhook secret:** Developers → Webhooks → Crear endpoint:
     - URL: `https://api.likida.mx/api/v1/webhooks/stripe`
     - Eventos: `payment_intent.succeeded`, `invoice.paid`, `customer.subscription.updated`
     - Copiar el `whsec_...` del webhook

### 2.3 Conekta (pagos México)

1. Crear cuenta en [dashboard.conekta.com](https://dashboard.conekta.com)
2. Obtener las claves:
   - **Server key:** Configuración → Llaves → `key_...`
   - **Public key:** Configuración → Llaves → `pk_...`

### 2.4 SMTP (notificaciones por email)

**Opción A — Gmail (rápido para empezar):**
1. Habilitar 2FA en tu cuenta Google
2. Generar una "App Password": Google Account → Security → App passwords
3. Usar:
   - Host: `smtp.gmail.com`
   - Port: `587`
   - User: tu-email@gmail.com
   - Pass: la App Password de 16 caracteres

**Opción B — Proveedor dedicado (recomendado para producción):**
- [SendGrid](https://sendgrid.com), [Mailgun](https://mailgun.com), [Amazon SES](https://aws.amazon.com/ses/)
- Host, port y credenciales según el proveedor

### 2.5 WhatsApp Business API (opcional)

1. Crear cuenta en [business.whatsapp.com](https://business.whatsapp.com)
2. Configurar un número de teléfono
3. Obtener el token de la API
4. Obtener el Phone Number ID desde la configuración

### 2.6 OpenAI / LLM (opcional — funciona sin LLM)

Si quieres que la IA clasifique CFDI con GPT:
1. Crear cuenta en [platform.openai.com](https://platform.openai.com)
2. Generar API key: `sk-...`
3. La app funciona 100% con reglas sin LLM — esta integración es opcional

### 2.7 Cloudflare (DNS + SSL)

1. Crear cuenta en [cloudflare.com](https://cloudflare.com)
2. Agregar tu dominio (ej: `likida.mx`)
3. Cambiar los nameservers en tu registrador de dominio a los que da Cloudflare
4. Esperar propagación (puede tomar hasta 24 horas)

---

## 3. Primer deploy (Railway)

### Opción A — Usar el script unificado (recomendado)

```bash
cd Desktop/B2B-AI-MVP/enterprise

# 1. Ver qué haría el deploy sin ejecutar nada
./scripts/deploy-production.sh --dry-run

# 2. Configurar variables de entorno base
./scripts/deploy-production.sh --env-only

# 3. Configurar secretos manualmente (uno por uno)
#    Genera los secretos primero:
API_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -hex 24)

#    Luego configúralos en Railway:
railway variables set B2B_API_KEY="$API_KEY"
railway variables set B2B_JWT_SECRET="$JWT_SECRET"
railway variables set B2B_ENCRYPTION_KEY="$ENCRYPTION_KEY"

# 4. Configurar el resto de secretos (ver sección 4)
# 5. Ejecutar el deploy real
./scripts/deploy-production.sh

# 6. Verificar
./scripts/deploy-production.sh --health
```

### Opción B — Usar Railway CLI directamente

```bash
cd Desktop/B2B-AI-MVP/enterprise

# Login (si no lo hiciste)
railway login

# Link al proyecto (si no lo hiciste)
railway init likida-api
railway add --plugin postgresql
railway add --plugin redis

# Deploy
railway up --yes

# Verificar
curl -s https://<tu-app>.up.railway.app/health | python3 -m json.tool
```

### Qué ocurre durante el deploy

1. Railway recibe el código del repo
2. Usa `railway.toml` para saber que debe construir con `Dockerfile`
3. Construye la imagen Docker multi-stage (builder → runtime)
4. El container arranca con uvicorn + proxy-headers
5. Railway ejecuta health check en `/health` cada 15s
6. Si falla, reintenta hasta 5 veces

---

## 4. Configurar variables de entorno

### Via Railway CLI (recomendado)

```bash
# --- Seguridad (OBLIGATORIOS) ---
railway variables set B2B_API_KEY="$(openssl rand -hex 32)"
railway variables set B2B_JWT_SECRET="$(openssl rand -hex 32)"
railway variables set B2B_ENCRYPTION_KEY="$(openssl rand -hex 24)"

# --- Entorno ---
railway variables set B2B_ENVIRONMENT=production
railway variables set B2B_DEBUG=false
railway variables set B2B_DEMO_MODE=false
railway variables set B2B_WORKERS=1

# --- Base de datos (auto-inyectado por add-on PostgreSQL) ---
# NO configurar DATABASE_URL manualmente

# --- Redis (auto-inyectado por add-on Redis) ---
# NO configurar REDIS_URL manualmente

# --- Pagos: Stripe ---
railway variables set B2B_STRIPE_SECRET=sk_live_tu_clave
railway variables set B2B_STRIPE_PUBLISHABLE_KEY=pk_live_tu_clave
railway variables set B2B_STRIPE_WEBHOOK_SECRET=whsec_tu_secreto

# --- Pagos: Conekta (México) ---
railway variables set B2B_CONEKTA_KEY=key_tu_clave
railway variables set B2B_CONEKTA_PUBLIC_KEY=pk_tu_clave

# --- Email / SMTP ---
railway variables set B2B_SMTP_HOST=smtp.gmail.com
railway variables set B2B_SMTP_PORT=587
railway variables set B2B_SMTP_USER=tu-email@gmail.com
railway variables set B2B_SMTP_PASS=tu-app-password
railway variables set B2B_SMTP_FROM="Likida AI <tu-email@gmail.com>"
railway variables set B2B_SMTP_USE_SSL=true

# --- WhatsApp (opcional) ---
railway variables set B2B_WHATSAPP_TOKEN=tu-token
railway variables set B2B_WHATSAPP_PHONE_NUMBER_ID=tu-id

# --- LLM (opcional) ---
railway variables set B2B_LLM_PROVIDER=openai
railway variables set B2B_LLM_MODEL=gpt-4o-mini
railway variables set B2B_OPENAI_API_KEY=sk-tu-clave

# --- CORS (si la landing está en otro dominio) ---
railway variables set B2B_CORS_ORIGINS=https://likida.mx,https://app.likida.mx
railway variables set B2B_CORS_ALLOW_CREDENTIALS=true

# --- Seguridad de transporte ---
railway variables set B2B_HSTS=true
railway variables set B2B_HSTS_ALWAYS=true
railway variables set B2B_TRUST_PROXY=true

# --- Rate limiting ---
railway variables set B2B_RATE_LIMIT=on
railway variables set B2B_RATE_LIMIT_PER_MIN=300

# --- Monitoreo ---
railway variables set B2B_LOG_LEVEL=INFO
railway variables set B2B_RETENTION_DAYS=365
```

### Via Dashboard de Railway

1. Ve a [railway.app](https://railway.app) → tu proyecto
2. Pestaña "Variables"
3. Agrega cada variable con su valor
4. Para secretos: marca la casilla "Is Secret"

### Variables que NO debes tocar

Railway las gestiona automáticamente:

| Variable | Fuente |
|---|---|
| `DATABASE_URL` | Add-on PostgreSQL |
| `REDIS_URL` | Add-on Redis |
| `PORT` | Asignado por Railway |

---

## 5. DNS con Cloudflare

### 5.1 Configurar el dominio en Railway

```bash
# Asignar dominio custom al servicio
railway domain api.likida.mx

# Railway te dará un dominio interno tipo:
#   likida-api-production.up.railway.app
```

### 5.2 Configurar DNS en Cloudflare

1. Ve a Cloudflare Dashboard → tu dominio → DNS
2. Crear registro:
   - **Tipo:** CNAME
   - **Nombre:** `api`
   - **Target:** `likida-api-production.up.railway.app`
   - **Proxy status:** Proxied (naranja) — esto activa SSL automático de Cloudflare
   - **TTL:** Auto

3. Esperar propagación ( usualmente < 5 minutos con Cloudflare)

### 5.3 SSL / HTTPS

**Con Cloudflare (recomendado):**
- SSL se activa automáticamente cuando el proxy está habilitado
- Certificado renovado automáticamente
- No necesitas configurar nada

**Verificar que HTTPS funciona:**
```bash
curl -I https://api.likida.mx/health
# Debe mostrar: HTTP/2 200
```

### 5.4 Dominios adicionales

Si también necesitas el dominio del portal:
```
Tipo: CNAME | Nombre: app | Target: likida-api-production.up.railway.app
```

---

## 6. Verificación post-deploy

### Health check

```bash
# Via script
./scripts/deploy-production.sh --health

# Via curl directo
curl -s https://api.likida.mx/health | python3 -m json.tool
# Esperado: { "status": "ok", "version": "1.0.0", ... }
```

### Endpoint protegido (sin auth → 401)

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.likida.mx/api/v1/stats
# Esperado: 401
```

### Endpoint protegido (con auth)

```bash
curl -s -H "X-API-Key: TU_API_KEY" https://api.likida.mx/api/v1/stats | python3 -m json.tool
# Esperado: estadísticas del sistema
```

### Leads (público)

```bash
curl -s -X POST https://api.likida.mx/api/v1/leads \
  -H 'Content-Type: application/json' \
  -d '{"nombre":"Test","email":"test@example.com"}'
# Esperado: { "ok": true, ... }
```

### Documentación OpenAPI

Abrir en navegador:
```
https://api.likida.mx/docs
```

### Verificar logs

```bash
# Via script
./scripts/deploy-production.sh --logs

# Via Railway CLI directo
railway logs --no-color
```

### Verificar estado

```bash
./scripts/deploy-production.sh --status
railway status
```

---

## 7. Rollback (deshacer un deploy)

Si algo sale mal después de un deploy:

### Opción rápida — Railway CLI

```bash
# Revertir al deploy anterior
railway rollback

# Verificar que el health check pasa
./scripts/deploy-production.sh --health
```

### Opción granular — Desde el dashboard

1. Ve a railway.app → tu proyecto
2. Pestaña "Deployments"
3. Busca el deploy que funcionaba
4. Click "Rollback to this deployment"

### Via el script

```bash
./scripts/deploy-production.sh --rollback
```

---

## 8. Actualizaciones futuras

Cuando hagas cambios al código y quieras redeployar:

```bash
cd Desktop/B2B-AI-MVP/enterprise

# Opción A: push a main (si auto-deploy está activado)
git add .
git commit -m "feat: nueva funcionalidad"
git push origin main

# Opción B: deploy manual
./scripts/deploy-production.sh
```

### Pre-deploy checklist

Antes de cada deploy:
1. `./scripts/deploy-production.sh --prereqs`
2. Tests pasan: `python3 -m pytest tests/ -x -q`
3. `./scripts/deploy-production.sh --dry-run` para ver qué cambiará
4. Deploy real: `./scripts/deploy-production.sh`
5. Verificar: `./scripts/deploy-production.sh --health`

---

## 9. Troubleshooting

### Deploy falla: "Railway CLI not found"

```bash
brew install railway
railway login
```

### Deploy falla: "No Railway project linked"

```bash
railway init likida-api
railway add --plugin postgresql
railway add --plugin redis
```

### Health check no responde (timeout)

1. Verificar logs:
   ```bash
   railway logs --no-color | tail -50
   ```
2. Causas comunes:
   - Build fallando (revisa logs del build)
   - Falta `B2B_API_KEY` o `B2B_JWT_SECRET`
   - Puerto incorrecto (Railway asigna `PORT` dinámicamente)

### "database is locked" en logs

- Causa: SQLite con múltiples workers
- Solución: `B2B_WORKERS=1` (Railway Plan Pro tiene 0.5-1 CPU)

### Error 401 en todos los endpoints

- Verificar que `B2B_API_KEY` está configurada y es correcta
- Usar el header `X-API-Key` en las peticiones

### Error 502 Bad Gateway

- El container no arrancó correctamente
- Verificar: `railway logs --no-color`
- Verificar variables de entorno: `railway variables`

### DNS no propaga

1. Verificar en Cloudflare que el registro CNAME apunta correctamente
2. Probar con: `dig api.likida.mx CNAME`
3. Esperar hasta 5 minutos (Cloudflare es rápido)

### Conekta no funciona

- Verificar que la key empieza con `key_` (no `sk_`)
- Verificar en el dashboard de Conekta que la cuenta está activa
- La app detecta automáticamente `B2B_CONEKTA_KEY` para pagos en MXN

### Rollback no funciona

1. Desde el dashboard de Railway → Deployments
2. Buscar el último deploy exitoso
3. Click "Rollback to this deployment"
4. Verificar health check

---

## 10. Checklist rápido

```
PRIMERA VEZ:
[ ] Cuenta Railway creada y autenticada (railway login)
[ ] Proyecto creado (railway init likida-api)
[ ] PostgreSQL add-on agregado (railway add --plugin postgresql)
[ ] Redis add-on agregado (railway add --plugin redis)
[ ] B2B_API_KEY generado (openssl rand -hex 32)
[ ] B2B_JWT_SECRET generado (openssl rand -hex 32)
[ ] B2B_ENCRYPTION_KEY generado (openssl rand -hex 24)
[ ] B2B_STRIPE_SECRET configurado
[ ] B2B_STRIPE_WEBHOOK_SECRET configurado
[ ] B2B_CONEKTA_KEY configurado
[ ] B2B_SMTP_* configurado (o sin credenciales = modo seguro)
[ ] Deploy ejecutado (railway up o ./scripts/deploy-production.sh)
[ ] Health check OK (curl https://api.likida.mx/health)
[ ] Dominio custom configurado en Railway
[ ] DNS CNAME configurado en Cloudflare
[ ] HTTPS funciona (curl -I https://api.likida.mx/health)

ACTUALIZACIONES:
[ ] Tests pasan locally
[ ] --dry-run ejecutado y revisado
[ ] Deploy ejecutado
[ ] Health check OK
[ ] Rollback listo si algo falla
```

---

## Archivos de referencia

| Archivo | Descripción |
|---|---|
| `scripts/deploy-production.sh` | Script unificado de deploy con dry-run y rollback |
| `.env.production.example` | Plantilla completa de variables de entorno |
| `railway.toml` | Configuración de build y health check para Railway |
| `Dockerfile` | Build multi-stage de la imagen Docker |
| `DEPLOY.md` | Resumen ejecutivo de opciones de deploy |
| `docs/DEPLOYMENT.md` | Guía detallada para VPS con Docker |

---

*Guía generada para Likida AI — Deploy a Railway con Docker.*
