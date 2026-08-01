#!/usr/bin/env bash
# =============================================================================
# stop.sh — Detiene B&B AI.
#
#   ./stop.sh          → docker compose down (conserva el volumen de la DB).
#   ./stop.sh --purge  → docker compose down -v (ELIMINA la DB persistente).
#   ./stop.sh --local  → mata un uvicorn local (modo desarrollo).
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-compose}"

if [ "$MODE" = "--purge" ]; then
    echo "→ Eliminando contenedores Y el volumen de datos (down -v) ..."
    docker compose down -v
    echo "  ✔ DB persistente eliminada."
    exit 0
fi

if [ "$MODE" = "--local" ]; then
    echo "→ Deteniendo uvicorn local ..."
    pkill -f "uvicorn b2b_ai.api.app:app" 2>/dev/null && echo "  ✔ Detenido." || echo "  · No había uvicorn corriendo."
    exit 0
fi

echo "→ Deteniendo contenedores (conserva el volumen de la DB) ..."
docker compose down
echo "  ✔ Detenido. La DB persiste en el volumen 'enterprise_db'."
echo "  Para volver a arrancar:  ./start.sh"
