# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Client Query Response module.

Handles client inquiries about invoices, deductions, FAQs, and
invoice status tracking for Mexican tax compliance.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

# Compliance imports
from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry


class QueryType(str, Enum):
    """Type of client query."""
    FACTURA = "factura"
    DEDUCCION = "deduccion"
    ESTATUS = "estatus"
    PREGUNTA = "pregunta"
    RECLAMO = "reclamo"


class QueryCategory(str, Enum):
    """Category for FAQ classification."""
    FACTURACION = "facturacion"
    IMPUESTOS = "impuestos"
    PAGOS = "pagos"
    GENERAL = "general"
    DEVOLUCIONES = "devoluciones"


class ClientQuery(BaseModel):
    """A client query received for processing."""
    id: Optional[str] = Field(default=None, description="Unique query ID")
    tipo: QueryType = Field(..., description="Type of query: factura, deduccion, estatus, pregunta, reclamo")
    contenido: str = Field(..., description="Content/body of the query")
    tenant_id: str = Field(..., description="Tenant ID of the client")
    cliente_rfc: Optional[str] = Field(default=None, description="RFC of the client asking")
    respuesta: Optional[str] = Field(default=None, description="Generated response (populated after processing)")
    categoria: Optional[QueryCategory] = Field(default=None, description="Auto-classified category")
    prioridad: int = Field(default=3, ge=1, le=5, description="Priority 1=urgent, 5=low")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp of creation")

    @field_validator("contenido")
    @classmethod
    def _contenido_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("contenido no puede estar vacío")
        return v.strip()


class InvoiceStatus(BaseModel):
    """Status of a CFDI invoice."""
    cfdi_id: str = Field(..., description="CFDI UUID or folio fiscal")
    estado: str = Field(default="pendiente", description="Status: pendiente, timbrada, cancelada, rechazada")
    fecha: Optional[str] = Field(default=None, description="Emission date YYYY-MM-DD")
    observaciones: Optional[str] = Field(default=None, description="Notes or observations")
    emisor: Optional[str] = Field(default=None, description="RFC emisor")
    receptor: Optional[str] = Field(default=None, description="RFC receptor")
    total: Optional[float] = Field(default=None, ge=0, description="Invoice total amount")
    regimen_fiscal: Optional[str] = Field(default=None, description="Tax regime code")
    uso_cfdi: Optional[str] = Field(default=None, description="CFDI usage code")
    requires_human_review: bool = Field(default=False, description="Requires human review")
    human_review_reason: Optional[str] = Field(default=None, description="Reason for human review")
    referencia_legal: Optional[str] = Field(default=None, description="Legal reference (CFF Art)")
    supuesto: Optional[str] = Field(default=None, description="Supuesto de aplicación")
    escalation_path: Optional[str] = Field(default=None, description="Escalation path")

    @field_validator("cfdi_id")
    @classmethod
    def _cfdi_id_format(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("cfdi_id no puede estar vacío")
        return v.strip()


class FAQEntry(BaseModel):
    """Frequently asked question entry."""
    id: Optional[str] = Field(default=None, description="Unique FAQ ID")
    question: str = Field(..., description="The question text")
    answer: str = Field(..., description="The answer text")
    category: QueryCategory = Field(default=QueryCategory.GENERAL, description="FAQ category")
    keywords: List[str] = Field(default_factory=list, description="Search keywords")
    tenant_id: Optional[str] = Field(default=None, description="Tenant-specific FAQ (None for global)")

    @field_validator("question")
    @classmethod
    def _question_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question no puede estar vacío")
        return v.strip()

    @field_validator("answer")
    @classmethod
    def _answer_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("answer no puede estar vacío")
        return v.strip()
