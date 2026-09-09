# -*- coding: utf-8 -*-
"""sat_portal_rpa_driver.py — SATPortalRPADriver: RPA sobre el portal público del SAT.

============================================================================
LEE ESTO ANTES DE USAR O MODIFICAR ESTE MÓDULO
============================================================================

`VERIFICADO_CONTRA_SAT_REAL = False` (ver constante abajo). Este driver
NUNCA se ha ejecutado, ni una sola vez, contra el portal real del SAT
(sat.gob.mx ni ningún subdominio *.gob.mx). Toda su implementación y todas
sus pruebas corren EXCLUSIVAMENTE contra un simulador local que este mismo
cambio construyó (`tests/fixtures/sat_portal_simulator.py`), que imita — con
el mejor esfuerzo posible a partir de conocimiento público general sobre el
portal de Declaraciones y Pagos / DIOT del SAT, NO de una sesión real — la
estructura de pasos del flujo. Ningún selector, ruta o comportamiento de
este archivo debe asumirse como válido contra el sistema real.

Decisión de negocio (ya tomada por el dueño del proyecto, no discutida
aquí): el envío real de declaraciones/DIOT se hará vía RPA sobre el portal
PÚBLICO del SAT (no un PAC de pago), por ser gratuito. Este módulo es el
prototipo de ESA vía — opción 2 del análisis en
`docs/CONTRATO-SAT-INTEGRACION-REAL.md` §2(C) — construido y probado de
forma 100% aislada del sistema real, tal como exige esa tarea.

Control técnico de seguridad (no solo un aviso en texto): `__init__` y
`connect()` llaman a `_assert_host_is_not_real_sat()`, que **lanza
`SATPortalRealDomainBlocked` y se niega a continuar** si `portal_url`
resuelve a cualquier host bajo `*.gob.mx`. Esto existe para que un error de
configuración (una variable de entorno mal puesta, un valor por defecto
equivocado) no pueda hacer que este código dispare una llamada real contra
el SAT. Los tests con Playwright real de este módulo únicamente usan
`http://127.0.0.1:<puerto>` (el simulador).

Suposiciones NO verificadas sobre la estructura del portal real (cada una
está marcada también junto al selector correspondiente más abajo):
    - Que el login de e.firma pide 3 campos: certificado (.cer), llave
      privada (.key) y contraseña de la llave — esto SÍ es un hecho público
      conocido del esquema e.firma en general, pero los *nombres/IDs* de los
      campos HTML del portal real son una conjetura.
    - Que existe un menú "Portafolio de trámites" con acceso a
      "Declaraciones y Pagos" / DIOT — la EXISTENCIA de ese flujo está
      documentada públicamente (ver CONTRATO-SAT-INTEGRACION-REAL.md §2),
      pero la navegación exacta (clics, URLs) es una conjetura.
    - Que la subida de DIOT sigue un patrón de dos pasos (cargar archivo →
      confirmar envío) antes de emitir un acuse — es el patrón común en
      software fiscal, pero no está confirmado para este flujo específico
      del SAT.
    - Que el acuse de recepción trae un folio y una fecha visibles en la
      página de confirmación — razonable por analogía con otros acuses
      SAT (CFDI, buzón tributario), no confirmado para DIOT vía portal.

Antes de usar este driver contra el SAT real con un cliente real hace falta,
como mínimo (ninguno de estos tres pasos se ha hecho todavía):
    (a) Confirmar la estructura real del portal contra una sesión manual
        real (selectores, rutas, mensajes de error, formato del acuse).
    (b) Probar contra un ambiente de prueba/sandbox del SAT, si el SAT
        ofrece alguno para este flujo (no se encontró evidencia pública de
        que exista uno para Declaraciones y Pagos/DIOT).
    (c) Revisión legal de que automatizar el portal del SAT con Playwright
        no viola sus términos de uso, y de las implicaciones de operar esto
        con la e.firma de un contribuyente real (bloqueo de cuenta por
        actividad de bot, declaraciones mal presentadas, etc.)

Fail-closed (obligatorio, ver también docstrings de cada método): cada paso
del flujo solo avanza cuando reconoce explícitamente un marcador de éxito
esperado. Cualquier otra cosa — un selector que no aparece, una página que
no coincide con ningún patrón conocido, un CAPTCHA, un error HTTP — produce
un `PortalRPAResult` con status distinto de `CONFIRMED` y el flujo se
DETIENE ahí. Nunca se reintenta el envío completo asumiendo que "probable-
mente funcionó"; nunca se fabrica un folio localmente (a diferencia del
stub de `sat_submitter.py`, que si fabrica un folio SIM- porque es un stub
puro — este driver, si dice CONFIRMED, es porque el simulador/portal
realmente devolvió una página de acuse con folio).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from b2b_ai.computer_use.playwright_desktop import PlaywrightDesktop

logger = logging.getLogger("b2b_ai.declaraciones.sat_portal_rpa_driver")


# ============================================================================
# Bandera de honestidad — NO renombrar/eliminar sin actualizar este docstring
# y docs/CONTRATO-SAT-INTEGRACION-REAL.md.
# ============================================================================
VERIFICADO_CONTRA_SAT_REAL = False
# ^ SIEMPRE False hasta que este driver se haya ejecutado con éxito contra el
#   portal real del SAT (no el simulador) con los tres requisitos (a), (b),
#   (c) del docstring del módulo cumplidos y documentados. Cualquier código
#   que consuma este driver debe tratar `VERIFICADO_CONTRA_SAT_REAL is False`
#   como "no confiar en un resultado CONFIRMED para presentar de verdad ante
#   el SAT sin supervisión humana adicional".


# ============================================================================
# Guarda de dominio — bloqueo técnico, no solo documental
# ============================================================================
class SATPortalRealDomainBlocked(RuntimeError):
    """Se intentó apuntar SATPortalRPADriver a un dominio real *.gob.mx.

    Esto está bloqueado a propósito: este driver nunca se ha probado contra
    el SAT real (ver VERIFICADO_CONTRA_SAT_REAL) y no debe usarse contra él
    bajo ninguna circunstancia sin completar antes la revisión descrita en
    el docstring del módulo.
    """


_BLOCKED_HOST_RE = re.compile(r"(?:^|\.)gob\.mx$", re.IGNORECASE)
_ALLOWED_TEST_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _assert_host_is_not_real_sat(url: str) -> None:
    """Lanza SATPortalRealDomainBlocked si `url` apunta a *.gob.mx.

    Se llama en __init__ y de nuevo en connect() (defensa en profundidad
    por si `portal_url` se muta después de construir el driver).
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise SATPortalRealDomainBlocked(
            f"SATPortalRPADriver: URL sin host reconocible: {url!r}"
        )
    if host in _ALLOWED_TEST_HOSTS:
        return
    if _BLOCKED_HOST_RE.search(host):
        raise SATPortalRealDomainBlocked(
            f"SATPortalRPADriver rechaza conectarse a '{host}': cualquier "
            "dominio *.gob.mx (incluido sat.gob.mx) está bloqueado a "
            "propósito en este código. Este driver solo ha sido probado "
            "contra el simulador local "
            "(tests/fixtures/sat_portal_simulator.py). Ver "
            "VERIFICADO_CONTRA_SAT_REAL en este módulo y "
            "docs/CONTRATO-SAT-INTEGRACION-REAL.md antes de cambiar esto."
        )
    # Cualquier otro host (un staging propio del despacho, por ejemplo) se
    # permite pasar, pero sigue sin estar verificado contra el SAT real.


# ============================================================================
# Selectores — [0] es SIEMPRE el del simulador local (el único confirmado).
# El resto son conjeturas educadas sobre el portal real, NO VERIFICADAS.
# ============================================================================
RFC_INPUT_SELECTORS = ["#rfc-input", "input[name='rfc']"]
CER_FILE_SELECTORS = [
    "#cer-input",                              # simulador local (confirmado)
    "input[name='cer']",
    "input[name='certificado']",
    "input[type='file'][accept*='.cer']",       # conjetura
]
KEY_FILE_SELECTORS = [
    "#key-input",                              # simulador local (confirmado)
    "input[name='key']",
    "input[name='llave']",
    "input[type='file'][accept*='.key']",       # conjetura
]
PASSWORD_SELECTORS = [
    "#password-input",                         # simulador local (confirmado)
    "input[name='password']",
    "input[name='contrasenia']",
    "input[type='password']",                   # conjetura
]
LOGIN_SUBMIT_SELECTORS = [
    "#login-submit",                            # simulador local (confirmado)
    "button:has-text('Iniciar sesión')",        # conjetura
    "button:has-text('Enviar')",                # conjetura
    "input[type='submit']",
]
CAPTCHA_SELECTORS = ["#captcha-challenge", ".g-recaptcha", "[id*='captcha' i]"]
LOGIN_ERROR_SELECTORS = ["#login-error", ".error-message"]
PORTAFOLIO_MARKER_SELECTORS = ["#portafolio-title"]  # simulador; real: conjetura

DIOT_NAV_SELECTORS = ["#nav-diot", "a:has-text('DIOT')", "a:has-text('Declaraciones y Pagos')"]
DIOT_FILE_SELECTORS = ["#diot-file-input", "input[name='diot_file']", "input[type='file']"]
DIOT_PERIODO_SELECTORS = ["#periodo-select", "select[name='periodo']"]
DIOT_CARGAR_SUBMIT_SELECTORS = ["#diot-cargar-submit", "button:has-text('Cargar')"]
DIOT_CONFIRMAR_SELECTORS = ["#diot-confirmar", "button:has-text('Confirmar')"]

DIOT_PREVIEW_SELECTORS = ["#diot-preview"]
DIOT_ERROR_SELECTORS = ["#diot-error"]
DIOT_RECHAZO_SELECTORS = ["#diot-rechazo"]
ACUSE_FOLIO_SELECTORS = ["#acuse-folio"]
ACUSE_FECHA_SELECTORS = ["#acuse-fecha"]
ACUSE_SELLO_SELECTORS = ["#acuse-sello"]

_ERROR_TEXT_MARKERS = ("no disponible", "tiempo de espera agotado", "servicio no disponible")


class PortalStatus(str, Enum):
    """Estados posibles de una operación de SATPortalRPADriver."""
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    NAVIGATED = "navigated"
    STAGED = "staged"                          # archivo cargado y validado, pendiente de confirmar
    CONFIRMED = "confirmed"                     # único estado de éxito final (con folio real del portal)
    CONFIRMATION_REQUIRED = "confirmation_required"  # confirm=False: no se intentó nada
    INVALID_CREDENTIALS = "invalid_credentials"
    CAPTCHA_BLOCKED = "captcha_blocked"
    PORTAL_UNAVAILABLE = "portal_unavailable"
    UPLOAD_REJECTED = "upload_rejected"         # el portal rechazó el archivo DIOT
    LOCAL_VALIDATION_ERROR = "local_validation_error"  # error detectado ANTES de tocar el navegador
    UNEXPECTED_STATE = "unexpected_state"       # fail-closed: ningún marcador esperado coincidió
    ERROR = "error"                              # excepción no clasificada


_STEP_OK_STATUSES = frozenset({
    PortalStatus.CONNECTED, PortalStatus.AUTHENTICATED, PortalStatus.NAVIGATED,
    PortalStatus.STAGED, PortalStatus.CONFIRMED,
})


@dataclass
class PortalRPAResult:
    """Resultado uniforme de cada operación de SATPortalRPADriver."""
    status: PortalStatus
    mensaje: str = ""
    folio_acuse: Optional[str] = None
    fecha_recepcion: Optional[str] = None
    sello_acuse: Optional[str] = None
    screenshot_path: Optional[str] = None
    detalle: Dict[str, Any] = field(default_factory=dict)
    # SIEMPRE False hoy — ver VERIFICADO_CONTRA_SAT_REAL al inicio del módulo.
    verificado_contra_sat_real: bool = False

    @property
    def ok(self) -> bool:
        """True si este PASO avanzó como se esperaba (no implica éxito final)."""
        return self.status in _STEP_OK_STATUSES

    @property
    def is_final_success(self) -> bool:
        """True SOLO cuando el portal (simulador) confirmó el envío con folio.

        Este es el único caso que un llamador debe tratar como "declaración
        presentada". Todo lo demás — incluido cualquier otro miembro de
        _STEP_OK_STATUSES — es un paso intermedio, no una presentación.
        """
        return self.status == PortalStatus.CONFIRMED and bool(self.folio_acuse)


class SATPortalRPADriver:
    """RPA sobre el portal público del SAT vía Playwright (NO verificado contra el real).

    Ver el docstring del módulo completo antes de usar esta clase. Resumen:
    solo se ha probado contra `tests/fixtures/sat_portal_simulator.py`;
    `connect()`/`__init__` rechazan técnicamente cualquier `portal_url` bajo
    `*.gob.mx`; todo resultado trae `verificado_contra_sat_real=False`.

    Uso (contra el simulador de pruebas):
        driver = SATPortalRPADriver(
            portal_url="http://127.0.0.1:18766",
            cer_path="/ruta/al/certificado.cer",
            key_path="/ruta/a/la/llave.key",
            password="...",  # nunca se registra en logs
        )
        result = await driver.submit_diot(diot_file_path, periodo="2026-01", confirm=True)
        if result.is_final_success:
            print(result.folio_acuse)
        await driver.close()
    """

    backend = "SATPortalRPADriver (Playwright sobre simulador local del portal SAT)"

    def __init__(
        self,
        portal_url: str,
        cer_path: str,
        key_path: str,
        password: str,
        rfc: Optional[str] = None,
        *,
        headless: bool = True,
        desktop: Optional[PlaywrightDesktop] = None,
    ):
        _assert_host_is_not_real_sat(portal_url)

        if not cer_path or not os.path.isfile(cer_path):
            raise FileNotFoundError(
                f"Certificado e.firma (.cer) no encontrado: {cer_path!r}"
            )
        if not key_path or not os.path.isfile(key_path):
            raise FileNotFoundError(
                f"Llave privada e.firma (.key) no encontrada: {key_path!r}"
            )
        if not password:
            raise ValueError("password (contraseña de la llave privada) es obligatoria.")

        self.portal_url = portal_url
        self._cer_path = cer_path
        self._key_path = key_path
        self._password = password  # NUNCA registrar en logs ni incluir en excepciones.
        self._rfc = rfc or ""
        self.desktop = desktop or PlaywrightDesktop(headless=headless)
        self._authenticated = False
        self._staged = False
        self._loop = asyncio.new_event_loop()

    def __repr__(self) -> str:
        """Repr sin la contraseña (nunca exponerla, ni por accidente en logs/debug)."""
        return (
            f"SATPortalRPADriver(portal_url={self.portal_url!r}, "
            f"cer_path={self._cer_path!r}, key_path={self._key_path!r}, "
            f"password='<redacted>', authenticated={self._authenticated}, "
            f"verificado_contra_sat_real={VERIFICADO_CONTRA_SAT_REAL})"
        )

    # -- gestión de recursos --------------------------------------------------
    def _run_sync(self, coro):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None and running.is_running():
            fresh = asyncio.new_event_loop()
            try:
                return fresh.run_until_complete(coro)
            finally:
                fresh.close()
        return self._loop.run_until_complete(coro)

    async def close(self) -> None:
        await self.desktop.close()
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
            self._loop = None

    def close_sync(self) -> None:
        self._run_sync(self.desktop.close())

    def __del__(self):
        # Defensivo: si __init__ lanzó antes de terminar (URL bloqueada,
        # archivo faltante, etc.) los atributos de abajo pueden no existir.
        loop = getattr(self, "_loop", None)
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.get_running_loop()
            # Hay un event loop activo en este hilo (p.ej. un test async en
            # curso): NO es seguro llamar run_until_complete sobre otro loop
            # desde __del__ (asyncio lo rechaza y deja una coroutine sin
            # await). Solo advertir; el cierre real debe hacerse con
            # `await driver.close()` explícito.
            logger.warning(
                "SATPortalRPADriver: recursos no cerrados explícitamente. "
                "Llame a 'await driver.close()' en vez de depender del GC."
            )
            return
        except RuntimeError:
            pass  # no hay loop corriendo en este hilo: sí es seguro cerrar aquí.
        desktop = getattr(self, "desktop", None)
        if desktop is None:
            loop.close()
            return
        try:
            loop.run_until_complete(desktop.close())
        except Exception:
            logger.debug("SATPortalRPADriver: error cerrando en __del__", exc_info=True)
        finally:
            loop.close()

    # -- helpers internos -------------------------------------------------------
    async def _fill_any(self, selectors: List[str], value: str) -> bool:
        for sel in selectors:
            res = await self.desktop.fill(sel, value)
            if res.get("ok"):
                return True
        return False

    async def _upload_any(self, selectors: List[str], file_path: str) -> bool:
        for sel in selectors:
            res = await self.desktop.upload_file(sel, file_path)
            if res.get("ok"):
                return True
        return False

    async def _click_any(self, selectors: List[str]) -> bool:
        for sel in selectors:
            res = await self.desktop.click_selector(sel)
            if res.get("ok"):
                return True
        return False

    async def _select_any(self, selectors: List[str], value: str) -> bool:
        for sel in selectors:
            res = await self.desktop.select_dropdown(sel, value)
            if res.get("ok"):
                return True
        return False

    async def _present(self, selectors: List[str]) -> bool:
        for sel in selectors:
            res = await self.desktop.find_elements(sel)
            if res.get("ok") and res.get("count", 0) > 0:
                return True
        return False

    async def _page_text(self) -> str:
        content = await self.desktop.get_content()
        return (content.get("text") or "") if content.get("ok") else ""

    async def _screenshot(self) -> Optional[str]:
        shot = await self.desktop.screenshot()
        return shot.get("path") if shot.get("ok") else None

    # -- pasos del flujo ---------------------------------------------------------
    async def connect(self) -> PortalRPAResult:
        """Lanza el navegador y navega a la página de login del portal."""
        _assert_host_is_not_real_sat(self.portal_url)  # defensa en profundidad
        result = await self.desktop.launch(self.portal_url)
        if not result.get("ok"):
            logger.error("SATPortalRPADriver: connect FAILED url=%s error=%s",
                         self.portal_url, result.get("error"))
            return PortalRPAResult(
                status=PortalStatus.ERROR,
                mensaje=f"No se pudo abrir el navegador en {self.portal_url}: {result.get('error')}",
            )
        logger.info("SATPortalRPADriver: conectado a %s", self.portal_url)
        return PortalRPAResult(status=PortalStatus.CONNECTED,
                                mensaje=f"Navegador conectado a {self.portal_url}.")

    async def authenticate(self) -> PortalRPAResult:
        """Autentica con e.firma (.cer/.key + contraseña). Fail-closed.

        NUNCA registra la contraseña. Solo avanza a AUTHENTICATED si aparece
        un marcador explícito de éxito (dashboard); si no reconoce ningún
        marcador conocido (éxito, error de credenciales, CAPTCHA), regresa
        UNEXPECTED_STATE en vez de asumir que funcionó.
        """
        logger.info(
            "SATPortalRPADriver: intentando autenticación e.firma en %s "
            "(cer=%s, key=%s, password=<oculta, %d chars>)",
            self.portal_url, self._cer_path, self._key_path, len(self._password),
        )
        try:
            if self._rfc:
                await self._fill_any(RFC_INPUT_SELECTORS, self._rfc)

            if not await self._upload_any(CER_FILE_SELECTORS, self._cer_path):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el campo de certificado (.cer) en la página de login.",
                    screenshot_path=await self._screenshot(),
                )
            if not await self._upload_any(KEY_FILE_SELECTORS, self._key_path):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el campo de llave privada (.key) en la página de login.",
                    screenshot_path=await self._screenshot(),
                )
            if not await self._fill_any(PASSWORD_SELECTORS, self._password):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el campo de contraseña en la página de login.",
                    screenshot_path=await self._screenshot(),
                )
            if not await self._click_any(LOGIN_SUBMIT_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el botón de envío del login.",
                    screenshot_path=await self._screenshot(),
                )

            await asyncio.sleep(0.3)  # dar tiempo a que cargue la respuesta

            if await self._present(CAPTCHA_SELECTORS):
                logger.warning("SATPortalRPADriver: CAPTCHA detectado en login; deteniendo (fail-closed).")
                return PortalRPAResult(
                    status=PortalStatus.CAPTCHA_BLOCKED,
                    mensaje="El portal presentó un CAPTCHA. Requiere intervención humana.",
                    screenshot_path=await self._screenshot(),
                )
            if await self._present(LOGIN_ERROR_SELECTORS):
                logger.warning("SATPortalRPADriver: credenciales rechazadas por el portal.")
                return PortalRPAResult(
                    status=PortalStatus.INVALID_CREDENTIALS,
                    mensaje="El portal rechazó las credenciales de e.firma.",
                    screenshot_path=await self._screenshot(),
                )
            text = (await self._page_text()).lower()
            if any(marker in text for marker in _ERROR_TEXT_MARKERS):
                return PortalRPAResult(
                    status=PortalStatus.PORTAL_UNAVAILABLE,
                    mensaje="El portal respondió con un error de servicio (no disponible / timeout).",
                    screenshot_path=await self._screenshot(),
                )
            if await self._present(PORTAFOLIO_MARKER_SELECTORS):
                self._authenticated = True
                logger.info("SATPortalRPADriver: autenticado correctamente.")
                return PortalRPAResult(status=PortalStatus.AUTHENTICATED,
                                        mensaje="Autenticación e.firma exitosa.")

            # Fail-closed: no reconocimos ningún marcador esperado.
            logger.error(
                "SATPortalRPADriver: estado inesperado tras login; no se "
                "reconoce éxito, error ni CAPTCHA. Deteniendo (fail-closed)."
            )
            return PortalRPAResult(
                status=PortalStatus.UNEXPECTED_STATE,
                mensaje=(
                    "Tras enviar el login, la página no coincide con ningún "
                    "estado conocido (ni éxito, ni error, ni CAPTCHA). No se "
                    "asume éxito. Revisar manualmente."
                ),
                screenshot_path=await self._screenshot(),
                detalle={"page_text_preview": text[:500]},
            )
        except Exception as e:
            logger.error("SATPortalRPADriver: authenticate EXCEPTION: %s", e)
            return PortalRPAResult(status=PortalStatus.ERROR, mensaje=f"Error de autenticación: {e}")

    async def navigate_to_diot(self) -> PortalRPAResult:
        """Navega desde el portafolio al módulo de DIOT."""
        if not self._authenticated:
            return PortalRPAResult(status=PortalStatus.UNEXPECTED_STATE,
                                    mensaje="Debe autenticarse antes de navegar.")
        try:
            if not await self._click_any(DIOT_NAV_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el acceso a DIOT en el portafolio.",
                    screenshot_path=await self._screenshot(),
                )
            await asyncio.sleep(0.2)
            if not await self._present(DIOT_FILE_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="Se navegó pero no se encontró el formulario de carga de DIOT.",
                    screenshot_path=await self._screenshot(),
                )
            return PortalRPAResult(status=PortalStatus.NAVIGATED,
                                    mensaje="Módulo DIOT abierto.")
        except Exception as e:
            logger.error("SATPortalRPADriver: navigate_to_diot EXCEPTION: %s", e)
            return PortalRPAResult(status=PortalStatus.ERROR, mensaje=f"Error de navegación: {e}")

    async def upload_diot_file(self, diot_file_path: str, periodo: str) -> PortalRPAResult:
        """Sube el archivo DIOT (ya generado por DIOTGenerator) y espera la vista previa.

        Fail-closed: si el portal responde con rechazo o error, se reporta
        tal cual; si no aparece ni la vista previa ni un marcador de error
        conocido, se reporta UNEXPECTED_STATE (nunca se asume éxito).
        """
        if not diot_file_path or not os.path.isfile(diot_file_path):
            return PortalRPAResult(
                status=PortalStatus.LOCAL_VALIDATION_ERROR,
                mensaje=f"Archivo DIOT no encontrado: {diot_file_path!r}",
            )
        if os.path.getsize(diot_file_path) == 0:
            return PortalRPAResult(
                status=PortalStatus.LOCAL_VALIDATION_ERROR,
                mensaje="El archivo DIOT está vacío; no se sube al portal.",
            )
        try:
            await self._select_any(DIOT_PERIODO_SELECTORS, periodo)  # best-effort, no bloqueante
            if not await self._upload_any(DIOT_FILE_SELECTORS, diot_file_path):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el campo de carga de archivo DIOT.",
                    screenshot_path=await self._screenshot(),
                )
            if not await self._click_any(DIOT_CARGAR_SUBMIT_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el botón para cargar el archivo DIOT.",
                    screenshot_path=await self._screenshot(),
                )
            await asyncio.sleep(0.3)

            text = (await self._page_text()).lower()
            if await self._present(DIOT_RECHAZO_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UPLOAD_REJECTED,
                    mensaje="El portal rechazó el archivo DIOT cargado.",
                    screenshot_path=await self._screenshot(),
                )
            if any(marker in text for marker in _ERROR_TEXT_MARKERS):
                return PortalRPAResult(
                    status=PortalStatus.PORTAL_UNAVAILABLE,
                    mensaje="El portal respondió con un error de servicio al cargar el DIOT.",
                    screenshot_path=await self._screenshot(),
                )
            if await self._present(DIOT_ERROR_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UPLOAD_REJECTED,
                    mensaje="El portal reportó un error de validación en el archivo DIOT.",
                    screenshot_path=await self._screenshot(),
                )
            if await self._present(DIOT_PREVIEW_SELECTORS):
                self._staged = True
                return PortalRPAResult(status=PortalStatus.STAGED,
                                        mensaje="Archivo DIOT cargado y validado; pendiente de confirmar.")

            logger.error(
                "SATPortalRPADriver: estado inesperado tras cargar DIOT; "
                "no hay vista previa ni error reconocido. Deteniendo."
            )
            return PortalRPAResult(
                status=PortalStatus.UNEXPECTED_STATE,
                mensaje="Tras cargar el DIOT, la página no coincide con ningún estado conocido.",
                screenshot_path=await self._screenshot(),
                detalle={"page_text_preview": text[:500]},
            )
        except Exception as e:
            logger.error("SATPortalRPADriver: upload_diot_file EXCEPTION: %s", e)
            return PortalRPAResult(status=PortalStatus.ERROR, mensaje=f"Error subiendo DIOT: {e}")

    async def confirm_submission(self) -> PortalRPAResult:
        """Confirma el envío previamente cargado y captura el acuse (folio/fecha/sello).

        Único método que puede devolver status CONFIRMED. Solo lo hace si
        encuentra explícitamente el folio del acuse en la página; de lo
        contrario, fail-closed a UNEXPECTED_STATE.
        """
        if not self._staged:
            return PortalRPAResult(
                status=PortalStatus.UNEXPECTED_STATE,
                mensaje="No hay ningún archivo DIOT cargado pendiente de confirmar.",
            )
        try:
            if not await self._click_any(DIOT_CONFIRMAR_SELECTORS):
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="No se encontró el botón de confirmación de envío.",
                    screenshot_path=await self._screenshot(),
                )
            await asyncio.sleep(0.3)

            if not await self._present(ACUSE_FOLIO_SELECTORS):
                text = (await self._page_text()).lower()
                if any(marker in text for marker in _ERROR_TEXT_MARKERS):
                    return PortalRPAResult(
                        status=PortalStatus.PORTAL_UNAVAILABLE,
                        mensaje="El portal respondió con un error de servicio al confirmar.",
                        screenshot_path=await self._screenshot(),
                    )
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje=(
                        "Se confirmó el envío pero no se encontró un folio de "
                        "acuse en la respuesta. NO se reporta éxito sin folio "
                        "verificable."
                    ),
                    screenshot_path=await self._screenshot(),
                    detalle={"page_text_preview": text[:500]},
                )

            folio_texts = await self.desktop.find_elements(ACUSE_FOLIO_SELECTORS[0])
            fecha_texts = await self.desktop.find_elements(ACUSE_FECHA_SELECTORS[0])
            sello_texts = await self.desktop.find_elements(ACUSE_SELLO_SELECTORS[0])
            folio = (folio_texts.get("texts") or [None])[0]
            fecha = (fecha_texts.get("texts") or [None])[0]
            sello = (sello_texts.get("texts") or [None])[0]

            if not folio:
                return PortalRPAResult(
                    status=PortalStatus.UNEXPECTED_STATE,
                    mensaje="El elemento de folio de acuse apareció vacío. No se reporta éxito.",
                    screenshot_path=await self._screenshot(),
                )

            self._staged = False
            logger.info("SATPortalRPADriver: envío confirmado, folio=%s", folio)
            return PortalRPAResult(
                status=PortalStatus.CONFIRMED,
                mensaje="Declaración DIOT confirmada por el portal (simulador). "
                        "VERIFICADO_CONTRA_SAT_REAL=False: esto NO es una "
                        "confirmación del SAT real.",
                folio_acuse=folio,
                fecha_recepcion=fecha,
                sello_acuse=sello,
                screenshot_path=await self._screenshot(),
            )
        except Exception as e:
            logger.error("SATPortalRPADriver: confirm_submission EXCEPTION: %s", e)
            return PortalRPAResult(status=PortalStatus.ERROR, mensaje=f"Error confirmando envío: {e}")

    # -- orquestación de punta a punta -----------------------------------------
    async def submit_diot(
        self,
        diot_file_path: str,
        periodo: str,
        confirm: bool = False,
    ) -> PortalRPAResult:
        """Flujo completo: conectar → autenticar → navegar → subir → confirmar.

        Fail-closed en cada paso: si un paso no avanza (`result.ok is
        False`), el flujo se DETIENE inmediatamente y se devuelve ese
        resultado — nunca se continúa "a ver si el siguiente paso sí
        funciona" ni se reintenta el envío completo.

        `confirm=True` es obligatorio (igual que en `SATSubmitter`): sin
        ella, no se toca el navegador en absoluto.
        """
        if not confirm:
            return PortalRPAResult(
                status=PortalStatus.CONFIRMATION_REQUIRED,
                mensaje=(
                    "Confirmación explícita requerida (confirm=True). No se "
                    "realizó ninguna acción contra el portal."
                ),
            )

        if not diot_file_path or not os.path.isfile(diot_file_path):
            return PortalRPAResult(
                status=PortalStatus.LOCAL_VALIDATION_ERROR,
                mensaje=f"Archivo DIOT no encontrado: {diot_file_path!r}",
            )
        if os.path.getsize(diot_file_path) == 0:
            return PortalRPAResult(
                status=PortalStatus.LOCAL_VALIDATION_ERROR,
                mensaje="El archivo DIOT está vacío; no se intenta el envío.",
            )

        step = await self.connect()
        if not step.ok:
            return step

        step = await self.authenticate()
        if not step.ok:
            return step

        step = await self.navigate_to_diot()
        if not step.ok:
            return step

        step = await self.upload_diot_file(diot_file_path, periodo)
        if not step.ok:
            return step

        return await self.confirm_submission()

    # -- salud -------------------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        browser_health = self.desktop.health()
        return {
            "ok": browser_health.get("ok", False),
            "backend": self.backend,
            "portal_url": self.portal_url,
            "authenticated": self._authenticated,
            "staged": self._staged,
            "verificado_contra_sat_real": VERIFICADO_CONTRA_SAT_REAL,
            "browser": browser_health,
        }
