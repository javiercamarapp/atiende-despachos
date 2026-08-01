import os
# -*- coding: utf-8 -*-
"""
afirme.py — Adaptador mock para Banco Afirme (API).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.bancos.adapter import BankAdapter
from b2b_ai.integrations.bancos.models import (
    BankConfig, BankStatement, BankTransaction, Banco, FormatoEstado, TipoTransaccion,
)

logger = logging.getLogger(__name__)


class AfirmeAdapter(BankAdapter):
    """Adaptador mock para Banco Afirme."""

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.AFIRME, account_number="9988776655")
            api_key=os.environ.get("AFIRME_API_KEY", ""),        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("AfirmeAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        self._ensure_connected()
        txs = [
            BankTransaction(fecha=f"2026-01-{18+i:02d}", monto=(-1 if i % 2 else 1) * (2000 + i * 400),
                           descripcion=f"Movimiento Afirme {i}", banco="afirme",
                           tipo=TipoTransaccion.CARGO if i % 2 else TipoTransaccion.ABONO)
            for i in range(1, 6)
        ]
        return BankStatement(account_id=self.config.account_number, bank=Banco.AFIRME,
                            periodo=datetime.now().strftime("%Y-%m"), transactions=txs,
                            saldo_inicial=60000.0, saldo_final=68000.0,
                            total_cargos=-6000.0, total_abonos=14000.0, num_transacciones=5)

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        self._ensure_connected()
        return [
            BankTransaction(fecha=f"2026-01-{18+i:02d}", monto=(-1 if i % 2 else 1) * 2000,
                           descripcion=f"Transacción Afirme {i}", tipo=TipoTransaccion.TRANSFERENCIA)
            for i in range(1, 4)
        ]

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        self._ensure_connected()
        return b"MOCK_AFIRME_STATEMENT_" + format.value.encode()
