#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_pilot.py — Demo Likida AI Enterprise en un solo comando.

Levanta el servidor FastAPI, puebla la base demo y recorre el flujo completo
CFDI → bookkeeping → conciliación, más 3 escenarios comerciales, todo con
salida visual en terminal para mostrarlo a un prospecto.

Uso:
    python scripts/demo_pilot.py                 # todo automático, puerto 8000
    python scripts/demo_pilot.py --port 8080     # puerto custom
    python scripts/demo_pilot.py --db /tmp/demo.db

Qué hace:
    1. Puebla la BD demo (scripts/demo_data/demo_pilot.db) con seed_demo.py
       (3 tenants, 300 CFDIs, 150 transacciones, 30 nóminas).
    2. Levanta la API FastAPI en http://localhost:<port>.
    3. Escenario S0 — Pipeline completo: POST /api/v1/pipeline/run
       (upload CFDI → parse → bookkeeping → conciliación bancaria real).
    4. Escenario A — Procesamiento de CFDI: POST /api/v1/invoices/process
       (subida multipart de un XML, validación + clasificación + póliza ERP).
    5. Escenario B — Nómina: POST /api/v1/payroll/calculate (ISR/IMSS/neto).
    6. Escenario C — Conciliación bancaria: POST /api/v1/reconcile/run.
    7. Resumen + apagado limpio del servidor.

Los datos de ejemplo viven en scripts/demo_data/ (CFDIs XML, transacciones
bancarias y nóminas) y se pueden personalizar por prospecto.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# ── Entorno ANTES de importar la app (create_app hace fail-fast de config) ──
# Este script se auto-configura como entorno de desarrollo/demo local.
_ROOT = Path(__file__).resolve().parent.parent
_DEMO_DIR = Path(__file__).resolve().parent / "demo_data"
_CFDI_DIR = _DEMO_DIR / "cfdi"
_BANCO_DIR = _DEMO_DIR / "bancos"
_NOMINA_DIR = _DEMO_DIR / "nominas"

_DEFAULT_DB = _DEMO_DIR / "demo_pilot.db"

os.environ.setdefault("B2B_ENV", "local")
os.environ.setdefault("B2B_API_KEY", "demo-key-likida-2026")
os.environ.setdefault("B2B_DEFAULT_TENANT_ID", "1")
os.environ.setdefault("B2B_DB_PATH", str(_DEFAULT_DB))

sys.path.insert(0, str(_ROOT))

# ── Colores / formato ANSI ──
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_BLUE = "\033[94m"


def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}"


def _line(char: str = "─", n: int = 78) -> str:
    return char * n


def _banner(text: str):
    print()
    print(_c(_CYAN, _line("═", 78)))
    print(_c(_BOLD + _CYAN, text.center(78)))
    print(_c(_CYAN, _line("═", 78)))


def _section(text: str):
    print()
    print(_c(_BLUE + _BOLD, "▸ " + text))


def _ok(text: str):
    print(_c(_GREEN, "  ✔ " + text))


def _kv(key: str, value: str):
    print(f"    {_c(_BOLD, key + ':'):<28}{value}")


def _warn(text: str):
    print(_c(_YELLOW, "  ⚠ " + text))


def _money(x) -> str:
    try:
        return f"${float(x):,.2f} MXN"
    except (TypeError, ValueError):
        return str(x)


# ── Cliente HTTP ligero (stdlib) ─────────────────────────────────────────────
def _http_json(method: str, url: str, payload=None, headers=None) -> tuple:
    import urllib.error
    import urllib.request
    hdrs = {"X-API-Key": os.environ["B2B_API_KEY"]}
    if headers:
        hdrs.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"detail": body}


def _http_multipart(url: str, file_field: str, filename: str, file_bytes: bytes,
                    extra_fields: dict | None = None) -> tuple:
    """POST multipart/form-data (subida de archivo) usando solo stdlib."""
    import urllib.error
    import urllib.request
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (extra_fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/xml\r\n\r\n"
    )
    body = ("".join(parts)).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    hdrs = {
        "X-API-Key": os.environ["B2B_API_KEY"],
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"detail": body}


# ── Setup ────────────────────────────────────────────────────────────────────
def seed_db(db_path: Path) -> None:
    """Puebla la BD demo ejecutando seed_demo.py."""
    _section("Poblando base de datos demo (seed_demo.py)")
    seed_script = _ROOT / "scripts" / "seed_demo.py"
    cmd = [sys.executable, str(seed_script), "--db", str(db_path)]
    print(f"    $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    # Mostramos el resumen final (la parte visual del seeder).
    tail = (proc.stdout or "").strip().splitlines()[-14:]
    print("\n".join("    " + ln for ln in tail))
    if proc.returncode != 0:
        sys.exit(_c(_RED, "\n  ✘ El seed falló:\n") + (proc.stderr or proc.stdout))
    _ok(f"Base demo lista: {db_path}")


def build_app(db):
    """Construye la app FastAPI y le añade el router del pipeline end-to-end."""
    from b2b_ai.api.app import create_app
    from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
    from b2b_ai.features.pipeline.routes import build_pipeline_router

    app = create_app(db=db)
    require_api_key = make_require_api_key(APIKeyAuth(db))
    app.include_router(build_pipeline_router(db=db, require_api_key=require_api_key))
    return app


def start_server(app, host: str, port: int):
    """Levanta uvicorn en un hilo de fondo y espera el /health."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True, name="demo-uvicorn")
    t.start()

    url = f"http://{host}:{port}"
    base = f"{url}/health"
    for _ in range(60):
        try:
            st, _ = _http_json("GET", base)
            if st == 200:
                return url, server
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(_c(_RED, f"El servidor no respondió en {url}"))
