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
    """Puebla la BD demo ejecutando seed_demo.py (la regenera desde cero)."""
    _section("Poblando base de datos demo (seed_demo.py)")
    if db_path.exists():
        try:
            db_path.unlink()
            print(f"    Base previa eliminada: {db_path.name}")
        except OSError:
            pass
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

    config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                            lifespan="off")
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


# ── Carga de datos demo ──────────────────────────────────────────────────────
def load_cfdis() -> list[tuple]:
    """Devuelve [(filename, content_xml)] de todos los CFDIs demo (emitidos + recibidos)."""
    files = sorted(_CFDI_DIR.glob("*.xml"))
    return [(f.name, f.read_text(encoding="utf-8")) for f in files]


def load_bank_transactions() -> list[dict]:
    return json.loads((_BANCO_DIR / "transacciones.json").read_text(encoding="utf-8"))["transacciones"]


def load_payrolls() -> list[dict]:
    return json.loads((_NOMINA_DIR / "nominas.json").read_text(encoding="utf-8"))["empleados"]


# ── Escenarios ───────────────────────────────────────────────────────────────
def scenario_pipeline(base: str):
    """S0 — Pipeline completo CFDI → bookkeeping → conciliación (un solo POST)."""
    _banner("ESCENARIO S0 · Pipeline completo (CFDI → parse → bookkeeping → conciliación)")
    _section("POST /api/v1/pipeline/run")

    cfdis = load_cfdis()
    # Seleccionamos un subconjunto representativo para no saturar la salida.
    by_name = {n: c for n, c in cfdis}
    picked_names = ["emitido_01.xml", "emitido_03.xml", "emitido_04.xml",
                    "recibido_01.xml", "recibido_03.xml"]
    picked = [(n, by_name[n]) for n in picked_names]
    # Transacciones bancarias: las que cruzan con esos CFDIs + 2 sin cruce (nómina, SAT).
    txs = load_bank_transactions()
    refs = {"11111111-2222-4333-8444-555555555501", "11111111-2222-4333-8444-555555555503",
            "11111111-2222-4333-8444-555555555504", "21111111-2222-4333-8444-555555555501",
            "21111111-2222-4333-8444-555555555503"}
    matched_tx = [t for t in txs if t["reference"] in refs]
    extra = [t for t in txs if t["reference"] in ("NOM-2026-07-08", "SAT-IVA-2026-07")]
    bank_tx = matched_tx + extra

    print(f"    Subiendo {_c(_BOLD, str(len(picked)))} CFDIs y "
          f"{_c(_BOLD, str(len(bank_tx)))} movimientos bancarios …")

    payload = {
        "cfdis": [{"filename": n, "content": c} for n, c in picked],
        "periodo": "2026-07",
        "auto_register_erp": True,
        "bank_transactions": bank_tx,
        "date_tolerance_days": 3,
    }
    st, res = _http_json("POST", f"{base}/api/v1/pipeline/run", payload)
    if st != 200:
        _warn(f"Respuesta {st}: {json.dumps(res)[:300]}")
        return res

    _ok(f"status={res.get('status')}  job_id={res.get('job_id')}")
    _kv("CFDIs parseados", str(res.get("cfdis_parsed")))
    _kv("Clasificaciones", str(res.get("classifications_count")))
    _kv("Pólizas generadas", str(res.get("polizas_count")))
    _kv("Referencias ERP", str(len(res.get("erp_references") or [])))
    parse_errors = res.get("parse_errors") or []
    if parse_errors:
        _warn(f"{len(parse_errors)} CFDI(s) con error de parseo (aislados)")

    rec = res.get("reconciliation")
    if isinstance(rec, dict) and rec.get("ok"):
        rep = rec.get("report") or {}
        print()
        _section("Conciliación bancaria (motor real)")
        _kv("Transacciones a conciliar", str(rep.get("total_transactions")))
        _kv("Conciliadas", str(rep.get("matched")))
        _kv("Sin conciliar", str(rep.get("unmatched")))
        _kv("Discrepancias", str(rep.get("discrepancies")))
        _kv("Tasa de conciliación", f"{rep.get('match_rate')}%")
        for m in (rec.get("poliza_matches") or [])[:3]:
            print(f"      · {_c(_CYAN, str(m.get('bank_transaction_id')))} → "
                  f"póliza {str(m.get('poliza_id'))[:12]} "
                  f"[{str(m.get('match_type'))} · conf {m.get('confidence_score')}]")
    elif isinstance(rec, dict):
        _warn("Conciliación no pudo completarse: " + str(rec.get("error", rec)))
    return res


def scenario_cfdi_process(base: str):
    """A — Procesamiento de un CFDI (subida multipart real)."""
    _banner("ESCENARIO A · Procesamiento de CFDI (upload → validar → clasificar → ERP)")
    _section("POST /api/v1/invoices/process (multipart)")
    xml_path = _CFDI_DIR / "recibido_03.xml"
    st, res = _http_multipart(
        f"{base}/api/v1/invoices/process",
        file_field="xml_file", filename=xml_path.name,
        file_bytes=xml_path.read_bytes(),
    )
    if st != 200:
        _warn(f"Respuesta {st}: {json.dumps(res)[:300]}")
        return res
    r = res.get("result") or res
    _kv("Archivo", r.get("archivo", xml_path.name))
    _kv("RFC emisor", r.get("emisor"))
    _kv("Total", _money(r.get("total")))
    _kv("Válido", "Sí" if r.get("valido") else "No")
    _kv("Requiere revisión humana", "Sí" if r.get("requires_human_review") else "No")
    _kv("Categoría", r.get("categoria"))
    _kv("Confianza", f"{float(r.get('confianza') or 0)*100:.1f}%")
    _kv("Póliza ERP", str(r.get("erp_poliza")))
    _kv("Estado ERP", str(r.get("erp_status")))
    _ok("CFDI procesado e insertado en la BD")
    return res


def scenario_nomina(base: str):
    """B — Cálculo de nómina (ISR / IMSS / neto)."""
    _banner("ESCENARIO B · Nómina (cálculo ISR · IMSS · neto)")
    _section("POST /api/v1/payroll/calculate")
    emp = load_payrolls()[0]
    payload = {
        "empleado": {"nombre": emp["nombre"], "rfc": emp["rfc"], "salario_diario": emp["salario_diario"]},
        "periodo": {"sueldo_bruto": emp["sueldo_bruto"], "dias_pagados": emp["dias_pagados"]},
        "generar_cfdi": False,
    }
    st, res = _http_json("POST", f"{base}/api/v1/payroll/calculate", payload)
    if st != 200:
        _warn(f"Respuesta {st}: {json.dumps(res)[:300]}")
        return res
    _kv("Empleado", emp["nombre"])
    _kv("RFC", emp["rfc"])
    perc = res.get("percepciones") or {}
    ded = res.get("deducciones") or {}
    _kv("Sueldo bruto", _money(perc.get("total", emp["sueldo_bruto"])))
    _kv("Total gravado", _money(perc.get("total_gravado")))
    _kv("ISR retenido", _money(ded.get("isr")))
    _kv("IMSS", _money(ded.get("imss")))
    _kv("Neto a pagar", _money(res.get("neto_a_pagar")))
    _ok("Nómina calculada correctamente")
    return res


def scenario_conciliacion(base: str):
    """C — Conciliación bancaria cruzando CFDIs del mes contra el banco."""
    _banner("ESCENARIO C · Conciliación bancaria (CFDIs vs estado de cuenta)")
    _section("POST /api/v1/reconcile/run")
    from b2b_ai.cfdi.parser import parse_cfdi_4

    # Derivamos las facturas demo desde los XML (uuid/fecha/total/emisor).
    invoices = []
    for name, content in load_cfdis():
        try:
            p = parse_cfdi_4(content)
        except Exception:
            continue
        invoices.append({
            "folio_fiscal": p.get("cfdi_uuid") or p.get("uuid"),
            "fecha": (p.get("fecha") or "")[:10],
            "total": float(p.get("total") or 0),
            "emisor": p.get("emisor", {}).get("rfc") or p.get("rfc_emisor"),
        })

    bank = [
        {"fecha": t["date"], "monto": float(t["amount"]), "descripcion": t["description"],
         "ref": t["reference"], "tipo": t["type"], "banco": t["bank_account"].split()[0]}
        for t in load_bank_transactions()
    ]
    payload = {"invoices": invoices, "bank_transactions": bank, "date_tolerance_days": 3}
    st, res = _http_json("POST", f"{base}/api/v1/reconcile/run", payload)
    if st != 200:
        _warn(f"Respuesta {st}: {json.dumps(res)[:300]}")
        return res
    _kv("Facturas en el periodo", str(res.get("facturas")))
    _kv("Movimientos bancarios", str(res.get("movimientos_banco")))
    _kv("Conciliados", str(res.get("conciliados")))
    _kv("Pendientes banco", str(res.get("pendientes_banco")))
    _kv("Pendientes facturas", str(res.get("pendientes_facturas")))
    _kv("Monto conciliado", _money(res.get("monto_conciliado")))
    _kv("Tasa de conciliación", f"{res.get('tasa_conciliacion')}%")
    for m in (res.get("matched") or [])[:4]:
        print(f"      · {_c(_CYAN, str(m.get('folio_fiscal'))[:12])}…  "
              f"{_money(m.get('monto'))}  vía {m.get('via')}")
    _ok("Reporte de conciliación generado")
    return res


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Demo Likida AI Enterprise en un comando.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default=str(_DEFAULT_DB),
                   help="Ruta de la base demo (default: scripts/demo_data/demo_pilot.db)")
    args = p.parse_args(argv)

    db_path = Path(args.db).expanduser().resolve()

    _banner("LIKIDA AI ENTERPRISE — DEMO AUTOMÁTICA")
    print(_c(_DIM, "  Pipeline contable end-to-end para presentación a prospecto"))

    # 1) Semilla
    seed_db(db_path)

    # 2) App + servidor
    from b2b_ai.db.db import Database
    db = Database(str(db_path))
    app = build_app(db)
    _section(f"Levantando servidor API en http://{args.host}:{args.port}")
    base, server = start_server(app, args.host, args.port)
    _ok(f"Servidor listo · API key demo: {os.environ['B2B_API_KEY']} · tenant_id=1")

    try:
        scenario_pipeline(base)
        scenario_cfdi_process(base)
        scenario_nomina(base)
        scenario_conciliacion(base)

        # Resumen
        _banner("RESUMEN")
        _ok("Demo completada correctamente (3 escenarios + pipeline end-to-end).")
        _ok("Base demo: " + str(db_path))
        _ok(f"Servidor: {base}  ·  documentación OpenAPI: {base}/docs")
        print(_c(_DIM, "\n  Apagando servidor …"))
    finally:
        server.should_exit = True
        time.sleep(0.6)
    return 0


if __name__ == "__main__":
    sys.exit(main())

