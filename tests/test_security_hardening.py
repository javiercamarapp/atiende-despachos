# -*- coding: utf-8 -*-
"""
Security hardening — XSS, auth bypass y secrets scan.

Complementa tests/test_e2e_security.py (SQLi, path traversal, rate limiting,
protección de endpoints legacy) con lo que faltaba del ticket:

  1. XSS: payloads maliciosos en campos de facturas/leads no deben ejecutarse
     ni reflejarse crudos en la salida del dashboard / stats / listado.
  2. Auth bypass: métodos alternativos (query string, cookies, headers
     inventados) no deben autenticar sin X-API-Key válida.
  3. Secrets scan: archivos con secretos conocidos (api keys, passwords,
     tokens) no deben existir versionados en el repo ni servirse vía web.
"""
import glob
import os
import re

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")

KEY = "sec-tenant-key-0001"
XSS = "<script>alert(1)</script>"


@pytest.fixture
def ctx(tmp_path):
    from b2b_ai.db.db import Database
    from b2b_ai.api.app import create_app
    db = Database(str(tmp_path / "sec.db"))
    t = db.create_tenant("Despacho Seguro")
    db.create_api_key(t, "sec", KEY)
    app = create_app(db)
    return TestClient(app), db, t


# --------------------------------------------------------------------------- #
# 1. XSS
# --------------------------------------------------------------------------- #
def _inject_xss_invoice(db, t):
    """Inserta una factura con payloads XSS en emisor_nombre y categoria
    (escenario de datos almacenados que llegan a la UI del dashboard)."""
    db.insert_invoice(
        t,
        {"folio_fiscal": "XSS-1", "archivo": "x.xml", "fecha": "2026-07-01",
         "emisor_rfc": "XAXX010101000",
         "emisor_nombre": "</script><script>alert(1)</script>",
         "subtotal": "100", "total": "116"},
        {"categoria": '<img src=x onerror=alert(2)>',
         "confianza": 0.9, "razon": ""},
        {"ok": True})


def test_xss_no_script_breakout_en_dashboard_html(ctx):
    """El JSON embebido en el <script> del dashboard escapa < > para impedir
    que un payload almacenado cierre el bloque <script> y ejecute JS."""
    c, db, t = ctx
    _inject_xss_invoice(db, t)
    html = c.get("/api/v1/dashboard", headers={"X-API-Key": KEY}).text

    # el payload NO debe aparecer como cierre de script + script nuevo
    assert "</script><script>" not in html
    assert "alert(1)</script>" not in html
    # los '<' del payload almacenado deben ir escapados en el literal JS
    assert "\\u003cscript>" in html or "\\u003c" in html


def test_xss_innerhtml_escaped_en_dashboard(ctx):
    """El código del dashboard debe escapar (esc()) los campos que inyecta
    por innerHTML (categoría, mes, folio, emisor, vía)."""
    src = open(os.path.join(ROOT, "b2b_ai", "api", "dashboard.py"),
               encoding="utf-8").read()
    # la función esc() existe y se usa en bars() (categoría/mes) y en la
    # tabla de conciliación (folio/emisor/vía)
    assert "function esc(" in src
    assert "esc(r[lblKey])" in src
    assert "esc(x.folio_fiscal)" in src
    assert "esc(x.emisor)" in src
    # el patrón inseguro de concatenar el campo crudo sin esc debe estar
    # eliminado en la asignación a innerHTML de bars()
    assert "'<div class=\"legend\">'+r[lblKey]" not in src


def test_xss_json_no_servido_como_html(ctx):
    """Los endpoints que devuelven datos almacenados responden application/json
    (no text/html), así un navegador no puede renderizarlos como página y
    ejecutar el payload."""
    c, db, t = ctx
    _inject_xss_invoice(db, t)
    h = {"X-API-Key": KEY}
    for path in ("/api/v1/dashboard/data", "/api/v1/stats",
                 "/api/v1/invoices"):
        r = c.get(path, headers=h)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert ct.startswith("application/json"), (path, ct)


def test_xss_leads_no_almacenan_html(ctx):
    """El endpoint público de leads debe rechazar o neutralizar payloads XSS."""
    c, _, _ = ctx
    # con XSS en email -> 422 (validación de campo obligatorio no puede pasar)
    r = c.post("/api/v1/leads",
               json={"nombre": "Juan", "email": XSS})
    # el sistema no debe devolver 500 ni reflejar el script en su respuesta
    assert r.status_code in (200, 422)
    assert "<script>" not in r.text


# --------------------------------------------------------------------------- #
# 2. Auth bypass
# --------------------------------------------------------------------------- #
def test_auth_bypass_medios_alternativos(ctx):
    c, db, t = ctx
    # key vía query string -> NO debe autenticar
    assert c.get("/api/v1/stats", params={"X-API-Key": KEY}).status_code == 401
    # key vía cookie -> NO
    assert c.get("/api/v1/stats", cookies={"X-API-Key": KEY}).status_code == 401
    # header inventado -> NO
    assert c.get("/api/v1/stats",
                 headers={"Authorization": f"Bearer {KEY}"}).status_code == 401
    # header con key + comillas / espacios -> NO (se compara hash exacto)
    assert c.get("/api/v1/stats",
                 headers={"X-API-Key": f" {KEY} "}).status_code == 401
    # key vacía -> NO
    assert c.get("/api/v1/stats", headers={"X-API-Key": ""}).status_code == 401
    # POST con key en body -> NO
    assert c.post("/api/v1/invoices/process",
                  json={"xml_path": "x.xml", "X-API-Key": KEY}).status_code == 401

    # la única forma que autentica es el header exacto
    assert c.get("/api/v1/stats", headers={"X-API-Key": KEY}).status_code == 200


# --------------------------------------------------------------------------- #
# 3. Secrets scan
# --------------------------------------------------------------------------- #
# Patrones de secretos de alto riesgo. Solo literales con valor real: el
# patrón genérico exige un string entre comillas tras el '=' (evita los
# falsos positivos de asignaciones a identificadores/funciones como
# `self.password = password` o `api_key = self._issue_api_key(...)`).
_HIGH_RISK = [
    # literal de secret con >= 12 caracteres entre comillas
    re.compile(r"(?i)(api[_-]?key|secret|password|passwd|token|credential)\s*[:=]\s*['\"][A-Za-z0-9_\-\.\/+=!@#$%^&*]{12,}['\"]"),
    re.compile(r"(?i)sk-[A-Za-z0-9]{20,}"),        # OpenAI-style
    re.compile(r"(?i)AKIA[0-9A-Z]{16}"),            # AWS access key
    re.compile(r"(?i)-----BEGIN (RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(r"(?i)gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"(?i)eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),  # JWT
]


def test_secrets_scan_repo(tmp_path):
    """Escanea el código del repo en busca de secretos hardcodeados."""
    # busca los .py del paquete y los scripts (no fixtures ni landing vendor)
    targets = (glob.glob(os.path.join(ROOT, "b2b_ai", "**", "*.py"), recursive=True)
               + glob.glob(os.path.join(ROOT, "scripts", "*.py"))
               + glob.glob(os.path.join(ROOT, "*.py")))
    hits = []
    for path in targets:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
        except OSError:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            # ignora líneas que son claramente ejemplos/placeholders de docs
            if any(x in line for x in ("example.com", "EXAMPLE", "PLACEHOLDER",
                                       "xxxx", "your-", "TU_", "YOUR_", "<secret>",
                                       "Mock", "mock", "MOCK")):
                continue
            for rx in _HIGH_RISK:
                if rx.search(line):
                    hits.append((path, i, line.strip()))
                    break
    assert hits == [], f"Secretos potenciales encontrados:\n" + "\n".join(
        f"{p}:{ln}: {l}" for p, ln, l in hits)


def test_secrets_scan_no_servidos_via_web(ctx):
    """Los archivos de entorno / DB no se sirven por HTTP."""
    c, _, _ = ctx
    for path in (".env", ".env.example", "b2b_ai.db",
                 "/static/.env", "/static/b2b_ai.db"):
        r = c.get(path)
        assert r.status_code in (404, 403), (path, r.status_code)


def test_env_example_no_contiene_valores_reales(ctx):
    """.env.example solo documenta nombres, nunca secretos con valor."""
    env_path = os.path.join(ROOT, ".env.example")
    assert os.path.exists(env_path)
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # formato KEY=VAL: el VAL no debe ser un secreto con 16+ caracteres
            if "=" in line:
                k, _, v = line.partition("=")
                if len(v) >= 16 and not any(x in v for x in ("YOUR_", "xxx", "<", "example")):
                    pytest.fail(f"Secret potencial en .env.example: {line}")
