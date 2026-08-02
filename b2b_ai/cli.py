#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli.py — Interfaz de línea de comandos `bb-ai`.

Comandos:
    bb-ai process <file.xml>          Procesa un CFDI por el pipeline.
    bb-ai batch <folder/>             Procesa todos los CFDI de una carpeta.
    bb-ai report --period YYYY-MM     Genera un reporte mensual.
    bb-ai status                      Estado del sistema (DB, audit, tools).
"""
from __future__ import annotations

import argparse
import os
import sys

from b2b_ai import __version__
import b2b_ai.tools.tools  # noqa: F401  (registra las tools)
from b2b_ai.db.db import Database, DEFAULT_DB
from b2b_ai.services.pipeline import process_file, process_batch, summarize
from b2b_ai.services.report import generate_report
from b2b_ai.services.classify import CATEGORIA_NOMBRE
from b2b_ai.tools.registry import all_tools
from b2b_ai.tools.router import list_routes
from b2b_ai.tools.logger import logger


def _print_resumen(res):
    d = res["datos"]
    v = res["validacion"]
    c = res["clasificacion"]
    print(f"  archivo        : {res['archivo']}")
    print(f"  RFC emisor     : {d['emisor_rfc']} ({d['emisor_nombre'][:40]})")
    print(f"  Fecha          : {d['fecha']}")
    print(f"  Subtotal/IVA   : {d['subtotal']} / {d['iva']}")
    print(f"  Total          : {d['total']}")
    print(f"  Folio fiscal   : {d['folio_fiscal']}")
    print(f"  VALIDACIÓN     : {'OK' if v['ok'] else 'CON OBSERVACIONES'} "
          f"(pass={v['checks']['pass']} fail={v['checks']['fail']})")
    for i in v["issues"]:
        print(f"      [fail] {i['mensaje']}")
    for w in v["warnings"]:
        print(f"      [warn] {w}")
    print(f"  CLASIFICACIÓN  : {CATEGORIA_NOMBRE.get(c['categoria'], c['categoria'])} "
          f"(confianza {c['confianza']}) — {c['razon']}")
    print(f"  ERP            : {res['erp'].get('poliza')} "
          f"({res['erp'].get('status')})")
    print(f"  Notificación   : {res['notificacion'].get('status')}")
    print(f"  Revisión humana: {'SÍ' if v['requires_human_review'] else 'no'}")


def cmd_process(args, db):
    print(f"\n=== bb-ai process: {args.file} ===")
    res = process_file(args.file, db=db, tenant_id=args.tenant_id)
    _print_resumen(res)
    print("\nProcesado. ✔")


def cmd_batch(args, db):
    print(f"\n=== bb-ai batch: {args.folder} ===")
    results = process_batch(args.folder, db=db, tenant_id=args.tenant_id)
    for r in results:
        print(f"\n--- {r['archivo']} ---")
        _print_resumen(r)
    s = summarize(results)
    print("\n" + "=" * 60)
    print("RESUMEN BATCH")
    print("=" * 60)
    print(f"  Procesadas        : {s['procesadas']}")
    print(f"  Válidas           : {s['validas']}")
    print(f"  Con observaciones : {s['con_observaciones']}")
    print(f"  Insertadas        : {s['insertadas']}")
    print(f"  Categorías        : {s['por_categoria']}")
    print(f"\n  Total en DB: {db.count_invoices(tenant_id=args.tenant_id)}")
    print("\nBatch completado. ✔")


def cmd_report(args, db):
    print(f"\n=== bb-ai report (periodo: {args.period or 'todos'}) ===")
    invoices = db.list_invoices(tenant_id=args.tenant_id)
    report = generate_report(invoices, period=args.period,
                             tenant_id=args.tenant_id)
    print(f"  Facturas : {report['facturas']} (válidas {report['validas']}, "
          f"inválidas {report['invalidas']})")
    print(f"  Subtotal : ${report['subtotal']}")
    print(f"  IVA      : ${report['iva']}")
    print(f"  Total    : ${report['total']}")
    print("  Por categoría:")
    for cat, v in report["por_categoria"].items():
        print(f"    - {CATEGORIA_NOMBRE.get(cat, cat)}: {v['count']} "
              f"(${v['total']})")
    print("\nReporte listo (informativo; presentación fiscal requiere humano).")


def cmd_status(args, db):
    print("\n=== bb-ai status ===")
    print(f"  Versión        : {__version__}")
    print(f"  Base           : {db.path}")
    print(f"  Esquema versión: {db.schema_version()}")
    print(f"  Tenants        : {len(db.list_tenants())}")
    print(f"  Facturas       : {db.count_invoices()}")
    print(f"  Audit calls    : {db.count_audit()}")
    print(f"  Notificaciones : {len(db.list_notifications())}")
    print(f"  Tools          : {[t.name for t in all_tools()]}")
    print("  Rutas:")
    for r in list_routes():
        print(f"    - {r['tool']:<20} ← {', '.join(r['patterns'])}")


def cmd_demo(args, db):
    """Ejecuta el modo demo interactivo."""
    db.close()  # demo usa su propia DB en memoria
    from b2b_ai.services.demo import main as demo_main
    return demo_main(args)


def build_parser():
    p = argparse.ArgumentParser(prog="bb-ai",
                                description="Agente contable IA (Likida AI Enterprise).")
    p.add_argument("--version", action="version", version=f"bb-ai {__version__}")
    p.add_argument("--db", default=None, help="Ruta de la base SQLite.")
    p.add_argument("--tenant-id", type=int, default=None, dest="tenant_id",
                   help="Tenant a usar (default: primer tenant).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("process", help="Procesa un CFDI XML.")
    sp.add_argument("file", help="Ruta al CFDI .xml")
    sp.set_defaults(func=cmd_process)

    sp = sub.add_parser("batch", help="Procesa todos los CFDI de una carpeta.")
    sp.add_argument("folder", help="Carpeta con CFDI .xml")
    sp.set_defaults(func=cmd_batch)

    sp = sub.add_parser("report", help="Genera un reporte.")
    sp.add_argument("--period", default=None, help="Periodo YYYY-MM")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("status", help="Estado del sistema.")
    sp.set_defaults(func=cmd_status)

    # Demo (modo interactivo para presentaciones a clientes)
    sp = sub.add_parser("demo", help="Modo demo interactivo para presentaciones a clientes.")
    sp.add_argument("--live", action="store_true",
                    help="Usa DeepSeek real (OpenRouter) en vez de MockLLM")
    sp.add_argument("--data", default=None,
                    help="Carpeta con CFDI .xml de ejemplo (default: demo-data/)")
    sp.add_argument("--output", default=None,
                    help="Carpeta de salida para el reporte HTML (default: demo-output/)")
    sp.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    db = Database(args.db or DEFAULT_DB)
    logger.set_db(db)
    try:
        args.func(args, db)
    except (OSError, ValueError) as e:
        # Errores esperados (p.ej. archivo inexistente, XML no CFDI) salen
        # como mensaje limpio, sin traceback, y con código de salida != 0.
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
