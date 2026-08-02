# -*- coding: utf-8 -*-
"""data_validator.py — Validación de integridad de datos de migración.

Valida los ítems extraídos de un archivo de origen contra el esquema de
Likida AI. Reglas por tipo de datos:

  Cliente          — RFC válido, razón social no vacía.
  CFDI             — UUID presente, total > 0, emisor y receptor con RFC.
  Cuenta bancaria  — número de cuenta presente, saldo numérico.
  Empleado         — RFC válido (o presente), nombre no vacío, salario numérico.

Devuelve una lista de errores agregados (uno por ítem) y la cuenta de
válidos/inválidos. No muta el job; el servicio aplica los resultados.
"""
from __future__ import annotations

from typing import Any, Dict, List

from b2b_ai.features.data_migration.models import MigrationDataType, MigrationItem
from b2b_ai.features.data_migration.validators.rfc_validator import (
    describe_rfc_error,
    is_valid_mx_rfc,
)


def _num(value: Any) -> bool:
    """True si el valor es un número finito (float/int) o string numérico."""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    return len(s) > 0


def validate_item(item: MigrationItem) -> MigrationItem:
    """Valida un ítem y rellena .valid y .errors según su tipo."""
    errors: List[str] = []
    data: Dict[str, Any] = item.data or {}

    if item.data_type == MigrationDataType.CLIENTE:
        rfc = data.get("rfc", "")
        if not _is_nonempty(rfc):
            errors.append("Falta el RFC del cliente")
        elif not is_valid_mx_rfc(rfc):
            errors.append(describe_rfc_error(rfc))
        if not _is_nonempty(data.get("razon_social")):
            errors.append("Falta la razón social del cliente")

    elif item.data_type == MigrationDataType.CFDI:
        uuid = data.get("uuid", "")
        if not _is_nonempty(uuid):
            errors.append("Falta el UUID del CFDI")
        if not _num(data.get("total")):
            errors.append("El total del CFDI debe ser numérico")
        for campo, label in (("emisor_rfc", "emisor"), ("receptor_rfc", "receptor")):
            rfc = data.get(campo, "")
            if not _is_nonempty(rfc):
                errors.append(f"Falta el RFC del {label}")
            elif not is_valid_mx_rfc(rfc):
                errors.append(f"RFC del {label} inválido: {describe_rfc_error(rfc)}")

    elif item.data_type == MigrationDataType.CUENTA_BANCARIA:
        numero = data.get("numero", "")
        if not _is_nonempty(numero):
            errors.append("Falta el número de cuenta bancaria")
        if not _num(data.get("saldo")):
            errors.append("El saldo de la cuenta debe ser numérico")

    elif item.data_type == MigrationDataType.EMPLEADO:
        rfc = data.get("rfc", "")
        if _is_nonempty(rfc) and not is_valid_mx_rfc(rfc):
            errors.append(f"RFC del empleado inválido: {describe_rfc_error(rfc)}")
        if not _is_nonempty(data.get("nombre")):
            errors.append("Falta el nombre del empleado")
        if not _num(data.get("salario")):
            errors.append("El salario del empleado debe ser numérico")

    item.errors = errors
    item.valid = not errors
    return item


def validate_items(items: List[MigrationItem]) -> Dict[str, Any]:
    """Valida una lista de ítems.

    Devuelve un resumen con conteos y la lista de ítems (mutados con .valid /
    .errors).
    """
    for it in items:
        validate_item(it)
    valid = [it for it in items if it.valid]
    invalid = [it for it in items if not it.valid]
    return {
        "items": items,
        "valid_items": valid,
        "invalid_items": invalid,
        "total": len(items),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "errors": [
            {"item_id": it.id, "row": it.row, "source": it.source,
             "data_type": it.data_type.value, "errors": it.errors}
            for it in invalid
        ],
    }
