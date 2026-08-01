# -*- coding: utf-8 -*-
"""Módulo de integración SAT Direct — CFDI 4.0, Cancelación, RFC, Contabilidad Electrónica, DIOT."""

from b2b_ai.integrations.sat_direct.adapter import SATDirectAdapter, SATDirectAdapterError
from b2b_ai.integrations.sat_direct.sat_direct_adapter import SATDirectConnection
from b2b_ai.integrations.sat_direct.models import (
    ContabilidadElectronicaDirect,
    CFDIVersion,
    DIOTRecord,
    DIOTStatus,
    DIOTSubmission,
    SATDirectConfig,
    SATDirectTimbradoResponse,
)

__all__ = [
    "SATDirectAdapter",
    "SATDirectAdapterError",
    "SATDirectConnection",
    "ContabilidadElectronicaDirect",
    "CFDIVersion",
    "DIOTRecord",
    "DIOTStatus",
    "DIOTSubmission",
    "SATDirectConfig",
    "SATDirectTimbradoResponse",
]
