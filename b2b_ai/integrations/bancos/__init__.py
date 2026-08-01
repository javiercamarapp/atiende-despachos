# -*- coding: utf-8 -*-
"""Módulo de integración bancaria — BBVA, Banorte, Santander, OFX, CSV."""

from b2b_ai.integrations.bancos.adapter import BankAdapter, BankAdapterError
from b2b_ai.integrations.bancos.bbva import BBVAAdapter
from b2b_ai.integrations.bancos.banorte import BanorteAdapter
from b2b_ai.integrations.bancos.santander import SantanderAdapter
from b2b_ai.integrations.bancos.ofx_parser import OFXParser
from b2b_ai.integrations.bancos.csv_parser import CSVParser
from b2b_ai.integrations.bancos.models import (
    BankConfig,
    BankStatement,
    BankTransaction,
    Banco,
    FormatoEstado,
    TipoTransaccion,
)

__all__ = [
    "BankAdapter",
    "BankAdapterError",
    "BBVAAdapter",
    "BanorteAdapter",
    "SantanderAdapter",
    "OFXParser",
    "CSVParser",
    "BankConfig",
    "BankStatement",
    "BankTransaction",
    "Banco",
    "FormatoEstado",
    "TipoTransaccion",
]
