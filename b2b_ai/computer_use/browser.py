# -*- coding: utf-8 -*-
"""
browser.py — Computer-use para navegación de ERPs web (CONTPAQi, SAP B1, etc.).

Problema que resuelve: muchos ERPs contables (especialmente CONTPAQi on-premise
y versiones web legacy) no exponen una API REST estable. La única vía de
automatización fiable es *ver* la pantalla y *actuar* sobre ella (computer use).

Este módulo define:

  - BrowserAutomation : interfaz abstracta, agnóstica del ERP. Cualquier ERP
    web (CONTPAQi web, SAP, Odoo, Oracle) puede implementarla.
  - MockBrowser       : implementación funcional EN MEMORIA para testing y
    demo. Simula una sesión de navegador: navega, hace login, sube CFDI y
    "lee" la pantalla devolviendo un resumen del estado.
  - Funciones helper a nivel de módulo (navigate_to_erp, login_contpaqi,
    upload_cfdi, read_screen) que operan sobre un navegador por defecto,
    para uso directo desde el pipeline o tests.

En producción real se sustituiría MockBrowser por un driver real (Playwright
controlado por un agente de visión): el contrato abstracto no cambia.

Diseño rector: la máquina navega y rellena; la validación fiscal final y la
firma son del profesional. Ninguna acción de este módulo presenta nada ante
el SAT.
"""
from __future__ import annotations

import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime


# ---------------------------------------------------------------------------
# Interfaz abstracta (agnóstica del ERP)
# ---------------------------------------------------------------------------
class BrowserAutomation(ABC):
    """Contrato de un controlador de navegador para ERPs web.

    Métodos mínimos que debe cumplir cualquier driver (mock, Playwright,
    Selenium, CDP). Toda acción devuelve un dict con estado + payload para
    poder ser auditada de forma uniforme.
    """

    @abstractmethod
    def navigate_to_erp(self, url: str) -> dict:
        """Navega a la URL del ERP. Devuelve {ok, url, screen, page_title}."""

    @abstractmethod
    def login(self, credentials: dict) -> dict:
        """Hace login en el ERP con {username, password, company}.
        Devuelve {ok, session, screen, message}."""

    @abstractmethod
    def upload_cfdi(self, xml_path: str, **options) -> dict:
        """Sube un CFDI (XML) al ERP. Devuelve {ok, upload_id, screen}."""

    @abstractmethod
    def read_screen(self) -> dict:
        """'Lee' la pantalla actual del ERP y devuelve un resumen estructurado:
        {page, url, logged_in, elements, text}."""

    @abstractmethod
    def click_element(self, selector: str) -> dict:
        """Hace clic en un elemento identificado por selector (css/text).
        Devuelve {ok, selector, screen, message}."""

    @abstractmethod
    def type_text(self, field: str, text: str) -> dict:
        """Escribe texto en un campo del formulario actual.
        Devuelve {ok, field, screen, message}."""

    @abstractmethod
    def health(self) -> dict:
        """Devuelve {ok, backend, detail}."""


# ---------------------------------------------------------------------------
# Mock funcional (en memoria) para testing / demo
# ---------------------------------------------------------------------------
class MockBrowser(BrowserAutomation):
    """Simulación de un navegador sobre un ERP web.

    Mantiene un estado en memoria (URL actual, sesión, archivos subidos) que
    permite probar el flujo completo sin una conexión real. Útil para tests y
    para demos sin credenciales.
    """

    backend = "MockBrowser (computer use, en memoria)"
    DEFAULT_ERP_URL = "https://contaqiweb.example.com/app"

    def __init__(self, erp_url: str = DEFAULT_ERP_URL):
        self.erp_url = erp_url
        self.current_url = None
        self.session = None
        self.uploads = []
        self._page = "login"
        self._screen_text = ""
        self._typed: dict = {}   # campos del formulario con texto escrito
        self._clicks: list = []  # registro de selectores pulsados

    # -- primitivas internas ------------------------------------------------
    def _set_screen(self, page, text):
        self._page = page
        self._screen_text = text

    # -- alias de la especificación (nombres cortos del MVP) ----------------
    def navigate_to(self, url=None):
        """Alias de navigate_to_erp (nombrado en la especificación)."""
        return self.navigate_to_erp(url)

    def login_erp(self, credentials):
        """Alias de login (nombrado en la especificación)."""
        return self.login(credentials)

    def read_screen_data(self):
        """Alias de read_screen (nombrado en la especificación)."""
        return self.read_screen()

    # -- interfaz -----------------------------------------------------------
    def navigate_to_erp(self, url=None):
        url = url or self.erp_url
        self.current_url = url
        self._set_screen("login", "CONTPAQi Web — Iniciar sesión")
        return {"ok": True, "url": url, "page": "login",
                "page_title": "CONTPAQi Web", "screen": self._page}

    def login(self, credentials):
        username = (credentials or {}).get("username", "")
        if not username:
            return {"ok": False, "session": None, "screen": self._page,
                    "message": "Falta 'username' en las credenciales."}
        self.session = {"username": username,
                        "token": "mock-token-" + uuid.uuid4().hex[:8],
                        "login_at": datetime.now().isoformat(timespec="seconds")}
        self._set_screen("dashboard", f"Panel de control — {username}")
        return {"ok": True, "session": self.session, "screen": self._page,
                "message": f"Sesión iniciada como {username}."}

    def upload_cfdi(self, xml_path, **options):
        if not os.path.exists(xml_path):
            return {"ok": False, "upload_id": None, "screen": self._page,
                    "message": f"Archivo no encontrado: {xml_path}"}
        if self.session is None:
            return {"ok": False, "upload_id": None, "screen": self._page,
                    "message": "No hay sesión activa; haga login primero."}
        upload_id = "UPL-" + uuid.uuid4().hex[:10].upper()
        self.uploads.append({
            "upload_id": upload_id,
            "archivo": os.path.basename(xml_path),
            "subido_en": datetime.now().isoformat(timespec="seconds"),
        })
        self._set_screen("upload_result",
                         f"CFDI {os.path.basename(xml_path)} cargado OK")
        return {"ok": True, "upload_id": upload_id, "screen": self._page,
                "archivos_subidos": len(self.uploads),
                "message": f"CFDI cargado: {upload_id}"}

    def read_screen(self):
        return {
            "page": self._page,
            "url": self.current_url,
            "logged_in": self.session is not None,
            "session_user": (self.session or {}).get("username", ""),
            "uploads": len(self.uploads),
            "elements": ["usuario", "clave", "empresa", "btn_entrar"] if self._page == "login"
                        else ["menu", "tabla_cfdi", "btn_subir"],
            "text": self._screen_text,
        }

    def click_element(self, selector):
        """Simula un clic sobre un elemento de la página actual.

        Valida que el selector exista en la página actual (login vs. resto).
        En la página de login, pulsar `btn_entrar` intenta completar la sesión
        con las credenciales ya tipeadas en `usuario`/`clave`."""
        known = self._known_elements()
        if selector not in known:
            return {"ok": False, "selector": selector, "screen": self._page,
                    "message": f"Elemento '{selector}' no está en la página actual."}
        self._clicks.append(selector)
        if selector == "btn_entrar" and self._page == "login":
            username = self._typed.get("usuario", "")
            if username:
                self.login({"username": username,
                            "password": self._typed.get("clave", "")})
                return {"ok": True, "selector": selector,
                        "screen": self._page,
                        "message": "Sesión iniciada desde clic en btn_entrar."}
        return {"ok": True, "selector": selector, "screen": self._page,
                "message": f"Clic en {selector} registrado."}

    def type_text(self, field, text):
        """Simula escribir texto en un campo del formulario actual."""
        known = self._known_elements()
        if field not in known:
            return {"ok": False, "field": field, "screen": self._page,
                    "message": f"Campo '{field}' no está en la página actual."}
        self._typed[field] = text
        return {"ok": True, "field": field, "value_len": len(text),
                "screen": self._page,
                "message": f"Texto escrito en {field}."}

    def _known_elements(self):
        if self._page == "login":
            return ["usuario", "clave", "empresa", "btn_entrar"]
        return ["menu", "tabla_cfdi", "btn_subir", "btn_subir_archivo"]

    def health(self):
        return {"ok": True, "backend": self.backend,
                "detail": "MockBrowser operativo (sin conexión real)."}


# ---------------------------------------------------------------------------
# Funciones helper a nivel de módulo (API pública simple)
# ---------------------------------------------------------------------------
# Navegador por defecto compartido (mock). En producción se inyectaría el driver
# real (p.ej. PlaywrightBrowser) que implemente BrowserAutomation.
_DEFAULT_BROWSER: BrowserAutomation | None = None


def get_default_browser() -> BrowserAutomation:
    global _DEFAULT_BROWSER
    if _DEFAULT_BROWSER is None:
        _DEFAULT_BROWSER = MockBrowser()
    return _DEFAULT_BROWSER


def set_default_browser(browser: BrowserAutomation) -> None:
    """Inyecta un navegador (mock o real). Permite swap en tests/producción."""
    global _DEFAULT_BROWSER
    _DEFAULT_BROWSER = browser


def navigate_to_erp(url: str | None = None, browser: BrowserAutomation | None = None) -> dict:
    """Navega al ERP. Devuelve {ok, url, page, page_title, screen}."""
    b = browser or get_default_browser()
    return b.navigate_to_erp(url)


def login_contpaqi(credentials: dict, browser: BrowserAutomation | None = None) -> dict:
    """Inicia sesión en CONTPAQi Web. Devuelve {ok, session, message}."""
    b = browser or get_default_browser()
    return b.login(credentials)


def upload_cfdi(xml_path: str, browser: BrowserAutomation | None = None, **options) -> dict:
    """Sube un CFDI al ERP. Devuelve {ok, upload_id, message}."""
    b = browser or get_default_browser()
    return b.upload_cfdi(xml_path, **options)


def read_screen(browser: BrowserAutomation | None = None) -> dict:
    """Lee la pantalla actual. Devuelve resumen estructurado."""
    b = browser or get_default_browser()
    return b.read_screen()


# -- helpers con los nombres de la especificación ----------------------------
def navigate_to(url: str, browser: BrowserAutomation | None = None) -> dict:
    """Navega al ERP (nombre corto de la especificación)."""
    b = browser or get_default_browser()
    return b.navigate_to_erp(url)


def login_erp(credentials: dict, browser: BrowserAutomation | None = None) -> dict:
    """Hace login en el ERP (nombre corto de la especificación)."""
    b = browser or get_default_browser()
    return b.login(credentials)


def read_screen_data(browser: BrowserAutomation | None = None) -> dict:
    """Lee la pantalla actual (nombre corto de la especificación)."""
    b = browser or get_default_browser()
    return b.read_screen()


def click_element(selector: str, browser: BrowserAutomation | None = None) -> dict:
    """Hace clic en un elemento de la página actual."""
    b = browser or get_default_browser()
    return b.click_element(selector)


def type_text(field: str, text: str, browser: BrowserAutomation | None = None) -> dict:
    """Escribe texto en un campo del formulario actual."""
    b = browser or get_default_browser()
    return b.type_text(field, text)


# ---------------------------------------------------------------------------
# Conveniencia: flujo orquestado end-to-end
# ---------------------------------------------------------------------------
def run_capture_flow(xml_path: str, credentials: dict,
                     browser: BrowserAutomation | None = None,
                     erp_url: str | None = None) -> dict:
    """Ejecuta el flujo completo de computer use sobre un ERP:
    navegar → login → subir CFDI → leer pantalla.

    Devuelve un dict con el resultado de cada paso. Útil para demos y tests
    de integración del módulo.
    """
    b = browser or get_default_browser()
    steps = {}
    steps["navigate"] = b.navigate_to_erp(erp_url)
    steps["login"] = b.login(credentials)
    steps["upload"] = b.upload_cfdi(xml_path)
    steps["screen"] = b.read_screen()
    # screen es informativo (no declara ok); solo cuentan los pasos con "ok"
    ok = all(s.get("ok") for s in steps.values() if isinstance(s, dict) and "ok" in s)
    return {"ok": ok, "steps": steps}
