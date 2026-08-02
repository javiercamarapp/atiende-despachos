# -*- coding: utf-8 -*-
"""
Tests for Computer Use factory, config, and interface (FASE 2).

Covers:
    - DriverResult: status classification, to_dict, convenience constructors
    - ComputerUseConfig: from_env, validation rules (mock in prod, playwright creds, example.com)
    - ComputerUseDriverFactory: create with all modes and providers
    - DisabledDriver: all methods return configuration_error
    - MockComputerUseDriver: full lifecycle, state tracking
    - ComputerUseDriver ABC: cannot be instantiated directly
"""
import os
import pytest

from b2b_ai.computer_use.interface import (
    ComputerUseDriver,
    DriverResult,
    DriverResultStatus,
)
from b2b_ai.computer_use.config import (
    ComputerUseConfig,
    ComputerUseConfigurationError,
    VALID_PROVIDERS,
    VALID_MODES,
)
from b2b_ai.computer_use.factory import (
    ComputerUseDriverFactory,
    DisabledDriver,
    MockComputerUseDriver,
)
from b2b_ai.computer_use.contpaqi_real_driver import CONTPAQiRealDriver
from b2b_ai.computer_use.erp_web_base import ERPWebDriverBase


# =========================================================================
# DriverResult
# =========================================================================
class TestDriverResult:
    def test_success_ok_true(self):
        r = DriverResult.success("all good", count=42)
        assert r.ok is True
        assert r.status == DriverResultStatus.SUCCESS
        assert r.message == "all good"
        assert r.data["count"] == 42

    def test_failed_ok_false(self):
        r = DriverResult.failed("nope")
        assert r.ok is False
        assert r.status == DriverResultStatus.FAILED

    def test_all_statuses_covered(self):
        """Every enum variant has a convenience constructor."""
        constructors = {
            DriverResultStatus.SUCCESS: DriverResult.success,
            DriverResultStatus.FAILED: DriverResult.failed,
            DriverResultStatus.NEEDS_HUMAN_REVIEW: DriverResult.needs_human_review,
            DriverResultStatus.BLOCKED_BY_MFA: DriverResult.blocked_by_mfa,
            DriverResultStatus.BLOCKED_BY_CAPTCHA: DriverResult.blocked_by_captcha,
            DriverResultStatus.SELECTOR_NOT_FOUND: DriverResult.selector_not_found,
            DriverResultStatus.SESSION_EXPIRED: DriverResult.session_expired,
            DriverResultStatus.VERIFICATION_FAILED: DriverResult.verification_failed,
            DriverResultStatus.CONFIGURATION_ERROR: DriverResult.configuration_error,
        }
        for status, ctor in constructors.items():
            r = ctor("test")
            assert r.status == status, f"Constructor for {status} returned wrong status"

    def test_to_dict(self):
        r = DriverResult.success("ok", extra="value")
        d = r.to_dict()
        assert d["ok"] is True
        assert d["status"] == "success"
        assert d["message"] == "ok"
        assert d["extra"] == "value"

    def test_to_dict_failed(self):
        r = DriverResult.session_expired("expired")
        d = r.to_dict()
        assert d["ok"] is False
        assert d["status"] == "session_expired"


# =========================================================================
# ComputerUseConfig
# =========================================================================
class TestComputerUseConfig:
    def test_default_config(self):
        """Default mode is disabled — should validate without error."""
        cfg = ComputerUseConfig()
        assert cfg.mode == "disabled"
        assert cfg.provider == "contpaqi"
        assert cfg.is_disabled is True
        assert cfg.is_mock is False
        assert cfg.is_playwright is False

    def test_mock_mode_valid(self):
        cfg = ComputerUseConfig(mode="mock")
        cfg.validate()  # should not raise

    def test_unknown_provider_rejected(self):
        with pytest.raises(ComputerUseConfigurationError, match="Unknown provider"):
            ComputerUseConfig(provider="sap").validate()

    def test_unknown_mode_rejected(self):
        with pytest.raises(ComputerUseConfigurationError, match="Unknown mode"):
            ComputerUseConfig(mode="selenium").validate()

    def test_production_rejects_mock(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "production")
        cfg = ComputerUseConfig(mode="mock")
        with pytest.raises(ComputerUseConfigurationError, match="not allowed in production"):
            cfg.validate()

    def test_playwright_requires_url(self):
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="",
            contpaqi_username="admin",
            contpaqi_password="pass",
        )
        with pytest.raises(ComputerUseConfigurationError, match="requires a URL"):
            cfg.validate()

    def test_playwright_requires_username(self):
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://real.contpaqi.com",
            contpaqi_username="",
            contpaqi_password="pass",
        )
        with pytest.raises(ComputerUseConfigurationError, match="requires a username"):
            cfg.validate()

    def test_playwright_requires_password(self):
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://real.contpaqi.com",
            contpaqi_username="admin",
            contpaqi_password="",
        )
        with pytest.raises(ComputerUseConfigurationError, match="requires a password"):
            cfg.validate()

    def test_playwright_rejects_example_com(self):
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://contpaqiweb.example.com/app",
            contpaqi_username="admin",
            contpaqi_password="pass",
        )
        with pytest.raises(ComputerUseConfigurationError, match="example.com"):
            cfg.validate()

    def test_playwright_valid_real_credentials(self):
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://real.contpaqi.com",
            contpaqi_username="admin",
            contpaqi_password="s3cret",
        )
        cfg.validate()  # should not raise

    def test_from_env_defaults(self, monkeypatch):
        """from_env with no env vars set should give defaults."""
        monkeypatch.delenv("B2B_COMPUTER_USE_MODE", raising=False)
        monkeypatch.delenv("B2B_COMPUTER_USE_PROVIDER", raising=False)
        monkeypatch.delenv("B2B_ENV", raising=False)
        monkeypatch.setenv("B2B_ENV", "test")
        cfg = ComputerUseConfig.from_env()
        assert cfg.mode == "disabled"
        assert cfg.provider == "contpaqi"

    def test_from_env_playwright(self, monkeypatch):
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
        monkeypatch.setenv("B2B_COMPUTER_USE_PROVIDER", "contpaqi")
        monkeypatch.setenv("CONTPAQI_URL", "https://real.contpaqi.com")
        monkeypatch.setenv("CONTPAQI_USERNAME", "admin")
        monkeypatch.setenv("CONTPAQI_PASSWORD", "s3cret")
        monkeypatch.setenv("B2B_ENV", "test")
        cfg = ComputerUseConfig.from_env()
        assert cfg.mode == "playwright"
        assert cfg.is_playwright is True
        assert cfg.credentials["url"] == "https://real.contpaqi.com"

    def test_credentials_property(self):
        cfg = ComputerUseConfig(
            provider="aspel",
            aspel_url="https://aspel.example.com",
            aspel_username="user",
            aspel_password="pw",
        )
        creds = cfg.credentials
        assert creds["url"] == "https://aspel.example.com"
        assert creds["username"] == "user"
        assert creds["password"] == "pw"

    def test_repr_masks_password(self):
        cfg = ComputerUseConfig(
            contpaqi_password="supersecret"
        )
        r = repr(cfg)
        assert "supersecret" not in r

    def test_valid_providers_and_modes(self):
        assert "contpaqi" in VALID_PROVIDERS
        assert "aspel" in VALID_PROVIDERS
        assert "mock" in VALID_MODES
        assert "playwright" in VALID_MODES
        assert "disabled" in VALID_MODES


# =========================================================================
# DisabledDriver
# =========================================================================
class TestDisabledDriver:
    def test_all_methods_return_configuration_error(self):
        d = DisabledDriver()
        assert d.provider == "none"
        assert d.mode == "disabled"

        r = d.connect()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.login({})
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.verify_authenticated()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.logout()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.navigate_menu("facturas")
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.extract_invoices()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.capture_invoice_grid()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.register_invoice({})
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.register_poliza({})
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.verify_invoice_registered("xxx")
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.verify_poliza_registered("xxx")
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.health()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

        r = d.recover_from_error()
        assert r.status == DriverResultStatus.CONFIGURATION_ERROR

    def test_close_is_noop(self):
        d = DisabledDriver()
        d.close()  # should not raise


# =========================================================================
# MockComputerUseDriver
# =========================================================================
class TestMockComputerUseDriver:
    def test_provider_and_mode(self):
        d = MockComputerUseDriver(provider="aspel", tenant_id=7)
        assert d.provider == "aspel"
        assert d.mode == "mock"

    def test_full_lifecycle(self):
        d = MockComputerUseDriver(provider="contpaqi", tenant_id=42)

        # connect
        r = d.connect()
        assert r.ok

        # login
        r = d.login({"username": "admin", "password": "pass"})
        assert r.ok
        assert r.data["session"]["usuario"] == "admin"

        # verify_authenticated
        r = d.verify_authenticated()
        assert r.ok

        # navigate
        r = d.navigate_menu("facturas")
        assert r.ok
        assert r.data["module"] == "facturas"

        # register invoice
        r = d.register_invoice({"folio_fiscal": "ABC-123", "total": 1000})
        assert r.ok

        # verify registered
        r = d.verify_invoice_registered("ABC-123")
        assert r.ok

        # verify not found
        r = d.verify_invoice_registered("NOT-EXIST")
        assert r.status == DriverResultStatus.VERIFICATION_FAILED

        # register poliza
        r = d.register_poliza({"fecha": "2026-01-01", "monto": 500})
        assert r.ok

        # verify poliza
        r = d.verify_poliza_registered("2026-01-01")
        assert r.ok

        # extract invoices
        r = d.extract_invoices()
        assert r.ok
        assert len(r.data["invoices"]) == 1

        # capture grid
        r = d.capture_invoice_grid()
        assert r.ok

        # logout
        r = d.logout()
        assert r.ok

        # close
        d.close()

    def test_login_requires_connect(self):
        d = MockComputerUseDriver()
        r = d.login({"username": "admin"})
        # Mock enforces connect-before-login
        assert r.status == DriverResultStatus.FAILED
        assert "Must connect" in r.message

    def test_login_without_username_fails(self):
        d = MockComputerUseDriver()
        d.connect()
        r = d.login({})
        assert r.status == DriverResultStatus.FAILED
        assert "Missing username" in r.message

    def test_operations_require_session(self):
        d = MockComputerUseDriver()
        d.connect()
        # All these should fail with session_expired
        assert d.verify_authenticated().status == DriverResultStatus.SESSION_EXPIRED
        assert d.navigate_menu("facturas").status == DriverResultStatus.SESSION_EXPIRED
        assert d.extract_invoices().status == DriverResultStatus.SESSION_EXPIRED
        assert d.capture_invoice_grid().status == DriverResultStatus.SESSION_EXPIRED
        assert d.register_invoice({"folio_fiscal": "X"}).status == DriverResultStatus.SESSION_EXPIRED
        assert d.register_poliza({}).status == DriverResultStatus.SESSION_EXPIRED
        assert d.verify_invoice_registered("X").status == DriverResultStatus.SESSION_EXPIRED
        assert d.verify_poliza_registered("X").status == DriverResultStatus.SESSION_EXPIRED

    def test_register_invoice_requires_folio(self):
        d = MockComputerUseDriver()
        d.connect()
        d.login({"username": "u"})
        r = d.register_invoice({})
        assert r.status == DriverResultStatus.FAILED

    def test_unknown_module(self):
        d = MockComputerUseDriver()
        d.connect()
        d.login({"username": "u"})
        r = d.navigate_menu("invalid_module")
        assert r.status == DriverResultStatus.FAILED

    def test_health(self):
        d = MockComputerUseDriver(provider="aspel", tenant_id=5)
        r = d.health()
        assert r.ok
        assert r.data["provider"] == "aspel"

    def test_inject_invoices(self):
        d = MockComputerUseDriver()
        d.inject_invoices([{"folio_fiscal": "TEST-1"}])
        d.connect()
        d.login({"username": "u"})
        r = d.extract_invoices()
        assert r.ok
        assert len(r.data["invoices"]) == 1


# =========================================================================
# ComputerUseDriverFactory
# =========================================================================
class TestComputerUseDriverFactory:
    def test_create_disabled(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "test")
        d = ComputerUseDriverFactory.create(mode="disabled")
        assert isinstance(d, DisabledDriver)

    def test_create_mock(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "test")
        d = ComputerUseDriverFactory.create(mode="mock", provider="contpaqi", tenant_id=1)
        assert isinstance(d, MockComputerUseDriver)
        assert d.provider == "contpaqi"
        assert d.mode == "mock"

    def test_create_mock_aspel(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "test")
        d = ComputerUseDriverFactory.create(mode="mock", provider="aspel")
        assert d.provider == "aspel"

    def test_create_playwright(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "test")
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://real.contpaqi.com",
            contpaqi_username="admin",
            contpaqi_password="pass",
        )
        d = ComputerUseDriverFactory.create(
            provider="contpaqi", mode="playwright", config=cfg
        )
        assert isinstance(d, CONTPAQiRealDriver)
        assert d.mode == "playwright"

    def test_create_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "test")
        with pytest.raises(ComputerUseConfigurationError, match="Unknown provider"):
            ComputerUseDriverFactory.create(provider="sap", mode="mock")

    def test_create_unknown_mode_raises(self, monkeypatch):
        monkeypatch.setenv("B2B_ENV", "test")
        with pytest.raises(ComputerUseConfigurationError, match="Unknown mode"):
            ComputerUseDriverFactory.create(mode="selenium")

    def test_create_default_config_from_env(self, monkeypatch):
        """When no config is passed, factory reads from env."""
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "disabled")
        monkeypatch.setenv("B2B_ENV", "test")
        d = ComputerUseDriverFactory.create()
        assert isinstance(d, DisabledDriver)

    def test_create_mock_is_not_silent_fallback(self, monkeypatch):
        """Mock and playwright are distinct — no silent fallback."""
        monkeypatch.setenv("B2B_ENV", "test")
        d = ComputerUseDriverFactory.create(mode="mock")
        assert d.mode == "mock"
        # A real connection would fail; mock should never pretend to be real
        assert isinstance(d, MockComputerUseDriver)


# =========================================================================
# ComputerUseDriver ABC
# =========================================================================
class TestComputerUseDriverABC:
    def test_cannot_instantiate(self):
        """ComputerUseDriver is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            ComputerUseDriver()

    def test_mock_implements_interface(self):
        """MockComputerUseDriver is a proper subclass."""
        assert issubclass(MockComputerUseDriver, ComputerUseDriver)

    def test_disabled_implements_interface(self):
        """DisabledDriver is a proper subclass."""
        assert issubclass(DisabledDriver, ComputerUseDriver)

    def test_adapter_implements_interface(self):
        """CONTPAQiRealDriver (via ERPWebDriverBase) is a proper subclass."""
        assert issubclass(CONTPAQiRealDriver, ComputerUseDriver)
        assert issubclass(ERPWebDriverBase, ComputerUseDriver)

    def test_all_abstract_methods_present(self):
        """Verify the ABC declares the expected abstract methods."""
        expected = {
            "provider", "mode",  # properties
            "connect", "login", "verify_authenticated", "logout", "close",
            "navigate_menu", "extract_invoices", "capture_invoice_grid",
            "register_invoice", "register_poliza",
            "verify_invoice_registered", "verify_poliza_registered",
            "health", "recover_from_error",
        }
        actual = ComputerUseDriver.__abstractmethods__
        assert expected == actual, f"Mismatch: missing={expected - actual}, extra={actual - expected}"
