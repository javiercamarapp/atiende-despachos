"""Módulo de integración de Firmas Electrónicas — DocuSign, FIEL/SAT, Adobe Sign."""
from b2b_ai.integrations.firmas.adapter import SignatureAdapter, SignatureAdapterError
from b2b_ai.integrations.firmas.docusign_adapter import DocuSignAdapter
from b2b_ai.integrations.firmas.fiel_adapter import FIELAdapter
from b2b_ai.integrations.firmas.adobe_sign_adapter import AdobeSignAdapter
from b2b_ai.integrations.firmas.models import (
    Envelope, EnvelopeStatus, SignatureConfig, SignatureProvider,
    Signer, SignerStatus, SigningRequest, SigningStatus,
)

__all__ = [
    "SignatureAdapter", "SignatureAdapterError",
    "DocuSignAdapter", "FIELAdapter", "AdobeSignAdapter",
    "Envelope", "EnvelopeStatus", "SignatureConfig", "SignatureProvider",
    "Signer", "SignerStatus", "SigningRequest", "SigningStatus",
]
