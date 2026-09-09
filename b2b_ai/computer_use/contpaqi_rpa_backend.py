# -*- coding: utf-8 -*-
"""
contpaqi_rpa_backend.py — Backends de RPA de escritorio para CONTPAQi.

Decisión de negocio (auditoría de producción, ver contpaqi_real_driver.py):
CONTPAQi se automatiza sobre la app de ESCRITORIO real (Windows), vía RPA de
controles UIA/Win32 — NO existe una "CONTPAQi Web". La librería de RPA de
escritorio usada es pywinauto (backend UIA), import perezoso y dependencia
OPCIONAL: si no está instalada, o si no se corre en Windows, el backend real
no está disponible y se debe usar el simulador.

HONESTIDAD OBLIGATORIA (mismo principio que SATSubmitter, commit 27f94a7):

    CONTPAQI_VERIFICADO_CONTRA_REAL = False

No hay ninguna instancia real de CONTPAQi disponible en este entorno de
desarrollo para probar contra ella. `PywinautoContpaqiBackend` está escrito
con la mejor comprensión disponible del flujo típico y documentado
públicamente de "Captura de pólizas" en CONTPAQi Contabilidad (menú
Movimientos > Pólizas > Captura de pólizas; automation_id de los campos del
diálogo de acceso; grid Cuenta/Concepto/Cargo/Abono con validación de
diferencia == 0.00) — pero ESOS SELECTORES/IDs NUNCA HAN SIDO EJECUTADOS NI
CONFIRMADOS contra una instalación real de CONTPAQi. Antes de usarlo en
producción, alguien con acceso a una instalación real (o una VM/servidor
Windows dedicado) debe:

    1. Verificar los automation_id / títulos reales de cada control.
    2. Ajustar MENU_PATH_POLIZAS / MENU_PATH_FACTURAS si difieren.
    3. Correr un piloto contra un cliente real.
    4. Sólo entonces, cambiar CONTPAQI_VERIFICADO_CONTRA_REAL a True (y
       documentar cuándo/contra qué versión de CONTPAQi se verificó).

Este archivo NUNCA debe cambiar ese flag por su cuenta ni pretender que el
backend de pywinauto fue probado. `ContpaqiSimulatorBackend` es honesto en
sentido opuesto: SIEMPRE reporta verificado_contra_real=False porque, por
definición, no es CONTPAQi real.
"""
from __future__ import annotations

import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONTPAQI_VERIFICADO_CONTRA_REAL = False

# ---------------------------------------------------------------------------
# Estructura de menús / controles típica de CONTPAQi Contabilidad para
# "Captura de pólizas", tomada de documentación pública y tutoriales.
# NUNCA CONFIRMADA CONTRA UNA INSTALACIÓN REAL. Ver disclaimer arriba.
# ---------------------------------------------------------------------------
DEFAULT_WINDOW_TITLE_RE = r".*CONTPAQi.*Contabilidad.*"
DEFAULT_PROCESS_NAME = "Contabilidad.exe"
MENU_PATH_POLIZAS = ["Movimientos", "Pólizas", "Captura de pólizas"]
MENU_PATH_FACTURAS = ["Movimientos", "Facturación"]
MENU_PATHS = {
    "polizas": MENU_PATH_POLIZAS,
    "facturas": MENU_PATH_FACTURAS,
    "catalogos": ["Catálogos", "Cuentas"],
    "reportes": ["Consultas", "Balanza de comprobación"],
}


# ---------------------------------------------------------------------------
# Contrato interno de backend (no es la ABC pública ComputerUseDriver; es el
# nivel de "controlar la ventana" del que CONTPAQiRealDriver se compone).
# ---------------------------------------------------------------------------
class ContpaqiDesktopBackend(ABC):
    """Contrato mínimo para controlar la ventana de escritorio de CONTPAQi.

    CONTPAQiRealDriver (interface.ComputerUseDriver) delega en un backend de
    este tipo. Cada método devuelve un dict {ok, ...} auditable, igual que el
    resto del código de computer_use.
    """

    #: Nombre legible del backend, para logs/health checks/reportes.
    NOMBRE: str = "backend-desconocido"
    #: Si True, este backend habla con una instancia real de CONTPAQi.
    ES_REAL: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """True si este backend puede operar en el entorno actual."""

    @abstractmethod
    def launch_or_attach(self) -> Dict[str, Any]:
        """Encuentra o lanza la ventana de CONTPAQi. {ok, titulo_ventana|error}."""

    @abstractmethod
    def login(self, usuario: str, password: str, empresa: str = "") -> Dict[str, Any]:
        """Inicia sesión en el diálogo de acceso a empresa. {ok, error?}."""

    @abstractmethod
    def logout(self) -> Dict[str, Any]:
        """Cierra la sesión actual. {ok}."""

    @abstractmethod
    def navigate(self, menu_path: List[str]) -> Dict[str, Any]:
        """Navega una ruta de menú. {ok, modulo|error}."""

    @abstractmethod
    def capture_poliza(self, poliza: Dict[str, Any]) -> Dict[str, Any]:
        """Captura una póliza en el grid Cuenta/Concepto/Cargo/Abono. {ok, registro|error}."""

    @abstractmethod
    def read_poliza(self, poliza_id: str) -> Dict[str, Any]:
        """Lee el registro de una póliza ya capturada. {ok, registro|error}."""

    @abstractmethod
    def capture_factura(self, factura: Dict[str, Any]) -> Dict[str, Any]:
        """Captura un CFDI en el módulo de facturación. {ok, registro|error}."""

    @abstractmethod
    def read_factura(self, folio_fiscal: str) -> Dict[str, Any]:
        """Lee el registro de una factura ya capturada. {ok, registro|error}."""

    @abstractmethod
    def close(self) -> Dict[str, Any]:
        """Libera recursos (cierra el cliente HTTP, o simplemente se desconecta
        de la ventana sin cerrar CONTPAQi -- nunca se cierra la app del usuario)."""

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """Estado del backend. {ok, backend, verificado_contra_real, ...}."""


# ---------------------------------------------------------------------------
# Backend real: pywinauto (Windows, UIA)
# ---------------------------------------------------------------------------
class PywinautoContpaqiBackend(ContpaqiDesktopBackend):
    """RPA de escritorio real sobre CONTPAQi Contabilidad usando pywinauto.

    ADVERTENCIA: ver el disclaimer de honestidad al inicio del módulo. Este
    backend NUNCA se ha ejecutado contra una instalación real de CONTPAQi
    (no hay ninguna disponible en este entorno). El flujo y los selectores
    codificados aquí son la mejor aproximación al flujo público y documentado
    de "Captura de pólizas" en CONTPAQi Contabilidad, pero requieren
    verificación contra una instalación real antes de usarse en producción.
    """

    NOMBRE = "pywinauto (RPA de escritorio Windows, UIA)"
    ES_REAL = True

    def __init__(
        self,
        window_title_re: Optional[str] = None,
        process_name: Optional[str] = None,
        timeout_seconds: int = 15,
    ):
        self._window_title_re = window_title_re or DEFAULT_WINDOW_TITLE_RE
        self._process_name = process_name or DEFAULT_PROCESS_NAME
        self._timeout = timeout_seconds
        self._app = None
        self._win = None

    # -- disponibilidad ---------------------------------------------------
    def is_available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import pywinauto  # noqa: F401
            return True
        except ImportError:
            return False

    def _import_pywinauto(self):
        try:
            from pywinauto import Application
            return Application
        except ImportError as e:
            raise RuntimeError(
                "pywinauto no está instalado. Es la dependencia OPCIONAL "
                "requerida para automatizar CONTPAQi de escritorio en "
                "Windows. Instalar con: pip install pywinauto"
            ) from e

    # -- ciclo de vida ------------------------------------------------------
    def launch_or_attach(self) -> Dict[str, Any]:
        if sys.platform != "win32":
            return {
                "ok": False,
                "error": (
                    "PywinautoContpaqiBackend requiere Windows (pywinauto "
                    f"controla ventanas Win32/UIA); plataforma actual: "
                    f"'{sys.platform}'. Use ContpaqiSimulatorBackend en "
                    "desarrollo/CI no-Windows."
                ),
            }
        try:
            Application = self._import_pywinauto()
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

        try:
            self._app = Application(backend="uia").connect(
                title_re=self._window_title_re, timeout=self._timeout
            )
        except Exception:
            try:
                self._app = Application(backend="uia").start(self._process_name)
            except Exception as e:
                return {
                    "ok": False,
                    "error": (
                        "Ventana de CONTPAQi no encontrada y no se pudo "
                        f"iniciar '{self._process_name}': {e}"
                    ),
                }
        try:
            self._win = self._app.window(title_re=self._window_title_re)
            self._win.wait("visible", timeout=self._timeout)
        except Exception as e:
            return {"ok": False, "error": f"Ventana de CONTPAQi no encontrada: {e}"}

        return {"ok": True, "titulo_ventana": self._win.window_text()}

    def login(self, usuario: str, password: str, empresa: str = "") -> Dict[str, Any]:
        if self._win is None:
            return {"ok": False, "error": "Sin ventana activa; llame launch_or_attach() primero."}
        try:
            # Campos del diálogo de acceso a empresa (automation_id NO
            # verificados contra una instalación real -- ver disclaimer).
            self._win.child_window(auto_id="txtUsuario", control_type="Edit").set_text(usuario)
            self._win.child_window(auto_id="txtPassword", control_type="Edit").set_text(password)
            if empresa:
                self._win.child_window(auto_id="cboEmpresa", control_type="ComboBox").select(empresa)
            self._win.child_window(auto_id="btnAceptar", control_type="Button").click_input()
            # El menú principal apareciendo es la señal de que el login
            # funcionó (equivalente al "verify_authenticated" del ABC).
            self._win.child_window(title="Menú principal", control_type="MenuBar").wait(
                "exists", timeout=self._timeout
            )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"Error de login en CONTPAQi: {e}"}

    def logout(self) -> Dict[str, Any]:
        if self._win is None:
            return {"ok": True}
        try:
            self._win.menu_select("Archivo->Cerrar sesión")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"Error cerrando sesión: {e}"}

    def navigate(self, menu_path: List[str]) -> Dict[str, Any]:
        if self._win is None:
            return {"ok": False, "error": "Sin ventana activa."}
        try:
            self._win.menu_select("->".join(menu_path))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo navegar el menú {menu_path}: {e}"}

    def capture_poliza(self, poliza: Dict[str, Any]) -> Dict[str, Any]:
        if self._win is None:
            return {"ok": False, "error": "Sin ventana activa."}
        conceptos = poliza.get("conceptos") or []
        cargo_total = round(sum(float(c.get("cargo", 0) or 0) for c in conceptos), 2)
        abono_total = round(sum(float(c.get("abono", 0) or 0) for c in conceptos), 2)
        if round(cargo_total - abono_total, 2) != 0:
            return {
                "ok": False,
                "error": (
                    f"La póliza no está balanceada. Diferencia: "
                    f"{cargo_total - abono_total:.2f}."
                ),
            }
        try:
            dlg = self._win.child_window(title="Captura de pólizas", control_type="Window")
            dlg.child_window(auto_id="cboTipoPoliza", control_type="ComboBox").select(
                poliza.get("tipo", "Diario")
            )
            dlg.child_window(auto_id="txtFecha", control_type="Edit").set_text(poliza.get("fecha", ""))
            grid = dlg.child_window(auto_id="gridConceptos", control_type="DataGrid")
            for i, concepto in enumerate(conceptos):
                grid.cell(i, "Cuenta").set_text(str(concepto.get("cuenta", "")))
                grid.cell(i, "Concepto").set_text(str(concepto.get("concepto", "")))
                grid.cell(i, "Cargo").set_text(str(concepto.get("cargo", 0)))
                grid.cell(i, "Abono").set_text(str(concepto.get("abono", 0)))
            dlg.child_window(auto_id="btnGuardar", control_type="Button").click_input()
            # Verificación: leer el número de póliza asignado por CONTPAQi.
            numero = dlg.child_window(auto_id="lblNumeroPoliza", control_type="Text").window_text()
            registro = {
                "poliza_id": numero,
                "tipo": poliza.get("tipo"),
                "fecha": poliza.get("fecha"),
                "conceptos": conceptos,
                "cargo_total": cargo_total,
                "abono_total": abono_total,
                "estado": "guardada",
            }
            return {"ok": True, "registro": registro}
        except Exception as e:
            return {"ok": False, "error": f"Error capturando póliza en CONTPAQi: {e}"}

    def read_poliza(self, poliza_id: str) -> Dict[str, Any]:
        if self._win is None:
            return {"ok": False, "error": "Sin ventana activa."}
        try:
            self.navigate(MENU_PATH_POLIZAS)
            grid = self._win.child_window(auto_id="gridPolizas", control_type="DataGrid")
            fila = grid.row_by_value("Numero", poliza_id)
            if fila is None:
                return {"ok": False, "error": f"Póliza '{poliza_id}' no encontrada en el grid."}
            return {"ok": True, "registro": {"poliza_id": poliza_id, "estado": "guardada"}}
        except Exception as e:
            return {"ok": False, "error": f"Error leyendo póliza: {e}"}

    def capture_factura(self, factura: Dict[str, Any]) -> Dict[str, Any]:
        if self._win is None:
            return {"ok": False, "error": "Sin ventana activa."}
        folio = factura.get("folio_fiscal")
        if not folio:
            return {"ok": False, "error": "Falta 'folio_fiscal'."}
        try:
            dlg = self._win.child_window(title="Captura de facturas", control_type="Window")
            dlg.child_window(auto_id="txtFolioFiscal", control_type="Edit").set_text(str(folio))
            dlg.child_window(auto_id="txtRfcEmisor", control_type="Edit").set_text(
                str(factura.get("emisor_rfc", ""))
            )
            dlg.child_window(auto_id="txtTotal", control_type="Edit").set_text(
                str(factura.get("total", ""))
            )
            dlg.child_window(auto_id="btnGuardar", control_type="Button").click_input()
            registro = {
                "folio_fiscal": folio,
                "total": factura.get("total"),
                "emisor_rfc": factura.get("emisor_rfc"),
                "estado": "guardada",
            }
            return {"ok": True, "registro": registro}
        except Exception as e:
            return {"ok": False, "error": f"Error capturando factura en CONTPAQi: {e}"}

    def read_factura(self, folio_fiscal: str) -> Dict[str, Any]:
        if self._win is None:
            return {"ok": False, "error": "Sin ventana activa."}
        try:
            self.navigate(MENU_PATH_FACTURAS)
            grid = self._win.child_window(auto_id="gridFacturas", control_type="DataGrid")
            fila = grid.row_by_value("FolioFiscal", folio_fiscal)
            if fila is None:
                return {"ok": False, "error": f"Factura '{folio_fiscal}' no encontrada en el grid."}
            return {"ok": True, "registro": {"folio_fiscal": folio_fiscal, "estado": "guardada"}}
        except Exception as e:
            return {"ok": False, "error": f"Error leyendo factura: {e}"}

    def close(self) -> Dict[str, Any]:
        # Nunca cerramos la aplicación CONTPAQi del usuario: sólo soltamos
        # nuestras referencias a la ventana.
        self._win = None
        self._app = None
        return {"ok": True}

    def health(self) -> Dict[str, Any]:
        return {
            "ok": self._win is not None,
            "backend": self.NOMBRE,
            "verificado_contra_real": CONTPAQI_VERIFICADO_CONTRA_REAL,
            "ventana_activa": self._win is not None,
        }


# ---------------------------------------------------------------------------
# Backend de simulación: cliente HTTP hacia ContpaqiSimulatorServer
# ---------------------------------------------------------------------------
class ContpaqiSimulatorBackend(ContpaqiDesktopBackend):
    """Cliente HTTP del simulador local de CONTPAQi (ver contpaqi_simulator_server.py).

    Usado cuando pywinauto no está disponible (no-Windows, como este entorno
    de desarrollo) o cuando se fuerza explícitamente para pruebas. SIEMPRE
    reporta verificado_contra_real=False: por definición no es CONTPAQi real.
    """

    NOMBRE = "simulador HTTP local (NO es CONTPAQi real)"
    ES_REAL = False

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 10.0):
        # Si no se da base_url, arrancamos un ContpaqiSimulatorServer propio
        # (perezoso: sólo al lanzar la "ventana", no al construir el backend).
        self._external_base_url = base_url
        self._owned_server = None
        self._base_url: Optional[str] = base_url
        self._timeout = timeout_seconds

    def is_available(self) -> bool:
        # El simulador es puro stdlib (http.server / urllib): siempre
        # disponible, en cualquier plataforma.
        return True

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Dict[str, Any]:
        import json
        import urllib.error
        import urllib.request

        if not self._base_url:
            return {"ok": False, "error": "Simulador no lanzado; llame launch_or_attach() primero."}

        url = self._base_url.rstrip("/") + path
        data = json.dumps(body or {}).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8"))
                payload.setdefault("ok", False)
                return payload
            except Exception:
                return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "error": f"Error de red hablando con el simulador: {e}"}

    def launch_or_attach(self) -> Dict[str, Any]:
        if not self._base_url:
            from b2b_ai.computer_use.contpaqi_simulator_server import ContpaqiSimulatorServer
            self._owned_server = ContpaqiSimulatorServer()
            self._base_url = self._owned_server.start()
            logger.warning(
                "ContpaqiSimulatorBackend: usando simulador propio en %s — "
                "NO verificado contra CONTPAQi real.", self._base_url,
            )
        return self._request("POST", "/ventana/lanzar")

    def login(self, usuario: str, password: str, empresa: str = "") -> Dict[str, Any]:
        return self._request(
            "POST", "/sesion/login",
            {"usuario": usuario, "password": password, "empresa": empresa},
        )

    def logout(self) -> Dict[str, Any]:
        return self._request("POST", "/sesion/logout")

    def navigate(self, menu_path: List[str]) -> Dict[str, Any]:
        return self._request("POST", "/menu/navegar", {"ruta": menu_path})

    def capture_poliza(self, poliza: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/polizas/capturar", poliza)

    def read_poliza(self, poliza_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/polizas/{poliza_id}")

    def capture_factura(self, factura: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/facturas/capturar", factura)

    def read_factura(self, folio_fiscal: str) -> Dict[str, Any]:
        return self._request("GET", f"/facturas/{folio_fiscal}")

    def close(self) -> Dict[str, Any]:
        if self._owned_server is not None:
            self._owned_server.stop()
            self._owned_server = None
            self._base_url = self._external_base_url
        return {"ok": True}

    def health(self) -> Dict[str, Any]:
        h = self._request("GET", "/salud") if self._base_url else {"ok": False}
        h["backend"] = self.NOMBRE
        h["verificado_contra_real"] = CONTPAQI_VERIFICADO_CONTRA_REAL
        h["simulador_base_url"] = self._base_url
        return h

    # -- helper de pruebas (no forma parte del contrato ContpaqiDesktopBackend) --
    def inyectar_falla(self, tipo: str, veces: int = 1) -> Dict[str, Any]:
        """Inyecta una falla de un solo uso en el simulador (para pruebas)."""
        return self._request("POST", "/debug/inyectar_falla", {"tipo": tipo, "veces": veces})


# ---------------------------------------------------------------------------
# Selección automática de backend
# ---------------------------------------------------------------------------
def select_contpaqi_backend(
    window_title: Optional[str] = None,
    process_name: Optional[str] = None,
    simulator_base_url: Optional[str] = None,
    force: Optional[str] = None,
) -> ContpaqiDesktopBackend:
    """Elige el backend de RPA para CONTPAQi.

    Args:
        window_title: regex de título de ventana (backend pywinauto).
        process_name: nombre del proceso a lanzar si no hay ventana (pywinauto).
        simulator_base_url: URL de un ContpaqiSimulatorServer ya corriendo;
            si no se da, ContpaqiSimulatorBackend lanza uno propio.
        force: 'pywinauto' | 'simulator' para forzar un backend explícito
            (usado por pruebas). Si None, se autodetecta: pywinauto real si
            está disponible (Windows + librería instalada), si no, simulador
            con una advertencia explícita.

    Returns:
        Una instancia de ContpaqiDesktopBackend. Nunca falla: si pywinauto no
        está disponible, cae al simulador (con warning), nunca pretende ser
        real cuando no lo es.
    """
    if force == "pywinauto":
        return PywinautoContpaqiBackend(window_title_re=window_title, process_name=process_name)
    if force == "simulator":
        return ContpaqiSimulatorBackend(base_url=simulator_base_url)

    candidato = PywinautoContpaqiBackend(window_title_re=window_title, process_name=process_name)
    if candidato.is_available():
        logger.info(
            "CONTPAQiRealDriver: backend=pywinauto (RPA de escritorio Windows real). "
            "verificado_contra_real=%s (ver disclaimer en contpaqi_rpa_backend.py).",
            CONTPAQI_VERIFICADO_CONTRA_REAL,
        )
        return candidato

    logger.warning(
        "CONTPAQiRealDriver: pywinauto no disponible (plataforma=%s). "
        "Usando ContpaqiSimulatorBackend — NO verificado contra una "
        "instalación real de CONTPAQi. Instale pywinauto y corra en "
        "Windows con CONTPAQi real para el backend real.",
        sys.platform,
    )
    return ContpaqiSimulatorBackend(base_url=simulator_base_url)
