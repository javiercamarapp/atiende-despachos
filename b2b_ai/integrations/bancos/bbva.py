# -*- coding: utf-8 -*-
"""
bbva.py — Adaptador mock para BBVA México.

Implementa la interfaz BankAdapter con respuestas simuladas.
En producción, se conectaría a la API de BBVA Open Banking.
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
class BBVAAdapter(BankAdapter):
    """Adaptador mock para BBVA México.

    En producción, se conectaría a la API de BBVA Open Banking
    (https://api.bbva.com/).
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.BBVA, account_number="0123456789",
            api_key=os.environ.get("BBVA_API_KEY", ""))
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a BBVA México."""
        logger.info("BBVAAdapter: conectando a BBVA México (mock)...")
        self._connected = True
        logger.info("BBVAAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("BBVAAdapter: desconectado")

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        """Obtiene estado de cuenta mock de BBVA."""
        self._ensure_connected()
        logger.info("BBVAAdapter: obteniendo estado de cuenta (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        transactions = [
            BankTransaction(
                fecha="2026-01-02",
                monto=-15000.00,
                descripcion="TRANSFERENCIA INTERBANCARIA BANCO NACIONAL",
                referencia="BBVA-REF-001",
                tipo=TipoTransaccion.TRANSFERENCIA,
                banco="BBVA",
                cuenta=self.config.account_number,
                rfc_contraparte="AAA010101AAA",
                nombre_contraparte="EMPRESA CLIENTE S.A. DE C.V.",
                saldo_posterior=185000.00,
            ),
            BankTransaction(
                fecha="2026-01-05",
                monto=50000.00,
                descripcion="DEPOSITO EN EFECTIVO",
                referencia="BBVA-REF-002",
                tipo=TipoTransaccion.DEPOSITO,
                banco="BBVA",
                cuenta=self.config.account_number,
                saldo_posterior=235000.00,
            ),
            BankTransaction(
                fecha="2026-01-10",
                monto=-350.00,
                descripcion="COMISION POR MANTENIMIENTO",
                referencia="BBVA-REF-003",
                tipo=TipoTransaccion.COMISION,
                banco="BBVA",
                cuenta=self.config.account_number,
                saldo_posterior=234650.00,
            ),
            BankTransaction(
                fecha="2026-01-15",
                monto=-22000.00,
                descripcion="PAGO NOMINA ENERO",
                referencia="BBVA-REF-004",
                tipo=TipoTransaccion.PAGO,
                banco="BBVA",
                cuenta=self.config.account_number,
                saldo_posterior=212650.00,
            ),
        ]

        return BankStatement(
            account_id=self.config.account_number,
            bank=Banco.BBVA,
            periodo="2026-01",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-31",
            transactions=transactions,
            saldo_inicial=200000.00,
            moneda="MXN",
        )

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        """Obtiene transacciones mock de BBVA."""
        self._ensure_connected()
        logger.info("BBVAAdapter: obteniendo transacciones (mock)")

        statement = self.get_statement(date_range)
        return statement.transactions

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        """Descarga estado de cuenta mock de BBVA."""
        self._ensure_connected()
        logger.info(f"BBVAAdapter: descargando estado de cuenta en {format.value} (mock)")

        # Mock: retornar contenido simulado
        if format == FormatoEstado.OFX:
            return b"OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n<OFX>...</OFX>"
        elif format == FormatoEstado.CSV:
            return b"Fecha,Monto,Descripcion,Referencia\n2026-01-02,-15000.00,TRANSFERENCIA,BBVA-REF-001"
        else:
            return b"Mock statement content"
