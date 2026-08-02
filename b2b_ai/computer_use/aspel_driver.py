# -*- coding: utf-8 -*-
"""
aspel_driver.py — Driver de computer use para Aspel de escritorio (SAE/COI).

Aspel es un ERP de escritorio (SAE, COI, NOI) sin API REST estable; se
automatiza por computer use de escritorio: capturar pantalla, localizar
controles y pulsar/teclear, igual que lo haría una persona.

Este driver implementa el contrato DesktopAutomation con la semántica concreta
de Aspel sobre un backend de escritorio (normalmente MockDesktop):

  - open_app(): arranca Aspel en su propia ventana.
  - login(): autentica con usuario/clave/empresa.
  - open_invoices(): abre el módulo de facturas.
  - capture_invoice_grid(): lee el grid de facturas del módulo activo.
  - register_invoice(): registra un CFDI capturado como pendiente de revisión.

En producción, AspelDriver se implementaría sobre Playwright/Sikuli/visión
sobre la ventana de escritorio; el contrato del agente no cambia.
"""
from __future__ import annotations

from datetime import datetime

from b2b_ai.computer_use.contpaqi_driver import DesktopAutomation, MockDesktop


class AspelDriver(DesktopAutomation):
    """Driver de computer use de escritorio para Aspel (SAE/COI).

    Comparte el contrato DesktopAutomation con CONTPAQi, pero abre su propia
    ventana y usa la semántica de pantallas de Aspel.
    """

    APP_NAME = "Aspel"
    APP_WINDOW = "Aspel SAE 8.0"
    backend = "Aspel (computer use, desktop mock)"

    def __init__(self, desktop: DesktopAutomation | None = None):
        self.desktop = desktop or MockDesktop()
        self.session = None
        self._registered = []
        self._invoices_open = False

    def open_app(self) -> dict:
        return {"ok": True, "app": self.APP_NAME,
                "window": self.desktop.read_window_title()}

    def login(self, credentials: dict) -> dict:
        creds = credentials or {}
        usuario = creds.get("usuario", "")
        if not usuario:
            return {"ok": False, "session": None,
                    "message": "Falta 'usuario' en las credenciales."}
        self.desktop.type_text(usuario)
        self.desktop.type_text(creds.get("password", ""))
        self.session = {
            "usuario": usuario,
            "empresa": creds.get("empresa", ""),
            "login_at": datetime.now().isoformat(timespec="seconds"),
        }
        return {"ok": True, "session": self.session,
                "message": f"Sesión Aspel iniciada como {usuario}."}

    def open_invoices(self) -> dict:
        if self.session is None:
            return {"ok": False,
                    "message": "Sin sesión; autentíquese primero."}
        self._invoices_open = True
        return {"ok": True, "module": "facturas",
                "message": "Módulo de facturas abierto."}

    def capture_invoice_grid(self) -> dict:
        if self.session is None:
            return {"ok": False, "grid": [],
                    "message": "Sin sesión; autentíquese primero."}
        return {"ok": True,
                "grid": [{"folio_fiscal": r["folio_fiscal"],
                          "status": r["status"]} for r in self._registered],
                "message": "Grid de facturas capturado."}

    def register_invoice(self, data: dict) -> dict:
        if self.session is None:
            return {"ok": False,
                    "message": "Sin sesión; autentíquese primero."}
        folio = (data or {}).get("folio_fiscal")
        if not folio:
            return {"ok": False, "registro": None,
                    "message": "Falta 'folio_fiscal' del CFDI."}
        registro = {
            "folio_fiscal": folio,
            "total": (data or {}).get("total"),
            "status": "pendiente_revision",
            "capturado_en": datetime.now().isoformat(timespec="seconds"),
        }
        self._registered.append(registro)
        return {"ok": True, "registro": registro,
                "message": f"CFDI {folio} registrado (pendiente de revisión)."}

    def health(self):
        return {"ok": True, "backend": self.backend,
                "detail": "AspelDriver operativo (sobre escritorio mock)."}

    # -- primitivas de escritorio: delegan al backend DesktopAutomation ------
    def screenshot(self):
        return self.desktop.screenshot()

    def read_window_title(self):
        return self.desktop.read_window_title()

    def click(self, x: int, y: int):
        return self.desktop.click(x, y)

    def type_text(self, text: str):
        return self.desktop.type_text(text)

    def press_key(self, key: str):
        return self.desktop.press_key(key)


# ---------------------------------------------------------------------------
# Helpers de módulo (API pública simple)
# ---------------------------------------------------------------------------
_DEFAULT_ASPEL: AspelDriver | None = None


def get_default_aspel() -> AspelDriver:
    global _DEFAULT_ASPEL
    if _DEFAULT_ASPEL is None:
        _DEFAULT_ASPEL = AspelDriver()
    return _DEFAULT_ASPEL


def set_default_aspel(driver: AspelDriver | None) -> None:
    global _DEFAULT_ASPEL
    _DEFAULT_ASPEL = driver


def aspel_login(credentials: dict) -> dict:
    return get_default_aspel().login(credentials)


def aspel_register(data: dict) -> dict:
    return get_default_aspel().register_invoice(data)
