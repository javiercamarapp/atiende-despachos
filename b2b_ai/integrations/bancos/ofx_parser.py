# -*- coding: utf-8 -*-
"""
ofx_parser.py — Parser universal de archivos OFX (Open Financial Exchange).

Parsea archivos OFX de cualquier banco mexicano.
"""
from __future__ import annotations

import logging
import re
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


class OFXParser(BankAdapter):
    """Parser universal de archivos OFX.

    Parsea archivos OFX (Open Financial Exchange) de cualquier banco.
    Compatible con OFX 1.x y SGML.
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.GENERIC, account_number="OFX-PARSER")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Parser no requiere conexión."""
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def _parse_ofx_date(self, ofx_date: str) -> str:
        """Convierte fecha OFX (YYYYMMDD o YYYYMMDDHHMMSS) a YYYY-MM-DD."""
        ofx_date = ofx_date.strip()
        if len(ofx_date) >= 8:
            return f"{ofx_date[:4]}-{ofx_date[4:6]}-{ofx_date[6:8]}"
        return ofx_date

    def _determine_transaction_type(self, amount: float, description: str) -> TipoTransaccion:
        """Determina el tipo de transacción basado en el monto y descripción."""
        desc_lower = description.lower()
        if "comision" in desc_lower or "cargo" in desc_lower:
            return TipoTransaccion.COMISION
        if "nomina" in desc_lower or "pago" in desc_lower:
            return TipoTransaccion.PAGO
        if "transferencia" in desc_lower or "spei" in desc_lower:
            return TipoTransaccion.TRANSFERENCIA
        if "deposito" in desc_lower:
            return TipoTransaccion.DEPOSITO
        if "retiro" in desc_lower:
            return TipoTransaccion.RETIRO
        if "cheque" in desc_lower:
            return TipoTransaccion.CHEQUE
        if amount > 0:
            return TipoTransaccion.ABONO
        return TipoTransaccion.CARGO

    def parse_ofx_content(self, content: str) -> BankStatement:
        """Parsea el contenido de un archivo OFX.

        Args:
            content: Contenido del archivo OFX como string.

        Returns:
            BankStatement con las transacciones parseadas.
        """
        logger.info("OFXParser: parseando contenido OFX")

        transactions: List[BankTransaction] = []
        saldo_inicial = 0.0

        # Extraer saldo inicial
        bal_match = re.search(r'<BALANCE>.*?<BALAMT>([\d.,\-]+)', content, re.DOTALL)
        if bal_match:
            saldo_inicial = float(bal_match.group(1).replace(",", ""))

        # Extraer transacciones (STMTTRN)
        trn_pattern = re.compile(
            r'<STMTTRN>(.*?)</STMTTRN>',
            re.DOTALL
        )

        for match in trn_pattern.finditer(content):
            trn_block = match.group(1)

            trntype = self._extract_tag(trn_block, 'TRNTYPE') or 'OTHER'
            dtposted = self._extract_tag(trn_block, 'DTPOSTED') or ''
            trnamt = self._extract_tag(trn_block, 'TRNAMT') or '0'
            fitid = self._extract_tag(trn_block, 'FITID') or ''
            name = self._extract_tag(trn_block, 'NAME') or ''
            memo = self._extract_tag(trn_block, 'MEMO') or ''

            amount = float(trnamt.replace(",", ""))
            description = f"{name} {memo}".strip()

            tx = BankTransaction(
                fecha=self._parse_ofx_date(dtposted[:8]),
                monto=amount,
                descripcion=description,
                referencia=fitid,
                tipo=self._determine_transaction_type(amount, description),
                banco=self.config.bank.value,
                cuenta=self.config.account_number,
            )
            transactions.append(tx)

        statement = BankStatement(
            account_id=self.config.account_number,
            bank=self.config.bank,
            transactions=transactions,
            saldo_inicial=saldo_inicial,
            moneda=self.config.moneda,
        )
        statement.calcular_totales()

        logger.info(f"OFXParser: parseadas {len(transactions)} transacciones")
        return statement

    def _extract_tag(self, block: str, tag: str) -> Optional[str]:
        """Extrae el valor de un tag SGML/XML del bloque OFX."""
        pattern = f'<{tag}>([^<]+)'
        match = re.search(pattern, block)
        return match.group(1).strip() if match else None

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        """Retorna statement vacío (el parsing se hace con parse_ofx_content)."""
        return BankStatement(
            account_id=self.config.account_number,
            bank=self.config.bank,
        )

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        return []

    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        raise NotImplementedError(
            "OFXParser no soporta descarga. Use parse_ofx_content() para parsear."
        )
