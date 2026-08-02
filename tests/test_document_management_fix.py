# -*- coding: utf-8 -*-
"""test_document_management_fix.py — Tests de regresión de los fixes P2.

Cubre los hallazgos de QA (195) que bloquean el piloto:
  1. Path traversal rechazado (LocalStorage con relative_to).
  2. Aislamiento multi-tenant: el tenant A NO accede a docs del tenant B.
  3. Sin tenant_id en el contexto de auth → 400 (nunca degrada a "default").
  4. Sanitización del nombre en el header Content-Disposition (header injection).
  5. Persistencia opcional a JSON (no se pierde al recrear el servicio).
  6. make_require_api_key devuelve dict con tenant_id/user_id/key.

IMPORTANTE: el repo corre tests con pytest; aquí no se usa nada que dependa de
la carpeta de tests con riesgo de mmap. Los tests son autónomos e importan el
módulo desde el tree del repo.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
from b2b_ai.features.document_management.models import DocumentCategory
from b2b_ai.features.document_management.routes import (
    _require_tenant,
    _sanitize_download_name,
    build_document_router,
)
from b2b_ai.features.document_management.service import (
    DocumentService,
    _reset_state,
)
from b2b_ai.features.document_management.storage import (
    LocalStorage,
    StorageBackendError,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_state()
    yield
    _reset_state()


@pytest.fixture()
def service(tmp_path):
    return DocumentService(kind="local", root=str(tmp_path / "docs"))


# ---------------------------------------------------------------------------
# 1. Path traversal rechazado (relative_to)
# ---------------------------------------------------------------------------

def test_localstorage_rejects_traversal_relative(tmp_path):
    st = LocalStorage(root=str(tmp_path / "storage"))
    # Atraviesa hacia fuera del root.
    with pytest.raises(StorageBackendError):
        st.save("../evil.bin", b"x")
    with pytest.raises(StorageBackendError):
        st.save("../../etc/passwd", b"x")
    with pytest.raises(StorageBackendError):
        st.read("../secret.bin")
    with pytest.raises(StorageBackendError):
        st.delete("../../outside.bin")


def test_localstorage_rejects_prefix_escape(tmp_path):
    """QA: con startswith, un directorio hermano con prefijo igual al root
    (root=/tmp/document_management, target=/tmp/document_management_evil)
    pasaba el check. Con relative_to se rechaza."""
    st = LocalStorage(root=str(tmp_path / "document_management"))
    # ../document_management_evil es HERMANO del root, no hijo.
    with pytest.raises(StorageBackendError):
        st.save("../document_management_evil/x.bin", b"x")


def test_localstorage_allows_legit_nested(tmp_path):
    st = LocalStorage(root=str(tmp_path / "storage"))
    path = st.save("T1/ab/abc123.bin", b"data")
    assert st.exists(path)
    assert st.read(path) == b"data"


# ---------------------------------------------------------------------------
# 2. Aislamiento multi-tenant
# ---------------------------------------------------------------------------

def test_service_tenant_isolation(service):
    doc_a = service.upload_document("TENANT_A", "factura.xml", b"<cfdi/>",
                                    category=DocumentCategory.CFDI)
    # El tenant B no ve el doc de A.
    with pytest.raises(KeyError):
        service.get_document("TENANT_B", doc_a.id)
    with pytest.raises(KeyError):
        service.read_document_bytes("TENANT_B", doc_a.id)
    with pytest.raises(KeyError):
        service.get_version_history("TENANT_B", doc_a.id)
    # search no filtra el doc de otro tenant.
    assert service.search_documents("TENANT_B") == []


def test_router_tenant_isolation(tmp_path):
    app = FastAPI()

    def _auth_a():
        return {"tenant_id": "TENANT_A", "user_id": "u-a"}

    app.include_router(build_document_router(db=None, require_api_key=lambda: _auth_a()))
    client_a = TestClient(app)

    _reset_state()

    up = client_a.post(
        "/api/v1/documents/upload",
        files={"file": ("fisc.txt", b"secreto-de-A", "text/plain")},
    )
    assert up.status_code == 200
    doc_id = up.json()["document"]["id"]

    # Otro cliente con auth que resuelve a otro tenant no puede leerlo.
    def _auth_b():
        return {"tenant_id": "TENANT_B", "user_id": "u-b"}

    app_b = FastAPI()
    app_b.include_router(build_document_router(db=None, require_api_key=lambda: _auth_b()))
    client_b = TestClient(app_b)

    assert client_b.get(f"/api/v1/documents/{doc_id}").status_code == 404
    assert client_b.get(f"/api/v1/documents/{doc_id}/content").status_code == 404


# ---------------------------------------------------------------------------
# 3. Sin tenant_id → 400 (nunca degrada a "default")
# ---------------------------------------------------------------------------

def test_require_tenant_raises_when_missing():
    with pytest.raises(HTTPException) as exc:
        _require_tenant({})
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        _require_tenant({"tenant_id": None})
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        _require_tenant({"tenant_id": ""})
    assert exc.value.status_code == 400


def test_require_tenant_returns_value():
    assert _require_tenant({"tenant_id": "T1"}) == "T1"


def test_router_rejects_missing_tenant(tmp_path):
    app = FastAPI()

    def _auth_no_tenant():
        return {"user_id": "u", "key": "k"}

    app.include_router(build_document_router(db=None, require_api_key=lambda: _auth_no_tenant()))
    client = TestClient(app)

    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.bin", b"data", "application/octet-stream")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4. Sanitización del nombre (Content-Disposition / header injection)
# ---------------------------------------------------------------------------

def test_sanitize_download_name_removes_dangerous_chars():
    out = _sanitize_download_name('evil"; inject="\r\nX-Injected')
    for ch in '"\'\r\n;':
        assert ch not in out
    assert _sanitize_download_name("../../etc/passwd") == "passwd"
    assert _sanitize_download_name("factura.pdf") == "factura.pdf"


def test_router_content_disposition_is_sanitized(tmp_path):
    app = FastAPI()

    def _auth():
        return {"tenant_id": "T1", "user_id": "u1"}

    app.include_router(build_document_router(db=None, require_api_key=lambda: _auth()))
    client = TestClient(app)
    _reset_state()

    evil_name = 'factura"\r\nX-Injected: yes.pdf'
    up = client.post(
        "/api/v1/documents/upload",
        files={"file": (evil_name, b"content", "application/pdf")},
    )
    assert up.status_code == 200
    doc_id = up.json()["document"]["id"]

    res = client.get(f"/api/v1/documents/{doc_id}/content")
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    # Sin CRLF ni comillas internas (solo las 2 comillas de encuadre del header).
    assert "\r" not in cd and "\n" not in cd
    assert cd.count('"') == 2


# ---------------------------------------------------------------------------
# 5. Persistencia real en DB
# ---------------------------------------------------------------------------

def test_persistence_survives_service_recreation(tmp_path):
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "docs.db"))
    root = str(tmp_path / "docs")
    s1 = DocumentService(db=db, kind="local", root=root)
    doc = s1.upload_document("T1", "persist.pdf", b"bytes", tags=["fiscal"])
    assert doc.version == 1

    # Simula reinicio: nueva instancia del servicio contra la MISMA base.
    s2 = DocumentService(db=db, kind="local", root=root)
    reloaded = s2.get_document("T1", doc.id)
    assert reloaded.name == "persist.pdf"
    assert reloaded.sha256 == doc.sha256
    assert reloaded.tags == ["fiscal"]
    assert s2.read_document_bytes("T1", doc.id) == b"bytes"


# ---------------------------------------------------------------------------
# 6. make_require_api_key devuelve dict
# ---------------------------------------------------------------------------

class _FakeAuth:
    def __init__(self, tenant=None):
        self._tenant = tenant

    def validate(self, key):
        return bool(key)

    def get_tenant_id(self, key):
        return self._tenant

    def get_user_id(self, key):
        return "u-1"


def test_require_api_key_returns_dict():
    """make_require_api_key inyecta el header X-API-Key y devuelve un dict."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    dep = make_require_api_key(_FakeAuth(tenant="T1"))
    app = FastAPI()

    @app.get("/_probe")
    def _probe(info: dict = Depends(dep)):
        return info

    client = TestClient(app)
    r = client.get("/_probe", headers={"X-API-Key": "secret-key"})
    assert r.status_code == 200, r.text
    info = r.json()
    assert isinstance(info, dict)
    assert info["tenant_id"] == "T1"
    assert info["user_id"] == "u-1"
    assert info["key"] == "secret-key"


def test_require_api_key_dict_has_tenant():
    """Sin tenant resuelto, el dep rechaza con 400 (nunca degrada a 'default')."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    dep = make_require_api_key(_FakeAuth(tenant=None))
    app = FastAPI()

    @app.get("/_probe")
    def _probe(info: dict = Depends(dep)):
        return info

    client = TestClient(app)
    r = client.get("/_probe", headers={"X-API-Key": "k"})
    # El dep (auth.py actual) rechaza keys sin tenant con 400.
    assert r.status_code == 400


def test_require_api_key_rejects_missing_key():
    """Sin header X-API-Key → 401 (no 422)."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    dep = make_require_api_key(_FakeAuth(tenant="T1"))
    app = FastAPI()

    @app.get("/_probe")
    def _probe(info: dict = Depends(dep)):
        return info

    client = TestClient(app)
    assert client.get("/_probe").status_code == 401


def test_require_api_key_rejects_invalid_key():
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    class _Reject:
        def validate(self, key):
            return False

        def get_tenant_id(self, key):
            return None

        def get_user_id(self, key):
            return None

    dep = make_require_api_key(_Reject())
    app = FastAPI()

    @app.get("/_probe")
    def _probe(info: dict = Depends(dep)):
        return info

    client = TestClient(app)
    assert client.get("/_probe", headers={"X-API-Key": "bad"}).status_code == 401
