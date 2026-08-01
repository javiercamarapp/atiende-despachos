#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Deploy de B&B AI en un VPS con Docker Compose.
#
# Flujo: construye la imagen, levanta el stack y verifica salud. Diseñado para
# ejecutarse EN el servidor de destino (o vía SSH). Asume Docker + Compose v2.
#
# Uso:
#   ./scripts/deploy.sh                        # build + up + healthcheck
#   ./scripts/deploy.sh --no-build             # solo up (imagen ya construida)
#   ./scripts/deploy.sh --prune                # docker compose down antes de up
#   ./scripts/deploy.sh --stack prod           # nombre del stack (default prod)
#
# Requisitos previos en el VPS (ver docs/DEPLOYMENT.md):
#   1. El código del repo en este directorio (git clone o rsync).
#   2. docker y docker compose v2 instalados.
#   3. .env.production creado desde .env.production.example y chmod 600.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."   # raíz del repo

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
STACK="${STACK:-prod}"
DO_BUILD=1
DO_PRUNE=0
HEALTH_URL="${B2B_HEALTH_URL:-http://127.0.0.1}"

for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=0 ;;
    --prune)    DO_PRUNE=1 ;;
    --stack)    : ;;  # --stack lo consume la siguiente opción (ver abajo)
    --stack=*)  STACK="${arg#*=}" ;;
    *) [ "$arg" != "--stack" ] && STACK="$arg" ;;
  esac
done

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: falta $ENV_FILE. Cópialo de .env.production.example y ajusta los secretos." >&2
  exit 1
fi

echo "==> Stack:  $STACK"
echo "==> Env:    $ENV_FILE"
echo "==> Compose: $COMPOSE_FILE"

# Validar que las variables obligatorias están puestas.
if grep -q "change-me" "$ENV_FILE"; then
  echo "ERROR: .env.production aún contiene valores 'change-me'. Edítalo antes de desplegar." >&2
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
    docker compose -f "$COMPOSE_FILE" -p "$STACK" ps || true
    docker compose -f "$COMPOSE_FILE" -p "$STACK" logs --tail=50 api || true
    exit 1
  fi
  sleep 3
done

echo "==> Estado final:"
docker compose -f "$COMPOSE_FILE" -p "$STACK" ps

echo "==> Deploy completado. Salud:"
curl -fsS -m 5 "$HEALTH_URL/health" || echo "(no se pudo leer /health)"
