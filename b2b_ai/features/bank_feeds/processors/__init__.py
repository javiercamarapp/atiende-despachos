# -*- coding: utf-8 -*-
"""
processors/__init__.py — Parsers de formatos de estados de cuenta bancarios
mexicanos: OFX/QFX (QuickBooks/Instituciones) y CNBV.

Expone:
  - ofx.parse_ofx      : parsea texto OFX/QFX a lista de transacciones raw
  - cnbv.parse_cnbv    : parsea estado CNBV (texto/CSV) a lista raw
  - RawMovement        : forma normalizada intermedia usada por los adapters
"""
from __future__ import annotations

from b2b_ai.features.bank_feeds.processors.ofx import RawMovement, parse_ofx
from b2b_ai.features.bank_feeds.processors.cnbv import parse_cnbv

__all__ = ["RawMovement", "parse_ofx", "parse_cnbv"]
