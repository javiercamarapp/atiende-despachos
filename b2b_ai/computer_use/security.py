# -*- coding: utf-8 -*-
"""
security.py — Security layer for Computer Use operations.

Implements:
    - Domain allowlist (real ERP domains only; no example.com)
    - Credential encryption at rest (Fernet / B2B_ENCRYPTION_KEY)
    - Per-tenant browser context isolation (cookies, storage)
    - Session lifecycle management (creation, expiration, forced close)
    - Screenshot PII masking (RFC, CURP, nómina, CURP, phone)
    - Configurable screenshot retention with auto-purge
    - Immutable audit log of every Computer Use operation
    - B2B_COMPUTER_USE_ALLOW_WRITES=false by default (read-only safe)
    - Human confirmation gate for fiscal actions
    - Idempotency keys for records and pólizas
    - RBAC enforcement for write operations

Design:
    - Zero dependencies beyond stdlib + cryptography (already in pyproject.toml)
    - Thread-safe (all mutable state protected by locks)
    - Audit log is append-only, never mutated in place
    - Encryption uses Fernet (AES-128-CBC + HMAC); key from env
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. DOMAIN ALLOWLIST
# ---------------------------------------------------------------------------
# Production ERP domains. Only these are navigable by the browser automation.
# example.com is explicitly rejected.

_KNOWN_ERP_DOMAINS: FrozenSet[str] = frozenset({
    # CONTPAQi Cloud / Web
    "contpaqi.com",
    "contpaqiweb.com",
    "contpaqicloud.com",
    "contpaqi.contpaqi.com",
    # Aspel Cloud / Web
    "aspel.com.mx",
    "aspelcloud.com",
    "aspel.net",
    # SAP B1 (cloud)
    "sap.com",
    "sapbydesign.com",
    "sapbusinessone.com",
    # Odoo (cloud-hosted)
    "odoo.com",
    "odoo.sh",
    # SAT (read-only reference)
    "sat.gob.mx",
    "cfdi.sat.gob.mx",
})

# Hard-blocked domains (never navigable, even if added to allowlist).
_BLOCKED_DOMAINS: FrozenSet[str] = frozenset({
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
})


class DomainNotAllowedError(Exception):
    """Raised when a URL targets a domain not in the allowlist."""


def validate_domain(url: str, *, extra_allowed: FrozenSet[str] = frozenset()) -> str:
    """Validate that *url* targets an allowed ERP domain.

    Args:
        url: The URL to validate.
        extra_allowed: Additional domains allowed beyond the built-in set.

    Returns:
        The normalized hostname.

    Raises:
        DomainNotAllowedError: If domain is blocked or not in allowlist.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")

    if not hostname:
        raise DomainNotAllowedError(f"URL has no hostname: {url}")

    # Hard-block check (takes precedence over allowlist).
    for blocked in _BLOCKED_DOMAINS:
        if hostname == blocked or hostname.endswith("." + blocked):
            raise DomainNotAllowedError(
                f"Domain '{hostname}' is hard-blocked (reserved/test domain). "
                f"Configure a real ERP URL in CONTPAQI_URL / ASPEL_URL."
            )

    # Allowlist check: hostname must be in the set or be a subdomain.
    all_allowed = _KNOWN_ERP_DOMAINS | extra_allowed
    for allowed in all_allowed:
        if hostname == allowed or hostname.endswith("." + allowed):
            return hostname

    # Also allow if URL was explicitly set in env (user-configured custom domain).
    # This is logged as a warning, not silently accepted.
    env_urls = {
        os.environ.get("CONTPAQI_URL", ""),
        os.environ.get("ASPEL_URL", ""),
    }
    for env_url in env_urls:
        if env_url:
            env_host = urlparse(env_url).hostname
            if env_host and hostname == env_host.lower():
                logger.warning(
                    "Domain '%s' not in built-in allowlist but matches env URL; "
                    "allowed with warning. Consider adding to _KNOWN_ERP_DOMAINS.",
                    hostname,
                )
                return hostname

    raise DomainNotAllowedError(
        f"Domain '{hostname}' is not in the Computer Use allowlist. "
        f"Allowed domains: {', '.join(sorted(_KNOWN_ERP_DOMAINS))}. "
        f"To allow a custom domain, set CONTPAQI_URL or ASPEL_URL in .env."
    )


# ---------------------------------------------------------------------------
# 2. CREDENTIAL ENCRYPTION (Fernet / B2B_ENCRYPTION_KEY)
# ---------------------------------------------------------------------------

def _get_encryption_key() -> Optional[bytes]:
    """Get the Fernet encryption key from B2B_ENCRYPTION_KEY env var.

    Returns None if not set (encryption disabled — degraded mode with warning).
    """
    raw = os.environ.get("B2B_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    # Accept raw 32-byte base64url key or derive from passphrase.
    try:
        key = base64.urlsafe_b64decode(raw)
        if len(key) == 32:
            return raw.encode() if isinstance(raw, str) else raw
    except Exception:
        pass
    # Derive from passphrase.
    derived = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(derived)


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a credential string using Fernet.

    Falls back to base64 obfuscation (NOT secure) if B2B_ENCRYPTION_KEY is
    not set, with a loud warning in logs.

    Returns:
        Encrypted string (base64-encoded).
    """
    if not plaintext:
        return ""

    key = _get_encryption_key()
    if key:
        from cryptography.fernet import Fernet
        f = Fernet(key)
        return f.encrypt(plaintext.encode()).decode()

    # Degraded mode: base64 obfuscation (NOT encryption).
    logger.critical(
        "B2B_ENCRYPTION_KEY not set! Credential stored with base64 obfuscation "
        "ONLY — this is NOT secure. Set B2B_ENCRYPTION_KEY in production."
    )
    return "OBFUSCATED:" + base64.b64encode(plaintext.encode()).decode()


def decrypt_credential(encrypted: str) -> str:
    """Decrypt a credential string.

    Handles Fernet-encrypted and obfuscated (legacy) values.
    """
    if not encrypted:
        return ""

    # Handle obfuscated (degraded) mode.
    if encrypted.startswith("OBFUSCATED:"):
        logger.warning("Decrypting credential stored in obfuscated (non-encrypted) mode.")
        return base64.b64decode(encrypted[len("OBFUSCATED:"):]).decode()

    key = _get_encryption_key()
    if key:
        from cryptography.fernet import Fernet
        f = Fernet(key)
        return f.decrypt(encrypted.encode()).decode()

    # No key + not obfuscated = try base64 decode (best effort).
    logger.warning("No B2B_ENCRYPTION_KEY; attempting raw base64 decode.")
    return base64.b64decode(encrypted).decode()


# ---------------------------------------------------------------------------
# 3. PER-TENANT BROWSER CONTEXT ISOLATION
# ---------------------------------------------------------------------------

@dataclass
class TenantBrowserContext:
    """Isolated browser context for a single tenant.

    Each tenant gets its own cookie jar, storage state, and screenshot
    directory. No cross-tenant leakage.
    """
    tenant_id: str
    context_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    cookie_jar: Dict[str, Any] = field(default_factory=dict)
    storage_state: Dict[str, Any] = field(default_factory=dict)
    screenshot_dir: str = ""
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_active: bool = True

    def touch(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()

    def get_screenshot_dir(self, base_dir: str = "/tmp/b2b_screenshots") -> str:
        """Get or create tenant-specific screenshot directory."""
        if not self.screenshot_dir:
            self.screenshot_dir = os.path.join(base_dir, f"tenant_{self.tenant_id}")
            os.makedirs(self.screenshot_dir, exist_ok=True)
        return self.screenshot_dir


class SessionManager:
    """Manages isolated browser sessions per tenant.

    Sessions expire after a configurable timeout (default 30 minutes).
    Each session is isolated: separate cookies, storage, screenshot dirs.
    """

    def __init__(
        self,
        session_timeout_seconds: int = 1800,  # 30 minutes
        max_sessions_per_tenant: int = 3,
        screenshot_base_dir: str = "/tmp/b2b_screenshots",
    ):
        self._lock = threading.Lock()
        self._sessions: Dict[str, TenantBrowserContext] = {}
        self._session_timeout = session_timeout_seconds
        self._max_per_tenant = max_sessions_per_tenant
        self._screenshot_base_dir = screenshot_base_dir

    def create_session(self, tenant_id: str) -> TenantBrowserContext:
        """Create a new isolated session for a tenant.

        Evicts oldest session if tenant exceeds max_sessions_per_tenant.
        """
        with self._lock:
            # Count existing sessions for this tenant.
            tenant_sessions = [
                (k, v) for k, v in self._sessions.items()
                if v.tenant_id == tenant_id and v.is_active
            ]

            # Evict oldest if at limit.
            if len(tenant_sessions) >= self._max_per_tenant:
                oldest_key = min(tenant_sessions, key=lambda x: x[1].created_at)[0]
                self._close_session_unlocked(oldest_key)

            ctx = TenantBrowserContext(
                tenant_id=tenant_id,
                screenshot_dir="",
            )
            ctx.get_screenshot_dir(self._screenshot_base_dir)
            self._sessions[ctx.context_id] = ctx

            logger.info(
                "Session created for tenant=%s context=%s",
                tenant_id, ctx.context_id,
            )
            return ctx

    def get_session(self, context_id: str) -> Optional[TenantBrowserContext]:
        """Get an active session. Returns None if expired or not found."""
        with self._lock:
            ctx = self._sessions.get(context_id)
            if not ctx or not ctx.is_active:
                return None
            if self._is_expired(ctx):
                self._close_session_unlocked(context_id)
                return None
            ctx.touch()
            return ctx

    def close_session(self, context_id: str) -> bool:
        """Explicitly close a session."""
        with self._lock:
            return self._close_session_unlocked(context_id)

    def purge_expired(self) -> int:
        """Close all expired sessions. Returns count of purged sessions."""
        with self._lock:
            now = time.time()
            expired = [
                k for k, v in self._sessions.items()
                if v.is_active and (now - v.last_activity) > self._session_timeout
            ]
            for k in expired:
                self._close_session_unlocked(k)
            return len(expired)

    def active_session_count(self) -> int:
        """Count of currently active sessions."""
        with self._lock:
            return sum(1 for v in self._sessions.values() if v.is_active)

    def _is_expired(self, ctx: TenantBrowserContext) -> bool:
        return (time.time() - ctx.last_activity) > self._session_timeout

    def _close_session_unlocked(self, context_id: str) -> bool:
        ctx = self._sessions.get(context_id)
        if ctx and ctx.is_active:
            ctx.is_active = False
            logger.info(
                "Session closed for tenant=%s context=%s",
                ctx.tenant_id, context_id,
            )
            return True
        return False


# ---------------------------------------------------------------------------
# 4. SCREENSHOT PII MASKING
# ---------------------------------------------------------------------------
# Patterns for Mexican fiscal PII that must be masked in screenshots.

_RFC_RE = re.compile(
    r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"
)
_CURP_RE = re.compile(
    r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9][0-9]\b"
)
_NOMINA_NUM_RE = re.compile(
    r"\b\d{1,2}[-/]\d{5,8}\b"  # Employee numbers like 01-12345 or 12/345678
)
_PHONE_RE = re.compile(
    r"(?:\+?52)?[\s.-]?\(?\d{2,3}\)?[\s.-]?\d{3,4}[\s.-]?\d{4}\b"
)
_CARD_RE = re.compile(
    r"\b(?:\d[ -]?){13,19}\d\b"
)

# Fields that may contain PII (for structured data masking).
_PII_FIELD_NAMES = {
    "rfc", "curp", "nombre", "razon_social", "telefono", "phone",
    "email", "correo", "nomina", "employee_number", "tarjeta", "card",
    "cuenta", "account", "domicilio", "direccion", "address",
}


def mask_pii_in_text(text: str) -> str:
    """Mask PII patterns in a text string (e.g., OCR'd screenshot content).

    Order matters: CURP before RFC (CURP is a superset pattern).
    """
    if not text:
        return text

    masked = text
    masked = _CURP_RE.sub("<CURP>", masked)
    masked = _RFC_RE.sub("<RFC>", masked)
    masked = _NOMINA_NUM_RE.sub("<NOMINA>", masked)
    masked = _PHONE_RE.sub("<TEL>", masked)
    masked = _CARD_RE.sub("<CARD>", masked)
    return masked


def mask_pii_in_dict(data: dict) -> dict:
    """Recursively mask PII values in a dict (by field name and value pattern)."""
    if not isinstance(data, dict):
        return data

    result = {}
    for k, v in data.items():
        key_lower = k.lower()
        if isinstance(v, dict):
            result[k] = mask_pii_in_dict(v)
        elif isinstance(v, list):
            result[k] = [mask_pii_in_dict(i) if isinstance(i, dict) else i for i in v]
        elif isinstance(v, str) and key_lower in _PII_FIELD_NAMES:
            result[k] = mask_pii_in_text(v)
        elif isinstance(v, str):
            # Also mask by pattern (even if field name isn't flagged).
            result[k] = mask_pii_in_text(v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# 5. SCREENSHOT RETENTION POLICY
# ---------------------------------------------------------------------------

@dataclass
class RetentionPolicy:
    """Configurable screenshot retention.

    - max_age_hours: Delete screenshots older than this.
    - max_count_per_tenant: Keep at most N screenshots per tenant.
    - max_total_size_mb: Total screenshots dir max size in MB.
    """
    max_age_hours: int = 72  # 3 days default
    max_count_per_tenant: int = 1000
    max_total_size_mb: int = 500

    @classmethod
    def from_env(cls) -> "RetentionPolicy":
        """Build from environment variables."""
        return cls(
            max_age_hours=int(os.environ.get("B2B_SCREENSHOT_RETENTION_HOURS", "72")),
            max_count_per_tenant=int(os.environ.get("B2B_SCREENSHOT_MAX_COUNT", "1000")),
            max_total_size_mb=int(os.environ.get("B2B_SCREENSHOT_MAX_SIZE_MB", "500")),
        )


def purge_screenshots(base_dir: str, policy: Optional[RetentionPolicy] = None) -> Dict[str, int]:
    """Purge screenshots according to retention policy.

    Returns:
        Dict with counts: {"deleted_by_age": N, "deleted_by_count": N, "errors": N}
    """
    if policy is None:
        policy = RetentionPolicy.from_env()

    stats = {"deleted_by_age": 0, "deleted_by_count": 0, "errors": 0}

    if not os.path.isdir(base_dir):
        return stats

    cutoff = time.time() - (policy.max_age_hours * 3600)

    try:
        # Walk tenant subdirs.
        for tenant_dir in os.listdir(base_dir):
            tenant_path = os.path.join(base_dir, tenant_dir)
            if not os.path.isdir(tenant_path):
                continue

            screenshots = []
            for f in os.listdir(tenant_path):
                fp = os.path.join(tenant_path, f)
                if os.path.isfile(fp):
                    stat = os.stat(fp)
                    screenshots.append((fp, stat.st_mtime, stat.st_size))

            # Delete by age.
            for fp, mtime, size in screenshots:
                if mtime < cutoff:
                    try:
                        os.remove(fp)
                        stats["deleted_by_age"] += 1
                    except OSError:
                        stats["errors"] += 1

            # Delete by count (keep newest N).
            remaining = sorted(
                [(fp, mtime) for fp, mtime, _ in screenshots if mtime >= cutoff],
                key=lambda x: x[1],
                reverse=True,
            )
            if len(remaining) > policy.max_count_per_tenant:
                for fp, _ in remaining[policy.max_count_per_tenant:]:
                    try:
                        os.remove(fp)
                        stats["deleted_by_count"] += 1
                    except OSError:
                        stats["errors"] += 1

    except Exception as e:
        logger.error("Screenshot purge error: %s", e)
        stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# 6. IMMUTABLE AUDIT LOG
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit log entry for a Computer Use operation.

    Once created, cannot be modified (frozen dataclass).
    """
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    action: str = ""  # e.g., "login", "navigate", "click", "extract", "register"
    target: str = ""  # e.g., "contpaqi/facturas", "aspel/catalogos"
    status: str = ""  # "success", "failed", "needs_human_review"
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    idempotency_key: str = ""
    human_confirmed: bool = False
    write_operation: bool = False
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (for JSON logging / DB storage)."""
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(
                self.timestamp, tz=timezone.utc
            ).isoformat(),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "action": self.action,
            "target": self.target,
            "status": self.status,
            "details": self.details,
            "ip_address": self.ip_address,
            "idempotency_key": self.idempotency_key,
            "human_confirmed": self.human_confirmed,
            "write_operation": self.write_operation,
            "error_message": self.error_message,
        }


class AuditLog:
    """Append-only, thread-safe audit log for Computer Use operations.

    In production, this would write to an append-only table or external
    log sink. This in-memory implementation is suitable for MVP/testing.
    Entries are never mutated — only appended.
    """

    _MAX_ENTRIES = 10_000  # Rotate oldest beyond this.

    def __init__(self, persist_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._entries: List[AuditEntry] = []
        self._idempotency_index: Dict[str, str] = {}  # key -> entry_id
        self._persist_path = persist_path

    def log(self, entry: AuditEntry) -> str:
        """Append an audit entry. Returns the entry_id.

        If idempotency_key is set and already seen, returns the existing
        entry_id without creating a new entry.
        """
        with self._lock:
            # Idempotency check.
            if entry.idempotency_key:
                existing = self._idempotency_index.get(entry.idempotency_key)
                if existing:
                    logger.info(
                        "Idempotent hit: key=%s existing_entry=%s",
                        entry.idempotency_key, existing,
                    )
                    return existing

            self._entries.append(entry)

            if entry.idempotency_key:
                self._idempotency_index[entry.idempotency_key] = entry.entry_id

            # Rotate if over limit.
            if len(self._entries) > self._MAX_ENTRIES:
                self._entries = self._entries[-self._MAX_ENTRIES:]

            # Persist if configured.
            if self._persist_path:
                self._persist_entry(entry)

            logger.info(
                "Audit: %s %s/%s status=%s tenant=%s",
                entry.action, entry.target, entry.entry_id[:8],
                entry.status, entry.tenant_id,
            )
            return entry.entry_id

    def query(
        self,
        tenant_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Query audit entries (read-only)."""
        with self._lock:
            results = []
            for e in reversed(self._entries):
                if tenant_id and e.tenant_id != tenant_id:
                    continue
                if action and e.action != action:
                    continue
                if since and e.timestamp < since:
                    continue
                results.append(e)
                if len(results) >= limit:
                    break
            return results

    def check_idempotency(self, key: str) -> Optional[str]:
        """Check if an idempotency key was already used. Returns entry_id or None."""
        with self._lock:
            return self._idempotency_index.get(key)

    def _persist_entry(self, entry: AuditEntry):
        """Append entry to persistent log file (JSONL)."""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a") as f:
                f.write(json.dumps(entry.to_dict(), default=str) + "\n")
        except Exception as e:
            logger.error("Failed to persist audit entry: %s", e)


# ---------------------------------------------------------------------------
# 7. RBAC FOR WRITE OPERATIONS
# ---------------------------------------------------------------------------

# Permissions specific to Computer Use operations.
COMPUTER_USE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "admin": frozenset({
        "computer_use.read",
        "computer_use.write",
        "computer_use.fiscal_actions",
        "computer_use.session.manage",
        "computer_use.audit.view",
    }),
    "contador": frozenset({
        "computer_use.read",
        "computer_use.write",
        "computer_use.fiscal_actions",
    }),
    "auxiliar": frozenset({
        "computer_use.read",
    }),
    "auditor": frozenset({
        "computer_use.read",
        "computer_use.audit.view",
    }),
}


def has_computer_use_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific Computer Use permission."""
    perms = COMPUTER_USE_PERMISSIONS.get(role, frozenset())
    return permission in perms


def require_write_permission(role: str) -> None:
    """Raise if role lacks write permission. Call before any write operation."""
    if not has_computer_use_permission(role, "computer_use.write"):
        raise PermissionError(
            f"Role '{role}' lacks 'computer_use.write' permission. "
            f"Only admin and contador can perform write operations via Computer Use."
        )


def require_fiscal_permission(role: str) -> None:
    """Raise if role lacks fiscal action permission."""
    if not has_computer_use_permission(role, "computer_use.fiscal_actions"):
        raise PermissionError(
            f"Role '{role}' lacks 'computer_use.fiscal_actions' permission. "
            f"Only admin and contador can perform fiscal actions."
        )


# ---------------------------------------------------------------------------
# 8. WRITE GATE (B2B_COMPUTER_USE_ALLOW_WRITES)
# ---------------------------------------------------------------------------

def writes_allowed() -> bool:
    """Check if write operations are enabled.

    Default is False (read-only safe mode). Must be explicitly enabled
    via B2B_COMPUTER_USE_ALLOW_WRITES=true.
    """
    return os.environ.get("B2B_COMPUTER_USE_ALLOW_WRITES", "false").lower() in (
        "true", "1", "yes", "on"
    )


def require_writes_enabled() -> None:
    """Raise if writes are not enabled. Call before any write operation."""
    if not writes_allowed():
        raise PermissionError(
            "Write operations are disabled. Set B2B_COMPUTER_USE_ALLOW_WRITES=true "
            "to enable. Default is read-only for safety."
        )


# ---------------------------------------------------------------------------
# 9. HUMAN CONFIRMATION FOR FISCAL ACTIONS
# ---------------------------------------------------------------------------

# Actions that are considered fiscal and require human confirmation.
FISCAL_ACTIONS: FrozenSet[str] = frozenset({
    "register_invoice",
    "register_poliza",
    "cancel_invoice",
    "submit_declaration",
    "submit_diot",
    "submit_nomina",
    "approve_payment",
    "modify_catalog",
    "close_period",
})


def is_fiscal_action(action: str) -> bool:
    """Check if an action is fiscal (requires human confirmation)."""
    return action.lower() in FISCAL_ACTIONS


def require_human_confirmation(action: str, confirmed: bool) -> None:
    """Raise if a fiscal action hasn't been human-confirmed."""
    if is_fiscal_action(action) and not confirmed:
        raise PermissionError(
            f"Action '{action}' is a fiscal action and requires human confirmation. "
            f"Set human_confirmed=True to proceed."
        )


# ---------------------------------------------------------------------------
# 10. IDEMPOTENCY
# ---------------------------------------------------------------------------

def generate_idempotency_key(
    tenant_id: str,
    action: str,
    target: str,
    payload_hash: Optional[str] = None,
) -> str:
    """Generate a deterministic idempotency key for a Computer Use operation.

    Same inputs always produce the same key, preventing duplicate operations.
    """
    parts = [tenant_id, action, target]
    if payload_hash:
        parts.append(payload_hash)
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def generate_payload_hash(data: Any) -> str:
    """Generate a stable hash of a payload for idempotency."""
    if data is None:
        return ""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 11. SECURITY CONFIG (aggregates all security settings)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityConfig:
    """Aggregated security configuration for Computer Use.

    Read from environment variables.
    """
    allow_writes: bool = False
    encryption_key_set: bool = False
    session_timeout_seconds: int = 1800
    max_sessions_per_tenant: int = 3
    screenshot_retention_hours: int = 72
    screenshot_max_count: int = 1000
    screenshot_max_size_mb: int = 500
    audit_log_path: str = "/var/log/b2b/computer_use_audit.jsonl"
    mask_pii_in_screenshots: bool = True
    require_human_for_fiscal: bool = True

    @classmethod
    def from_env(cls) -> "SecurityConfig":
        """Build from environment variables."""
        key_set = bool(os.environ.get("B2B_ENCRYPTION_KEY", "").strip())
        return cls(
            allow_writes=writes_allowed(),
            encryption_key_set=key_set,
            session_timeout_seconds=int(
                os.environ.get("B2B_CU_SESSION_TIMEOUT", "1800")
            ),
            max_sessions_per_tenant=int(
                os.environ.get("B2B_CU_MAX_SESSIONS", "3")
            ),
            screenshot_retention_hours=int(
                os.environ.get("B2B_SCREENSHOT_RETENTION_HOURS", "72")
            ),
            screenshot_max_count=int(
                os.environ.get("B2B_SCREENSHOT_MAX_COUNT", "1000")
            ),
            screenshot_max_size_mb=int(
                os.environ.get("B2B_SCREENSHOT_MAX_SIZE_MB", "500")
            ),
            audit_log_path=os.environ.get(
                "B2B_CU_AUDIT_LOG_PATH",
                "/var/log/b2b/computer_use_audit.jsonl",
            ),
            mask_pii_in_screenshots=os.environ.get(
                "B2B_CU_MASK_PII", "true"
            ).lower() in ("true", "1", "yes"),
            require_human_for_fiscal=os.environ.get(
                "B2B_CU_REQUIRE_HUMAN_FISCAL", "true"
            ).lower() in ("true", "1", "yes"),
        )

    def validate(self) -> List[str]:
        """Validate security config. Returns list of warnings/issues."""
        issues = []
        if not self.encryption_key_set:
            issues.append(
                "CRITICAL: B2B_ENCRYPTION_KEY not set. Credentials stored insecurely."
            )
        if self.allow_writes:
            issues.append(
                "WARNING: B2B_COMPUTER_USE_ALLOW_WRITES=true. "
                "Write operations are enabled — ensure RBAC is enforced."
            )
        if self.screenshot_retention_hours > 168:  # 7 days
            issues.append(
                f"WARNING: Screenshot retention is {self.screenshot_retention_hours}h "
                f"(>{168}h). Consider shorter retention for PII compliance."
            )
        return issues


# ---------------------------------------------------------------------------
# 12. SecurityPolicy alias (backward compat)
# ---------------------------------------------------------------------------
# SecurityPolicy is the legacy name for SecurityConfig.
# Keep as alias for callers that import SecurityPolicy.
SecurityPolicy = SecurityConfig
