#!/usr/bin/env bash
# =============================================================================
# scripts/deploy-railway.sh — Deploy one-click de Likida AI Enterprise a Railway
#
# Uso:
#   ./scripts/deploy-railway.sh                     # deploy completo (una vez)
#   ./scripts/deploy-railway.sh --env-only          # solo configurar variables
#   ./scripts/deploy-railway.sh --logs              # ver logs en tiempo real
#   ./scripts/deploy-railway.sh --status            # estado del servicio
#   ./scripts/deploy-railway.sh --domain <dom>      # asignar dominio custom
#   ./scripts/deploy-railway.sh --teardown          # eliminar servicio
#
# Requisitos previos (primera vez):
#   brew install railway                      # o: npm i -g @railway/cli
#   railway login                             # autenticación
#
# Qué hace en un "deploy completo":
#   1. Verifica CLI + login + proyecto vinculado
#   2. Crea el plugin PostgreSQL (inyecta DATABASE_URL) si no existe
#   3. Genera y fija los secretos (B2B_JWT_SECRET, B2B_ENCRYPTION_KEY, B2B_API_KEY)
#   4. Fija las variables de configuración de la app
#   5. Sube el build (railway up) y espera el healthcheck de /health
#
# Docs: https://docs.railway.com
# =============================================================================
set -euo pipefail

# ---- Raíz del repo (para encontrar Dockerfile / railway.toml) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

SERVICE_NAME="${RAILWAY_SERVICE:-b2b-ai-api}"
HEALTH_TIMEOUT=90

# ---------- Colores ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
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
  if ! railway whoami &>/dev/null 2>&1; then
    fail "No estás autenticado. Ejecuta: railway login"
  fi

  ok "CLI instalado y autenticado."

  if ! railway status &>/dev/null 2>&1; then
    warn "No hay proyecto Railway vinculado. Creando '$SERVICE_NAME'..."
    railway init "$SERVICE_NAME"
  fi
  if [ ! -f "Dockerfile" ] || [ ! -f "railway.toml" ]; then
    fail "Faltan Dockerfile o railway.toml en la raíz del proyecto."
  fi
  ok "Pre-flight checks completados."
}

# ---------- Garantizar plugin PostgreSQL (inyecta DATABASE_URL) ----------
ensure_postgres() {
  info "Verificando plugin PostgreSQL (DATABASE_URL)..."
  if railway variables get DATABASE_URL >/dev/null 2>&1; then
    ok "DATABASE_URL ya está presente (PostgreSQL conectado)."
    return
  fi
  warn "No se encontró DATABASE_URL. Añadiendo plugin PostgreSQL..."
  railway add --plugin postgresql
  # Railway reinicia el servicio al añadir el plugin; esperar a que la variable exista.
  for _ in $(seq 1 12); do
    if railway variables get DATABASE_URL >/dev/null 2>&1; then
      ok "DATABASE_URL disponible."
      return
    fi
    sleep 5
  done
  fail "DATABASE_URL no apareció tras añadir el plugin PostgreSQL."
}

# ---------- Secretos generados (idempotente: no sobrescribe los ya puestos) ----------
ensure_secrets() {
  info "Configurando secretos (no sobrescribe los existentes)..."

  local set_secret=()
  if ! railway variables get B2B_JWT_SECRET >/dev/null 2>&1; then
    set_secret+=(B2B_JWT_SECRET="$(openssl rand -hex 32)")
  fi
  if ! railway variables get B2B_ENCRYPTION_KEY >/dev/null 2>&1; then
    set_secret+=(B2B_ENCRYPTION_KEY="$(openssl rand -hex 24)")
  fi
  if ! railway variables get B2B_API_KEY >/dev/null 2>&1; then
    set_secret+=(B2B_API_KEY="$(openssl rand -hex 32)")
  fi
  if [ "${#set_secret[@]}" -gt 0 ]; then
    railway variables set "${set_secret[@]}"
  fi
  ok "Secretos de seguridad asegurados."
}

# ---------- Variables de configuración ----------
configure_env() {
  ensure_secrets
  info "Configurando variables de configuración..."

  # Postgres add-on ya inyecta DATABASE_URL; la app la lee automáticamente.
  railway variables set \
    B2B_ENV="production" \
    B2B_WORKERS="1" \
    B2B_TRUST_PROXY="true" \
    B2B_RATE_LIMIT="on" \
    B2B_RATE_LIMIT_PER_MIN="300" \
    B2B_CORS_ORIGINS="" \
    B2B_CORS_ALLOW_CREDENTIALS="false"

  ok "Variables de entorno configuradas."
}

# ---------- Deploy completo ----------
deploy() {
  configure_env
  info "Desplegando a Railway (build + push)..."
  railway up
  ok "Build subido. Esperando healthcheck de /health..."

  local url
  url=$(railway domain 2>/dev/null || true)
  if [ -z "$url" ]; then
    url=$(railway status 2>/dev/null | grep -oE 'https://[^ ]+' | head -1 || true)
  fi
  [ -z "$url" ] && url="<tu-app>.up.railway.app"

  # Esperar a que el servicio responda /health.
  local waited=0
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    if curl -fsS -m 5 "${url}/health" >/dev/null 2>&1; then
      ok "Healthcheck OK: ${url}/health"
      echo ""
      echo "🚀  Likida AI desplegado:"
      echo "    API:  $url"
      echo "    Docs: $url/docs"
      echo "    Health: $url/health"
      echo ""
      warn "Guarda B2B_API_KEY: Railway → Variables → B2B_API_KEY (pásala a tus clientes)."
      return 0
    fi
    sleep 5
    waited=$((waited + 5))
  done
  warn "El healthcheck no respondió en ${HEALTH_TIMEOUT}s. Revisa: ./scripts/deploy-railway.sh --logs"
}

# ---------- Utilidades ----------
view_logs()     { info "Logs (Ctrl+C para salir):"; railway logs --no-color; }
view_status()   { railway status; }
setup_domain()  { local domain="${1:-api.likida.app}"; railway domain "$domain"; }
teardown() {
  warn "⚠️  Esto ELIMINARÁ el servicio de Railway."
  read -rp "¿Seguro? (escribe 'yes'): " confirm
  [ "$confirm" = "yes" ] && railway service delete || info "Cancelado."
}

usage() {
  cat <<EOF
Uso: $(basename "$0") [opción]

Opciones:
  (sin args)   Deploy completo: PG plugin + secretos + build + healthcheck
  --env-only   Solo configurar variables de entorno
  --logs       Ver logs en tiempo real
  --status     Estado del servicio
  --domain D   Asignar dominio custom (default: api.likida.app)
  --teardown   Eliminar el servicio de Railway
  -h, --help   Esta ayuda

Primera vez (una sola vez):
  railway login
  ./scripts/deploy-railway.sh
EOF
  exit 0
}

# ---------- Main ----------
case "${1:-}" in
  --env-only) preflight; ensure_postgres; configure_env ;;
  --logs)     view_logs ;;
  --status)   view_status ;;
  --domain)   setup_domain "${2:-api.likida.app}" ;;
  --teardown) teardown ;;
  -h|--help)  usage ;;
  ""|deploy)  preflight; ensure_postgres; deploy ;;
  *)          fail "Opción desconocida: $1. Usa --help." ;;
esac
