# -*- coding: utf-8 -*-
"""
computer_use — Computer use para navegación de ERPs web y de escritorio.

Re-exporta la interfaz abstracta BrowserAutomation, el mock funcional y las
funciones helper para ERPs web (CONTPAQi web, SAP, Odoo...) así como los
drivers de escritorio para las suites on-premise (CONTPAQi y Aspel), que no
exponen API REST y se automatizan viendo la ventana.

Los drivers reales de Playwright (PlaywrightDesktop, CONTPAQiRealDriver,
AspelRealDriver) se importan de forma LAZY vía __getattr__ para que importar
este paquete no cargue Playwright/Chromium (reduce startup time y evita
dependencias innecesarias cuando Computer Use está deshabilitado).
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from b2b_ai.computer_use.browser import (
    BrowserAutomation,
    MockBrowser,
    navigate_to_erp,
    login_contpaqi,
    upload_cfdi,
    read_screen,
    run_capture_flow,
    get_default_browser,
    set_default_browser,
    form_fill,
    select_dropdown,
    extract_table,
    retry_action,
)
from b2b_ai.computer_use.contpaqi_driver import (
    DesktopAutomation,
    MockDesktop,
    ContpaqiDriver,
    get_default_contpaqi,
    set_default_contpaqi,
    contpaqi_login,
    contpaqi_register,
)
from b2b_ai.computer_use.aspel_driver import (
    AspelDriver,
    get_default_aspel,
    set_default_aspel,
    aspel_login,
    aspel_register,
)

__all__ = [
    # web ERPs
    "BrowserAutomation",
    "MockBrowser",
    "navigate_to_erp",
    "login_contpaqi",
    "upload_cfdi",
    "read_screen",
    "run_capture_flow",
    "get_default_browser",
    "set_default_browser",
    "form_fill",
    "select_dropdown",
    "extract_table",
    "retry_action",
    # escritorio (CONTPAQi)
    "DesktopAutomation",
    "MockDesktop",
    "ContpaqiDriver",
    "get_default_contpaqi",
    "set_default_contpaqi",
    "contpaqi_login",
    "contpaqi_register",
    # escritorio (Aspel)
    "AspelDriver",
    "get_default_aspel",
    "set_default_aspel",
    "aspel_login",
    "aspel_register",
    # Real drivers (Playwright) — lazy
    "PlaywrightDesktop",
    "PlaywrightDesktopConfig",
    "CONTPAQiRealDriver",
    "AspelRealDriver",
    "_retry_async",
]

_LAZY_IMPORTS = {
    "PlaywrightDesktop": ("b2b_ai.computer_use.playwright_desktop", "PlaywrightDesktop"),
    "PlaywrightDesktopConfig": ("b2b_ai.computer_use.playwright_desktop", "PlaywrightDesktopConfig"),
    "_retry_async": ("b2b_ai.computer_use.playwright_desktop", "_retry_async"),
    "CONTPAQiRealDriver": ("b2b_ai.computer_use.contpaqi_real_driver", "CONTPAQiRealDriver"),
    "AspelRealDriver": ("b2b_ai.computer_use.aspel_real_driver", "AspelRealDriver"),
}


def __getattr__(name: str) -> Any:
    """Lazily import Playwright-based drivers on first access."""
    if name in _LAZY_IMPORTS:
        mod, attr = _LAZY_IMPORTS[name]
        import importlib
        return getattr(importlib.import_module(mod), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list:
    return sorted(set(__all__) | set(globals().keys()))
