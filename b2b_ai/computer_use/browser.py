# -*- coding: utf-8 -*-
"""
browser.py — Computer use para navegación de ERPs web (CONTPAQi, SAP B1, etc.).

Problema que resuelve: muchos ERPs contables (especialmente CONTPAQi on-premise
y versiones web legacy) no exponen una API REST estable. La única vía de
automatización fiable es *ver* la pantalla y *actuar* sobre ella (computer use).

Este módulo define:

  - BrowserAutomation : interfaz abstracta, agnóstica del ERP.
  - MockBrowser       : implementación funcional EN MEMORIA para testing/demo.
  - Funciones helper  : navigate_to_erp, login_contpaqi, upload_cfdi, read_screen,
    form_fill, select_dropdown, extract_table, retry_action.

Features:
  - Form filling with validation
  - Dropdown selection
  - Table/grid extraction
  - Retry logic with exponential backoff
  - Error recovery
  - Health checks for all drivers
  - Structured logging for all operations
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry helper with exponential backoff (sync version)
# ---------------------------------------------------------------------------
def retry_action(
    fn,
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    operation: str = "operation",
) -> Any:
    """Execute a callable with retry + exponential backoff (sync).

    Args:
        fn: Callable to execute.
        max_attempts: Total attempts (1 = no retry).
        base_delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier for delay on each retry.
        retryable_exceptions: Tuple of exception types to retry on.
        operation: Name for logging.

    Returns:
        Result of fn on success.

    Raises:
        Last exception if all attempts fail.
    """
    last_exc = None
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "browser:retry attempt=%d/%d op=%s error=%s retry_in=%.1fs",
                    attempt, max_attempts, operation, exc, delay,
                )
                time.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(
                    "browser:retry EXHAUSTED attempt=%d op=%s error=%s",
                    attempt, operation, exc,
                )
    raise last_exc  # type: ignore[misc]


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
        """'Lee' la pantalla actual del ERP."""

    @abstractmethod
    def click_element(self, selector: str) -> dict:
        """Hace clic en un elemento identificado por selector (css/text)."""

    @abstractmethod
    def type_text(self, field: str, text: str) -> dict:
        """Escribe texto en un campo del formulario actual."""

    @abstractmethod
    def health(self) -> dict:
        """Devuelve {ok, backend, detail}."""


# ---------------------------------------------------------------------------
# Mock funcional (en memoria) para testing / demo
# ---------------------------------------------------------------------------
class MockBrowser(BrowserAutomation):
    """Simulación de un navegador sobre un ERP web.

    Mantiene un estado en memoria (URL actual, sesión, archivos subidos) que
    permite probar el flujo completo sin una conexión real.
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
        self._dropdowns: list = []  # registro de dropdowns seleccionados
        self._table_data: list = []  # datos de tabla capturados

    def _set_screen(self, page, text):
        self._page = page
        self._screen_text = text

    # -- alias de la especificación -----------------------------------------
    def navigate_to(self, url=None):
        return self.navigate_to_erp(url)

    def login_erp(self, credentials):
        return self.login(credentials)

    def read_screen_data(self):
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
            "elements": (
                ["usuario", "clave", "empresa", "btn_entrar"]
                if self._page == "login"
                else ["menu", "tabla_cfdi", "btn_subir"]
            ),
            "text": self._screen_text,
        }

    def click_element(self, selector):
        """Simula un clic sobre un elemento de la página actual."""
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

    # -- New: form filling with validation ----------------------------------
    def form_fill(self, fields: dict) -> dict:
        """Fill multiple form fields with validation.

        Args:
            fields: Dict of {field_name: value} pairs.

        Returns:
            Dict with {ok, filled_fields, errors}.
        """
        known = self._known_elements()
        filled = []
        errors = []
        for field, value in fields.items():
            if field not in known:
                errors.append(f"Campo '{field}' no está en la página actual.")
                continue
            self._typed[field] = value
            filled.append(field)

        return {
            "ok": len(errors) == 0,
            "filled_fields": filled,
            "errors": errors,
            "screen": self._page,
            "message": f"Campos llenados: {len(filled)}, errores: {len(errors)}.",
        }

    # -- New: dropdown selection ---------------------------------------------
    def select_dropdown(self, field: str, value: str) -> dict:
        """Select an option from a dropdown element.

        Args:
            field: Name of the dropdown field.
            value: Value to select.

        Returns:
            Dict with {ok, field, selected_value, screen}.
        """
        known = self._known_elements()
        if field not in known:
            return {"ok": False, "field": field, "screen": self._page,
                    "message": f"Campo '{field}' no está en la página actual."}
        self._dropdowns.append({"field": field, "value": value})
        self._typed[field] = value
        return {"ok": True, "field": field, "selected_value": value,
                "screen": self._page,
                "message": f"Dropdown '{field}' seleccionado: {value}."}

    # -- New: table extraction -----------------------------------------------
    def extract_table(self, table_id: str = "tabla_cfdi") -> dict:
        """Extract tabular data from a mock table.

        Args:
            table_id: Identifier of the table to extract.

        Returns:
            Dict with {ok, headers, rows, row_count}.
        """
        # Mock returns registered invoices as table data
        headers = ["folio_fiscal", "total", "emisor_rfc", "status", "capturado_en"]
        rows = []
        for inv in getattr(self, "_registered_invoices", []):
            rows.append([inv.get(h, "") for h in headers])

        # Also include uploaded files as a table
        if self.uploads:
            upload_headers = ["upload_id", "archivo", "subido_en"]
            for up in self.uploads:
                rows.append([up.get(h, "") for h in upload_headers])

        return {
            "ok": True,
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
            "table_id": table_id,
        }

    # -- New: retry wrapper --------------------------------------------------
    def retry_action(self, action_name: str, fn, **kwargs) -> dict:
        """Execute an action with retry logic.

        Args:
            action_name: Name for logging.
            fn: Callable to execute.

        Returns:
            Result of fn or error dict.
        """
        try:
            return retry_action(fn, operation=action_name, **kwargs)
        except Exception as e:
            return {"ok": False, "error": str(e),
                    "message": f"Acción '{action_name}' falló después de reintentos."}

    def health(self):
        return {"ok": True, "backend": self.backend,
                "detail": "MockBrowser operativo (sin conexión real).",
                "page": self._page,
                "session": bool(self.session),
                "uploads": len(self.uploads),
                "typed_fields": len(self._typed),
                "clicks": len(self._clicks)}


# ---------------------------------------------------------------------------
# Funciones helper a nivel de módulo (API pública simple)
# ---------------------------------------------------------------------------
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


def form_fill(fields: dict, browser: BrowserAutomation | None = None) -> dict:
    """Llena múltiples campos de formulario con validación."""
    b = browser or get_default_browser()
    if hasattr(b, "form_fill"):
        return b.form_fill(fields)
    return {"ok": False, "error": "Driver no soporta form_fill."}


def select_dropdown(field: str, value: str,
                    browser: BrowserAutomation | None = None) -> dict:
    """Selecciona una opción de un dropdown."""
    b = browser or get_default_browser()
    if hasattr(b, "select_dropdown"):
        return b.select_dropdown(field, value)
    return {"ok": False, "error": "Driver no soporta select_dropdown."}


def extract_table(table_id: str = "tabla_cfdi",
                  browser: BrowserAutomation | None = None) -> dict:
    """Extrae datos de una tabla."""
    b = browser or get_default_browser()
    if hasattr(b, "extract_table"):
        return b.extract_table(table_id)
    return {"ok": False, "error": "Driver no soporta extract_table."}


# ---------------------------------------------------------------------------
# Conveniencia: flujo orquestado end-to-end
# ---------------------------------------------------------------------------
def run_capture_flow(xml_path: str, credentials: dict,
                     browser: BrowserAutomation | None = None,
                     erp_url: str | None = None) -> dict:
    """Ejecuta el flujo completo de computer use sobre un ERP:
    navegar → login → subir CFDI → leer pantalla.

    Returns:
        Dict with the result of each step.
    """
    b = browser or get_default_browser()
    steps = {}
    steps["navigate"] = b.navigate_to_erp(erp_url)
    steps["login"] = b.login(credentials)
    steps["upload"] = b.upload_cfdi(xml_path)
    steps["screen"] = b.read_screen()
    ok = all(
        s.get("ok")
        for s in steps.values()
        if isinstance(s, dict) and "ok" in s
    )
    return {"ok": ok, "steps": steps}
