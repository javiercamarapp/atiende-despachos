# -*- coding: utf-8 -*-
"""Onboarding Wizard — flujo del Día 1 del piloto (30 días).

Lleva al contador desde "me interesa" hasta "estoy procesando CFDIs en
producción", en 5 pasos validados:

    1. tenant        — crea el tenant (empresa contable) + usuario admin
    2. fiscal        — configura datos fiscales (RFC, régimen, código postal)
    3. data_source   — conecta la fuente de datos (CFDI/SAT/bank)
    4. test_cfdi     — sube, parsea y valida el primer CFDI de prueba
    5. health_check  — verificación completa (checklist)

Exports públicos:
    OnboardingStep, OnboardingStatus, OnboardingSession, STEP_ORDER,
    OnboardingWizard, OnboardingWizardError, build_onboarding_wizard_router
"""
from b2b_ai.features.onboarding.models import (
    OnboardingSession,
    OnboardingStatus,
    OnboardingStep,
    STEP_NAMES,
    STEP_ORDER,
)
from b2b_ai.features.onboarding.wizard import (
    OnboardingWizard,
    OnboardingWizardError,
    _reset_state,
)
from b2b_ai.features.onboarding.routes import build_onboarding_wizard_router

__all__ = [
    "OnboardingSession",
    "OnboardingStatus",
    "OnboardingStep",
    "STEP_NAMES",
    "STEP_ORDER",
    "OnboardingWizard",
    "OnboardingWizardError",
    "build_onboarding_wizard_router",
    "_reset_state",
]
