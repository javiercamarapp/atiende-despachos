# -*- coding: utf-8 -*-
"""
classification_rules.py — Rule engine for deposit classification.

Provides a configurable rule system for classifying bank deposits into:
  - INGRESO: matched to an invoice (CFDI)
  - FINANCIAMIENTO: matched to loan/credit agreement
  - APORTACION_SOCIO: matched to partner capital contribution
  - GARANTIA: guarantee/depósito en garantía
  - OTRO_NO_GRAVABLE: unmatched to any taxable event

Rules are extensible: add new Rule instances to ClassificationEngine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    AuxiliarContable,
    ClasificacionDeposito,
    DepositoBancario,
)


@dataclass
class Rule:
    """A single classification rule.

    Attributes
    ----------
    name : str
        Human-readable rule name.
    description : str
        Description of what this rule matches.
    classification : ClasificacionDeposito
        The classification to assign when the condition matches.
    condition : Callable[[DepositoBancario, List[AuxiliarContable]], bool]
        Function that evaluates whether a deposit matches this rule.
    confidence : float
        Confidence level (0-1) when this rule matches.
    articulo_cff : Optional[str]
        Applicable CFF article, if any.
    """
    name: str = ""
    description: str = ""
    classification: ClasificacionDeposito = ClasificacionDeposito.OTRO_NO_GRAVABLE
    condition: Callable[[DepositoBancario, List[AuxiliarContable]], bool] = field(
        default=lambda deposito, auxiliares: False
    )
    confidence: float = 0.0
    articulo_cff: Optional[str] = None


def _matches_cfdi(deposito: DepositoBancario, auxiliares: List[AuxiliarContable]) -> bool:
    """Check if deposit matches a CFDI invoice in auxiliaries."""
    ref = deposito.referencia.strip().upper()
    if not ref:
        return False
    # Check if reference contains CFDI-related keywords
    cfdi_patterns = [
        r"CFDI", r"UUID", r"FACTURA", r"FACT\.", r"FAC",
        r"INV\.", r"INVOICE", r"TIMBR",
    ]
    for pattern in cfdi_patterns:
        if re.search(pattern, ref):
            return True
    # Check if reference matches a movement in auxiliaries
    for aux in auxiliares:
        for mov in aux.movimientos:
            if mov.referencia and mov.referencia.strip().upper() == ref:
                return True
    return False


def _matches_financiamiento(deposito: DepositoBancario, auxiliares: List[AuxiliarContable]) -> bool:
    """Check if deposit is a financing/loan deposit."""
    desc = deposito.descripcion.strip().upper()
    ref = deposito.referencia.strip().upper()
    financing_patterns = [
        r"PRÉSTAMO", r"PRESTAMO", r"PRÉSTAMO", r"FINANCIAMIENTO",
        r"CREDITO", r"CRÉDITO", r"LOAN", r"BANCO.*DEPOSITO",
        r"DEPOSITO.*BANC", r"CAPITAL.*TRABAJO", r"LINEA.*CREDITO",
    ]
    combined = f"{desc} {ref}"
    for pattern in financing_patterns:
        if re.search(pattern, combined):
            return True
    # Check auxiliaries for financing accounts (1020-1049 range typically)
    for aux in auxiliares:
        cuenta = aux.cuenta_mayor.strip()
        if cuenta.startswith("10") and cuenta[2:4].isdigit():
            mayor_num = int(cuenta[2:4])
            if 20 <= mayor_num <= 49:
                for mov in aux.movimientos:
                    if mov.referencia and mov.referencia.strip().upper() == ref:
                        return True
    return False


def _matches_aportacion_socio(deposito: DepositoBancario, auxiliares: List[AuxiliarContable]) -> bool:
    """Check if deposit is a partner capital contribution."""
    desc = deposito.descripcion.strip().upper()
    ref = deposito.referencia.strip().upper()
    partner_patterns = [
        r"APORTACIÓN", r"APORTACION", r"SOCIO",
        r"CAPITAL.*SOCIAL", r"APORTACIÓN.*SOCIO",
        r"CONTRIBUCIÓN.*SOCIO", r"CONTRIBUCION.*SOCIO",
    ]
    combined = f"{desc} {ref}"
    for pattern in partner_patterns:
        if re.search(pattern, combined):
            return True
    # Check auxiliaries for partner capital accounts (typically 2010-2020)
    for aux in auxiliares:
        cuenta = aux.cuenta_mayor.strip()
        if cuenta.startswith("201") or cuenta.startswith("202"):
            for mov in aux.movimientos:
                if mov.referencia and mov.referencia.strip().upper() == ref:
                    return True
    return False


def _matches_garantia(deposito: DepositoBancario, auxiliares: List[AuxiliarContable]) -> bool:
    """Check if deposit is a guarantee deposit."""
    desc = deposito.descripcion.strip().upper()
    ref = deposito.referencia.strip().upper()
    guarantee_patterns = [
        r"GARANTÍA", r"GARANTIA", r"DEPÓSITO.*GARANT",
        r"DEPOSITO.*GARANT", r"COLATERAL",
        r"FIANZA", r"AVAL", r"SEGURO.*DEPÓSITO",
    ]
    combined = f"{desc} {ref}"
    for pattern in guarantee_patterns:
        if re.search(pattern, combined):
            return True
    # Check auxiliaries for guarantee accounts
    for aux in auxiliares:
        desc_aux = aux.descripcion.strip().upper()
        if "GARANT" in desc_aux:
            for mov in aux.movimientos:
                if mov.referencia and mov.referencia.strip().upper() == ref:
                    return True
    return False


# ---------------------------------------------------------------------------
# Default rules for Mexican fiscal context
# ---------------------------------------------------------------------------

DEFAULT_RULES: List[Rule] = [
    Rule(
        name="CFDI-Ingreso",
        description="Depósito que coincide con una factura CFDI (ingreso gravado)",
        classification=ClasificacionDeposito.INGRESO,
        condition=_matches_cfdi,
        confidence=0.95,
        articulo_cff="CFF Art. 14, LIVA Art. 1",
    ),
    Rule(
        name="Financiamiento-Bancario",
        description="Depósito de financiamiento o préstamo bancario",
        classification=ClasificacionDeposito.FINANCIAMIENTO,
        condition=_matches_financiamiento,
        confidence=0.85,
        articulo_cff="CFF Art. 14",
    ),
    Rule(
        name="Aportación-Socio",
        description="Aportación de capital de socio o accionista",
        classification=ClasificacionDeposito.APORTACION_SOCIO,
        condition=_matches_aportacion_socio,
        confidence=0.90,
        articulo_cff="CFF Art. 14",
    ),
    Rule(
        name="Garantía-Depósito",
        description="Depósito en garantía recibido",
        classification=ClasificacionDeposito.GARANTIA,
        condition=_matches_garantia,
        confidence=0.85,
        articulo_cff=None,
    ),
]


class ClassificationEngine:
    """Engine that evaluates a deposit against a set of rules.

    Usage
    -----
    >>> engine = ClassificationEngine()
    >>> result = engine.classify(deposito, auxiliares)
    """

    def __init__(self, rules: Optional[List[Rule]] = None):
        self.rules: List[Rule] = rules if rules is not None else list(DEFAULT_RULES)

    def add_rule(self, rule: Rule) -> None:
        """Add a custom rule to the engine."""
        self.rules.append(rule)

    def classify(
        self,
        deposito: DepositoBancario,
        auxiliares: List[AuxiliarContable],
    ) -> tuple[ClasificacionDeposito, float, Optional[str], Optional[str]]:
        """Classify a single deposit against all rules.

        Returns
        -------
        (classification, confidence, reason, articulo_cff)
        """
        for rule in self.rules:
            try:
                if rule.condition(deposito, auxiliares):
                    reason = f"Regla '{rule.name}': {rule.description}"
                    return (
                        rule.classification,
                        rule.confidence,
                        reason,
                        rule.articulo_cff,
                    )
            except Exception:
                continue

        # Default: not taxable
        return (
            ClasificacionDeposito.OTRO_NO_GRAVABLE,
            0.5,
            "No se encontró regla que aplique al depósito.",
            None,
        )
