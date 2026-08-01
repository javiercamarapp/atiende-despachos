# -*- coding: utf-8 -*-
"""
playwright_desktop.py — Real desktop automation driver using Playwright.

Provides PlaywrightDesktop, a production-grade implementation of the
DesktopAutomation interface. Uses Playwright's Chromium browser to automate
web-based ERPs and web applications. Unlike MockDesktop, this driver
actually launches a real browser, navigates to URLs, takes screenshots,
clicks elements, and types text.

Usage:
    from b2b_ai.computer_use.playwright_desktop import PlaywrightDesktop

    desktop = PlaywrightDesktop(headless=True)
    await desktop.launch("https://contpaqiweb.example.com/app")
    await desktop.type_text("admin")
    await desktop.press_key("Tab")
    await desktop.type_text("password123")
    await desktop.press_key("Enter")
    screenshot = await desktop.screenshot()
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.computer_use.contpaqi_driver import DesktopAutomation

logger = logging.getLogger(__name__)


class PlaywrightDesktop(DesktopAutomation):
    """Real desktop automation using Playwright browser.

    Implements the DesktopAutomation interface with a real Playwright Chromium
    browser. This enables computer-use style automation for web-based ERPs.

    Requires: playwright>=1.40
    Install: pip install playwright && playwright install chromium

    Features:
        - Real browser launch and navigation
        - Screenshot capture with UUID-named files
        - Click by coordinates (x, y)
        - Type text into focused elements
        - Press keyboard keys (Enter, Tab, etc.)
        - Health check with browser state
    """

    backend = "PlaywrightDesktop (real browser automation)"

    def __init__(self, headless: bool = True):
        """Initialize the Playwright desktop driver.

        Args:
            headless: If True, runs the browser without a visible window.
                     Set to False for debugging/demos.
        """
        self.headless = headless
        self._pw = None  # Playwright instance
        self._browser = None  # Browser instance
        self._page = None  # Page instance
        self._launched = False

    def __del__(self):
        """Ensure browser resources are freed on garbage collection."""
        if self._launched or self._browser:
            logger.warning("PlaywrightDesktop: resources not closed before GC. "
                           "Call close() explicitly to avoid fd leaks.")
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self.close())
                finally:
                    loop.close()
            except Exception:
                pass

    async def launch(self, url: str) -> Dict[str, Any]:
        """Launch a real Chromium browser and navigate to the URL.

        Args:
            url: URL to navigate to.

        Returns:
            Dict with {ok, url, page_title, message}.
        """
        try:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)
            self._page = await self._browser.new_page()
            await self._page.goto(url, wait_until="domcontentloaded")
            self._launched = True
            title = await self._page.title()
            logger.info(f"PlaywrightDesktop: launched and navigated to {url}")
            return {
                "ok": True,
                "url": url,
                "page_title": title,
                "message": f"Browser launched and navigated to {url}",
            }
        except ImportError:
            return {
                "ok": False,
                "url": url,
                "error": "playwright not installed. Run: pip install playwright && playwright install chromium",
            }
        except Exception as e:
            logger.error(f"PlaywrightDesktop: launch failed: {e}")
            return {"ok": False, "url": url, "error": str(e)}

    async def screenshot(self) -> Dict[str, Any]:
        """Take a screenshot of the current page.

        Returns:
            Dict with {ok, path, title}.
        """
        if not self._page:
            return {"ok": False, "path": None, "error": "No browser page active"}
        try:
            path = f"/tmp/screenshot_{uuid.uuid4().hex[:8]}.png"
            await self._page.screenshot(path=path, full_page=False)
            title = await self._page.title()
            return {"ok": True, "path": path, "title": title}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: screenshot failed: {e}")
            return {"ok": False, "path": None, "error": str(e)}

    async def click(self, x: int, y: int) -> Dict[str, Any]:
        """Click at coordinates on the page.

        Args:
            x: X coordinate.
            y: Y coordinate.

        Returns:
            Dict with {ok, x, y}.
        """
        if not self._page:
            return {"ok": False, "x": x, "y": y, "error": "No browser page active"}
        try:
            await self._page.mouse.click(x, y)
            return {"ok": True, "x": x, "y": y}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: click failed: {e}")
            return {"ok": False, "x": x, "y": y, "error": str(e)}

    async def type_text(self, text: str) -> Dict[str, Any]:
        """Type text into the currently focused element.

        Args:
            text: Text to type.

        Returns:
            Dict with {ok, chars}.
        """
        if not self._page:
            return {"ok": False, "chars": 0, "error": "No browser page active"}
        try:
            await self._page.keyboard.type(text)
            return {"ok": True, "chars": len(text)}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: type_text failed: {e}")
            return {"ok": False, "chars": 0, "error": str(e)}

    async def press_key(self, key: str) -> Dict[str, Any]:
        """Press a keyboard key.

        Args:
            key: Key to press (e.g., "Enter", "Tab", "Escape").

        Returns:
            Dict with {ok, key}.
        """
        if not self._page:
            return {"ok": False, "key": key, "error": "No browser page active"}
        try:
            await self._page.keyboard.press(key)
            return {"ok": True, "key": key}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: press_key failed: {e}")
            return {"ok": False, "key": key, "error": str(e)}

    async def click_selector(self, selector: str) -> Dict[str, Any]:
        """Click an element by CSS selector.

        Args:
            selector: CSS selector of the element to click.

        Returns:
            Dict with {ok, selector}.
        """
        if not self._page:
            return {"ok": False, "selector": selector, "error": "No browser page active"}
        try:
            await self._page.click(selector)
            return {"ok": True, "selector": selector}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: click_selector failed: {e}")
            return {"ok": False, "selector": selector, "error": str(e)}

    async def fill(self, selector: str, value: str) -> Dict[str, Any]:
        """Fill a form field by CSS selector.

        Args:
            selector: CSS selector of the input element.
            value: Value to fill.

        Returns:
            Dict with {ok, selector, chars}.
        """
        if not self._page:
            return {"ok": False, "selector": selector, "error": "No browser page active"}
        try:
            await self._page.fill(selector, value)
            return {"ok": True, "selector": selector, "chars": len(value)}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: fill failed: {e}")
            return {"ok": False, "selector": selector, "error": str(e)}

    async def get_content(self) -> Dict[str, Any]:
        """Get the page text content.

        Returns:
            Dict with {ok, text, url}.
        """
        if not self._page:
            return {"ok": False, "text": "", "error": "No browser page active"}
        try:
            text = await self._page.inner_text("body")
            url = self._page.url
            return {"ok": True, "text": text, "url": url}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: get_content failed: {e}")
            return {"ok": False, "text": "", "error": str(e)}

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> Dict[str, Any]:
        """Wait for an element to appear on the page.

        Args:
            selector: CSS selector to wait for.
            timeout: Timeout in milliseconds.

        Returns:
            Dict with {ok, selector}.
        """
        if not self._page:
            return {"ok": False, "selector": selector, "error": "No browser page active"}
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return {"ok": True, "selector": selector}
        except Exception as e:
            logger.error(f"PlaywrightDesktop: wait_for_selector failed: {e}")
            return {"ok": False, "selector": selector, "error": str(e)}

    async def close(self) -> None:
        """Close the browser and cleanup resources."""
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as e:
            logger.warning(f"PlaywrightDesktop: cleanup warning: {e}")
        finally:
            self._browser = None
            self._page = None
            self._pw = None
            self._launched = False

    # -- DesktopAutomation interface (sync wrappers for backward compat) ---

    def read_window_title(self) -> str:
        """Read the current page title (sync wrapper)."""
        if not self._page:
            return "No browser active"
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return "Browser active (async context)"
            return loop.run_until_complete(self._page.title())
        except Exception:
            return "Browser active"

    def health(self) -> dict:
        """Return health status of the Playwright driver."""
        return {
            "ok": self._launched and self._browser is not None,
            "backend": self.backend,
            "detail": (
                f"Playwright browser active (headless={self.headless})"
                if self._launched
                else "Playwright ready, not yet launched"
            ),
            "launched": self._launched,
        }
