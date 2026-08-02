"""Módulo de Cumplimiento Gubernamental — CFF, LISR, LIVA, LFT, LFPDPPP, NOM-151."""
from b2b_ai.integrations.compliance.cff_adapter import CFFCompliance
from b2b_ai.integrations.compliance.lisr_adapter import LISRCompliance
from b2b_ai.integrations.compliance.liva_adapter import LIVACompliance
from b2b_ai.integrations.compliance.lft_adapter import LFTCompliance
from b2b_ai.integrations.compliance.lfpdppp_adapter import LFPDPPPCompliance
from b2b_ai.integrations.compliance.nom151_adapter import NOM151Compliance

__all__ = [
    "CFFCompliance", "LISRCompliance", "LIVACompliance",
    "LFTCompliance", "LFPDPPPCompliance", "NOM151Compliance",
]
