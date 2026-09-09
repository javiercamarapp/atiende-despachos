#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/checks/no_delete_origen_migracion.py — REQ-MIG-011
(docs/BLUEPRINT-AGENTES-FISCALES.md §3 — Migración/fusión de catálogo de
cuentas).

Criterio de aceptación exacto:
  "El migrador nunca debe emitir `DELETE` sobre las pólizas/cuentas de
  origen; prueba estática tipo `scripts/checks/no-delete-events.ts`
  (equivalente Python) que falle el build si aparece un `DELETE FROM` en
  `migracion_catalogo/migrador.py` contra las tablas de origen."

Chequeo ESTÁTICO: lee el texto fuente de
`b2b_ai/features/migracion_catalogo/migrador.py` (nunca lo importa ni lo
ejecuta) y falla si encuentra una sentencia `DELETE FROM` contra alguna
tabla de origen de la migración de catálogo, o contra un nombre de tabla
que no se puede determinar en tiempo de lectura (p. ej. un placeholder o
una variable) — ese caso se trata como violación por precaución, porque
no se puede probar estáticamente que NO afecta una tabla de origen.

Tablas de origen (`b2b_ai/db/models.py`):
  - `cuentas_contables`   -- catálogo de cuentas origen.
  - `asientos_contables`  -- líneas de póliza origen.

Por qué nunca debe haber un DELETE contra ellas: el motor de migración
de pólizas (REQ-MIG-009) migra hacia el catálogo/periodo destino;
REQ-MIG-010 exige que sea idempotente marcando `migrada_a_id` en la
póliza origen, nunca borrándola. Un DELETE sobre la póliza o cuenta de
origen destruiría la única fuente verificable para el cuadre de saldos
de REQ-MIG-012/013/014/015 y para una auditoría posterior — es
irreversible sobre datos que pueden sustentar contabilidad electrónica
ya dictaminada ante el SAT (ver ADR-3).

Uso:
    python scripts/checks/no_delete_origen_migracion.py

Código de salida 0 si el archivo está limpio (o si aún no existe: no
hay nada que chequear todavía); 1 si se encontró al menos una violación,
con el detalle impreso en stderr.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVO_MIGRADOR = (
    REPO_ROOT / "b2b_ai" / "features" / "migracion_catalogo" / "migrador.py"
)

# Tablas de origen reales de la migración de catálogo de cuentas (ver
# `b2b_ai/db/models.py::cuentas_contables/asientos_contables`). Ninguna
# de las dos debe recibir jamás un DELETE desde el motor de migración de
# pólizas.
TABLAS_ORIGEN = frozenset({"cuentas_contables", "asientos_contables"})

# Detecta `DELETE FROM <tabla>`, tolerando: mayúsculas/minúsculas,
# saltos de línea/espacios múltiples entre DELETE y FROM, comillas
# dobles/simples/backticks alrededor del nombre, un prefijo de esquema
# ("public.cuentas_contables"), y nombres que en realidad son
# placeholders/f-strings/variables (`%s`, `{tabla}`, `:tabla`, `" + t +
# "`) -- estos últimos se capturan igual para poder marcarlos como no
# resolubles estáticamente (ver `_es_identificador_literal`).
_PATRON_DELETE_FROM = re.compile(
    r"DELETE\s+FROM\s+(?P<tabla>[\"'`]?[\w{}%:.\-]+[\"'`]?)",
    re.IGNORECASE,
)


class DeleteContraOrigenError(Exception):
    """Se encontró un `DELETE FROM` contra una tabla de origen (o contra
    un nombre de tabla no resoluble estáticamente) en migrador.py."""


def _normalizar_nombre_tabla(crudo: str) -> str:
    tabla = crudo.strip().strip("\"'`")
    if "." in tabla:  # esquema.tabla -> tabla
        tabla = tabla.rsplit(".", 1)[-1]
    return tabla.lower()


def _es_identificador_literal(nombre: str) -> bool:
    """True si `nombre` es un identificador SQL literal simple (letras,
    dígitos, guion bajo) y no un placeholder/variable/f-string cuyo
    valor real no se puede conocer leyendo el archivo estáticamente."""
    return bool(re.fullmatch(r"[a-z_][a-z0-9_]*", nombre))


def encontrar_deletes_contra_origen(texto_fuente: str) -> List[str]:
    """Devuelve la lista de fragmentos `DELETE FROM ...` (tal cual
    aparecen en el texto) que violan la regla: contra una tabla en
    `TABLAS_ORIGEN`, o contra un nombre de tabla que no se puede
    resolver estáticamente (se trata como violación por precaución).

    Un `DELETE FROM` contra una tabla literal que NO está en
    `TABLAS_ORIGEN` (p. ej. una cola de trabajo interna del propio
    módulo) no se reporta -- el criterio de aceptación es específico a
    "contra las tablas de origen".
    """
    violaciones: List[str] = []
    for match in _PATRON_DELETE_FROM.finditer(texto_fuente):
        tabla = _normalizar_nombre_tabla(match.group("tabla"))
        if not _es_identificador_literal(tabla) or tabla in TABLAS_ORIGEN:
            violaciones.append(match.group(0).strip())
    return violaciones


def verificar(archivo: Path = ARCHIVO_MIGRADOR) -> List[str]:
    """Lee `archivo` y devuelve sus violaciones (lista vacía si está
    limpio). Si el archivo todavía no existe, devuelve lista vacía: no
    es una violación que un módulo previsto no exista aún."""
    if not archivo.exists():
        return []
    texto = archivo.read_text(encoding="utf-8")
    return encontrar_deletes_contra_origen(texto)


def main() -> int:
    violaciones = verificar()
    ruta_relativa = ARCHIVO_MIGRADOR.relative_to(REPO_ROOT)
    if violaciones:
        print(
            f"REQ-MIG-011: DELETE FROM prohibido en {ruta_relativa} "
            "contra tabla de origen (o tabla no determinable "
            "estáticamente):",
            file=sys.stderr,
        )
        for violacion in violaciones:
            print(f"  - {violacion!r}", file=sys.stderr)
        print(
            "El motor de migración de pólizas nunca debe borrar la "
            "póliza o cuenta de origen (cuentas_contables, "
            "asientos_contables) -- REQ-MIG-009/010 migran marcando "
            "migrada_a_id, nunca borrando. Corrige "
            f"{ruta_relativa}.",
            file=sys.stderr,
        )
        return 1
    print(f"OK (REQ-MIG-011): sin DELETE FROM contra tablas de origen en {ruta_relativa}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
