# -*- coding: utf-8 -*-
"""
bbva.py — Adapter del banco BBVA.

Conecta con el feed de BBVA (banca en línea / SPEI / CoDi). Para el MVP acepta
un estado de cuenta OFX/QFX en ``account`` (clave ``ofx_content``) y lo
parsea; si no hay contenido usa el mock genérico.
"""
from __future__ import annotations

from typing import List, Optional

from b2b_ai.features.bank_feeds.adapters.base import BaseBankAdapter, slice_movements
from b2b_ai.features.bank_feeds.models import BankProvider
from b2b_ai.features.bank_feeds.processors.ofx import RawMovement, parse_ofx


class BBVAAdapter(BaseBankAdapter):
    provider = BankProvider.BBVA

    def fetch_transactions(
        self,
        account: dict,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawMovement]:
        content = account.get("ofx_content") or account.get("statement_text")
        if content:
            return slice_movements(parse_ofx(content), limit)
        from b2b_ai.features.bank_feeds.adapters.mock import MockBankAdapter
        return slice_movements(
            MockBankAdapter(provider=self.provider).fetch_transactions(
                account, from_date, to_date, limit
            ),
            limit,
        )
