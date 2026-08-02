# -*- coding: utf-8 -*-
"""
test_batch_cfdi.py — Tests del módulo de procesamiento batch de CFDIs.

Cubre:
  - Límites: 500 CFDIs por batch, 10 MB max de subida
  - Extracción desde ZIP de XML y desde CSV
  - Creación de BatchJob + BatchItems
  - Procesamiento: ítems exitosos, fallidos y conteos/reportes
  - Webhook cfdi.batch.completed al terminar
  - API: POST /api/v1/cfdi/batch y GET /api/v1/cfdi/batch/{id} con auth
"""
from __future__ import annotations

import io
import zipfile

import pytest

from b2b_ai.cfdi.parser import parse_cfdi_4
from b2b_ai.features.batch.models import (
    BatchItemStatus,
    BatchJob,
    BatchJobStatus,
)
from b2b_ai.features.batch.service import (
    BatchLimitError,
    BatchService,
    MAX_ITEMS,
    MAX_UPLOAD_BYTES,
    reset_state,
)
from b2b_ai.features.webhooks.models import WebhookEventType
from b2b_ai.features.webhooks.service import WebhookService, reset_state as wh_reset


SAMPLE_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="D" Folio="100"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Descuento="0.00" Total="1160.00">
    <cfdi:Emisor Rfc="PAP850101JKL" Nombre="PAPELERIA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR TEST"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Papeleria y articulos de oficina"
            ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                        TasaOCuota="0.160000" Importe="160.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1"
            UUID="550e8400-e29b-41d4-a716-446655440000"
            FechaTimbrado="2026-07-03T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

BAD_CFDI = "<xml>no es un cfdi</xml>"

INVALID_NO_SELLO = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Serie="X" Folio="999"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="500.00" Total="580.00">
    <cfdi:Emisor Rfc="PABD850101AB1" Nombre="EMPRESA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            Descripcion="Servicio" ValorUnitario="500.00" Importe="500.00"/>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="80.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="500.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="80.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
</cfdi:Comprobante>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_zip(*xmls, names=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, xml in enumerate(xmls):
            name = (names[i] if names and i < len(names) else f"cfdi_{i}.xml")
            zf.writestr(name, xml)
    return buf.getvalue()


def _clean():
    reset_state()
    wh_reset()


# ---------------------------------------------------------------------------
# Límites
# ---------------------------------------------------------------------------

class TestLimits:
    def test_max_items_constant(self):
        assert MAX_ITEMS == 500

    def test_max_upload_bytes(self):
        assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Extracción
# ---------------------------------------------------------------------------

class TestExtraction:
    @pytest.fixture(autouse=True)
    def _clean(self):
        _clean()
        yield
        _clean()

    def test_extract_from_zip(self):
        svc = BatchService()
        pairs = svc.extract_xmls(make_zip(SAMPLE_CFDI, SAMPLE_CFDI), "lote.zip")
        assert len(pairs) == 2
        assert all(n.endswith(".xml") for n, _ in pairs)
        assert all(SAMPLE_CFDI in content for _, content in pairs)

    def test_extract_from_csv(self):
        svc = BatchService()
        csv_data = "filename,xml_content\n" \
                   f"a.xml,\"{SAMPLE_CFDI.replace(chr(34), chr(34)+chr(34))}\"\n" \
                   f"b.xml,\"{SAMPLE_CFDI.replace(chr(34), chr(34)+chr(34))}\"\n"
        pairs = svc.extract_xmls(csv_data.encode("utf-8"), "lote.csv")
        assert len(pairs) == 2

    def test_rejects_unknown_extension(self):
        svc = BatchService()
        with pytest.raises(ValueError):
            svc.extract_xmls(b"data", "file.txt")

    def test_rejects_bad_zip(self):
        svc = BatchService()
        with pytest.raises(ValueError):
            svc.extract_xmls(b"not a zip", "file.zip")


# ---------------------------------------------------------------------------
# Creación y límite de ítems
# ---------------------------------------------------------------------------

class TestCreateJob:
    @pytest.fixture(autouse=True)
    def _clean(self):
        _clean()
        yield
        _clean()

    def test_create_job(self):
        svc = BatchService()
        job = svc.create_job([("a.xml", SAMPLE_CFDI), ("b.xml", SAMPLE_CFDI)])
        assert job.status == BatchJobStatus.PENDING
        assert job.total_items == 2
        assert len(job.items) == 2
        assert svc.get_job(job.id) is job

    def test_create_job_empty_raises(self):
        svc = BatchService()
        with pytest.raises(ValueError):
            svc.create_job([])

    def test_create_job_over_500_raises(self):
        svc = BatchService()
        many = [(f"f{i}.xml", SAMPLE_CFDI) for i in range(MAX_ITEMS + 1)]
        with pytest.raises(BatchLimitError):
            svc.create_job(many)


# ---------------------------------------------------------------------------
# Procesamiento
# ---------------------------------------------------------------------------

class TestProcessJob:
    @pytest.fixture(autouse=True)
    def _clean(self):
        _clean()
        yield
        _clean()

    def test_process_all_success(self):
        svc = BatchService()
        job = svc.create_job([("a.xml", SAMPLE_CFDI), ("b.xml", SAMPLE_CFDI)])
        svc.process_job(job.id)
        assert job.status == BatchJobStatus.COMPLETED
        assert job.success_count == 2
        assert job.failed_count == 0
        assert job.processed_items == 2
        assert job.total_amount == 1160.0 * 2
        assert job.total_iva == 160.0 * 2

    def test_process_mixed_success_and_fail(self):
        svc = BatchService()
        job = svc.create_job([
            ("ok.xml", SAMPLE_CFDI),
            ("bad.xml", BAD_CFDI),
        ])
        svc.process_job(job.id)
        assert job.status == BatchJobStatus.COMPLETED
        assert job.success_count == 1
        assert job.failed_count == 1
        assert job.total_amount == 1160.0

        statuses = {i.filename: i.status for i in job.items}
        assert statuses["ok.xml"] == BatchItemStatus.SUCCESS
        assert statuses["bad.xml"] == BatchItemStatus.FAILED

    def test_process_invalid_cfdi_counts_as_success_with_status(self):
        """Un CFDI mal formado falla; uno válido pero INVALIDO cuenta como OK."""
        svc = BatchService()
        job = svc.create_job([
            ("ok.xml", SAMPLE_CFDI),
            ("no_sello.xml", INVALID_NO_SELLO),
        ])
        svc.process_job(job.id)
        assert job.success_count == 2  # no_sello parsea, da status INVALIDO (no es error de parseo)
        no_sello = [i for i in job.items if i.filename == "no_sello.xml"][0]
        assert no_sello.result["status"] == "INVALIDO"

    def test_summary_report(self):
        svc = BatchService()
        job = svc.create_job([("ok.xml", SAMPLE_CFDI), ("bad.xml", BAD_CFDI)])
        svc.process_job(job.id)
        s = job.summary()
        assert s["total"] == 2
        assert s["successful"] == 1
        assert s["failed"] == 1
        assert s["total_amount"] == 1160.0
        assert s["completed_at"] is not None

    def test_process_missing_job_raises(self):
        svc = BatchService()
        with pytest.raises(KeyError):
            svc.process_job("no-existe")


# ---------------------------------------------------------------------------
# Webhook cfdi.batch.completed
# ---------------------------------------------------------------------------

class TestWebhook:
    @pytest.fixture(autouse=True)
    def _clean(self):
        _clean()
        yield
        _clean()

    def test_batch_completed_event_exists(self):
        assert WebhookEventType.CFDI_BATCH_COMPLETED.value == "cfdi.batch.completed"

    def test_process_publishes_batch_completed(self):
        posts = []

        def _post(url, body, headers):
            posts.append((url, body))
            return {"ok": True, "status_code": 200}

        from b2b_ai.features.webhooks.processor import WebhookProcessor
        wh = WebhookService(processor=WebhookProcessor(http_post=_post, sleep=lambda s: None))
        wh.register_subscription(url="https://hooks.example.com/cb",
                                 secret="secret-largo-123",
                                 event_types=["cfdi.batch.completed"])

        svc = BatchService(webhook_service=wh)
        job = svc.create_job([("ok.xml", SAMPLE_CFDI)])
        svc.process_job(job.id)

        assert len(posts) == 1
        assert b"cfdi.batch.completed" in posts[0][1]

    def test_webhook_failure_does_not_break_batch(self):
        def _fail(url, body, headers):
            raise ConnectionError("down")

        from b2b_ai.features.webhooks.processor import WebhookProcessor
        wh = WebhookService(processor=WebhookProcessor(http_post=_fail, sleep=lambda s: None))
        wh.register_subscription(url="https://hooks.example.com/cb",
                                 secret="secret-largo-123",
                                 event_types=["cfdi.batch.completed"])

        svc = BatchService(webhook_service=wh)
        job = svc.create_job([("ok.xml", SAMPLE_CFDI)])
        svc.process_job(job.id)
        assert job.status == BatchJobStatus.COMPLETED
        assert job.success_count == 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class TestApi:
    @pytest.fixture(autouse=True)
    def _clean(self):
        _clean()
        yield
        _clean()

    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from b2b_ai.features.batch.routes import build_batch_router

        def fake_auth():
            return {"tenant_id": "t1"}

        app = FastAPI()
        app.include_router(build_batch_router(None, fake_auth))
        return TestClient(app)

    def test_upload_zip_creates_batch(self, client):
        r = client.post("/api/v1/cfdi/batch",
                        files={"file": ("lote.zip", make_zip(SAMPLE_CFDI), "application/zip")})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["total_items"] == 1
        assert body["data"]["status"] == "pending"
        batch_id = body["data"]["batch_id"]
        # El job existe
        status = client.get(f"/api/v1/cfdi/batch/{batch_id}")
        assert status.status_code == 200
        assert status.json()["batch"]["total"] == 1

    def test_upload_csv_creates_batch(self, client):
        csv_data = "xml_content\n" \
                   f"\"{SAMPLE_CFDI.replace(chr(34), chr(34)+chr(34))}\"\n" \
                   f"\"{SAMPLE_CFDI.replace(chr(34), chr(34)+chr(34))}\"\n"
        r = client.post("/api/v1/cfdi/batch",
                        files={"file": ("lote.csv", csv_data.encode("utf-8"), "text/csv")})
        assert r.status_code == 200
        assert r.json()["data"]["total_items"] == 2

    def test_upload_empty_file_400(self, client):
        r = client.post("/api/v1/cfdi/batch",
                        files={"file": ("empty.zip", b"", "application/zip")})
        assert r.status_code == 400

    def test_upload_over_10mb_413(self, client):
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        r = client.post("/api/v1/cfdi/batch",
                        files={"file": ("big.zip", big, "application/zip")})
        assert r.status_code == 413

    def test_upload_bad_extension_400(self, client):
        r = client.post("/api/v1/cfdi/batch",
                        files={"file": ("doc.txt", b"hello", "text/plain")})
        assert r.status_code == 400

    def test_upload_over_500_items_413(self, client):
        # Generamos un zip con 501 XML (puede ser pesado, usamos uno pequeño)
        xmls = [f"<xml>{i}</xml>" for i in range(501)]
        zip_bytes = make_zip(*xmls)
        r = client.post("/api/v1/cfdi/batch",
                        files={"file": ("many.zip", zip_bytes, "application/zip")})
        # 501 ítems excede el límite → 413
        assert r.status_code == 413

    def test_get_batch_not_found_404(self, client):
        r = client.get("/api/v1/cfdi/batch/nonexistent")
        assert r.status_code == 404

    def test_router_refuses_without_auth(self):
        from b2b_ai.features.batch.routes import build_batch_router
        with pytest.raises(ValueError):
            build_batch_router(None, None)
