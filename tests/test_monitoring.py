# -*- coding: utf-8 -*-
"""
Tests — monitoring: logging estructurado, métricas Prometheus, alertas y
health endpoint.

Cubre los 4 entregables de "monitoring + logging":
  1. logger.py   — JSON, niveles, request-id, contexto tenant/user, PII masking.
  2. metrics.py  — counters/gauges/summary + render Prometheus + negocio/custom.
  3. alerts.py   — reglas (error rate > 5%, latencia > 2s), canales, historial.
  4. health      — /health/detailed (DB, Redis, disco, memoria, uptime) + rutas.
"""
import io
import json
import logging
import os
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.monitoring.logger import JsonFormatter, mask_pii, request_context
from b2b_ai.monitoring.metrics import MetricsRegistry
from b2b_ai.monitoring.alerts import (AlertManager, WebhookChannel,
                                      EmailChannel, DEFAULT_RULES)
from b2b_ai.monitoring.health import build_health_detailed

API_KEY = "test-secret-key-123"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "fixtures", "cfdis", "02_inversion_consultoria.xml")


# --------------------------------------------------------------------------- #
# logger
# --------------------------------------------------------------------------- #
def _capture_logger():
    """Logger aislado con handler JSON a un buffer StringIO."""
    logger = logging.getLogger("test_capture_" + uuid.uuid4().hex[:8])
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger, buf


def test_logger_emite_json_con_niveles():
    log, buf = _capture_logger()
    log.info("mensaje info")
    log.warning("mensaje warning")
    log.error("mensaje error")
    log.debug("mensaje debug")
    log.critical("mensaje critical")
    lines = [json.loads(l) for l in buf.getvalue().strip().splitlines()]
    levels = {l["level"] for l in lines}
    assert {"INFO", "WARNING", "ERROR", "CRITICAL"} <= levels
    assert all("ts" in l and "message" in l and "logger" in l for l in lines)


def test_logger_request_context_y_tenant():
    log, buf = _capture_logger()
    with request_context(tenant_id=7, user_id="u_12"):
        log.info("factura procesada")
    line = json.loads(buf.getvalue().strip().splitlines()[0])
    assert line["request_id"]  # se genera automáticamente
    assert line["tenant_id"] == 7
    assert line["user_id"] == "u_12"


def test_request_context_ids_aislados_entre_requests():
    log, buf = _capture_logger()
    ids = []
    with request_context() as a:
        with request_context() as b:  # anidado: contexto interior gana
            log.info("inner")
    # cada request_context genera un id distinto
    assert a["request_id"] != b["request_id"]


def test_mask_pii_strings():
    assert mask_pii("contacto pedro@despacho.mx") == "contacto <email>"
    assert mask_pii("RFC XAXX010101000") == "RFC <rfc>"
    assert mask_pii("curp GODE561231HDFRRN09") == "curp <curp>"
    assert mask_pii("tarjeta 4111111111111111") == "tarjeta <card>"


def test_mask_pii_dict_por_clave_sensible():
    masked = mask_pii({"password": "s3cret", "api_key": "k", "nombre": "Juan",
                       "rfc": "XAXX010101000"})
    assert masked["password"] == "<redacted>"
    assert masked["api_key"] == "<redacted>"
    assert masked["rfc"] == "<redacted>"
    assert masked["nombre"] == "Juan"


def test_logger_masca_pii_en_extras():
    log, buf = _capture_logger()
    log.info("lead", extra={"extra_fields": {"email": "x@y.com",
                                             "rfc": "XAXX010101000"}})
    line = json.loads(buf.getvalue().strip().splitlines()[0])
    assert line["email"] == "<redacted>"
    assert line["rfc"] == "<redacted>"


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_metrics_operativas():
    m = MetricsRegistry()
    m.reset()
    m.record_request("/x", 200, 0.05)
    m.record_request("/x", 500, 0.1)
    snap = m.snapshot()
    assert snap["total_requests"] == 2
    assert snap["errors_5xx"] == 1
    assert snap["error_rate"] == 0.5
    assert snap["latency_ms_by_path"]["/x"]["count"] == 2


def test_metrics_negocio_y_custom():
    m = MetricsRegistry()
    m.reset()
    m.inc_invoices(2)
    m.inc_anomalies(3)
    m.set_tenant_usage([{"tenant_id": 1, "api_calls": 9, "invoices_processed": 4}])
    snap = m.snapshot()
    assert snap["invoices_processed"] == 2
    assert snap["anomalies_detected"] == 3
    assert snap["tenant_usage"][0]["tenant_id"] == "1"


def test_metrics_render_prometheus():
    m = MetricsRegistry()
    m.reset()
    m.record_request("/x", 200, 0.05)
    m.record_request("/x", 500, 0.1)
    m.inc_invoices(1)
    m.inc_anomalies(2)
    m.set_tenant_usage([{"tenant_id": 1, "api_calls": 9, "invoices_processed": 4}])
    text = m.render_prometheus()
    assert "# HELP b2b_requests_total" in text
    assert "# TYPE b2b_requests_total counter" in text
    assert 'b2b_requests_total{path="/x",status="500"} 1' in text
    assert 'b2b_invoices_processed_total 1' in text
    assert 'b2b_anomalies_detected_total 2' in text
    assert 'b2b_tenant_api_calls{tenant_id="1"} 9' in text
    assert 'b2b_request_duration_seconds{path="/x"} p95=' in text


# --------------------------------------------------------------------------- #
# alerts
# --------------------------------------------------------------------------- #
def test_alert_error_rate_fire_y_cooldown():
    am = AlertManager()
    am.reset()
    for _ in range(10):
        am.record_http(500, 0.001)
    fired = am.evaluate()
    assert any(a.rule_name == "error_rate" for a in fired)
    # cooldown: mismo estado no re-dispara
    assert am.evaluate() == []


def test_alert_error_rate_cleared_al_recuperarse():
    am = AlertManager()
    am.reset()
    for _ in range(10):
        am.record_http(500, 0.001)
    am.evaluate()
    # suficiente tráfico OK para bajar la tasa por debajo de 5%
    for _ in range(200):
        am.record_http(200, 0.001)
    am.evaluate()
    cleared = [a for a in am.history if a.status == "cleared"]
    assert any(a.rule_name == "error_rate" for a in cleared)


def test_alert_latencia_p95():
    am = AlertManager()
    am.reset()
    for _ in range(50):
        am.record_http(200, 5.0)  # 5s -> p95 > 2s
    fired = am.evaluate()
    assert any(a.rule_name == "latency_p95" for a in fired)


def test_alert_historial():
    am = AlertManager()
    am.reset()
    for _ in range(10):
        am.record_http(500, 0.001)
    am.evaluate()
    hist = am.alert_history()
    assert hist and hist[0]["status"] == "triggered"
    assert hist[0]["severity"] == "warning"


def test_email_channel_mock_no_falla():
    ch = EmailChannel()
    alert = am_fake_alert()
    assert ch.send(alert) is True


def test_webhook_channel_envia_json():
    import http.server
    import socketserver

    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = self.rfile.read(length)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        port = srv.server_address[1]
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        ch = WebhookChannel("http://127.0.0.1:%d/hook" % port)
        assert ch.send(am_fake_alert()) is True
        t.join(timeout=3)
    payload = json.loads(received["body"])
    assert payload["rule"] == "error_rate"
    assert payload["status"] == "triggered"


def test_webhook_channel_urla_invalida_retorna_false():
    ch = WebhookChannel("http://127.0.0.1:1/hook")  # puerto cerrado -> refusa
    assert ch.send(am_fake_alert()) is False


def am_fake_alert():
    from b2b_ai.monitoring.alerts import Alert
    return Alert("error_rate", "warning", "demo", 0.5, 0.05, status="triggered")


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #
def test_health_detailed_db_y_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    db = Database(":memory:", migrate=True)
    h = build_health_detailed(db)
    assert h["status"] in ("ok", "degraded")
    assert h["db"]["status"] == "ok"
    assert h["db"]["schema_version"] >= 1
    assert h["redis"]["status"] == "not_configured"
    assert h["disk"]["status"] in ("ok", "warning")
    assert h["disk"]["percent"] is not None
    assert "memory" in h
    assert "uptime_seconds" in h
    assert h["process"]["pid"] == os.getpid()
    assert "degraded_components" in h


# --------------------------------------------------------------------------- #
# API endpoints
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _h():
    return {"X-API-Key": API_KEY}


def test_health_detailed_endpoint(client):
    c, db = client
    r = c.get("/health/detailed")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] in ("ok", "degraded")
    assert j["db"]["status"] == "ok"
    assert j["redis"]["status"] == "not_configured"
    assert "disk" in j and "memory" in j and "uptime_seconds" in j


def test_metrics_prometheus_endpoint(client):
    c, db = client
    r = c.get("/metrics/prometheus")
    assert r.status_code == 200
    body = r.text
    assert "# HELP b2b_requests_total" in body
    assert "# TYPE b2b_requests_total counter" in body


def test_business_metrics_incrementa_al_procesar(client):
    c, db = client
    from b2b_ai.monitoring.metrics import metrics as pm
    before = pm.snapshot()["invoices_processed"]
    with open(FIXTURE, "rb") as f:
        r = c.post("/api/v1/invoices/process", headers=_h(),
                   files={"xml_file": ("f.xml", f, "application/xml")})
    assert r.status_code == 200
    after = pm.snapshot()["invoices_processed"]
    assert after > before


def test_metrics_legacy_sigue_funcionando(client):
    c, db = client
    r = c.get("/metrics")
    assert r.status_code == 200
    assert "total_requests" in r.json()
