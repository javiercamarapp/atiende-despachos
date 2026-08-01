#!/usr/bin/env bash
# =============================================================================
# deploy-railway.sh — Deploy de Likida AI Enterprise a Railway
#
# Uso:
#   ./deploy-railway.sh                    # deploy completo (build + push)
#   ./deploy-railway.sh --env-only         # solo configurar variables de entorno
#   ./deploy-railway.sh --logs             # ver logs en tiempo real
#   ./deploy-railway.sh --status           # ver estado del servicio
#   ./deploy-railway.sh --domain           # asignar dominio custom
#   ./deploy-railway.sh --teardown         # eliminar servicio Railway
#
# Requisitos:
#   brew install railway        (o npm i -g @railway/cli)
#   railway login               (autenticación inicial)
#   railway init bb-ai-api      (crear proyecto la primera vez)
#   railway add --plugin postgresql
#   railway add --plugin redis
#
# Docs: https://docs.railway.com
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$PWD"
SERVICE_NAME="${RAILWAY_SERVICE:-bb-ai-api}"
HEALTH_TIMEOUT=60

# ---------- Colores ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

info()  { echo -e "${BLUE}==> $1${NC}"; }
ok()    { echo -e "${GREEN}✅ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
fail()  { echo -e "${RED}❌ $1${NC}" >&2; exit 1; }

# ---------- Pre-flight checks ----------
preflight() {
  info "Verificando requisitos..."

  if ! command -v railway &>/dev/null; then
    fail "Railway CLI no instalado. Instala con: brew install railway"
  fi

  # Verificar login
  if ! railway whoami &>/dev/null 2>&1; then
    fail "No estás autenticado. Ejecuta: railway login"
  fi

  local user
  user=$(railway whoami 2>/dev/null || echo "unknown")
  ok "Autenticado como: $user"

  # Verificar que existe un proyecto vinculado
  if ! railway status &>/dev/null 2>&1; then
    warn "No hay proyecto Railway vinculado."
    echo "  Ejecuta primero:"
    echo "    railway init $SERVICE_NAME"
    echo "    railway add --plugin postgresql"
    echo "    railway add --plugin redis"
    exit 1
  fi

  # Verificar Dockerfile
  if [ ! -f "Dockerfile" ]; then
    fail "No se encontró Dockerfile en la raíz del proyecto."
  fi

  ok "Pre-flight checks completados."
}

# ---------- Configure environment variables ----------
configure_env() {
  info "Configurando variables de entorno en Railway..."

  # --- Railway auto-inyecta estas variables con los add-ons ---
  # DATABASE_URL  → PostgreSQL (add-on)
  # REDIS_URL     → Redis (add-on)
  # PORT          → Puerto asignado por Railway
  #
  # NO las configures manualmente. La app las detecta automáticamente.

  # --- Variables de la app ---
  railway variables set \
    B2B_ENVIRONMENT="production" \
    B2B_DEBUG="false" \
    B2B_WORKERS="1" \
    B2B_RATE_LIMIT="on" \
    B2B_RATE_LIMIT_PER_MIN="300" \
    B2B_HSTS="true" \
    B2B_HSTS_ALWAYS="true" \
    B2B_TRUST_PROXY="true" \
    B2B_RETENTION_DAYS="365" \
    B2B_LOG_LEVEL="INFO"

  ok "Variables de entorno base configuradas."
  echo ""
  warn "Recuerda configurar los secretos MANUALMENTE (nunca en scripts):"
  echo "  railway variables set B2B_API_KEY=\$(openssl rand -hex 32)"
  echo "  railway variables set B2B_JWT_SECRET=\$(openssl rand -hex 32)"
  echo "  railway variables set B2B_ENCRYPTION_KEY=\$(openssl rand -hex 24)"
  echo "  railway variables set B2B_STRIPE_KEY=sk_live_..."
  echo "  railway variables set B2B_CONEKTA_KEY=key_..."
  echo "  railway variables set SMTP_HOST=smtp.gmail.com"
  echo "  railway variables set SMTP_USER=notifications@bb-ai.com"
  echo "  railway variables set SMTP_PASSWORD=your-app-password"
  echo "  railway variables set B2B_OPENAI_API_KEY=sk-..."
  echo ""
}

# ---------- Deploy ----------
deploy() {
  info "Desplegando a Railway..."
  echo ""

  # Railway construye usando el Dockerfile multi-stage definido en railway.toml
  # y ejecuta el healthcheck en /health automáticamente.
  railway up --yes

  ok "Deploy enviado. Esperando que Railway construya e inicie..."
  echo ""

  # Esperar health check
  info "Esperando health check (máx ${HEALTH_TIMEOUT}s)..."
  local url
  url=$(railway domain 2>/dev/null || echo "")

  if [ -n "$url" ]; then
    local start_time=$SECONDS
    while (( SECONDS - start_time < HEALTH_TIMEOUT )); do
      local code
      code=$(curl -fsS -o /dev/null -w '%{http_code}' -m 5 "https://$url/health" 2>/dev/null || echo "000")
      if [ "$code" = "200" ]; then
        ok "API sana: https://$url/health"
        return 0
      fi
      sleep 3
    done
    warn "Health check no respondió en ${HEALTH_TIMEOUT}s. Revisa logs con: railway logs"
  else
    warn "No se pudo obtener el dominio. Revisa el dashboard: railway open"
  fi
}

# ---------- View logs ----------
view_logs() {
  info "Mostrando logs de Railway (Ctrl+C para salir)..."
  railway logs --no-color
}

# ---------- View status ----------
view_status() {
  info "Estado del servicio en Railway:"
  railway status
}

# ---------- Setup domain ----------
setup_domain() {
  local domain="${1:-api.bb-ai.com}"
  info "Configurando dominio custom: $domain"

  railway domain "$domain"

  ok "Dominio configurado: $domain"
  echo ""
  warn "Asegúrate de que el DNS apunta a Railway:"
  echo "  CNAME  $domain  → $(railway domain 2>/dev/null || echo '<railway-url>')"
}

# ---------- Teardown ----------
teardown() {
  warn "⚠️  Esto ELIMINARÁ el servicio de Railway."
  read -p "¿Estás seguro? (escribe 'yes' para confirmar): " confirm
  if [ "$confirm" = "yes" ]; then
    railway service delete
    ok "Servicio eliminado."
  else
    info "Operación cancelada."
  fi
}

# ---------- Usage ----------
usage() {
  cat <<EOF
Uso: $(basename "$0") [opción]

Opciones:
  (sin args)     Deploy completo: build + push + health check
  --env-only     Solo configurar variables de entorno
  --logs         Ver logs en tiempo real
  --status       Ver estado del servicio
  --domain       Asignar dominio custom (default: api.bb-ai.com)
  --teardown     Eliminar servicio de Railway

Ejemplos:
  ./deploy-railway.sh                    # primer deploy
  ./deploy-railway.sh --env-only         # configurar vars después de crear add-ons
  ./deploy-railway.sh --domain api.bb-ai.com
  ./deploy-railway.sh --logs             # debugging

Requisitos previos (primera vez):
  railway login
  railway init $SERVICE_NAME
  railway add --plugin postgresql
  railway add --plugin redis
  railway variables set B2B_API_KEY=\$(openssl rand -hex 32)
  railway variables set B2B_JWT_SECRET=\$(openssl rand -hex 32)
  railway variables set B2B_ENCRYPTION_KEY=\$(openssl rand -hex 24)
EOF
  exit 1
}

# ---------- Main ----------
preflight

case "${1:-}" in
  --env-only)   configure_env ;;
  --logs)       view_logs ;;
  --status)     view_status ;;
  --domain)     setup_domain "${2:-api.bb-ai.com}" ;;
  --teardown)   teardown ;;
  -h|--help|"") usage ;;
  *)            fail "Opción desconocida: $1. Usa --help para ver opciones." ;;
esac
