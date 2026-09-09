# -*- coding: utf-8 -*-
"""
test_sat_integration_pii_masking.py — Verifica que el RFC (PII) nunca se
exponga sin enmascarar en los logs de la integración con el SAT.

Cubre los adaptadores en b2b_ai/integrations/sat/ (Ecodex, Finkok, Portal SAT
y los PACs: FACTURAPI, PAXFACTURAS, COREFI, MULTIFACTURA), que usan la
utilidad de masking centralizada en b2b_ai.infrastructure.structured_logging
(mask_pii) en cada punto donde se loguea un RFC.
"""
from __future__ import annotations

import logging

import pytest

from b2b_ai.integrations.sat.ecodex import EcodexAdapter
from b2b_ai.integrations.sat.finkok import FinkokAdapter
from b2b_ai.integrations.sat.sat_portal import SATPortalAdapter
from b2b_ai.integrations.sat.pacs.facturapi_adapter import FacturapiAdapter
from b2b_ai.integrations.sat.pacs.paxfacturas_adapter import PAXFACTURASAdapter
from b2b_ai.integrations.sat.pacs.corefi_adapter import CorefiAdapter
from b2b_ai.integrations.sat.pacs.multifactura_adapter import MultifacturaAdapter
from b2b_ai.integrations.sat.models import CFDIRequest

RFC_EMISOR = "XAXX010101000"
RFC_RECEPTOR = "AAA010101AAA"

_CONSULTA_ADAPTERS = [
    EcodexAdapter,
    FinkokAdapter,
    SATPortalAdapter,
    FacturapiAdapter,
    PAXFACTURASAdapter,
    CorefiAdapter,
    MultifacturaAdapter,
]

_TIMBRADO_ADAPTERS = [EcodexAdapter, FinkokAdapter]


def _cfdi_request(rfc_emisor: str, rfc_receptor: str) -> CFDIRequest:
    return CFDIRequest(
        rfc_emisor=rfc_emisor,
        rfc_receptor=rfc_receptor,
        fecha="2026-09-08",
        subtotal=1000.0,
        iva=160.0,
        total=1160.0,
        tipo="I",
        serie="A",
    )


@pytest.mark.parametrize("adapter_cls", _CONSULTA_ADAPTERS)
def test_consultar_rfc_no_expone_rfc_en_logs(adapter_cls, caplog):
    """consultar_rfc() no debe loguear el RFC en claro."""
    adapter = adapter_cls()
    adapter.connect()

    with caplog.at_level(logging.INFO):
        adapter.consultar_rfc(RFC_EMISOR)

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert RFC_EMISOR not in log_text, (
        f"{adapter_cls.__name__}.consultar_rfc filtró el RFC sin enmascarar: "
        f"{log_text!r}"
    )
    assert "<rfc>" in log_text, (
        f"{adapter_cls.__name__}.consultar_rfc no aplicó mask_pii al RFC "
        f"(se esperaba el token <rfc> en el log): {log_text!r}"
    )


@pytest.mark.parametrize("adapter_cls", _TIMBRADO_ADAPTERS)
def test_timbrar_cfdi_no_expone_rfc_en_logs(adapter_cls, caplog):
    """timbrar_cfdi() no debe loguear los RFC de emisor/receptor en claro."""
    adapter = adapter_cls()
    adapter.connect()
    cfdi_data = _cfdi_request(RFC_EMISOR, RFC_RECEPTOR)

    with caplog.at_level(logging.INFO):
        adapter.timbrar_cfdi(cfdi_data)

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert RFC_EMISOR not in log_text
    assert RFC_RECEPTOR not in log_text
    assert log_text.count("<rfc>") >= 2, (
        f"{adapter_cls.__name__}.timbrar_cfdi no enmascaró ambos RFC "
        f"(emisor y receptor): {log_text!r}"
    )


def test_mask_pii_es_la_utilidad_reutilizada():
    """Los adaptadores SAT reutilizan mask_pii de infrastructure.structured_logging
    (no inventan una utilidad de masking nueva)."""
    import b2b_ai.integrations.sat.ecodex as ecodex_mod
    import b2b_ai.integrations.sat.finkok as finkok_mod
    import b2b_ai.integrations.sat.sat_portal as portal_mod
    import b2b_ai.integrations.sat.pacs.facturapi_adapter as facturapi_mod
    import b2b_ai.integrations.sat.pacs.paxfacturas_adapter as paxfacturas_mod
    import b2b_ai.integrations.sat.pacs.corefi_adapter as corefi_mod
    import b2b_ai.integrations.sat.pacs.multifactura_adapter as multifactura_mod
    from b2b_ai.infrastructure.structured_logging import mask_pii as canonical_mask_pii

    for mod in (
        ecodex_mod, finkok_mod, portal_mod, facturapi_mod,
        paxfacturas_mod, corefi_mod, multifactura_mod,
    ):
        assert mod.mask_pii is canonical_mask_pii, (
            f"{mod.__name__} no está usando la utilidad canónica de masking "
            f"(b2b_ai.infrastructure.structured_logging.mask_pii)"
        )
