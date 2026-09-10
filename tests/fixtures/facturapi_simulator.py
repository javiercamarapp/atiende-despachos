# -*- coding: utf-8 -*-
"""facturapi_simulator.py — Simulador local del API pública de FacturAPI.

**ESTO NO ES FACTURAPI.** Es un servidor HTTP local (stdlib puro, sin
dependencias externas) que imita, a partir del contrato documentado
públicamente en https://docs.facturapi.io/en/api/ (revisado sept-2026), el
comportamiento de:

    - POST   /invoices              → timbrar CFDI
    - DELETE /invoices/{id}         → cancelar CFDI
    - GET    /invoices/{id}         → consultar CFDI

NO se construyó a partir de una cuenta real de FacturAPI ni de tráfico
capturado contra facturapi.io (regla no negociable de esta tarea: ningún test
toca la red real). La forma de los payloads/respuestas es la documentada
públicamente; cualquier detalle no confirmado se simplificó de la forma más
honesta posible. Ver
`b2b_ai/integrations/sat/pacs/facturapi_adapter.py` (docstring del módulo)
para el detalle del contrato investigado y
`docs/integraciones/facturapi-pac-real.md` para el estado de verificación.

Disparadores de prueba (SOLO existen en este simulador, NO son comportamiento
real de FacturAPI — son ganchos para escribir pruebas de contrato
deterministas):
    - Authorization ausente o distinta de "Bearer <VALID_API_KEY>" → 401 con
      el cuerpo de error documentado.
    - `customer.tax_id` == "RFC_INVALIDO_TEST" → 400, simulando un rechazo
      real del PAC por RFC receptor inválido.
    - Cancelar/consultar un id que no existe en `INVOICES` → 404.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid as uuid_lib
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

# API key que este simulador acepta como válida. Los tests que quieran
# probar el camino feliz deben configurar el adaptador con esta key.
VALID_API_KEY = "sk_test_facturapi_simulator_valid"

# Gancho de prueba: un tax_id que el simulador siempre rechaza como si fuera
# un RFC receptor inválido real (comportamiento real documentado: 4xx con
# cuerpo {"message","code","errors":[...]}).
RFC_TRIGGER_INVALIDO = "RFC_INVALIDO_TEST"


class FacturapiSimulatorHandler(BaseHTTPRequestHandler):
    """Simulador HTTP del API de FacturAPI para pruebas de contrato."""

    INVOICES: Dict[str, Dict[str, Any]] = {}

    _INVOICE_PATH_RE = re.compile(r"^/invoices/([^/]+)$")

    # -- helpers ------------------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # silenciar logs de acceso durante las pruebas

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {VALID_API_KEY}"

    def _unauthorized(self) -> None:
        self._send_json(401, {
            "message": "Authentication error: invalid or missing API key.",
            "status": 401,
            "ok": False,
            "code": "invalid_api_key",
            "errors": [],
        })

    # -- routing --------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/invoices":
            self._handle_create_invoice()
        else:
            self.send_error(404)

    def do_GET(self):
        path = urlparse(self.path).path
        match = self._INVOICE_PATH_RE.match(path)
        if match:
            self._handle_get_invoice(match.group(1))
        else:
            self.send_error(404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        match = self._INVOICE_PATH_RE.match(path)
        if match:
            query = parse_qs(urlparse(self.path).query)
            self._handle_cancel_invoice(match.group(1), query)
        else:
            self.send_error(404)

    # -- POST /invoices -------------------------------------------------------
    def _handle_create_invoice(self) -> None:
        if not self._check_auth():
            self._unauthorized()
            return

        body = self._read_json_body()
        customer = body.get("customer") or {}
        tax_id = customer.get("tax_id", "")

        if tax_id == RFC_TRIGGER_INVALIDO:
            self._send_json(400, {
                "message": "El RFC del receptor no es válido ante el SAT.",
                "status": 400,
                "ok": False,
                "code": "invalid_customer",
                "errors": [{
                    "message": "customer.tax_id no es un RFC válido.",
                    "code": "invalid_tax_id",
                    "location": "body",
                    "path": "customer.tax_id",
                    "source": "facturapi",
                }],
            })
            return

        invoice_id = uuid_lib.uuid4().hex[:24]
        fiscal_uuid = str(uuid_lib.uuid4())
        items = body.get("items") or []
        subtotal = sum(
            float(item.get("product", {}).get("price", 0)) * item.get("quantity", 1)
            for item in items
        )
        now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        invoice = {
            "id": invoice_id,
            "uuid": fiscal_uuid,
            "status": "valid",
            "cancellation_status": "none",
            "customer": customer,
            "organization": {"tax_id": "AAA010101AAA"},
            "items": items,
            "subtotal": round(subtotal, 2),
            "total": round(subtotal, 2),
            "series": body.get("series", "A"),
            "folio_number": len(self.INVOICES) + 1,
            "payment_form": body.get("payment_form"),
            "use": body.get("use"),
            "created_at": now,
            "verification_url": f"https://verificacfdi.facturaelectronica.sat.gob.mx/simulado/{fiscal_uuid}",
            "stamp": {
                "date": now,
                "sat_seal": f"sello-sat-simulado-{invoice_id}",
                "cfdi_seal": f"sello-cfdi-simulado-{invoice_id}",
                "sat_cert_number": "00001000000500003416",
            },
        }
        self.INVOICES[invoice_id] = invoice
        # También se indexa por el UUID fiscal: el adaptador real usa el UUID
        # fiscal como id al cancelar/consultar (ver docstring de
        # FacturapiAdapter.cancelar_cfdi sobre por qué ambos coinciden en la
        # práctica para CFDIs timbrados por el propio adaptador).
        self.INVOICES[fiscal_uuid] = invoice
        self._send_json(200, invoice)

    # -- GET /invoices/{id} -----------------------------------------------------
    def _handle_get_invoice(self, invoice_id: str) -> None:
        if not self._check_auth():
            self._unauthorized()
            return
        invoice = self.INVOICES.get(invoice_id)
        if invoice is None:
            self._send_json(404, {
                "message": f"No se encontró la factura {invoice_id}.",
                "status": 404,
                "ok": False,
                "code": "invoice_not_found",
                "errors": [],
            })
            return
        self._send_json(200, invoice)

    # -- DELETE /invoices/{id} --------------------------------------------------
    def _handle_cancel_invoice(self, invoice_id: str, query: Dict[str, Any]) -> None:
        if not self._check_auth():
            self._unauthorized()
            return
        invoice = self.INVOICES.get(invoice_id)
        if invoice is None:
            self._send_json(404, {
                "message": f"No se encontró la factura {invoice_id}.",
                "status": 404,
                "ok": False,
                "code": "invoice_not_found",
                "errors": [],
            })
            return

        motive = (query.get("motive") or [None])[0]
        if motive not in {"01", "02", "03", "04"}:
            self._send_json(400, {
                "message": "El parámetro 'motive' es requerido y debe ser 01-04.",
                "status": 400,
                "ok": False,
                "code": "invalid_motive",
                "errors": [],
            })
            return

        invoice["status"] = "canceled"
        invoice["cancellation_status"] = "accepted"
        self._send_json(200, invoice)


def start_facturapi_simulator(port: int = 18777) -> HTTPServer:
    """Arranca el simulador de FacturAPI en localhost. Devuelve el server."""
    server = HTTPServer(("127.0.0.1", port), FacturapiSimulatorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
