# -*- coding: utf-8 -*-
"""
pricing.py — Planes y precios del producto Likida AI Enterprise (en MXN/mes).

Tiers:
    Starter      — $4,999  MXN/mes  (hasta 500 CFDI/mes).
    Professional — $14,999 MXN/mes  (hasta 2,000 CFDI/mes).
    Enterprise   — precio custom (cotización por contrato, sin tope).

Los límites de CFDI se usan para chequear si un tenant excede su plan
(función `exceeds_cfdi_limit`). La moneda de facturación del producto es
MXN, tanto para Stripe como para Conekta.
"""
from __future__ import annotations

from typing import Optional


class Plan:
    """Definición de un plan de facturación."""

    def __init__(self, key: str, name: str, price_mxn: float,
                 cfdi_limit: Optional[int], description: str = ""):
        self.key = key
        self.name = name
        self.price_mxn = price_mxn
        self.cfdi_limit = cfdi_limit     # None = sin límite (Enterprise)
        self.description = description

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "price_mxn": self.price_mxn,
            "price_cents": int(round(self.price_mxn * 100)),
            "cfdi_limit": self.cfdi_limit,
            "description": self.description,
        }


PLANS = {
    "starter": Plan(
        key="starter",
        name="Starter",
        price_mxn=4999.0,
        cfdi_limit=500,
        description="Hasta 500 CFDI/mes",
    ),
    "professional": Plan(
        key="professional",
        name="Professional",
        price_mxn=14999.0,
        cfdi_limit=2000,
        description="Hasta 2,000 CFDI/mes",
    ),
    "enterprise": Plan(
        key="enterprise",
        name="Enterprise",
        price_mxn=0.0,          # custom: se cotiza por contrato
        cfdi_limit=None,
        description="Precio custom (cotización)",
    ),
}


def get_plan(key: str) -> Optional[Plan]:
    """Devuelve el plan por su key, o None si no existe."""
    return PLANS.get(key)


def list_plans() -> list:
    """Devuelve la lista de planes como dicts (para la API)."""
    return [p.to_dict() for p in PLANS.values()]


def exceeds_cfdi_limit(plan_key: str, cfdi_count: int) -> bool:
    """True si `cfdi_count` excede el límite del plan (Enterprise nunca)."""
    plan = get_plan(plan_key)
    if plan is None or plan.cfdi_limit is None:
        return False
    return cfdi_count > plan.cfdi_limit


def cfdi_limit_for(plan_key: str) -> Optional[int]:
    """Límite de CFDI del plan (None para Enterprise)."""
    plan = get_plan(plan_key)
    return plan.cfdi_limit if plan else None
