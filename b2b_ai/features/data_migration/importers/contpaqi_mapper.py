# -*- coding: utf-8 -*-
"""contpaqi_mapper.py — Mapeo del formato de exportación de CONTPAQi a Likida.

CONTPAQi (CONTPAQ i Contabilidad / Comercial) no expone API pública, así que
la vía práctica es importar sus exportaciones. Esta clase conoce las formas
típicas de los reportes CSV/XLS de CONTPAQi y las convierte al esquema
canónico de Likida AI (el mismo que producen excel_importer/csv_importer).

Mapea las columnas que CONTPAQi suele emitir (en español) a los campos
canónicos, tolerando encabezados variantes. La detección del tipo se hace por
el nombre de hoja/archivo y por inspección de columnas.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional

from b2b_ai.features.data_migration.importers.base import detect_sheet_type
from b2b_ai.features.data_migration.models import MigrationDataType, MigrationItem


def _norm_key(k: str) -> str:
    """Normaliza un nombre de columna: minúsculas, sin acentos, compacto.

    Los encabezados de CONTPAQi vienen en español y pueden llevar acentos o no
    según la exportación (\"Razón Social\" vs \"RAZON SOCIAL\", \"Régimen\" vs
    \"Regimen\"). Para mapear ambos de forma robusta se eliminan los diacríticos
    antes de comparar contra las columnas candidatas.
    """
    if not k:
        return ""
    text = unicodedata.normalize("NFD", str(k))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.strip().lower().replace("_", " ").replace("-", " ")

# Columna canónica -> posibles columnas CONTPAQi (nombres de export reales).
_CONTPAQI_COLUMNS = {
    MigrationDataType.CLIENTE: {
        "rfc": ["rfc", "clave_rfc", "rfcl", "rfc cliente"],
        "razon_social": ["razon social", "nombre", "nombre del cliente",
                         "razonsocial", "cliente", "denominacion"],
        "regimen_fiscal": ["regimen fiscal", "regimen", "regimenfiscal",
                           "tipo_regimen", "régimen fiscal"],
    },
    MigrationDataType.CFDI: {
        "uuid": ["uuid", "folio fiscal", "foliofiscal", "folio_fiscal",
                 "no de complemento", "uuid cfdi"],
        "emisor_rfc": ["emisor rfc", "rfcemisor", "rfc emisor", "emisor"],
        "receptor_rfc": ["receptor rfc", "rfcreceptor", "rfc receptor", "receptor"],
        "total": ["total", "importe total", "monto total", "total con impuestos"],
        "fecha": ["fecha", "fecha de emision", "fecha de timbrado", "fechaemision"],
        "conceptos": ["concepto", "descripcion", "conceptos", "descripcion del concepto"],
    },
    MigrationDataType.CUENTA_BANCARIA: {
        "numero": ["numero de cuenta", "no de cuenta", "numero", "cuenta",
                   "número de cuenta"],
        "banco": ["banco", "institucion", "banco emisor", "institucion bancaria"],
        "saldo": ["saldo", "saldo actual", "saldo inicial", "saldo disponible"],
    },
    MigrationDataType.EMPLEADO: {
        "rfc": ["rfc", "rfcempleado", "rfc empleado"],
        "nombre": ["nombre", "nombre completo", "nombre del empleado", "empleado"],
        "salario": ["salario", "sueldo", "salario mensual", "sueldo bruto", "sueldo neto"],
        "puesto": ["puesto", "cargo", "puesto del empleado", "posicion"],
    },
}


class ContpaqiMapper:
    """Convierte exportaciones de CONTPAQi al esquema de Likida AI."""

    # ------------------------------------------------------------------
    def map_sheet(self, sheet_name: str, rows: List[Dict[str, Any]]) -> List[MigrationItem]:
        """Mapea una hoja (lista de dicts) de una exportación CONTPAQi."""
        data_type = self.infer_sheet_type(sheet_name, rows)
        if data_type is None:
            return []
        items: List[MigrationItem] = []
        for idx, row in enumerate(rows, start=2):
            data = self.map_row(row, data_type)
            if not data:
                continue
            items.append(MigrationItem(
                data_type=data_type,
                source=sheet_name,
                row=idx,
                data=data,
            ))
        return items

    # ------------------------------------------------------------------
    def map_row(self, row: Dict[str, Any], data_type: MigrationDataType) -> Dict[str, Any]:
        """Convierte una fila CONTPAQi al dict canónico."""
        col_map = _CONTPAQI_COLUMNS.get(data_type, {})
        norm_row = {_norm_key(k): v for k, v in (row or {}).items()}
        out: Dict[str, Any] = {}
        for canonical, candidates in col_map.items():
            for cand in candidates:
                hit = norm_row.get(_norm_key(cand))
                if hit is not None and str(hit).strip() != "":
                    out[canonical] = hit
                    break
        return out

    # ------------------------------------------------------------------
    def infer_sheet_type(self, sheet_name: str,
                         rows: List[Dict[str, Any]]) -> Optional[MigrationDataType]:
        """Infiera el tipo por nombre de hoja y, en segundo plano, por columnas."""
        by_name = detect_sheet_type(sheet_name)
        if by_name is not None:
            return by_name
        if rows:
            first = rows[0]
            norm = {_norm_key(k) for k in first.keys()}
            if "rfc" in norm and any("razon" in c or "nombre" in c for c in norm):
                return MigrationDataType.CLIENTE
            if "uuid" in norm or "folio" in norm:
                return MigrationDataType.CFDI
            if "saldo" in norm and ("banco" in norm or "cuenta" in norm):
                return MigrationDataType.CUENTA_BANCARIA
            if "salario" in norm or "sueldo" in norm:
                return MigrationDataType.EMPLEADO
        return None
