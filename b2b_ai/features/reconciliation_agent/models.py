# -*- coding: utf-8 -*-
"""
models.py — Data models for the Reconciliation Agent (Agente 1).

Extends the existing conciliacion/models.py with richer types for:
  - Multi-format bank movements (OFX, QIF, MT940, CSV, PDF)
  - 4-level matching with confidence scores
  - Aging alerts and SPEI verification
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MatchLevel(str, Enum):
    """Matching algorithm level."""
    EXACT = "exact"
    FUZZY = "fuzzy"
    MULTI_LINE = "multi_line"
    LLM = "llm"
    MANUAL = "manual"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class BankFormat(str, Enum):
    """Supported bank statement formats."""
    CSV = "csv"
    OFX = "ofx"
    QIF = "qif"
    MT940 = "mt940"
    PDF = "pdf"
    XLSX = "xlsx"


class BancoMX(str, Enum):
    """Supported Mexican banks."""
    BBVA = "bbva"
    BANORTE = "banorte"
    SANTANDER = "santander"
    HSBC = "hsbc"
    CITIBANAMEX = "citibanamex"
    BANREGIO = "banregio"
    SCOTIABANK = "scotiabank"
    GENERIC = "generic"


class MovementType(str, Enum):
    """Type of bank movement."""
    CARGO = "cargo"
    ABONO = "abono"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class BankMovement(BaseModel):
    """A single parsed bank movement from any format/bank."""
    fecha: str = Field(..., description="Date YYYY-MM-DD")
    descripcion: str = Field(default="", description="Movement description")
    referencia: Optional[str] = Field(default=None, description="Bank reference")
    cargo: Optional[float] = Field(default=None, description="Debit amount")
    abono: Optional[float] = Field(default=None, description="Credit amount")
    saldo: Optional[float] = Field(default=None, description="Running balance")
    monto: float = Field(default=0.0, description="Signed amount (abono+, cargo-)")
    banco: str = Field(default="generic", description="Bank identifier")
    formato: str = Field(default="csv", description="Source format")
    raw: Optional[Dict[str, Any]] = Field(default=None, description="Raw parsed data")

    @property
    def monto_abs(self) -> float:
        return abs(self.monto)

    @property
    def naturaleza(self) -> str:
        return "abono" if self.monto >= 0 else "cargo"


class ReconciliationMatch(BaseModel):
    """A match between a bank movement and an accounting record."""
    movement_idx: int = Field(..., description="Index in movements list")
    registro_idx: Optional[int] = Field(default=None, description="Index in records list")
    registro_indices: Optional[List[int]] = Field(default=None, description="Multi-line record indices")
    level: MatchLevel = Field(..., description="Matching algorithm used")
    score: float = Field(..., ge=0, le=100, description="Confidence score 0-100")
    detail: str = Field(default="", description="Human-readable explanation")
    monto_banco: float = Field(default=0.0, description="Bank movement amount")
    monto_registro: float = Field(default=0.0, description="Recorded amount")
    fecha_banco: str = Field(default="", description="Bank movement date")
    fecha_registro: str = Field(default="", description="Record date")


class ReconciliationResult(BaseModel):
    """Complete reconciliation result."""
    matched: List[ReconciliationMatch] = Field(default_factory=list, description="Successful matches")
    unmatched_bank: List[BankMovement] = Field(default_factory=list, description="Bank movements without match")
    unmatched_books: List[Dict[str, Any]] = Field(default_factory=list, description="Book records without match")
    confidence: float = Field(default=0.0, ge=0, le=100, description="Overall confidence score")
    total_movements: int = Field(default=0, description="Total bank movements")
    total_records: int = Field(default=0, description="Total book records")
    total_matched: int = Field(default=0, description="Number of matched items")
    match_rate: float = Field(default=0.0, description="Percentage matched")
    monto_matched: float = Field(default=0.0, description="Total matched amount")
    monto_unmatched_bank: float = Field(default=0.0, description="Unmatched bank amount")
    monto_unmatched_books: float = Field(default=0.0, description="Unmatched books amount")
    processing_time_ms: float = Field(default=0.0, description="Processing time in ms")
    alerts: List[Dict[str, Any]] = Field(default_factory=list, description="Generated alerts")


class AgingAlert(BaseModel):
    """Alert for unreconciled items with aging information."""
    item_type: str = Field(..., description="'bank' or 'book'")
    fecha: str = Field(..., description="Transaction date")
    monto: float = Field(..., description="Amount")
    descripcion: str = Field(default="", description="Description")
    days_unreconciled: int = Field(..., description="Days since transaction")
    severity: AlertSeverity = Field(..., description="Alert severity")
    message: str = Field(..., description="Alert message")
    rule: str = Field(default="", description="Alert rule that triggered")


class SPEIVerificationResult(BaseModel):
    """Result of SPEI payment verification."""
    clave_rastreo: Optional[str] = Field(default=None, description="SPEI tracking key")
    verified: bool = Field(default=False, description="Whether payment was verified")
    status: str = Field(default="unknown", description="Payment status")
    monto: Optional[float] = Field(default=None, description="Verified amount")
    fecha: Optional[str] = Field(default=None, description="Payment date")
    emisor: Optional[str] = Field(default=None, description="Sender info")
    receptor: Optional[str] = Field(default=None, description="Receiver info")
    cep_url: Optional[str] = Field(default=None, description="CEP download URL")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class ReconciliationStatus(BaseModel):
    """Status of a reconciliation job."""
    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(default="pending", description="Job status")
    progress: float = Field(default=0.0, ge=0, le=100, description="Progress percentage")
    result: Optional[ReconciliationResult] = Field(default=None, description="Result if complete")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    error: Optional[str] = Field(default=None, description="Error message if failed")
    bank: str = Field(default="generic", description="Bank used")
    format: str = Field(default="csv", description="File format parsed")
    filename: str = Field(default="", description="Original filename")


class ApprovalRequest(BaseModel):
    """Request to approve a reconciliation match."""
    job_id: str = Field(..., description="Reconciliation job ID")
    match_idx: int = Field(..., description="Index of match to approve")
    approved: bool = Field(True, description="Whether to approve or reject")
    notes: Optional[str] = Field(default=None, description="Approval notes")


class UploadRequest(BaseModel):
    """Parameters for file upload."""
    bank: BancoMX = Field(default=BancoMX.GENERIC, description="Bank identifier")
    format: Optional[BankFormat] = Field(default=None, description="File format (auto-detected if None)")
    date_tolerance_days: int = Field(default=3, ge=0, le=30, description="Date matching tolerance")
    monto_tolerance_pct: float = Field(default=5.0, ge=0, le=50, description="Amount tolerance %")
    fuzzy_threshold: int = Field(default=80, ge=0, le=100, description="Fuzzy matching threshold")
    enable_llm: bool = Field(default=False, description="Enable LLM matching level")
