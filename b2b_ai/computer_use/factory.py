# -*- coding: utf-8 -*-
"""
factory.py — Factory for creating Computer Use driver instances.

ComputerUseDriverFactory.create() is the single entry point. It inspects
the config to determine which concrete driver to instantiate:

    mode=mock       → MockComputerUseDriver (in-memory, safe for tests)
    mode=playwright → CONTPAQiRealDriver / AspelRealDriver (real browser)
    mode=disabled   → DisabledDriver (no-op, always returns disabled status)

The factory NEVER silently falls back from real to mock. If a playwright
driver fails to initialize, the caller gets a configuration_error — not a
mock pretending to be real.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from b2b_ai.computer_use.config import ComputerUseConfig, ComputerUseConfigurationError
from b2b_ai.computer_use.interface import (
    ComputerUseDriver,
    DriverResult,
    DriverResultStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Disabled driver (no-op stub)
# ---------------------------------------------------------------------------
class DisabledDriver(ComputerUseDriver):
    """No-op driver that returns configuration_error for every operation.

    Used when mode=disabled — the system is explicitly configured to not
    automate the ERP.
    """

    _PROVIDER = "none"
    _MODE = "disabled"

    @property
    def provider(self) -> str:
        return self._PROVIDER

    @property
    def mode(self) -> str:
        return self._MODE

    def connect(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def login(self, credentials: Dict[str, Any]) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def verify_authenticated(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def logout(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def close(self) -> None:
        pass

    def navigate_menu(self, module: str) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def extract_invoices(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def capture_invoice_grid(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def register_invoice(self, data: Dict[str, Any]) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def register_poliza(self, data: Dict[str, Any]) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def verify_invoice_registered(self, folio_fiscal: str) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def verify_poliza_registered(self, poliza_id: str) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def health(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")

    def recover_from_error(self) -> DriverResult:
        return DriverResult.configuration_error("Computer Use is disabled.")


# ---------------------------------------------------------------------------
# Mock driver (in-memory, for tests and development)
# ---------------------------------------------------------------------------
class MockComputerUseDriver(ComputerUseDriver):
    """In-memory mock driver for testing and development.

    Implements the full ComputerUseDriver interface without any external
    dependencies. Maintains state in memory for test assertions.
    """

    def __init__(self, provider: str = "contpaqi", tenant_id: Optional[int] = None):
        self._provider = provider
        self._tenant_id = tenant_id
        self._connected = False
        self._session: Optional[Dict[str, Any]] = None
        self._current_module: Optional[str] = None
        self._invoices: list = []
        self._polizas: list = []
        self._closed = False

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def mode(self) -> str:
        return "mock"

    def connect(self) -> DriverResult:
        self._connected = True
        return DriverResult.success(
            message=f"Mock connected to {self._provider}",
            provider=self._provider,
            tenant_id=self._tenant_id,
        )

    def login(self, credentials: Dict[str, Any]) -> DriverResult:
        if not self._connected:
            return DriverResult.failed("Must connect before login.")
        usuario = (credentials or {}).get("username") or (credentials or {}).get("usuario", "")
        if not usuario:
            return DriverResult.failed("Missing username/usuario in credentials.")
        self._session = {
            "usuario": usuario,
            "provider": self._provider,
            "tenant_id": self._tenant_id,
        }
        return DriverResult.success(
            message=f"Mock login as {usuario} on {self._provider}",
            session=self._session,
        )

    def verify_authenticated(self) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("No active session.")
        return DriverResult.success("Session is valid.")

    def logout(self) -> DriverResult:
        if not self._session:
            return DriverResult.failed("No active session to logout.")
        user = self._session.get("usuario", "")
        self._session = None
        self._current_module = None
        return DriverResult.success(message=f"Logged out {user}.")

    def close(self) -> None:
        self._closed = True
        self._session = None
        self._connected = False

    def navigate_menu(self, module: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        valid = {"facturas", "catalogos", "reportes", "nominas"}
        if module not in valid:
            return DriverResult.failed(
                f"Unknown module '{module}'. Valid: {sorted(valid)}"
            )
        self._current_module = module
        return DriverResult.success(
            message=f"Navigated to {module}", module=module
        )

    def extract_invoices(self) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        return DriverResult.success(
            message=f"Extracted {len(self._invoices)} invoices.",
            invoices=list(self._invoices),
        )

    def capture_invoice_grid(self) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        return DriverResult.success(
            message=f"Grid captured: {len(self._invoices)} rows.",
            grid=list(self._invoices),
        )

    def register_invoice(self, data: Dict[str, Any]) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        folio = (data or {}).get("folio_fiscal")
        if not folio:
            return DriverResult.failed("Missing 'folio_fiscal'.")
        registro = {
            "folio_fiscal": folio,
            "total": data.get("total"),
            "emisor_rfc": data.get("emisor_rfc"),
            "status": "pendiente_revision",
        }
        self._invoices.append(registro)
        return DriverResult.success(
            message=f"Invoice {folio} registered.", registro=registro
        )

    def register_poliza(self, data: Dict[str, Any]) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        poliza_id = (data or {}).get("poliza_id") or (data or {}).get("fecha", "mock-poliza")
        registro = {"poliza_id": poliza_id, "status": "registrada"}
        self._polizas.append(registro)
        return DriverResult.success(
            message=f"Póliza {poliza_id} registered.", registro=registro
        )

    def verify_invoice_registered(self, folio_fiscal: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        found = any(i["folio_fiscal"] == folio_fiscal for i in self._invoices)
        if found:
            return DriverResult.success(
                message=f"Invoice {folio_fiscal} confirmed.", folio_fiscal=folio_fiscal
            )
        return DriverResult.verification_failed(
            f"Invoice {folio_fiscal} not found in registered invoices."
        )

    def verify_poliza_registered(self, poliza_id: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")
        found = any(p["poliza_id"] == poliza_id for p in self._polizas)
        if found:
            return DriverResult.success(
                message=f"Póliza {poliza_id} confirmed.", poliza_id=poliza_id
            )
        return DriverResult.verification_failed(
            f"Póliza {poliza_id} not found in registered pólizas."
        )

    def health(self) -> DriverResult:
        return DriverResult.success(
            message="Mock driver healthy.",
            provider=self._provider,
            tenant_id=self._tenant_id,
            connected=self._connected,
            session_active=self._session is not None,
            closed=self._closed,
        )

    def recover_from_error(self) -> DriverResult:
        return DriverResult.success(message="Mock recovery (no-op).")

    # -- test helpers (not part of the ABC) ------------------------------------
    def inject_invoices(self, invoices: list) -> None:
        """Test helper: pre-populate the invoice list."""
        self._invoices.extend(invoices)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
class ComputerUseDriverFactory:
    """Factory for creating ComputerUseDriver instances.

    Usage:
        config = ComputerUseConfig.from_env()
        driver = ComputerUseDriverFactory.create(
            provider="contpaqi",
            mode="playwright",
            tenant_id=42,
            config=config,
        )
    """

    @staticmethod
    def create(
        provider: str = "contpaqi",
        mode: str = "disabled",
        tenant_id: Optional[int] = None,
        config: Optional[ComputerUseConfig] = None,
    ) -> ComputerUseDriver:
        """Create a driver instance.

        Args:
            provider: 'contpaqi' or 'aspel'.
            mode: 'mock', 'playwright', or 'disabled'.
            tenant_id: Optional tenant identifier for multi-tenant tracking.
            config: Optional ComputerUseConfig. If None, reads from env.

        Returns:
            A ComputerUseDriver implementation.

        Raises:
            ComputerUseConfigurationError: If configuration is invalid.
        """
        if config is None:
            config = ComputerUseConfig.from_env()

        # Override config values if explicitly passed
        if provider != "contpaqi":
            # Validate provider even if config had a different default
            if provider not in VALID_PROVIDERS:
                raise ComputerUseConfigurationError(
                    f"Unknown provider '{provider}'. Valid: {sorted(VALID_PROVIDERS)}"
                )

        mode = mode.strip().lower()
        provider = provider.strip().lower()

        if mode == "disabled":
            logger.info("factory:create mode=disabled provider=%s", provider)
            return DisabledDriver()

        if mode == "mock":
            logger.info("factory:create mode=mock provider=%s tenant_id=%s", provider, tenant_id)
            return MockComputerUseDriver(provider=provider, tenant_id=tenant_id)

        if mode == "playwright":
            url, username, password = config._provider_credentials()
            # Defensive: config.validate() should have caught this, but double-check
            if not url or not username or not password:
                raise ComputerUseConfigurationError(
                    f"Playwright mode requires URL, username, and password for '{provider}'."
                )
            logger.info(
                "factory:create mode=playwright provider=%s url=%s tenant_id=%s",
                provider, url, tenant_id,
            )
            return _create_playwright_driver(
                provider=provider,
                erp_url=url,
                headless=config.headless,
                timeout_seconds=config.timeout_seconds,
                max_retries=config.max_retries,
                tenant_id=tenant_id,
            )

        raise ComputerUseConfigurationError(
            f"Unknown mode '{mode}'. Valid: {sorted(VALID_MODES)}"
        )


def _create_playwright_driver(
    provider: str,
    erp_url: str,
    headless: bool = True,
    timeout_seconds: int = 30,
    max_retries: int = 3,
    tenant_id: Optional[int] = None,
) -> ComputerUseDriver:
    """Create the appropriate real driver for the provider.

    Imports are deferred to avoid loading Playwright when not needed.
    """
    if provider == "contpaqi":
        from b2b_ai.computer_use.contpaqi_real_driver import CONTPAQiRealDriver
        return CONTPAQiRealDriver(
            erp_url=erp_url,
            headless=headless,
        )
    elif provider == "aspel":
        from b2b_ai.computer_use.aspel_real_driver import AspelRealDriver
        return AspelRealDriver(
            erp_url=erp_url,
            headless=headless,
        )
    else:
        raise ComputerUseConfigurationError(
            f"No Playwright driver for provider '{provider}'. "
            f"Valid: {sorted(VALID_PROVIDERS)}"
        )


# Re-export for convenience (import from config)
from b2b_ai.computer_use.config import VALID_PROVIDERS, VALID_MODES  # noqa: E402,F401
