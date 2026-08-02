# -*- coding: utf-8 -*-
"""
templates.py — Calendario de obligaciones SAT para el módulo compliance_tracker.

Plantilla por defecto de las obligaciones fiscales de un despacho mexicano,
con vencimientos basados en el calendario SAT:

    a. DIOT                   : día 17 de cada mes.
    b. ISR mensual            : día 17 de cada mes.
    c. IVA mensual            : día 17 de cada mes.
    d. Contabilidad electrónica: día 20 de cada mes.
    e. Nómina bimestral       : día 17 de cada bimestre PAR (ene-feb → feb,
                                mar-abr → abr, ...).
    f. Declaración anual      : día 30 de abril.

`generate_annual_template()` devuelve la lista de obligaciones de un año
(con su due_date ya resuelta) lista para instanciarse por tenant.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date
from typing import Dict, List

from b2b_ai.features.compliance_tracker.models import Obligation, ObligationType

# Días de vencimiento por tipo (reglas SAT).
_DUE_DAY: Dict[str, int] = {
    "DIOT": 17,
    "ISR_MENSUAL": 17,
    "IVA_MENSUAL": 17,
    "CONTAB_ELECTRONICA": 20,
    "NOMINA_BIMESTRAL": 17,
    "ANUAL": 30,  # mes fijo abril
}
_ANNUAL_MONTH = 4  # abril


def _obligation(
    tenant_id: str,
    obligation_type: ObligationType,
    year: int,
    month: int,
    day: int,
    notes: str = "",
) -> Obligation:
    """Crea una obligación con due_date resuelta para (year, month, day)."""
    return Obligation(
        tenant_id=tenant_id,
        obligation_type=obligation_type,
        due_date=date(year, month, day),
        notes=notes,
    )


def monthly_obligations(tenant_id: str, year: int, month: int) -> List[Obligation]:
    """Obligaciones del SAT con vencimiento en el mes (year, month)."""
    return [
        _obligation(tenant_id, ObligationType.DIOT, year, month, 17,
                    "Declaración Informativa de Operaciones con Terceros."),
        _obligation(tenant_id, ObligationType.ISR_MENSUAL, year, month, 17,
                    "Declaración mensual de ISR."),
        _obligation(tenant_id, ObligationType.IVA_MENSUAL, year, month, 17,
                    "Declaración mensual de IVA."),
        _obligation(tenant_id, ObligationType.CONTAB_ELECTRONICA, year, month, 20,
                    "Envío de contabilidad electrónica del mes."),
    ]


def is_even_bimester(month: int) -> bool:
    """True si el mes cierra un bimestre PAR (feb, abr, jun, ago, oct, dic)."""
    return month in (2, 4, 6, 8, 10, 12)


def nomina_bimestral_obligations(tenant_id: str, year: int) -> List[Obligation]:
    """Nómina bimestral: vence día 17 del mes que cierra cada bimestre par."""
    out: List[Obligation] = []
    for month in (2, 4, 6, 8, 10, 12):
        out.append(_obligation(
            tenant_id, ObligationType.NOMINA_BIMESTRAL, year, month, 17,
            f"Declaración de nómina bimestral (bimestre par mes {month})."))
    return out


def annual_obligations(tenant_id: str, year: int) -> Obligation:
    """Declaración anual ISR: vence día 30 de abril."""
    return _obligation(
        tenant_id, ObligationType.ANUAL, year, _ANNUAL_MONTH, 30,
        "Declaración anual de ISR.")


def generate_annual_template(tenant_id: str, year: int) -> List[Obligation]:
    """Calendario anual completo de obligaciones SAT para un tenant.

    Incluye:
      - DIOT, ISR mensual, IVA mensual y contabilidad electrónica de cada mes.
      - Nómina bimestral (día 17 de cada bimestre par).
      - Declaración anual (30 de abril).
    """
    obligations: List[Obligation] = []
    for month in range(1, 13):
        obligations.extend(monthly_obligations(tenant_id, year, month))
    obligations.extend(nomina_bimestral_obligations(tenant_id, year))
    obligations.append(annual_obligations(tenant_id, year))
    return obligations


# Re-export para comodidad de tests / callers.
def _obligation_id() -> str:
    return str(_uuid.uuid4())
