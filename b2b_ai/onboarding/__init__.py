# -*- coding: utf-8 -*-
"""Paquete de onboarding de nuevos clientes (wizard + checklist + API)."""
from b2b_ai.onboarding.wizard import (
    OnboardingWizard, STEP_ORDER, STEP_NAMES, STEP_TITLES,
    ERP_OPTIONS, PLAN_OPTIONS, PLAN_DETAILS, OnboardingError,
)
from b2b_ai.onboarding.checklist import OnboardingChecklist

__all__ = [
    "OnboardingWizard", "OnboardingChecklist",
    "STEP_ORDER", "STEP_NAMES", "STEP_TITLES",
    "ERP_OPTIONS", "PLAN_OPTIONS", "PLAN_DETAILS",
    "OnboardingError",
]
