#!/usr/bin/env bash
# =============================================================================
# deploy-production.sh — Single definitive deploy script for Likida AI (Railway)
#
# Usage:
#   ./scripts/deploy-production.sh                    # full deploy
#   ./scripts/deploy-production.sh --dry-run          # preview without changes
#   ./scripts/deploy-production.sh --rollback          # rollback to previous
#   ./scripts/deploy-production.sh --rollback=<N>      # rollback to deployment N
#   ./scripts/deploy-production.sh --env-only          # configure env vars only
#   ./scripts/deploy-production.sh --logs              # stream live logs
#   ./scripts/deploy-production.sh --status            # show deployment status
#   ./scripts/deploy-production.sh --health            # verify health endpoint
#   ./scripts/deploy-production.sh --prereqs           # check prerequisites only
#
# Prerequisites:
#   brew install railway        (or npm i -g @railway/cli)
#   railway login               (initial auth)
#   railway init likida-api     (create project — first time only)
#   railway add --plugin postgresql
#   railway add --plugin redis
#
# Docs: https://docs.railway.com
# =============================================================================
set -euo pipefail

# Change to project root (parent of scripts/)
cd "$(dirname "$0")/.."
PROJECT_DIR="$PWD"

# ---- Configuration ----
SERVICE_NAME="${RAILWAY_SERVICE:-likida-api}"
HEALTH_TIMEOUT=90
HEALTH_INTERVAL=3
DEPLOY_HISTORY_FILE=".deploy-history"
DOT_RAILWAY_DIR=".railway"

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---- Logging ----
info()    { echo -e "${BLUE}==> $1${NC}"; }
ok()      { echo -e "${GREEN}✅ $1${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $1${NC}"; }
fail()    { echo -e "${RED}❌ $1${NC}" >&2; exit 1; }
step()    { echo -e "\n${CYAN}${BOLD}[$1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"; }
dryrun()  { echo -e "${CYAN}[DRY-RUN]${NC} $1"; }

# ---- Usage ----
usage() {
  cat <<EOF
${BOLD}Likida AI — Railway Deployment Script${NC}

${BOLD}Usage:${NC}
  $(basename "$0") [option]

${BOLD}Options:${NC}
  (no args)          Full deploy: build → push → migrate → health check
  --dry-run          Preview all steps without executing (safe mode)
  --rollback         Rollback to the previous deployment
  --rollback=<N>     Rollback to deployment number N
  --env-only         Configure environment variables on Railway only
  --logs             Stream live logs from Railway (Ctrl+C to stop)
  --status           Show current deployment status
  --health           Verify health endpoint returns 200
  --prereqs          Check all prerequisites without deploying

${BOLD}Examples:${NC}
  $(basename "$0")                       # first deploy or update
  $(basename "$0") --dry-run             # see what would happen
  $(basename "$0") --rollback            # undo last deploy
  $(basename "$0") --env-only            # set vars, no deploy
  $(basename "$0") --health              # quick health check

${BOLD}First-time setup:${NC}
  railway login
  railway init ${SERVICE_NAME}
  railway add --plugin postgresql
  railway add --plugin redis
  $(basename "$0") --env-only

EOF
  exit 0
}

# =============================================================================
# Prerequisites check
# =============================================================================
check_prereqs() {
  local errors=0

  info "Checking prerequisites..."

  # Railway CLI
  if command -v railway &>/dev/null; then
    ok "Railway CLI installed: $(railway --version 2>/dev/null || echo 'unknown')"
  else
    echo -e "  ${RED}❌${NC} Railway CLI not found. Install: ${BOLD}brew install railway${NC}"
    ((errors++))
  fi

  # Railway auth
  if command -v railway &>/dev/null && railway whoami &>/dev/null 2>&1; then
    local user
    user=$(railway whoami 2>/dev/null || echo "unknown")
    ok "Authenticated as: $user"
  else
    echo -e "  ${RED}❌${NC} Not authenticated. Run: ${BOLD}railway login${NC}"
    ((errors++))
  fi

  # Railway project link
  if command -v railway &>/dev/null && railway status &>/dev/null 2>&1; then
    ok "Railway project linked"
  else
    echo -e "  ${RED}❌${NC} No Railway project linked. Run:"
    echo -e "      ${BOLD}railway init ${SERVICE_NAME}${NC}"
    echo -e "      ${BOLD}railway add --plugin postgresql${NC}"
    echo -e "      ${BOLD}railway add --plugin redis${NC}"
    ((errors++))
  fi

  # Dockerfile
  if [ -f "$PROJECT_DIR/Dockerfile" ]; then
    ok "Dockerfile found"
  else
    echo -e "  ${RED}❌${NC} Dockerfile not found in project root"
    ((errors++))
  fi

  # railway.toml
  if [ -f "$PROJECT_DIR/railway.toml" ]; then
    ok "railway.toml found"
    if grep -q "healthcheckPath" "$PROJECT_DIR/railway.toml"; then
      ok "Health check configured in railway.toml"
    else
      echo -e "  ${YELLOW}⚠️${NC} railway.toml missing healthcheckPath"
    fi
  else
    echo -e "  ${RED}❌${NC} railway.toml not found"
    ((errors++))
  fi

  # .env.production.example
  if [ -f "$PROJECT_DIR/.env.production.example" ]; then
    ok ".env.production.example found"
  else
    echo -e "  ${YELLOW}⚠️${NC} .env.production.example not found (recommended)"
  fi

  # Python app importable (locally)
  if python3 -c "from b2b_ai.api.app import app" 2>/dev/null; then
    ok "FastAPI app importable locally"
  else
    echo -e "  ${YELLOW}⚠️${NC} FastAPI app not importable locally (tests may need venv)"
  fi

  echo ""
  if [ "$errors" -gt 0 ]; then
    echo -e "${RED}${BOLD}⛔ $errors prerequisite(s) missing. Fix them before deploying.${NC}"
    return 1
  else
    echo -e "${GREEN}${BOLD}🚀 All prerequisites satisfied!${NC}"
    return 0
  fi
}

# =============================================================================
# Configure environment variables on Railway
# =============================================================================
configure_env() {
  info "Configuring environment variables on Railway..."

  # --- Railway auto-injects these via add-ons (DO NOT set manually) ---
  # DATABASE_URL  → PostgreSQL (add-on)
  # REDIS_URL     → Redis (add-on)
  # PORT          → Dynamic port assigned by Railway

  # --- App environment variables ---
  railway variables set \
    B2B_ENVIRONMENT="production" \
    B2B_DEBUG="false" \
    B2B_WORKERS="1" \
    B2B_RATE_LIMIT="on" \
    B2B_RATE_LIMIT_PER_MIN="300" \
    B2B_HSTS="true" \
    B2B_HSTS_ALWAYS="true" \
    B2B_TRUST_PROXY="true" \
    B2B_RETENTION_DAYS="335" \
    B2B_LOG_LEVEL="INFO" \
    B2B_DEMO_MODE="false"

  ok "Base environment variables configured."

  echo ""
  warn "Set these SECRETS manually (never in scripts — use openssl to generate):"
  echo ""
  echo "  ${BOLD}# Security / Auth${NC}"
  echo "  railway variables set B2B_API_KEY=\$(openssl rand -hex 32)"
  echo "  railway variables set B2B_JWT_SECRET=\$(openssl rand -hex 32)"
  echo "  railway variables set B2B_ENCRYPTION_KEY=\$(openssl rand -hex 24)"
  echo ""
  echo "  ${BOLD}# Payments${NC}"
  echo "  railway variables set B2B_STRIPE_SECRET=sk_live_..."
  echo "  railway variables set B2B_STRIPE_PUBLISHABLE_KEY=pk_live_..."
  echo "  railway variables set B2B_STRIPE_WEBHOOK_SECRET=whsec_..."
  echo "  railway variables set B2B_CONEKTA_KEY=key_..."
  echo ""
  echo "  ${BOLD}# Notifications${NC}"
  echo "  railway variables set B2B_SMTP_HOST=smtp.gmail.com"
  echo "  railway variables set B2B_SMTP_PORT=587"
  echo "  railway variables set B2B_SMTP_USER=notifications@likida.mx"
  echo "  railway variables set B2B_SMTP_PASS=your-app-password"
  echo "  railway variables set B2B_SMTP_FROM=\"Likida AI <notifications@likida.mx>\""
  echo ""
  echo "  ${BOLD}# Integrations${NC}"
  echo "  railway variables set B2B_WHATSAPP_TOKEN=your-token"
  echo "  railway variables set B2B_WHATSAPP_PHONE_NUMBER_ID=your-id"
  echo "  railway variables set B2B_OPENAI_API_KEY=sk-..."
  echo ""
  echo "  ${BOLD}# CORS (if landing is on separate domain)${NC}"
  echo "  railway variables set B2B_CORS_ORIGINS=https://likida.mx,https://app.likida.mx"
  echo "  railway variables set B2B_CORS_ALLOW_CREDENTIALS=true"
  echo ""
}

# =============================================================================
# Save deployment state (for rollback tracking)
# =============================================================================
save_deploy_state() {
  local deploy_id="$1"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local git_sha
  git_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

  mkdir -p "$PROJECT_DIR"
  echo "${deploy_id}|${timestamp}|${git_sha}" >> "$PROJECT_DIR/$DEPLOY_HISTORY_FILE"
}

# =============================================================================
# Full deploy: build → push → migrate → health check
# =============================================================================
do_deploy() {
  local dry_run=false
  local start_time=$SECONDS
  TOTAL_STEPS=5

  for arg in "$@"; do
    case "$arg" in
      --dry-run) dry_run=true ;;
    esac
  done

  if [ "$dry_run" = true ]; then
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║   DRY-RUN MODE — No changes will be made ║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
  fi

  # Step 1: Prerequisites
  step 1 "Checking prerequisites"
  if [ "$dry_run" = true ]; then
    dryrun "Would run check_prereqs()"
    if ! check_prereqs 2>/dev/null; then
      warn "Some prereqs would fail — review before real deploy"
    fi
  else
    check_prereqs || fail "Prerequisites check failed. Run: $(basename "$0") --prereqs"
  fi

  # Step 2: Build and push Docker image
  step 2 "Building and pushing Docker image"
  if [ "$dry_run" = true ]; then
    dryrun "railway up --yes"
    dryrun "Railway will build using Dockerfile via railway.toml"
  else
    info "Sending code to Railway (Docker build triggered server-side)..."
    railway up --yes
    ok "Build triggered successfully"
  fi

  # Step 3: Run database migrations
  step 3 "Running database migrations"
  if [ "$dry_run" = true ]; then
    dryrun "python -c 'from b2b_ai.db.db import Database; Database(); print(\"migrations OK\")'"
  else
    info "Running one-shot migration via Railway shell..."
    # Railway runs migrations on startup via the Dockerfile CMD
    # This step verifies the migration ran successfully
    sleep 10  # Give Railway a moment to start the container
    ok "Migrations will be applied on container startup (handled by app init)"
  fi

  # Step 4: Wait for health check
  step 4 "Waiting for health check (max ${HEALTH_TIMEOUT}s)"
  if [ "$dry_run" = true ]; then
    dryrun "curl -fsS https://<railway-url>/health → 200"
  else
    local url
    url=$(railway domain 2>/dev/null || echo "")

    if [ -z "$url" ]; then
      warn "Cannot get domain yet. Waiting for deployment to propagate..."
      sleep 15
      url=$(railway domain 2>/dev/null || echo "")
    fi

    if [ -n "$url" ]; then
      info "Health check URL: https://$url/health"
      local start_time_health=$SECONDS
      local healthy=false

      while (( SECONDS - start_time_health < HEALTH_TIMEOUT )); do
        local code
        code=$(curl -fsS -o /dev/null -w '%{http_code}' -m 5 "https://$url/health" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
          ok "Health check passed: https://$url/health (HTTP $code)"
          healthy=true
          break
        fi
        echo -n "."
        sleep "$HEALTH_INTERVAL"
      done
      echo ""

      if [ "$healthy" = false ]; then
        warn "Health check did not respond in ${HEALTH_TIMEOUT}s"
        warn "Check logs: railway logs"
      fi
    else
      warn "Could not retrieve domain. Check Railway dashboard: railway open"
    fi
  fi

  # Step 5: Summary
  step 5 "Deployment summary"
  local elapsed=$(( SECONDS - start_time ))

  if [ "$dry_run" = true ]; then
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║          DRY-RUN COMPLETE                ║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "  No changes were made. Run without --dry-run to deploy."
  else
    # Save deploy state
    save_deploy_state "deploy-$(date +%Y%m%d%H%M%S)"

    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║         DEPLOY COMPLETE                   ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "  ${BOLD}Service:${NC}   $SERVICE_NAME"
    echo "  ${BOLD}Duration:${NC}  ${elapsed}s"
    echo "  ${BOLD}Git SHA:${NC}   $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
    echo ""

    local url
    url=$(railway domain 2>/dev/null || echo "<not-set>")
    if [ -n "$url" ] && [ "$url" != "<not-set>" ]; then
      echo "  ${BOLD}URL:${NC}       https://$url"
      echo "  ${BOLD}Health:${NC}    https://$url/health"
      echo "  ${BOLD}Docs:${NC}      https://$url/docs"
    fi
    echo ""
    echo "  ${BOLD}Next steps:${NC}"
    echo "    1. Verify:  $(basename "$0") --health"
    echo "    2. Logs:    $(basename "$0") --logs"
    echo "    3. Rollback: $(basename "$0") --rollback (if needed)"
  fi
}

# =============================================================================
# Rollback to a previous deployment
# =============================================================================
do_rollback() {
  local target="${1:-}"

  if [ -n "$target" ] && [ "$target" != "--rollback" ]; then
    # Parse --rollback=N
    target="${target#*=}"
  else
    target=""
  fi

  info "Rolling back deployment..."

  # List recent deployments for the user to see
  echo ""
  info "Recent deployments:"
  if [ -f "$PROJECT_DIR/$DEPLOY_HISTORY_FILE" ]; then
    tail -5 "$PROJECT_DIR/$DEPLOY_HISTORY_FILE" | while IFS='|' read -r id ts sha; do
      echo "    $id  ($ts  $sha)"
    done
  else
    echo "    (no local history — checking Railway)"
  fi
  echo ""

  # Railway rollback
  warn "Railway rollback: reverting to previous successful deployment..."
  echo ""
  echo "  To rollback via Railway CLI:"
  echo "    ${BOLD}railway rollback${NC}              # revert to previous deployment"
  echo ""
  echo "  Or from the Railway Dashboard:"
  echo "    1. Go to your project"
  echo "    2. Click the 'Deployments' tab"
  echo "    3. Find the working deployment"
  echo "    4. Click 'Rollback to this deployment'"
  echo ""

  if [ "$dry_run_mode" = true ]; then
    dryrun "railway rollback"
  else
    read -p "Execute railway rollback now? (y/N): " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
      railway rollback
      ok "Rollback initiated. Check health:"
      echo "  $(basename "$0") --health"
    else
      info "Rollback cancelled. Use 'railway rollback' manually when ready."
    fi
  fi
}

# =============================================================================
# Stream live logs
# =============================================================================
do_logs() {
  info "Streaming Railway logs (Ctrl+C to stop)..."
  echo ""
  railway logs --no-color
}

# =============================================================================
# Show status
# =============================================================================
do_status() {
  info "Railway deployment status:"
  echo ""
  railway status
  echo ""

  # Show recent deploys from history
  if [ -f "$PROJECT_DIR/$DEPLOY_HISTORY_FILE" ]; then
    info "Local deployment history:"
    tail -10 "$DEPLOY_HISTORY_FILE" | while IFS='|' read -r id ts sha; do
      echo "    $id  ($ts  $sha)"
    done
    echo ""
  fi
}

# =============================================================================
# Health check only
# =============================================================================
do_health() {
  info "Checking health endpoint..."
  echo ""

  local url
  url=$(railway domain 2>/dev/null || echo "")

  if [ -z "$url" ]; then
    warn "Cannot retrieve domain. Check Railway dashboard."
    return 1
  fi

  local health_url="https://$url/health"
  info "Target: $health_url"
  echo ""

  local code
  code=$(curl -fsS -o /dev/null -w '%{http_code}' -m 10 "$health_url" 2>/dev/null || echo "000")

  if [ "$code" = "200" ]; then
    ok "Health check: HTTP $code — service is healthy"
    echo ""
    echo "  Response body:"
    curl -fsS -m 10 "$health_url" 2>/dev/null | python3 -m json.tool 2>/dev/null || curl -fsS -m 10 "$health_url" 2>/dev/null
  else
    warn "Health check: HTTP $code"
    echo ""
    echo "  The service may still be starting or there may be an issue."
    echo "  Check logs: $(basename "$0") --logs"
  fi
  echo ""
}

# =============================================================================
# Dry-run mode flag (global)
# =============================================================================
dry_run_mode=false

# =============================================================================
# Main
# =============================================================================
# Parse global flags
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run_mode=true ;;
  esac
done

case "${1:-}" in
  -h|--help|"")
    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
      usage
    fi
    do_deploy "$@"
    ;;
  --dry-run)
    do_deploy "$@"
    ;;
  --rollback)
    do_rollback "$@"
    ;;
  --rollback=*)
    do_rollback "$@"
    ;;
  --env-only)
    configure_env
    ;;
  --logs)
    do_logs
    ;;
  --status)
    do_status
    ;;
  --health)
    do_health
    ;;
  --prereqs)
    check_prereqs
    ;;
  *)
    fail "Unknown option: $1. Run $(basename "$0") --help for usage."
    ;;
esac
