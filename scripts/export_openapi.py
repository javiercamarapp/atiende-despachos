#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_openapi.py — Exporta el contrato OpenAPI de la app FastAPI de Likida AI.

Genera `openapi.json` y `openapi.yaml` desde la app real (`b2b_ai.api.app:app`),
nunca a mano. Se usa para regenerar docs/openapi.json tras cambiar rutas.

Uso:
    B2B_API_KEY=<key> B2B_JWT_SECRET=<secret> B2B_ENCRYPTION_KEY=<key> \
        python scripts/export_openapi.py [--out DIR]

Requiere las mismas variables de entorno que arrancar la API:
    B2B_API_KEY         key de servicio (cualquier valor en dev)
    B2B_JWT_SECRET      secret de firma JWT (openssl rand -hex 32)
    B2B_ENCRYPTION_KEY  clave AES-GCM (openssl rand -hex 24)
    B2B_ENV             "development" en local para saltarse los fail-fast
Salida (por defecto en `docs/`):
    openapi.json
    openapi.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Asegura que la raíz del repo esté en sys.path aunque el paquete b2b_ai no
# esté instalado (ejecución directa del script sin `pip install -e .`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _resolve_out_dir(arg: str) -> Path:
    """Resuelve el directorio de salida relativo a la raíz del repo."""
    if arg:
        return Path(arg).resolve()
    # Root del repo = 3 niveles arriba de este script: scripts/ -> repo.
    return Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="", help="Directorio de salida (default: docs/)")
    parser.add_argument(
        "--yaml", action="store_true", default=True,
        help="Además de JSON, escribir openapi.yaml")
    args = parser.parse_args()

    # Importar la app real. Si falta una env requerida, el fail-fast de la
    # app lanza RuntimeError y el script muere con un mensaje claro.
    from b2b_ai.api.app import app

    spec = app.openapi()

    out_dir = _resolve_out_dir(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "openapi.json"
    json_path.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    written = [json_path]
    if args.yaml:
        try:
            import yaml  # type: ignore
        except ImportError:
            print("PyYAML no instalado; omitiendo openapi.yaml.", file=sys.stderr)
        else:
            yaml_path = out_dir / "openapi.yaml"
            yaml_path.write_text(
                yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
                encoding="utf-8")
            written.append(yaml_path)

    paths = len(spec.get("paths", {}))
    for w in written:
        print(f"OK  {w}  ({w.stat().st_size} bytes)")
    print(f"Contracto: {paths} paths · {len(spec.get('components', {}).get('schemas', {}))} schemas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
