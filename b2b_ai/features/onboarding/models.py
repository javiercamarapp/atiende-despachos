# -*- coding: utf-8 -*-
"""models.py — Modelos Pydantic del Onboarding Wizard del piloto (Día 1).

Define los tres tipos centrales:

    OnboardingStep   — los 5 pasos del flujo (orden secuencial estricto).
    OnboardingStatus — estado global de una sesión de onboarding.
    OnboardingSession— la sesión persistente (tenant + progreso + datos).

Convenciones del proyecto (pydantic v2, Field con description) y del módulo
`multi_tenant`: aislamiento por tenant y timestamps ISO UTC.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pasos del flujo
# ---------------------------------------------------------------------------

class OnboardingStep(str, Enum):
    """Los 5 pasos del onboarding del piloto, en orden estricto."""
    TENANT = "tenant"
    FISCAL = "fiscal"
    DATA_SOURCE = "data_source"
    TEST_CFDI = "test_cfdi"
    HEALTH_CHECK = "health_check"


# Orden secuencial obligatorio: no se puede saltar un paso.
STEP_ORDER: List[OnboardingStep] = [
    OnboardingStep.TENANT,
    OnboardingStep.FISCAL,
    OnboardingStep.DATA_SOURCE,
    OnboardingStep.TEST_CFDI,
    OnboardingStep.HEALTH_CHECK,
]

STEP_NAMES: Dict[str, str] = {
    "tenant": "Crear tenant y usuario admin",
    "fiscal": "Datos fiscales (RFC, régimen, CP)",
    "data_source": "Conectar fuente de datos",
    "test_cfdi": "Primer CFDI de prueba",
    "health_check": "Verificación completa",
}


# ---------------------------------------------------------------------------
# Estado global de la sesión
# ---------------------------------------------------------------------------

class OnboardingStatus(str, Enum):
    """Estado global de una sesión de onboarding."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class OnboardingSession(BaseModel):
    """Sesión persistente de onboarding de un tenant.

    Guarda el progreso (pasos completados) y los datos aportados por cada
    paso, de forma que si el flujo se corta se retoma donde quedó.
    """
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único de la sesión de onboarding",
    )
    tenant_id: str = Field(
        default="",
        description="Tenant creado en el paso 1 (empresa contable)",
    )
    tenant_name: str = Field(
        default="",
        description="Nombre del tenant / empresa contable",
    )
    status: OnboardingStatus = Field(
        default=OnboardingStatus.IN_PROGRESS,
        description="Estado global de la sesión",
    )
    completed_steps: List[str] = Field(
        default_factory=list,
        description="Pasos ya completados (en orden)",
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Datos aportados por cada paso, por clave de paso",
    )
    errors: Dict[str, str] = Field(
        default_factory=dict,
        description="Errores de validación registrados por paso",
    )
    created_at: str = Field(
        default_factory=_utcnow,
        description="Fecha de creación ISO UTC",
    )
    updated_at: Optional[str] = Field(
        default=None,
        description="Última actualización ISO UTC",
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="Timestamp de cierre (cuando status == completed)",
    )

    # ------------------------------------------------------------------
    # Propiedades derivadas (no se persisten)
    # ------------------------------------------------------------------

    @property
    def current_step(self) -> Optional[str]:
        """El siguiente paso que falta por completar (None si todo hecho)."""
        done = set(self.completed_steps)
        for step in STEP_ORDER:
            if step.value not in done:
                return step.value
        return None

    @property
    def progress(self) -> int:
        """Número de pasos completados (0..5)."""
        return len(self.completed_steps)

    @property
    def total_steps(self) -> int:
        return len(STEP_ORDER)

    @property
    def is_complete(self) -> bool:
        return self.status == OnboardingStatus.COMPLETED

    # ------------------------------------------------------------------
    # Helpers de mutación (mantienen el timestamp)
    # ------------------------------------------------------------------

    def touch(self) -> None:
        """Actualiza `updated_at` a UTC now."""
        self.updated_at = _utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Snapshot serializable (dict) para respuestas API."""
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "status": self.status.value,
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "progress": self.progress,
            "total_steps": self.total_steps,
            "data": self.data,
            "errors": self.errors,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }
