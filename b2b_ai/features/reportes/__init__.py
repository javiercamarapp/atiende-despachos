# -*- coding: utf-8 -*-
"""Módulo de Reportes Contables: generación de reportes profesionales.

Expone:
  - ReportData, ReportSection, ReportLine — dataclasses para reportes
  - BalanceGeneral, EstadoResultados, ConciliacionBancaria, ReporteNomina
  - serialize_json, serialize_csv, serialize_html
  - build_reportes_router()
"""
from b2b_ai.features.reportes.generator import (
    ReportData,
    ReportSection,
    ReportLine,
    generate_balance_general,
    generate_estado_resultados,
    generate_conciliacion_bancaria,
    generate_reporte_nomina,
)
from b2b_ai.features.reportes.serializers import (
    serialize_json,
    serialize_csv,
    serialize_html,
)
from b2b_ai.features.reportes.routes import build_reportes_router

__all__ = [
    "ReportData",
    "ReportSection",
    "ReportLine",
    "generate_balance_general",
    "generate_estado_resultados",
    "generate_conciliacion_bancaria",
    "generate_reporte_nomina",
    "serialize_json",
    "serialize_csv",
    "serialize_html",
    "build_reportes_router",
]
