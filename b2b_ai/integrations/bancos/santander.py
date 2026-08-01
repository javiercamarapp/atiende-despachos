# -*- coding: utf-8 -*-
"""
santander.py — Adaptador mock para Santander México.

Implementa la interfaz BankAdapter con respuestas simuladas.
En producción, se conectaría a la API de Santander.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.bancos.adapter import BankAdapter
from b2b_ai.integrations.bancos.models import (
    BankConfig,
    BankStatement,
    BankTransaction,
    Banco,
    FormatoEstado,
    TipoTransaccion,
)

logger = logging.getLogger(__name__)


class SantanderAdapter(BankAdapter):
    """Adaptador mock para Santander México.

    En producción, se conectaría a la API de Santander
    o al portal de banca en línea empresarial.
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.SANTANDER, account_number="0143456789")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        logger.info("SantanderAdapter: conectando a Santander (mock)...")
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("SantanderAdapter: desconectado")

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        self._ensure_connected()
        logger.info("SantanderAdapter: obteniendo estado de cuenta (mock)")

        transactions = [
            BankTransaction(
                fecha="2026-01-04",
                monto=-12000.00,
                descripcion="SPEI SALIDA",
                references="SAN-REF-001",
                tipo=TipoTransaccion.TRANSFERENCIA,
                banco="Santander",
                cuenta=self.config.account_number,
                saldo_posterior=88000.00,
            ),
            BankTransaction(
                fecha="2026-01-12",
                monto=45000.00,
                descripcion="COBRO CLIENTE MAYORISTA",
                referencia="SAN-REF-002",
                tipo=TipoTransaccion.ABONO,
                banco="Santander",
                cuenta=self.config.account_number,
                saldo_posterior=133000.00,
            ),
            BankTransaction(
                fecha="2026-01-25",
                monto=-450.00,
                descripcion="COMISION MENSUAL",
                referencia="SAN-REF-003",
                tipo=TipoTransaccion.COMISION,
                banco="Santander",
                cuenta=self.config.account_number,
                saldo_posterior=132550.00,
            ),
        ]

        return BankStatement(
            account_id=self.config.account_number,
            bank=Banco.SANTANDER,
            periodo="2026-01",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-31",
            transactions=transactions,
            saldo_inicial=100000.00,
            moneda="MXN",
        )

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        self._ensure_connected()
        return self.get_statement(date_range).transactions

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        self._ensure_connected()
        logger.info(f"SantanderAdapter: descargando en {format.value} (mock)")
        return b"Mock Santander statement"
