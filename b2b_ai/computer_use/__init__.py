# -*- coding: utf-8 -*-
"""
computer_use — Computer use para navegación de ERPs web y de escritorio.

Re-exporta la interfaz abstracta BrowserAutomation, el mock funcional y las
funciones helper para ERPs web (CONTPAQi web, SAP, Odoo...) así como los
drivers de escritorio para las suites on-premise (CONTPAQi y Aspel), que no
exponen API REST y se automatizan viendo la ventana.
"""
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
# Real Playwright-based drivers
from b2b_ai.computer_use.playwright_desktop import PlaywrightDesktop
from b2b_ai.computer_use.contpaqi_real_driver import CONTPAQiRealDriver
from b2b_ai.computer_use.aspel_real_driver import AspelRealDriver

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
    # Real drivers (Playwright)
    "PlaywrightDesktop",
    "CONTPAQiRealDriver",
    "AspelRealDriver",
]
