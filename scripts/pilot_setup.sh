#!/usr/bin/env bash
# =============================================================================
# pilot_setup.sh — One-click pilot environment setup for Likida AI Enterprise
#
# Automatiza todo el proceso de preparar un tenant de demo para piloto:
#   1. Verifica prerequisitos (Python 3.11, pip, PostgreSQL si se pide PG)
#   2. Crea venv e instala dependencias
#   3. Aplica migraciones de BD
#   4. Siembra datos demo realistas mexicanos (scripts/seed_demo.py)
#   5. Arranca el server y verifica el health check (/health)
#   6. Genera credenciales demo (API key + tenant admin)
#   7. Imprime credenciales + URL + instrucciones de acceso
#
# Uso:
#   ./scripts/pilot_setup.sh
#   ./scripts/pilot_setup.sh --fresh --port 9000
#   ./scripts/pilot_setup.sh --tenant-name "Despacho Demo SA de CV"
#   B2B_DATABASE_URL=postgresql://b2b:pass@localhost:5432/b2b_ai ./scripts/pilot_setup.sh
#
# Flags:
#   --fresh           Resetea la BD antes de migrar (borra b2b_ai.db en SQLite,
#                     o recrea la BD en PostgreSQL).
#   --tenant-name     Nombre del tenant demo a crear (default: 1er tenant del seed).
#   --port <N>        Puerto del server (default 8000).
#   --host <H>        Host de bind (default 0.0.0.0).
#   --db <ruta|dsn>   Ruta SQLite o DSN PostgreSQL. Default: B2B_DATABASE_URL | b2b_ai.db.
#   --no-serve        Verifica el arranque (health check) y detiene el server
#                     (no lo deja corriendo).
#   --reinstall       Fuerza reinstalación de dependencias en el venv.
#
# Requiere: bash >= 4, Python 3.11, curl. PostgreSQL solo si se usa DSN postgres.
# =============================================================================
set -euo pipefail

# ---- Resolución de rutas ----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ---- Configuración por defecto ----------------------------------------------
PORT=8000
HOST="0.0.0.0"
FRESH=false
REINSTALL=false
SERVE=true
TENANT_NAME=""
DB_ARG=""
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

# ---- Parsing de flags -------------------------------------------------------
usage() {
    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh) FRESH=true ;;
        --reinstall) REINSTALL=true ;;
        --no-serve) SERVE=false ;;
        --tenant-name) TENANT_NAME="$2"; shift ;;
        --port) PORT="$2"; shift ;;
        --host) HOST="$2"; shift ;;
        --db) DB_ARG="$2"; shift ;;
        -h|--help) usage ;;
        *) echo "❌ Flag desconocido: $1"; usage ;;
    esac
    shift
done

# ---- Helpers ----------------------------------------------------------------
step() { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m  ✔ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m  ⚠ %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✖ %s\033[0m\n" "$*" >&2; exit 1; }

# ---- Variables de entorno de desarrollo (fail-fast del server) --------------
B2B_JWT_SECRET="${B2B_JWT_SECRET:-$(openssl rand -hex 32)}"
B2B_ENCRYPTION_KEY="${B2B_ENCRYPTION_KEY:-$(openssl rand -hex 24)}"
B2B_ENV="${B2B_ENV:-development}"
export B2B_JWT_SECRET B2B_ENCRYPTION_KEY B2B_ENV

# Resolución de BD: --db > B2B_DATABASE_URL > DATABASE_URL > B2B_DB_PATH > SQLite default
IS_PG=false
DB_TARGET="${DB_ARG:-}"
if [[ -z "$DB_TARGET" ]]; then
    DB_TARGET="${B2B_DATABASE_URL:-${DATABASE_URL:-${B2B_DB_PATH:-}}}"
fi
if [[ -z "$DB_TARGET" ]]; then
    DB_TARGET="b2b_ai.db"   # SQLite junto al repo
fi
if [[ "$DB_TARGET" == postgres* ]]; then
    IS_PG=true
    export B2B_DATABASE_URL="$DB_TARGET"
else
    export B2B_DB_PATH="$DB_TARGET"
fi

# ---------------------------------------------------------------------------
# 1. PREREQUISITOS
# ---------------------------------------------------------------------------
step "1/7 Verificando prerequisitos"

"$PYTHON_BIN" --version 2>/dev/null | grep -qE "Python 3\.(1[1-9]|[2-9][0-9])" \
    || warn "No se encontró Python 3.11+ ('$PYTHON_BIN'). Intentando continuar de todas formas."

if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    ok "Python: $("$PYTHON_BIN" --version 2>&1)"
else
    die "Python 3.11 no está en el PATH (busca '$PYTHON_BIN'). Instala Python 3.11+."
fi
command -v curl >/dev/null 2>&1 || warn "curl no encontrado; el health check usará Python."

if [[ "$IS_PG" == true ]]; then
    if command -v psql >/dev/null 2>&1; then
        ok "PostgreSQL: psql $(psql --version 2>&1 | sed 's/psql (PostgreSQL) //')"
    else
        warn "psql no está en el PATH — asumimos que PostgreSQL ya corre (DSN: $DB_TARGET)."
    fi
else
    ok "BD local SQLite: $DB_TARGET (PostgreSQL no requerido)"
fi

# ---------------------------------------------------------------------------
# 2. VENV + DEPENDENCIAS
# ---------------------------------------------------------------------------
step "2/7 Preparando entorno (venv + dependencias)"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    ok "venv creado en $VENV_DIR"
fi

PY="$REPO_ROOT/$VENV_DIR/bin/python"
PIP="$REPO_ROOT/$VENV_DIR/bin/pip"

if [[ "$REINSTALL" == true ]] || ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    ok "Instalando dependencias del proyecto (editable + extras)"
    "$PIP" install --upgrade pip setuptools wheel
    # pyproject.toml es la fuente de verdad de dependencias (no hay requirements.txt raíz).
    if [[ -f "requirements-production.txt" ]]; then
        "$PIP" install -r requirements-production.txt || warn "requisitos prod parciales"
    fi
    "$PIP" install -e ".[test]" || die "Fallo instalando dependencias (ver arriba)."
else
    ok "Dependencias ya instaladas (usa --reinstall para forzar)"
fi

# ---------------------------------------------------------------------------
# 3. MIGRACIONES DE BD (+ reset con --fresh)
# ---------------------------------------------------------------------------
step "3/7 Migrando base de datos"

if [[ "$FRESH" == true ]]; then
    if [[ "$IS_PG" == true ]]; then
        warn "--fresh en PostgreSQL: no se auto-borra la BD por seguridad."
        warn "  Borra/recrea la BD manualmente y vuelve a correr el script."
    elif [[ -f "$DB_TARGET" ]]; then
        rm -f "$DB_TARGET"
        ok "BD SQLite eliminada ($DB_TARGET)"
    fi
fi

if [[ -f "alembic.ini" ]] && "$PY" -c "import alembic" >/dev/null 2>&1; then
    if "$PY" -m alembic upgrade head >/dev/null 2>&1; then
        ok "Migraciones aplicadas (alembic upgrade head)"
    else
        warn "alembic falló — usando Database.migrate() como respaldo."
        "$PY" -c "from b2b_ai.db.db import Database; Database().migrate()" \
            && ok "Esquema creado/migrado (Database.migrate)"
    fi
else
    "$PY" -c "from b2b_ai.db.db import Database; Database().migrate()" \
        && ok "Esquema creado/migrado (Database.migrate)"
fi

# ---------------------------------------------------------------------------
# 4. SEED — datos demo realistas mexicanos
# ---------------------------------------------------------------------------
step "4/7 Sembrando datos demo mexicanos (seed_demo.py)"

SEED_ARGS=()
if [[ -n "$DB_ARG" ]]; then
    SEED_ARGS+=(--db "$DB_ARG")
fi
if [[ ${#SEED_ARGS[@]} -gt 0 ]]; then
    "$PY" scripts/seed_demo.py "${SEED_ARGS[@]}" || warn "seed_demo.py falló — revisa la salida."
else
    "$PY" scripts/seed_demo.py || warn "seed_demo.py falló — revisa la salida."
fi

# ---------------------------------------------------------------------------
# 5. CREDENCIALES DEMO (API key + tenant admin)
# ---------------------------------------------------------------------------
step "5/7 Generando credenciales demo"

# Pequeño helper Python que crea el tenant demo (si se pidió uno custom) y
# emite una API key válida contra la BD real usando el adaptador de la app.
CREDS_FILE="${REPO_ROOT}/.pilot_credentials"
"$PY" - "$DB_ARG" "$TENANT_NAME" <<'PYEOF' | tee "$CREDS_FILE"
import sys, secrets, hashlib
from b2b_ai.db.db import Database

db_arg = sys.argv[1] if len(sys.argv) > 1 else ""
tenant_name = sys.argv[2] if len(sys.argv) > 2 else ""

db = Database()

def emit(tid, name):
    key = "demo-" + secrets.token_hex(16)
    db.create_api_key(tid, "demo-admin", key)
    rfc = ""
    ts = db.list_tenants()
    row = next((t for t in ts if str(t["id"]) == str(tid)), None)
    if row:
        rfc = row.get("rfc", "")
        name = row.get("name", name)
    # Email admin REAL sembrado por seed_demo (password = demo-pass-<email>).
    email = ""
    try:
        cur = db.conn.execute(
            "SELECT email FROM users WHERE tenant_id=? AND role='admin' ORDER BY id LIMIT 1",
            (tid,))
        r = cur.fetchone()
        if r:
            email = r[0]
    except Exception:
        email = ""
    if not email:
        email = f"admin@tenant{tid}.demo.mx"
    print(f"DEMO_TENANT_ID={tid}")
    print(f"DEMO_TENANT_NAME={name}")
    print(f"DEMO_TENANT_RFC={rfc}")
    print(f"DEMO_API_KEY={key}")
    print(f"DEMO_ADMIN_EMAIL={email}")
    print(f"DEMO_ADMIN_PASSWORD=demo-pass-{email}")
    print(f"# Auth header: X-API-Key: {key}")

if tenant_name:
    ts = db.list_tenants()
    existing = next((t for t in ts if t.get("name") == tenant_name), None)
    if existing:
        emit(existing["id"], tenant_name)
    else:
        tid = db.create_tenant(tenant_name, rfc="XAXX010101000")
        admin_email = f"admin@{tenant_name.lower().replace(' ','').replace(',','')}.mx"
        uid = db.create_user(tid, "Admin Demo", admin_email, role="admin")
        # Credencial de login real siguiendo la convención del seed (client_users:
        # email + password_hash = sha256("demo-pass-<email>")).
        try:
            pw = hashlib.sha256(f"demo-pass-{admin_email}".encode()).hexdigest()
            db.conn.execute(
                "INSERT INTO client_users(tenant_id,email,password_hash,name,role) "
                "VALUES (?,?,?,?,?)",
                (tid, admin_email, pw, "Admin Demo", "admin"))
            db.conn.commit()
        except Exception:
            pass
        emit(tid, tenant_name)
else:
    ts = db.list_tenants()
    if not ts:
        print("ERROR: No hay tenants — corre primero el seed.", file=sys.stderr)
        sys.exit(1)
    emit(ts[0]["id"], ts[0]["name"])
PYEOF

if [[ -s "$CREDS_FILE" ]]; then
    ok "Credenciales guardadas en .pilot_credentials"
else
    warn "No se pudieron generar credenciales API."
fi

# ---------------------------------------------------------------------------
# 6. HEALTH CHECK — arranca el server y verifica /health
# ---------------------------------------------------------------------------
step "6/7 Verificando arranque del server (health check)"

if [[ "$SERVE" == false ]]; then
    warn "--no-serve: omitiendo arranque/health check."
else
    LOG="${REPO_ROOT}/.pilot_server.log"
    "$PY" -m uvicorn b2b_ai.api.app:app --host "$HOST" --port "$PORT" \
        >"$LOG" 2>&1 &
    SRV_PID=$!
    echo "$SRV_PID" > .pilot_server.pid
    trap 'kill "$SRV_PID" 2>/dev/null || true' EXIT

    # Poll /health hasta timeout (20s)
    HEALTH_OK=false
    for i in $(seq 1 20); do
        if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            HEALTH_OK=true
            break
        fi
        if ! kill -0 "$SRV_PID" 2>/dev/null; then
            warn "El server murió durante el arranque. Log: $LOG"
            tail -30 "$LOG" >&2
            break
        fi
        sleep 1
    done

    if [[ "$HEALTH_OK" == true ]]; then
        ok "Health check OK — server responde en http://${HOST}:${PORT}/health"
    else
        warn "No se confirmó el health check dentro de 20s (revisa $LOG)."
    fi

    if [[ "$SERVE" == true ]]; then
        # El trap EXIT no debe matar el server si lo dejamos corriendo.
        trap - EXIT
        disown "$SRV_PID" 2>/dev/null || true
        ok "Server corriendo en background (PID $SRV_PID). Detener con: kill $SRV_PID"
    fi
fi

# ---------------------------------------------------------------------------
# 7. OUTPUT — credenciales + URL + instrucciones
# ---------------------------------------------------------------------------
step "7/7 Resumen del piloto"

URL="http://${HOST}:${PORT}"
cat <<EOF

═══════════════════════════════════════════════════════════════════
  ✅  PILOTO LISTO — Likida AI Enterprise
═══════════════════════════════════════════════════════════════════
  API ................. $URL
  Health check ........ $URL/health
  Swagger UI .......... $URL/docs
  ReDoc ............... $URL/redoc
  OpenAPI ............. $URL/openapi.json
═══════════════════════════════════════════════════════════════════
EOF

if [[ -f "$CREDS_FILE" ]]; then
    grep -E "DEMO_" "$CREDS_FILE" | sed 's/^/  /'
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    echo "  Probar con:"
    KEY=$(grep '^DEMO_API_KEY=' "$CREDS_FILE" | cut -d= -f2)
    echo "    curl -s -H \"X-API-Key: $KEY\" $URL/api/v1/stats"
    echo ""
    echo "  Detener el server:  kill \$(cat .pilot_server.pid)   (o Ctrl-C si está en foreground)"
    echo "  Volver a sembrar:   $0 --fresh --no-serve"
fi

echo ""
ok "Pilot setup completo."
exit 0
