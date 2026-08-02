# -*- coding: utf-8 -*-
"""
smoke_test.py — Smoke test para verificar que Playwright + Chromium funciona.

Se puede ejecutar:
  1. Como script standalone: python -m b2b_ai.computer_use.smoke_test
  2. Como endpoint de health: GET /health/playwright (integrado en app.py)

Verifica que:
  - El módulo playwright se importa correctamente
  - El binario de Chromium es accesible
  - Se puede abrir una página y tomar screenshot
  - El cleanup es limpio (sin leaks de fd)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def run_smoke_test() -> Dict[str, Any]:
    """Ejecuta el smoke test completo de Playwright + Chromium.

    Returns:
        Dict con {ok, message, details}.
    """
    t0 = time.monotonic()
    details: Dict[str, Any] = {}

    # 1) Verificar que playwright se importa
    try:
        from playwright.async_api import async_playwright
        details["import"] = "ok"
    except ImportError as e:
        return {
            "ok": False,
            "message": f"No se pudo importar playwright: {e}",
            "details": {"import": "failed"},
        }

    # 2) Verificar que el binario de Chromium existe
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    details["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path or "(default ~/.cache/ms-playwright)"

    chromium_found = False
    search_roots = [browsers_path] if browsers_path else []
    search_roots.append(str(Path.home() / ".cache" / "ms-playwright"))

    for root in search_roots:
        if not root:
            continue
        root_path = Path(root)
        if root_path.is_dir():
            # Playwright stores browsers as chromium-XXXX/chrome-linux/chrome
            for child in root_path.iterdir():
                if child.name.startswith("chromium"):
                    chrome_bin = child / "chrome-linux" / "chrome"
                    if chrome_bin.exists():
                        chromium_found = True
                        details["chromium_path"] = str(chrome_bin)
                        break
                    # Also check ffmpeg (marker that install completed)
                    for sub in child.iterdir():
                        if sub.name.startswith("chrome"):
                            chromium_found = True
                            details["chromium_dir"] = str(sub)
                            break
            if chromium_found:
                break

    if not chromium_found:
        return {
            "ok": False,
            "message": "Chromium no encontrado en PLAYWRIGHT_BROWSERS_PATH",
            "details": details,
        }
    details["chromium_binary"] = "found"

    # 3) Lanzar browser, abrir página, tomar screenshot, cerrar
    pw = None
    browser = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
        )
        details["browser_launch"] = "ok"

        page = await browser.new_page()
        # Navegar a una página data: minimal (sin red)
        await page.goto("data:text/html,<h1>B2B-AI Playwright Smoke Test OK</h1>")
        title = await page.title()
        details["page_title"] = title

        # Tomar screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            screenshot_path = tmp.name
        await page.screenshot(path=screenshot_path, full_page=True)
        size = os.path.getsize(screenshot_path)
        details["screenshot_path"] = screenshot_path
        details["screenshot_bytes"] = size

        # Cleanup screenshot
        os.unlink(screenshot_path)
        details["screenshot_cleanup"] = "ok"

        await page.close()
        details["page_close"] = "ok"

    except Exception as e:
        details["error"] = str(e)
        logger.error("smoke_test:error %s", e)
        return {
            "ok": False,
            "message": f"Error durante smoke test: {e}",
            "details": details,
        }
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass

    elapsed = time.monotonic() - t0
    details["elapsed_seconds"] = round(elapsed, 3)

    return {
        "ok": True,
        "message": "Playwright + Chromium operativo",
        "details": details,
    }


def run_smoke_test_sync() -> Dict[str, Any]:
    """Versión sincrónica del smoke test (para CLI o healthcheck sync)."""
    return asyncio.run(run_smoke_test())


def main():
    """CLI entry point: python -m b2b_ai.computer_use.smoke_test"""
    import json

    print("=== B2B-AI Playwright Smoke Test ===")
    result = run_smoke_test_sync()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
