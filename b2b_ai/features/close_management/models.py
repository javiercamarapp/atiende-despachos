# -*- coding: utf-8 -*-
"""
models.py — Data models for Close Management Agent (Agente 3).

Defines the CloseChecklist lifecycle:
    pending → in_progress → review → approved → closed

Each step has either automatic validation or human approval.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CloseStepStatus(str, Enum):
    """Lifecycle states for a checklist step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    APPROVED = "approved"
    CLOSED = "closed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ClosePeriodStatus(str, Enum):
    """Overall close period status."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    APPROVED = "approved"
    CLOSED = "closed"


class AdjustmentType(str, Enum):
    """13 automatic adjustment policy types."""
    DEPRECIACION = "depreciacion"
    AMORTIZACION = "amortizacion"
    PROVISION_AGUINALDO = "provision_aguinaldo"
    PROVISION_VACACIONES = "provision_vacaciones"
    PROVISION_PTU = "provision_ptu"
    PROVISION_ISR = "provision_isr"
    PROVISION_IMSS = "provision_imss"
    AJUSTE_INFLACION = "ajuste_inflacion"
    AJUSTE_PREPAGOS = "ajuste_prepagos"
    AJUSTE_INVENTARIOS = "ajuste_inventarios"
    DIFERENCIAS_CAMBIARIAS = "diferencias_cambiarias"
    PROVISION_INCOBRABLES = "provision_incobrables"
    VALUACION_INVERSIONES = "valuacion_inversiones"


class ValidationType(str, Enum):
    """Types of close validations."""
    BALANCE_CUADRADA = "balance_cuadrada"
    IVA_CONCILIADO = "iva_conciliado"
    ISR_PROVISIONADO = "isr_provisionado"
    NOMINA_CUADRADA = "nomina_cuadrada"
    BANCOS_CONCILIADOS = "bancos_conciliados"
    POLIZAS_CUADRADAS = "polizas_cuadradas"
    CFDIS_PROCESADOS = "cfdis_procesados"
    PRE_AUDITORIA = "pre_auditoria"


class ERPType(str, Enum):
    """Supported ERP systems for writing adjustment policies."""
    CONTPAQi = "contpaqi"
    ASPEL = "aspel"
    SAP_B1 = "sap_b1"
    QUICKBOOKS = "quickbooks"
    ODOO = "odoo"
    GENERIC = "generic"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class ChecklistStep(BaseModel):
    """A single step in the close checklist."""
    step: int = Field(..., description="Step number (1-based)")
    name: str = Field(..., description="Human-readable step name")
    status: CloseStepStatus = Field(
        default=CloseStepStatus.PENDING,
        description="Current status",
    )
    is_automatic: bool = Field(
        default=True,
        description="True if auto-validated, False if needs human approval",
    )
    requires_approval: bool = Field(
        default=False,
        description="True if step must be explicitly approved by human",
    )
    detail: Dict[str, Any] = Field(
        default_factory=dict,
        description="Step-specific data (totals, warnings, etc.)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if step failed",
    )
    started_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)
    approved_by: Optional[str] = Field(default=None)
    approval_notes: Optional[str] = Field(default=None)

    def mark_started(self) -> None:
        self.status = CloseStepStatus.IN_PROGRESS
        self.started_at = datetime.utcnow().isoformat()

    def mark_completed(self, detail: Optional[Dict[str, Any]] = None) -> None:
        if self.requires_approval:
            self.status = CloseStepStatus.REVIEW
        else:
            self.status = CloseStepStatus.APPROVED
        if detail is not None:
            self.detail = detail
        self.completed_at = datetime.utcnow().isoformat()

    def mark_failed(self, error: str) -> None:
        self.status = CloseStepStatus.FAILED
        self.error = error
        self.completed_at = datetime.utcnow().isoformat()

    def approve(self, by: str, notes: Optional[str] = None) -> None:
        self.status = CloseStepStatus.APPROVED
        self.approved_by = by
        self.approval_notes = notes

    def skip(self, reason: str = "") -> None:
        self.status = CloseStepStatus.SKIPPED
        self.detail["skip_reason"] = reason


class AdjustmentPolicy(BaseModel):
    """An adjustment policy (póliza de ajuste) generated during close."""
    id: Optional[str] = Field(default=None, description="Unique policy ID")
    type: AdjustmentType = Field(..., description="Adjustment type")
    periodo: str = Field(..., description="Period YYYY-MM")
    tenant_id: Optional[int] = Field(default=None)
    description: str = Field(default="", description="Human description")
    entries: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Journal entries: [{cuenta, debe, haber, concepto}]",
    )
    total_debe: float = Field(default=0.0)
    total_haber: float = Field(default=0.0)
    is_balanced: bool = Field(default=False, description="debe == haber")
    erp_written: bool = Field(default=False)
    erp_reference: Optional[str] = Field(default=None)
    status: str = Field(default="draft", description="draft|posted|error")
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
    )
    posted_at: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)


class ValidationResult(BaseModel):
    """Result of a close validation check."""
    type: ValidationType = Field(..., description="Validation type")
    passed: bool = Field(..., description="Whether validation passed")
    message: str = Field(default="", description="Human-readable message")
    details: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class ClosePeriod(BaseModel):
    """A monthly close period — the main aggregate."""
    id: Optional[str] = Field(default=None, description="Unique close ID")
    periodo: str = Field(..., description="Period YYYY-MM")
    tenant_id: Optional[int] = Field(default=None)
    rfc: str = Field(default="", description="Tax ID")
    status: ClosePeriodStatus = Field(default=ClosePeriodStatus.NOT_STARTED)
    steps: List[ChecklistStep] = Field(default_factory=list)
    adjustments: List[AdjustmentPolicy] = Field(default_factory=list)
    validations: List[ValidationResult] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
    )
    closed_at: Optional[str] = Field(default=None)
    closed_by: Optional[str] = Field(default=None)

    @property
    def completed_steps(self) -> int:
        return sum(
            1 for s in self.steps
            if s.status in (
                CloseStepStatus.APPROVED,
                CloseStepStatus.CLOSED,
                CloseStepStatus.SKIPPED,
            )
        )

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def progress_pct(self) -> float:
        if not self.steps:
            return 0.0
        return round(self.completed_steps / self.total_steps * 100, 1)

    @property
    def all_validations_passed(self) -> bool:
        return all(v.passed for v in self.validations)

    def update_summary(self) -> None:
        self.summary = {
            "periodo": self.periodo,
            "total_steps": self.total_steps,
            "completed": self.completed_steps,
            "pending": sum(
                1 for s in self.steps
                if s.status == CloseStepStatus.PENDING
            ),
            "in_progress": sum(
                1 for s in self.steps
                if s.status == CloseStepStatus.IN_PROGRESS
            ),
            "review": sum(
                1 for s in self.steps
                if s.status == CloseStepStatus.REVIEW
            ),
            "failed": sum(
                1 for s in self.steps
                if s.status == CloseStepStatus.FAILED
            ),
            "skipped": sum(
                1 for s in self.steps
                if s.status == CloseStepStatus.SKIPPED
            ),
            "progress_pct": self.progress_pct,
            "adjustments_count": len(self.adjustments),
            "adjustments_balanced": sum(
                1 for a in self.adjustments if a.is_balanced
            ),
            "validations_passed": sum(
                1 for v in self.validations if v.passed
            ),
            "validations_total": len(self.validations),
            "requires_human_review": any(
                s.requires_approval
                and s.status in (
                    CloseStepStatus.PENDING,
                    CloseStepStatus.REVIEW,
                )
                for s in self.steps
            ),
            "all_validations_passed": self.all_validations_passed,
        }
        self.updated_at = datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# API request/response schemas
# ---------------------------------------------------------------------------

class CloseStartRequest(BaseModel):
    """Request to start a monthly close."""
    periodo: str = Field(
        ...,
        description="Period YYYY-MM",
        pattern=r"^\d{4}-\d{2}$",
    )
    tenant_id: Optional[int] = Field(default=None)
    rfc: str = Field(default="")
    auto_approve: bool = Field(
        default=False,
        description="Auto-approve automatic steps",
    )


class CloseApproveStepRequest(BaseModel):
    """Request to approve a specific step."""
    close_id: str = Field(..., description="Close period ID")
    step: int = Field(..., description="Step number")
    approved: bool = Field(default=True)
    notes: Optional[str] = Field(default=None)
    approved_by: str = Field(default="contador")


class CloseFinalizeRequest(BaseModel):
    """Request to finalize (close) a period."""
    close_id: str = Field(..., description="Close period ID")
    closed_by: str = Field(default="contador")
    force: bool = Field(
        default=False,
        description="Force close even if validations fail",
    )
