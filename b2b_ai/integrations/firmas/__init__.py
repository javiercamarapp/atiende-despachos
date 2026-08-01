# -*- coding: utf-8 -*-
"""Módulo de integración de Firmas Electrónicas — DocuSign, FIEL/SAT."""

from b2b_ai.integrations.firmas.adapter import SignatureAdapter, SignatureAdapterError
from b2b_ai.integrations.firmas.docusign_adapter import DocuSignAdapter
from b2b_ai.integrations.firmas.fiel_adapter import FIELAdapter
from b2b_ai.integrations.firmas.models import (
    Envelope,
    EnvelopeStatus,
    SignatureConfig,
    SignatureProvider,
    Signer,
    SignerStatus,
    SigningRequest,
    SigningStatus,
)

__all__ = [
    "SignatureAdapter",
    "SignatureAdapterError",
    "DocuSignAdapter",
    "FIELAdapter",
    "Envelope",
    "EnvelopeStatus",
    "SignatureConfig",
    "SignatureProvider",
    "Signer",
    "SignerStatus",
    "SigningRequest",
    "SigningStatus",
]
