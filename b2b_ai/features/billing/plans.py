# -*- coding: utf-8 -*-
"""plans.py — Definición de planes de suscripción de Likida AI.

Precios en MXN por mes (recurrente). Los límites (usuarios y CFDIs/mes) son
las métricas que el BillingService usa para controlar el uso del tenant.

    STARTER     : $8,000  MXN/mes,   1 usuario,   500 CFDIs/mes
    PRO         : $20,000 MXN/mes,   5 usuarios, 2000 CFDIs/mes
    BUSINESS    : $40,000 MXN/mes,  15 usuarios, 10000 CFDIs/mes
    ENTERPRISE  : $80,000 MXN/mes,  usuarios ilimitados, CFDIs ilimitados

Convenciones del proyecto (pydantic v2, Field con description, enums).
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PlanCode(str, Enum):
    """Códigos de plan disponibles."""
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class BillingCycle(str, Enum):
    """Ciclos de facturación soportados (mensual para el piloto)."""
    MONTHLY = "monthly"
    ANNUAL = "annual"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class Plan(BaseModel):
    """Un plan de suscripción de Likida AI (pricing en MXN)."""
    code: PlanCode = Field(..., description="Código canónico del plan")
    name: str = Field(..., description="Nombre comercial del plan")
    price_mxn: int = Field(..., ge=0, description="Precio mensual en MXN")
    max_users: Optional[int] = Field(
        default=None, description="Máximo de usuarios (None = ilimitado)"
    )
    max_cfdis_month: Optional[int] = Field(
        default=None, description="Máximo de CFDIs procesados por mes (None = ilimitado)"
    )
    description: str = Field(default="", description="Descripción breve")
    features: List[str] = Field(
        default_factory=list, description="Lista de características incluidas"
    )

    @property
    def code_str(self) -> str:
        """Código como string (helper para APIs / dicts)."""
        return self.code.value


# ---------------------------------------------------------------------------
# Catálogo de planes
# ---------------------------------------------------------------------------

PLANS: List[Plan] = [
    Plan(
        code=PlanCode.STARTER,
        name="Starter",
        price_mxn=8000,
        max_users=1,
        max_cfdis_month=500,
        description="Ideal para despachos pequeños que inician su automatización.",
        features=[
            "1 usuario",
            "Hasta 500 CFDIs/mes",
            "Importación de CFDIs",
            "Validación SAT",
            "Reportes básicos",
        ],
    ),
    Plan(
        code=PlanCode.PRO,
        name="Pro",
        price_mxn=20000,
        max_users=5,
        max_cfdis_month=2000,
        description="Para despachos en crecimiento con volumen moderado.",
        features=[
            "5 usuarios",
            "Hasta 2000 CFDIs/mes",
            "Todo lo de Starter",
            "Complemento de pagos",
            "Conciliación bancaria",
            "Soporte prioritario",
        ],
    ),
    Plan(
        code=PlanCode.BUSINESS,
        name="Business",
        price_mxn=40000,
        max_users=15,
        max_cfdis_month=10000,
        description="Para contadores con múltiples clientes y alto volumen.",
        features=[
            "15 usuarios",
            "Hasta 10000 CFDIs/mes",
            "Todo lo de Pro",
            "Multi-tenant por cliente",
            "API de integración",
            "Gerente de cuenta",
        ],
    ),
    Plan(
        code=PlanCode.ENTERPRISE,
        name="Enterprise",
        price_mxn=80000,
        max_users=None,
        max_cfdis_month=None,
        description="Para organizaciones de gran escala. Límites ilimitados.",
        features=[
            "Usuarios ilimitados",
            "CFDIs ilimitados",
            "Todo lo de Business",
            "Onboarding dedicado",
            "SLA garantizado",
            "Firmas y legalización",
        ],
    ),
]

# Índice por código para búsqueda O(1).
PLANS_BY_CODE: Dict[str, Plan] = {p.code.value: p for p in PLANS}

# Plan por defecto que se asigna al inicio del piloto (trial de 30 días).
DEFAULT_TRIAL_PLAN: str = PlanCode.STARTER.value
TRIAL_DAYS: int = 30

# Moneda única para billing (MXN).
CURRENCY: str = "MXN"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_plan(code: str) -> Plan:
    """Devuelve el plan con el código dado, o lanza KeyError si no existe."""
    return PLANS_BY_CODE[code.lower()]


def get_plan_or_none(code: str) -> Optional[Plan]:
    """Devuelve el plan o None si el código no existe (sin lanzar)."""
    return PLANS_BY_CODE.get(code.lower())


def list_plans() -> List[Plan]:
    """Devuelve todos los planes disponibles, en orden de precio."""
    return sorted(PLANS, key=lambda p: p.price_mxn)


def exceeds_cfdi_limit(plan_code: str, cfdis_used: int) -> bool:
    """True si el tenant ya superó el límite mensual de CFDIs de su plan.

    ENTERPRISE (o cualquier plan con max_cfdis_month=None) nunca excede.
    """
    plan = get_plan(plan_code)
    limit = plan.max_cfdis_month
    if limit is None:
        return False
    return cfdis_used > limit


def exceeds_user_limit(plan_code: str, users: int) -> bool:
    """True si `users` supera el límite de usuarios del plan."""
    plan = get_plan(plan_code)
    limit = plan.max_users
    if limit is None:
        return False
    return users > limit


def plan_to_dict(plan: Plan) -> dict:
    """Serializa un plan a dict plano para respuestas API."""
    return {
        "code": plan.code.value,
        "name": plan.name,
        "price_mxn": plan.price_mxn,
        "currency": CURRENCY,
        "max_users": plan.max_users,
        "max_cfdis_month": plan.max_cfdis_month,
        "description": plan.description,
        "features": plan.features,
    }
