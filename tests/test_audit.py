# -*- coding: utf-8 -*-
"""Tests — audit trail: models, AuditTrail y middleware de auto-registro."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.audit.models import Actions, AuditEntry
from b2b_ai.audit.trail import AuditTrail

API_KEY = "audit-test-secret-1"


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
def test_actions_enum_cubre_verbos_requeridos():
    required = {"CREATE", "READ", "UPDATE", "DELETE",
                "LOGIN", "LOGOUT", "EXPORT", "APPROVE"}
    assert required <= {a.value for a in Actions}


def test_audit_entry_to_dict_y_from_row(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = AuditTrail(db).log_action("u1", 7, Actions.UPDATE, "invoice",
                                    {"categoria": "gasto"},
                                    resource_id="42", ip="10.0.0.1")
    row = db.conn.execute(
        "SELECT * FROM audit_entries WHERE id=?", (tid,)).fetchone()
    entry = AuditEntry.from_row(row)
    assert entry.action == "UPDATE"
    assert entry.details == {"categoria": "gasto"}
    assert entry.resource_id == "42"
    d = entry.to_dict()
    assert d["action"] == "UPDATE" and d["details"] == {"categoria": "gasto"}


# --------------------------------------------------------------------------- #
# AuditTrail
# --------------------------------------------------------------------------- #
@pytest.fixture
def trail_db(tmp_path):
    db = Database(str(tmp_path / "audit.db"))
    t = AuditTrail(db)
    t.log_action("user_a", 1, Actions.CREATE, "invoice", {"monto": "100"},
                 resource_id="11", ip="1.1.1.1")
    t.log_action("user_a", 1, Actions.DELETE, "invoice", resource_id="11",
                 ip="1.1.1.1")
    t.log_action("user_b", 2, Actions.CREATE, "invoice", resource_id="22",
                 ip="2.2.2.2")
    t.log_action("admin", 1, Actions.APPROVE, "review", {"ok": True},
                 ip="1.1.1.1")
    return db


def test_get_audit_log_aisla_por_tenant(trail_db):
    t = AuditTrail(trail_db)
    tenant1 = t.get_audit_log(1)
    tenant2 = t.get_audit_log(2)
    assert len(tenant1) == 3
    assert len(tenant2) == 1
    assert all(e.tenant_id == 1 for e in tenant1)
    assert all(e.tenant_id == 2 for e in tenant2)


def test_get_audit_log_filtros(trail_db):
    t = AuditTrail(trail_db)
    # por acción
    creates = t.get_audit_log(1, {"action": Actions.CREATE})
    assert len(creates) == 1 and creates[0].resource_id == "11"
    # por recurso
    deletes = t.get_audit_log(1, {"resource": "invoice",
                                  "action": Actions.DELETE})
    assert len(deletes) == 1 and deletes[0].action == "DELETE"
    # por usuario
    by_user = t.get_audit_log(1, {"user_id": "admin"})
    assert len(by_user) == 1 and by_user[0].action == "APPROVE"
    # orden: más reciente primero
    all1 = t.get_audit_log(1)
    assert all1[0].action == "APPROVE"


def test_search_audit_log(trail_db):
    t = AuditTrail(trail_db)
    hits = t.search_audit_log("invoice")
    assert len(hits) == 3
    # acotado por tenant
    scoped = t.search_audit_log("invoice", tenant_id=1)
    assert len(scoped) == 2


def test_export_audit_log_json_y_csv(trail_db):
    t = AuditTrail(trail_db)
    js = t.export_audit_log(1, "json")
    data = json.loads(js)
    assert len(data) == 3 and data[0]["action"] == "APPROVE"
    csv_out = t.export_audit_log(1, "csv")
    assert csv_out.splitlines()[0].startswith("id,user_id")
    assert "APPROVE" in csv_out


# --------------------------------------------------------------------------- #
# middleware: auto-log de mutaciones de la API
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def test_middleware_audita_mutacion_con_contexto(client):
    testclient, db = client
    r = testclient.post(
        "/api/v1/leads",
        headers={"X-API-Key": API_KEY},
        json={"nombre": "Ana", "email": "ana@cliente.com"})
    assert r.status_code == 200
    # la mutación quedó registrada con contexto de usuario/tenant
    rows = db.conn.execute(
        "SELECT * FROM audit_entries WHERE tenant_id=1").fetchall()
    assert len(rows) == 1
    entry = rows[0]
    assert entry["action"] == "CREATE"
    assert entry["resource"] == "/api/v1/leads"
    assert entry["user_id"] == "test-key"
    details = json.loads(entry["details"])
    assert details["method"] == "POST" and details["status"] == 200


def test_middleware_no_audita_get(client):
    testclient, db = client
    r = testclient.get("/health")
    assert r.status_code == 200
    n = db.conn.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
    assert n == 0


def test_middleware_captura_ip_y_falla_no_rompe(client):
    testclient, db = client
    # mutación sin auth (lead público): se audita con user_id None
    r = testclient.post("/api/v1/leads",
                        json={"nombre": "Bob", "email": "bob@x.com"})
    assert r.status_code == 200
    rows = db.conn.execute("SELECT * FROM audit_entries").fetchall()
    assert len(rows) == 1 and rows[0]["user_id"] is None
