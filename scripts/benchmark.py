#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
benchmark.py — Benchmarks de performance del enterprise MVP.

Mide:
  1. Throughput : CFDI procesados por segundo (process_file, pipeline completo).
  2. Latencia   : tiempo promedio por CFDI (ms).
  3. Memoria    : uso de memoria bajo carga (tracemalloc, pico incremental).
  4. DB         : queries por segundo (list_invoices / count_invoices /
                  invoice_stats en bucle).

Uso:
    python3 scripts/benchmark.py [--n 200] [--db /tmp/bench.db] [--json]

Salida: tabla por métrica; con --json, JSON para CI. Usa la DB en memoria
por defecto (más rápida) salvo que se pase --db.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import tracemalloc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from gen_cfdis import generate  # noqa: E402

from b2b_ai.db.db import Database  # noqa: E402
from b2b_ai.services.pipeline import process_file  # noqa: E402

_FIXTURE = os.path.join(ROOT, "fixtures", "cfdis",
                        "02_inversion_consultoria.xml")


def _bench_pipeline(n, tmpdir):
    """Procesa `n` CFDI únicos por el pipeline completo y mide throughput."""
    generate(n, tmpdir)
    db = Database(":memory:")
    files = sorted(os.path.join(tmpdir, f)
                   for f in os.listdir(tmpdir) if f.endswith(".xml"))

    # warm-up + medición
    tracemalloc.start()
    t0 = time.perf_counter()
    for f in files:
        process_file(f, db=db)
    wall = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    db.close()

    cps = n / wall
    avg_ms = (wall / n) * 1000.0
    return {"throughput_cfdi_s": round(cps, 2),
            "latencia_avg_ms": round(avg_ms, 2),
            "wall_seg": round(wall, 3),
            "memoria_pico_mb": round(peak / (1024 * 1024), 2),
            "n": n}


def _bench_db_queries(db, n=5000):
    """Mide QPS de las consultas de listado / stats."""
    bench = {}
    for name, fn in (("list_invoices", db.list_invoices),
                     ("count_invoices", db.count_invoices),
                     ("invoice_stats", db.invoice_stats)):
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        wall = time.perf_counter() - t0
        bench[name] = round(n / wall, 1)
    return bench


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--db", default=None, help="Ruta DB (default: memoria).")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tmpdir", default=None)
    args = ap.parse_args()

    tmpdir = args.tmpdir or os.path.join(
        os.environ.get("TMPDIR", "/tmp"), f"b2b_bench_{int(time.time())}")

    pipe = _bench_pipeline(args.n, tmpdir)
    db = Database(args.db or ":memory:")
    qps = _bench_db_queries(db)
    db.close()

    result = {"pipeline": pipe, "db_queries_per_s": qps}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        p = pipe
        print(f"\n=== Benchmark pipeline ({p['n']} CFDI) ===")
        print(f"  Throughput : {p['throughput_cfdi_s']} CFDI/s")
        print(f"  Latencia   : {p['latencia_avg_ms']} ms promedio por CFDI")
        print(f"  Memoria    : {p['memoria_pico_mb']} MB pico incremental")
        print(f"  Wall       : {p['wall_seg']} s")
        print("\n=== DB queries/s (5k cada una) ===")
        for k, v in qps.items():
            print(f"  {k:<16}: {v} q/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
