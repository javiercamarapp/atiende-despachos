# -*- coding: utf-8 -*-
"""hsbc.py — Adaptador mock para HSBC México.

Implementa la interfaz BankAdapter con respuestas simuladas.
En producción, se conectaría a la API de HSBC Open Banking.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.bancos.adapter import BankAdapter, BankAdapterError
from b2b_ai.integrations.bancos.models import (
    BankConfig,
    BankStatement,
    BankTransaction,
    Banco,
    FormatoEstado,
    TipoTransaccion,
)

logger = logging.getLogger(__name__)

import os


class HSBCAdapter(BankAdapter):
    """Adaptador mock para HSBC México.

    En producción, se conectaría a la API de HSBC
    (https://www.hsbc.com/).
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(
            bank=Banco.HSBC,
            account_number="HSBC123456789",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a HSBC."""
        logger.info("HSBCAdapter: conectando a HSBC (mock)...")
        self._connected = True
        logger.info("HSBCAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("HSBCAdapter: desconectado")

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        """Obtiene estado de cuenta mock de HSBC."""
        self._ensure_connected()
        logger.info("HSBCAdapter: obteniendo estado de cuenta (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        transactions = [
            BankTransaction(
                fecha="2026-01-03",
                monto=-8500.00,
                descripcion="TRANSFERENCIA SPEI",
                referencia="HSBC-REF-001",
                tipo=TipoTransaccion.TRANSFERENCIA,
                banco="HSBC",
                cuenta=self.config.account_number,
                rfc_contraparte="AAA010101AAA",
                nombre_contraparte="PROVEEDOR ABC S.A. DE C.V.",
                saldo_posterior=141500.00,
            ),
            BankTransaction(
                fecha="2026-01-07",
                monto=35000.00,
                descripcion="DEPOSITO CLIENTE",
                referencia="HSBC-REF-002",
                tipo=TipoTransaccion.DEPOSITO,
                banco="HSBC",
                cuenta=self.config.account_number,
                saldo_posterior=176500.00,
            ),
            BankTransaction(
                fecha="2026-01-12",
                monto=-250.00,
                descripcion="COMISION MANTENIMIENTO",
                referencia="HSBC-REF-003",
                tipo=TipoTransaccion.COMISION,
                banco="HSBC",
                cuenta=self.config.account_number,
                saldo_posterior=176250.00,
            ),
            BankTransaction(
                fecha="2026-01-18",
                monto=-15000.00,
                descripcion="PAGO PROVEEDOR",
                referencia="HSBC-REF-004",
                tipo=TipoTransaccion.PAGO,
                banco="HSBC",
                cuenta=self.config.account_number,
                rfc_contraparte="BBB020202BBB",
                nombre_contraparte="SERVICIOS XYZ S.A.",
                saldo_posterior=161250.00,
            ),
        ]

        return BankStatement(
            account_id=self.config.account_number,
            bank=Banco.HSBC,
            periodo="2026-01",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-31",
            transactions=transactions,
            saldo_inicial=150000.00,
            moneda="MXN",
        )

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        """Obtiene transacciones mock de HSBC."""
        self._ensure_connected()
        logger.info("HSBCAdapter: obteniendo transacciones (mock)")
        statement = self.get_statement(date_range)
        return statement.transactions

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        """Descarga estado de cuenta mock de HSBC."""
        self._ensure_connected()
        logger.info(f"HSBCAdapter: descargando estado de cuenta en {format.value} (mock)")

        if format == FormatoEstado.OFX:
            return b"OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n<OFX>...</OFX>"
        elif format == FormatoEstado.CSV:
            return b"Fecha,Monto,Descripcion,Referencia\n2026-01-03,-8500.00,TRANSFERENCIA SPEI,HSBC-REF-001"
        else:
            return b"Mock HSBC statement"
