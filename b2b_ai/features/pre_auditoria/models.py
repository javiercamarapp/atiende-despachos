# -*- coding: utf-8 -*-
"""
models.py — Modelos de Pre-Auditoría Contable.

AuditFinding   — Hallazgo individual con severidad y recomendación.
AuditReport    — Reporte completo de una pre-auditoría.
DeductibilityCheck — Resultado de verificación de deducibilidad de un gasto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AuditFinding:
    """Hallazgo de auditoría con severidad y recomendación."""

    category: str = ""
    severity: Severity = Severity.LOW
    description: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "description": self.description,
            "recommendation": self.recommendation,
        }


@dataclass
class DeductibilityCheck:
    """Resultado de verificación de deducibilidad de una factura."""

    invoice_id: str = ""
    concepto: str = ""
    es_deducible: bool = True
    razon: str = ""
    articulo_cff: str = ""

    def to_dict(self) -> dict:
        return {
            "invoice_id": self.invoice_id,
            "concepto": self.concepto,
            "es_deducible": self.es_deducible,
            "razon": self.razon,
            "articulo_cff": self.articulo_cff,
        }


@dataclass
class AuditReport:
    """Reporte completo de una pre-auditoría."""

    period: str = ""
    tenant_id: Optional[int] = None
    findings: list[AuditFinding] = field(default_factory=list)
    score: float = 100.0
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "tenant_id": self.tenant_id,
            "findings": [f.to_dict() for f in self.findings],
            "score": self.score,
            "summary": self.summary,
        }
