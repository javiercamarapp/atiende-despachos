#!/usr/bin/env bash
# =============================================================================
# test.sh — Corre la suite de tests + verificación del deploy (landing+API).
#
#   ./test.sh            → tests unitarios/integración (pytest).
#   ./test.sh --all      → tests + smoke test sobre el contenedor (si corre).
#   ./test.sh --smoke    → solo smoke test HTTP sobre http://localhost:8000.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-unit}"

run_pytest() {
    echo "→ Suite de tests (pytest) ..."
    if [ -d .venv ]; then
        ./.venv/bin/python -m pytest -q
    else
        python -m pytest -q
    fi
}

smoke_test() {
    local base="${1:-http://localhost:8000}"
    echo "→ Smoke test sobre ${base} ..."
    local fail=0

    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "$base/")
    echo "  GET /             → ${code}  (esperado 200)"
    [ "$code" = "200" ] || fail=1

    code=$(curl -s -o /dev/null -w "%{http_code}" "$base/robots.txt")
    echo "  GET /robots.txt   → ${code}  (esperado 200)"
    [ "$code" = "200" ] || fail=1

    code=$(curl -s -o /dev/null -w "%{http_code}" "$base/health")
    echo "  GET /health       → ${code}  (esperado 200)"
    [ "$code" = "200" ] || fail=1

    # /api/v1/* debe rechazar sin API key (401) → prueba que la auth está activa.
    code=$(curl -s -o /dev/null -w "%{http_code}" "$base/api/v1/stats")
    echo "  GET /api/v1/stats (sin key) → ${code}  (esperado 401)"
    [ "$code" = "401" ] || fail=1

    if [ "$fail" -ne 0 ]; then
        echo "  ✗ Smoke test FALLÓ."
        return 1
    fi
    echo "  ✔ Smoke test OK."
}

case "$MODE" in
    unit|--unit)
        run_pytest
        ;;
    --all)
        run_pytest
        smoke_test "${2:-http://localhost:8000}"
        ;;
    --smoke)
        smoke_test "${2:-http://localhost:8000}"
        ;;
    *)
        echo "Uso: $0 [unit|--all|--smoke]"
        exit 2
        ;;
esac
