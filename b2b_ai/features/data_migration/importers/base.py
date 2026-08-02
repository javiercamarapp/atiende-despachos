# -*- coding: utf-8 -*-
"""base.py — Base común para los importers de migración de datos.

Normaliza filas (dicts de columna->valor) a los diccionarios canónicos de
Likida AI para cada tipo de datos. Tanto el importer de Excel como el de CSV
producen filas como ``dict`` y delegan aquí la normalización, de modo que un
mismo archivo CONTPAQi exportado a .xlsx o a .csv termine en el mismo esquema.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from b2b_ai.features.data_migration.models import MigrationDataType

# Alias de columnas aceptadas (normaliza variantes de encabezado comunes).
_CLIENTE_ALIASES = {
    "rfc": ["rfc", "clave_rfc", "rfcl"],
    "razon_social": ["razon social", "razonsocial", "nombre", "nombre del cliente",
                     "cliente", "nombre_comercial", "razón social"],
    "regimen_fiscal": ["regimen fiscal", "regimenfiscal", "regimen", "régimen fiscal",
                       "tipo_regimen"],
}
_CFDI_ALIASES = {
    "uuid": ["uuid", "folio_fiscal", "foliofiscal", "id", "cfdi"],
    "emisor_rfc": ["emisor_rfc", "rfcemisor", "rfc emisor", "emisor"],
    "receptor_rfc": ["receptor_rfc", "rfcreceptor", "rfc receptor", "receptor"],
    "total": ["total", "importe_total", "monto", "importe", "total_factura"],
    "fecha": ["fecha", "fecha_emision", "fechaemision", "fecha timbre"],
    "conceptos": ["conceptos", "descripcion", "concepto", "descripcion_concepto"],
}
_CUENTA_ALIASES = {
    "numero": ["numero", "numero_cuenta", "no_cuenta", "cuenta", "número"],
    "banco": ["banco", "institucion", "banco nombre", "institucion financiera"],
    "saldo": ["saldo", "saldo_actual", "saldo actual", "monto_saldo"],
}
_EMPLEADO_ALIASES = {
    "rfc": ["rfc", "clave_rfc", "rfcempleado", "rfc empleado"],
    "nombre": ["nombre", "nombre_completo", "nombre completo", "empleado", "trabajador"],
    "salario": ["salario", "sueldo", "salario_mensual", "sueldo_bruto", "sueldo mensual"],
    "puesto": ["puesto", "cargo", "posicion", "area"],
}

_ALIASES = {
    MigrationDataType.CLIENTE: _CLIENTE_ALIASES,
    MigrationDataType.CFDI: _CFDI_ALIASES,
    MigrationDataType.CUENTA_BANCARIA: _CUENTA_ALIASES,
    MigrationDataType.EMPLEADO: _EMPLEADO_ALIASES,
}


def _norm_key(k: str) -> str:
    return (k or "").strip().lower().replace("_", " ").replace("-", " ")


def _lookup(row: Dict[str, Any], aliases: Dict[str, List[str]]) -> Optional[Any]:
    """Busca la primera columna presente que coincida con alguno de los alias."""
    norm_map = {_norm_key(ck): cv for ck, cv in (row or {}).items()}
    for canonical, candidates in aliases.items():
        for cand in candidates:
            hit = norm_map.get(_norm_key(cand))
            if hit is not None and str(hit).strip() != "":
                return hit
    return None


def normalize_row(row: Dict[str, Any], data_type: MigrationDataType) -> Dict[str, Any]:
    """Convierte una fila cruda (columna->valor) al dict canónico del tipo."""
    aliases = _ALIASES[data_type]
    out: Dict[str, Any] = {}
    for canonical in aliases:
        val = _lookup(row, {canonical: aliases[canonical]})
        if val is not None:
            out[canonical] = val
    # Preservar cualquier columna extra (para diagnóstico / metadatos).
    for k, v in (row or {}).items():
        if k not in out:
            out.setdefault("raw_" + k, v)
    return out


def detect_sheet_type(sheet_name: str) -> Optional[MigrationDataType]:
    """Infiera el tipo de datos a partir del nombre de la hoja."""
    n = _norm_key(sheet_name)
    if any(tok in n for tok in ("client", "cliente", "cuenta")):
        if "banc" in n or "cuenta" in n:
            return MigrationDataType.CUENTA_BANCARIA
        return MigrationDataType.CLIENTE
    if any(tok in n for tok in ("cfdi", "factura", "comprobante", "xml", "invoice")):
        return MigrationDataType.CFDI
    if any(tok in n for tok in ("emplead", "nomina", "nómina", "trabajador", "personal")):
        return MigrationDataType.EMPLEADO
    return None
