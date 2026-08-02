# -*- coding: utf-8 -*-
"""test_computer_use_security_controls.py — Security controls for Computer Use.

Covers:
  - Domain allowlist: non-allowlisted URLs blocked
  - SSRF protection: private IPs, localhost, loopback blocked
  - Credential encryption/decryption (Fernet + degraded base64)
  - Audit log: append-only, idempotency
  - Session manager: isolation, expiration
  - RBAC: write/fiscal permission enforcement
  - PII masking in screenshots
  - Write gate: default read-only
"""
from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import time
from unittest.mock import patch

import pytest

os.environ.setdefault("B2B_ENV", "test")

from b2b_ai.computer_use.security import (
    validate_domain,
    DomainNotAllowedError,
    encrypt_credential,
    decrypt_credential,
    mask_pii_in_text,
    mask_pii_in_dict,
    has_computer_use_permission,
    require_write_permission,
    require_fiscal_permission,
    writes_allowed,
    require_writes_enabled,
    is_fiscal_action,
    require_human_confirmation,
    generate_idempotency_key,
    generate_payload_hash,
    AuditLog,
    AuditEntry,
    SessionManager,
    SecurityConfig,
    COMPUTER_USE_PERMISSIONS,
    FISCAL_ACTIONS,
)


# ---------------------------------------------------------------------------
# Domain allowlist tests
# ---------------------------------------------------------------------------

class TestDomainAllowlist:
    """Non-allowlisted URLs must be blocked."""

    def test_non_allowlisted_domain_blocked(self):
        """Arbitrary domain not in allowlist → DomainNotAllowedError."""
        with pytest.raises(DomainNotAllowedError, match="not in the Computer Use allowlist"):
            validate_domain("https://evil-site.com/app")

    def test_random_saas_domain_blocked(self):
        with pytest.raises(DomainNotAllowedError):
            validate_domain("https://my-random-saas.io/dashboard")

    def test_numeric_ip_blocked(self):
        """Direct IP addresses are not allowlisted."""
        with pytest.raises(DomainNotAllowedError):
            validate_domain("https://54.239.28.85/app")

    def test_subdomain_of_non_allowed_blocked(self):
        """Subdomain of a non-allowed domain should still be blocked."""
        with pytest.raises(DomainNotAllowedError):
            validate_domain("https://app.evil-site.com/erp")

    def test_allowlisted_erp_domain_accepted(self):
        """Real ERP domains should be accepted."""
        assert validate_domain("https://contpaqi.com/app") == "contpaqi.com"
        assert validate_domain("https://aspel.com.mx/app") == "aspel.com.mx"
        assert validate_domain("https://cfdi.sat.gob.mx/consulta") == "cfdi.sat.gob.mx"

    def test_subdomain_of_allowed_accepted(self):
        """Subdomain of an allowed domain should be accepted."""
        assert validate_domain("https://app.contpaqi.com/login") == "app.contpaqi.com"

    def test_extra_allowed_param(self):
        """extra_allowed parameter extends the allowlist."""
        result = validate_domain(
            "https://my-erp.company.com/app",
            extra_allowed=frozenset({"company.com"}),
        )
        assert result == "my-erp.company.com"

    def test_empty_url_blocked(self):
        """URL with no hostname → error."""
        with pytest.raises(DomainNotAllowedError, match="no hostname"):
            validate_domain("")

    def test_malformed_url_blocked(self):
        """Malformed URL → error."""
        with pytest.raises(DomainNotAllowedError):
            validate_domain("not-a-url")


# ---------------------------------------------------------------------------
# SSRF protection tests
# ---------------------------------------------------------------------------

class TestSSRFProtection:
    """Private/internal IPs must be blocked to prevent SSRF."""

    def test_localhost_blocked(self):
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://localhost:8000/api")

    def test_127_0_0_1_blocked(self):
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://127.0.0.1/admin")

    def test_0_0_0_0_blocked(self):
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://0.0.0.0:3000")

    def test_private_192_168_blocked(self):
        """RFC 1918 addresses should not be allowlisted."""
        with pytest.raises(DomainNotAllowedError):
            validate_domain("http://192.168.1.1/app")

    def test_private_10_blocked(self):
        with pytest.raises(DomainNotAllowedError):
            validate_domain("http://10.0.0.1/app")

    def test_example_com_blocked(self):
        """example.com is a reserved domain, must be hard-blocked."""
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("https://example.com/app")

    def test_example_org_blocked(self):
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("https://example.org/app")

    def test_ipv6_loopback_blocked(self):
        """IPv6 loopback should be blocked."""
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://[::1]:8080/app")

    def test_subdomain_of_blocked_domain_blocked(self):
        """Subdomain of a blocked domain should still be blocked."""
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://app.localhost:8000/api")


# ---------------------------------------------------------------------------
# Credential encryption tests
# ---------------------------------------------------------------------------

class TestCredentialEncryption:
    """Test encrypt/decrypt roundtrip with Fernet and degraded mode."""

    def test_encrypt_decrypt_roundtrip_with_key(self):
        """With B2B_ENCRYPTION_KEY set, encrypt→decrypt should roundtrip."""
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch.dict(os.environ, {"B2B_ENCRYPTION_KEY": key}):
            plaintext = "my-secret-password-123"
            encrypted = encrypt_credential(plaintext)
            assert encrypted != plaintext
            assert not encrypted.startswith("OBFUSCATED:")

            decrypted = decrypt_credential(encrypted)
            assert decrypted == plaintext

    def test_encrypt_decrypt_with_passphrase_key(self):
        """A non-base64 key should derive via SHA-256 and still work."""
        with patch.dict(os.environ, {"B2B_ENCRYPTION_KEY": "my-secret-passphrase"}):
            plaintext = "erp-password-456"
            encrypted = encrypt_credential(plaintext)
            decrypted = decrypt_credential(encrypted)
            assert decrypted == plaintext

    def test_degraded_mode_obfuscation(self):
        """Without B2B_ENCRYPTION_KEY, should use base64 obfuscation."""
        with patch.dict(os.environ, {"B2B_ENCRYPTION_KEY": ""}, clear=False):
            plaintext = "my-password"
            encrypted = encrypt_credential(plaintext)
            assert encrypted.startswith("OBFUSCATED:")

            decrypted = decrypt_credential(encrypted)
            assert decrypted == plaintext

    def test_empty_plaintext_returns_empty(self):
        assert encrypt_credential("") == ""
        assert decrypt_credential("") == ""

    def test_different_inputs_produce_different_ciphertext(self):
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch.dict(os.environ, {"B2B_ENCRYPTION_KEY": key}):
            enc1 = encrypt_credential("password-a")
            enc2 = encrypt_credential("password-b")
            assert enc1 != enc2

    def test_encrypted_value_is_not_plaintext(self):
        """Ensure the ciphertext doesn't contain the original password."""
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch.dict(os.environ, {"B2B_ENCRYPTION_KEY": key}):
            plaintext = "super-secret-123"
            encrypted = encrypt_credential(plaintext)
            assert plaintext not in encrypted


# ---------------------------------------------------------------------------
# Audit log tests
# ---------------------------------------------------------------------------

class TestAuditLog:
    """Immutable audit log: append-only, idempotent, queryable."""

    def test_log_and_query(self):
        log = AuditLog()
        entry = AuditEntry(
            tenant_id="t1", action="login", target="contpaqi",
            status="success",
        )
        entry_id = log.log(entry)
        assert entry_id == entry.entry_id

        results = log.query(tenant_id="t1", action="login")
        assert len(results) == 1
        assert results[0].action == "login"

    def test_idempotency_prevents_duplicate(self):
        log = AuditLog()
        key = "test-idem-key-001"
        e1 = AuditEntry(idempotency_key=key, action="register", tenant_id="t1")
        e2 = AuditEntry(idempotency_key=key, action="register", tenant_id="t1")

        id1 = log.log(e1)
        id2 = log.log(e2)
        assert id1 == id2  # Same entry returned
        assert log.check_idempotency(key) == id1

    def test_query_filters_by_tenant(self):
        log = AuditLog()
        log.log(AuditEntry(tenant_id="t1", action="login"))
        log.log(AuditEntry(tenant_id="t2", action="login"))

        assert len(log.query(tenant_id="t1")) == 1
        assert len(log.query(tenant_id="t2")) == 1
        assert len(log.query()) == 2

    def test_entry_is_immutable(self):
        """AuditEntry is a frozen dataclass."""
        entry = AuditEntry(action="test")
        with pytest.raises(AttributeError):
            entry.action = "changed"

    def test_to_dict_has_all_fields(self):
        entry = AuditEntry(
            tenant_id="t1", action="register", status="success",
            write_operation=True,
        )
        d = entry.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["action"] == "register"
        assert d["write_operation"] is True
        assert "entry_id" in d
        assert "timestamp_iso" in d

    def test_persist_to_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log = AuditLog(persist_path=path)
            log.log(AuditEntry(action="test_persist", tenant_id="t1"))
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            import json
            data = json.loads(lines[0])
            assert data["action"] == "test_persist"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Session manager tests
# ---------------------------------------------------------------------------

class TestSessionManager:
    """Per-tenant browser context isolation."""

    def test_create_and_get_session(self):
        mgr = SessionManager()
        ctx = mgr.create_session("tenant_1")
        assert ctx.tenant_id == "tenant_1"
        assert ctx.is_active is True

        retrieved = mgr.get_session(ctx.context_id)
        assert retrieved is not None
        assert retrieved.tenant_id == "tenant_1"

    def test_tenant_isolation(self):
        """Sessions from different tenants don't leak."""
        mgr = SessionManager()
        ctx1 = mgr.create_session("tenant_1")
        ctx2 = mgr.create_session("tenant_2")

        assert ctx1.context_id != ctx2.context_id
        assert mgr.get_session(ctx1.context_id).tenant_id == "tenant_1"
        assert mgr.get_session(ctx2.context_id).tenant_id == "tenant_2"

    def test_session_expiration(self):
        """Expired sessions should return None."""
        mgr = SessionManager(session_timeout_seconds=0)  # Immediate expiry
        ctx = mgr.create_session("tenant_1")
        time.sleep(0.01)
        assert mgr.get_session(ctx.context_id) is None

    def test_close_session(self):
        mgr = SessionManager()
        ctx = mgr.create_session("tenant_1")
        assert mgr.close_session(ctx.context_id) is True
        assert mgr.get_session(ctx.context_id) is None

    def test_max_sessions_per_tenant_eviction(self):
        """Exceeding max sessions evicts the oldest."""
        mgr = SessionManager(max_sessions_per_tenant=2)
        ctx1 = mgr.create_session("tenant_1")
        time.sleep(0.01)
        ctx2 = mgr.create_session("tenant_1")
        time.sleep(0.01)
        ctx3 = mgr.create_session("tenant_1")  # Should evict ctx1

        assert mgr.active_session_count() == 2
        assert mgr.get_session(ctx1.context_id) is None  # Evicted
        assert mgr.get_session(ctx2.context_id) is not None
        assert mgr.get_session(ctx3.context_id) is not None

    def test_purge_expired(self):
        mgr = SessionManager(session_timeout_seconds=0)
        mgr.create_session("t1")
        mgr.create_session("t2")
        time.sleep(0.01)
        purged = mgr.purge_expired()
        assert purged == 2
        assert mgr.active_session_count() == 0


# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------

class TestRBAC:
    """Write/fiscal permission enforcement."""

    def test_admin_has_write_permission(self):
        assert has_computer_use_permission("admin", "computer_use.write") is True

    def test_contador_has_write_permission(self):
        assert has_computer_use_permission("contador", "computer_use.write") is True

    def test_auxiliar_no_write_permission(self):
        assert has_computer_use_permission("auxiliar", "computer_use.write") is False

    def test_auditor_no_write_permission(self):
        assert has_computer_use_permission("auditor", "computer_use.write") is False

    def test_unknown_role_no_permissions(self):
        assert has_computer_use_permission("unknown", "computer_use.read") is False

    def test_require_write_permission_raises_for_auxiliar(self):
        with pytest.raises(PermissionError, match="auxiliar"):
            require_write_permission("auxiliar")

    def test_require_write_permission_ok_for_admin(self):
        require_write_permission("admin")  # Should not raise

    def test_require_fiscal_permission_raises_for_auxiliar(self):
        with pytest.raises(PermissionError, match="auxiliar"):
            require_fiscal_permission("auxiliar")

    def test_require_fiscal_permission_ok_for_contador(self):
        require_fiscal_permission("contador")  # Should not raise


# ---------------------------------------------------------------------------
# Write gate tests
# ---------------------------------------------------------------------------

class TestWriteGate:
    """Default read-only: writes disabled unless explicitly enabled."""

    def test_writes_disabled_by_default(self):
        with patch.dict(os.environ, {"B2B_COMPUTER_USE_ALLOW_WRITES": ""}, clear=False):
            assert writes_allowed() is False

    def test_writes_enabled_when_true(self):
        with patch.dict(os.environ, {"B2B_COMPUTER_USE_ALLOW_WRITES": "true"}):
            assert writes_allowed() is True

    def test_require_writes_raises_when_disabled(self):
        with patch.dict(os.environ, {"B2B_COMPUTER_USE_ALLOW_WRITES": "false"}):
            with pytest.raises(PermissionError, match="disabled"):
                require_writes_enabled()

    def test_require_writes_ok_when_enabled(self):
        with patch.dict(os.environ, {"B2B_COMPUTER_USE_ALLOW_WRITES": "true"}):
            require_writes_enabled()  # Should not raise


# ---------------------------------------------------------------------------
# Fiscal action / human confirmation tests
# ---------------------------------------------------------------------------

class TestFiscalActions:
    """Fiscal actions require human confirmation."""

    def test_register_invoice_is_fiscal(self):
        assert is_fiscal_action("register_invoice") is True

    def test_navigate_menu_not_fiscal(self):
        assert is_fiscal_action("navigate_menu") is False

    def test_require_human_confirmation_raises(self):
        with pytest.raises(PermissionError, match="human confirmation"):
            require_human_confirmation("register_invoice", confirmed=False)

    def test_require_human_confirmation_ok_when_confirmed(self):
        require_human_confirmation("register_invoice", confirmed=True)  # No raise

    def test_non_fiscal_action_skips_confirmation(self):
        require_human_confirmation("navigate_menu", confirmed=False)  # No raise


# ---------------------------------------------------------------------------
# Idempotency key tests
# ---------------------------------------------------------------------------

class TestIdempotencyKeys:
    """Deterministic idempotency keys prevent duplicate operations."""

    def test_key_is_deterministic(self):
        k1 = generate_idempotency_key("t1", "register", "contpaqi/inv")
        k2 = generate_idempotency_key("t1", "register", "contpaqi/inv")
        assert k1 == k2

    def test_different_inputs_different_keys(self):
        k1 = generate_idempotency_key("t1", "register", "contpaqi/inv")
        k2 = generate_idempotency_key("t2", "register", "contpaqi/inv")
        assert k1 != k2

    def test_payload_hash_deterministic(self):
        h1 = generate_payload_hash({"total": 100, "uuid": "abc"})
        h2 = generate_payload_hash({"uuid": "abc", "total": 100})  # Different order
        assert h1 == h2  # sort_keys ensures determinism

    def test_payload_hash_none_returns_empty(self):
        assert generate_payload_hash(None) == ""


# ---------------------------------------------------------------------------
# PII masking tests
# ---------------------------------------------------------------------------

class TestPIIMasking:
    """PII patterns must be masked in screenshots."""

    def test_mask_rfc(self):
        text = "Emisor RFC: XAXX010101000"
        masked = mask_pii_in_text(text)
        assert "XAXX010101000" not in masked
        assert "<RFC>" in masked

    def test_mask_phone(self):
        text = "Tel: +52 55 1234 5678"
        masked = mask_pii_in_text(text)
        assert "1234 5678" not in masked

    def test_mask_empty_text(self):
        assert mask_pii_in_text("") == ""
        # None input returns None (the guard is `if not text: return text`)
        assert mask_pii_in_text(None) is None

    def test_mask_pii_in_dict(self):
        data = {"rfc": "XAXX010101000", "nombre": "Test SA", "total": 100}
        masked = mask_pii_in_dict(data)
        assert "<RFC>" in masked["rfc"]
        assert masked["total"] == 100  # Non-string fields unchanged

    def test_mask_pii_in_nested_dict(self):
        data = {"emisor": {"rfc": "XAXX010101000", "nombre": "Test"}}
        masked = mask_pii_in_dict(data)
        assert "<RFC>" in masked["emisor"]["rfc"]


# ---------------------------------------------------------------------------
# SecurityConfig tests
# ---------------------------------------------------------------------------

class TestSecurityConfig:
    """Aggregated security config from environment."""

    def test_default_config(self):
        with patch.dict(os.environ, {
            "B2B_ENCRYPTION_KEY": "",
            "B2B_COMPUTER_USE_ALLOW_WRITES": "false",
        }, clear=False):
            cfg = SecurityConfig.from_env()
            assert cfg.allow_writes is False
            assert cfg.encryption_key_set is False

    def test_validate_warns_no_encryption_key(self):
        cfg = SecurityConfig(encryption_key_set=False)
        issues = cfg.validate()
        assert any("B2B_ENCRYPTION_KEY" in i for i in issues)

    def test_validate_warns_writes_enabled(self):
        cfg = SecurityConfig(allow_writes=True, encryption_key_set=True)
        issues = cfg.validate()
        assert any("B2B_COMPUTER_USE_ALLOW_WRITES" in i for i in issues)
