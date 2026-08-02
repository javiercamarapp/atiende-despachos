# -*- coding: utf-8 -*-
"""Módulo de integración SAT — PACs, CFDI, Cancelación, RFC, Contabilidad Electrónica."""

from b2b_ai.integrations.sat.adapter import SATAdapter, SATAdapterError
from b2b_ai.integrations.sat.ecodex import EcodexAdapter
from b2b_ai.integrations.sat.finkok import FinkokAdapter
from b2b_ai.integrations.sat.sat_portal import SATPortalAdapter
from b2b_ai.integrations.sat.models import (
    CancelacionRequest,
    CFDI,
    CFDIRequest,
    CFDIStatus,
    ContabilidadElectronica,
    RFCStatus,
    TipoCancelacion,
    TipoComprobante,
    TimbradoResponse,
)

__all__ = [
    "SATAdapter",
    "SATAdapterError",
    "EcodexAdapter",
    "FinkokAdapter",
    "SATPortalAdapter",
    "CancelacionRequest",
    "CFDI",
    "CFDIRequest",
    "CFDIStatus",
    "ContabilidadElectronica",
    "RFCStatus",
    "TipoCancelacion",
    "TipoComprobante",
    "TimbradoResponse",
]
