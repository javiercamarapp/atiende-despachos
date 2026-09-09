# -*- coding: utf-8 -*-
"""sat_portal_simulator.py — Simulador local del portal público del SAT.

**ESTO NO ES EL PORTAL DEL SAT.** Es un servidor HTTP local (stdlib puro, sin
dependencias externas) que imita, con el mejor esfuerzo posible a partir de
conocimiento público general, la ESTRUCTURA de pasos que tendría el flujo de
autenticación con e.firma + presentación de DIOT en el portal real del SAT
("Presenta tu declaración" / Servicio de Declaraciones y Pagos, dentro del
portafolio de trámites del contribuyente).

NO se construyó a partir de una sesión real contra sat.gob.mx (regla no
negociable de esta tarea: nunca conectar contra el dominio real del SAT).
Toda la estructura de páginas, campos, IDs de elementos y nombres de rutas de
este archivo es una CONJETURA EDUCADA para poder probar
`SATPortalRPADriver` de punta a punta sin tocar el sistema real. Ningún
selector aquí debe copiarse a un driver real sin antes confirmarlo contra el
portal real. Ver docs/CONTRATO-SAT-INTEGRACION-REAL.md.

Flujo simulado:
    1. GET  /                  → login (e.firma: certificado .cer, llave
                                  .key, contraseña de la llave; + RFC como
                                  campo auxiliar SOLO para poder disparar
                                  escenarios de prueba, ver abajo).
    2. POST /login             → valida credenciales, puede responder:
                                    - 302 a /portafolio (éxito)
                                    - 200 con #login-error (credenciales
                                      inválidas)
                                    - 200 con #captcha-challenge (CAPTCHA)
                                    - 503 (portal caído)
    3. GET  /portafolio        → dashboard con acceso a "Presentar DIOT".
    4. GET  /diot               → formulario de carga del archivo DIOT.
    5. POST /diot/cargar        → sube y valida el archivo. Responde:
                                    - 200 con #diot-preview + botón
                                      #diot-confirmar (listo para confirmar)
                                    - 200 con #diot-error (archivo vacío)
                                    - 200 con #diot-rechazo (SAT "rechaza"
                                      el archivo — contenido con marcador
                                      de prueba FORZAR_RECHAZO)
                                    - 504 (timeout — contenido con marcador
                                      de prueba FORZAR_TIMEOUT)
    6. POST /diot/confirmar      → confirma el envío previamente cargado.
                                    Responde con el acuse (folio, fecha,
                                    sello) o error si no hay nada en staging
                                    para esa sesión.

Disparadores de prueba (SOLO existen en este simulador, NO son
comportamiento real del SAT — son ganchos para poder escribir pruebas de
contrato deterministas):
    - password == "wrong"            → credenciales inválidas
    - password == "captcha-trigger"  → CAPTCHA
    - rfc == "PORTALCAIDO0000000"    → portal caído (503) antes de procesar
    - contenido del DIOT contiene "FORZAR_RECHAZO" → rechazo del archivo
    - contenido del DIOT contiene "FORZAR_TIMEOUT" → timeout (504)
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

_NAME_RE = re.compile(r'name="([^"]*)"')
_FILENAME_RE = re.compile(r'filename="([^"]*)"')


def _parse_multipart(content_type: str, body: bytes) -> Dict[str, List[Dict[str, Any]]]:
    """Parser mínimo de multipart/form-data (stdlib puro, sin `cgi`).

    Devuelve {nombre_campo: [{"filename": str|None, "value": bytes}, ...]}.
    Suficiente para los formularios controlados de este simulador; NO es un
    parser HTTP de propósito general.
    """
    if "boundary=" not in content_type:
        return {}
    boundary = content_type.split("boundary=")[-1].strip().strip('"')
    delimiter = ("--" + boundary).encode()
    fields: Dict[str, List[Dict[str, Any]]] = {}
    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, value = part.split(b"\r\n\r\n", 1)
        value = value[:-2] if value.endswith(b"\r\n") else value
        headers = header_blob.decode("utf-8", errors="replace")
        name_match = _NAME_RE.search(headers)
        if not name_match:
            continue
        filename_match = _FILENAME_RE.search(headers)
        fields.setdefault(name_match.group(1), []).append({
            "filename": filename_match.group(1) if filename_match else None,
            "value": value,
        })
    return fields


def _field(fields: Dict[str, List[Dict[str, Any]]], name: str, default: str = "") -> str:
    entries = fields.get(name) or []
    if not entries:
        return default
    return entries[0]["value"].decode("utf-8", errors="replace")


def _file_bytes(fields: Dict[str, List[Dict[str, Any]]], name: str) -> bytes:
    entries = fields.get(name) or []
    if not entries:
        return b""
    return entries[0]["value"]


class SATPortalHandler(BaseHTTPRequestHandler):
    """Simulador HTTP del portal del SAT para pruebas E2E de RPA."""

    SESSIONS: Dict[str, Dict[str, Any]] = {}
    SUBMISSIONS: Dict[str, Dict[str, Any]] = {}

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_login()
        elif path == "/portafolio":
            self._with_session(self._serve_portafolio)
        elif path == "/diot":
            self._with_session(self._serve_diot_form)
        elif path.startswith("/diot/acuse/"):
            self._serve_acuse(path.rsplit("/", 1)[-1])
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            self._handle_login()
        elif path == "/diot/cargar":
            self._with_session(self._handle_diot_cargar)
        elif path == "/diot/confirmar":
            self._with_session(self._handle_diot_confirmar)
        else:
            self.send_error(404)

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # silenciar logs de acceso durante las pruebas

    # -- helpers -------------------------------------------------------------
    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _session_token(self) -> Optional[str]:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part[len("session="):]
        return None

    def _with_session(self, handler) -> None:
        token = self._session_token()
        if token and token in self.SESSIONS:
            handler(token)
        else:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

    def _html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    # -- login ---------------------------------------------------------------
    def _serve_login(self) -> None:
        self._html(200, """
<html><head><title>Acceso e.firma (simulador SAT)</title></head><body>
<h1 id="login-title">Acceso con e.firma</h1>
<form method="POST" action="/login" enctype="multipart/form-data">
  <input type="text" name="rfc" id="rfc-input" placeholder="RFC">
  <input type="file" name="cer" id="cer-input">
  <input type="file" name="key" id="key-input">
  <input type="password" name="password" id="password-input">
  <button type="submit" id="login-submit">Enviar</button>
</form>
</body></html>""")

    def _handle_login(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        fields = _parse_multipart(content_type, self._read_body())
        rfc = _field(fields, "rfc")
        password = _field(fields, "password")
        cer = _file_bytes(fields, "cer")
        key = _file_bytes(fields, "key")

        # Gancho de prueba: portal caído, ANTES de validar nada más.
        if rfc == "PORTALCAIDO0000000":
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Servicio no disponible temporalmente.")
            return

        if password == "captcha-trigger":
            self._html(200, """
<html><body>
<h1 id="login-title">Acceso con e.firma</h1>
<div id="captcha-challenge">Verificacion adicional requerida (CAPTCHA)</div>
</body></html>""")
            return

        if not cer or not key:
            self._html(200, """
<html><body>
<h1 id="login-title">Acceso con e.firma</h1>
<p id="login-error">Falta el certificado (.cer) o la llave privada (.key).</p>
</body></html>""")
            return

        if password == "wrong" or not password:
            self._html(200, """
<html><body>
<h1 id="login-title">Acceso con e.firma</h1>
<p id="login-error">La contrasena de la llave privada es incorrecta.</p>
</body></html>""")
            return

        token = f"sess_{len(self.SESSIONS) + 1}_{int(time.time() * 1000)}"
        self.SESSIONS[token] = {"rfc": rfc, "staged_diot": None, "staged_periodo": None}
        self.send_response(302)
        self.send_header("Set-Cookie", f"session={token}; Path=/")
        self.send_header("Location", "/portafolio")
        self.end_headers()

    # -- portafolio / DIOT -----------------------------------------------------
    def _serve_portafolio(self, token: str) -> None:
        self._html(200, """
<html><body>
<h1 id="portafolio-title">Portafolio de tramites</h1>
<nav>
  <a href="/diot" id="nav-diot">Presentar DIOT</a>
</nav>
</body></html>""")

    def _serve_diot_form(self, token: str) -> None:
        self._html(200, """
<html><body>
<h1 id="diot-title">Presentar DIOT</h1>
<form method="POST" action="/diot/cargar" enctype="multipart/form-data">
  <select name="periodo" id="periodo-select">
    <option value="2026-01">2026-01</option>
    <option value="2026-02">2026-02</option>
  </select>
  <input type="file" name="diot_file" id="diot-file-input">
  <button type="submit" id="diot-cargar-submit">Cargar archivo</button>
</form>
</body></html>""")

    def _handle_diot_cargar(self, token: str) -> None:
        content_type = self.headers.get("Content-Type", "")
        fields = _parse_multipart(content_type, self._read_body())
        periodo = _field(fields, "periodo", "0000-00")
        content = _file_bytes(fields, "diot_file")

        if not content.strip():
            self._html(200, """
<html><body>
<h1 id="diot-title">Presentar DIOT</h1>
<p id="diot-error">El archivo DIOT esta vacio o no se recibio.</p>
</body></html>""")
            return

        text = content.decode("utf-8", errors="replace")
        if "FORZAR_TIMEOUT" in text:
            self.send_response(504)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Tiempo de espera agotado del servicio.")
            return

        if "FORZAR_RECHAZO" in text:
            self._html(200, """
<html><body>
<h1 id="diot-title">Presentar DIOT</h1>
<p id="diot-rechazo">El archivo fue rechazado: formato invalido (simulado).</p>
</body></html>""")
            return

        num_lineas = len([ln for ln in text.splitlines() if ln.strip()])
        self.SESSIONS[token]["staged_diot"] = content
        self.SESSIONS[token]["staged_periodo"] = periodo
        self._html(200, f"""
<html><body>
<h1 id="diot-title">Presentar DIOT</h1>
<div id="diot-preview">
  <span id="diot-preview-count">{num_lineas}</span> registros detectados
  para el periodo {periodo}.
</div>
<form method="POST" action="/diot/confirmar">
  <button type="submit" id="diot-confirmar">Confirmar envio</button>
</form>
</body></html>""")

    def _handle_diot_confirmar(self, token: str) -> None:
        session = self.SESSIONS.get(token, {})
        staged = session.get("staged_diot")
        if not staged:
            self._html(200, """
<html><body>
<h1 id="diot-title">Presentar DIOT</h1>
<p id="diot-error">No hay ningun archivo cargado pendiente de confirmar.</p>
</body></html>""")
            return

        periodo = session.get("staged_periodo") or "0000-00"
        digest = hashlib.sha256(staged).hexdigest()[:12].upper()
        folio = f"ACUSE-{periodo}-{digest}"
        fecha = time.strftime("%Y-%m-%dT%H:%M:%S")
        sello = hashlib.sha256((folio + fecha).encode()).hexdigest()[:24]
        self.SUBMISSIONS[folio] = {
            "folio": folio, "periodo": periodo, "fecha_recepcion": fecha,
            "sello": sello, "rfc": session.get("rfc"),
        }
        session["staged_diot"] = None
        session["staged_periodo"] = None
        self._html(200, f"""
<html><body>
<h1 id="diot-title">Acuse de recepcion</h1>
<div id="acuse-folio">{folio}</div>
<div id="acuse-fecha">{fecha}</div>
<div id="acuse-sello">{sello}</div>
</body></html>""")

    def _serve_acuse(self, folio: str) -> None:
        import json
        record = self.SUBMISSIONS.get(folio)
        if not record:
            self.send_error(404)
            return
        payload = json.dumps(record).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_sat_portal_server(port: int = 18766) -> HTTPServer:
    """Arranca el simulador del portal SAT en localhost. Devuelve el server."""
    server = HTTPServer(("127.0.0.1", port), SATPortalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
