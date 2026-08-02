# -*- coding: utf-8 -*-
"""Módulo de Contabilidad Electrónica del SAT: parser, validador y endpoints.

Expone:
  - parse_balanza_xml(), parse_catalogo_xml(), parse_estado_resultados_xml()
  - validate_balanza(), validate_catalogo(), validate_estado_resultados()
  - build_contabilidad_router()
"""
from b2b_ai.features.contabilidad.parser import (
    parse_balanza_xml,
    parse_catalogo_xml,
    parse_estado_resultados_xml,
    BalanzaData,
    CatalogoData,
    EstadoResultadosData,
    AccountBalance,
    AccountCatalogEntry,
    IncomeStatementLine,
)
from b2b_ai.features.contabilidad.validators import (
    validate_balanza,
    validate_catalogo,
    validate_estado_resultados,
)
from b2b_ai.features.contabilidad.routes import build_contabilidad_router

__all__ = [
    "parse_balanza_xml",
    "parse_catalogo_xml",
    "parse_estado_resultados_xml",
    "BalanzaData",
    "CatalogoData",
    "EstadoResultadosData",
    "AccountBalance",
    "AccountCatalogEntry",
    "IncomeStatementLine",
    "validate_balanza",
    "validate_catalogo",
    "validate_estado_resultados",
    "build_contabilidad_router",
]
