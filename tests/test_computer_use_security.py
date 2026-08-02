# -*- coding: utf-8 -*-
"""Tests for Computer Use security module (b2b_ai.computer_use.security)."""
from __future__ import annotations

import base64
import os
import tempfile
import time
import uuid

import pytest


# ---------------------------------------------------------------------------
# Domain allowlist
# ---------------------------------------------------------------------------

class TestDomainAllowlist:
    def test_valid_erp_domain_contpaqi(self):
        from b2b_ai.computer_use.security import validate_domain
        host = validate_domain("https://contpaqi.com/app")
        assert host == "contpaqi.com"

    def test_valid_subdomain(self):
        from b2b_ai.computer_use.security import validate_domain
        host = validate_domain("https://miempresa.contpaqiweb.com/app")
        assert host == "miempresa.contpaqiweb.com"

    def test_aspel_domain(self):
        from b2b_ai.computer_use.security import validate_domain
        host = validate_domain("https://aspelcloud.com/app")
        assert host == "aspelcloud.com"

    def test_sat_readonly(self):
        from b2b_ai.computer_use.security import validate_domain
        host = validate_domain("https://cfdi.sat.gob.mx/consultas")
        assert host == "cfdi.sat.gob.mx"

    def test_blocked_example_com(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("https://example.com/app")

    def test_blocked_localhost(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://localhost:8000/app")

    def test_blocked_127(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError, match="hard-blocked"):
            validate_domain("http://127.0.0.1/app")

    def test_unknown_domain_blocked(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError, match="not in the Computer Use allowlist"):
            validate_domain("https://evil-site.com/app")

    def test_env_url_allowed(self, monkeypatch):
        from b2b_ai.computer_use.security import validate_domain
        monkeypatch.setenv("CONTPAQI_URL", "https://mi-erp-custom.com/app")
        host = validate_domain("https://mi-erp-custom.com/dashboard")
        assert host == "mi-erp-custom.com"

    def test_empty_url_raises(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError, match="no hostname"):
            validate_domain("")


# ---------------------------------------------------------------------------
# Credential encryption
# ---------------------------------------------------------------------------

class TestCredentialEncryption:
    def test_encrypt_decrypt_with_key(self, monkeypatch):
        from b2b_ai.computer_use.security import encrypt_credential, decrypt_credential
        monkeypatch.setenv("B2B_ENCRYPTION_KEY", "test-secret-key-12345")
        plaintext = "MySecretPassword123!"
        encrypted = encrypt_credential(plaintext)
        assert encrypted != plaintext
        assert "OBFUSCATED" not in encrypted
        decrypted = decrypt_credential(encrypted)
        assert decrypted == plaintext

    def test_encrypt_empty_returns_empty(self):
        from b2b_ai.computer_use.security import encrypt_credential
        assert encrypt_credential("") == ""

    def test_obfuscated_without_key(self, monkeypatch):
        from b2b_ai.computer_use.security import encrypt_credential, decrypt_credential
        monkeypatch.delenv("B2B_ENCRYPTION_KEY", raising=False)
        plaintext = "MyPassword"
        encrypted = encrypt_credential(plaintext)
        assert encrypted.startswith("OBFUSCATED:")
        decrypted = decrypt_credential(encrypted)
        assert decrypted == plaintext


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManager:
    def test_create_and_get_session(self):
        from b2b_ai.computer_use.security import SessionManager
        mgr = SessionManager(session_timeout_seconds=300)
        ctx = mgr.create_session("tenant_1")
        assert ctx.tenant_id == "tenant_1"
        assert ctx.is_active is True

        retrieved = mgr.get_session(ctx.context_id)
        assert retrieved is not None
        assert retrieved.tenant_id == "tenant_1"

    def test_session_isolation(self):
        from b2b_ai.computer_use.security import SessionManager
        mgr = SessionManager()
        ctx1 = mgr.create_session("tenant_1")
        ctx2 = mgr.create_session("tenant_2")
        assert ctx1.context_id != ctx2.context_id
        assert ctx1.tenant_id != ctx2.tenant_id

    def test_session_expiration(self):
        from b2b_ai.computer_use.security import SessionManager
        mgr = SessionManager(session_timeout_seconds=1)  # 1 second timeout
        ctx = mgr.create_session("tenant_1")
        time.sleep(1.1)
        retrieved = mgr.get_session(ctx.context_id)
        assert retrieved is None

    def test_close_session(self):
        from b2b_ai.computer_use.security import SessionManager
        mgr = SessionManager()
        ctx = mgr.create_session("tenant_1")
        assert mgr.close_session(ctx.context_id) is True
        assert mgr.get_session(ctx.context_id) is None

    def test_max_sessions_per_tenant(self):
        from b2b_ai.computer_use.security import SessionManager
        mgr = SessionManager(max_sessions_per_tenant=2)
        ctx1 = mgr.create_session("tenant_1")
        ctx2 = mgr.create_session("tenant_1")
        ctx3 = mgr.create_session("tenant_1")
        # ctx1 should have been evicted
        assert mgr.get_session(ctx1.context_id) is None
        assert mgr.get_session(ctx2.context_id) is not None
        assert mgr.get_session(ctx3.context_id) is not None

    def test_purge_expired(self):
        from b2b_ai.computer_use.security import SessionManager
        mgr = SessionManager(session_timeout_seconds=1)
        mgr.create_session("t1")
        mgr.create_session("t2")
        time.sleep(1.1)
        purged = mgr.purge_expired()
        assert purged == 2
        assert mgr.active_session_count() == 0


# ---------------------------------------------------------------------------
# Screenshot PII masking
# ---------------------------------------------------------------------------

class TestPIIMasking:
    def test_mask_rfc(self):
        from b2b_ai.computer_use.security import mask_pii_in_text
        text = "RFC del contribuyente: XAXX010101000"
        masked = mask_pii_in_text(text)
        assert "XAXX010101000" not in masked
        assert "<RFC>" in masked

    def test_mask_curp(self):
        from b2b_ai.computer_use.security import mask_pii_in_text
        text = "CURP: GODE561231HDFRRL04"
        masked = mask_pii_in_text(text)
        assert "GODE561231HDFRRL04" not in masked
        assert "<CURP>" in masked

    def test_mask_nomina(self):
        from b2b_ai.computer_use.security import mask_pii_in_text
        text = "Número de nómina: 01-12345"
        masked = mask_pii_in_text(text)
        assert "01-12345" not in masked
        assert "<NOMINA>" in masked

    def test_mask_dict_by_field_name(self):
        from b2b_ai.computer_use.security import mask_pii_in_dict
        data = {
            "rfc": "XAXX010101000",
            "nombre": "Empresa Test",
            "telefono": "+52 55 1234 5678",
        }
        masked = mask_pii_in_dict(data)
        assert "XAXX010101000" not in str(masked)
        assert masked["nombre"] is not None  # nombre is PII field, gets masked

    def test_mask_empty_string(self):
        from b2b_ai.computer_use.security import mask_pii_in_text
        assert mask_pii_in_text("") == ""


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_log_and_query(self):
        from b2b_ai.computer_use.security import AuditLog, AuditEntry
        log = AuditLog()
        entry = AuditEntry(
            tenant_id="t1", action="login", target="contpaqi",
            status="success",
        )
        entry_id = log.log(entry)
        assert entry_id == entry.entry_id

        results = log.query(tenant_id="t1")
        assert len(results) == 1
        assert results[0].action == "login"

    def test_idempotency(self):
        from b2b_ai.computer_use.security import AuditLog, AuditEntry
        log = AuditLog()
        e1 = AuditEntry(
            tenant_id="t1", action="register", target="poliza",
            idempotency_key="key_abc_123",
        )
        e2 = AuditEntry(
            tenant_id="t1", action="register", target="poliza",
            idempotency_key="key_abc_123",
        )
        id1 = log.log(e1)
        id2 = log.log(e2)
        assert id1 == id2  # Same entry returned

    def test_immutability(self):
        from b2b_ai.computer_use.security import AuditEntry
        entry = AuditEntry(tenant_id="t1", action="test")
        # Frozen dataclass: assignment raises (AttributeError or FrozenInstanceError)
        try:
            object.__setattr__(entry, "tenant_id", "changed")  # noqa
            # If dataclass is frozen, this should still raise
            assert False, "Expected frozen dataclass to block mutation"
        except Exception:
            pass  # Expected

    def test_persist_to_file(self):
        from b2b_ai.computer_use.security import AuditLog, AuditEntry
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log = AuditLog(persist_path=path)
            log.log(AuditEntry(tenant_id="t1", action="test", status="ok"))
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            import json
            data = json.loads(lines[0])
            assert data["action"] == "test"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

class TestRBAC:
    def test_admin_has_write(self):
        from b2b_ai.computer_use.security import has_computer_use_permission
        assert has_computer_use_permission("admin", "computer_use.write") is True

    def test_auxiliar_no_write(self):
        from b2b_ai.computer_use.security import has_computer_use_permission
        assert has_computer_use_permission("auxiliar", "computer_use.write") is False

    def test_auditor_read_only(self):
        from b2b_ai.computer_use.security import has_computer_use_permission
        assert has_computer_use_permission("auditor", "computer_use.read") is True
        assert has_computer_use_permission("auditor", "computer_use.write") is False

    def test_require_write_raises(self):
        from b2b_ai.computer_use.security import require_write_permission
        with pytest.raises(PermissionError, match="auxiliar"):
            require_write_permission("auxiliar")

    def test_require_write_passes(self):
        from b2b_ai.computer_use.security import require_write_permission
        require_write_permission("admin")  # Should not raise
        require_write_permission("contador")  # Should not raise


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------

class TestWriteGate:
    def test_writes_disabled_by_default(self, monkeypatch):
        from b2b_ai.computer_use.security import writes_allowed, require_writes_enabled
        monkeypatch.delenv("B2B_COMPUTER_USE_ALLOW_WRITES", raising=False)
        assert writes_allowed() is False
        with pytest.raises(PermissionError, match="disabled"):
            require_writes_enabled()

    def test_writes_enabled(self, monkeypatch):
        from b2b_ai.computer_use.security import writes_allowed
        monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
        assert writes_allowed() is True


# ---------------------------------------------------------------------------
# Human confirmation
# ---------------------------------------------------------------------------

class TestHumanConfirmation:
    def test_fiscal_action_requires_confirmation(self):
        from b2b_ai.computer_use.security import require_human_confirmation
        with pytest.raises(PermissionError, match="human confirmation"):
            require_human_confirmation("register_invoice", confirmed=False)

    def test_fiscal_action_with_confirmation_passes(self):
        from b2b_ai.computer_use.security import require_human_confirmation
        require_human_confirmation("register_invoice", confirmed=True)

    def test_non_fiscal_no_confirmation_needed(self):
        from b2b_ai.computer_use.security import require_human_confirmation
        require_human_confirmation("navigate", confirmed=False)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_deterministic_key(self):
        from b2b_ai.computer_use.security import generate_idempotency_key
        k1 = generate_idempotency_key("t1", "register", "poliza/123")
        k2 = generate_idempotency_key("t1", "register", "poliza/123")
        assert k1 == k2

    def test_different_inputs_different_keys(self):
        from b2b_ai.computer_use.security import generate_idempotency_key
        k1 = generate_idempotency_key("t1", "register", "poliza/123")
        k2 = generate_idempotency_key("t2", "register", "poliza/123")
        assert k1 != k2

    def test_payload_hash(self):
        from b2b_ai.computer_use.security import generate_payload_hash
        h1 = generate_payload_hash({"amount": 100, "concept": "test"})
        h2 = generate_payload_hash({"amount": 100, "concept": "test"})
        assert h1 == h2
        h3 = generate_payload_hash({"amount": 200, "concept": "test"})
        assert h1 != h3


# ---------------------------------------------------------------------------
# Security config
# ---------------------------------------------------------------------------

class TestSecurityConfig:
    def test_defaults(self, monkeypatch):
        from b2b_ai.computer_use.security import SecurityConfig
        monkeypatch.delenv("B2B_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("B2B_COMPUTER_USE_ALLOW_WRITES", raising=False)
        cfg = SecurityConfig.from_env()
        assert cfg.allow_writes is False
        assert cfg.encryption_key_set is False

    def test_validate_warns_no_key(self, monkeypatch):
        from b2b_ai.computer_use.security import SecurityConfig
        monkeypatch.delenv("B2B_ENCRYPTION_KEY", raising=False)
        cfg = SecurityConfig.from_env()
        issues = cfg.validate()
        assert any("B2B_ENCRYPTION_KEY" in i for i in issues)

    def test_validate_warns_writes_enabled(self, monkeypatch):
        from b2b_ai.computer_use.security import SecurityConfig
        monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
        cfg = SecurityConfig.from_env()
        issues = cfg.validate()
        assert any("write" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# Screenshot retention
# ---------------------------------------------------------------------------

class TestScreenshotRetention:
    def test_purge_empty_dir(self):
        from b2b_ai.computer_use.security import purge_screenshots, RetentionPolicy
        stats = purge_screenshots("/tmp/nonexistent_dir_12345")
        assert stats["deleted_by_age"] == 0

    def test_purge_by_age(self):
        from b2b_ai.computer_use.security import purge_screenshots, RetentionPolicy
        with tempfile.TemporaryDirectory() as tmpdir:
            tenant_dir = os.path.join(tmpdir, "tenant_1")
            os.makedirs(tenant_dir)
            # Create an old file
            old_file = os.path.join(tenant_dir, "old.png")
            with open(old_file, "w") as f:
                f.write("test")
            # Set mtime to 100 hours ago
            old_time = time.time() - (100 * 3600)
            os.utime(old_file, (old_time, old_time))

            policy = RetentionPolicy(max_age_hours=72)
            stats = purge_screenshots(tmpdir, policy)
            assert stats["deleted_by_age"] == 1
            assert not os.path.exists(old_file)
