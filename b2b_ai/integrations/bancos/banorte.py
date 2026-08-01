import os
# -*- coding: utf-8 -*-
"""
banorte.py — Adaptador mock para Banorte.

Implementa la interfaz BankAdapter con respuestas simuladas.
En producción, se conectaría a la API de Banorte.
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


class BanorteAdapter(BankAdapter):
    """Adaptador mock para Banorte México.

    En producción, se conectaría a la API de Banorte
    o al portal de banca en línea empresarial.
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.BANORTE, account_number="0723456789")
            api_key=os.environ.get("BANORTE_API_KEY", ""),        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        logger.info("BanorteAdapter: conectando a Banorte (mock)...")
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("BanorteAdapter: desconectado")

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        self._ensure_connected()
        logger.info("BanorteAdapter: obteniendo estado de cuenta (mock)")

        transactions = [
            BankTransaction(
                fecha="2026-01-03",
                monto=-8500.00,
                descripcion="PAGO PROVEEDOR BANORTE",
                referencia="BAN-REF-001",
                tipo=TipoTransaccion.PAGO,
                banco="Banorte",
                cuenta=self.config.account_number,
                saldo_posterior=141500.00,
            ),
            BankTransaction(
                fecha="2026-01-08",
                monto=35000.00,
                descripcion="DEPOSITO CLIENTE",
                referencia="BAN-REF-002",
                tipo=TipoTransaccion.DEPOSITO,
                banco="Banorte",
                cuenta=self.config.account_number,
                saldo_posterior=176500.00,
            ),
            BankTransaction(
                fecha="2026-01-20",
                monto=-18000.00,
                descripcion="PAGO NOMINA ENERO",
                referencia="BAN-REF-003",
                tipo=TipoTransaccion.PAGO,
                banco="Banorte",
                cuenta=self.config.account_number,
                saldo_posterior=158500.00,
            ),
        ]

        return BankStatement(
            account_id=self.config.account_number,
            bank=Banco.BANORTE,
            periodo="2026-01",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-31",
            transactions=transactions,
            saldo_inicial=150000.00,
            moneda="MXN",
        )

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        self._ensure_connected()
        return self.get_statement(date_range).transactions

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        self._ensure_connected()
        logger.info(f"BanorteAdapter: descargando en {format.value} (mock)")
        return b"Mock Banorte statement"
