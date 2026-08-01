import os
# -*- coding: utf-8 -*-
"""
hsbc.py — Adaptador mock para HSBC México (API).
En producción, se conectaría a la API de HSBC Business.
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


class HSBCAdapter(BankAdapter):
    """Adaptador mock para HSBC México."""

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.HSBC, account_number="0123456789")
            api_key=os.environ.get("HSBC_API_KEY", ""),        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("HSBCAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        self._ensure_connected()
        now = datetime.now()
        txs = [
            BankTransaction(fecha=f"2026-01-{10+i:02d}", monto=(-1 if i % 2 else 1) * (5000 + i * 1000),
                           descripcion=f"Movimiento HSBC {i}", referencia=f"HSBC-{_uuid.uuid4().hex[:6]}",
                           tipo=TipoTransaccion.CARGO if i % 2 else TipoTransaccion.ABONO,
                           banco="hsbc", cuenta=self.config.account_number)
            for i in range(1, 6)
        ]
        return BankStatement(account_id=self.config.account_number, bank=Banco.HSBC,
                            periodo=now.strftime("%Y-%m"), transactions=txs,
                            saldo_inicial=150000.0, saldo_final=175000.0,
                            total_cargos=-15000.0, total_abonos=40000.0, num_transacciones=5)

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        self._ensure_connected()
        return [
            BankTransaction(fecha=f"2026-01-{10+i:02d}", monto=(-1 if i % 2 else 1) * 5000,
                           descripcion=f"Transacción HSBC {i}", tipo=TipoTransaccion.TRANSFERENCIA)
            for i in range(1, 4)
        ]

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        self._ensure_connected()
        return b"MOCK_HSBC_STATEMENT_" + format.value.encode()
