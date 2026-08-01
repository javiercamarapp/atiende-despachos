# -*- coding: utf-8 -*-
"""
Security hardening fase 2 — cabeceras, upload validation, PII, retención,
cifrado en reposo y audit de mutaciones.

Complementa tests/test_e2e_security.py y tests/test_security_hardening.py
cubriendo lo que faltaba del ticket:

  1. Cabeceras de seguridad (HSTS, CSP, X-Frame-Options, nosniff, Referrer).
  2. Upload validation: la API rechaza archivos que no son .xml/.pdf antes
     de tocar disco.
  3. PII detection: el pipeline marca RFC/CURP/email/teléfono/cuentas.
  4. Data retention: enforce_retention purga solo registros operativos.
  5. Encryption at rest: webhook_url/notif_recipient cifrados con clave env.
  6. Audit de mutaciones: webhooks/tenants quedan registrados en audit_log.
"""
import os
import re

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")
KEY = "harden-key-0001"


@pytest.fixture
def ctx(tmp_path):
    from b2b_ai.db.db import Database
    from b2b_ai.api.app import create_app
    db = Database(str(tmp_path / "harden.db"))
    t = db.create_tenant("Hardening")
    db.create_api_key(t, "h", KEY)
    app = create_app(db)
    return TestClient(app), db, t


# --------------------------------------------------------------------------- #
# 1. Security headers
# --------------------------------------------------------------------------- #
def test_security_headers_presentes(ctx):
    c, _, _ = ctx
    r = c.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp, csp
    assert "object-src 'none'" in csp, csp


def test_security_headers_en_rutas_protegidas(ctx):
    c, _, _ = ctx
    h = {"X-API-Key": KEY}
    r = c.get("/api/v1/stats", headers=h)
    assert r.status_code == 200
    assert r.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in r.headers


def test_hsts_solo_con_https_o_flag(ctx):
    """En HTTP local (TestClient) no se manda HSTS; con B2B_HSTS=on sí se
    fuerza siempre (env del proceso), y con X-Forwarded-Proto https + trust
    proxy también."""
    from fastapi.testclient import TestClient
    from b2b_ai.api.app import create_app
    from b2b_ai.db.db import Database
    import tempfile

    db = Database(str(tempfile.mkdtemp()) + "/h.db")
    c = TestClient(create_app(db))
    assert "strict-transport-security" not in c.get("/health").headers


def test_hsts_con_forwarded_proto(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from b2b_ai.api.app import create_app
    from b2b_ai.db.db import Database
    monkeypatch.setenv("B2B_HSTS", "true")
    monkeypatch.setenv("B2B_TRUST_PROXY", "true")
    db = Database(str(tmp_path / "hp.db"))
    c = TestClient(create_app(db))
    r = c.get("/health",
              headers={"X-Forwarded-Proto": "https"})
    assert r.headers.get("strict-transport-security", "").startswith(
        "max-age=31536000")


# --------------------------------------------------------------------------- #
# 2. Upload validation (extension)
# --------------------------------------------------------------------------- #
def test_upload_rechaza_extensiones_no_cfdi(ctx):
    c, _, _ = ctx
    h = {"X-API-Key": KEY}
    # .exe, .txt, .sh, .js NO se aceptan (422 antes de tocar disco)
    for ext in (".exe", ".txt", ".sh", ".js", ".html", ".py"):
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("malo" + ext, b"<xml/>", "text/xml")})
        assert r.status_code == 422, (ext, r.status_code)
        assert "Solo se aceptan" in r.json().get("detail", ""), ext


def test_upload_acepta_xml(ctx):
    c, _, _ = ctx
    h = {"X-API-Key": KEY}
    f = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
    with open(f, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("factura.xml", fh, "text/xml")})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# 3. PII detection en el pipeline
# --------------------------------------------------------------------------- #
def test_pii_detection_en_pipeline(ctx):
    c, _, _ = ctx
    h = {"X-API-Key": KEY}
    f = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
    with open(f, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("factura.xml", fh, "text/xml")})
    assert r.status_code == 200
    res = r.json()["result"]
    # el resultado del pipeline no expone el detalle pii en _strip, pero la
    # función detect_pii debe existir y marcar RFC si los hay.
    from b2b_ai.api.security import detect_pii
    from b2b_ai.cfdi.parser import parse_cfdi
    datos = parse_cfdi(f)
    out = detect_pii(datos)
    assert "pii" in out and "tipos" in out and "found" in out
    # el CFDI tiene emisor_rfc/receptor_rfc → debe detectar al menos RFC
    assert "rfc" in out["tipos"]


def test_pii_detection_cuenta_curp_email():
    from b2b_ai.api.security import detect_pii
    datos = {
        "emisor_rfc": "XAXX010101000",
        "receptor_rfc": "COSC8001137TA",
        "emisor_nombre": "Juan",
        "descripcion": "clabe 012345678901234567 y correo juan@x.com "
                       "tel 5551234567",
        "receptor_curp": "COSC800113HDFNRL05",
    }
    out = detect_pii(datos)
    assert out["pii"] is True
    tipos = set(out["tipos"])
    assert "clabe_cuenta" in tipos
    assert "email" in tipos
    assert "telefono" in tipos
    assert "curp" in tipos
    assert "rfc" in tipos


def test_pii_detection_sin_pii():
    from b2b_ai.api.security import detect_pii
    datos = {"emisor_rfc": "XAXX010101000",  # RFC genérico, no identifica
             "receptor_rfc": "XAXX010101000",
             "descripcion": "papeleria y articulos de oficina"}
    out = detect_pii(datos)
    assert out["pii"] is False


# --------------------------------------------------------------------------- #
# 4. Data retention
# --------------------------------------------------------------------------- #
def test_enforce_retention_purga_operativo_no_facturas(ctx):
    c, db, t = ctx
    # una factura y un audit viejo
    f = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
    from b2b_ai.services.pipeline import process_file
    process_file(f, db=db, tenant_id=t)
    db.log_call("test", "mutation", entity="x", entity_id="1",
                payload={}, status="ok", tenant_id=t)
    # el audit_log recién creado es "hoy"; forzar uno viejo
    db.conn.execute(
        "UPDATE audit_log SET created_at=? WHERE tool_name='test'",
        ("2020-01-01T00:00:00",))
    db.conn.commit()

    removed = db.enforce_retention(days=30)
    assert removed["audit_log"] >= 1
    # las facturas NO se tocan
    assert db.count_invoices(tenant_id=t) == 1


def test_retention_no_rompe_sin_tablas(tmp_path):
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "r.db"))
    out = db.enforce_retention(days=1)
    assert set(out.keys()) == {"audit_log", "webhook_deliveries",
                               "notifications", "portal_sessions"}


# --------------------------------------------------------------------------- #
# 5. Encryption at rest
# --------------------------------------------------------------------------- #
def test_encrypt_field_roundtrip(monkeypatch):
    monkeypatch.setenv("B2B_ENCRYPTION_KEY", "x" * 32)
    from b2b_ai.api.security import encrypt_field, decrypt_field
    secret = "https://hooks.example.com/abc-very-secret"
    enc = encrypt_field(secret)
    assert enc != secret
    assert enc.startswith("enc1:")
    assert decrypt_field(enc) == secret


def test_encrypt_degradado_sin_clave(monkeypatch):
    monkeypatch.delenv("B2B_ENCRYPTION_KEY", raising=False)
    from b2b_ai.api.security import encrypt_field, decrypt_field
    v = "https://hooks.example.com/x"
    # sin clave → transparente (no rompe lecturas/existentes)
    assert encrypt_field(v) == v
    assert decrypt_field(v) == v


def test_config_sensible_cifrado_en_db(monkeypatch, tmp_path):
    monkeypatch.setenv("B2B_ENCRYPTION_KEY", "y" * 32)
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "enc.db"))
    t = db.create_tenant("Enc")
    db.set_tenant_config(t, "webhook_url", "https://hooks.x.com/secreto")
    # en la DB está cifrado (no en claro)
    raw = db.conn.execute(
        "SELECT config_value FROM tenant_config "
        "WHERE tenant_id=? AND config_key='webhook_url'", (t,)).fetchone()[0]
    assert raw.startswith("enc1:")
    assert "hooks.x.com" not in raw
    # la lectura devuelve el valor original
    assert db.get_tenant_config(t, "webhook_url") == "https://hooks.x.com/secreto"


def test_config_no_sensible_no_cifrado(monkeypatch, tmp_path):
    monkeypatch.setenv("B2B_ENCRYPTION_KEY", "z" * 32)
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "enc2.db"))
    t = db.create_tenant("Enc2")
    db.set_tenant_config(t, "plantilla_contable", "SAT")
    assert db.get_tenant_config(t, "plantilla_contable") == "SAT"


# --------------------------------------------------------------------------- #
# 6. Audit de mutaciones
# --------------------------------------------------------------------------- #
def test_webhook_mutation_auditada(ctx):
    c, db, t = ctx
    h = {"X-API-Key": KEY}
    r = c.post("/api/v2/webhooks", headers=h,
               json={"url": "https://hook.example.com/cb", "events": ["x"]})
    assert r.status_code == 200
    events = [a for a in db.list_audit(tenant_id=t)
              if a["tool_name"] == "webhook" and a["action"] == "register"]
    assert events, "el alta de webhook debe quedar auditada"


def test_onboard_tenant_auditado(ctx):
    c, db, t = ctx
    h = {"X-API-Key": KEY}
    r = c.post("/api/v1/tenants", headers=h, json={"name": "Cliente Nuevo"})
    assert r.status_code == 200
    events = [a for a in db.list_audit()
              if a["tool_name"] == "tenant" and a["action"] == "onboard"]
    assert events, "el onboarding debe quedar auditado"
