# -*- coding: utf-8 -*-
"""CFDI 4.0 package — parser and SAT compliance checks.

Exports the full (legacy) parser/validator API plus the newer minimal
parse_cfdi_4 / SAT compliance API, so both callers keep working.
"""
from b2b_ai.cfdi.parser import CFDIError, parse_cfdi, parse_cfdi_4
from b2b_ai.cfdi.validator import (
    ValidationResult,
    SATError,
    check_cfdi_compliance,
    validate_cfdi,
    validate_rfc_format,
)
from b2b_ai.cfdi.cancellation import evaluate_cancellation

__all__ = [
    "CFDIError",
    "parse_cfdi",
    "parse_cfdi_4",
    "validate_cfdi",
    "ValidationResult",
    "SATError",
    "check_cfdi_compliance",
    "validate_rfc_format",
    "evaluate_cancellation",
]
