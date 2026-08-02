# -*- coding: utf-8 -*-
"""
validators.py — Validaciones del módulo DIOT.

Valida:
  - Formato RFC del SAT (personas morales 12 chars, físicas 13 chars)
  - Cantidades positivas (base gravable, IVA)
  - Tasa de IVA válida (0%, 16%; +8% frontera opcional)
  - Operaciones con terceros (régimen, RFC no vacío)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import DIOTRecord, TipoOperacion, TipoIVA

# Persona moral: 3 letras + 6 dígitos (fecha) + 3 homoclave
RFC_PM_PATTERN = re.compile(r"^[A-ZÑ&]{3}\d{6}[A-Z\d]{3}$")
# Persona física: 4 letras + 6 dígitos + 3 homoclave
RFC_PF_PATTERN = re.compile(r"^[A-ZÑ&]{4}\d{6}[A-Z\d]{3}$")

VALID_IVA_RATES = {0.0, 0.08, 0.16}
TASA_TO_TIPOIVA = {0.0: TipoIVA.IVA_00, 0.08: TipoIVA.IVA_08, 0.16: TipoIVA.IVA_16}
TIPOIVA_TO_TASA = {TipoIVA.IVA_00: 0.0, TipoIVA.IVA_08: 0.08, TipoIVA.IVA_16: 0.16}
VALID_TIPOS = {t.value for t in TipoOperacion}
REGIMENES_VALIDOS = {
    "601", "603", "606", "607", "608", "609", "610", "611", "612",
    "614", "615", "616", "621", "622", "623", "624", "625", "626",
    "628", "629", "630", "631", "632", "633", "634", "635", "636",
}


@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def validate_rfc(rfc: str) -> Optional[str]:
    """Valida el formato de un RFC mexicano (None si válido)."""
    if not rfc or not rfc.strip():
        return "RFC no puede estar vacío."
    rfc = rfc.strip().upper()
    if len(rfc) == 12:
        if RFC_PM_PATTERN.match(rfc):
            return None
        return f"RFC de persona moral inválido: '{rfc}'."
    if len(rfc) == 13:
        if RFC_PF_PATTERN.match(rfc):
            return None
        return f"RFC de persona física inválido: '{rfc}'."
    return f"RFC con longitud inválida ({len(rfc)}). Se esperaban 12-13 caracteres."


def is_valid_rfc(rfc: str) -> bool:
    return validate_rfc(rfc) is None


def validate_positive_amount(value: float, field_name: str = "monto") -> Optional[str]:
    if value is None:
        return f"{field_name} es obligatorio."
    if value < 0:
        return f"{field_name} no puede ser negativo ({value})."
    return None


def validate_iva_rate(rate: float) -> Optional[str]:
    if rate not in VALID_IVA_RATES:
        return f"Tasa de IVA inválida: {rate}. Tasas aceptadas: 0%, 8%, 16%."
    return None


def validate_record(record: DIOTRecord) -> ValidationResult:
    result = ValidationResult()
    rfc_err = validate_rfc(record.rfc_tercero)
    if rfc_err:
        result.valid = False
        result.errors.append(f"RFC tercero: {rfc_err}")
    if not record.nombre.strip():
        result.valid = False
        result.errors.append("nombre del tercero es obligatorio.")
    if record.regimen_fiscal is not None and record.regimen_fiscal not in REGIMENES_VALIDOS:
        result.warnings.append(f"régimen fiscal '{record.regimen_fiscal}' no es clave SAT estándar.")
    for field_name, value in (
        ("base_gravable", record.base_gravable),
        ("iva_trasladado", record.iva_trasladado),
        ("iva_acreditable", record.iva_acreditable),
    ):
        err = validate_positive_amount(value, field_name)
        if err:
            result.valid = False
            result.errors.append(err)
    tasa = TIPOIVA_TO_TASA[record.tasa_iva]
    if record.base_gravable > 0 and record.tasa_iva != TipoIVA.IVA_00:
        expected = round(record.base_gravable * tasa, 2)
        if abs(record.iva_trasladado - expected) > 0.01:
            result.warnings.append(
                f"IVA trasladado ({record.iva_trasladado}) difiere del esperado "
                f"({expected}) para base {record.base_gravable} @ tasa {tasa:.0%}."
            )
    if record.iva_acreditable > record.iva_trasladado + 0.01:
        result.warnings.append("IVA acreditable supera al IVA trasladado.")
    return result


def validate_records(records: List[Any]) -> ValidationResult:
    result = ValidationResult()
    if not records:
        result.valid = False
        result.errors.append("No hay registros que validar.")
        return result
    seen: set = set()
    for i, raw in enumerate(records, 1):
        prefix = f"Registro #{i}"
        rec = coerce_record(raw)
        r = validate_record(rec)
        if not r.valid:
            result.valid = False
            for e in r.errors:
                result.errors.append(f"{prefix}: {e}")
        for w in r.warnings:
            result.warnings.append(f"{prefix}: {w}")
        key = (rec.rfc_tercero, rec.tipo_operacion.value, rec.base_gravable)
        if key in seen:
            result.warnings.append(f"{prefix}: operación duplicada detectada.")
        seen.add(key)
    return result


def coerce_record(raw: Any) -> DIOTRecord:
    if isinstance(raw, DIOTRecord):
        return raw
    if isinstance(raw, dict):
        return DIOTRecord(**raw)
    return DIOTRecord(**raw.model_dump())
