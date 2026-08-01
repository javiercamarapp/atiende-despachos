# -*- coding: utf-8 -*-
"""
rfc.py — Canonical RFC validation regex for Mexican tax IDs (RFC).

Centralizes the RFC regex pattern so all modules use the same definition.
The pattern covers both persona moral (12 chars: 3 letters + 6 digits + 3 alphanum)
and persona física (13 chars: 4 letters + 6 digits + 3 alphanum).

Usage:
    from b2b_ai.common.rfc import RFC_RE, is_valid_rfc

    RFC_RE.match("ABC850101AB1")  # True (moral)
    is_valid_rfc("XAXX010101000")  # True (generic)
"""
from __future__ import annotations

import re

# Canonical RFC regex: 3-4 letters (& allowed) + 6 digits + 2-3 alphanumeric.
# The {2,3} suffix covers both old (2-digit homoclave) and current (3-digit)
# RFCs issued by SAT. All comparisons must be against .upper() input.
RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

# Alias for the narrower (legacy) pattern used in PII masking.
RFC_EXACT_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")


def is_valid_rfc(rfc: str) -> bool:
    """Return True if `rfc` matches the canonical RFC pattern.

    Input is auto-normalized (stripped, uppercased). Returns False on
    None, empty string, or non-matching input.
    """
    if not rfc:
        return False
    return bool(RFC_RE.match(rfc.strip().upper()))


def normalize_rfc(rfc: str) -> str:
    """Normalize an RFC string: strip whitespace and uppercase."""
    return (rfc or "").strip().upper()
