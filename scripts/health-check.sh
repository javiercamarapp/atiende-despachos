#!/usr/bin/env bash
# =============================================================================
# health-check.sh — Verifica el estado de los servicios del stack B&B AI.
#
# Uso:
#   ./scripts/health-check.sh                     # comprueba el stack completo
#   ./scripts/health-check.sh api                 # solo el API
#   ./scripts/health-check.sh --quiet             # sin salida extra (exit code)
#   ./scripts/health-check.sh --timeout 5         # timeout HTTP en segundos
#
# Exit code: 0 = todo sano, 1 = algo falló.
# Pensado para correr en el VPS junto al stack (docker compose.prod).
# =============================================================================
set -u

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
BASE_URL="${B2B_HEALTH_URL:-http://127.0.0.1}"
TIMEOUT=4
QUIET=0
SERVICE="${1:-all}"
if [ "${2:-}" = "--quiet" ] || [ "${1:-}" = "--quiet" ]; then QUIET=1; fi
if [ "${1:-}" = "--timeout" ]; then TIMEOUT="${2:-4}"; SERVICE="${3:-all}"; fi

ok=0; fail=0

report() { # report <servicio> <estado> <detalle>
  if [ "$QUIET" -eq 0 ]; then printf "%-10s  %s  %s\n" "$1" "$2" "$3"; fi
}

check_api() {
  local code
  code=$(curl -sS -m "$TIMEOUT" -o /tmp/b2b_health.$$ -w '%{http_code}' \
      "$BASE_URL/health" 2>/dev/null)
  if [ "$code" = "200" ]; then
    ok=$((ok+1)); report "api" "OK " "GET /health → 200"
  else
    fail=$((fail+1)); report "api" "FAIL" "GET /health → ${code:-sin respuesta}"
  fi
}

check_metrics() {
  local code
  code=$(curl -sS -m "$TIMEOUT" -o /dev/null -w '%{http_code}' \
      "$BASE_URL/metrics" 2>/dev/null)
  if [ "$code" = "200" ]; then
    ok=$((ok+1)); report "metrics" "OK " "GET /metrics → 200"
  else
    fail=$((fail+1)); report "metrics" "FAIL" "GET /metrics → ${code:-sin respuesta}"
  fi
}

check_container() { # check_container <servicio>
  local svc="$1"
  if command -v docker >/dev/null 2>&1; then
    local state
    state=$(docker inspect -f '{{.State.Health.Status}}' "b2b-ai-$svc" 2>/dev/null \
            || docker inspect -f '{{.State.Status}}' "b2b-ai-$svc" 2>/dev/null)
    if [ -n "$state" ]; then
      ok=$((ok+1)); report "$svc" "OK " "contenedor → $state"
    else
      fail=$((fail+1)); report "$svc" "FAIL" "contenedor b2b-ai-$svc no encontrado"
    fi
  else
    report "$svc" "SKIP" "docker no disponible en este host"
  fi
}

if [ "$SERVICE" = "api" ] || [ "$SERVICE" = "all" ]; then
  check_api
  check_metrics
fi
for svc in postgres redis nginx; do
  [ "$SERVICE" = "$svc" ] || [ "$SERVICE" = "all" ] && check_container "$svc"
done

rm -f /tmp/b2b_health.$$
if [ "$QUIET" -eq 0 ]; then
  echo "---"
  echo "Resumen: $ok sanos, $fail fallidos"
fi
[ "$fail" -eq 0 ] && exit 0 || exit 1
