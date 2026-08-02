# -*- coding: utf-8 -*-
"""test_audit_logger.py — Tests del sistema de audit logging (AuditLogger).

Cubre:
  - Modelo: AuditEvent y AuditLog (who/what/when/where/result).
  - Logger: escritura async no-bloqueante, persistencia estructurada JSON,
    eventos por conveniencia, configuración (enabled_events, retention),
    flush síncrono y consulta con filtros.
  - Routes: GET /api/v1/audit/logs con filtros y aislamiento por tenant.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def audit_db(tmp_path):
    from b2b_ai.db.db import Database
    return Database(str(tmp_path / "audit_logger_test.db"))


@pytest.fixture
def logger(audit_db):
    from b2b_ai.audit.logger import AuditLogger
    lgr = AuditLogger(audit_db, auto_start=True)
    yield lgr
    lgr.stop()


# ---- Models ---------------------------------------------------------------

class TestAuditEvent:
    def test_members(self):
        from b2b_ai.audit.models import AuditEvent
        expected = {
            "login", "logout", "tenant.create", "tenant.update",
            "tenant.delete", "cfdi.upload", "cfdi.process",
            "declaration.submit", "billing.change", "webhook.config.change",
        }
        assert {e.value for e in AuditEvent} == expected
        assert len(AuditEvent) == 10

    def test_normalize_event(self):
        from b2b_ai.audit.models import AuditEvent, normalize_event
        assert normalize_event(AuditEvent.LOGIN) == "login"
        assert normalize_event("cfdi.process") == "cfdi.process"


class TestAuditLog:
    def test_to_dict_structure(self):
        from b2b_ai.audit.models import AuditLog
        e = AuditLog(actor="alice", event="login", tenant_id=7,
                     resource="auth", result="success", ip="1.2.3.4")
        d = e.to_dict()
        for key in ("actor", "tenant_id", "event", "resource",
                    "resource_id", "result", "details", "ip", "timestamp"):
            assert key in d

    def test_from_row_structured_details(self):
        from b2b_ai.audit.models import AuditLog
        row = {
            "id": 1, "user_id": "alice", "tenant_id": 7, "action": "login",
            "resource": "auth", "resource_id": None, "ip": "1.2.3.4",
            "timestamp": "2025-01-01T00:00:00",
            "details": json.dumps({"result": "failure", "details": {"mfa": "denied"}}),
        }
        e = AuditLog.from_row(row)
        assert e.actor == "alice"
        assert e.event == "login"
        assert e.result == "failure"
        assert e.details == {"mfa": "denied"}

    def test_from_row_plain_details(self):
        from b2b_ai.audit.models import AuditLog
        row = {
            "id": 2, "user_id": "bob", "tenant_id": 1, "action": "cfdi.upload",
            "resource": "cfdi", "resource_id": "x", "ip": None,
            "timestamp": None, "details": json.dumps({"file": "cfdi.xml"}),
        }
        e = AuditLog.from_row(row)
        assert e.event == "cfdi.upload"
        assert e.result == "success"
        assert e.details == {"file": "cfdi.xml"}


# ---- AuditLogger -----------------------------------------------------------

class TestAuditLoggerWrite:
    def test_log_login_persists(self, logger):
        logger.login(actor="alice@x.io", tenant_id=1, ip="10.0.0.1")
        logger.flush()
        rows = logger.query(tenant_id=1)
        assert len(rows) == 1
        e = rows[0]
        assert e.event == "login"
        assert e.actor == "alice@x.io"
        assert e.ip == "10.0.0.1"
        assert e.result == "success"
        assert e.timestamp  # when presente

    def test_structured_details_roundtrip(self, logger):
        logger.cfdi_processed(actor="sys", tenant_id=3,
                              resource_id="CFDI42",
                              details={"status": "ok", "issues": []},
                              result="success")
        logger.flush()
        e = logger.query(tenant_id=3, event="cfdi.process")[0]
        assert e.resource_id == "CFDI42"
        assert e.result == "success"
        assert e.details == {"status": "ok", "issues": []}

    def test_event_convenience_methods(self, logger):
        logger.login("u1", 1)
        logger.logout("u1", 1)
        logger.tenant_created("admin", 2, resource_id="2")
        logger.tenant_updated("admin", 2, resource_id="2")
        logger.tenant_deleted("admin", 2, resource_id="2")
        logger.cfdi_uploaded("u1", 1, resource_id="C1")
        logger.declaration_submitted("u1", 1, resource_id="D1")
        logger.billing_changed("u1", 1, resource_id="B1")
        logger.webhook_config_changed("u1", 1, resource_id="W1")
        logger.flush()
        assert len(logger.query()) >= 9

    def test_result_failure(self, logger):
        logger.login("u1", 1, result="failure", details={"reason": "bad pw"})
        logger.flush()
        e = logger.query(tenant_id=1, event="login")[0]
        assert e.result == "failure"
        assert e.details == {"reason": "bad pw"}

    def test_non_blocking_no_crash(self, logger):
        # Encolar y no esperar: el request no debe latir.
        for i in range(20):
            logger.login(f"u{i}", 1)
        logger.flush()
        assert len(logger.query(tenant_id=1)) == 20


class TestAuditLoggerConfig:
    def test_enabled_events_filters(self, audit_db):
        from b2b_ai.audit.logger import AuditLogger
        lgr = AuditLogger(audit_db, enabled_events=["login"], auto_start=True)
        lgr.login("u1", 1)                 # permitido
        lgr.cfdi_uploaded("u1", 1)         # descartado
        lgr.flush()
        rows = lgr.query(tenant_id=1)
        assert len(rows) == 1
        assert rows[0].event == "login"
        lgr.stop()

    def test_disabled_event_not_logged(self, audit_db):
        from b2b_ai.audit.logger import AuditLogger
        lgr = AuditLogger(audit_db, enabled_events=set(), auto_start=True)
        lgr.login("u1", 1)
        lgr.flush()
        assert len(lgr.query()) == 0
        lgr.stop()

    def test_retention_prune(self, logger):
        # Entrada vieja (más de 30 días atrás) y otra reciente.
        from b2b_ai.audit.logger import _now_iso
        from datetime import datetime, timedelta, timezone
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        logger.login("old", 1, _when=old_ts)
        logger.login("new", 1)
        logger.flush()
        assert len(logger.query(tenant_id=1)) == 2
        removed = logger.prune(retention_days=30)
        assert removed >= 1
        rows = logger.query(tenant_id=1)
        assert len(rows) == 1
        assert rows[0].actor == "new"


class TestAuditLoggerQuery:
    def test_filters(self, logger):
        logger.login("alice", 1)
        logger.login("bob", 2)
        logger.tenant_created("admin", 3)
        logger.flush()
        by_actor = logger.query(actor="alice")
        assert len(by_actor) == 1 and by_actor[0].actor == "alice"
        by_event = logger.query(event="login")
        assert len(by_event) == 2
        by_tenant = logger.query(tenant_id=3, event="tenant.create")
        assert len(by_tenant) == 1

    def test_tenant_isolation(self, logger):
        logger.login("u1", 1)
        logger.login("u2", 2)
        logger.flush()
        assert len(logger.query(tenant_id=1)) == 1
        assert len(logger.query(tenant_id=2)) == 1
        assert len(logger.query()) == 2


# ---- Routes ----------------------------------------------------------------

class TestAuditRoutes:
    def _build(self, db):
        from fastapi import FastAPI
        from b2b_ai.audit.routes import build_audit_logger_router

        async def require_api_key():
            return "test-key"

        class FakeAuth:
            def __init__(self):
                self.tenant = None

            def get_tenant_id(self, key):
                return self.tenant

        auth = FakeAuth()
        app = FastAPI()
        app.include_router(build_audit_logger_router(db, require_api_key, auth))
        return app, auth

    def test_list_logs(self, audit_db, logger):
        from fastapi.testclient import TestClient
        logger.login("alice", 1)
        logger.flush()
        app, auth = self._build(audit_db)
        client = TestClient(app)
        res = client.get("/api/v1/audit/logs")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] >= 1
        assert body["entries"][0]["event"] == "login"

    def test_filter_by_user_and_action(self, audit_db, logger):
        from fastapi.testclient import TestClient
        logger.login("alice", 1)
        logger.tenant_created("admin", 2)
        logger.flush()
        app, auth = self._build(audit_db)
        client = TestClient(app)
        res = client.get("/api/v1/audit/logs", params={"user": "alice"})
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["entries"][0]["actor"] == "alice"

        res2 = client.get("/api/v1/audit/logs", params={"action": "login"})
        assert res2.json()["total"] == 1

    def test_tenant_scoping_from_key(self, audit_db, logger):
        from fastapi.testclient import TestClient
        logger.login("u1", 1)
        logger.login("u2", 2)
        logger.flush()
        app, auth = self._build(audit_db)
        auth.tenant = 1  # la key autenticada pertenece al tenant 1
        client = TestClient(app)
        res = client.get("/api/v1/audit/logs")
        body = res.json()
        assert body["total"] == 1
        assert body["entries"][0]["tenant_id"] == 1
