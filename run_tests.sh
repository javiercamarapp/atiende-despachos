#!/usr/bin/env bash
# run_tests.sh — ejecuta la suite de tests del repo enterprise con:
#   * ulimit alto (evita "Resource deadlock avoided" por agotamiento de descriptores/mmap)
#   * timeout razonable (por defecto 15 min por invocacion)
#   * sin escribir caches (no:cacheprovider) y sin generar __pycache__ residual
#
# Uso:
#   ./run_tests.sh                 # suite completa (tests/)
#   ./run_tests.sh tests/test_x.py # subconjunto concreto
#   TIMEOUT=600 ./run_tests.sh     # override del timeout (segundos)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# --- Python correcto: usar .venv/bin/python3.11 directamente.
# El activate del repo hardcodea un VIRTUAL_ENV stale (--private/tmp/enterprise-clean),
# por lo que NO se hace source. Fallback a python3 del PATH.
if [[ -x "$REPO_DIR/.venv/bin/python3.11" ]]; then
    PY="$REPO_DIR/.venv/bin/python3.11"
elif [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PY="$REPO_DIR/.venv/bin/python"
else
    PY="$(command -v python3 || command -v python)"
fi
echo ">>> Python: $PY"
"$PY" --version

# --- ulimit alto: descriptores de archivo (raiz de mmap corruption en macOS)
CURRENT_ULIMIT="$(ulimit -n)"
TARGET_ULIMIT=4096
if [[ "$CURRENT_ULIMIT" -lt "$TARGET_ULIMIT" ]]; then
    ulimit -n "$TARGET_ULIMIT" 2>/dev/null \
        && echo ">>> ulimit -n: $CURRENT_ULIMIT -> $(ulimit -n)" \
        || echo ">>> aviso: no se pudo subir ulimit -n (queda en $CURRENT_ULIMIT)"
else
    echo ">>> ulimit -n ya es suficiente: $CURRENT_ULIMIT"
fi

# --- timeout (default 900s)
TIMEOUT="${TIMEOUT:-900}"

# --- target de tests: args pasados o suite completa
if [[ $# -eq 0 ]]; then
    TEST_TARGET="tests"
else
    TEST_TARGET="$*"
fi

echo ">>> Target: $TEST_TARGET"
echo ">>> Timeout: ${TIMEOUT}s"

# --- ejecutar
# -p no:cacheprovider: no reescribe .pytest_cache
# PYTHONDONTWRITEBYTECODE=1: no genera __pycache__ (evita re-sembrar mmap residual)
PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest $TEST_TARGET \
    --no-header \
    -p no:cacheprovider

EC=$?
echo ""
echo ">>> pytest salio con exit code: $EC"
exit "$EC"
