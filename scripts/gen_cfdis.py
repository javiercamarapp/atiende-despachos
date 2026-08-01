#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_cfdis.py — Genera N CFDI XML únicos (UUID+folio distintos) a partir de una
plantilla del repo. Necesario para pruebas de batch (100/10K) y benchmarks.

Uso:
    python3 scripts/gen_cfdis.py <carpeta_salida> <N> [--base fixtures/cfdis/01_gasto_operativo_papeleria.xml]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import uuid

# Plantilla por defecto: gasto operativo válido (SubTotal 1000, Total 1160).
_DEFAULT_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "cfdis", "01_gasto_operativo_papeleria.xml")


def generate(n: int, out_dir: str, template: str = _DEFAULT_TEMPLATE,
             start_folio: int = 1) -> list:
    """Genera N CFDI únicos y devuelve la lista de rutas creadas."""
    with open(template, "r", encoding="utf-8") as fh:
        base = fh.read()
    os.makedirs(out_dir, exist_ok=True)
    # Sustituye el UUID del TimbreFiscalDigital y el Folio de cada copia.
    uuid_re = re.compile(r'UUID="([0-9a-fA-F\-]{36})"')
    folio_re = re.compile(r'(<cfdi:Comprobante[^>]*\bFolio=")([0-9]+)(")')
    paths = []
    for i in range(n):
        uid = str(uuid.uuid4())
        folio = str(start_folio + i)
        xml = uuid_re.sub(f'UUID="{uid}"', base, count=1)
        xml = folio_re.sub(rf"\g<1>{folio}\g<3>", xml, count=1)
        path = os.path.join(out_dir, f"cfdi_{start_folio + i:06d}.xml")
        with open(path, "w", encoding="utf-8") as out:
            out.write(xml)
        paths.append(path)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera N CFDI XML únicos.")
    ap.add_argument("out_dir", help="Carpeta de salida.")
    ap.add_argument("n", type=int, help="Cantidad de CFDI a generar.")
    ap.add_argument("--base", default=_DEFAULT_TEMPLATE, help="Plantilla XML.")
    ap.add_argument("--start-folio", type=int, default=1)
    args = ap.parse_args()
    paths = generate(args.n, args.out_dir, args.base, args.start_folio)
    print(f"Generados {len(paths)} CFDI en {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
