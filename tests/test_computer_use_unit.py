# -*- coding: utf-8 -*-
"""test_computer_use_unit.py — Unit tests for Computer Use module.

Tests: factory, config, security, interface, driver states, idempotency,
tenant isolation, URL validation, secret redaction, session/cleanup.
"""
import os
import pytest
import tempfile
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------
class TestComputerUseConfig:
    """Test ComputerUseConfig from_env and validate."""

    def test_default_mode_is_disabled(self):
        from b2b_ai.computer_use.config import ComputerUseConfig
        cfg = ComputerUseConfig()
        assert cfg.mode == "disabled"

    def test_from_env_reads_vars(self):
        from b2b_ai.computer_use.config import ComputerUseConfig
        with patch.dict(os.environ, {
            "B2B_COMPUTER_USE_MODE": "mock",
            "B2B_COMPUTER_USE_PROVIDER": "aspel",
            "B2B_COMPUTER_USE_HEADLESS": "false",
            "B2B_COMPUTER_USE_TIMEOUT_SECONDS": "45",
        }):
            cfg = ComputerUseConfig.from_env()
            assert cfg.mode == "mock"
            assert cfg.provider == "aspel"
            assert cfg.headless is False
            assert cfg.timeout_seconds == 45

    def test_production_rejects_mock(self):
        from b2b_ai.computer_use.config import ComputerUseConfig, ComputerUseConfigurationError
        cfg = ComputerUseConfig(mode="mock", provider="contpaqi")
        with patch.dict(os.environ, {"B2B_ENV": "production"}):
            with pytest.raises(ComputerUseConfigurationError, match="mock.*production"):
                cfg.validate()

    def test_playwright_rejects_example_com(self):
        from b2b_ai.computer_use.config import ComputerUseConfig, ComputerUseConfigurationError
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://example.com/app",
            contpaqi_username="admin",
            contpaqi_password="pass",
        )
        with pytest.raises(ComputerUseConfigurationError, match="example.com"):
            cfg.validate()

    def test_playwright_requires_credentials(self):
        from b2b_ai.computer_use.config import ComputerUseConfig, ComputerUseConfigurationError
        cfg = ComputerUseConfig(mode="playwright", contpaqi_url="", contpaqi_username="")
        with pytest.raises(ComputerUseConfigurationError):
            cfg.validate()

    def test_allow_writes_defaults_false(self):
        from b2b_ai.computer_use.config import ComputerUseConfig
        cfg = ComputerUseConfig()
        assert cfg.allow_writes is False


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------
class TestComputerUseFactory:
    """Test ComputerUseDriverFactory.create."""

    def test_disabled_returns_disabled_driver(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory, DisabledDriver
        driver = ComputerUseDriverFactory.create(mode="disabled")
        assert isinstance(driver, DisabledDriver)
        assert driver.mode == "disabled"

    def test_mock_returns_mock_driver(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory, MockComputerUseDriver
        driver = ComputerUseDriverFactory.create(mode="mock", provider="contpaqi")
        assert isinstance(driver, MockComputerUseDriver)
        assert driver.mode == "mock"
        assert driver.provider == "contpaqi"

    def test_unknown_mode_raises(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        from b2b_ai.computer_use.config import ComputerUseConfigurationError
        with pytest.raises(ComputerUseConfigurationError, match="Unknown mode"):
            ComputerUseDriverFactory.create(mode="invalid")

    def test_unknown_provider_raises(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        from b2b_ai.computer_use.config import ComputerUseConfigurationError
        with pytest.raises(ComputerUseConfigurationError, match="Unknown provider"):
            ComputerUseDriverFactory.create(mode="mock", provider="oracle")

    def test_mock_with_tenant_id(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="mock", tenant_id=42)
        assert driver._tenant_id == 42

    def test_factory_does_not_silently_fall_back(self):
        """If mode=playwright but credentials are missing, it MUST raise — never silently give mock."""
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        from b2b_ai.computer_use.config import ComputerUseConfigurationError
        with patch.dict(os.environ, {
            "B2B_COMPUTER_USE_MODE": "playwright",
            "CONTPAQI_URL": "",
            "CONTPAQI_USERNAME": "",
            "CONTPAQI_PASSWORD": "",
        }, clear=False):
            with pytest.raises(ComputerUseConfigurationError):
                ComputerUseDriverFactory.create(mode="playwright")


# ---------------------------------------------------------------------------
# Interface / DriverResult tests
# ---------------------------------------------------------------------------
class TestDriverResult:
    """Test DriverResult and DriverResultStatus."""

    def test_success_is_ok(self):
        from b2b_ai.computer_use.interface import DriverResult
        r = DriverResult.success("all good", extra=42)
        assert r.ok is True
        assert r.status.value == "success"
        assert r.message == "all good"
        assert r.data["extra"] == 42

    def test_failed_is_not_ok(self):
        from b2b_ai.computer_use.interface import DriverResult
        r = DriverResult.failed("broken")
        assert r.ok is False
        assert r.status.value == "failed"

    def test_session_expired_status(self):
        from b2b_ai.computer_use.interface import DriverResult, DriverResultStatus
        r = DriverResult.session_expired("token invalid")
        assert r.status == DriverResultStatus.SESSION_EXPIRED
        assert r.ok is False

    def test_verification_failed_status(self):
        from b2b_ai.computer_use.interface import DriverResult
        r = DriverResult.verification_failed("not found in ERP")
        assert r.ok is False
        assert "not found" in r.message

    def test_selector_not_found_status(self):
        from b2b_ai.computer_use.interface import DriverResult
        r = DriverResult.selector_not_found("#missing-element")
        assert r.ok is False

    def test_to_dict(self):
        from b2b_ai.computer_use.interface import DriverResult
        r = DriverResult.success("ok", key="val")
        d = r.to_dict()
        assert d["ok"] is True
        assert d["status"] == "success"
        assert d["key"] == "val"


# ---------------------------------------------------------------------------
# Mock driver tests
# ---------------------------------------------------------------------------
class TestMockComputerUseDriver:
    """Test MockComputerUseDriver lifecycle."""

    def test_full_lifecycle(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="mock", tenant_id=1)
        # Connect
        r = driver.connect()
        assert r.ok
        # Login
        r = driver.login({"username": "admin", "password": "pass"})
        assert r.ok
        # Verify auth
        r = driver.verify_authenticated()
        assert r.ok
        # Navigate
        r = driver.navigate_menu("facturas")
        assert r.ok
        # Register invoice
        r = driver.register_invoice({"folio_fiscal": "ABC-123", "total": 1000})
        assert r.ok
        # Verify registered
        r = driver.verify_invoice_registered("ABC-123")
        assert r.ok
        # Register poliza
        r = driver.register_poliza({"poliza_id": "POL-001"})
        assert r.ok
        # Verify poliza
        r = driver.verify_poliza_registered("POL-001")
        assert r.ok
        # Health
        r = driver.health()
        assert r.ok
        # Logout
        r = driver.logout()
        assert r.ok
        # Close
        driver.close()

    def test_login_without_connect_fails(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="mock")
        r = driver.login({"username": "admin"})
        assert not r.ok

    def test_login_without_username_fails(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="mock")
        driver.connect()
        r = driver.login({})
        assert not r.ok

    def test_navigate_unknown_module_fails(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="mock")
        driver.connect()
        driver.login({"username": "admin"})
        r = driver.navigate_menu("nonexistent")
        assert not r.ok

    def test_verify_unregistered_invoice_fails(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="mock")
        driver.connect()
        driver.login({"username": "admin"})
        r = driver.verify_invoice_registered("DOES-NOT-EXIST")
        assert not r.ok

    def test_tenant_isolation(self):
        """Two mock drivers with different tenants don't share state."""
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        d1 = ComputerUseDriverFactory.create(mode="mock", tenant_id=1)
        d2 = ComputerUseDriverFactory.create(mode="mock", tenant_id=2)
        d1.connect()
        d1.login({"username": "admin"})
        d1.register_invoice({"folio_fiscal": "T1-001"})
        d2.connect()
        d2.login({"username": "admin"})
        # d2 should NOT see d1's invoice
        r = d2.verify_invoice_registered("T1-001")
        assert not r.ok


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------
class TestComputerUseSecurity:
    """Test domain validation, blocked domains, etc."""

    def test_example_com_blocked(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError):
            validate_domain("https://example.com/app")

    def test_localhost_blocked(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError):
            validate_domain("http://localhost:8000")

    def test_valid_erp_domain_accepted(self):
        from b2b_ai.computer_use.security import validate_domain
        result = validate_domain("https://contpaqi.contpaqi.com/app")
        assert "contpaqi.com" in result

    def test_private_ip_blocked_by_default(self):
        from b2b_ai.computer_use.security import validate_domain, DomainNotAllowedError
        with pytest.raises(DomainNotAllowedError):
            validate_domain("http://192.168.1.1/app")

    def test_sat_domain_allowed_readonly(self):
        from b2b_ai.computer_use.security import validate_domain
        result = validate_domain("https://cfdi.sat.gob.mx/consulta")
        assert "sat.gob.mx" in result


# ---------------------------------------------------------------------------
# Disabled driver tests
# ---------------------------------------------------------------------------
class TestDisabledDriver:
    """Test that DisabledDriver returns configuration_error for everything."""

    def test_all_operations_return_disabled(self):
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        driver = ComputerUseDriverFactory.create(mode="disabled")
        assert driver.connect().status.value == "configuration_error"
        assert driver.login({}).status.value == "configuration_error"
        assert driver.verify_authenticated().status.value == "configuration_error"
        assert driver.navigate_menu("x").status.value == "configuration_error"
        assert driver.extract_invoices().status.value == "configuration_error"
        assert driver.register_invoice({}).status.value == "configuration_error"
        assert driver.register_poliza({}).status.value == "configuration_error"
        assert driver.health().status.value == "configuration_error"
        assert driver.recover_from_error().status.value == "configuration_error"
        driver.close()  # should not raise
