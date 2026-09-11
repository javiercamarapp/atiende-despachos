# -*- coding: utf-8 -*-
"""sat_consulta_cfdi_simulator.py — Simulador local del WSDL público del SAT
para el servicio de "Verificación de Comprobantes Fiscales Digitales por
Internet" (ConsultaCFDIService).

**ESTO NO ES EL SAT.** Es un servidor HTTP local (stdlib puro, sin
dependencias externas) que imita, a partir del contrato leído directamente
del WSDL real y del PDF oficial "Documentación del Servicio de Consulta de
CFDI" v1.4 (ver docstring de `b2b_ai/sat/validator.py`), la forma exacta del
sobre SOAP de respuesta de la operación `Consulta`:

    POST /ConsultaCFDIService.svc   (SOAPAction: .../IConsultaCFDIService/Consulta)
        -> <soap:Envelope>...<ConsultaResponse><ConsultaResult>
             <CodigoEstatus/><EsCancelable/><Estado/><EstatusCancelacion/>
             <ValidacionEFOS/>
           </ConsultaResult></ConsultaResponse></soap:Envelope>

NO se construyó a partir de tráfico real capturado contra
consultaqr.facturaelectronica.sat.gob.mx (regla no negociable de esta tarea:
ningún test toca la red real del SAT). La forma del sobre/namespaces es la
documentada públicamente en el WSDL leído durante esta tarea; el mapeo
folio→estatus es un gancho de prueba determinista que SOLO existe aquí, no
es comportamiento real del SAT.

Disparadores de prueba (SOLO existen en este simulador):
    - folio_fiscal termina en '0'                 -> Estado=Cancelado
    - folio_fiscal == FOLIO_NO_ENCONTRADO_TEST      -> CodigoEstatus "N 602"
      (Comprobante no encontrado; Estado ausente, igual que el SAT real).
    - folio_fiscal == FOLIO_EXPRESION_INVALIDA_TEST -> CodigoEstatus "N 601"
    - folio_fiscal == FOLIO_ESTADO_DESCONOCIDO_TEST  -> Estado="Suspendido"
      (valor no documentado, para probar el camino fail-closed).
    - folio_fiscal == FOLIO_SOAP_FAULT_TEST          -> SOAP Fault 500.
    - folio_fiscal == FOLIO_XML_INVALIDO_TEST        -> cuerpo no-XML, 200.
    - cualquier otro folio bien formado              -> Estado=Vigente.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

FOLIO_NO_ENCONTRADO_TEST = "00000000-0000-0000-0000-000000000602"
FOLIO_EXPRESION_INVALIDA_TEST = "00000000-0000-0000-0000-000000000601"
FOLIO_ESTADO_DESCONOCIDO_TEST = "00000000-0000-0000-0000-000000009999"
FOLIO_SOAP_FAULT_TEST = "00000000-0000-0000-0000-0000000000fa"
FOLIO_XML_INVALIDO_TEST = "00000000-0000-0000-0000-00000000bad0"

_NS_TEMPURI = "http://tempuri.org/"
_NS_SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_ACUSE = "http://schemas.datacontract.org/2004/07/Sat.Cfdi.Negocio.ConsultaCfdi.Servicio"


def _extraer_expresion_impresa(body: bytes) -> str:
    """Extrae el texto de <tem:expresionImpresa> del sobre SOAP de request."""
    root = ET.fromstring(body)
    els = root.findall(f".//{{{_NS_TEMPURI}}}expresionImpresa")
    return els[0].text or "" if els else ""


def _parse_expresion_impresa(expresion: str) -> dict:
    """`?re=..&rr=..&tt=..&id=..` -> dict de un solo valor por clave."""
    qs = expresion.lstrip("?")
    parsed = parse_qs(qs, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


def _acuse_response(codigo_estatus, es_cancelable, estado,
                     estatus_cancelacion, validacion_efos) -> bytes:
    def _campo(nombre, valor):
        if valor is None:
            return f'<{nombre} xmlns="{_NS_ACUSE}" i:nil="true" xmlns:i="http://www.w3.org/2001/XMLSchema-instance"/>'
        return f'<{nombre} xmlns="{_NS_ACUSE}">{valor}</{nombre}>'

    acuse = (
        f'<ConsultaResult xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
        + _campo("CodigoEstatus", codigo_estatus)
        + _campo("EsCancelable", es_cancelable)
        + _campo("Estado", estado)
        + _campo("EstatusCancelacion", estatus_cancelacion)
        + _campo("ValidacionEFOS", validacion_efos)
        + "</ConsultaResult>"
    )
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{_NS_SOAP_ENV}">'
        "<s:Body>"
        f'<ConsultaResponse xmlns="{_NS_TEMPURI}">'
        + acuse +
        "</ConsultaResponse>"
        "</s:Body>"
        "</s:Envelope>"
    )
    return envelope.encode("utf-8")


def _soap_fault_response() -> bytes:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{_NS_SOAP_ENV}">'
        "<s:Body><s:Fault>"
        "<faultcode>s:Server</faultcode>"
        "<faultstring>Error interno simulado del servicio de Verificación de CFDI.</faultstring>"
        "</s:Fault></s:Body>"
        "</s:Envelope>"
    )
    return envelope.encode("utf-8")


class SATConsultaCFDISimulatorHandler(BaseHTTPRequestHandler):
    """Simulador HTTP del WSDL ConsultaCFDIService para pruebas de contrato."""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # silenciar logs de acceso durante las pruebas

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/ConsultaCFDIService.svc":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            expresion = _extraer_expresion_impresa(raw)
        except ET.ParseError:
            self._send_xml(400, b"<error>request SOAP invalido</error>")
            return

        campos = _parse_expresion_impresa(expresion)
        folio = campos.get("id", "")

        if folio == FOLIO_SOAP_FAULT_TEST:
            self._send_xml(500, _soap_fault_response())
            return
        if folio == FOLIO_XML_INVALIDO_TEST:
            self._send_xml(200, b"esto no es xml valido <<<")
            return
        if folio == FOLIO_NO_ENCONTRADO_TEST:
            body = _acuse_response(
                "N 602: Comprobante no encontrado.", None, None, None, None,
            )
            self._send_xml(200, body)
            return
        if folio == FOLIO_EXPRESION_INVALIDA_TEST:
            body = _acuse_response(
                "N 601: La expresión impresa proporcionada no es válida.",
                None, None, None, None,
            )
            self._send_xml(200, body)
            return
        if folio == FOLIO_ESTADO_DESCONOCIDO_TEST:
            body = _acuse_response(
                "S - Comprobante obtenido satisfactoriamente.",
                "No cancelable", "Suspendido", None, "201",
            )
            self._send_xml(200, body)
            return
        if folio.endswith("0"):
            body = _acuse_response(
                "S - Comprobante obtenido satisfactoriamente.",
                "No cancelable", "Cancelado",
                "Cancelado sin aceptación", "201",
            )
            self._send_xml(200, body)
            return

        body = _acuse_response(
            "S - Comprobante obtenido satisfactoriamente.",
            "Cancelable sin aceptación", "Vigente", None, "201",
        )
        self._send_xml(200, body)

    def _send_xml(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_sat_consulta_cfdi_simulator(port: int = 18778) -> HTTPServer:
    """Arranca el simulador de ConsultaCFDIService en localhost. Devuelve el server."""
    server = HTTPServer(("127.0.0.1", port), SATConsultaCFDISimulatorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
