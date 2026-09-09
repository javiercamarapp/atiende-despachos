# -*- coding: utf-8 -*-
"""
contpaqi_simulator_server.py — Simulador HTTP local del CONTPAQi de escritorio.

HONESTIDAD OBLIGATORIA (mismo principio que SATSubmitter, commit 27f94a7):
Este módulo NO habla con CONTPAQi. Es un servidor HTTP local (stdlib puro,
sin dependencias nuevas) que imita, con una máquina de estados, los mismos
pasos/estados/respuestas que tendría un flujo real de "Captura de pólizas"
en CONTPAQi Contabilidad de escritorio: lanzar/encontrar la ventana, iniciar
sesión, navegar el menú, capturar una póliza (con validación de balance
Cargo == Abono, igual que hace el CONTPAQi real), capturar una factura,
verificar lo registrado, y cerrar sesión.

Se usa como respaldo en entornos de desarrollo donde no hay Windows/CONTPAQi
disponibles (como esta máquina). NUNCA debe confundirse con una integración
verificada contra una instalación real:

    CONTPAQI_VERIFICADO_CONTRA_REAL = False

La estructura de menús y campos que este simulador reproduce (Movimientos >
Pólizas > Captura de pólizas; grid Cuenta/Concepto/Cargo/Abono; validación de
diferencia == 0.00 antes de guardar) está tomada de documentación pública y
tutoriales de CONTPAQi Contabilidad para ese flujo típico — NUNCA ha sido
confirmada contra una instalación real. Ver contpaqi_rpa_backend.py para el
mismo disclaimer aplicado al backend de pywinauto (para cuando sí exista una
VM/servidor Windows con CONTPAQi real para probar).

Uso:
    server = ContpaqiSimulatorServer()
    base_url = server.start()   # p.ej. "http://127.0.0.1:53291"
    ...
    server.stop()
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

CONTPAQI_VERIFICADO_CONTRA_REAL = False

# ---------------------------------------------------------------------------
# Estructura de menús típica de CONTPAQi Contabilidad (documentación pública,
# NUNCA confirmada contra una instalación real) para "Captura de pólizas".
# ---------------------------------------------------------------------------
CONTPAQI_MENU_ESTRUCTURA_TIPICA: Dict[tuple, str] = {
    ("Movimientos", "Pólizas"): "polizas",
    ("Movimientos", "Pólizas", "Captura de pólizas"): "polizas",
    ("Movimientos", "Facturación"): "facturas",
    ("Catálogos", "Cuentas"): "catalogos",
    ("Consultas", "Balanza de comprobación"): "reportes",
}

VENTANA_TITULO_DEMO = "CONTPAQi Contabilidad - Empresa DEMO (SIMULADO, no verificado)"


class _EstadoContpaqi:
    """Estado en memoria de la 'ventana' simulada. Un simulador == un cliente."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.ventana_lanzada = False
        self.sesion: Optional[Dict[str, Any]] = None
        self.modulo_actual: Optional[str] = None
        self.polizas: Dict[str, Dict[str, Any]] = {}
        self.facturas: Dict[str, Dict[str, Any]] = {}
        self._contador_poliza = 0
        # Fallas inyectadas de un solo uso, por operación (mismo patrón que
        # MockDesktop.fail_next en contpaqi_driver.py).
        self.fallas: Dict[str, int] = {}

    def inyectar_falla(self, tipo: str, veces: int = 1) -> None:
        with self.lock:
            self.fallas[tipo] = self.fallas.get(tipo, 0) + int(veces)

    def consumir_falla(self, tipo: str) -> bool:
        with self.lock:
            n = self.fallas.get(tipo, 0)
            if n > 0:
                self.fallas[tipo] = n - 1
                return True
            return False

    def siguiente_numero_poliza(self) -> str:
        with self.lock:
            self._contador_poliza += 1
            return f"P-{self._contador_poliza:05d}"


class _Handler(BaseHTTPRequestHandler):
    server_version = "ContpaqiSimulator/1.0 (NO-VERIFICADO)"

    def log_message(self, fmt, *args):  # silencia logging default a stderr
        logger.debug("contpaqi_simulator: " + fmt, *args)

    # -- helpers --------------------------------------------------------
    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        payload.setdefault("verificado_contra_real", CONTPAQI_VERIFICADO_CONTRA_REAL)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @property
    def estado(self) -> _EstadoContpaqi:
        return self.server.estado  # type: ignore[attr-defined]

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        st = self.estado
        if path == "/salud":
            self._send_json(200, {
                "ok": True,
                "ventana_lanzada": st.ventana_lanzada,
                "sesion_activa": st.sesion is not None,
                "modulo_actual": st.modulo_actual,
            })
            return
        if path.startswith("/polizas/"):
            poliza_id = path.rsplit("/", 1)[-1]
            registro = st.polizas.get(poliza_id)
            if registro:
                self._send_json(200, {"ok": True, "registro": registro})
            else:
                self._send_json(404, {"ok": False, "error": f"Póliza '{poliza_id}' no encontrada."})
            return
        if path.startswith("/facturas/"):
            folio = path.rsplit("/", 1)[-1]
            registro = st.facturas.get(folio)
            if registro:
                self._send_json(200, {"ok": True, "registro": registro})
            else:
                self._send_json(404, {"ok": False, "error": f"Factura '{folio}' no encontrada."})
            return
        self._send_json(404, {"ok": False, "error": f"Ruta desconocida: {path}"})

    def do_POST(self):
        path = urlparse(self.path).path
        st = self.estado
        body = self._read_json()

        if path == "/ventana/lanzar":
            if st.consumir_falla("ventana_no_encontrada"):
                self._send_json(504, {
                    "ok": False,
                    "error": "Ventana no encontrada: no se localizó ningún proceso "
                             "'Contabilidad.exe' con la ventana de CONTPAQi (falla "
                             "inyectada para prueba).",
                })
                return
            if st.consumir_falla("timeout"):
                self._send_json(504, {
                    "ok": False,
                    "error": "Timeout esperando a que la ventana de CONTPAQi respondiera "
                             "(falla inyectada para prueba).",
                })
                return
            st.ventana_lanzada = True
            self._send_json(200, {"ok": True, "titulo_ventana": VENTANA_TITULO_DEMO})
            return

        if path == "/sesion/login":
            if not st.ventana_lanzada:
                self._send_json(409, {"ok": False, "error": "Ventana no lanzada; llame /ventana/lanzar primero."})
                return
            usuario = (body.get("usuario") or "").strip()
            password = body.get("password") or ""
            if not usuario or not password:
                self._send_json(400, {"ok": False, "error": "Faltan 'usuario'/'password'."})
                return
            if usuario == "usuario_invalido" or password == "clave_incorrecta":
                self._send_json(401, {
                    "ok": False,
                    "error": "CONTPAQi rechazó las credenciales (diálogo: "
                             "'Usuario o contraseña incorrectos').",
                })
                return
            st.sesion = {"usuario": usuario, "empresa": body.get("empresa", "")}
            self._send_json(200, {"ok": True, "sesion": st.sesion})
            return

        if path == "/sesion/logout":
            st.sesion = None
            st.modulo_actual = None
            self._send_json(200, {"ok": True})
            return

        if path == "/menu/navegar":
            if not st.sesion:
                self._send_json(409, {"ok": False, "error": "Sin sesión activa."})
                return
            ruta = tuple(body.get("ruta") or [])
            modulo = CONTPAQI_MENU_ESTRUCTURA_TIPICA.get(ruta)
            if not modulo:
                self._send_json(404, {
                    "ok": False,
                    "error": f"Ruta de menú {list(ruta)} no reconocida en la "
                             "estructura típica de CONTPAQi Contabilidad.",
                })
                return
            st.modulo_actual = modulo
            self._send_json(200, {"ok": True, "modulo": modulo})
            return

        if path == "/polizas/capturar":
            if not st.sesion:
                self._send_json(409, {"ok": False, "error": "Sin sesión activa."})
                return
            if st.modulo_actual != "polizas":
                self._send_json(409, {"ok": False, "error": "No está en el módulo de pólizas."})
                return
            if st.consumir_falla("dialogo_error"):
                self._send_json(422, {
                    "ok": False,
                    "error": "CONTPAQi mostró un diálogo de error inesperado al "
                             "guardar la póliza (falla inyectada para prueba).",
                })
                return
            conceptos: List[Dict[str, Any]] = body.get("conceptos") or []
            if not conceptos:
                self._send_json(400, {"ok": False, "error": "La póliza no tiene conceptos."})
                return
            cargo = round(sum(float(c.get("cargo", 0) or 0) for c in conceptos), 2)
            abono = round(sum(float(c.get("abono", 0) or 0) for c in conceptos), 2)
            diferencia = round(cargo - abono, 2)
            if diferencia != 0:
                self._send_json(422, {
                    "ok": False,
                    "error": f"La póliza no está balanceada. Diferencia: {diferencia:.2f} "
                             f"(Cargo={cargo:.2f}, Abono={abono:.2f}).",
                    "diferencia": diferencia,
                })
                return
            poliza_id = st.siguiente_numero_poliza()
            registro = {
                "poliza_id": poliza_id,
                "tipo": body.get("tipo"),
                "fecha": body.get("fecha"),
                "conceptos": conceptos,
                "cargo_total": cargo,
                "abono_total": abono,
                "estado": "guardada",
            }
            st.polizas[poliza_id] = registro
            self._send_json(200, {"ok": True, "registro": registro})
            return

        if path == "/facturas/capturar":
            if not st.sesion:
                self._send_json(409, {"ok": False, "error": "Sin sesión activa."})
                return
            if st.modulo_actual != "facturas":
                self._send_json(409, {"ok": False, "error": "No está en el módulo de facturación."})
                return
            folio = body.get("folio_fiscal")
            if not folio:
                self._send_json(400, {"ok": False, "error": "Falta 'folio_fiscal'."})
                return
            registro = {
                "folio_fiscal": folio,
                "total": body.get("total"),
                "emisor_rfc": body.get("emisor_rfc"),
                "concepto": body.get("concepto"),
                "estado": "guardada",
            }
            st.facturas[folio] = registro
            self._send_json(200, {"ok": True, "registro": registro})
            return

        if path == "/debug/inyectar_falla":
            tipo = body.get("tipo", "")
            veces = int(body.get("veces", 1))
            st.inyectar_falla(tipo, veces)
            self._send_json(200, {"ok": True, "tipo": tipo, "veces": veces})
            return

        self._send_json(404, {"ok": False, "error": f"Ruta desconocida: {path}"})


class ContpaqiSimulatorServer:
    """Servidor HTTP local (stdlib) que hospeda el simulador de CONTPAQi.

    Corre en un hilo daemon sobre 127.0.0.1 y un puerto efímero (o el que se
    indique). Pensado para pruebas de contrato y para el modo de desarrollo
    de ContpaqiSimulatorBackend cuando no hay Windows/CONTPAQi disponibles.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.estado = _EstadoContpaqi()

    def start(self) -> str:
        if self._httpd is not None:
            return self.base_url
        self._httpd = ThreadingHTTPServer((self._host, self._port), _Handler)
        self._httpd.estado = self.estado  # type: ignore[attr-defined]
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="contpaqi-simulator", daemon=True
        )
        self._thread.start()
        logger.warning(
            "ContpaqiSimulatorServer iniciado en %s — SIMULADO, "
            "verificado_contra_real=False.", self.base_url,
        )
        return self.base_url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def __enter__(self) -> "ContpaqiSimulatorServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
