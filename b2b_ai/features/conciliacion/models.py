# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Bank Reconciliation module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent bank transactions, CFDI references, match results,
and reconciliation reports used by accounting auxiliares in Mexico.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TransactionType(str, Enum):
    """Type of bank transaction."""
    INGRESO = "INGRESO"
    EGRESO = "EGRESO"
    TRANSFERENCIA = "TRANSFERENCIA"


class MatchStatus(str, Enum):
    """Status of a match between a bank transaction and a CFDI."""
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    PARTIAL = "PARTIAL"
    DISCREPANCY = "DISCREPANCY"


class MatchType(str, Enum):
    """Algorithm used to match a bank transaction to a CFDI."""
    EXACT = "EXACT"
    AMOUNT_DATE = "AMOUNT_DATE"
    PARTIAL_REFERENCE = "PARTIAL_REFERENCE"


# ---------------------------------------------------------------------------
# Core schemas
# ---------------------------------------------------------------------------

class BankTransaction(BaseModel):
    """A single transaction from a bank statement (estado de cuenta)."""
    id: str = Field(..., description="Unique transaction ID from the bank")
    date: str = Field(
        ...,
        description="Transaction date in YYYY-MM-DD format",
    )
    description: str = Field(
        default="",
        description="Transaction description from the bank",
    )
    amount: float = Field(
        ...,
        description="Transaction amount (positive for income, negative for expenses)",
    )
    type: TransactionType = Field(
        ...,
        description="Transaction type: INGRESO, EGRESO, or TRANSFERENCIA",
    )
    reference: str = Field(
        default="",
        description="Bank reference number or UUID",
    )
    bank_account: str = Field(
        default="",
        description="Bank account identifier (last 4 digits or CLABE)",
    )

    @field_validator("amount")
    @classmethod
    def _amount_not_zero(cls, v: float) -> float:
        if v == 0:
            raise ValueError("amount cannot be zero")
        return v


class CFDIReference(BaseModel):
    """A CFDI (invoice) reference used for reconciliation matching."""
    uuid: str = Field(
        ...,
        description="UUID del CFDI (UUID del Timbre Fiscal Digital)",
    )
    fecha: str = Field(
        ...,
        description="Fecha de emisión del CFDI in YYYY-MM-DD format",
    )
    rfc_emisor: str = Field(
        ...,
        description="RFC del emisor (issuer) of the CFDI",
    )
    rfc_receptor: str = Field(
        ...,
        description="RFC del receptor (recipient) of the CFDI",
    )
    total: float = Field(
        ...,
        description="Total amount of the CFDI (with taxes)",
    )
    tipo_comprobante: str = Field(
        default="I",
        description="Tipo de comprobante: I=Ingreso, E=Egreso, T=Traslado, N=Nómina",
    )


class MatchResult(BaseModel):
    """Result of matching a bank transaction to a CFDI."""
    bank_transaction_id: str = Field(
        ...,
        description="ID of the matched bank transaction",
    )
    cfdi_uuid: Optional[str] = Field(
        default=None,
        description="UUID of the matched CFDI (None if unmatched)",
    )
    match_type: MatchType = Field(
        default=MatchType.EXACT,
        description="Algorithm used for the match",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the match (0.0 to 1.0)",
    )
    status: MatchStatus = Field(
        default=MatchStatus.MATCHED,
        description="Status of the match",
    )


class ConciliationReport(BaseModel):
    """Summary report of a reconciliation run."""
    period: str = Field(
        ...,
        description="Period covered by the report (e.g. '2024-01')",
    )
    total_transactions: int = Field(
        default=0,
        description="Total bank transactions processed",
    )
    matched: int = Field(
        default=0,
        description="Number of transactions matched to CFDI",
    )
    unmatched: int = Field(
        default=0,
        description="Number of transactions without a match",
    )
    discrepancies: int = Field(
        default=0,
        description="Number of matches with amount discrepancies >2%",
    )
    match_rate: float = Field(
        default=0.0,
        description="Match rate as a percentage (0.0 to 100.0)",
    )
    details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed match results",
    )
    discrepancy_details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed discrepancy information",
    )
