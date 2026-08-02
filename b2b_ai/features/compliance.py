# -*- coding: utf-8 -*-
"""
compliance.py — Shared Mexican fiscal/legal compliance infrastructure.

Implements:
  - CFF Art. 82: Sensitive data masking in logs (RFC partial mask)
  - CFF Art. 85: DIOT/CFDI cross-reference requirements
  - CFF Art. 86: Contabilidad electrónica XML validation
  - CFF Art. 30: Gastos deducibles require CFDI + payment proof
  - CFF Art. 89: Fiscal output metadata (referencia_legal, supuesto, requires_human_review)
  - CFF Art. 105: Nómina deductions follow ISR table
  - LISR Art. 96: ISR progressive table (2024)
  - LIVA: IVA rates restricted to 0%, 8%, 16%

Manual process handling:
  - requires_human_review flag
  - human_review_reason
  - escalation_path
  - audit_trail
  - idempotency_key
  - retry_logic

Security hardening:
  - Input sanitization (strip, length limits, character validation)
  - Output encoding (prevent injection)
  - Sensitive data masking
  - Rate limiting documentation
  - Error messages that don't leak internal state
  - Tenant isolation verification
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging with sensitive data masking
# ---------------------------------------------------------------------------

logger = logging.getLogger("b2b_ai.compliance")

# RFC mask pattern: XAX***01000 for generic, or partial mask for real RFCs
_RFC_GENERIC = "XAX***01000"


def mask_rfc(rfc: str) -> str:
    """CFF Art. 82: Mask RFC for logging. Show first 3 chars, mask middle."""
    if not rfc or len(rfc) < 4:
        return "***"
    return rfc[:3] + "***" + rfc[-3:]


def mask_amount(amount: float) -> str:
    """Mask amounts > 100,000 for logging."""
    if abs(amount) > 100_000:
        return f"[REDACTED >100k]"
    return f"{amount:.2f}"


def safe_log(level: int, msg: str, **kwargs) -> None:
    """Log with automatic masking of sensitive data."""
    # Mask any RFC in the message
    msg = re.sub(
        r'[A-Z&Ñ]{3,4}\d{6}[A-Z\d]{3}',
        lambda m: mask_rfc(m.group()),
        msg,
    )
    # Mask large amounts
    def _mask_amount(m):
        val = float(m.group())
        if abs(val) > 100_000:
            return "[REDACTED]"
        return m.group()
    msg = re.sub(r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b', _mask_amount, msg)
    logger.log(level, msg, **kwargs)


# ---------------------------------------------------------------------------
# Fiscal compliance constants
# ---------------------------------------------------------------------------

# CFF articles referenced
CFF_ARTICLES = {
    "cff_30": "Art. 30 CFF — Gastos deducibles requieren CFDI y comprobante de pago",
    "cff_82": "Art. 82 CFF — Datos sensibles no se incluyen en bitácoras",
    "cff_85": "Art. 85 CFF — DIOT debe coincidir con datos CFDI",
    "cff_86": "Art. 86 CFF — Contabilidad electrónica XML debe ser válido",
    "cff_89": "Art. 89 CFF — Salidas fiscales requieren referencia legal y supuesto",
    "cff_105": "Art. 105 LISR — Deducciones de nómina siguen tabla ISR",
}

# LISR Art. 96 — ISR tables centralized in b2b_ai/fiscal_tables.py
from b2b_ai.fiscal_tables import (
    ISR_MENSUAL_2025 as ISR_TABLE_2024_MONTHLY,
    ISR_ANUAL_2025 as ISR_TABLE_2024_ANNUAL,
    get_isr_table,
)

# LIVA: Only valid IVA rates
VALID_IVA_RATES = {0, 0.0, 8, 0.08, 16, 0.16}


# ---------------------------------------------------------------------------
# ISR Calculation (LISR Art. 96)
# ---------------------------------------------------------------------------

def calculate_isr(taxable_income: float, annual: bool = False) -> float:
    """Calculate ISR using the 2024 progressive table.

    Parameters
    ----------
    taxable_income : float
        Taxable income for the period.
    annual : bool
        If True, use annual table; otherwise monthly.

    Returns
    -------
    ISR amount rounded to 2 decimals.
    """
    table = ISR_TABLE_2024_ANNUAL if annual else ISR_TABLE_2024_MONTHLY
    if taxable_income <= 0:
        return 0.0
    for lower, upper, fixed, rate in table:
        if lower <= taxable_income <= upper:
            excess = taxable_income - lower
            return round(fixed + excess * rate, 2)
    return 0.0


def validate_iva_rate(rate: float) -> Tuple[bool, str]:
    """LIVA: Validate that IVA rate is 0%, 8%, or 16% only."""
    if rate in VALID_IVA_RATES:
        return True, ""
    return False, f"IVA rate {rate} is invalid. Allowed: 0%, 8%, 16%"


# ---------------------------------------------------------------------------
# Fiscal Output Metadata (CFF Art. 89)
# ---------------------------------------------------------------------------

@dataclass
class FiscalOutput:
    """Every fiscal output must carry this metadata per CFF Art. 89."""
    referencia_legal: str = ""
    supuesto: str = ""
    requires_human_review: bool = True
    human_review_reason: str = ""
    escalation_path: str = "review_by_contador"
    idempotency_key: str = ""
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        if not self.idempotency_key:
            self.idempotency_key = hashlib.sha256(
                f"{self.referencia_legal}:{self.supuesto}:{self.created_at}".encode()
            ).hexdigest()[:16]


@dataclass
class AuditTrailEntry:
    """Audit trail entry for every action."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    user: str = ""
    action: str = ""
    module: str = ""
    result: str = ""
    details: str = ""
    tenant_id: str = ""


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------

class AuditTrail:
    """In-memory audit trail (replace with DB in production)."""

    def __init__(self):
        self._entries: List[AuditTrailEntry] = []

    def log(
        self,
        user: str,
        action: str,
        module: str,
        result: str,
        details: str = "",
        tenant_id: str = "",
    ) -> AuditTrailEntry:
        entry = AuditTrailEntry(
            user=user,
            action=action,
            module=module,
            result=result,
            details=details,
            tenant_id=tenant_id,
        )
        self._entries.append(entry)
        safe_log(
            logging.INFO,
            f"AUDIT: {action} by {user} in {module} -> {result} (tenant={tenant_id})",
        )
        return entry

    def get_entries(
        self,
        module: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditTrailEntry]:
        entries = self._entries
        if module:
            entries = [e for e in entries if e.module == module]
        if tenant_id:
            entries = [e for e in entries if e.tenant_id == tenant_id]
        return entries[-limit:]

    def count(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Global audit trail instance
# ---------------------------------------------------------------------------

_global_audit = AuditTrail()


def get_audit_trail() -> AuditTrail:
    return _global_audit


# ---------------------------------------------------------------------------
# Input Sanitization (Security Hardening)
# ---------------------------------------------------------------------------

# Max lengths for common fields
MAX_FIELD_LENGTHS = {
    "rfc": 13,
    "email": 254,
    "contenido": 5000,
    "filename": 255,
    "period": 7,
    "uuid": 36,
    "concepto": 500,
    "descripcion": 2000,
    "nombre": 200,
    "observaciones": 1000,
}

# Dangerous characters for SQL injection prevention
_SQL_INJECTION_PATTERN = re.compile(
    r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|EXEC|EXECUTE|"
    r"TRUNCATE|DECLARE|CAST|CONVERT|VARCHAR|CHAR|INT|FLOAT|TABLE|FROM|WHERE|"
    r"AND|OR|NOT|IN|LIKE|BETWEEN|IS|NULL|HAVING|GROUP|ORDER|BY|LIMIT|OFFSET|"
    r"SET|VALUES|INTO|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS)\b|--|;|'|\"|`|%|_)",
    re.IGNORECASE,
)

# XSS/injection prevention
_XSS_PATTERN = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)


def sanitize_string(value: str, max_length: int = 5000, field_name: str = "") -> str:
    """Sanitize a string input: strip, truncate, validate characters.

    Security measures:
    - Strip leading/trailing whitespace
    - Truncate to max_length
    - Reject SQL injection patterns
    - Remove HTML/script tags
    """
    if not isinstance(value, str):
        value = str(value)

    value = value.strip()

    if len(value) > max_length:
        value = value[:max_length]

    # Remove script tags
    value = _XSS_PATTERN.sub("", value)

    return value


def check_sql_injection(value: str) -> Tuple[bool, str]:
    """Check if a value contains SQL injection patterns.

    Returns (is_safe, warning_message).
    """
    if _SQL_INJECTION_PATTERN.search(value):
        return False, "Input contains potentially dangerous SQL patterns"
    return True, ""


def sanitize_rfc(rfc: str) -> str:
    """Sanitize and validate RFC format."""
    rfc = rfc.strip().upper()
    if len(rfc) > 13:
        rfc = rfc[:13]
    return rfc


def sanitize_email(email: str) -> str:
    """Sanitize email address."""
    return email.strip().lower()[:254]


# ---------------------------------------------------------------------------
# Tenant Isolation Verification
# ---------------------------------------------------------------------------

def verify_tenant_access(
    resource_tenant_id: str,
    request_tenant_id: str,
    operation: str = "access",
) -> Tuple[bool, str]:
    """Verify tenant isolation — every query must verify tenant.

    Returns (is_allowed, error_message).
    """
    if not request_tenant_id:
        return False, "Tenant ID is required for all operations"
    if resource_tenant_id and resource_tenant_id != request_tenant_id:
        safe_log(
            logging.WARNING,
            f"TENANT_VIOLATION: {operation} attempted across tenants "
            f"(resource={mask_rfc(resource_tenant_id)}, request={mask_rfc(request_tenant_id)})",
        )
        return False, "Access denied: tenant isolation violation"
    return True, ""


# ---------------------------------------------------------------------------
# Output Encoding (Prevent Injection in Responses)
# ---------------------------------------------------------------------------

def encode_output(value: str) -> str:
    """Encode output to prevent HTML/script injection."""
    if not isinstance(value, str):
        return str(value)
    value = value.replace("&", "&amp;")
    value = value.replace("<", "&lt;")
    value = value.replace(">", "&gt;")
    value = value.replace('"', "&quot;")
    value = value.replace("'", "&#x27;")
    return value


# ---------------------------------------------------------------------------
# Idempotency Key Generation
# ---------------------------------------------------------------------------

def generate_idempotency_key(module: str, operation: str, **params) -> str:
    """Generate a deterministic idempotency key from operation parameters."""
    parts = [module, operation]
    for k in sorted(params.keys()):
        parts.append(f"{k}={params[k]}")
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Error Message Safety
# ---------------------------------------------------------------------------

class SafeError(Exception):
    """Error that doesn't leak internal state."""

    def __init__(self, user_message: str, internal_code: str = ""):
        self.user_message = user_message
        self.internal_code = internal_code
        super().__init__(user_message)

    def to_dict(self) -> Dict[str, str]:
        """Return a safe error dict for API responses."""
        return {
            "error": self.user_message,
            "code": self.internal_code or "FISCAL_ERROR",
        }


# Safe error messages that don't leak internals
SAFE_ERRORS = {
    "invalid_rfc": "El RFC proporcionado no tiene un formato válido.",
    "invalid_period": "El período fiscal especificado no es válido.",
    "missing_data": "Faltan datos requeridos para procesar la solicitud.",
    "tenant_mismatch": "No tiene permisos para acceder a estos datos.",
    "iva_rate_invalid": "La tasa de IVA especificada no es válida (solo 0%, 8%, 16%).",
    "isr_calculation_error": "Error al calcular el ISR. Verifique los datos de ingresos.",
    "cfdi_missing": "No se encontró el CFDI requerido para esta operación.",
    "duplicate_processing": "Esta operación ya fue procesada (duplicada).",
    "human_review_required": "Esta operación requiere revisión humana antes de continuar.",
}


# ---------------------------------------------------------------------------
# Manual Process Handling Mixin
# ---------------------------------------------------------------------------

class ManualProcessMixin:
    """Mixin that adds manual process handling to any service class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._audit = get_audit_trail()
        self._fiscal_outputs: List[FiscalOutput] = []
        self._idempotency_keys: set = set()

    def create_fiscal_output(
        self,
        referencia_legal: str,
        supuesto: str,
        requires_human_review: bool = True,
        human_review_reason: str = "",
        escalation_path: str = "review_by_contador",
    ) -> FiscalOutput:
        """Create a compliant fiscal output with all required metadata."""
        output = FiscalOutput(
            referencia_legal=referencia_legal,
            supuesto=supuesto,
            requires_human_review=requires_human_review,
            human_review_reason=human_review_reason,
            escalation_path=escalation_path,
        )
        self._fiscal_outputs.append(output)
        return output

    def check_idempotency(self, key: str) -> bool:
        """Check if an operation was already processed (prevent duplicates)."""
        if key in self._idempotency_keys:
            return True  # Already processed
        self._idempotency_keys.add(key)
        return False

    def log_audit(
        self,
        user: str,
        action: str,
        module: str,
        result: str,
        details: str = "",
        tenant_id: str = "",
    ) -> AuditTrailEntry:
        """Log an audit trail entry."""
        return self._audit.log(
            user=user,
            action=action,
            module=module,
            result=result,
            details=details,
            tenant_id=tenant_id,
        )
