# -*- coding: utf-8 -*-
"""
E2E integration + security audit del enterprise MVP.

Cubre:
  1. E2E full flow sobre la API (upload -> parse -> validate -> classify -> store -> report)
  2. Codigos HTTP (200, 400, 401, 404, 422)
  3. Aislamiento multi-tenant sobre la API
  4. Fallback LLM -> reglas (nivel pipeline)
  5. Security audit:
       - SQL injection en inputs de la API
       - Exposicion de archivos sensibles (.env, .db) via /static y rutas directas
       - Endpoints legacy sin autenticacion (fuga de datos)
"""
import glob
import os

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")

KEY_A = "tenant-a-secret-key-0001"
KEY_B = "tenant-b-secret-key-0002"


@pytest.fixture
def ctx(tmp_path):
    db = Database(str(tmp_path / "e2e.db"))
    ta = db.create_tenant("Despacho A", rfc="XAXX010101000")
    tb = db.create_tenant("Despacho B", rfc="XAXX010101001")
    db.create_api_key(ta, "key-a", KEY_A)
    db.create_api_key(tb, "key-b", KEY_B)
    app = create_app(db)
    return TestClient(app), db, ta, tb


def _all_fixtures():
    return sorted(glob.glob(os.path.join(FIXTURES, "*.xml")))


# --------------------------------------------------------------------------- #
# 1. E2E full flow
# --------------------------------------------------------------------------- #
def test_e2e_full_flow_7_cfdis(ctx):
    c, db, ta, _ = ctx
    h = {"X-API-Key": KEY_A}
    for f in _all_fixtures():
        with open(f, "rb") as fh:
            r = c.post("/api/v1/invoices/process",
                       headers=h,
                       files={"xml_file": (os.path.basename(f), fh, "text/xml")})
        assert r.status_code == 200, f
        res = r.json()["result"]
        assert res["insertado"] is True
        assert res["valido"] is True
        assert res["categoria"], f
        # FASE 2: los comprobantes de pago exigen aprobación humana (gate) y
        # NO registran póliza ERP hasta ser aprobados. El resto sí.
        if os.path.basename(f).startswith("07_"):
            assert res["erp_status"] == "pending_approval", f
            assert res["erp_poliza"] is None, f
        else:
            assert res["erp_poliza"], f

    # report / stats reflejan lo procesado
    st = c.get("/api/v1/stats", headers=h).json()
    assert st["total_facturas"] == 7
    # listado completo
    lst = c.get("/api/v1/invoices", headers=h).json()
    assert lst["count"] == 7
    # detalle de una
    inv_id = lst["invoices"][0]["id"]
    det = c.get(f"/api/v1/invoices/{inv_id}", headers=h)
    assert det.status_code == 200


def test_e2e_http_codes(ctx):
    c, db, ta, _ = ctx
    h = {"X-API-Key": KEY_A}
    bad = os.path.join(ROOT, "README.md")  # XML no-CFDI

    # 401 sin token
    assert c.get("/api/v1/stats").status_code == 401
    assert c.post("/api/v1/invoices/process").status_code == 401
    # 401 token invalido
    assert c.get("/api/v1/stats", headers={"X-API-Key": "wrong"}).status_code == 401
    # 200 con token valido
    assert c.get("/api/v1/stats", headers=h).status_code == 200
    # 400 body vacio / sin archivo
    assert c.post("/api/v1/invoices/process", headers=h).status_code == 400
    assert c.post("/api/v1/invoices/process", headers=h,
                  files={"xml_file": ("vacio.xml", b"", "text/xml")}).status_code == 400
    # 422 XML que no es CFDI valido (multipart) -> el pipeline lo rechaza
    with open(bad, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("readme.xml", fh, "text/xml")})
    assert r.status_code == 422
    # 404 xml_path inexistente
    assert c.post("/api/v1/invoices/process", headers=h,
                  json={"xml_path": "/no/existe.xml"}).status_code == 404


# --------------------------------------------------------------------------- #
# 3. Multi-tenant isolation
# --------------------------------------------------------------------------- #
def test_multi_tenant_aislamiento(ctx):
    c, db, ta, tb = ctx
    ha, hb = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}
    f1 = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
    f2 = os.path.join(FIXTURES, "01_gasto_operativo_papeleria.xml")

    # A sube una factura, B sube otra
    assert c.post("/api/v1/invoices/process", headers=ha,
                  json={"xml_path": f1}).status_code == 200
    assert c.post("/api/v1/invoices/process", headers=hb,
                  json={"xml_path": f2}).status_code == 200

    # A solo ve su factura
    la = c.get("/api/v1/invoices", headers=ha).json()
    assert la["count"] == 1 and la["tenant_id"] == ta
    assert la["invoices"][0]["categoria"] == "inversion"

    # B solo ve la suya
    lb = c.get("/api/v1/invoices", headers=hb).json()
    assert lb["count"] == 1 and lb["tenant_id"] == tb
    assert lb["invoices"][0]["categoria"] == "gasto_operativo"

    # A no puede leer el detalle de la factura de B (por id)
    id_b = lb["invoices"][0]["id"]
    r = c.get(f"/api/v1/invoices/{id_b}", headers=ha)
    assert r.status_code == 404

    # stats aislados
    assert c.get("/api/v1/stats", headers=ha).json()["total_facturas"] == 1
    assert c.get("/api/v1/stats", headers=hb).json()["total_facturas"] == 1

    # B NO puede forzar la vista de A con query param tenant_id: la key de
    # tenant fuerza su propio scope (regresión del IDOR).
    forced = c.get("/api/v1/invoices", headers=hb, params={"tenant_id": ta}).json()
    assert forced["tenant_id"] == tb
    assert forced["count"] == 1
    assert forced["invoices"][0]["categoria"] == "gasto_operativo"


# --------------------------------------------------------------------------- #
# 4. LLM fallback -> reglas
# --------------------------------------------------------------------------- #
def test_llm_fallback_reglas(ctx):
    """Con un cliente LLM que siempre falla, la clasificación cae a reglas."""
    from b2b_ai.services.llm import LLMService

    class FailingClient:
        def complete(self, messages, temperature=0.0, max_tokens=512):
            raise RuntimeError("boom")

    svc = LLMService(client=FailingClient())
    from b2b_ai.cfdi.parser import parse_cfdi
    f = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
    r = svc.classify_invoice(parse_cfdi(f))
    assert r["source"] == "rules"
    assert r["categoria"] == "inversion"

    # Y el tool que usa el pipeline (classify_cfdi) es determinístico/reglas.
    from b2b_ai.services.classify import classify_cfdi
    r2 = classify_cfdi(parse_cfdi(f))
    assert r2["categoria"] == "inversion"
    assert 0 <= r2["confianza"] <= 1


# --------------------------------------------------------------------------- #
# 5. Security audit — SQLi / path traversal / sensitive files
# --------------------------------------------------------------------------- #
def test_sql_injection_filters(ctx):
    c, db, ta, _ = ctx
    h = {"X-API-Key": KEY_A}
    f = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
    c.post("/api/v1/invoices/process", headers=h, json={"xml_path": f})

    payloads = [
        {"categoria": "'; DROP TABLE invoices;--"},
        {"categoria": "inversion' OR '1'='1"},
        {"fecha_desde": "' OR '1'='1"},
        {"fecha_desde": "2026-01-01'; DROP TABLE invoices;--"},
        {"tenant_id": "1 OR 1=1"},
    ]
    for p in payloads:
        r = c.get("/api/v1/invoices", headers=h, params=p)
        # No debe ser 500 ni exponer error SQL crudo
        assert r.status_code in (200, 422), (p, r.status_code)

    # la tabla sigue existiendo (no se inyecto DROP)
    assert db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name='invoices'").fetchone() is not None
    # y los datos siguen
    assert db.count_invoices(tenant_id=ta) == 1


def test_sensitive_files_no_expuestos(ctx):
    c, db, ta, _ = ctx
    for path in (".env", "b2b_ai.db", "/.env", "/b2b_ai.db",
                 "/static/.env", "/static/b2b_ai.db", "/static/../.env",
                 "/static/../../.env", "/.git/config"):
        r = c.get(path)
        assert r.status_code in (404, 403), (path, r.status_code)


def test_icons_path_traversal_bloqueado(ctx):
    c, db, ta, _ = ctx
    for p in ("/icons/../.env", "/icons/..%2F.env", "/icons/icon-192.png"):
        r = c.get(p)
        if p.endswith(".png"):
            assert r.status_code == 200
        else:
            assert r.status_code in (404, 403), p


# --------------------------------------------------------------------------- #
# 5b. Rate limiting (regresión del hallazgo de auditoría)
# --------------------------------------------------------------------------- #
def test_rate_limiting_devuelve_429(monkeypatch, tmp_path):
    """Con un límite bajo, excederlo devuelve 429 (antes: sin protección)."""
    monkeypatch.setenv("B2B_RATE_LIMIT_PER_MIN", "5")
    monkeypatch.setenv("B2B_RATE_LIMIT", "on")
    db = Database(str(tmp_path / "rl.db"))
    db.create_tenant("Despacho A")
    c = TestClient(create_app(db))

    codes = []
    for _ in range(8):
        codes.append(c.get("/api/v1/stats").status_code)  # sin key -> 401
    # las primeras 5 pasan (401); a partir del 6º, 429 (rate limited)
    assert codes[:5] == [401] * 5
    assert codes[5:] == [429] * 3

    # el healthcheck NO se limita
    assert c.get("/health").status_code == 200


def test_rate_limiting_desactivable(monkeypatch, tmp_path):
    """B2B_RATE_LIMIT=off desactiva el límite (para dev/CI)."""
    monkeypatch.setenv("B2B_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("B2B_RATE_LIMIT", "off")
    db = Database(str(tmp_path / "rl2.db"))
    c = TestClient(create_app(db))
    for _ in range(5):
        assert c.get("/api/v1/stats").status_code == 401


# --------------------------------------------------------------------------- #
# 5c. Legacy endpoints ya NO exponen datos sin auth
# --------------------------------------------------------------------------- #
def test_legacy_endpoints_protegidos(ctx):
    c, db, ta, _ = ctx
    # sin key -> 401 en todos
    for path in ("/invoices", "/stats", "/tools"):
        assert c.get(path).status_code == 401, path
    assert c.post("/process", json={"xml_path": "x.xml"}).status_code == 401
    # con key -> 200 (y el proceso devuelve 422 para XML inválido, no 500)
    h = {"X-API-Key": KEY_A}
    assert c.get("/invoices", headers=h).status_code == 200
    assert c.get("/stats", headers=h).status_code == 200
    bad = os.path.join(ROOT, "README.md")
    r = c.post("/process", headers=h, json={"xml_path": bad})
    assert r.status_code == 422
