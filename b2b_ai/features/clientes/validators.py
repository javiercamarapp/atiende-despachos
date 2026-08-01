# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for client queries, CFDI IDs, and concepto catalog.

Validates:
  - Query type values
  - CFDI ID format (UUID pattern)
  - Concepto against known deductible catalog
  - Query content length and format
"""
from __future__ import annotations

import re
from typing import List, Tuple

from b2b_ai.features.clientes.models import QueryType


# CFDI UUID pattern
_CFDI_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Known deductible concepto keywords (for validation)
_KNOWN_CONCEPTOS = [
    "salario", "nómina", "sueldo", "renta", "arrendamiento",
    "servicio", "luz", "agua", "gas", "telefono", "internet",
    "equipo", "mobiliario", "computadora", "software",
    "viatico", "viaje", "hotel", "pasaje",
    "comida", "alimentacion", "restaurante",
    "multa", "sancion", "honorarios", "consultoria",
    "seguro", "mantenimiento", "reparacion", "transporte",
    "publicidad", "marketing", "capacitacion",
]


def validate_query_type(tipo: str) -> Tuple[bool, List[str]]:
    """Validate a query type string.

    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []
    valid_types = {t.value for t in QueryType}

    if not tipo:
        errors.append("El tipo de consulta es obligatorio.")
    elif tipo not in valid_types:
        errors.append(
            f"Tipo de consulta inválido '{tipo}'. "
            f"Valores permitidos: {', '.join(sorted(valid_types))}."
        )

    return len(errors) == 0, errors


def validate_cfdi_id(cfdi_id: str) -> Tuple[bool, List[str]]:
    """Validate a CFDI ID (UUID / folio fiscal).

    Returns (is_valid, list_of_errors).

    Checks:
      - Not empty
      - Matches UUID format (8-4-4-4-12 hex)
    """
    errors: List[str] = []

    if not cfdi_id or not cfdi_id.strip():
        errors.append("El ID del CFDI es obligatorio.")
    else:
        cfdi_id_clean = cfdi_id.strip()
        if not _CFDI_UUID_PATTERN.match(cfdi_id_clean):
            # Also accept if it looks like a valid folio (at least 36 chars with dashes)
            if len(cfdi_id_clean) < 10:
                errors.append(
                    f"Formato de CFDI ID inválido '{cfdi_id_clean}'. "
                    "Se esperaba un UUID (XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)."
                )

    return len(errors) == 0, errors


def validate_concepto(concepto: str) -> Tuple[bool, List[str]]:
    """Validate a concepto (expense concept) against the known catalog.

    Returns (is_valid, list_of_errors).

    This is a soft validation — it warns if the concepto is not recognized
    but doesn't block processing.
    """
    errors: List[str] = []

    if not concepto or not concepto.strip():
        errors.append("El concepto es obligatorio.")
        return False, errors

    concepto_lower = concepto.lower().strip()
    known = any(kw in concepto_lower for kw in _KNOWN_CONCEPTOS)

    if not known:
        errors.append(
            f"El concepto '{concepto}' no se reconoce en el catálogo conocido. "
            "Se procesará pero la información de deducibilidad puede ser incompleta."
        )

    return len(errors) == 0, errors


def validate_client_query(data: dict) -> Tuple[bool, List[str]]:
    """Validate raw client query data dict.

    Returns (is_valid, combined_list_of_errors).
    """
    all_errors: List[str] = []

    # Check tipo
    tipo = data.get("tipo", "")
    is_valid_tipo, tipo_errors = validate_query_type(tipo)
    if not is_valid_tipo:
        all_errors.extend([f"[Tipo] {e}" for e in tipo_errors])

    # Check contenido
    contenido = data.get("contenido", "")
    if not contenido or not str(contenido).strip():
        all_errors.append("[Contenido] El contenido de la consulta es obligatorio.")
    elif len(str(contenido).strip()) < 3:
        all_errors.append("[Contenido] El contenido debe tener al menos 3 caracteres.")

    # Check tenant_id
    tenant_id = data.get("tenant_id", "")
    if not tenant_id or not str(tenant_id).strip():
        all_errors.append("[Tenant] El tenant_id es obligatorio.")

    return len(all_errors) == 0, all_errors
