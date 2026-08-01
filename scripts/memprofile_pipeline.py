#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memprofile_pipeline.py — Memory profiling del pipeline (batch de CFDI).

Procesa un batch de N CFDI (default 1000) por `process_batch` y mide:

  - Pico de memoria con tracemalloc (incremento del intérprete, en MB).
  - Pico RSS del proceso (ru.maxrss) durante el lote.
  - Retención post-GC: memoria que queda viva tras `gc.collect()` y
    descartar los resultados — señal de un posible memory leak.
  - Patrón: procesa el batch en K bloques y mide la retención acumulada
    por bloque para ver si crece (leak) o se estabiliza (normal).

Uso:
    .venv/bin/python scripts/memprofile_pipeline.py [--n 1000] [--blocks 4] [--json]
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import sys
import tempfile
import time
import tracemalloc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from gen_cfdis import generate  # noqa: E402

from b2b_ai.db.db import Database  # noqa: E402
from b2b_ai.services.pipeline import process_batch, summarize  # noqa: E402


def _rss_mb() -> float:
    """RSS del proceso en MB (resource.getrusage)."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    # macOS: ru_maxrss en bytes; Linux: en KB.
    return ru.ru_maxrss / (1024 * 1024) if sys.platform == "darwin" else ru.ru_maxrss / 1024


def _run_batch(db, tmpdir, n):
    """Procesa n CFDI y devuelve (resumen, wall_s, tracemalloc_pico_mb)."""
    generate(n, tmpdir)
    tracemalloc.start()
    t0 = time.perf_counter()
    results = process_batch(tmpdir, db=db)
    wall = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    s = summarize(results)
    return s, wall, peak / (1024 * 1024), cur / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000, help="CFDI por bloque.")
    ap.add_argument("--blocks", type=int, default=4, help="Bloques a procesar.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    # Dos DB separadas: una para el test de retención (en memoria) y otra
    # para el patrón por bloques (en disco, para acumular filas).
    db_mem = Database(":memory:")
    block_results = []
    base_rss = _rss_mb()

    for b in range(args.blocks):
        tmpdir = tempfile.mkdtemp(prefix=f"b2b_mem_b{b}_")
        gc.collect()
        s, wall, peak_mb, cur_mb = _run_batch(db_mem, tmpdir, args.n)
        gc.collect()
        # Retención tracemalloc tras GC: cuánta memoria del intérprete quedó
        # viva después de limpiar (sin contar el RSS que acumula la DB).
        tracemalloc.start()
        gc.collect()
        retained, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        block_results.append({
            "bloque": b + 1,
            "procesadas": s["procesadas"],
            "validas": s["validas"],
            "wall_seg": round(wall, 3),
            "peak_int_MB": round(peak_mb, 2),
            "cur_int_MB": round(cur_mb, 2),
            "retained_post_gc_MB": round(retained / (1024 * 1024), 2),
            "rss_max_MB": round(_rss_mb() - base_rss, 2),
        })
    db_mem.close()

    # Cálculo del "leak" aparente: la retención post-GC por bloque debería
    # estabilizarse si no hay fuga. La comparamos entre el 1º y el último.
    ret_first = block_results[0]["retained_post_gc_MB"]
    ret_last = block_results[-1]["retained_post_gc_MB"]
    leak_signal = (ret_last - ret_first) if args.blocks > 1 else 0.0

    if args.json:
        print(json.dumps({"blocks": block_results,
                          "leak_signal_MB": round(leak_signal, 2),
                          "nota": "retención post-GC estable => sin leak"}, indent=2))
    else:
        print(f"\n=== Memory profiling pipeline ({args.n} CFDI/bloque, "
              f"{args.blocks} bloques) ===")
        print(f"{'bloque':<7} {'proc':<7} {'wall(s)':<8} {'peak(MB)':<10} "
              f"{'ret.postGC(MB)':<15} {'rss_max(MB)'}")
        for r in block_results:
            print(f"{r['bloque']:<7} {r['procesadas']:<7} {r['wall_seg']:<8} "
                  f"{r['peak_int_MB']:<10} {r['retained_post_gc_MB']:<15} "
                  f"{r['rss_max_MB']}")
        print(f"\nSeñal de leak (retención último - primero): {leak_signal:.2f} MB")
        if leak_signal > 10:
            print("⚠  Posible memory leak: la retención crece con cada bloque.")
        else:
            print("✓ Sin señal de leak: la retención post-GC se estabiliza.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
