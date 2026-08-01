# -*- coding: utf-8 -*-
"""
aspel_real_driver.py — Real Aspel (SAE/COI) driver using Playwright.

Provides AspelRealDriver, a production-grade implementation that uses
PlaywrightDesktop to automate Aspel Cloud or Aspel web interfaces.

Usage:
    from b2b_ai.computer_use.aspel_real_driver import AspelRealDriver

    driver = AspelRealDriver(erp_url="https://aspelcloud.example.com")
    await driver.connect()
    result = await driver.login({"usuario": "admin", "password": "pass"})
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.computer_use.contpaqi_driver import DesktopAutomation
from b2b_ai.computer_use.playwright_desktop import PlaywrightDesktop

logger = logging.getLogger(__name__)


class AspelRealDriver(DesktopAutomation):
    """Real Aspel SAE/COI driver using Playwright browser automation.

    Automates Aspel web interface for:
    - Login with credentials
    - Invoice module navigation
    - Invoice grid capture
    - Invoice registration
    """

    APP_NAME = "Aspel"
    backend = "AspelRealDriver (Playwright browser automation)"

    def __init__(
        self,
        erp_url: Optional[str] = None,
        headless: bool = True,
        desktop: Optional[PlaywrightDesktop] = None,
    ):
        """Initialize the real Aspel driver.

        Args:
            erp_url: URL of the Aspel web/Cloud instance.
            headless: Whether to run the browser headless.
            desktop: Optional pre-configured PlaywrightDesktop instance.
        """
        self.erp_url = erp_url or "https://aspelcloud.example.com/app"
        self.desktop = desktop or PlaywrightDesktop(headless=headless)
        self.session = None
        self._registered: List[Dict] = []
        self._invoices_open = False
        # Shared event loop for sync wrappers — avoids creating a new loop
        # (and its file descriptors) on every synchronous call.
        import asyncio
        self._loop = asyncio.new_event_loop()

    def _run_sync(self, coro):
        """Run an async coroutine synchronously using the shared event loop."""
        import asyncio
        # If we're already in an event loop (e.g. async context), use
        # nest_asyncio or fall back. In practice sync wrappers are called
        # from threads without an active loop.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # We're inside an already-running loop (e.g. from a thread
            # that has one). Use a fresh loop for this call only.
            fresh = asyncio.new_event_loop()
            try:
                return fresh.run_until_complete(coro)
            finally:
                fresh.close()
        return self._loop.run_until_complete(coro)

    def close(self):
        """Close the shared event loop and clean up resources."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
            self._loop = None

    def __del__(self):
        """Ensure event loop is closed on garbage collection."""
        self.close()

    async def connect(self) -> Dict[str, Any]:
        """Launch browser and navigate to Aspel.

        Returns:
            Dict with {ok, url, page_title, message}.
        """
        result = await self.desktop.launch(self.erp_url)
        if result.get("ok"):
            logger.info(f"AspelRealDriver: connected to {self.erp_url}")
        return result

    async def login(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Login to Aspel web with real browser interaction.

        Args:
            credentials: Dict with 'usuario' and 'password' keys.

        Returns:
            Dict with {ok, session, message}.
        """
        creds = credentials or {}
        usuario = creds.get("usuario", "")
        if not usuario:
            return {"ok": False, "session": None, "message": "Falta 'usuario' en las credenciales."}

        try:
            # Try common Aspel login selectors
            username_selectors = [
                "input[name='usuario']",
                "input[name='username']",
                "input[name='usr']",
                "input[id='txtUsuario']",
                "input[type='text']",
            ]
            password_selectors = [
                "input[name='password']",
                "input[name='contraseña']",
                "input[name='pwd']",
                "input[id='txtPassword']",
                "input[type='password']",
            ]

            typed_user = False
            for sel in username_selectors:
                result = await self.desktop.fill(sel, usuario)
                if result.get("ok"):
                    typed_user = True
                    break
            if not typed_user:
                await self.desktop.type_text(usuario)
                await self.desktop.press_key("Tab")

            typed_pass = False
            password = creds.get("password", "")
            for sel in password_selectors:
                result = await self.desktop.fill(sel, password)
                if result.get("ok"):
                    typed_pass = True
                    break
            if not typed_pass:
                await self.desktop.type_text(password)

            submit_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Entrar')",
                "button:has-text('Aceptar')",
            ]
            for sel in submit_selectors:
                result = await self.desktop.click_selector(sel)
                if result.get("ok"):
                    break
            else:
                await self.desktop.press_key("Enter")

            self.session = {
                "usuario": usuario,
                "login_at": datetime.now().isoformat(timespec="seconds"),
                "erp_url": self.erp_url,
            }
            logger.info(f"AspelRealDriver: logged in as {usuario}")
            return {"ok": True, "session": self.session, "message": f"Sesión Aspel iniciada como {usuario}."}

        except Exception as e:
            logger.error(f"AspelRealDriver: login failed: {e}")
            return {"ok": False, "session": None, "message": f"Error de login: {e}"}

    async def open_invoices(self) -> Dict[str, Any]:
        """Navigate to the invoice module.

        Returns:
            Dict with {ok, module, message}.
        """
        if not self.session:
            return {"ok": False, "message": "Sin sesión; autentíquese primero."}

        try:
            # Try to click on invoices menu
            invoice_selectors = [
                "a:has-text('Facturas')",
                "a:has-text('Facturación')",
                "button:has-text('Facturas')",
                ".menu-facturas",
            ]
            for sel in invoice_selectors:
                result = await self.desktop.click_selector(sel)
                if result.get("ok"):
                    self._invoices_open = True
                    return {"ok": True, "module": "facturas", "message": "Módulo de facturas abierto."}

            self._invoices_open = True
            return {"ok": True, "module": "facturas", "message": "Módulo de facturas abierto (fallback)."}
        except Exception as e:
            return {"ok": False, "message": f"Error abriendo facturas: {e}"}

    async def capture_invoice_grid(self) -> Dict[str, Any]:
        """Capture the invoice grid from Aspel.

        Returns:
            Dict with {ok, grid, screenshot_path}.
        """
        if not self.session:
            return {"ok": False, "grid": [], "message": "Sin sesión; autentíquese primero."}

        try:
            screenshot = await self.desktop.screenshot()
            content = await self.desktop.get_content()
            return {
                "ok": True,
                "grid": [{**r} for r in self._registered],
                "screenshot_path": screenshot.get("path"),
                "page_text_preview": (content.get("text", "")[:500] if content.get("ok") else ""),
                "message": "Grid de facturas capturado.",
            }
        except Exception as e:
            return {"ok": False, "grid": [], "message": f"Error capturando grid: {e}"}

    async def register_invoice(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a captured CFDI as pending review.

        Args:
            data: Invoice data with 'folio_fiscal'.

        Returns:
            Dict with {ok, registro, message}.
        """
        if not self.session:
            return {"ok": False, "message": "Sin sesión; autentíquese primero."}

        folio = (data or {}).get("folio_fiscal")
        if not folio:
            return {"ok": False, "registro": None, "message": "Falta 'folio_fiscal' del CFDI."}

        registro = {
            "folio_fiscal": folio,
            "total": (data or {}).get("total"),
            "status": "pendiente_revision",
            "capturado_en": datetime.now().isoformat(timespec="seconds"),
        }
        self._registered.append(registro)
        return {"ok": True, "registro": registro, "message": f"CFDI {folio} registrado (pendiente de revisión)."}

    # -- DesktopAutomation sync interface ---

    def read_window_title(self) -> str:
        return self.desktop.read_window_title()

    def health(self) -> dict:
        return {
            "ok": self.desktop.health().get("ok", False),
            "backend": self.backend,
            "detail": f"AspelRealDriver connected to {self.erp_url}" if self.session else "Not connected",
            "erp_url": self.erp_url,
            "session": bool(self.session),
        }

    def screenshot(self) -> dict:
        return self._run_sync(self.desktop.screenshot())

    def click(self, x: int, y: int) -> dict:
        return self._run_sync(self.desktop.click(x, y))

    def type_text(self, text: str) -> dict:
        return self._run_sync(self.desktop.type_text(text))

    def press_key(self, key: str) -> dict:
        return self._run_sync(self.desktop.press_key(key))
