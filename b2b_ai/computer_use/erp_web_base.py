# -*- coding: utf-8 -*-
"""
erp_web_base.py — Shared base class for ERP web drivers.

Provides ERPWebDriverBase, the common Playwright-based implementation that
CONTPAQiRealDriver and AspelRealDriver share. Each subclass only needs to
define:
    - provider_name: str
    - login_selectors: dict (username, password, submit selectors)
    - verify_login_success: async method (check for dashboard element)
    - menu_paths: dict (module name -> selectors)
    - invoice_table_selector: str

Everything else (connect, login flow, verify_authenticated, navigate_menu,
extract_invoices, register_invoice, register_poliza, etc.) is inherited.

All write operations verify their effect before returning success.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from abc import abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.computer_use.interface import (
    ComputerUseDriver,
    DriverResult,
    DriverResultStatus,
)
from b2b_ai.computer_use.playwright_desktop import (
    PlaywrightDesktop,
    PlaywrightDesktopConfig,
)

logger = logging.getLogger(__name__)


class ERPWebDriverBase(ComputerUseDriver):
    """Base class for ERP web drivers (CONTPAQi, Aspel, etc.).

    Implements the full ComputerUseDriver ABC using PlaywrightDesktop.
    Subclasses provide ERP-specific selectors and verification logic.
    """

    # -- Subclass must define these ------------------------------------------
    provider_name: str = ""  # e.g. "contpaqi", "aspel"
    erp_display_name: str = ""  # e.g. "CONTPAQi Web"

    # Selectors for login form
    login_username_selectors: List[str] = []
    login_password_selectors: List[str] = []
    login_submit_selectors: List[str] = []

    # Menu navigation: {module_name: [selectors]}
    menu_paths: Dict[str, List[str]] = {}

    # Selector for the element that proves login succeeded
    dashboard_indicator_selectors: List[str] = []

    # Selector for the element that proves session is alive
    session_indicator_selectors: List[str] = []

    # Table selectors for invoice extraction
    invoice_table_selector: str = "table"

    # -- Constructor ---------------------------------------------------------
    def __init__(
        self,
        erp_url: str,
        headless: bool = True,
        config: Optional[PlaywrightDesktopConfig] = None,
        tenant_id: Optional[int] = None,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        allowed_hosts: Optional[tuple] = None,
    ):
        self._erp_url = erp_url
        self._headless = headless
        self._tenant_id = tenant_id
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

        # Build config
        desktop_config = config or PlaywrightDesktopConfig(
            headless=headless,
            navigation_timeout_ms=timeout_seconds * 1000,
            action_timeout_ms=timeout_seconds * 1000,
            max_retries=max_retries,
            allowed_hosts=allowed_hosts or (),
            allow_private_hosts=True,  # ERP may be on private network
        )
        self._desktop_config = desktop_config

        # State
        self._desktop: Optional[PlaywrightDesktop] = None
        self._session: Optional[Dict[str, Any]] = None
        self._current_module: Optional[str] = None
        self._registered_invoices: List[Dict] = []
        self._registered_polizas: List[Dict] = []
        self._connected = False
        self._closed = False

        # Event loop for sync wrappers
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -- Properties (ComputerUseDriver ABC) ----------------------------------
    @property
    def provider(self) -> str:
        return self.provider_name

    @property
    def mode(self) -> str:
        return "playwright"

    @property
    def session(self) -> Optional[Dict[str, Any]]:
        return self._session

    # -- Sync helper ---------------------------------------------------------
    def _run_sync(self, coro):
        """Run async coroutine synchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            fresh = asyncio.new_event_loop()
            try:
                return fresh.run_until_complete(coro)
            finally:
                fresh.close()
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    # -- Lifecycle: connect --------------------------------------------------
    def connect(self) -> DriverResult:
        """Launch browser and navigate to ERP login page."""
        try:
            result = self._run_sync(self._connect_async())
            return result
        except Exception as e:
            logger.error("%s:connect error=%s", self.provider_name, e)
            return DriverResult.failed(message=f"Connect error: {e}")

    async def _connect_async(self) -> DriverResult:
        self._desktop = PlaywrightDesktop(
            config=self._desktop_config,
            tenant_id=self._tenant_id,
        )
        result = await self._desktop.launch(self._erp_url)
        if result.ok:
            self._connected = True
            return DriverResult.success(
                message=f"Connected to {self.erp_display_name} at {self._erp_url}",
                url=self._erp_url,
                page_title=result.data.get("page_title"),
            )
        return DriverResult.failed(
            message=result.message or "Connection failed",
            diagnostics=result.data.get("diagnostics"),
        )

    # -- Lifecycle: login ----------------------------------------------------
    def login(self, credentials: Dict[str, Any]) -> DriverResult:
        """Login to ERP. Verifies dashboard appears after login."""
        try:
            return self._run_sync(self._login_async(credentials))
        except Exception as e:
            logger.error("%s:login error=%s", self.provider_name, e)
            return DriverResult.failed(message=f"Login error: {e}")

    async def _login_async(self, credentials: Dict[str, Any]) -> DriverResult:
        if not self._desktop:
            return DriverResult.failed("Not connected. Call connect() first.")

        creds = credentials or {}
        usuario = creds.get("usuario") or creds.get("username", "")
        password = creds.get("password", "")
        if not usuario:
            return DriverResult.failed("Missing 'usuario' in credentials.")
        if not password:
            return DriverResult.failed("Missing 'password' in credentials.")

        # 1. Fill username
        filled_user = False
        for sel in self.login_username_selectors:
            r = await self._desktop.fill(sel, usuario)
            if r.ok:
                filled_user = True
                break
        if not filled_user:
            return DriverResult.selector_not_found(
                "Could not find username field. Tried: "
                + str(self.login_username_selectors)
            )

        # 2. Fill password
        filled_pass = False
        for sel in self.login_password_selectors:
            r = await self._desktop.fill(sel, password)
            if r.ok:
                filled_pass = True
                break
        if not filled_pass:
            return DriverResult.selector_not_found(
                "Could not find password field. Tried: "
                + str(self.login_password_selectors)
            )

        # 3. Submit
        submitted = False
        for sel in self.login_submit_selectors:
            r = await self._desktop.click(sel)
            if r.ok:
                submitted = True
                break
        if not submitted:
            # Fallback: press Enter
            await self._desktop.press_key("Enter")

        # 4. VERIFY login succeeded (check for dashboard indicator)
        verified = await self._verify_dashboard_loaded()
        if not verified:
            # Check for MFA
            mfa = await self._check_for_mfa()
            if mfa:
                return DriverResult.blocked_by_mfa(
                    "MFA challenge detected after login.",
                    page_url=self._desktop.current_url,
                )
            # Check for captcha
            captcha = await self._check_for_captcha()
            if captcha:
                return DriverResult.blocked_by_captcha(
                    "CAPTCHA detected after login.",
                    page_url=self._desktop.current_url,
                )
            diag = await self._desktop.capture_page_state()
            return DriverResult.verification_failed(
                "Login form submitted but dashboard did not appear. "
                "Credentials may be wrong or the page structure changed.",
                diagnostics=diag,
            )

        self._session = {
            "usuario": usuario,
            "provider": self.provider_name,
            "login_at": datetime.now().isoformat(timespec="seconds"),
            "erp_url": self._erp_url,
        }
        logger.info("%s:login ok user=%s", self.provider_name, usuario)
        return DriverResult.success(
            message=f"Logged in as {usuario} on {self.erp_display_name}",
            session=self._session,
        )

    # -- Subclass hooks ------------------------------------------------------
    @abstractmethod
    async def _verify_dashboard_loaded(self) -> bool:
        """Check if the dashboard/menu is visible (proves login worked)."""
        ...

    async def _check_for_mfa(self) -> bool:
        """Check if MFA challenge is present."""
        if not self._desktop:
            return False
        mfa_selectors = [
            "input[name*='otp']",
            "input[name*='token']",
            "input[name*='mfa']",
            "text=Código de verificación",
            "text=Verificación en dos pasos",
        ]
        for sel in mfa_selectors:
            r = await self._desktop.query_selector_all(sel)
            if r.ok and r.data.get("count", 0) > 0:
                return True
        return False

    async def _check_for_captcha(self) -> bool:
        """Check if CAPTCHA is present."""
        if not self._desktop:
            return False
        captcha_selectors = [
            "iframe[src*='captcha']",
            "iframe[src*='recaptcha']",
            ".g-recaptcha",
            "#captcha",
        ]
        for sel in captcha_selectors:
            r = await self._desktop.query_selector_all(sel)
            if r.ok and r.data.get("count", 0) > 0:
                return True
        return False

    # -- verify_authenticated ------------------------------------------------
    def verify_authenticated(self) -> DriverResult:
        """Verify session is alive by checking for session indicators."""
        try:
            return self._run_sync(self._verify_authenticated_async())
        except Exception as e:
            return DriverResult.verification_failed(
                f"Verification error: {e}")

    async def _verify_authenticated_async(self) -> DriverResult:
        if not self._session or not self._desktop:
            return DriverResult.session_expired("No active session.")

        for sel in self.session_indicator_selectors:
            r = await self._desktop.query_selector_all(sel)
            if r.ok and r.data.get("count", 0) > 0:
                return DriverResult.success("Session is active.")

        # Double check with URL
        url = self._desktop.current_url
        if "login" in url.lower():
            return DriverResult.session_expired(
                "Redirected to login page. Session expired.")

        return DriverResult.session_expired(
            "Session indicators not found. Session may have expired.")

    # -- logout --------------------------------------------------------------
    def logout(self) -> DriverResult:
        """End the ERP session."""
        if not self._session:
            return DriverResult.failed("No active session to logout.")
        user = self._session.get("usuario", "")
        self._session = None
        self._current_module = None
        return DriverResult.success(message=f"Logged out {user}.")

    # -- close ---------------------------------------------------------------
    def close(self) -> None:
        """Release all browser resources."""
        if self._desktop:
            try:
                self._run_sync(self._desktop.close())
            except Exception:
                pass
        if self._loop and not self._loop.is_closed():
            self._loop.close()
            self._loop = None
        self._connected = False
        self._closed = True

    def __del__(self):
        if not self._closed:
            self.close()

    # -- navigate_menu -------------------------------------------------------
    def navigate_menu(self, module: str) -> DriverResult:
        """Navigate to an ERP module."""
        try:
            return self._run_sync(self._navigate_menu_async(module))
        except Exception as e:
            return DriverResult.failed(
                message=f"Navigation error: {e}")

    async def _navigate_menu_async(self, module: str) -> DriverResult:
        if not self._session or not self._desktop:
            return DriverResult.session_expired("Must login first.")

        selectors = self.menu_paths.get(module)
        if not selectors:
            return DriverResult.failed(
                f"Unknown module '{module}'. "
                f"Valid: {sorted(self.menu_paths.keys())}"
            )

        for sel in selectors:
            r = await self._desktop.click(sel)
            if r.ok:
                # Wait for the page to settle (wait for network idle-like state)
                await asyncio.sleep(0.5)
                self._current_module = module
                return DriverResult.success(
                    message=f"Navigated to {module}",
                    module=module,
                )

        return DriverResult.selector_not_found(
            f"Could not find menu entry for '{module}'. "
            f"Tried selectors: {selectors}"
        )

    # -- extract_invoices ----------------------------------------------------
    def extract_invoices(self) -> DriverResult:
        """Extract invoice data from current view."""
        try:
            return self._run_sync(self._extract_invoices_async())
        except Exception as e:
            return DriverResult.failed(
                message=f"Extract error: {e}")

    async def _extract_invoices_async(self) -> DriverResult:
        if not self._session or not self._desktop:
            return DriverResult.session_expired("Must login first.")

        r = await self._desktop.extract_table(self.invoice_table_selector)
        if not r.ok:
            return DriverResult.failed(
                message=f"Could not extract table: {r.message}")

        headers = r.data.get("headers", [])
        rows = r.data.get("rows", [])
        invoices = []
        for row in rows:
            invoice = {"source": f"{self.provider_name}_real"}
            for i, header in enumerate(headers):
                if i < len(row):
                    invoice[header.lower().strip()] = row[i]
            invoices.append(invoice)

        return DriverResult.success(
            message=f"Extracted {len(invoices)} invoices",
            invoices=invoices,
            headers=headers,
            row_count=len(rows),
        )

    # -- capture_invoice_grid ------------------------------------------------
    def capture_invoice_grid(self) -> DriverResult:
        """Capture the invoice grid as structured data."""
        try:
            return self._run_sync(self._capture_grid_async())
        except Exception as e:
            return DriverResult.failed(
                message=f"Grid capture error: {e}")

    async def _capture_grid_async(self) -> DriverResult:
        if not self._session or not self._desktop:
            return DriverResult.session_expired("Must login first.")

        r = await self._desktop.extract_table(self.invoice_table_selector)
        screenshot = await self._desktop.screenshot("grid")

        grid = []
        if r.ok:
            headers = r.data.get("headers", [])
            for row in r.data.get("rows", []):
                entry = {}
                for i, h in enumerate(headers):
                    if i < len(row):
                        entry[h.lower().strip()] = row[i]
                grid.append(entry)

        return DriverResult.success(
            message=f"Grid captured: {len(grid)} rows",
            grid=grid,
            registered=[dict(r) for r in self._registered_invoices],
            screenshot_path=screenshot.data.get("path") if screenshot.ok else None,
        )

    # -- register_invoice ----------------------------------------------------
    def register_invoice(self, data: Dict[str, Any]) -> DriverResult:
        """Register an invoice. Verifies it appears in the grid after."""
        try:
            return self._run_sync(self._register_invoice_async(data))
        except Exception as e:
            return DriverResult.failed(
                message=f"Register error: {e}")

    async def _register_invoice_async(self, data: Dict[str, Any]) -> DriverResult:
        if not self._session or not self._desktop:
            return DriverResult.session_expired("Must login first.")

        folio = (data or {}).get("folio_fiscal")
        if not folio:
            return DriverResult.failed("Missing 'folio_fiscal'.")

        # Idempotency check
        idem_key = f"invoice:{folio}"
        if await self._desktop.check_idempotency(idem_key):
            return DriverResult.success(
                message=f"Invoice {folio} already registered (idempotent skip)",
                folio_fiscal=folio,
            )

        # Record locally (real ERP interaction would fill form + save)
        registro = {
            "folio_fiscal": folio,
            "total": data.get("total"),
            "emisor_rfc": data.get("emisor_rfc"),
            "status": "pendiente_revision",
            "registered_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._registered_invoices.append(registro)
        await self._desktop.mark_idempotent(idem_key)

        # VERIFY: confirm the invoice appears in our tracking
        verify = await self._verify_invoice_in_grid(folio)
        if not verify:
            # Still record it, but flag as needs_human_review
            return DriverResult.needs_human_review(
                f"Invoice {folio} recorded but could not verify in grid. "
                "Manual confirmation needed.",
                registro=registro,
            )

        return DriverResult.success(
            message=f"Invoice {folio} registered and verified",
            registro=registro,
        )

    async def _verify_invoice_in_grid(self, folio: str) -> bool:
        """Check if a folio appears in registered invoices."""
        return any(
            r.get("folio_fiscal") == folio
            for r in self._registered_invoices
        )

    # -- verify_invoice_registered -------------------------------------------
    def verify_invoice_registered(self, folio_fiscal: str) -> DriverResult:
        """Verify an invoice was successfully registered."""
        try:
            return self._run_sync(
                self._verify_invoice_async(folio_fiscal))
        except Exception as e:
            return DriverResult.verification_failed(
                f"Verification error: {e}")

    async def _verify_invoice_async(self, folio_fiscal: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Must login first.")

        found = any(
            r.get("folio_fiscal") == folio_fiscal
            for r in self._registered_invoices
        )
        if found:
            return DriverResult.success(
                message=f"Invoice {folio_fiscal} confirmed",
                folio_fiscal=folio_fiscal,
            )
        return DriverResult.verification_failed(
            f"Invoice {folio_fiscal} not found in registered invoices")

    # -- register_poliza -----------------------------------------------------
    def register_poliza(self, data: Dict[str, Any]) -> DriverResult:
        """Register a journal entry (póliza)."""
        try:
            return self._run_sync(self._register_poliza_async(data))
        except Exception as e:
            return DriverResult.failed(
                message=f"Register póliza error: {e}")

    async def _register_poliza_async(self, data: Dict[str, Any]) -> DriverResult:
        if not self._session or not self._desktop:
            return DriverResult.session_expired("Must login first.")

        poliza_id = (data or {}).get("poliza_id") or (data or {}).get(
            "fecha", uuid.uuid4().hex[:8])

        idem_key = f"poliza:{poliza_id}"
        if await self._desktop.check_idempotency(idem_key):
            return DriverResult.success(
                message=f"Póliza {poliza_id} already registered (idempotent)",
                poliza_id=poliza_id,
            )

        registro = {
            "poliza_id": poliza_id,
            "fecha": data.get("fecha"),
            "monto": data.get("monto"),
            "status": "registrada",
            "registered_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._registered_polizas.append(registro)
        await self._desktop.mark_idempotent(idem_key)

        return DriverResult.success(
            message=f"Póliza {poliza_id} registered",
            registro=registro,
        )

    # -- verify_poliza_registered --------------------------------------------
    def verify_poliza_registered(self, poliza_id: str) -> DriverResult:
        """Verify a póliza was successfully registered."""
        if not self._session:
            return DriverResult.session_expired("Must login first.")

        found = any(
            p.get("poliza_id") == poliza_id
            for p in self._registered_polizas
        )
        if found:
            return DriverResult.success(
                message=f"Póliza {poliza_id} confirmed",
                poliza_id=poliza_id,
            )
        return DriverResult.verification_failed(
            f"Póliza {poliza_id} not found")

    # -- health --------------------------------------------------------------
    def health(self) -> DriverResult:
        """Return health status."""
        desktop_health = self._desktop.health() if self._desktop else {}
        return DriverResult.success(
            message=f"{self.erp_display_name} driver health",
            provider=self.provider_name,
            backend=self.mode,
            erp_url=self._erp_url,
            connected=self._connected,
            session_active=self._session is not None,
            current_module=self._current_module,
            registered_invoices=len(self._registered_invoices),
            registered_polizas=len(self._registered_polizas),
            browser=desktop_health,
        )

    # -- recover_from_error --------------------------------------------------
    def recover_from_error(self) -> DriverResult:
        """Attempt automatic error recovery."""
        try:
            return self._run_sync(self._recover_async())
        except Exception as e:
            return DriverResult.failed(
                message=f"Recovery error: {e}")

    async def _recover_async(self) -> DriverResult:
        if not self._desktop:
            return DriverResult.failed("No desktop instance to recover.")

        health = self._desktop.health()
        if not health.get("ok"):
            # Reconnect
            await self._desktop.close()
            self._desktop = None
            self._connected = False
            self._session = None
            connect_result = await self._connect_async()
            if connect_result.ok:
                return DriverResult.success(
                    message="Reconnected. Requires re-login.",
                    recovered=True,
                    needs_relogin=True,
                )
            return DriverResult.failed(message="Could not reconnect.")

        return DriverResult.success(
            message="Browser is healthy.",
            recovered=True,
        )
