#!/usr/bin/env bash
# ============================================================================
# demo_run.sh — Launch B&B AI Demo Server
#
# Usage:
#   ./demo_run.sh          # Start on port 8080
#   ./demo_run.sh 9090     # Start on custom port
# ============================================================================
set -euo pipefail

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")" && pwd)"

# Find Python (prefer venv if it exists)
PYTHON=""
if [ -f "$DIR/.venv/bin/python3" ]; then
    PYTHON="$DIR/.venv/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON="$(command -v python3)"
elif command -v python &>/dev/null; then
    PYTHON="$(command -v python)"
else
    echo "  ❌ Error: Python not found in PATH"
    exit 1
fi

echo ""
echo "  🚀 B&B AI — Demo Server"
echo "  ========================"
echo "  🐍 Python:     $PYTHON"
echo "  📂 Working dir: $DIR"
echo "  🌐 Dashboard:   http://localhost:$PORT"
echo "  📡 API docs:    http://localhost:$PORT/docs"
echo "  ========================"
echo ""
echo "  Press Ctrl+C to stop the server."
echo ""

cd "$DIR"
exec "$PYTHON" -c "
import uvicorn, sys
sys.path.insert(0, '$DIR')
from demo_server import app
uvicorn.run(app, host='0.0.0.0', port=$PORT, log_level='info')
"
