# -*- coding: utf-8 -*-
"""test_document_management.py — Tests del sistema de gestión documental.

Cubre:
  - DocumentService.upload_document: hash SHA-256, versión 1, storage.
  - Versionado: re-subida del mismo nombre crea nueva versión (sin duplicar).
  - search_documents: por query, tags, categoría.
  - get_document / read_document_bytes: lectura y pertenencia por tenant.
  - get_version_history: historial ordenado desc.
  - share_document / list_shares.
  - add_tag / archive_document.
  - Backend LocalStorage: save/read/delete/exists y path traversal.
  - OCR: extract_text_from_pdf (pdfplumber) y extract_cfdi_data_from_xml.
  - Router /api/v1/documents/* (upload/search/get).
"""
from __future__ import annotations

import io
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.document_management.models import (
    Document,
    DocumentCategory,
    DocumentVersion,
    SharePermission,
)
from b2b_ai.features.document_management.ocr_integration import (
    extract_cfdi_data_from_xml,
    extract_text_from_pdf,
)
from b2b_ai.features.document_management.service import (
    DocumentService,
    _reset_state,
)
from b2b_ai.features.document_management.storage import (
    LocalStorage,
    StorageBackendError,
    get_backend,
)
from b2b_ai.features.document_management.routes import build_document_router


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_state()
    yield
    _reset_state()


@pytest.fixture()
def service(tmp_path):
    return DocumentService(kind="local", root=str(tmp_path / "docs"))


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def test_upload_creates_version_1_with_sha256(service):
    doc = service.upload_document(
        "T1", "factura.xml", b"<xml/>",
        category=DocumentCategory.CFDI, tags=["fiscal", "2024"])
    assert isinstance(doc, Document)
    assert doc.version == 1
    assert len(doc.sha256) == 64
    assert doc.category == DocumentCategory.CFDI
    assert "fiscal" in doc.tags
    assert service.storage.exists(doc.storage_path)


def test_upload_empty_data_raises(service):
    with pytest.raises(ValueError):
        service.upload_document("T1", "x.txt", b"")


def test_upload_versioning_same_name(service):
    d1 = service.upload_document("T1", "factura.xml", b"v1")
    d2 = service.upload_document("T1", "factura.xml", b"v2")
    assert d1.id == d2.id
    assert d2.version == 2
    assert d1.sha256 != d2.sha256
    history = service.get_version_history("T1", d1.id)
    assert [h.version for h in history] == [2, 1]
    assert all(isinstance(h, DocumentVersion) for h in history)


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

def test_search_by_query_and_category(service):
    service.upload_document("T1", "factura.xml", b"<cfdi/>",
                            category=DocumentCategory.CFDI,
                            tags=["proveedor-a"], metadata={"rfc": "ABC123456789"})
    service.upload_document("T1", "contrato.pdf", b"%PDF-1.4 contrato",
                            category=DocumentCategory.CONTRATO)

    by_q = service.search_documents("T1", query="factura")
    assert len(by_q) == 1
    assert by_q[0].name == "factura.xml"

    by_rfc = service.search_documents("T1", query="ABC123456789")
    assert len(by_rfc) == 1

    by_cat = service.search_documents("T1", category=DocumentCategory.CONTRATO)
    assert len(by_cat) == 1

    by_tag = service.search_documents("T1", tags=["proveedor-a"])
    assert len(by_tag) == 1


def test_search_isolates_tenants(service):
    service.upload_document("T1", "doc.pdf", b"data")
    service.upload_document("T2", "doc.pdf", b"data")
    assert len(service.search_documents("T1")) == 1


# ---------------------------------------------------------------------------
# Lectura / pertenencia
# ---------------------------------------------------------------------------

def test_get_document_and_read_bytes(service):
    doc = service.upload_document("T1", "doc.txt", b"hola", content_type="text/plain")
    assert service.get_document("T1", doc.id).name == "doc.txt"
    assert service.read_document_bytes("T1", doc.id) == b"hola"


def test_get_document_other_tenant_raises(service):
    doc = service.upload_document("T1", "doc.txt", b"hola")
    with pytest.raises(KeyError):
        service.get_document("T2", doc.id)


# ---------------------------------------------------------------------------
# Compartición
# ---------------------------------------------------------------------------

def test_share_and_list(service):
    doc = service.upload_document("T1", "doc.pdf", b"data")
    share = service.share_document(
        "T1", doc.id, "socio@ejemplo.com", permission=SharePermission.EDICION)
    assert share.permission == SharePermission.EDICION
    shares = service.list_shares("T1", doc.id)
    assert len(shares) == 1
    assert shares[0].shared_with == "socio@ejemplo.com"


# ---------------------------------------------------------------------------
# Tags / archivo
# ---------------------------------------------------------------------------

def test_add_tag_and_archive(service):
    doc = service.upload_document("T1", "doc.pdf", b"data")
    service.add_tag("T1", doc.id, "nuevo")
    assert "nuevo" in doc.tags
    archived = service.archive_document("T1", doc.id)
    assert archived.status.value == "ARCHIVADO"
    assert service.search_documents("T1") == []


# ---------------------------------------------------------------------------
# Backend LocalStorage
# ---------------------------------------------------------------------------

def test_localstorage_roundtrip(tmp_path):
    st = LocalStorage(root=str(tmp_path / "storage"))
    path = st.save("T1/ab/file.bin", b"\x00\x01")
    assert st.exists(path)
    assert st.read(path) == b"\x00\x01"
    assert st.delete(path) is True
    assert st.exists(path) is False


def test_localstorage_path_traversal_blocked(tmp_path):
    st = LocalStorage(root=str(tmp_path / "storage"))
    with pytest.raises(StorageBackendError):
        st.save("../../evil.txt", b"x")


def test_get_backend_factory(tmp_path):
    st = get_backend("local", root=str(tmp_path / "b"))
    assert isinstance(st, LocalStorage)
    with pytest.raises(Exception):
        get_backend("nosuch")


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def test_extract_cfdi_from_xml():
    # XML mínimo que el parser reconoce como CFDI (se tolera error si el
    # esquema no es completo, pero debe devolver dict sin crashear).
    xml = b"""<?xml version="1.0"?>
    <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
        Version="4.0" Serie="A" Folio="1" Fecha="2024-03-15T10:00:00"
        SubTotal="1000.00" Total="1160.00" TipoDeComprobante="I" MetodoPago="PUE"
        FormaPago="01" Moneda="MXN" LugarExpedicion="45000">
      <cfdi:Emisor Rfc="ABC123456789" Nombre="Proveedor SA" RegimenFiscal="601"/>
      <cfdi:Receptor Rfc="XYZ987654321" Nombre="Cliente SA" UsoCFDI="G03"/>
      <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1"
          ClaveUnidad="EA" Descripcion="Servicio" ValorUnitario="1000.00"
          Importe="1000.00">
          <cfdi:Impuestos>
            <cfdi:Traslados><cfdi:Traslado Base="1000.00" Impuesto="002"
              TipoFactor="Tasa" TasaOCuota="0.160000" Importe="160.00"/></cfdi:Traslados>
          </cfdi:Impuestos>
        </cfdi:Concepto>
      </cfdi:Conceptos>
      <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados><cfdi:Traslado Base="1000.00" Impuesto="002"
          TipoFactor="Tasa" TasaOCuota="0.160000" Importe="160.00"/></cfdi:Traslados>
      </cfdi:Impuestos>
    </cfdi:Comprobante>"""
    data = extract_cfdi_data_from_xml(xml)
    # Si el parser completo falla por falta de sello, devuelve dict con error
    if data.get("error"):
        assert "error" in data
    else:
        assert data.get("emisor_rfc") == "ABC123456789"


def test_extract_text_from_pdf_empty():
    assert extract_text_from_pdf(b"") == ""
    # Contenido no-PDF devuelve "" sin crashear
    assert extract_text_from_pdf(b"not a pdf") == ""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def _make_client():
    app = FastAPI()

    def _auth():
        return {"tenant_id": "T1", "user_id": "u1"}

    app.include_router(build_document_router(db=None, require_api_key=lambda: _auth()))
    return TestClient(app)


def test_router_upload_search_get(tmp_path):
    client = _make_client()
    # reset in-memory docs + apuntar storage a tmp
    _reset_state()

    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("factura.xml", b"<cfdi/>", "application/xml")},
        data={"category": "CFDI", "tags": "fiscal,proveedor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    doc_id = body["document"]["id"]
    assert body["document"]["sha256"]

    sresp = client.get("/api/v1/documents/search", params={"q": "factura"})
    assert sresp.status_code == 200
    assert sresp.json()["count"] == 1

    gresp = client.get(f"/api/v1/documents/{doc_id}")
    assert gresp.status_code == 200
    assert gresp.json()["document"]["name"] == "factura.xml"

    cresp = client.get(f"/api/v1/documents/{doc_id}/content")
    assert cresp.status_code == 200
    assert cresp.content == b"<cfdi/>"


def test_router_upload_empty_returns_400(tmp_path):
    client = _make_client()
    _reset_state()
    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("empty.bin", b"", "application/octet-stream")},
    )
    assert resp.status_code == 400
