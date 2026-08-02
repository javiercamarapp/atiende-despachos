# -*- coding: utf-8 -*-
"""Módulo de nómina: parser, validador y endpoints para complementos
Nomina 1.2 del SAT.

Expone:
  - parse_nomina()   : Extrae datos del complemento Nomina 1.2.
  - validate_nomina(): Valida contra reglas SAT.
  - build_nomina_router(): Router FastAPI con endpoints /nomina/*.
"""
from b2b_ai.features.nomina.parser import parse_nomina, NominaData
from b2b_ai.features.nomina.validators import validate_nomina
from b2b_ai.features.nomina.routes import build_nomina_router

__all__ = ["parse_nomina", "NominaData", "validate_nomina", "build_nomina_router"]
