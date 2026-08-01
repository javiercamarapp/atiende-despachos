# -*- coding: utf-8 -*-
"""
reconciliation_agent — Agente 1: Conciliación Bancaria Inteligente.

Extends the existing reconciliation infrastructure with:
  - Multi-format parsers (OFX, QIF, MT940, CSV, PDF) for 7 Mexican banks
  - 4-level matching engine (exact → fuzzy → multi-line → LLM)
  - SPEI payment verification
  - Aging alerts for unreconciled items
  - API endpoints for upload, status, and approval
"""
from b2b_ai.features.reconciliation_agent.models import (
    BankMovement,
    ReconciliationMatch,
    ReconciliationResult,
    AgingAlert,
    SPEIVerificationResult,
    MatchLevel,
    AlertSeverity,
)
from b2b_ai.features.reconciliation_agent.matching_engine import MatchingEngine
from b2b_ai.features.reconciliation_agent.parsers import BankStatementParser
from b2b_ai.features.reconciliation_agent.spei import SPEIVerifier
from b2b_ai.features.reconciliation_agent.alerts import AlertEngine

__all__ = [
    "BankMovement",
    "ReconciliationMatch",
    "ReconciliationResult",
    "AgingAlert",
    "SPEIVerificationResult",
    "MatchLevel",
    "AlertSeverity",
    "MatchingEngine",
    "BankStatementParser",
    "SPEIVerifier",
    "AlertEngine",
]
