# -*- coding: utf-8 -*-
"""
test_compliance.py — Tests for the shared compliance infrastructure.

Covers:
  - CFF Art. 82: RFC masking
  - CFF Art. 89: Fiscal output metadata
  - ISR calculation (LISR Art. 96)
  - IVA rate validation (LIVA)
  - Audit trail
  - Input sanitization
  - SQL injection prevention
  - Tenant isolation
  - Output encoding
  - Idempotency keys
  - Error message safety
"""
from __future__ import annotations

import pytest

from b2b_ai.features.compliance import (
    AuditTrail,
    FiscalOutput,
    ManualProcessMixin,
    SafeError,
    calculate_isr,
    check_sql_injection,
    encode_output,
    generate_idempotency_key,
    get_audit_trail,
    mask_amount,
    mask_rfc,
    safe_log,
    sanitize_email,
    sanitize_rfc,
    sanitize_string,
    validate_iva_rate,
    verify_tenant_access,
)


class TestRfcMasking:
    """CFF Art. 82: Sensitive data masking in logs."""

    def test_mask_rfc_normal(self):
        masked = mask_rfc("EMP850101AB1")
        assert masked == "EMP***AB1"

    def test_mask_rfc_generic(self):
        masked = mask_rfc("XAXX010101AAA")
        assert "***" in masked

    def test_mask_rfc_short(self):
        masked = mask_rfc("AB")
        assert masked == "***"

    def test_mask_rfc_empty(self):
        masked = mask_rfc("")
        assert masked == "***"

    def test_mask_amount_normal(self):
        assert mask_amount(50000.0) == "50000.00"

    def test_mask_amount_large(self):
        assert mask_amount(150000.0) == "[REDACTED >100k]"

    def test_mask_amount_zero(self):
        assert mask_amount(0.0) == "0.00"


class TestFiscalOutput:
    """CFF Art. 89: Fiscal output metadata."""

    def test_fiscal_output_creation(self):
        output = FiscalOutput(
            referencia_legal="CFF Art. 89",
            supuesto="Declaración mensual IVA",
        )
        assert output.referencia_legal == "CFF Art. 89"
        assert output.requires_human_review is True
        assert output.idempotency_key != ""
        assert output.created_at != ""

    def test_fiscal_output_human_review(self):
        output = FiscalOutput(
            referencia_legal="LISR Art. 96",
            supuesto="Cálculo ISR provisional",
            requires_human_review=True,
            human_review_reason="Monto excede umbral",
        )
        assert output.requires_human_review is True
        assert output.human_review_reason == "Monto excede umbral"

    def test_fiscal_output_idempotency_key_unique(self):
        o1 = FiscalOutput(referencia_legal="test1", supuesto="s1")
        o2 = FiscalOutput(referencia_legal="test2", supuesto="s2")
        assert o1.idempotency_key != o2.idempotency_key


class TestISR:
    """LISR Art. 96: ISR progressive table."""

    def test_isr_zero_income(self):
        assert calculate_isr(0) == 0.0

    def test_isr_negative_income(self):
        assert calculate_isr(-1000) == 0.0

    def test_isr_first_bracket(self):
        # 100 * 1.92% = 1.92
        isr = calculate_isr(100.0)
        assert abs(isr - 1.92) < 0.01

    def test_isr_second_bracket(self):
        # 1000 in bracket (435.09-3666.30) of ISR_MENSUAL_2026:
        # (1000-435.09)*6.4% + 8.35 = 44.50
        expected = (1000 - 435.09) * 0.0640 + 8.35
        isr = calculate_isr(1000.0)
        assert abs(isr - round(expected, 2)) < 0.01

    def test_isr_high_income(self):
        # 100000 in bracket (95462.31, inf) of ISR_MENSUAL_2026:
        # (100000-95462.31)*35% + 28513.25 = 30101.44
        expected = (100000 - 95462.31) * 0.35 + 28513.25
        isr = calculate_isr(100000.0)
        assert abs(isr - round(expected, 2)) < 0.01

    def test_isr_annual(self):
        isr_annual = calculate_isr(500000.0, annual=True)
        assert isr_annual > 0


class TestIVA:
    """LIVA: IVA rates restricted to 0%, 8%, 16%."""

    def test_iva_16_percent(self):
        valid, msg = validate_iva_rate(0.16)
        assert valid is True

    def test_iva_8_percent(self):
        valid, msg = validate_iva_rate(0.08)
        assert valid is True

    def test_iva_0_percent(self):
        valid, msg = validate_iva_rate(0.0)
        assert valid is True

    def test_iva_invalid_rate(self):
        valid, msg = validate_iva_rate(0.25)
        assert valid is False
        assert "inválida" in msg or "invalid" in msg.lower()


class TestAuditTrail:
    """Audit trail logging."""

    def test_log_entry(self):
        trail = AuditTrail()
        entry = trail.log(
            user="test_user",
            action="create",
            module="test_module",
            result="success",
            tenant_id="t1",
        )
        assert entry.user == "test_user"
        assert entry.action == "create"
        assert entry.module == "test_module"
        assert entry.result == "success"
        assert entry.tenant_id == "t1"

    def test_get_entries(self):
        trail = AuditTrail()
        trail.log(user="u1", action="a1", module="m1", result="r1")
        trail.log(user="u2", action="a2", module="m2", result="r2")
        entries = trail.get_entries(module="m1")
        assert len(entries) == 1

    def test_count(self):
        trail = AuditTrail()
        trail.log(user="u1", action="a1", module="m1", result="r1")
        assert trail.count() == 1


class TestSanitization:
    """Input sanitization."""

    def test_sanitize_string_strip(self):
        assert sanitize_string("  hello  ") == "hello"

    def test_sanitize_string_truncate(self):
        long_str = "a" * 10000
        result = sanitize_string(long_str, max_length=100)
        assert len(result) == 100

    def test_sanitize_string_removes_script(self):
        malicious = '<script>alert("xss")</script>Hello'
        result = sanitize_string(malicious)
        assert "<script>" not in result
        assert "Hello" in result

    def test_sanitize_rfc(self):
        assert sanitize_rfc("  emp850101ab1  ") == "EMP850101AB1"

    def test_sanitize_rfc_too_long(self):
        assert len(sanitize_rfc("A" * 20)) == 13

    def test_sanitize_email(self):
        assert sanitize_email("  Test@Email.COM  ") == "test@email.com"


class TestSQLInjection:
    """SQL injection prevention."""

    def test_safe_input(self):
        is_safe, _ = check_sql_injection("Hello world 123")
        assert is_safe is True

    def test_detect_select(self):
        is_safe, msg = check_sql_injection("'; DROP TABLE users; --")
        assert is_safe is False

    def test_detect_union(self):
        is_safe, _ = check_sql_injection("1 UNION SELECT * FROM users")
        assert is_safe is False

    def test_detect_insert(self):
        is_safe, _ = check_sql_injection("INSERT INTO users VALUES")
        assert is_safe is False


class TestTenantIsolation:
    """Tenant isolation verification."""

    def test_same_tenant(self):
        allowed, msg = verify_tenant_access("t1", "t1")
        assert allowed is True

    def test_different_tenant(self):
        allowed, msg = verify_tenant_access("t1", "t2")
        assert allowed is False
        assert "tenant" in msg.lower()

    def test_missing_tenant(self):
        allowed, msg = verify_tenant_access("t1", "")
        assert allowed is False


class TestOutputEncoding:
    """Output encoding to prevent injection."""

    def test_encode_html(self):
        encoded = encode_output('<script>alert("xss")</script>')
        assert "<script>" not in encoded
        assert "&lt;" in encoded

    def test_encode_quotes(self):
        encoded = encode_output('He said "hello"')
        assert "&quot;" in encoded


class TestIdempotency:
    """Idempotency key generation."""

    def test_deterministic(self):
        k1 = generate_idempotency_key("mod", "op", x=1)
        k2 = generate_idempotency_key("mod", "op", x=1)
        assert k1 == k2

    def test_different_params(self):
        k1 = generate_idempotency_key("mod", "op", x=1)
        k2 = generate_idempotency_key("mod", "op", x=2)
        assert k1 != k2


class TestSafeError:
    """Error messages that don't leak internal state."""

    def test_safe_error(self):
        err = SafeError("Error de formato", internal_code="FMT_001")
        assert err.user_message == "Error de formato"
        d = err.to_dict()
        assert d["error"] == "Error de formato"
        assert "internal" not in d


class TestManualProcessMixin:
    """Manual process handling."""

    def test_create_fiscal_output(self):
        class MyService(ManualProcessMixin):
            pass
        svc = MyService()
        output = svc.create_fiscal_output(
            referencia_legal="CFF Art. 89",
            supuesto="Test",
        )
        assert output.referencia_legal == "CFF Art. 89"
        assert len(svc._fiscal_outputs) == 1

    def test_idempotency_check(self):
        class MyService(ManualProcessMixin):
            pass
        svc = MyService()
        assert svc.check_idempotency("key1") is False  # First time
        assert svc.check_idempotency("key1") is True  # Duplicate

    def test_audit_logging(self):
        class MyService(ManualProcessMixin):
            pass
        svc = MyService()
        entry = svc.log_audit(
            user="test",
            action="process",
            module="test_mod",
            result="ok",
            tenant_id="t1",
        )
        assert entry.user == "test"

    def test_fiscal_output_escalation(self):
        class MyService(ManualProcessMixin):
            pass
        svc = MyService()
        output = svc.create_fiscal_output(
            referencia_legal="LISR Art. 96",
            supuesto="ISR",
            escalation_path="escalate_to_director",
        )
        assert output.escalation_path == "escalate_to_director"

    def test_fiscal_output_no_human_review(self):
        class MyService(ManualProcessMixin):
            pass
        svc = MyService()
        output = svc.create_fiscal_output(
            referencia_legal="LIVA",
            supuesto="IVA 16%",
            requires_human_review=False,
        )
        assert output.requires_human_review is False
