# -*- coding: utf-8 -*-
"""Módulo de Contabilidad Electrónica del SAT: generación de XML para
balanza de comprobación y catálogo de cuentas.

Expone:
  - CuentaContable, BalanzaRow, BalanzaRequest, CatalogoCuenta,
    ContabilidadElectronicaResponse
  - generate_balanza_xml(), generate_catalogo_xml()
  - validate_balanza(), validate_catalogo(), validate_balanza_totals()
  - build_contabilidad_electronica_router()
"""
from b2b_ai.features.contabilidad_electronica.models import (
    CuentaContable,
    BalanzaRow,
    BalanzaRequest,
    CatalogoCuenta,
    ContabilidadElectronicaResponse,
)
from b2b_ai.features.contabilidad_electronica.generator import (
    generate_balanza_xml,
    generate_catalogo_xml,
)
from b2b_ai.features.contabilidad_electronica.validators import (
    validate_balanza,
    validate_catalogo,
    validate_balanza_totals,
)
from b2b_ai.features.contabilidad_electronica.routes import (
    build_contabilidad_electronica_router,
)

__all__ = [
    "CuentaContable",
    "BalanzaRow",
    "BalanzaRequest",
    "CatalogoCuenta",
    "ContabilidadElectronicaResponse",
    "generate_balanza_xml",
    "generate_catalogo_xml",
    "validate_balanza",
    "validate_catalogo",
    "validate_balanza_totals",
    "build_contabilidad_electronica_router",
]
