#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
profile_endpoints.py — Profiling de endpoints del enterprise MVP.

Mide, contra una DB temporal sembrada con N facturas:
  1. Tiempo de respuesta de CADA endpoint de lectura (p50/p95/max en ms).
  2. cProfile del pipeline (process_batch) → top funciones por tiempo.

Uso:
    .venv/bin/python scripts/profile_endpoints.py [--n 500] [--db /tmp/prof.db] [--json]
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import shutil
import sys
import tempfile
import time
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from gen_cfdis import generate  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from b2b_ai.db.db import Database  # noqa: E402
from b2b_ai.services.pipeline import process_batch, summarize  # noqa: E402

KEY = "prof-key-0001"


def _seed(db, n):
    t = db.create_tenant("Profiling")
    db.create_api_key(t, "prof", KEY)
    db.create_user(t, "Contador", "c@b2b-ai.local")
    # Sembrar facturas directamente (rápido, sin pipeline) para darle volumen
    # real a las lecturas agregadas.
    for i in range(n):
        db.conn.execute(
            """INSERT INTO invoices
               (tenant_id, folio_fiscal, archivo, fecha, tipo, serie, folio,
                emisor_rfc, emisor_nombre, receptor_rfc, subtotal, iva, total,
                moneda, descripcion, categoria, confianza, razon_clasificacion,
                valido, requires_human_review, issues, status, procesado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t, f"F-{i:06d}-{i}", f"cfdi_{i:06d}.xml",
             f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
             "I", "A", str(i), "XAXX010101000", f"Emisor {i % 50}",
             "XAXX010101000", "1000.00", "160.00", "1160.00",
             "MXN", f"Servicios {i % 20}",
             ("gastos_operativos" if i % 3 else "servicios_profesionales"),
             0.95, "regla", 1, 0, "", "procesado",
             "2026-07-31T10:00:00"))
    db.conn.commit()
    return t


def _read_endpoints(app, n_iter=30):
    """Mide latencia por endpoint con TestClient (loopback, sin red)."""
    client = TestClient(app)
    h = {"X-API-Key": KEY}
    endpoints = [
        ("/health", None),
        ("/api/v1/invoices", h),
        ("/api/v1/invoices?tenant_id=1&limit=50", h),
        ("/api/v1/stats", h),
        ("/api/v1/accounting/balance", h),
        ("/api/v1/dashboard/data", h),
        ("/api/v1/dashboard/summary", h),
        ("/api/v1/dashboard/monthly", h),
        ("/api/v1/dashboard/by-provider", h),
    ]
    result = {}
    for path, hdr in endpoints:
        lat = []
        ok = 0
        codes = {}
        for _ in range(n_iter):
            t0 = time.perf_counter()
            r = client.get(path, headers=hdr or {})
            dt = (time.perf_counter() - t0) * 1000.0
            lat.append(dt)
            if r.status_code == 200:
                ok += 1
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
            if r.status_code != 200 and "_first_err_" not in result:
                result["_first_err_"] = {path: r.status_code, "body": str(r.text)[:300]}
        lat.sort()
        result[path] = {
            "ok": f"{ok}/{n_iter}",
            "codes": codes,
            "p50_ms": round(lat[len(lat) // 2], 2),
            "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 2),
            "p99_ms": round(lat[int(len(lat) * 0.99) - 1], 2),
            "max_ms": round(lat[-1], 2),
            "avg_ms": round(statistics.mean(lat), 2),
        }
    return result


def _cprofile_pipeline(n, tmpdir):
    generate(n, tmpdir)
    db = Database(":memory:")
    pr = cProfile.Profile()
    pr.enable()
    results = process_batch(tmpdir, db=db)
    pr.disable()
    s = summarize(results)
    db.close()

    buf = io.StringIO()
    ps = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    ps.print_stats(25)
    return s, buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--db", default=None)
    ap.add_argument("--pipeline", type=int, default=150)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    work = tempfile.mkdtemp(prefix="b2b_prof_")
    db_path = args.db or os.path.join(work, "prof.db")
    db = Database(db_path)
    _seed(db, args.n)
    db.close()

    from b2b_ai.api.app import create_app
    # Instrument get_api_key to reveal intermittent auth failures.
    import b2b_ai.db.db as _D
    _orig_gak = _D.Database.get_api_key
    def _patched_gak(self, key):
        try:
            return _orig_gak(self, key)
        except Exception as e:  # noqa: BLE001
            print(f"[AUTH-INSTR] get_api_key EXC: {type(e).__name__}: {e}")
            raise
    _D.Database.get_api_key = _patched_gak
    app = create_app(db=Database(db_path))
    endpoints = _read_endpoints(app, n_iter=20)

    tmp = os.path.join(work, "cfdis")
    pipe_sum, prof_out = _cprofile_pipeline(args.pipeline, tmp)
    shutil.rmtree(work, ignore_errors=True)

    if args.json:
        print(json.dumps({"endpoints": endpoints,
                          "pipeline_summary": pipe_sum}, indent=2))
    else:
        if "_first_err_" in endpoints:
            print("\n=== PRIMER ERROR ===")
            print(json.dumps(endpoints.pop("_first_err_"), indent=2))
        print(f"\n=== Latencia por endpoint (n={args.n} facturas, "
              f"DB={db_path}) ===")
        print(f"{'endpoint':<42} {'ok':<6} {'p50':>8} {'p95':>8} "
              f"{'p99':>8} {'max':>8}  (ms)")
        for path, m in endpoints.items():
            print(f"{path:<42} {m['ok']:<6} {m['p50_ms']:>7}ms "
                  f"{m['p95_ms']:>7}ms {m['p99_ms']:>7}ms {m['max_ms']:>7}ms"
                  f"  codes={m['codes']}")
        print(f"\n=== Pipeline ({args.pipeline} CFDI) ===")
        print(f"  {pipe_sum['procesadas']} procesadas, "
              f"{pipe_sum['validas']} válidas")
        print("\n=== cProfile top (cumulative) ===")
        print(prof_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
