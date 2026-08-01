#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_test_improved.py — Load testing del enterprise MVP contra servidor real.

Levanta uvicorn (subproceso, puerto efímero) con una DB on-disk sembrada y
golpea los endpoints de lectura con N usuarios concurrentes. Mide:

  - Latencia  : p50 / p95 / p99 (ms) y promedio.
  - Throughput: requests/second agregado y por endpoint.
  - Errores   : códigos de estado (200 / 401 / 429 / 5xx / timeout).

Niveles de carga: 50, 100 y 200 usuarios concurrentes (por defecto),
o uno solo con --users N.

Output: tabla en consola y, con --report, un reporte markdown en disco.

Uso:
    .venv/bin/python scripts/load_test_improved.py
    .venv/bin/python scripts/load_test_improved.py --users 200 --endpoints stats,invoices
    .venv/bin/python scripts/load_test_improved.py --report reports/load_test.md

Nota: el rate limiter se desactiva (B2B_RATE_LIMIT=off) para medir el
rendimiento real de la API; la protección anti-abuso se cubre en
tests/test_e2e_security.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import httpx  # noqa: E402
from b2b_ai.db.db import Database  # noqa: E402

KEY = "load-test-key-0001"

# Endpoints de lectura a probar (todas requieren X-API-Key).
ENDPOINTS = {
    "stats": "/api/v1/stats",
    "invoices": "/api/v1/invoices",
    "balance": "/api/v1/accounting/balance",
    "dashboard": "/api/v1/dashboard/data",
    "dashboard_summary": "/api/v1/dashboard/summary",
    "dashboard_monthly": "/api/v1/dashboard/monthly",
}


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


def _wait_health(host, port, timeout=40):
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


def _seed(db_path, n_invoices):
    """Crea tenant + API key y siembra `n_invoices` para dar volumen real."""
    db = Database(db_path)
    t = db.create_tenant("Load")
    db.create_api_key(t, "load", KEY)
    db.create_user(t, "Contador", "c@b2b-ai.local")
    batch = []
    for i in range(n_invoices):
        batch.append((
            t, f"L-{i:06d}-{i}", f"cfdi_{i:06d}.xml",
            f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
            "I", "A", str(i),
            f"EM{i % 40:09d}AA", f"Emisor {i % 40}",  # RFC distribuido realista
            "XAXX010101000", "1000.00", "160.00", "1160.00", "MXN",
            f"Servicios {i % 15}",
            "gastos_operativos" if i % 3 else "servicios_profesionales",
            0.95, "regla", 1, 0, "", "procesado", "2026-07-31T10:00:00"))
    db.conn.executemany(
        """INSERT INTO invoices
           (tenant_id, folio_fiscal, archivo, fecha, tipo, serie, folio,
            emisor_rfc, emisor_nombre, receptor_rfc, subtotal, iva, total,
            moneda, descripcion, categoria, confianza, razon_clasificacion,
            valido, requires_human_review, issues, status, procesado_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", batch)
    db.conn.commit()
    db.close()


def _start_server(db_path, key, host, port):
    env = dict(os.environ)
    env["B2B_DB_PATH"] = db_path
    env["B2B_RATE_LIMIT"] = "off"
    cmd = [sys.executable, "-m", "uvicorn", "b2b_ai.api.app:app",
           "--host", host, "--port", str(port), "--log-level", "warning"]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def _run_level(host, port, key, users, endpoint_names, reqs_per_user=3):
    """Lanza `users` hilos concurrentes; cada uno pega los endpoints elegidos.

    Usa UN solo httpx.Client compartido (connection pool con límites altos) para
    que el proceso de carga NO agote file descriptors al abrir un socket por
    hilo (ulimit -n típico = 256). De este modo la medición refleja el
    rendimiento real del servidor, no el límite de fds del cliente de carga.
    """
    base = f"http://{host}:{port}"
    headers = {"X-API-Key": key}
    targets = [(name, base + path) for name, path in ENDPOINTS.items()
               if name in endpoint_names]

    results = {name: {"lat": [], "codes": Counter()} for name, _ in targets}
    t_level0 = time.perf_counter()

    # Un solo pool compartido por todos los hilos (thread-safe).
    shared = httpx.Client(
        base_url=base, headers=headers, timeout=30,
        limits=httpx.Limits(max_connections=users + 10,
                            max_keepalive_connections=users + 10))

    def _worker(_):
        for name, url in targets:
            for _ in range(reqs_per_user):
                t0 = time.perf_counter()
                try:
                    r = shared.get(url)
                    code = r.status_code
                except Exception:
                    code = 0  # timeout / conn error
                dt = (time.perf_counter() - t0) * 1000.0
                results[name]["lat"].append(dt)
                results[name]["codes"][code] += 1

    with ThreadPoolExecutor(max_workers=users) as ex:
        list(ex.map(_worker, range(users)))
    shared.close()
    wall = time.perf_counter() - t_level0
    return results, wall


def _aggregate(level_results, users, wall):
    """Convierte resultados por endpoint en métricas por nivel."""
    agg = {"users": users}
    total_lat = []
    for name, r in level_results.items():
        lat = r["lat"]
        total_lat.extend(lat)
        n = len(lat)
        agg[name] = {
            "requests": n,
            "ok": r["codes"].get(200, 0),
            "codes": dict(r["codes"]),
            "p50_ms": round(_percentile(lat, 50), 2),
            "p95_ms": round(_percentile(lat, 95), 2),
            "p99_ms": round(_percentile(lat, 99), 2),
            "avg_ms": round(statistics.mean(lat), 2) if lat else 0.0,
        }
    agg["_total_requests"] = len(total_lat)
    agg["_total_ok"] = sum(r["codes"].get(200, 0) for r in level_results.values())
    agg["_p50_ms"] = round(_percentile(total_lat, 50), 2)
    agg["_p95_ms"] = round(_percentile(total_lat, 95), 2)
    agg["_p99_ms"] = round(_percentile(total_lat, 99), 2)
    agg["_wall_seg"] = round(wall, 3)
    agg["_throughput_req_s"] = round(len(total_lat) / wall, 2) if wall else 0.0
    return agg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=0,
                    help="Un solo nivel con N usuarios (0 = run 50/100/200).")
    ap.add_argument("--reqs", type=int, default=3, help="peticiones/usuario/endpoint")
    ap.add_argument("--endpoints", default="stats,invoices,dashboard",
                    help="Endpoints a probar, separados por coma.")
    ap.add_argument("--invoices", type=int, default=600,
                    help="Facturas sembradas en la DB de carga.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--report", default=None,
                    help="Ruta del reporte markdown a generar.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ep_names = [e.strip() for e in args.endpoints.split(",") if e.strip()]
    levels = ([args.users] if args.users else [50, 100, 200])

    work = tempfile.mkdtemp(prefix="b2b_load_")
    db_path = os.path.join(work, "load.db")
    port = args.port or _find_free_port()

    _seed(db_path, args.invoices)
    proc = _start_server(db_path, KEY, args.host, port)
    try:
        _wait_health(args.host, port)
        all_levels = []
        for users in levels:
            res, wall = _run_level(args.host, port, KEY, users, ep_names, args.reqs)
            all_levels.append(_aggregate(res, users, wall))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    shutil.rmtree(work, ignore_errors=True)

    if args.report:
        _write_report(args.report, all_levels, ep_names, args)

    if args.json:
        print(json.dumps({"levels": all_levels, "endpoints": ep_names}, indent=2))
    else:
        _print_table(all_levels, ep_names)
    return 0


def _print_table(all_levels, ep_names):
    print(f"\n=== Load test: endpoints={','.join(ep_names)} ===")
    for lvl in all_levels:
        u = lvl["users"]
        print(f"\n-- {u} usuarios concurrentes -- "
              f"(total {lvl['_total_requests']} req, "
              f"ok {lvl['_total_ok']}/{lvl['_total_requests']})")
        print(f"  Latencia global: p50={lvl['_p50_ms']}ms  "
              f"p95={lvl['_p95_ms']}ms  p99={lvl['_p99_ms']}ms")
        print(f"  Throughput     : {lvl['_throughput_req_s']} req/s")
        for name in ep_names:
            m = lvl[name]
            print(f"  {name:<20} ok={m['ok']}/{m['requests']}  "
                  f"p50={m['p50_ms']}ms p95={m['p95_ms']}ms "
                  f"p99={m['p99_ms']}ms  codes={m['codes']}")


def _write_report(path, all_levels, ep_names, args):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# Load Test — Enterprise MVP\n",
        f"_Generado el {time.strftime('%Y-%m-%d %H:%M:%S')}_\n",
        f"- Endpoints: `{','.join(ep_names)}`",
        f"- Facturas sembradas: {args.invoices}",
        f"- Peticiones/usuario/endpoint: {args.reqs}",
        f"- Rate limiter: off (mide rendimiento real de la API)",
        "",
        "## Resultados\n",
        "| Usuarios | Peticiones | OK | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (req/s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for lvl in all_levels:
        lines.append(
            f"| {lvl['users']} | {lvl['_total_requests']} | "
            f"{lvl['_total_ok']}/{lvl['_total_requests']} | "
            f"{lvl['_p50_ms']} | {lvl['_p95_ms']} | {lvl['_p99_ms']} | "
            f"{lvl['_throughput_req_s']} |")
    lines.append("\n## Por endpoint\n")
    for lvl in all_levels:
        lines.append(f"### {lvl['users']} usuarios\n")
        lines.append("| Endpoint | OK | p50 | p95 | p99 | avg | códigos |")
        lines.append("|---|---|---|---|---|---|---|")
        for name in ep_names:
            m = lvl[name]
            lines.append(
                f"| {name} | {m['ok']}/{m['requests']} | {m['p50_ms']}ms | "
                f"{m['p95_ms']}ms | {m['p99_ms']}ms | {m['avg_ms']}ms | "
                f"{m['codes']} |")
        lines.append("")
    lines.append("\n## Interpretación\n")
    lines.append(
        "- **OK bajo 100%** o **códigos ≠ 200/0**: revisar logs, la autenticación "
        "concurrente o locks de SQLite.")
    lines.append(
        "- **p99 >> p95**: cola de contención (SQLite WAL o threadpool).")
    lines.append(
        "- **Throughput plano al subir usuarios**: el bottleneck es el servidor "
        "o la DB, no el cliente.")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Reporte escrito: {path}")


if __name__ == "__main__":
    sys.exit(main())
