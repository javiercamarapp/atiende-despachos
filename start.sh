#!/usr/bin/env bash
# =============================================================================
# start.sh — Levanta B&B AI (landing + API + DB) en 5 minutos.
#
# Modos:
#   ./start.sh          → arranca con Docker Compose (recomendado, prod-like).
#   ./start.sh --local  → arranca uvicorn local (sin Docker, para desarrollo).
#
# Requiere:
#   - Docker + Docker Compose (modo compose), o
#   - Python 3.9+ con .venv creado (modo local).
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-compose}"

# --- Prepara .env si no existe ----------------------------------------------
if [ ! -f .env ]; then
    echo "→ Creando .env desde .env.example ..."
    cp .env.example .env
    echo "  ⚠ Edita .env y define una B2B_API_KEY fuerte (openssl rand -hex 32)."
fi

# Cargar B2B_PORT para el modo local / mensajes.
if [ -f .env ]; then
    set -a; source .env; set +a
fi
PORT="${B2B_PORT:-8000}"

if [ "$MODE" = "--local" ]; then
    echo "→ Modo LOCAL (uvicorn) en http://localhost:${PORT}"
    if [ ! -d .venv ]; then
        echo "→ Creando .venv e instalando deps ..."
        python3 -m venv .venv
        ./.venv/bin/pip install -e .
    fi
    exec ./.venv/bin/uvicorn b2b_ai.api.app:app --host "${B2B_HOST:-0.0.0.0}" --port "$PORT" --reload
fi

# --- Modo Docker Compose -----------------------------------------------------
echo "→ Levantando con Docker Compose ..."
docker compose up --build -d

echo ""
echo "  ✔ B&B AI arrancado."
echo "  → Landing :  http://localhost:${PORT}/"
echo "  → API docs:  http://localhost:${PORT}/docs"
echo "  → Health  :  http://localhost:${PORT}/health"
echo ""
echo "  Para probar la API:"
echo "    KEY=\$(grep B2B_API_KEY .env | cut -d= -f2)"
echo "    curl -H \"X-API-Key: \$KEY\" http://localhost:${PORT}/api/v1/stats"
echo "  Para detener:  ./stop.sh"
