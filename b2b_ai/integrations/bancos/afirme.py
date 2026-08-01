# -*- coding: utf-8 -*-
"""afirme.py — Adaptador mock para GENERIC México.

Implementa la interfaz BankAdapter con respuestas simuladas.
En producción, se conectaría a la API de GENERIC Open Banking.
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


class AfirmeAdapter(BankAdapter):
    """Adaptador mock para GENERIC México.

    En producción, se conectaría a la API de GENERIC
    (https://www.afirme.com/).
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(
            bank=Banco.GENERIC,
            account_number="AFIR123456789",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a GENERIC."""
        logger.info("AfirmeAdapter: conectando a GENERIC (mock)...")
        self._connected = True
        logger.info("AfirmeAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("AfirmeAdapter: desconectado")

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        """Obtiene estado de cuenta mock de GENERIC."""
        self._ensure_connected()
        logger.info("AfirmeAdapter: obteniendo estado de cuenta (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        transactions = [
            BankTransaction(
                fecha="2026-01-03",
                monto=-8500.00,
                descripcion="TRANSFERENCIA SPEI",
                referencia="AFIRME-REF-001",
                tipo=TipoTransaccion.TRANSFERENCIA,
                banco="GENERIC",
                cuenta=self.config.account_number,
                rfc_contraparte="AAA010101AAA",
                nombre_contraparte="PROVEEDOR ABC S.A. DE C.V.",
                saldo_posterior=141500.00,
            ),
            BankTransaction(
                fecha="2026-01-07",
                monto=35000.00,
                descripcion="DEPOSITO CLIENTE",
                referencia="AFIRME-REF-002",
                tipo=TipoTransaccion.DEPOSITO,
                banco="GENERIC",
                cuenta=self.config.account_number,
                saldo_posterior=176500.00,
            ),
            BankTransaction(
                fecha="2026-01-12",
                monto=-250.00,
                descripcion="COMISION MANTENIMIENTO",
                referencia="AFIRME-REF-003",
                tipo=TipoTransaccion.COMISION,
                banco="GENERIC",
                cuenta=self.config.account_number,
                saldo_posterior=176250.00,
            ),
            BankTransaction(
                fecha="2026-01-18",
                monto=-15000.00,
                descripcion="PAGO PROVEEDOR",
                referencia="AFIRME-REF-004",
                tipo=TipoTransaccion.PAGO,
                banco="GENERIC",
                cuenta=self.config.account_number,
                rfc_contraparte="BBB020202BBB",
                nombre_contraparte="SERVICIOS XYZ S.A.",
                saldo_posterior=161250.00,
            ),
        ]

        return BankStatement(
            account_id=self.config.account_number,
            bank=Banco.GENERIC,
            periodo="2026-01",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-31",
            transactions=transactions,
            saldo_inicial=150000.00,
            moneda="MXN",
        )

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        """Obtiene transacciones mock de GENERIC."""
        self._ensure_connected()
        logger.info("AfirmeAdapter: obteniendo transacciones (mock)")
        statement = self.get_statement(date_range)
        return statement.transactions

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        """Descarga estado de cuenta mock de GENERIC."""
        self._ensure_connected()
        logger.info(f"AfirmeAdapter: descargando estado de cuenta en {format.value} (mock)")

        if format == FormatoEstado.OFX:
            return b"OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n<OFX>...</OFX>"
        elif format == FormatoEstado.CSV:
            return b"Fecha,Monto,Descripcion,Referencia\n2026-01-03,-8500.00,TRANSFERENCIA SPEI,AFIRME-REF-001"
        else:
            return b"Mock GENERIC statement"
