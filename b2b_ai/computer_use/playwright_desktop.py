# -*- coding: utf-8 -*-
"""
playwright_desktop.py — Real desktop automation driver using Playwright.

Provides PlaywrightDesktop, a production-grade implementation of the
DesktopAutomation interface. Uses Playwright's Chromium browser to automate
web-based ERPs and web applications.

Features:
    - Real browser launch and navigation
    - Screenshot capture with UUID-named files
    - Screenshot comparison for state verification
    - Click by coordinates (x, y) or by CSS/XPath selectors
    - Type text into focused elements or fill form fields
    - Press keyboard keys (Enter, Tab, etc.)
    - Dropdown selection
    - Table/grid extraction
    - Retry logic with exponential backoff
    - Element detection using CSS selectors and XPath
    - Health check with browser state
    - Structured logging for all operations

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

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.computer_use.contpaqi_driver import DesktopAutomation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry helper with exponential backoff
# ---------------------------------------------------------------------------
async def _retry_async(
    coro_fn,
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    operation: str = "operation",
) -> Any:
    """Execute an async callable with retry + exponential backoff.

    Args:
        coro_fn: Callable returning an awaitable (no args, use lambda/closure).
        max_attempts: Total attempts (1 = no retry).
        base_delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier for delay on each retry.
        retryable_exceptions: Tuple of exception types to retry on.
        operation: Name for logging.

    Returns:
        Result of coro_fn on success.

    Raises:
        Last exception if all attempts fail.
    """
    last_exc = None
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "playwright:retry attempt=%d/%d op=%s error=%s retry_in=%.1fs",
                    attempt, max_attempts, operation, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(
                    "playwright:retry EXHAUSTED attempt=%d op=%s error=%s",
                    attempt, operation, exc,
                )
    raise last_exc  # type: ignore[misc]


class PlaywrightDesktop(DesktopAutomation):
    """Real desktop automation using Playwright browser.

    Implements the DesktopAutomation interface with a real Playwright Chromium
    browser. This enables computer-use style automation for web-based ERPs.

    Requires: playwright>=1.40
    Install: pip install playwright && playwright install chromium
    """

    backend = "PlaywrightDesktop (real browser automation)"

    def __init__(self, headless: bool = True, retry_max_attempts: int = 3):
        """Initialize the Playwright desktop driver.

        Args:
            headless: If True, runs the browser without a visible window.
            retry_max_attempts: Max retries for transient failures.
        """
        self.headless = headless
        self.retry_max_attempts = retry_max_attempts
        self._pw = None
        self._browser = None
        self._page = None
        self._launched = False
        self._screenshot_hashes: List[str] = []  # history for comparison

    def __del__(self):
        """Ensure browser resources are freed on garbage collection."""
        if self._launched or self._browser:
            logger.warning(
                "PlaywrightDesktop: resources not closed before GC. "
                "Call close() explicitly to avoid fd leaks."
            )
            try:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self.close())
                finally:
                    loop.close()
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Core operations with retry
    # -------------------------------------------------------------------
    async def launch(self, url: str) -> Dict[str, Any]:
        """Launch a real Chromium browser and navigate to the URL (with retry).

        Args:
            url: URL to navigate to.

        Returns:
            Dict with {ok, url, page_title, message}.
        """
        async def _do():
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)
            self._page = await self._browser.new_page()
            await self._page.goto(url, wait_until="domcontentloaded")
            self._launched = True
            title = await self._page.title()
            return {"ok": True, "url": url, "page_title": title,
                    "message": f"Browser launched and navigated to {url}"}

        try:
            result = await _retry_async(
                _do, max_attempts=self.retry_max_attempts,
                operation="launch", retryable_exceptions=(OSError, ConnectionError),
            )
            logger.info("playwright:launch ok url=%s", url)
            return result
        except ImportError:
            return {"ok": False, "url": url,
                    "error": "playwright not installed. Run: pip install playwright && playwright install chromium"}
        except Exception as e:
            logger.error("playwright:launch FAILED url=%s error=%s", url, e)
            return {"ok": False, "url": url, "error": str(e)}

    async def screenshot(self) -> Dict[str, Any]:
        """Take a screenshot of the current page with comparison hash.

        Returns:
            Dict with {ok, path, title, hash, is_duplicate}.
        """
        if not self._page:
            return {"ok": False, "path": None, "error": "No browser page active"}
        try:
            path = f"/tmp/screenshot_{uuid.uuid4().hex[:8]}.png"
            await self._page.screenshot(path=path, full_page=False)
            title = await self._page.title()
            # Compute hash for comparison
            with open(path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()[:16]
            is_dup = file_hash in self._screenshot_hashes[-5:]
            self._screenshot_hashes.append(file_hash)
            # Keep only last 20 hashes
            if len(self._screenshot_hashes) > 20:
                self._screenshot_hashes = self._screenshot_hashes[-20:]
            return {"ok": True, "path": path, "title": title,
                    "hash": file_hash, "is_duplicate": is_dup}
        except Exception as e:
            logger.error("playwright:screenshot FAILED error=%s", e)
            return {"ok": False, "path": None, "error": str(e)}

    async def compare_screenshots(self, path_a: str, path_b: str) -> Dict[str, Any]:
        """Compare two screenshots by SHA-256 hash.

        Returns:
            Dict with {ok, identical, hash_a, hash_b}.
        """
        try:
            with open(path_a, "rb") as f:
                ha = hashlib.sha256(f.read()).hexdigest()[:16]
            with open(path_b, "rb") as f:
                hb = hashlib.sha256(f.read()).hexdigest()[:16]
            return {"ok": True, "identical": ha == hb, "hash_a": ha, "hash_b": hb}
        except Exception as e:
            return {"ok": False, "identical": False, "error": str(e)}

    async def click(self, x: int, y: int) -> Dict[str, Any]:
        """Click at coordinates on the page (with retry)."""
        if not self._page:
            return {"ok": False, "x": x, "y": y, "error": "No browser page active"}
        try:
            await _retry_async(
                lambda: self._page.mouse.click(x, y),
                max_attempts=self.retry_max_attempts,
                operation=f"click({x},{y})",
            )
            logger.debug("playwright:click x=%d y=%d", x, y)
            return {"ok": True, "x": x, "y": y}
        except Exception as e:
            logger.error("playwright:click FAILED x=%d y=%d error=%s", x, y, e)
            return {"ok": False, "x": x, "y": y, "error": str(e)}

    async def type_text(self, text: str) -> Dict[str, Any]:
        """Type text into the currently focused element (with retry)."""
        if not self._page:
            return {"ok": False, "chars": 0, "error": "No browser page active"}
        try:
            await _retry_async(
                lambda: self._page.keyboard.type(text),
                max_attempts=self.retry_max_attempts,
                operation="type_text",
            )
            logger.debug("playwright:type_text chars=%d", len(text))
            return {"ok": True, "chars": len(text)}
        except Exception as e:
            logger.error("playwright:type_text FAILED error=%s", e)
            return {"ok": False, "chars": 0, "error": str(e)}

    async def press_key(self, key: str) -> Dict[str, Any]:
        """Press a keyboard key (with retry)."""
        if not self._page:
            return {"ok": False, "key": key, "error": "No browser page active"}
        try:
            await _retry_async(
                lambda: self._page.keyboard.press(key),
                max_attempts=self.retry_max_attempts,
                operation=f"press_key({key})",
            )
            logger.debug("playwright:press_key key=%s", key)
            return {"ok": True, "key": key}
        except Exception as e:
            logger.error("playwright:press_key FAILED key=%s error=%s", key, e)
            return {"ok": False, "key": key, "error": str(e)}

    async def click_selector(self, selector: str) -> Dict[str, Any]:
        """Click an element by CSS selector or XPath (with retry).

        Supports:
          - CSS selectors: 'button.submit', '#login-btn'
          - XPath selectors: 'xpath=//button[@type="submit"]'
        """
        if not self._page:
            return {"ok": False, "selector": selector, "error": "No browser page active"}
        try:
            if selector.startswith("xpath="):
                xpath = selector[6:]
                await _retry_async(
                    lambda: self._page.click(f"xpath={xpath}"),
                    max_attempts=self.retry_max_attempts,
                    operation="click_xpath",
                )
            else:
                await _retry_async(
                    lambda: self._page.click(selector),
                    max_attempts=self.retry_max_attempts,
                    operation=f"click_selector({selector})",
                )
            logger.debug("playwright:click_selector sel=%s", selector)
            return {"ok": True, "selector": selector}
        except Exception as e:
            logger.error("playwright:click_selector FAILED sel=%s error=%s", selector, e)
            return {"ok": False, "selector": selector, "error": str(e)}

    async def fill(self, selector: str, value: str) -> Dict[str, Any]:
        """Fill a form field by CSS selector with validation (with retry)."""
        if not self._page:
            return {"ok": False, "selector": selector, "error": "No browser page active"}
        try:
            async def _do_fill():
                el = self._page.locator(selector)
                await el.fill(value)
                # Verify value was set
                actual = await el.input_value()
                if actual != value:
                    logger.warning(
                        "playwright:fill MISMATCH sel=%s expected_len=%d got_len=%d",
                        selector, len(value), len(actual),
                    )
                return True

            await _retry_async(
                _do_fill, max_attempts=self.retry_max_attempts,
                operation=f"fill({selector})",
            )
            logger.debug("playwright:fill sel=%s chars=%d", selector, len(value))
            return {"ok": True, "selector": selector, "chars": len(value)}
        except Exception as e:
            logger.error("playwright:fill FAILED sel=%s error=%s", selector, e)
            return {"ok": False, "selector": selector, "error": str(e)}

    async def select_dropdown(self, selector: str, value: str) -> Dict[str, Any]:
        """Select an option from a <select> dropdown by label or value.

        Returns:
            Dict with {ok, selector, selected_value}.
        """
        if not self._page:
            return {"ok": False, "selector": selector, "error": "No browser page active"}
        try:
            await self._page.select_option(selector, value)
            logger.debug("playwright:select_dropdown sel=%s val=%s", selector, value)
            return {"ok": True, "selector": selector, "selected_value": value}
        except Exception as e:
            logger.error("playwright:select_dropdown FAILED sel=%s error=%s", selector, e)
            return {"ok": False, "selector": selector, "error": str(e)}

    async def extract_table(self, selector: str = "table") -> Dict[str, Any]:
        """Extract tabular data from a <table> element.

        Args:
            selector: CSS selector for the table element (default: 'table').

        Returns:
            Dict with {ok, headers, rows, row_count}.
        """
        if not self._page:
            return {"ok": False, "headers": [], "rows": [],
                    "error": "No browser page active"}
        try:
            headers = await self._page.eval_on_selector_all(
                f"{selector} th",
                "els => els.map(e => e.textContent.trim())",
            )
            rows_raw = await self._page.eval_on_selector_all(
                f"{selector} tbody tr",
                "els => els.map(e => Array.from(e.cells).map(c => c.textContent.trim()))",
            )
            logger.debug("playwright:extract_table sel=%s rows=%d",
                         selector, len(rows_raw))
            return {"ok": True, "headers": headers, "rows": rows_raw,
                    "row_count": len(rows_raw)}
        except Exception as e:
            logger.error("playwright:extract_table FAILED sel=%s error=%s",
                         selector, e)
            return {"ok": False, "headers": [], "rows": [], "error": str(e)}

    async def find_elements(self, selector: str) -> Dict[str, Any]:
        """Detect elements by CSS selector or XPath.

        Args:
            selector: CSS selector or 'xpath=...' prefix.

        Returns:
            Dict with {ok, count, texts, selector}.
        """
        if not self._page:
            return {"ok": False, "count": 0, "texts": [],
                    "error": "No browser page active"}
        try:
            if selector.startswith("xpath="):
                xpath = selector[6:]
                count = await self._page.locator(f"xpath={xpath}").count()
                texts = await self._page.eval_on_selector_all(
                    f"xpath={xpath}",
                    "els => els.map(e => e.textContent.trim())",
                )
            else:
                count = await self._page.locator(selector).count()
                texts = await self._page.eval_on_selector_all(
                    selector, "els => els.map(e => e.textContent.trim())",
                )
            return {"ok": True, "count": count, "texts": texts[:20],
                    "selector": selector}
        except Exception as e:
            return {"ok": False, "count": 0, "texts": [], "error": str(e),
                    "selector": selector}

    async def get_content(self) -> Dict[str, Any]:
        """Get the page text content."""
        if not self._page:
            return {"ok": False, "text": "", "error": "No browser page active"}
        try:
            text = await self._page.inner_text("body")
            url = self._page.url
            return {"ok": True, "text": text, "url": url}
        except Exception as e:
            logger.error("playwright:get_content FAILED error=%s", e)
            return {"ok": False, "text": "", "error": str(e)}

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> Dict[str, Any]:
        """Wait for an element to appear on the page."""
        if not self._page:
            return {"ok": False, "selector": selector,
                    "error": "No browser page active"}
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return {"ok": True, "selector": selector}
        except Exception as e:
            logger.error("playwright:wait_for_selector FAILED sel=%s error=%s",
                         selector, e)
            return {"ok": False, "selector": selector, "error": str(e)}

    async def close(self) -> None:
        """Close the browser and cleanup resources."""
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as e:
            logger.warning("playwright:close warning: %s", e)
        finally:
            self._browser = None
            self._page = None
            self._pw = None
            self._launched = False

    # -- DesktopAutomation interface (sync wrappers) -------------------------

    def read_window_title(self) -> str:
        """Read the current page title (sync wrapper)."""
        if not self._page:
            return "No browser active"
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return "Browser active (async context)"
            return loop.run_until_complete(self._page.title())
        except Exception:
            return "Browser active"

    def health(self) -> dict:
        """Return comprehensive health status of the Playwright driver."""
        browser_ok = self._launched and self._browser is not None
        page_ok = self._page is not None
        page_url = ""
        if self._page:
            try:
                page_url = self._page.url
            except Exception:
                page_url = "unknown"
        return {
            "ok": browser_ok,
            "backend": self.backend,
            "detail": (
                f"Playwright browser active (headless={self.headless})"
                if self._launched
                else "Playwright ready, not yet launched"
            ),
            "launched": self._launched,
            "page_active": page_ok,
            "page_url": page_url,
            "screenshot_history_len": len(self._screenshot_hashes),
        }
