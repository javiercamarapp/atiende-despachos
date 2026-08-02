# -*- coding: utf-8 -*-
"""
mock.py — MockBankAdapter para el MVP.

Genera movimientos de ejemplo deterministas para demo, desarrollo y tests,
simulando la respuesta de un feed bancario real (SPEI, CoDi, banca en línea).
Usado por todos los adapters cuando no se provee contenido OFX/QFX/CNBV real.
"""
from __future__ import annotations

from typing import List, Optional

from b2b_ai.features.bank_feeds.adapters.base import BaseBankAdapter
from b2b_ai.features.bank_feeds.models import BankProvider
from b2b_ai.features.bank_feeds.processors.ofx import RawMovement

_SAMPLE = [
    # (external_id, date, amount, desc, type_raw, channel, ref, counterparty)
    ("SPEI000001", "2025-01-15", "15000.00", "Transferencia SPEI recibida — Cliente A",
     "CREDIT", "SPEI", "SPEI-1001", "XAXX010101000"),
    ("SPEI000002", "2025-01-16", "-5200.00", "Pago proveedor — factura 0012",
     "DEBIT", "SPEI", "SPEI-1002", "XAXX010101000"),
    ("CODI000001", "2025-01-17", "780.50", "Cobro CoDi punto de venta",
     "CREDIT", "CODI", "CODI-2001", "XAXX010101000"),
    ("BANCA00001", "2025-01-18", "-12000.00", "Nómina quincenal",
     "DEBIT", "BANCA_EN_LINEA", "NOM-3001", "XAXX010101000"),
    ("BANCA00002", "2025-01-19", "-450.00", "Comisión bancaria",
     "DEBIT", "BANCA_EN_LINEA", "COM-4001", ""),
    ("SPEI000003", "2025-01-20", "3200.00", "Abono SPEI — reembolso",
     "CREDIT", "SPEI", "SPEI-1003", "XAXX010101000"),
]


class MockBankAdapter(BaseBankAdapter):
    """Genera movimientos de ejemplo deterministas para el banco indicado."""

    def __init__(self, provider: BankProvider = BankProvider.BBVA, http_session=None,
                 base_url: Optional[str] = None):
        super().__init__(http_session=http_session, base_url=base_url)
        self.provider = provider

    def fetch_transactions(
        self,
        account: dict,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawMovement]:
        movements: List[RawMovement] = []
        for (eid, date, amt, desc, ttype, channel, ref, cp) in _SAMPLE:
            if from_date and date < from_date:
                continue
            if to_date and date > to_date:
                continue
            movements.append(
                RawMovement(
                    external_id=f"{self.provider.value}:{eid}",
                    date=date,
                    amount=amt,
                    description=desc,
                    memo=desc,
                    type_raw=ttype,
                    bank_name=self.provider.value,
                    extra={"channel": channel, "reference": ref, "counterparty": cp},
                )
            )
        if limit and limit > 0:
            return movements[:limit]
        return movements
