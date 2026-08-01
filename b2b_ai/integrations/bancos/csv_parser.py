# -*- coding: utf-8 -*-
"""
csv_parser.py — Parser universal de estados de cuenta CSV bancarios.

Parsea archivos CSV de cualquier banco mexicano.
"""
from __future__ import annotations

import csv
import io
import logging
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

# Mapeos de columnas comunes en CSV bancarios mexicanos
COLUMN_MAPPINGS = {
    # Español
    "fecha": "fecha",
    "date": "fecha",
    "monto": "monto",
    "amount": "monto",
    "importe": "monto",
    "descripcion": "descripcion",
    "description": "descripcion",
    "concepto": "descripcion",
    "referencia": "referencia",
    "reference": "referencia",
    "folio": "referencia",
    "tipo": "tipo",
    "type": "tipo",
    "movimiento": "tipo",
}


class CSVParser(BankAdapter):
    """Parser universal de archivos CSV bancarios.

    Parsea archivos CSV de cualquier banco mexicano, detectando
    automáticamente el separador y las columnas.
    """

    def __init__(self, config: Optional[BankConfig] = None):
        config = config or BankConfig(bank=Banco.GENERIC, account_number="CSV-PARSER")
        super().__init__(config=config)
        self._column_map: Dict[str, str] = {}

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def _detect_delimiter(self, content: str) -> str:
        """Detecta el delimitador del CSV."""
        first_line = content.split("\n")[0]
        if ";" in first_line:
            return ";"
        if "\t" in first_line:
            return "\t"
        return ","

    def _map_columns(self, headers: List[str]) -> Dict[str, str]:
        """Mapea las columnas del CSV a nombres estándar."""
        mapping = {}
        for i, header in enumerate(headers):
            header_lower = header.strip().lower().strip('"')
            for key, value in COLUMN_MAPPINGS.items():
                if key in header_lower:
                    mapping[value] = i
                    break
        return mapping

    def _determine_transaction_type(self, monto: float, descripcion: str) -> TipoTransaccion:
        """Determina el tipo de transacción."""
        desc_lower = descripcion.lower()
        if "comision" in desc_lower:
            return TipoTransaccion.COMISION
        if "nomina" in desc_lower:
            return TipoTransaccion.PAGO
        if "transferencia" in desc_lower or "spei" in desc_lower:
            return TipoTransaccion.TRANSFERENCIA
        if "deposito" in desc_lower:
            return TipoTransaccion.DEPOSITO
        if "retiro" in desc_lower:
            return TipoTransaccion.RETIRO
        if "cheque" in desc_lower:
            return TipoTransaccion.CHEQUE
        if "interes" in desc_lower:
            return TipoTransaccion.INTERES
        if monto > 0:
            return TipoTransaccion.ABONO
        return TipoTransaccion.CARGO

    def parse_csv_content(self, content: str) -> BankStatement:
        """Parsea el contenido de un archivo CSV bancario.

        Args:
            content: Contenido del archivo CSV como string.

        Returns:
            BankStatement con las transacciones parseadas.
        """
        logger.info("CSVParser: parseando contenido CSV")

        delimiter = self._detect_delimiter(content)
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)

        rows = list(reader)
        if not rows:
            return BankStatement(account_id=self.config.account_number)

        # Detectar encabezados
        headers = rows[0]
        col_map = self._map_columns(headers)

        transactions: List[BankTransaction] = []

        for row in rows[1:]:
            if not row or all(c.strip() == "" for c in row):
                continue

            try:
                fecha = row[col_map.get("fecha", 0)].strip() if "fecha" in col_map else ""
                monto_str = row[col_map.get("monto", 1)].strip().replace(",", "").replace("$", "") if "monto" in col_map else "0"
                monto = float(monto_str) if monto_str else 0.0
                descripcion = row[col_map.get("descripcion", 2)].strip() if "descripcion" in col_map else ""
                referencia = row[col_map.get("referencia", 3)].strip() if "referencia" in col_map and col_map["referencia"] < len(row) else ""

                tx = BankTransaction(
                    fecha=fecha,
                    monto=monto,
                    descripcion=descripcion,
                    referencia=referencia,
                    tipo=self._determine_transaction_type(monto, descripcion),
                    banco=self.config.bank.value,
                    cuenta=self.config.account_number,
                )
                transactions.append(tx)
            except (IndexError, ValueError) as e:
                logger.warning(f"CSVParser: error parseando fila: {e}")
                continue

        statement = BankStatement(
            account_id=self.config.account_number,
            bank=self.config.bank,
            transactions=transactions,
            moneda=self.config.moneda,
        )
        statement.calcular_totales()

        logger.info(f"CSVParser: parseadas {len(transactions)} transacciones")
        return statement

    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        return BankStatement(account_id=self.config.account_number, bank=self.config.bank)

    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        return []

    def download_statement(self, format: FormatoEstado = FormatoEstado.CSV) -> bytes:
        raise NotImplementedError(
            "CSVParser no soporta descarga. Use parse_csv_content() para parsear."
        )
