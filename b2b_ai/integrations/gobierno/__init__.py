"""Módulo de Portales Gubernamentales — IMSS, INFONAVIT, SAR, CONDUSEF (Computer Use)."""
from b2b_ai.integrations.gobierno.imss_adapter import IMSSAdapter
from b2b_ai.integrations.gobierno.infonavit_adapter import INFONAVITAdapter
from b2b_ai.integrations.gobierno.sar_adapter import SARAdapter
from b2b_ai.integrations.gobierno.condusef_adapter import CONDUSEFAdapter

__all__ = ["IMSSAdapter", "INFONAVITAdapter", "SARAdapter", "CONDUSEFAdapter"]
