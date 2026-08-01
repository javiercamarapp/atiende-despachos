# -*- coding: utf-8 -*-
"""
scotiabank.py — Adaptador mock para Scotiabank México (API).
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


class ScotiabankAdapter(BankAdapter):
    """Adaptador mock para Scotiabank."""

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.SCOTIABANK, account_number="1122334455")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("ScotiabankAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        self._ensure_connected()
        txs = [
            BankTransaction(fecha=f"2026-01-{14+i:02d}", monto=(-1 if i % 2 else 1) * (3000 + i * 600),
                           descripcion=f"Movimiento Scotiabank {i}", banco="scotiabank",
                           tipo=TipoTransaccion.CARGO if i % 2 else TipoTransaccion.ABONO)
            for i in range(1, 6)
        ]
        return BankStatement(account_id=self.config.account_number, bank=Banco.SCOTIABANK,
                            periodo=datetime.now().strftime("%Y-%m"), transactions=txs,
                            saldo_inicial=80000.0, saldo_final=95000.0,
                            total_cargos=-9000.0, total_abonos=24000.0, num_transacciones=5)

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        self._ensure_connected()
        return [
            BankTransaction(fecha=f"2026-01-{14+i:02d}", monto=(-1 if i % 2 else 1) * 3000,
                           descripcion=f"Transacción Scotiabank {i}", tipo=TipoTransaccion.TRANSFERENCIA)
            for i in range(1, 4)
        ]

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        self._ensure_connected()
        return b"MOCK_SCOTIABANK_STATEMENT_" + format.value.encode()
