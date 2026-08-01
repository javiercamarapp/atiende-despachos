#!/usr/bin/env bash
# =============================================================================
# B&B AI — Deploy Verification Script
# Verifica que todo está listo antes de hacer deploy a Railway/Vercel
# Uso: bash scripts/verify-deploy.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
  local desc="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✅${NC} $desc"
    ((PASS++))
  else
    echo -e "  ${RED}❌${NC} $desc"
    ((FAIL++))
  fi
}

warn_check() {
  local desc="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✅${NC} $desc"
    ((PASS++))
  else
    echo -e "  ${YELLOW}⚠️${NC} $desc (recomendado)"
    ((WARN++))
  fi
}

echo ""
echo "🔍 B&B AI — Deploy Verification"
echo "================================"
echo ""

# --- 1. Python environment ---
echo "📦 Entorno Python"
check "Python 3.11+ disponible" python3 -c "import sys; assert sys.version_info >= (3,11)"
check "pyproject.toml existe" test -f pyproject.toml
check "requirements.txt o poetry.lock" bash -c "test -f requirements.txt || test -f poetry.lock || test -f pyproject.toml"
echo ""

# --- 2. Code quality ---
echo "🧪 Suite de tests"
check "Tests pasan (0 fallos)" python3 -m pytest tests/ -x -q --tb=no 2>&1 | grep -E "passed|0 failed"
echo ""

# --- 3. Docker ---
echo "🐳 Docker"
check "Dockerfile existe" test -f Dockerfile
check "Docker build OK" docker build -t b2b-ai:verify . 2>&1 | tail -1 | grep -i "success\|error" | grep -v error
warn_check ".dockerignore existe" test -f .dockerignore
echo ""

# --- 4. Railway config ---
echo "🚂 Railway"
check "railway.toml existe" test -f railway.toml
check "railway.toml tiene healthcheck" grep -q "healthcheckPath" railway.toml
check "Dockerfile configurado en railway.toml" grep -q 'dockerfilePath' railway.toml
echo ""

# --- 5. Landing page ---
echo "🌐 Landing"
check "index.html existe" test -f landing/index.html
check "vercel.json existe" test -f landing/vercel.json
check "manifest.json válido" python3 -c "import json; json.load(open('landing/manifest.json'))"
check "sw.js existe" test -f landing/sw.js
check "Assets (og-image)" test -f landing/assets/og-image.jpg
warn_check "Assets (hero image)" test -f landing/assets/hero.jpg
warn_check "Assets (hero video)" test -f landing/assets/hero-ai-dashboard.mp4
echo ""

# --- 6. Environment variables ---
echo "🔑 Variables de entorno"
warn_check ".env.example existe" test -f .env.example
if [ -f .env ]; then
  check "B2B_API_KEY configurado" grep -q "B2B_API_KEY=change-me" .env && false || true
  check "B2B_JWT_SECRET configurado" grep -q "B2B_JWT_SECRET=" .env && test "$(grep B2B_JWT_SECRET .env | cut -d= -f2 | wc -c)" -gt 5
else
  echo -e "  ${YELLOW}⚠️${NC} .env no existe (copiar de .env.example)"
  ((WARN++))
fi
echo ""

# --- 7. API ---
echo "🔌 API"
check "FastAPI app importable" python3 -c "from b2b_ai.api.app import app"
check "OpenAPI spec válida" python3 -c "
from b2b_ai.api.app import app
spec = app.openapi()
assert 'paths' in spec and len(spec['paths']) > 10
"
echo ""

# --- 8. Database ---
echo "🗄️ Base de datos"
check "Alembic migrations presentes" test -d migrations
check "Latest migration existe" bash -c "ls migrations/versions/*.py | tail -1 | grep -q ."
echo ""

# --- Summary ---
echo "================================"
TOTAL=$((PASS + FAIL + WARN))
echo -e "📊 Resultados: ${GREEN}${PASS} pass${NC}, ${RED}${FAIL} fail${NC}, ${YELLOW}${WARN} warn${NC} / ${TOTAL} total"
echo ""

if [ $FAIL -eq 0 ]; then
  echo -e "${GREEN}🚀 ¡Listo para deploy!${NC}"
  echo ""
  echo "Próximos pasos:"
  echo "  1. railway login"
  echo "  2. railway up"
  echo "  3. railway variables set B2B_API_KEY=<random>"
  echo "  4. railway variables set B2B_JWT_SECRET=<random>"
  echo "  5. railway variables set B2B_ENV=production"
  exit 0
else
  echo -e "${RED}⛔ Hay ${FAIL} problema(s) que resolver antes de deploy.${NC}"
  exit 1
fi
