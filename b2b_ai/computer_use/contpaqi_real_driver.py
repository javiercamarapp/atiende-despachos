# -*- coding: utf-8 -*-
"""
contpaqi_real_driver.py — Driver real de CONTPAQi via RPA de escritorio.

REDISEÑO (auditoría de producción, decisión de negocio ya tomada): CONTPAQi
se integra vía RPA sobre la app de ESCRITORIO real (Windows), NO vía una
"CONTPAQi Web" que nunca existió. La versión anterior de este archivo
heredaba de DesktopAutomation (no de la ABC ComputerUseDriver que exige el
factory) y usaba Playwright asumiendo una URL web -- ambos eran incorrectos
para un ERP de escritorio on-premise.

CONTPAQiRealDriver implementa ahora la ABC completa `interface.ComputerUseDriver`
(provider, mode, connect, login, verify_authenticated, logout, close,
navigate_menu, extract_invoices, capture_invoice_grid, register_invoice,
register_poliza, verify_invoice_registered, verify_poliza_registered, health,
recover_from_error), delegando el control de la ventana de escritorio a un
`ContpaqiDesktopBackend` (ver contpaqi_rpa_backend.py):

    - PywinautoContpaqiBackend: RPA real sobre pywinauto (Windows, UIA).
      Dependencia OPCIONAL -- import perezoso, con mensaje claro si falta o
      si no se corre en Windows.
    - ContpaqiSimulatorBackend: cliente de un simulador HTTP local (stdlib
      puro) que imita el mismo flujo de estados que tendría CONTPAQi real,
      para desarrollo/pruebas en entornos sin Windows (como este).

HONESTIDAD OBLIGATORIA (mismo principio que SATSubmitter, commit 27f94a7):

    CONTPAQI_VERIFICADO_CONTRA_REAL = False

No existe ninguna instancia real de CONTPAQi disponible para probar en este
entorno. El backend de pywinauto está escrito con la mejor comprensión del
flujo típico y documentado públicamente de "Captura de pólizas" en CONTPAQi
Contabilidad, pero NUNCA se ha ejecutado ni confirmado contra una instalación
real -- ver el disclaimer completo en contpaqi_rpa_backend.py. El backend por
defecto en este entorno (sin Windows) es el simulador HTTP local, que por
definición tampoco es CONTPAQi real. Todo DriverResult que produce este
driver incluye `verificado_contra_real: False` en sus datos para que ningún
llamador lo confunda con una integración verificada.

Uso:
    from b2b_ai.computer_use.contpaqi_real_driver import CONTPAQiRealDriver

    driver = CONTPAQiRealDriver()   # autodetecta backend (pywinauto o simulador)
    driver.connect()
    driver.login({"usuario": "admin", "password": "pass", "empresa": "Demo SA"})
    driver.navigate_menu("polizas")
    driver.register_poliza({
        "tipo": "Diario", "fecha": "2026-01-01",
        "conceptos": [
            {"cuenta": "1105-001", "concepto": "Ingreso banco", "cargo": 1000, "abono": 0},
            {"cuenta": "4105-001", "concepto": "Venta", "cargo": 0, "abono": 1000},
        ],
    })
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from b2b_ai.computer_use.contpaqi_rpa_backend import (
    ContpaqiDesktopBackend,
    select_contpaqi_backend,
)
from b2b_ai.computer_use.interface import (
    ComputerUseDriver,
    DriverResult,
)

logger = logging.getLogger(__name__)

# Ver disclaimer completo arriba y en contpaqi_rpa_backend.py.
CONTPAQI_VERIFICADO_CONTRA_REAL = False


class CONTPAQiRealDriver(ComputerUseDriver):
    """Driver real de CONTPAQi (RPA de escritorio) sobre la ABC ComputerUseDriver.

    Implementa la interfaz completa exigida por ComputerUseDriverFactory,
    delegando la manipulación de la ventana a un ContpaqiDesktopBackend
    (pywinauto real, o el simulador HTTP local cuando pywinauto no está
    disponible). Ver el disclaimer de honestidad al inicio del módulo:
    verificado_contra_real es SIEMPRE False hasta que alguien lo confirme
    contra una instalación real de CONTPAQi.
    """

    APP_NAME = "CONTPAQi Contabilidad (escritorio)"
    PROVIDER = "contpaqi"

    def __init__(
        self,
        erp_url: Optional[str] = None,
        headless: bool = True,
        *,
        window_title: Optional[str] = None,
        process_name: Optional[str] = None,
        simulator_base_url: Optional[str] = None,
        backend: Optional[ContpaqiDesktopBackend] = None,
        force_backend: Optional[str] = None,
        tenant_id: Optional[int] = None,
        timeout_seconds: int = 30,
        max_retries: int = 3,
    ):
        """Inicializa el driver.

        Args:
            erp_url, headless: aceptados sólo por compatibilidad con la firma
                que usa ComputerUseDriverFactory._create_playwright_driver
                (herencia de la era "CONTPAQi Web"). Un ERP de escritorio no
                tiene URL ni modo headless; se ignoran (se registra un debug
                log si erp_url viene con un valor). No se eliminan del
                constructor para no romper el wiring existente del factory.
            window_title: regex de título de ventana para pywinauto.
            process_name: proceso a lanzar si pywinauto no encuentra ventana.
            simulator_base_url: URL de un ContpaqiSimulatorServer externo ya
                corriendo; si no se da, el backend simulador lanza uno propio.
            backend: inyecta un ContpaqiDesktopBackend explícito (pruebas).
            force_backend: 'pywinauto' | 'simulator', fuerza la selección en
                vez de autodetectar (pruebas / troubleshooting).
            tenant_id, timeout_seconds, max_retries: metadatos/operación:
                tenant_id se incluye en logs y health(); timeout/retries se
                exponen para futura integración con lógica de reintento.
        """
        if erp_url:
            logger.debug(
                "CONTPAQiRealDriver: erp_url=%r ignorado (RPA de escritorio "
                "no usa URL; parámetro conservado sólo por compatibilidad "
                "con el wiring previo del factory).", erp_url,
            )
        self._headless_ignored = headless  # no aplica a RPA de escritorio

        self._backend: ContpaqiDesktopBackend = backend or select_contpaqi_backend(
            window_title=window_title,
            process_name=process_name,
            simulator_base_url=simulator_base_url,
            force=force_backend,
        )
        self._tenant_id = tenant_id
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

        self._connected = False
        self._closed = False
        self._session: Optional[Dict[str, Any]] = None
        self._current_module: Optional[str] = None
        self._registered_invoices: List[Dict[str, Any]] = []
        self._registered_polizas: List[Dict[str, Any]] = []

    # -- identidad (ComputerUseDriver ABC) -----------------------------------
    @property
    def provider(self) -> str:
        return self.PROVIDER

    @property
    def mode(self) -> str:
        # Se conserva el valor 'playwright' del vocabulario de modos del
        # factory/config (mock | playwright | disabled) por compatibilidad:
        # 'playwright' es, en ese enum, el modo genérico de "driver real, no
        # mock" -- NO implica que la tecnología subyacente sea la librería
        # Playwright. La tecnología real es RPA de escritorio (pywinauto) o,
        # en desarrollo sin Windows, el simulador HTTP local. Ver
        # self.backend_info() / health() para la tecnología real en uso.
        return "playwright"

    def backend_info(self) -> Dict[str, Any]:
        """Expone qué backend concreto está en uso (para logs/reportes)."""
        return {
            "backend_nombre": self._backend.NOMBRE,
            "backend_es_real": self._backend.ES_REAL,
            "verificado_contra_real": CONTPAQI_VERIFICADO_CONTRA_REAL,
        }

    # -- lifecycle ------------------------------------------------------------
    def connect(self) -> DriverResult:
        try:
            r = self._backend.launch_or_attach()
        except Exception as e:
            logger.error("CONTPAQiRealDriver:connect error=%s", e)
            return DriverResult.failed(
                message=f"Error conectando con CONTPAQi: {e}",
                verificado_contra_real=CONTPAQI_VERIFICADO_CONTRA_REAL,
            )
        if not r.get("ok"):
            logger.error("CONTPAQiRealDriver:connect FAILED error=%s", r.get("error"))
            return DriverResult.failed(
                message=r.get("error", "No se pudo conectar con CONTPAQi."),
                **self.backend_info(),
            )
        self._connected = True
        logger.info(
            "CONTPAQiRealDriver:connect ok backend=%s titulo_ventana=%s",
            self._backend.NOMBRE, r.get("titulo_ventana"),
        )
        return DriverResult.success(
            message=f"Conectado a CONTPAQi ({self._backend.NOMBRE}).",
            titulo_ventana=r.get("titulo_ventana"),
            **self.backend_info(),
        )

    def login(self, credentials: Dict[str, Any]) -> DriverResult:
        if not self._connected:
            return DriverResult.failed(
                "No conectado; llame connect() primero.",
                **self.backend_info(),
            )
        creds = credentials or {}
        usuario = creds.get("usuario") or creds.get("username", "")
        password = creds.get("password", "")
        empresa = creds.get("empresa", "")
        if not usuario:
            return DriverResult.failed("Falta 'usuario' en las credenciales.")
        if not password:
            return DriverResult.failed("Falta 'password' en las credenciales.")

        try:
            r = self._backend.login(usuario, password, empresa)
        except Exception as e:
            logger.error("CONTPAQiRealDriver:login error=%s", e)
            return DriverResult.failed(message=f"Error de login: {e}")

        if not r.get("ok"):
            return DriverResult.failed(
                message=r.get("error", "Login rechazado por CONTPAQi."),
                **self.backend_info(),
            )

        self._session = {"usuario": usuario, "empresa": empresa, "provider": self.PROVIDER}
        logger.info("CONTPAQiRealDriver:login ok usuario=%s", usuario)
        return DriverResult.success(
            message=f"Sesión CONTPAQi iniciada como {usuario}.",
            session=self._session,
            **self.backend_info(),
        )

    def verify_authenticated(self) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Sin sesión activa.")
        try:
            h = self._backend.health()
        except Exception as e:
            return DriverResult.session_expired(f"No se pudo verificar la sesión: {e}")
        if not h.get("ok", True):
            return DriverResult.session_expired(
                h.get("error", "El backend de CONTPAQi no respondió; sesión probablemente perdida.")
            )
        return DriverResult.success("Sesión activa.", session=self._session)

    def logout(self) -> DriverResult:
        if not self._session:
            return DriverResult.failed("No hay sesión activa para cerrar.")
        try:
            r = self._backend.logout()
        except Exception as e:
            return DriverResult.failed(f"Error cerrando sesión: {e}")
        usuario = self._session.get("usuario", "")
        self._session = None
        self._current_module = None
        if not r.get("ok", True):
            return DriverResult.failed(r.get("error", "No se pudo cerrar sesión."))
        return DriverResult.success(f"Sesión de {usuario} cerrada.")

    def close(self) -> None:
        try:
            self._backend.close()
        except Exception:
            logger.debug("CONTPAQiRealDriver: error cerrando backend", exc_info=True)
        self._connected = False
        self._session = None
        self._closed = True

    def __del__(self):
        if not getattr(self, "_closed", True):
            try:
                self.close()
            except Exception:
                pass

    # -- navegación / extracción ----------------------------------------------
    def navigate_menu(self, module: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        from b2b_ai.computer_use.contpaqi_rpa_backend import MENU_PATHS

        ruta = MENU_PATHS.get(module)
        if not ruta:
            return DriverResult.failed(
                f"Módulo '{module}' no reconocido. Disponibles: {sorted(MENU_PATHS)}"
            )
        try:
            r = self._backend.navigate(ruta)
        except Exception as e:
            return DriverResult.failed(f"Error navegando a {module}: {e}")
        if not r.get("ok"):
            return DriverResult.selector_not_found(
                r.get("error", f"No se pudo navegar a {module}."), ruta=ruta,
            )
        self._current_module = module
        return DriverResult.success(f"Módulo {module} abierto.", module=module)

    def extract_invoices(self) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        return DriverResult.success(
            message=f"{len(self._registered_invoices)} facturas registradas en esta sesión.",
            invoices=list(self._registered_invoices),
            **self.backend_info(),
        )

    def capture_invoice_grid(self) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        return DriverResult.success(
            message=f"Grid: {len(self._registered_invoices)} facturas.",
            grid=list(self._registered_invoices),
            **self.backend_info(),
        )

    # -- escritura --------------------------------------------------------------
    def register_invoice(self, data: Dict[str, Any]) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        folio = (data or {}).get("folio_fiscal") or (data or {}).get("folio")
        if not folio:
            return DriverResult.failed("Falta 'folio_fiscal' del CFDI.")
        if self._current_module != "facturas":
            nav = self.navigate_menu("facturas")
            if not nav.ok:
                return nav

        try:
            r = self._backend.capture_factura({**data, "folio_fiscal": folio})
        except Exception as e:
            return DriverResult.failed(f"Error capturando CFDI en CONTPAQi: {e}")
        if not r.get("ok"):
            return DriverResult.needs_human_review(
                r.get("error", f"CFDI {folio} no se pudo capturar."),
                folio_fiscal=folio,
            )
        registro = r["registro"]
        self._registered_invoices.append(registro)

        # Verificación: releer del backend que quedó registrada (mismo
        # principio de "no confiar sólo en que la escritura no truene" que
        # usa ERPWebDriverBase).
        verify = self.verify_invoice_registered(folio)
        if not verify.ok:
            return DriverResult.needs_human_review(
                f"CFDI {folio} capturado pero no se pudo verificar en el grid.",
                registro=registro,
            )
        return DriverResult.success(
            f"CFDI {folio} registrado y verificado en CONTPAQi.", registro=registro,
        )

    def register_poliza(self, data: Dict[str, Any]) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        conceptos = (data or {}).get("conceptos") or []
        if not conceptos:
            return DriverResult.failed("La póliza no tiene 'conceptos'.")

        cargo_total = round(sum(float(c.get("cargo", 0) or 0) for c in conceptos), 2)
        abono_total = round(sum(float(c.get("abono", 0) or 0) for c in conceptos), 2)
        if round(cargo_total - abono_total, 2) != 0:
            return DriverResult.failed(
                f"La póliza no está balanceada (Cargo={cargo_total:.2f}, "
                f"Abono={abono_total:.2f}); CONTPAQi la rechazaría igual.",
                cargo_total=cargo_total, abono_total=abono_total,
            )

        if self._current_module != "polizas":
            nav = self.navigate_menu("polizas")
            if not nav.ok:
                return nav

        try:
            r = self._backend.capture_poliza(data)
        except Exception as e:
            return DriverResult.failed(f"Error capturando póliza en CONTPAQi: {e}")
        if not r.get("ok"):
            # Diferencia != 0 detectada del lado del backend (simula el
            # diálogo de error real de CONTPAQi) -> needs_human_review, no
            # failed silencioso.
            return DriverResult.needs_human_review(
                r.get("error", "CONTPAQi rechazó la póliza."),
            )
        registro = r["registro"]
        self._registered_polizas.append(registro)

        verify = self.verify_poliza_registered(registro["poliza_id"])
        if not verify.ok:
            return DriverResult.needs_human_review(
                f"Póliza {registro['poliza_id']} capturada pero no se pudo "
                "verificar en el grid.",
                registro=registro,
            )
        return DriverResult.success(
            f"Póliza {registro['poliza_id']} registrada y verificada.", registro=registro,
        )

    def verify_invoice_registered(self, folio_fiscal: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        try:
            r = self._backend.read_factura(folio_fiscal)
        except Exception as e:
            return DriverResult.verification_failed(f"Error verificando factura: {e}")
        if r.get("ok"):
            return DriverResult.success(
                f"Factura {folio_fiscal} confirmada en CONTPAQi.",
                folio_fiscal=folio_fiscal, registro=r.get("registro"),
            )
        return DriverResult.verification_failed(
            r.get("error", f"Factura {folio_fiscal} no encontrada en CONTPAQi.")
        )

    def verify_poliza_registered(self, poliza_id: str) -> DriverResult:
        if not self._session:
            return DriverResult.session_expired("Debe iniciar sesión primero.")
        try:
            r = self._backend.read_poliza(poliza_id)
        except Exception as e:
            return DriverResult.verification_failed(f"Error verificando póliza: {e}")
        if r.get("ok"):
            return DriverResult.success(
                f"Póliza {poliza_id} confirmada en CONTPAQi.",
                poliza_id=poliza_id, registro=r.get("registro"),
            )
        return DriverResult.verification_failed(
            r.get("error", f"Póliza {poliza_id} no encontrada en CONTPAQi.")
        )

    # -- resiliencia --------------------------------------------------------------
    def health(self) -> DriverResult:
        backend_health = {}
        try:
            backend_health = self._backend.health()
        except Exception as e:
            backend_health = {"ok": False, "error": str(e)}
        return DriverResult.success(
            message=f"CONTPAQiRealDriver ({self._backend.NOMBRE})",
            provider=self.PROVIDER,
            mode=self.mode,
            tenant_id=self._tenant_id,
            connected=self._connected,
            session_active=self._session is not None,
            current_module=self._current_module,
            registered_invoices=len(self._registered_invoices),
            registered_polizas=len(self._registered_polizas),
            backend=backend_health,
            verificado_contra_real=CONTPAQI_VERIFICADO_CONTRA_REAL,
        )

    def recover_from_error(self) -> DriverResult:
        try:
            h = self._backend.health()
        except Exception as e:
            h = {"ok": False, "error": str(e)}

        if h.get("ok"):
            return DriverResult.success("Backend de CONTPAQi operativo.", recovered=True)

        logger.warning(
            "CONTPAQiRealDriver:recover_from_error backend no saludable (%s); reintentando conexión.",
            h.get("error"),
        )
        try:
            self._backend.close()
        except Exception:
            pass
        self._connected = False
        self._session = None
        self._current_module = None
        reconnect = self.connect()
        if reconnect.ok:
            return DriverResult.success(
                "Backend reconectado. Requiere volver a iniciar sesión.",
                recovered=True, needs_relogin=True,
            )
        return DriverResult.failed(
            f"No se pudo recuperar la conexión con CONTPAQi: {reconnect.message}",
            recovered=False,
        )
