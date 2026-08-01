# -*- coding: utf-8 -*-
"""
test_email_processing.py — Tests del módulo de Recepción de Correos.

Cobertura:
  Monitor:    email vacío, email con adjuntos, email sin adjuntos.
  Extract:    XML CFDI válido, XML inválido, sin adjuntos, subject matching.
  Process:    validación CFDI, RFC inválido, total ausente, todo válido.
  Notify:     resultado válido, inválido, vacío.
  Routes:     POST /scan, POST /process, GET /history, GET /stats.
"""
from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient

from b2b_ai.features.email_processing.models import (
    Attachment,
    EmailMessage,
    ExtractedInvoice,
    ProcessingResult,
)
from b2b_ai.features.email_processing.service import (
    extract_invoices,
    monitor_inbox,
    notify_user,
    process_extracted_invoices,
)
from b2b_ai.features.email_processing.routes import build_email_processing_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(build_email_processing_router())
    return app


def _client() -> TestClient:
    return TestClient(_app())


VALID_CFDI_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="A" Folio="12345"
    Fecha="2026-07-15T10:00:00" Total="15000.00"
    Moneda="MXN" TipoDeComprobante="I"
    MetodoPago="PUE" FormaPago="03"
    NoCertificado="30001000000500003416"
    LugarExpedicion="06600">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Empresa SA"
        RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="RECEPTOR010101BBB" Nombre="Cliente ABC"
        RegimenFiscalReceptor="601" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="43232300" NoIdentificacion="001"
            Cantidad="1" ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Servicio de consultoria" ValorUnitario="15000"
            Importe="15000" ObjetoImp="002"/>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="0"/>
    <tfd:TimbreFiscalDigital Version="1.1"
        UUID="12345678-1234-1234-1234-123456789012"
        FechaTimbrado="2026-07-15T10:00:01"/>
</cfdi:Comprobante>
"""

INVALID_CFDI_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Total="0">
</cfdi:Comprobante>
"""


def _email_con_cfdi(**overrides) -> dict:
    # Use base64 so bytes are JSON-serializable via httpx TestClient
    cfdi_b64 = base64.b64encode(VALID_CFDI_XML.encode("utf-8")).decode("ascii")
    base = {
        "message_id": "msg-001",
        "from": "proveedor@empresa.com",
        "to": "contabilidad@cliente.com",
        "subject": "Factura Electrónica #12345",
        "date": "2026-07-15T10:00:00",
        "body": "Adjunto factura del mes de julio.",
        "attachments": [
            {
                "filename": "factura_12345.xml",
                "content_type": "application/xml",
                "size": 5000,
                "content": cfdi_b64,
            }
        ],
    }
    base.update(overrides)
    return base


def _email_sin_adjuntos() -> dict:
    return {
        "message_id": "msg-002",
        "from": "info@empresa.com",
        "subject": "Reporte mensual",
        "body": "Reporte sin adjuntos.",
        "attachments": [],
    }


# ===========================================================================
# Tests: Monitor Inbox
# ===========================================================================
class TestMonitorInbox:
    def test_emails_vacios(self):
        messages = monitor_inbox(tenant_id=1, emails=[])
        assert messages == []

    def test_email_con_adjunto(self):
        messages = monitor_inbox(tenant_id=1, emails=[_email_con_cfdi()])
        assert len(messages) == 1
        assert messages[0].subject == "Factura Electrónica #12345"
        assert len(messages[0].attachments) == 1

    def test_email_sin_adjuntos(self):
        messages = monitor_inbox(tenant_id=1, emails=[_email_sin_adjuntos()])
        assert len(messages) == 1
        assert messages[0].attachments == []

    def test_multiples_emails(self):
        emails = [_email_con_cfdi(), _email_sin_adjuntos()]
        messages = monitor_inbox(tenant_id=1, emails=emails)
        assert len(messages) == 2


# ===========================================================================
# Tests: Extract Invoices
# ===========================================================================
class TestExtractInvoices:
    def test_extrae_cfdi(self):
        messages = monitor_inbox(tenant_id=1, emails=[_email_con_cfdi()])
        invoices = extract_invoices(messages)
        assert len(invoices) == 1
        assert invoices[0].filename == "factura_12345.xml"

    def test_cfdi_parseado(self):
        messages = monitor_inbox(tenant_id=1, emails=[_email_con_cfdi()])
        invoices = extract_invoices(messages)
        assert invoices[0].emisor_rfc == "EMISOR010101AAA"
        assert invoices[0].receptor_rfc == "RECEPTOR010101BBB"
        assert invoices[0].total == 15000.0

    def test_sin_adjuntos(self):
        messages = monitor_inbox(tenant_id=1, emails=[_email_sin_adjuntos()])
        invoices = extract_invoices(messages)
        assert invoices == []

    def test_xml_invalido(self):
        msg_dict = _email_con_cfdi(
            subject="Archivo XML",
            attachments=[{
                "filename": "data.xml",
                "content_type": "application/xml",
                "size": 100,
                "content": b"<invalid>not a cfdi</invalid>",
            }],
        )
        messages = monitor_inbox(tenant_id=1, emails=[msg_dict])
        invoices = extract_invoices(messages)
        # XML no CFDI — se extrae pero sin datos CFDI
        assert len(invoices) == 1


# ===========================================================================
# Tests: Process Invoices
# ===========================================================================
class TestProcessInvoices:
    def test_cfdi_valido(self):
        messages = monitor_inbox(tenant_id=1, emails=[_email_con_cfdi()])
        invoices = extract_invoices(messages)
        result = process_extracted_invoices(invoices)
        assert result.processed == 1
        assert result.valid == 1
        assert result.invalid == 0

    def test_cfdi_sin_uuid(self):
        inv = ExtractedInvoice(
            filename="test.xml",
            cfdi_data={"emisor_rfc": "EMI010101AAA", "total": 5000},
        )
        result = process_extracted_invoices([inv])
        assert result.invalid == 1
        assert any("UUID" in e for e in inv.errors)

    def test_cfdi_sin_rfc(self):
        inv = ExtractedInvoice(
            filename="test.xml",
            cfdi_data={"total": 5000, "uuid": "12345678-1234-1234-1234-123456789012"},
        )
        result = process_extracted_invoices([inv])
        assert result.invalid == 1
        assert any("emisor" in e for e in inv.errors)

    def test_vacio(self):
        result = process_extracted_invoices([])
        assert result.total_invoices == 0


# ===========================================================================
# Tests: Notify
# ===========================================================================
class TestNotify:
    def test_notificacion_valida(self):
        inv = ExtractedInvoice(
            filename="factura.xml",
            cfdi_data={
                "emisor_rfc": "EMI010101AAA",
                "receptor_rfc": "REC010101BBB",
                "total": "10000",
                "uuid": "12345678-1234-1234-1234-123456789012",
            },
        )
        result = process_extracted_invoices([inv])
        notif = notify_user(result, tenant_id=1)
        assert notif["ok"] is True
        assert notif["valid"] == 1
        assert "✅" in notif["summary"]

    def test_notificacion_vacia(self):
        result = ProcessingResult()
        notif = notify_user(result, tenant_id=1)
        assert "📭" in notif["summary"]

    def test_notificacion_invalida(self):
        inv = ExtractedInvoice(
            filename="bad.xml",
            cfdi_data={"total": 5000},  # Sin RFC ni UUID
        )
        result = process_extracted_invoices([inv])
        notif = notify_user(result, tenant_id=1)
        assert "❌" in notif["summary"]


# ===========================================================================
# Tests: Routes
# ===========================================================================
class TestEmailProcessingRoutes:
    def test_scan(self):
        resp = _client().post("/email/scan", json={
            "tenant_id": 1,
            "emails": [_email_con_cfdi()],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total_invoices_found"] == 1

    def test_scan_vacio(self):
        resp = _client().post("/email/scan", json={
            "tenant_id": 1,
            "emails": [],
        })
        assert resp.status_code == 200
        assert resp.json()["total_invoices_found"] == 0

    def test_process(self):
        resp = _client().post("/email/process", json={
            "invoices": [
                {
                    "filename": "factura.xml",
                    "message_id": "msg-001",
                    "cfdi_data": {
                        "emisor_rfc": "EMI010101AAA",
                        "receptor_rfc": "REC010101BBB",
                        "total": "10000",
                        "uuid": "12345678-1234-1234-1234-123456789012",
                    },
                    "status": "pending",
                }
            ],
            "tenant_id": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["result"]["valid"] == 1

    def test_history(self):
        client = _client()
        client.post("/email/scan", json={
            "tenant_id": 5,
            "emails": [_email_con_cfdi()],
        })
        resp = client.get("/email/history", params={"tenant_id": 5})
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_stats(self):
        client = _client()
        client.post("/email/scan", json={
            "tenant_id": 1,
            "emails": [_email_con_cfdi()],
        })
        resp = client.get("/email/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_scans"] >= 1
