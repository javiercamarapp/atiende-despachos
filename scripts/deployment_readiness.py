# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""deployment_readiness.py — Script de deployment readiness del MVP.

Valida que TODOS los módulos del piloto estén conectados y funcionales antes
de salir a producción:

    * Importa cada feature module y detecta errores de import.
    * Verifica que las rutas de cada módulo se registran correctamente
      (construye el build_*_router y cuenta sus rutas).
    * Verifica que los modelos de cada módulo son construibles (Pydantic;
      este MVP no usa SQLAlchemy — ver b2b_ai/api/health.py).
    * Comprueba la conectividad a la base de datos (SELECT 1).

Salida:
    * stdout — reporte legible (tick por módulo + resumen + errores).
    * JSON   — archivo con los resultados completos (por defecto
      `deployment_readiness_report.json` en el directorio actual).

Uso:
    python scripts/deployment_readiness.py
    python scripts/deployment_readiness.py --json out/readiness.json
    python scripts/deployment_readiness.py --module billing,onboarding
    B2B_DATABASE_URL=postgres://... python scripts/deployment_readiness.py

Código de salida:
    0 = todo OK (o DB no configurada, considerado degradado)
    1 = hay módulos con errores (import / rutas / modelos)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Asegurar que el repo esté en sys.path para `import b2b_ai`.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_db():
    """Instancia la Database (SQLite por defecto o B2B_DATABASE_URL)."""
    from b2b_ai.db.db import Database
    pg_url = os.environ.get("B2B_DATABASE_URL")
    if pg_url:
        return Database(pg_url)
    return Database()


def _render_report(report: dict) -> str:
    """Render legible del reporte para stdout."""
    lines = []
    lines.append("=" * 62)
    lines.append("DEPLOYMENT READINESS — b2b-ai-enterprise")
    lines.append(f"  status   : {report['status'].upper()}")
    lines.append(f"  version  : {report['version']}")
    lines.append(f"  timestamp: {report['timestamp']}")
    lines.append("-" * 62)
    s = report["summary"]
    lines.append(f"  summary  : {s['ok']}/{s['total']} módulos OK · "
                 f"{s['route_count']} rutas · {s['model_count']} modelos")
    db = report.get("database", {})
    lines.append(f"  database : [{db.get('status')}] {db.get('detail')}")
    lines.append("-" * 62)

    for mod in report["modules"]:
        imp = mod["import"]["status"]
        rte = mod["routes"]["status"]
        mdl = mod["models"]["status"]
        flag = "✓" if mod["status"] == "ok" else "✗"
        n_routes = mod["routes"].get("route_count", 0)
        n_models = mod["models"].get("model_count", 0)
        lines.append(
            f"  {flag} {mod['name']:<34} "
            f"import={imp:<5} routes={rte:<5}({n_routes}) models={mdl:<5}({n_models})"
        )

    if report["errors"]:
        lines.append("-" * 62)
        lines.append("  ERRORES:")
        for e in report["errors"]:
            lines.append(f"    ✗ {e['module']:<30} {e['detail']}")
    lines.append("=" * 62)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Deployment readiness checker del MVP.")
    parser.add_argument("--json", metavar="PATH", default=None,
                        help="Ruta del archivo JSON de salida "
                             "(default: deployment_readiness_report.json).")
    parser.add_argument("--no-json", action="store_true",
                        help="No escribir archivo JSON.")
    parser.add_argument("--module", default=None,
                        help="Lista de módulos a chequear (coma), en vez de todos.")
    parser.add_argument("--no-db", action="store_true",
                        help="No inicializar DB (la reporta como not_configured).")
    args = parser.parse_args(argv)

    from b2b_ai.api.health import discover_feature_modules, run_readiness

    module_names = None
    if args.module:
        module_names = [m.strip() for m in args.module.split(",") if m.strip()]

    db = None
    if not args.no_db:
        try:
            db = _build_db()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] No se pudo inicializar DB: {exc}. "
                  f"Se reportará como not_configured.", file=sys.stderr)

    report = run_readiness(db=db, module_names=module_names)

    print(_render_report(report))

    json_path = args.json
    if args.no_json:
        json_path = None
    if json_path is None and not args.no_json:
        json_path = "deployment_readiness_report.json"
    if json_path:
        Path(json_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[reporte JSON] {Path(json_path).resolve()}")

    # Cierre: 1 = hay errores reales de módulo; 0 = ok o degradado (solo DB).
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
