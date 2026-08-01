#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Deploy de B&B AI
#
# Opción A: deploy local (VPS con Docker Compose) — ya funciona
#   ./deploy.sh local [--no-build] [--prune]
#
# Opción B: deploy cloud (Vercel + Railway) — nueva
#   ./deploy.sh cloud [--landing-only] [--api-only]
#
# Requisitos:
#   local  → docker + docker compose v2 + curl
#   cloud  → vercel CLI (`npm i -g vercel`) + railway CLI (`npm i -g @railway/cli`)
#
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"   # raíz del proyecto (enterprise/)
PROJECT_DIR="$PWD"

usage() {
  cat <<EOF
Uso: ./$(basename "$0") <modo> [opciones]

Modos:
  local          Deploy en VPS con Docker Compose (opciones: --no-build, --prune, --stack=NOMBRE)
  cloud          Deploy cloud en Vercel (landing) + Railway (API)

Opciones cloud:
  --landing-only  Solo landing (Vercel)
  --api-only      Solo API (Railway)

Ejemplos:
  ./deploy.sh local
  ./deploy.sh local --no-build --stack prod
  ./deploy.sh cloud
  ./deploy.sh cloud --landing-only
EOF
  exit 1
}

# ========== Deploy local (VPS con Docker) ==========
deploy_local() {
  cd "$PROJECT_DIR"

  COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
  ENV_FILE="${ENV_FILE:-.env.production}"
  STACK="${STACK:-prod}"
  DO_BUILD=1
  DO_PRUNE=0
  HEALTH_URL="${B2B_HEALTH_URL:-http://127.0.0.1}"

  # Parse args after 'local'
  for arg in "$@"; do
    case "$arg" in
      --no-build) DO_BUILD=0 ;;
      --prune)    DO_PRUNE=1 ;;
      --stack=*)  STACK="${arg#*=}" ;;
    esac
  done

  if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: falta $ENV_FILE. Cópialo de .env.production.example y ajusta los secretos." >&2
    exit 1
  fi

  echo "==> Mode: local (VPS Docker)"
  echo "==> Stack: $STACK  |  Env: $ENV_FILE"

  # Validar que las variables obligatorias están puestas
  if grep -q "change-me" "$ENV_FILE"; then
    echo "ERROR: $ENV_FILE aún contiene valores 'change-me'. Edítalo antes de desplegar." >&2
    exit 1
  fi

  if [ "$DO_PRUNE" -eq 1 ]; then
    echo "==> Dando de baja el stack previo..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" down || true
  fi

  if [ "$DO_BUILD" -eq 1 ]; then
    echo "==> Construyendo imagen..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" build --pull
  fi

  echo "==> Ejecutando migraciones de base de datos..."
  # La app aplica migraciones versionadas al instanciar la DB. Corremos un
  # one-shot con la imagen ya construida para ejecutarlas ANTES de servir.
  # APP_SERVICE: docker-compose.prod.yml usa 'api'; docker-compose.yml usa 'app'.
  APP_SERVICE="${APP_SERVICE:-api}"
  if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" \
       run --rm --no-deps "$APP_SERVICE" python -c \
       "from b2b_ai.db.db import Database; Database(); print('migraciones OK')"; then
    echo "==> ✅ Migraciones aplicadas."
  else
    echo "WARN: el one-shot de migraciones falló (¿DB aún no arranca?). Se reintenta al levantar servicios." >&2
  fi

  echo "==> Levantando servicios..."
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" up -d

  echo "==> Esperando que el API responda en $HEALTH_URL/health..."
  for i in $(seq 1 30); do
    if curl -fsS -m 5 "$HEALTH_URL/health" >/dev/null 2>&1; then
      echo "==> ✅ API sano (intento $i)."
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "ERROR: el API no respondió tras 30 intentos." >&2
      docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" ps || true
      docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" logs --tail=50 api || true
      exit 1
    fi
    sleep 3
  done

  echo "==> Estado final:"
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$STACK" ps
  echo "==> Deploy local completado."
  curl -fsS -m 5 "$HEALTH_URL/health" || echo "(no se pudo leer /health)"
}

# ========== Deploy cloud (Vercel + Railway) ==========
deploy_cloud() {
  LANDING_ONLY=false
  API_ONLY=false

  for arg in "$@"; do
    case "$arg" in
      --landing-only) LANDING_ONLY=true ;;
      --api-only)     API_ONLY=true ;;
    esac
  done

  echo "==> Mode: cloud (Vercel + Railway)"

  # --- Landing: Vercel ---
  if [ "$API_ONLY" = false ]; then
    if ! command -v vercel &>/dev/null; then
      echo "ERROR: 'vercel' CLI no está instalado. Corre: npm i -g vercel" >&2
      exit 1
    fi

    echo ""
    echo "--- Landing: desplegando en Vercel ---"
    cd "$PROJECT_DIR/landing"

    if [ ! -f "vercel.json" ]; then
      echo "ERROR: falta landing/vercel.json. ¿Se copió el proyecto completo?" >&2
      exit 1
    fi

    echo "==> Ejecutando: vercel --prod"
    vercel --prod --yes
    echo "==> ✅ Landing desplegada en Vercel"

    # Obtener la URL de preview/producción
    echo "==> URL de producción asignada por Vercel (revisa el output arriba)"
    echo "==> Para configurar dominio custom: vercel domains add tudominio.mx"
    echo ""

    cd "$PROJECT_DIR"
  fi

  # --- API: Railway ---
  if [ "$LANDING_ONLY" = false ]; then
    if ! command -v railway &>/dev/null; then
      echo "ERROR: 'railway' CLI no está instalado. Corre: npm i -g @railway/cli" >&2
      exit 1
    fi

    echo ""
    echo "--- API: desplegando en Railway ---"
    cd "$PROJECT_DIR"

    # Archivos necesarios para Railway
    for f in railway.json Procfile runtime.txt; do
      if [ ! -f "$f" ]; then
        echo "ERROR: falta $f en la raíz del proyecto." >&2
        exit 1
      fi
    done

    echo "==> Vinculando proyecto Railway (primera vez: railway login -> railway init)"
    echo "==> Si ya está vinculado, solo corre: railway up"

    if [ -f ".railway" ]; then
      # Ya vinculado: deploy directo
      echo "==> Subiendo a Railway..."
      railway up --yes
      echo "==> ✅ API desplegada en Railway"

      echo "==> Para configurar variables de entorno en Railway:"
      echo "   railway variables set B2B_API_KEY=..."
      echo "   railway variables set B2B_DB_PATH=/data/b2b_ai.db"
      echo "   railway variables set B2B_WORKERS=1"
      echo ""
      echo "==> Para dominio custom: railway domain add api.tudominio.mx"
      echo ""
    elif [ ! -z "${RAILWAY_TOKEN:-}" ]; then
      # CI mode pero sin .railway
      echo "ERROR: No hay .railway/ y estás en modo CI/CD (RAILWAY_TOKEN presente)." >&2
      echo "  Corre 'railway init' manualmente la primera vez, luego sube .railway/ al repo." >&2
      exit 1
    else
      # Primera vez en local: instrucciones
      echo "==> No hay .railway/ — se necesita vincular un proyecto existente."
      echo "  Opción 1 (recomendada): railway login && railway init   (interactivo, crea proyecto nuevo)"
      echo "  Opción 2: railway login && railway link                (vincula proyecto existente)"
      echo ""
      echo "  Después de la primera vez, solo corre: railway up"
      echo "  (o usa el deploy automático desde el dashboard de Railway)"
      echo "  Omitiendo deploy de API por ahora..."
      echo ""
    fi
  fi

  echo "==> Deploy cloud completado."
  echo "    Landing: https://<vercel-url>"
  echo "    API:     https://<railway-url>"
}

# ========== Main ==========
if [ $# -lt 1 ]; then
  usage
fi

MODE="$1"
shift  # consume el modo; el resto va como argumentos al subcomando

case "$MODE" in
  local)  deploy_local "$@" ;;
  cloud)  deploy_cloud "$@" ;;
  *)      echo "ERROR: modo desconocido '$MODE'"; usage ;;
esac