# -*- coding: utf-8 -*-
"""
adapters/__init__.py — Conectores por banco mexicano.

Para el MVP cada adapter expone ``fetch_transactions`` que devuelve movimientos
raw (RawMovement) desde un origen simulado (mock) o desde texto OFX/QFX/CNBV.
La arquitectura permite sustituir el mock por un HTTP real conservando la
misma interfaz.

Expone:
  - BaseBankAdapter      : clase base con interfaz común y helper de mapeo
  - BBVAAdapter, BanorteAdapter, SantanderAdapter, HSBCAdapter
  - MockBankAdapter      : genera movimientos de ejemplo (dev/demo/tests)
"""
from __future__ import annotations

from b2b_ai.features.bank_feeds.adapters.base import BaseBankAdapter
from b2b_ai.features.bank_feeds.adapters.bbva import BBVAAdapter
from b2b_ai.features.bank_feeds.adapters.banorte import BanorteAdapter
from b2b_ai.features.bank_feeds.adapters.santander import SantanderAdapter
from b2b_ai.features.bank_feeds.adapters.hsbc import HSBCAdapter
from b2b_ai.features.bank_feeds.adapters.mock import MockBankAdapter

_ADAPTERS = {
    "BBVA": BBVAAdapter,
    "BANORTE": BanorteAdapter,
    "SANTANDER": SantanderAdapter,
    "HSBC": HSBCAdapter,
}


def get_adapter(provider: str) -> BaseBankAdapter:
    """Devuelve la clase adapter para un banco (por nombre o valor enum)."""
    key = str(getattr(provider, "value", provider)).upper()
    if key in _ADAPTERS:
        return _ADAPTERS[key]()
    raise ValueError(f"Banco no soportado: {provider}")


__all__ = [
    "BaseBankAdapter",
    "BBVAAdapter",
    "BanorteAdapter",
    "SantanderAdapter",
    "HSBCAdapter",
    "MockBankAdapter",
    "get_adapter",
]
