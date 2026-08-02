# -*- coding: utf-8 -*-
"""
ofx.py — Parser de estados de cuenta OFX/QFX.

Formato OFX (Open Financial Exchange) es el estándar usado por la mayoría de
los bancos mexicanos para exportar estados de cuenta (BBVA, Banorte,
Santander, HSBC exportan .QFX). Es SGML/XML: cada movimiento vive en un bloque
<STMTTRN>...</STMTTRN>.

Estructura de un STMTTRN:
    <STMTTRN>
      <TRNTYPE>CREDIT</TRNTYPE>        ; CREDIT / DEBIT / OTHER
      <DTPOSTED>20250115000000[0:GMT]</DTPOSTED>
      <TRNAMT>1234.56</TRNAMT>         ; positivo para CREDIT, negativo DEBIT
      <FITID>UNIQUE-ID-0001</FITID>    ; id único para dedupe
      <NAME>...</NAME>
      <MEMO>...</MEMO>
    </STMTTRN>

Devuelve objetos RawMovement (forma normalizada) listos para mapear a
Transaction. Tolerante a nombres de tag con / sin espacio en el cierre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# RawMovement — forma intermedia normalizada
# ---------------------------------------------------------------------------


@dataclass
class RawMovement:
    """Movimiento normalizado extraído de un estado de cuenta.

    Los valores son crudos (aún no tipados): amount es str, date es str
    'YYYYMMDD' (formato OFX) o 'YYYY-MM-DD'. El adapter los convierte a
    Transaction.
    """
    external_id: str
    date: str
    amount: str
    description: str = ""
    memo: str = ""
    type_raw: str = ""          # TRNTYPE crudo (CREDIT / DEBIT / OTHER)
    bank_name: str = ""         # nombre del banco si viene en OFX
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "external_id": self.external_id,
            "date": self.date,
            "amount": self.amount,
            "description": self.description,
            "memo": self.memo,
            "type_raw": self.type_raw,
            "bank_name": self.bank_name,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<([A-Z0-9]+)>([^<]*)</\1>", re.IGNORECASE)
_TRN_TYPE_RE = re.compile(r"<TRNTYPE>([^<]+)</TRNTYPE>", re.IGNORECASE)
_DATE_RE = re.compile(r"<DTPOSTED>([0-9]{8})", re.IGNORECASE)
_AMT_RE = re.compile(r"<TRNAMT>([^<]+)</TRNAMT>", re.IGNORECASE)
_FITID_RE = re.compile(r"<FITID>([^<]+)</FITID>", re.IGNORECASE)
_NAME_RE = re.compile(r"<NAME>([^<]+)</NAME>", re.IGNORECASE)
_MEMO_RE = re.compile(r"<MEMO>([^<]+)</MEMO>", re.IGNORECASE)
_BANKID_RE = re.compile(r"<BANKID>([^<]+)</BANKID>", re.IGNORECASE)


def _strip_tags(block: str) -> List[str]:
    """Extrae los nombres de tags presentes en un bloque (para detectar
    TRNTYPE sin valor explícito)."""
    return re.findall(r"<([A-Z0-9]+)[\s/>]", block, re.IGNORECASE)


def parse_ofx(text: str) -> List[RawMovement]:
    """Parsea contenido OFX/QFX y devuelve lista de RawMovement.

    Lanza ValueError si no encuentra ningún STMTTRN (no parece OFX).
    """
    if not text or not text.strip():
        raise ValueError("Contenido OFX vacío")

    # Localiza bloques STMTTRN con regex balanceada: <STMTTRN> ... </STMTTRN>
    stmttrn_blocks = _extract_stmttrn_blocks(text)
    if not stmttrn_blocks:
        raise ValueError("No se encontraron movimientos <STMTTRN> en el OFX")

    bank_name = _first_group(_BANKID_RE, text)
    movements: List[RawMovement] = []

    for block in stmttrn_blocks:
        fitid = _first_group(_FITID_RE, block)
        if not fitid:
            # Si falta FITID usamos un hash determinístico de la fecha+monto.
            date = _first_group(_DATE_RE, block) or "00000000"
            amt = _first_group(_AMT_RE, block) or "0"
            fitid = f"ofx:{date}:{amt}"
        date = _first_group(_DATE_RE, block) or ""
        amount = _first_group(_AMT_RE, block) or "0"
        type_raw = _first_group(_TRN_TYPE_RE, block) or "OTHER"
        name = _first_group(_NAME_RE, block) or ""
        memo = _first_group(_MEMO_RE, block) or ""
        movements.append(
            RawMovement(
                external_id=fitid,
                date=_normalize_date(date),
                amount=amount.strip(),
                description=name.strip(),
                memo=memo.strip(),
                type_raw=type_raw.strip(),
                bank_name=bank_name,
            )
        )

    return movements


def _extract_stmttrn_blocks(text: str) -> List[str]:
    """Extrae bloques <STMTTRN>...</STMTTRN> de forma tolerante a mayúsculas
    y a espacios en el tag de cierre (ej. '</ STMTTRN>' raro)."""
    blocks: List[str] = []
    pattern = re.compile(
        r"<\s*STMTTRN\s*>.*?<\s*/\s*STMTTRN\s*>",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(text):
        blocks.append(m.group(0))
    return blocks


def _first_group(pattern: "re.Pattern", text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _normalize_date(raw: str) -> str:
    """Convierte '20250115' o '2025-01-15' a 'YYYY-MM-DD'."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw
