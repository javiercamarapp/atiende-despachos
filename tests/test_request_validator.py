# -*- coding: utf-8 -*-
"""Tests para b2b_ai.middleware.request_validator — Content-Type, tamaño,
detección de SQL injection y XSS.

Cubre:
  - Funciones de detección (stateless) para SQLi y XSS.
  - Middleware: Content-Type inválido (415), cuerpo demasiado grande (413),
    payload sospechoso (422), rutas exentas, body binario (uploads).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.middleware.request_validator import (
    detect_sql_injection,
    detect_xss,
    install_request_validator,
    validate_content_type,
)


# ---------------------------------------------------------------------------
# Detección SQL injection
# ---------------------------------------------------------------------------
class TestDetectSQLInjection:
    def test_union_select(self):
        assert detect_sql_injection("' UNION SELECT password FROM users--") \
            == "union_select"

    def test_clean_text(self):
        assert detect_sql_injection("Hola, ¿cómo estás?") is None
        assert detect_sql_injection("SELECT * FROM ventas") is None  # no patrón
        assert detect_sql_injection("") is None

    def test_or_equals(self):
        assert detect_sql_injection("' OR 1=1 --") == "or_1_equals_1"

    def test_stacked_query(self):
        assert detect_sql_injection("x; DROP TABLE invoices;") == "stacked_queries"

    def test_comment(self):
        assert detect_sql_injection("1=1--") == "comments"

    def test_sleep(self):
        assert detect_sql_injection("SLEEP(5)") == "sleep_benchmark"


# ---------------------------------------------------------------------------
# Detección XSS
# ---------------------------------------------------------------------------
class TestDetectXSS:
    def test_script_tag(self):
        assert detect_xss("<script>alert(1)</script>") == "script_tag"

    def test_clean_text(self):
        assert detect_xss("texto normal sin nada raro") is None

    def test_event_handler(self):
        assert detect_xss("<img onerror=alert(1)>") == "event_handler"

    def test_javascript_proto(self):
        assert detect_xss("<a href=javascript:alert(1)>x</a>") == "javascript_proto"

    def test_iframe(self):
        assert detect_xss("<iframe src=x></iframe>") == "iframe_object"


# ---------------------------------------------------------------------------
# validate_content_type (unit)
# ---------------------------------------------------------------------------
class TestValidateContentType:
    def _req(self, method, ct):
        from starlette.requests import Request
        from starlette.datastructures import Headers
        scope = {
            "type": "http", "method": method, "path": "/x",
            "headers": Headers({"content-type": ct}).raw,
        }
        return Request(scope)

    def test_allows_json(self):
        assert validate_content_type(self._req("POST", "application/json")) is None

    def test_allows_multipart(self):
        assert validate_content_type(self._req("POST", "multipart/form-data")) is None

    def test_rejects_unknown(self):
        assert validate_content_type(self._req("POST", "text/html")) is not None

    def test_ignores_get(self):
        assert validate_content_type(self._req("GET", "text/html")) is None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
def _build_app(max_bytes=None, scan=True):
    app = FastAPI()

    @app.post("/api/echo")
    async def echo():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": "healthy"}

    install_request_validator(app, max_bytes=max_bytes, enable_content_scan=scan)
    return TestClient(app)


class TestRequestValidationMiddleware:
    def test_normal_json_passes(self):
        client = _build_app()
        r = client.post("/api/echo", json={"a": 1})
        assert r.status_code == 200

    def test_invalid_content_type_415(self):
        client = _build_app()
        r = client.post(
            "/api/echo",
            content="<html></html>",
            headers={"Content-Type": "text/html"},
        )
        assert r.status_code == 415
        assert "Unsupported Content-Type" in r.json()["detail"]

    def test_body_too_large_413(self):
        client = _build_app(max_bytes=1024)  # 1KB para el test
        r = client.post(
            "/api/echo",
            content=b"x" * 2048,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 413
        assert "too large" in r.json()["detail"].lower()

    def test_exact_limit_passes(self):
        client = _build_app(max_bytes=1024)
        r = client.post(
            "/api/echo",
            content=b"x" * 1024,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 200

    def test_sqli_body_rejected_422(self):
        client = _build_app()
        r = client.post(
            "/api/echo",
            json={"query": "' UNION SELECT password FROM users--"},
        )
        assert r.status_code == 422
        assert any("SQL" in e for e in r.json()["detail"])

    def test_xss_body_rejected_422(self):
        client = _build_app()
        r = client.post(
            "/api/echo",
            json={"comment": "<script>alert(1)</script>"},
        )
        assert r.status_code == 422
        assert any("script" in e.lower() for e in r.json()["detail"])

    def test_binary_upload_passes(self):
        # Un upload binario (PDF/XLSX) no debe disparar falso positivo ni 422.
        client = _build_app()
        r = client.post(
            "/api/echo",
            content=bytes([0x25, 0x50, 0x44, 0x46, 0x00, 0xFF, 0xFE]) * 20,
            headers={"Content-Type": "application/pdf"},
        )
        assert r.status_code == 200

    def test_health_exempt(self):
        client = _build_app()
        assert client.get("/health").status_code == 200

    def test_get_with_body_content_type_not_rejected(self):
        # Un GET con Content-Type raro no debe ser rechazado por validate_ct.
        client = _build_app()
        r = client.get("/health", headers={"Content-Type": "text/html"})
        assert r.status_code == 200

    def test_scan_disabled_allows_sqli(self):
        client = _build_app(scan=False)
        r = client.post(
            "/api/echo",
            json={"q": "' UNION SELECT 1--"},
        )
        assert r.status_code == 200
