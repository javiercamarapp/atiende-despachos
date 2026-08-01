"""Módulo de PACs adicionales — Corefi, Facturapi, PAXFACTURAS, Multifactura."""
from b2b_ai.integrations.sat.pacs.corefi_adapter import CorefiAdapter
from b2b_ai.integrations.sat.pacs.facturapi_adapter import FacturapiAdapter
from b2b_ai.integrations.sat.pacs.paxfacturas_adapter import PAXFACTURASAdapter
from b2b_ai.integrations.sat.pacs.multifactura_adapter import MultifacturaAdapter

__all__ = ["CorefiAdapter", "FacturapiAdapter", "PAXFACTURASAdapter", "MultifacturaAdapter"]
