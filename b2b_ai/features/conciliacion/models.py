# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Bank Reconciliation module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent bank transactions, accounting entries (pólizas contables),
match results, discrepancies, adjustments, and reconciliation reports
used by accounting auxiliares in Mexico.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TransactionType(str, Enum):
    """Type of bank transaction."""
    INGRESO = "INGRESO"
    EGRESO = "EGRESO"
    TRANSFERENCIA = "TRANSFERENCIA"


class MatchStatus(str, Enum):
    """Status of a match between a bank transaction and a CFDI/póliza."""
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    PARTIAL = "PARTIAL"
    DISCREPANCY = "DISCREPANCY"


class MatchType(str, Enum):
    """Algorithm used to match a bank transaction to a CFDI/póliza."""
    EXACT = "EXACT"
    AMOUNT_DATE = "AMOUNT_DATE"
    PARTIAL_REFERENCE = "PARTIAL_REFERENCE"
    AMOUNT_ONLY = "AMOUNT_ONLY"


class DiscrepancyType(str, Enum):
    """Type of discrepancy found during reconciliation."""
    MONTO = "monto"
    FECHA = "fecha"
    FALTANTE = "faltante"
    SOBRANTE = "sobrante"
    DUPLICADO = "duplicado"


class AdjustmentStatus(str, Enum):
    """Status of a proposed adjustment."""
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


# ---------------------------------------------------------------------------
# Core schemas — Bank Transactions
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


# ---------------------------------------------------------------------------
# Core schemas — CFDI References
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Core schemas — Accounting Entries (Pólizas Contables)
# ---------------------------------------------------------------------------

class PolizaContable(BaseModel):
    """A journal entry (póliza contable) used for reconciliation matching."""
    id: str = Field(..., description="Unique poliza ID")
    fecha: str = Field(
        ...,
        description="Entry date in YYYY-MM-DD format",
    )
    monto: float = Field(
        ...,
        description="Amount of the accounting entry",
    )
    descripcion: str = Field(
        default="",
        description="Description of the accounting entry",
    )
    cuenta: str = Field(
        default="",
        description="Account code (cuenta contable)",
    )
    concepto: str = Field(
        default="",
        description="Concept or concepto contable",
    )
    referencia: str = Field(
        default="",
        description="Reference number for cross-linking",
    )
    rfc: str = Field(
        default="",
        description="RFC associated with this entry",
    )

    @field_validator("monto")
    @classmethod
    def _monto_not_zero(cls, v: float) -> float:
        if v == 0:
            raise ValueError("monto cannot be zero")
        return v


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------

class MatchResult(BaseModel):
    """Result of matching a bank transaction to a CFDI or poliza."""
    bank_transaction_id: str = Field(
        ...,
        description="ID of the matched bank transaction",
    )
    cfdi_uuid: Optional[str] = Field(
        default=None,
        description="UUID of the matched CFDI (None if unmatched)",
    )
    poliza_id: Optional[str] = Field(
        default=None,
        description="ID of the matched poliza contable (None if not matched to poliza)",
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


# ---------------------------------------------------------------------------
# Discrepancy
# ---------------------------------------------------------------------------

class Discrepancy(BaseModel):
    """A discrepancy found during reconciliation."""
    id: str = Field(
        default="",
        description="Unique discrepancy identifier",
    )
    type: DiscrepancyType = Field(
        ...,
        description="Type of discrepancy: monto, fecha, faltante, sobrante, duplicado",
    )
    bank_transaction_id: Optional[str] = Field(
        default=None,
        description="Related bank transaction ID",
    )
    poliza_id: Optional[str] = Field(
        default=None,
        description="Related poliza contable ID",
    )
    cfdi_uuid: Optional[str] = Field(
        default=None,
        description="Related CFDI UUID",
    )
    bank_amount: Optional[float] = Field(
        default=None,
        description="Bank transaction amount",
    )
    poliza_amount: Optional[float] = Field(
        default=None,
        description="Poliza contable amount",
    )
    expected_amount: Optional[float] = Field(
        default=None,
        description="Expected amount for comparison",
    )
    actual_amount: Optional[float] = Field(
        default=None,
        description="Actual amount found",
    )
    variance: Optional[float] = Field(
        default=None,
        description="Percentage variance (0.0 to 100.0)",
    )
    variance_amount: Optional[float] = Field(
        default=None,
        description="Absolute monetary variance",
    )
    date_diff_days: Optional[int] = Field(
        default=None,
        description="Difference in days between bank and poliza dates",
    )
    details: str = Field(
        default="",
        description="Human-readable description of the discrepancy",
    )


# ---------------------------------------------------------------------------
# Adjustment
# ---------------------------------------------------------------------------

class Adjustment(BaseModel):
    """A proposed adjustment to resolve a discrepancy."""
    id: str = Field(
        default="",
        description="Unique adjustment identifier",
    )
    discrepancy_id: str = Field(
        ...,
        description="ID of the discrepancy this adjustment addresses",
    )
    proposal: str = Field(
        ...,
        description="Human-readable description of the proposed adjustment",
    )
    adjustment_type: str = Field(
        default="correction",
        description="Type: correction, void, reclassify, manual_entry",
    )
    journal_entry: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Proposed journal entry (asiento contable) if applicable",
    )
    reason: str = Field(
        default="",
        description="Reason or justification for the adjustment",
    )
    status: AdjustmentStatus = Field(
        default=AdjustmentStatus.PROPOSED,
        description="Current status of the adjustment",
    )
    applied_by: Optional[str] = Field(
        default=None,
        description="User who applied the adjustment",
    )
    applied_at: Optional[str] = Field(
        default=None,
        description="Timestamp when the adjustment was applied (ISO format)",
    )


# ---------------------------------------------------------------------------
# Reconciliation Report
# ---------------------------------------------------------------------------

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
    total_polizas: int = Field(
        default=0,
        description="Total polizas contables considered",
    )
    polizas_matched: int = Field(
        default=0,
        description="Number of polizas matched to bank transactions",
    )
    adjustments_proposed: int = Field(
        default=0,
        description="Number of adjustments proposed",
    )
    adjustments_applied: int = Field(
        default=0,
        description="Number of adjustments already applied",
    )
    total_variance: float = Field(
        default=0.0,
        description="Total monetary variance across all discrepancies",
    )
    details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed match results",
    )
    discrepancy_details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed discrepancy information",
    )
    adjustment_details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed adjustment proposals",
    )
    requires_human_review: bool = Field(default=False, description="Requires human review")
    referencia_legal: Optional[str] = Field(default=None, description="Legal reference (CFF Art)")
    escalation_path: Optional[str] = Field(default=None, description="Escalation path")
