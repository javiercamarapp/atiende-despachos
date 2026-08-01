#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_test.py — Pruebas de carga del enterprise MVP contra un servidor real.

Levanta uvicorn (subproceso, puerto efímero) con una DB on-disk temporal y,
contra él:

  1. N usuarios concurrentes golpeando GET /api/v1/stats (httpx).
  2. Batch de CFDI por el pipeline (medición local, in-process).
Métricas de latencia: p50, p95, p99 (ms).

Uso:
    python3 scripts/load_test.py [--users 100] [--reqs 3] [--batch 10000]
        [--host 127.0.0.1] [--port 0] [--json]

Nota: el rate limiter se desactiva (B2B_RATE_LIMIT=off) para medir el
rendimiento real de la API; la protección anti-abuso se cubre en
tests/test_e2e_security.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from gen_cfdis import generate  # noqa: E402

import httpx  # noqa: E402
from b2b_ai.db.db import Database  # noqa: E402
from b2b_ai.services.pipeline import process_batch, summarize  # noqa: E402


def _percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(host, port, timeout=30):
    url = f"http://{host}:{port}/health"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Servidor no respondió en {timeout}s: {url}")


def _start_server(db_path, key, host, port):
    """Prepara la DB y levanta uvicorn como subproceso. Devuelve Popen."""
    db = Database(db_path)
    t = db.create_tenant("Carga")
    db.create_api_key(t, "carga", key)
    db.close()

    env = dict(os.environ)
    env["B2B_DB_PATH"] = db_path
    env["B2B_RATE_LIMIT"] = "off"
    cmd = [sys.executable, "-m", "uvicorn", "b2b_ai.api.app:app",
           "--host", host, "--port", str(port), "--log-level", "warning"]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def _load_concurrent(host, port, key, users, reqs_per_user):
    lat, codes = [], []
    headers = {"X-API-Key": key}

    def _hit(_):
        t0 = time.perf_counter()
        try:
            r = httpx.get(f"http://{host}:{port}/api/v1/stats",
                          headers=headers, timeout=30)
            codes.append(r.status_code)
        except Exception:
            codes.append(0)
        finally:
            lat.append((time.perf_counter() - t0) * 1000.0)

    with ThreadPoolExecutor(max_workers=users) as ex:
        list(ex.map(_hit, range(users * reqs_per_user)))
    return lat, codes


def _batch_n(n, tmpdir):
    generate(n, tmpdir)
    db = Database(":memory:")
    t0 = time.perf_counter()
    results = process_batch(tmpdir, db=db)
    wall = time.perf_counter() - t0
    s = summarize(results)
    db.close()
    return s, wall


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--reqs", type=int, default=3, help="peticiones por usuario")
    ap.add_argument("--batch", type=int, default=10000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--key", default="load-test-key-0001")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tmpdir", default=None)
    args = ap.parse_args()

    tmpdir = args.tmpdir or os.path.join(
        tempfile.gettempdir(), f"b2b_load_{int(time.time())}")
    work = tempfile.mkdtemp(prefix="b2b_load_srv_")
    db_path = os.path.join(work, "load.db")
    port = args.port or _find_free_port()

    proc = _start_server(db_path, args.key, args.host, port)
    try:
        _wait_health(args.host, port)
        lat, codes = _load_concurrent(args.host, port, args.key,
                                      args.users, args.reqs)
        ok = codes.count(200)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    s, wall = _batch_n(args.batch, tmpdir)
    shutil.rmtree(work, ignore_errors=True)

    result = {
        "concurrentes": {
            "usuarios": args.users,
            "peticiones": len(lat),
            "ok": ok,
            "p50_ms": round(_percentile(lat, 50), 2),
            "p95_ms": round(_percentile(lat, 95), 2),
            "p99_ms": round(_percentile(lat, 99), 2),
        },
        "batch": {
            "n": args.batch,
            "procesadas": s["procesadas"],
            "validas": s["validas"],
            "wall_seg": round(wall, 3),
            "throughput_cfdi_s": round(s["procesadas"] / wall, 2),
        },
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        cc = result["concurrentes"]
        print(f"\n=== Carga: {cc['usuarios']} usuarios concurrentes "
              f"({cc['peticiones']} peticiones) ===")
        print(f"  OK        : {cc['ok']}/{cc['peticiones']}")
        print(f"  Latencia  : p50={cc['p50_ms']}ms  "
              f"p95={cc['p95_ms']}ms  p99={cc['p99_ms']}ms")
        b = result["batch"]
        print(f"\n=== Batch {b['n']} CFDI ===")
        print(f"  Procesadas: {b['procesadas']} (válidas {b['validas']})")
        print(f"  Wall      : {b['wall_seg']} s")
        print(f"  Throughput: {b['throughput_cfdi_s']} CFDI/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
