# -*- coding: utf-8 -*-
"""
parsers.py — BankStatementParser: multi-format parser for Mexican bank statements.

Supports:
  - CSV (all banks, auto-detect delimiter)
  - OFX (Citibanamex, Scotiabank, Banorte)
  - QIF (Banregio, HSBC)
  - MT940 (HSBC, Santander)
  - PDF via pdfplumber (BBVA, Banorte, Santander, HSBC, Citibanamex, Banregio, Scotiabank)

Extends the existing parsers in b2b_ai.services.reconcile (CSV/PDF) and
b2b_ai.integrations.bancos.ofx_parser (OFX).
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from b2b_ai.features.reconciliation_agent.models import (
    BankFormat,
    BankMovement,
    BancoMX,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dec(v) -> Optional[float]:
    """Convert to float tolerantly."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace(" ", "")
    if s in ("", "-", "--", "N/A", "n/a"):
        return None
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(s: str) -> Optional[str]:
    """Try multiple date formats, return YYYY-MM-DD or None."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y",
                "%Y/%m/%d", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y",
                "%Y%m%d", "%d.%m.%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _detect_format(file_path: str) -> BankFormat:
    """Auto-detect file format from extension."""
    lower = file_path.lower()
    if lower.endswith(".ofx"):
        return BankFormat.OFX
    if lower.endswith(".qif"):
        return BankFormat.QIF
    if lower.endswith(".mt940") or lower.endswith(".sta"):
        return BankFormat.MT940
    if lower.endswith(".pdf"):
        return BankFormat.PDF
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return BankFormat.XLSX
    return BankFormat.CSV


# ---------------------------------------------------------------------------
# Bank Profiles — column mappings per bank
# ---------------------------------------------------------------------------

BANK_PROFILES: Dict[str, Dict[str, Any]] = {
    "bbva": {
        "csv_delimiter": ";",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "abono", "cargo", "saldo"],
    },
    "banorte": {
        "csv_delimiter": ";",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "depositos", "retiros", "saldo"],
    },
    "santander": {
        "csv_delimiter": ";",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "abono", "cargo", "saldo"],
        "decimal_sep": ",",  # Santander uses . for thousands, , for decimal
    },
    "hsbc": {
        "csv_delimiter": ",",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "monto", "saldo"],
    },
    "citibanamex": {
        "csv_delimiter": ",",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "cargo", "abono", "saldo"],
    },
    "banregio": {
        "csv_delimiter": ";",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "abono", "cargo", "saldo"],
    },
    "scotiabank": {
        "csv_delimiter": ",",
        "pdf_column_order": ["fecha", "descripcion", "referencia", "depositos", "retiros", "saldo"],
    },
}


# ---------------------------------------------------------------------------
# Column recognition sets
# ---------------------------------------------------------------------------

_COL_FECHA = {"fecha", "fecha operacion", "fecha operación", "fecha de operacion",
              "fecha valor", "fecha de pago", "date", "dia", "fecha movimiento",
              "fec", "fecha oper"}
_COL_DESCR = {"descripcion", "descripción", "concepto", "detalle", "referencia",
              "referencia (descripcion)", "desc", "description", "movimiento",
              "detalle del movimiento", "concepto/descripción", "glosa"}
_COL_REF = {"referencia", "ref", "referencia1", "folio", "clave de rastreo",
            "clave rastreo", "numero de referencia", "nº de referencia",
            "num referencia", "referencia operación"}
_COL_CARGO = {"cargo", "cargos", "debito", "débito", "debe", "retiro", "retiros",
              "salida", "abono cargo"}
_COL_ABONO = {"abono", "abonos", "credito", "crédito", "haber", "deposito",
              "depósitos", "depositos", "entrada", "abono credito"}
_COL_MONTO = {"monto", "importe", "cantidad", "valor", "amount", "saldo movimiento"}
_COL_SALDO = {"saldo", "balance", "saldo final"}


def _header_index(headers: List[str], accepted: set) -> Optional[int]:
    for i, h in enumerate(headers):
        if h.strip().lower() in accepted:
            return i
    return None


# ---------------------------------------------------------------------------
# Main Parser
# ---------------------------------------------------------------------------

class BankStatementParser:
    """Multi-format parser for Mexican bank statements.

    Usage:
        parser = BankStatementParser()
        movements = parser.parse("estado_cuenta.csv", bank="bbva")
        movements = parser.parse("estado_cuenta.ofx", bank="citibanamex")
        movements = parser.parse("estado_cuenta.pdf", bank="banorte")
    """

    def parse(
        self,
        file_path: str,
        bank: str = "generic",
        format_hint: Optional[str] = None,
    ) -> List[BankMovement]:
        """Parse a bank statement file into normalized movements.

        Args:
            file_path: Path to the bank statement file.
            bank: Bank identifier (bbva, banorte, santander, etc.)
            format_hint: Force a specific format (csv, ofx, qif, mt940, pdf)

        Returns:
            List of BankMovement objects.
        """
        bank = self._normalize_bank(bank)
        fmt = BankFormat(format_hint) if format_hint else _detect_format(file_path)

        parser_map = {
            BankFormat.CSV: self._parse_csv,
            BankFormat.OFX: self._parse_ofx,
            BankFormat.QIF: self._parse_qif,
            BankFormat.MT940: self._parse_mt940,
            BankFormat.PDF: self._parse_pdf,
        }

        parser_fn = parser_map.get(fmt)
        if parser_fn is None:
            raise ValueError(f"Formato no soportado: {fmt.value}")

        movements = parser_fn(file_path, bank)
        # Enrich with metadata
        for m in movements:
            m.banco = bank
            m.formato = fmt.value
        return movements

    @staticmethod
    def _normalize_bank(bank: str) -> str:
        b = (bank or "generic").strip().lower().replace(" ", "_")
        for key in BancoMX.__members__.values():
            if key.value == b or key.value in b:
                return key.value
        return "generic"

    # ------------------------------------------------------------------
    # CSV Parser (extends reconcile.parse_bank_statement_csv)
    # ------------------------------------------------------------------

    def _parse_csv(self, file_path: str, bank: str) -> List[BankMovement]:
        """Parse CSV bank statement. Extends the existing reconcile parser."""
        try:
            with open(file_path, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as fh:
                raw = fh.read()

        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return []

        delim = self._sniff_delimiter(lines)
        profile = BANK_PROFILES.get(bank, {})
        if profile.get("csv_delimiter"):
            delim = profile["csv_delimiter"]

        rows = []
        for ln in lines:
            try:
                rows.append(next(csv.reader([ln], delimiter=delim)))
            except Exception:
                continue

        # Find header row
        header_idx = 0
        for i, r in enumerate(rows):
            low = {c.strip().lower() for c in r if str(c).strip()}
            if low & _COL_FECHA or low & _COL_CARGO or low & _COL_ABONO:
                header_idx = i
                break

        headers = [str(c).strip().lower() for c in rows[header_idx]]
        i_fecha = _header_index(headers, _COL_FECHA)
        i_desc = _header_index(headers, _COL_DESCR)
        i_ref = _header_index(headers, _COL_REF)
        i_cargo = _header_index(headers, _COL_CARGO)
        i_abono = _header_index(headers, _COL_ABONO)
        i_monto = _header_index(headers, _COL_MONTO)
        i_saldo = _header_index(headers, _COL_SALDO)

        # Don't confuse reference column with description
        if i_ref is None and i_desc is not None and headers[i_desc] in _COL_REF:
            i_ref = i_desc
            i_desc = None

        movements = []
        for r in rows[header_idx + 1:]:
            if i_fecha is not None and len(r) <= i_fecha:
                continue
            if not any(str(c).strip() for c in r):
                continue

            fecha_raw = r[i_fecha].strip() if i_fecha is not None and len(r) > i_fecha else None
            fecha = _parse_date(fecha_raw)
            if fecha is None:
                continue

            descripcion = r[i_desc].strip() if i_desc is not None and len(r) > i_desc else ""
            ref = r[i_ref].strip() if i_ref is not None and len(r) > i_ref else ""

            # Monto calculation
            cargo = _dec(r[i_cargo]) if i_cargo is not None and len(r) > i_cargo else None
            abono = _dec(r[i_abono]) if i_abono is not None and len(r) > i_abono else None
            saldo = _dec(r[i_saldo]) if i_saldo is not None and len(r) > i_saldo else None

            if cargo is None and abono is None and i_monto is not None and len(r) > i_monto:
                monto_raw = _dec(r[i_monto])
                if monto_raw is not None:
                    if monto_raw < 0:
                        cargo = abs(monto_raw)
                    else:
                        abono = monto_raw

            monto = (abono or 0) - (cargo or 0)
            if cargo is None and abono is None:
                continue

            movements.append(BankMovement(
                fecha=fecha,
                descripcion=descripcion,
                referencia=ref or None,
                cargo=cargo,
                abono=abono,
                saldo=saldo,
                monto=monto,
                banco=bank,
                formato="csv",
            ))

        return movements

    @staticmethod
    def _sniff_delimiter(lines: List[str]) -> str:
        from collections import Counter
        counts: Counter = Counter()
        for ln in lines[:20]:  # Sample first 20 lines
            for d in ("\t", ";", ","):
                counts[d] += ln.count(d)
        if not counts:
            return ","
        best = max(("\t", ";", ","), key=lambda d: counts.get(d, 0))
        return best if counts.get(best, 0) > 0 else ","

    # ------------------------------------------------------------------
    # OFX Parser (extends integrations.bancos.ofx_parser)
    # ------------------------------------------------------------------

    def _parse_ofx(self, file_path: str, bank: str) -> List[BankMovement]:
        """Parse OFX (Open Financial Exchange) files."""
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as fh:
                content = fh.read()

        return self._parse_ofx_content(content, bank)

    def _parse_ofx_content(self, content: str, bank: str) -> List[BankMovement]:
        """Parse OFX content string into movements."""
        movements = []

        # OFX 1.x uses SGML-like tags; OFX 2.x uses XML.
        # Parse the transaction list block.
        # Pattern for STMTTRN (statement transaction) blocks
        trn_pattern = re.compile(
            r"<STMTTRN>(.*?)</?STMTTRN>",
            re.DOTALL | re.IGNORECASE
        )
        # Also handle SGML (no closing tags)
        if not trn_pattern.search(content):
            trn_pattern = re.compile(
                r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)",
                re.DOTALL | re.IGNORECASE
            )

        for match in trn_pattern.finditer(content):
            block = match.group(1)
            trn_type = self._ofx_tag(block, "TRNTYPE")
            posted = self._ofx_tag(block, "DTPOSTED")
            amount_str = self._ofx_tag(block, "TRNAMT")
            fitid = self._ofx_tag(block, "FITID")
            memo = self._ofx_tag(block, "MEMO")
            name = self._ofx_tag(block, "NAME")
            checknum = self._ofx_tag(block, "CHECKNUM")

            fecha = self._parse_ofx_date(posted) if posted else None
            amount = _dec(amount_str)
            descripcion = (name or memo or "").strip()
            referencia = fitid or checknum or None

            if fecha is None or amount is None:
                continue

            cargo = abs(amount) if amount < 0 else None
            abono = amount if amount >= 0 else None

            movements.append(BankMovement(
                fecha=fecha,
                descripcion=descripcion,
                referencia=referencia,
                cargo=cargo,
                abono=abono,
                monto=amount,
                banco=bank,
                formato="ofx",
            ))

        return movements

    @staticmethod
    def _ofx_tag(block: str, tag: str) -> Optional[str]:
        """Extract value of an OFX tag from a block."""
        m = re.search(rf"<{tag}>\s*(.+?)(?:\s*<|$)", block, re.IGNORECASE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _parse_ofx_date(d: str) -> Optional[str]:
        """Convert OFX date (YYYYMMDD or YYYYMMDDHHMMSS) to YYYY-MM-DD."""
        d = d.strip().rstrip("[]")  # Remove timezone brackets
        if len(d) >= 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return None

    # ------------------------------------------------------------------
    # QIF Parser
    # ------------------------------------------------------------------

    def _parse_qif(self, file_path: str, bank: str) -> List[BankMovement]:
        """Parse QIF (Quicken Interchange Format) files.

        QIF format:
            D01/07/2026
            T-1500.00
            PMercado Pago
            MTransferencia SPEI
            N123456
            ^
        """
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as fh:
                content = fh.read()

        return self._parse_qif_content(content, bank)

    def _parse_qif_content(self, content: str, bank: str) -> List[BankMovement]:
        """Parse QIF content string."""
        movements = []
        # Split into transactions by ^
        transactions = content.split("^")
        current_type = "Bank"  # Default

        # Check for header
        first_line = content.strip().split("\n")[0].strip()
        if first_line.startswith("!"):
            type_map = {
                "!Type:Bank": "Bank",
                "!Type:Cash": "Cash",
                "!Type:CCard": "CCard",
            }
            current_type = type_map.get(first_line, "Bank")
            # Remove header from first transaction
            content = content[content.index("\n") + 1:]
            transactions = content.split("^")

        for txn_text in transactions:
            lines = txn_text.strip().split("\n")
            if not lines or not any(l.strip() for l in lines):
                continue

            fecha = None
            monto = None
            descripcion = ""
            referencia = None
            memo = ""

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                code = line[0]
                value = line[1:].strip()

                if code == "D":  # Date
                    fecha = _parse_date(value)
                elif code == "T":  # Amount
                    monto = _dec(value)
                elif code == "P":  # Payee
                    descripcion = value
                elif code == "M":  # Memo
                    memo = value
                elif code == "N":  # Number (check/reference)
                    referencia = value
                elif code == "L":  # Category
                    if not descripcion:
                        descripcion = value

            if memo and descripcion:
                descripcion = f"{descripcion} {memo}".strip()
            elif memo:
                descripcion = memo

            if fecha and monto is not None:
                cargo = abs(monto) if monto < 0 else None
                abono = monto if monto >= 0 else None
                movements.append(BankMovement(
                    fecha=fecha,
                    descripcion=descripcion,
                    referencia=referencia,
                    cargo=cargo,
                    abono=abono,
                    monto=monto,
                    banco=bank,
                    formato="qif",
                ))

        return movements

    # ------------------------------------------------------------------
    # MT940 Parser
    # ------------------------------------------------------------------

    def _parse_mt940(self, file_path: str, bank: str) -> List[BankMovement]:
        """Parse MT940 (SWIFT format) bank statements.

        MT940 fields:
            :61: — Transaction details (date, amount, type)
            :86: — Information to account owner (description)
        """
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as fh:
                content = fh.read()

        return self._parse_mt940_content(content, bank)

    def _parse_mt940_content(self, content: str, bank: str) -> List[BankMovement]:
        """Parse MT940 content."""
        movements = []
        lines = content.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # :61: line contains date and amount
            if line.startswith(":61:") or (i > 0 and lines[i-1].strip().endswith(":61:")):
                data_line = line if line.startswith(":61:") else line
                if not data_line.startswith(":61:"):
                    i += 1
                    continue
                data = data_line[4:].strip()

                # Parse :61: field
                # Format: YYMMDD[CCYYMMDD]DCamount[SWIFT code]
                # D = debit, C = credit
                movement = self._parse_mt940_61(data)
                if movement is None:
                    i += 1
                    continue

                # Look for :86: on next line(s) for description
                descripcion = ""
                j = i + 1
                while j < len(lines) and j < i + 5:
                    next_line = lines[j].strip()
                    if next_line.startswith(":86:"):
                        descripcion = next_line[4:].strip()
                        # Handle continuation lines
                        k = j + 1
                        while k < len(lines) and not lines[k].strip().startswith(":"):
                            cont = lines[k].strip()
                            if cont:
                                descripcion += " " + cont
                            k += 1
                        break
                    elif next_line.startswith(":61:") or next_line.startswith(":62"):
                        break
                    j += 1

                movement.descripcion = descripcion.strip()
                movements.append(movement)

            i += 1

        return movements

    def _parse_mt940_61(self, data: str) -> Optional[BankMovement]:
        """Parse a :61: field in MT940 format.

        Format: YYMMDD[+/-N]DCAMOUNT[//reference]
        Example: 260715D1500,00NTRF
        """
        # Date (first 6 chars: YYMMDD)
        if len(data) < 10:
            return None
        yy = data[0:2]
        mm = data[2:4]
        dd = data[4:6]
        year = int(yy) + 2000 if int(yy) < 80 else int(yy) + 1900
        fecha = f"{year}-{mm}-{dd}"

        # Value date offset (optional +N or -N)
        idx = 6
        if idx < len(data) and data[idx] in ("+", "-"):
            idx += 2  # skip sign + 1 digit

        # Debit/Credit indicator
        if idx >= len(data):
            return None
        dc = data[idx].upper()
        idx += 1

        # Skip 'N' or 'F' (notional/financial indicator)
        if idx < len(data) and data[idx] in ("N", "F", "R"):
            idx += 1

        # Amount (digits, comma for decimal)
        amount_match = re.match(r"([\d,\.]+)", data[idx:])
        if not amount_match:
            return None
        amount_str = amount_match.group(1).replace(",", ".")
        amount = _dec(amount_str)
        if amount is None:
            return None

        # D = debit, C = credit
        if dc == "D":
            monto = -abs(amount)
        else:
            monto = abs(amount)

        cargo = abs(amount) if dc == "D" else None
        abono = amount if dc == "C" else None

        # Reference (after amount)
        ref = data[idx + len(amount_match.group(0)):].strip()
        referencia = ref.lstrip("/").strip() or None

        return BankMovement(
            fecha=fecha,
            descripcion="",
            referencia=referencia,
            cargo=cargo,
            abono=abono,
            monto=monto,
            formato="mt940",
        )

    # ------------------------------------------------------------------
    # PDF Parser (uses pdfplumber, extends reconcile.parse_bank_statement_pdf)
    # ------------------------------------------------------------------

    def _parse_pdf(self, file_path: str, bank: str) -> List[BankMovement]:
        """Parse PDF bank statements using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            raise ValueError(
                "pdfplumber no está instalado. Instala con: pip install pdfplumber"
            )

        movements = []
        profile = BANK_PROFILES.get(bank, {})
        col_order = profile.get("pdf_column_order", [])

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    page_movs = self._parse_pdf_table(table, bank, col_order)
                    movements.extend(page_movs)

                # Fallback: if no tables found, try text extraction
                if not tables:
                    text = page.extract_text() or ""
                    text_movs = self._parse_text_movements(text, bank)
                    movements.extend(text_movs)

        return movements

    def _parse_pdf_table(
        self, table: List[List], bank: str, col_order: List[str]
    ) -> List[BankMovement]:
        """Parse a table extracted from a PDF page."""
        movements = []
        if not table:
            return movements

        # Detect header row
        header_idx = 0
        for i, row in enumerate(table):
            if row and any(str(c or "").strip().lower() in _COL_FECHA for c in row):
                header_idx = i
                break

        headers = [str(c or "").strip().lower() for c in table[header_idx]]
        i_fecha = _header_index(headers, _COL_FECHA)
        i_desc = _header_index(headers, _COL_DESCR)
        i_ref = _header_index(headers, _COL_REF)
        i_cargo = _header_index(headers, _COL_CARGO)
        i_abono = _header_index(headers, _COL_ABONO)
        i_monto = _header_index(headers, _COL_MONTO)
        i_saldo = _header_index(headers, _COL_SALDO)

        # If headers not found, try using column_order from bank profile
        if i_fecha is None and col_order:
            return self._parse_pdf_table_with_profile(table, bank, col_order)

        for row in table[header_idx + 1:]:
            if not row or not any(str(c or "").strip() for c in row):
                continue

            fecha_raw = str(row[i_fecha] or "").strip() if i_fecha is not None and len(row) > i_fecha else None
            fecha = _parse_date(fecha_raw)
            if fecha is None:
                # Skip header-like or empty rows
                continue

            descripcion = str(row[i_desc] or "").strip() if i_desc is not None and len(row) > i_desc else ""
            ref = str(row[i_ref] or "").strip() if i_ref is not None and len(row) > i_ref else None

            cargo = _dec(row[i_cargo]) if i_cargo is not None and len(row) > i_cargo else None
            abono = _dec(row[i_abono]) if i_abono is not None and len(row) > i_abono else None
            saldo = _dec(row[i_saldo]) if i_saldo is not None and len(row) > i_saldo else None

            if cargo is None and abono is None and i_monto is not None and len(row) > i_monto:
                monto_raw = _dec(row[i_monto])
                if monto_raw is not None:
                    if monto_raw < 0:
                        cargo = abs(monto_raw)
                    else:
                        abono = monto_raw

            if cargo is None and abono is None:
                continue

            monto = (abono or 0) - (cargo or 0)

            movements.append(BankMovement(
                fecha=fecha,
                descripcion=descripcion,
                referencia=ref,
                cargo=cargo,
                abono=abono,
                saldo=saldo,
                monto=monto,
            ))

        return movements

    def _parse_pdf_table_with_profile(
        self, table: List[List], bank: str, col_order: List[str]
    ) -> List[BankMovement]:
        """Parse PDF table using bank profile column order."""
        movements = []
        # Find the first row that looks like data (starts with a date)
        date_re = re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")

        for row in table:
            if not row or not row[0]:
                continue
            first = str(row[0]).strip()
            if not date_re.match(first):
                continue

            fecha = _parse_date(first)
            if fecha is None:
                continue

            values = {col_order[i]: str(row[i] or "").strip()
                      for i in range(min(len(col_order), len(row)))}

            descripcion = values.get("descripcion", "")
            ref = values.get("referencia", "") or None

            cargo = _dec(values.get("cargo")) or _dec(values.get("retiros"))
            abono = _dec(values.get("abono")) or _dec(values.get("depositos"))
            saldo = _dec(values.get("saldo"))
            monto_val = _dec(values.get("monto"))

            if cargo is None and abono is None:
                if monto_val is not None:
                    if monto_val < 0:
                        cargo = abs(monto_val)
                    else:
                        abono = monto_val
                else:
                    continue

            monto = (abono or 0) - (cargo or 0)

            movements.append(BankMovement(
                fecha=fecha,
                descripcion=descripcion,
                referencia=ref,
                cargo=cargo,
                abono=abono,
                saldo=saldo,
                monto=monto,
            ))

        return movements

    def _parse_text_movements(self, text: str, bank: str) -> List[BankMovement]:
        """Fallback: parse movements from raw PDF text."""
        movements = []
        pat = re.compile(
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})"
            r"\s+"
            r"([+-]?[\d,]+\.?\d*|[\d,]+\.?\d*)"
            r"(?:\s+([+-]?[\d,]+\.?\d*))?"
            r"\s+(.*)",
            re.IGNORECASE,
        )
        for line in text.splitlines():
            m = pat.search(line)
            if not m:
                continue
            fecha = _parse_date(m.group(1))
            if fecha is None:
                continue
            m1 = _dec(m.group(2))
            m2 = _dec(m.group(3))
            desc = m.group(4).strip()

            if m2 is not None and m2 != 0:
                monto = m2
            else:
                monto = m1 or 0

            cargo = abs(monto) if monto < 0 else None
            abono = monto if monto >= 0 else None

            movements.append(BankMovement(
                fecha=fecha,
                descripcion=desc,
                referencia=re.search(r"REF[- ]?[0-9A-Z]+", desc, re.IGNORECASE).group(0)
                if re.search(r"REF[- ]?[0-9A-Z]+", desc, re.IGNORECASE) else None,
                cargo=cargo,
                abono=abono,
                monto=monto,
            ))

        return movements
