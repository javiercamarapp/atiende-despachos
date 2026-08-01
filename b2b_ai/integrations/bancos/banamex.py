# -*- coding: utf-8 -*-
"""
banamex.py — Adaptador mock para Citibanamex (API).
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


class BanamexAdapter(BankAdapter):
    """Adaptador mock para Citibanamex."""

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.CITIBANAMEX, account_number="0987654321")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("BanamexAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        self._ensure_connected()
        now = datetime.now()
        txs = [
            BankTransaction(fecha=f"2026-01-{12+i:02d}", monto=(-1 if i % 2 else 1) * (4000 + i * 800),
                           descripcion=f"Movimiento Banamex {i}", banco="citibanamex",
                           tipo=TipoTransaccion.CARGO if i % 2 else TipoTransaccion.DEPOSITO)
            for i in range(1, 6)
        ]
        return BankStatement(account_id=self.config.account_number, bank=Banco.CITIBANAMEX,
                            periodo=now.strftime("%Y-%m"), transactions=txs,
                            saldo_inicial=200000.0, saldo_final=220000.0,
                            total_cargos=-12000.0, total_abonos=32000.0, num_transacciones=5)

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        self._ensure_connected()
        return [
            BankTransaction(fecha=f"2026-01-{12+i:02d}", monto=(-1 if i % 2 else 1) * 4000,
                           descripcion=f"Transacción Banamex {i}", tipo=TipoTransaccion.TRANSFERENCIA)
            for i in range(1, 4)
        ]

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        self._ensure_connected()
        return b"MOCK_BANAMEX_STATEMENT_" + format.value.encode()
