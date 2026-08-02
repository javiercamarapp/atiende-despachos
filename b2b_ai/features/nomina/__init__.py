# -*- coding: utf-8 -*-
"""Módulo de nómina: parser, validador, modelos y servicio de payroll.

Expone:
  - parse_nomina()          : Extrae datos del complemento Nomina 1.2.
  - validate_nomina()       : Valida contra reglas SAT.
  - build_nomina_router()   : Router FastAPI con endpoints /nomina/*.
  - NominaManager           : Gestión de registros de nómina (payroll).
  - PayrollCalculator       : Cálculo de ISR, IMSS y neto.
  - PayrollSummaryGenerator : Resúmenes agregados + exportación CSV.
"""
from b2b_ai.features.nomina.parser import parse_nomina, NominaData
from b2b_ai.features.nomina.validators import validate_nomina
from b2b_ai.features.nomina.routes import build_nomina_router
from b2b_ai.features.nomina.models import (
    NominaRecord,
    NominaRecordCreate,
    NominaConcept,
    NominaStatus,
    ConceptType,
    PayrollSummary,
)
from b2b_ai.features.nomina.service import (
    NominaManager,
    NominaValidator,
    PayrollCalculator,
    PayrollSummaryGenerator,
)

__all__ = [
    "parse_nomina",
    "NominaData",
    "validate_nomina",
    "build_nomina_router",
    "NominaRecord",
    "NominaRecordCreate",
    "NominaConcept",
    "NominaStatus",
    "ConceptType",
    "PayrollSummary",
    "NominaManager",
    "NominaValidator",
    "PayrollCalculator",
    "PayrollSummaryGenerator",
]
