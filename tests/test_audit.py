# -*- coding: utf-8 -*-
"""test_audit.py — Tests unitarios del módulo de auditoría."""
import json
import os
import sys

import pytest

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def audit_db(tmp_path):
    """Devuelve una Database temporal con esquema de audit_entries."""
    from b2b_ai.db.db import Database
    return Database(str(tmp_path / "audit_test.db"))


@pytest.fixture
def trail(audit_db):
    from b2b_ai.audit.trail import AuditTrail
    return AuditTrail(audit_db)


# ---- Models ----

class TestActions:
    def test_actions_values(self):
        from b2b_ai.audit.models import Actions
        assert Actions.CREATE.value == "CREATE"
        assert Actions.READ.value == "READ"
        assert Actions.UPDATE.value == "UPDATE"
        assert Actions.DELETE.value == "DELETE"
        assert Actions.LOGIN.value == "LOGIN"
        assert Actions.LOGOUT.value == "LOGOUT"
        assert Actions.EXPORT.value == "EXPORT"
        assert Actions.APPROVE.value == "APPROVE"

    def test_actions_count(self):
        from b2b_ai.audit.models import Actions
        assert len(Actions) == 8


class TestAuditEntry:
    def test_from_row(self):
        from b2b_ai.audit.models import AuditEntry
        row = {
            "id": 1,
            "user_id": "u1",
            "tenant_id": 10,
            "action": "CREATE",
            "resource": "invoice",
            "resource_id": "42",
            "details": '{"key": "val"}',
            "ip": "127.0.0.1",
            "timestamp": "2025-01-01T00:00:00",
        }
        entry = AuditEntry.from_row(row)
        assert entry.id == 1
        assert entry.details == {"key": "val"}
        assert entry.action == "CREATE"

    def test_from_row_none_details(self):
        from b2b_ai.audit.models import AuditEntry
        row = {"id": 2, "user_id": None, "tenant_id": 1, "action": "READ",
               "resource": "x", "resource_id": None, "details": None,
               "ip": None, "timestamp": None}
        entry = AuditEntry.from_row(row)
        assert entry.details is None

    def test_to_dict(self):
        from b2b_ai.audit.models import AuditEntry
        e = AuditEntry(id=5, action="DELETE", resource="user")
        d = e.to_dict()
        assert d["id"] == 5
        assert d["action"] == "DELETE"
        assert "details" in d


# ---- Trail ----

class TestAuditTrail:
    def test_log_and_get(self, trail):
        entry_id = trail.log_action(
            user_id="alice", tenant_id=1, action="CREATE",
            resource="invoice", details={"total": 100},
            resource_id="42", ip="10.0.0.1",
        )
        assert entry_id is not None
        entries = trail.get_audit_log(1)
        assert len(entries) >= 1
        e = entries[0]
        assert e.user_id == "alice"
        assert e.tenant_id == 1
        assert e.action == "CREATE"
        assert e.resource == "invoice"
        assert e.details == {"total": 100}

    def test_tenant_isolation(self, trail):
        trail.log_action("u1", 1, "CREATE", "invoice")
        trail.log_action("u2", 2, "CREATE", "invoice")
        t1 = trail.get_audit_log(1)
        t2 = trail.get_audit_log(2)
        assert len(t1) == 1
        assert len(t2) == 1
        assert t1[0].tenant_id == 1
        assert t2[0].tenant_id == 2

    def test_filters(self, trail):
        trail.log_action("u1", 1, "CREATE", "invoice")
        trail.log_action("u1", 1, "READ", "invoice")
        trail.log_action("u1", 1, "DELETE", "user")
        by_action = trail.get_audit_log(1, {"action": "CREATE"})
        assert len(by_action) == 1
        by_resource = trail.get_audit_log(1, {"resource": "user"})
        assert len(by_resource) == 1
        by_user = trail.get_audit_log(1, {"user_id": "u1"})
        assert len(by_user) == 3

    def test_limit(self, trail):
        for i in range(10):
            trail.log_action("u", 1, "READ", "x")
        entries = trail.get_audit_log(1, {"limit": 3})
        assert len(entries) == 3

    def test_search(self, trail):
        trail.log_action("alice", 1, "CREATE", "invoice",
                         details={"memo": "test"})
        trail.log_action("bob", 1, "READ", "user")
        results = trail.search_audit_log("alice")
        assert any(e.user_id == "alice" for e in results)
        results2 = trail.search_audit_log("user")
        assert any(e.resource == "user" for e in results2)

    def test_export_json(self, trail):
        trail.log_action("u1", 1, "CREATE", "invoice")
        out = trail.export_audit_log(1, format="json")
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["action"] == "CREATE"

    def test_export_csv(self, trail):
        trail.log_action("u1", 1, "CREATE", "invoice")
        out = trail.export_audit_log(1, format="csv")
        assert "action" in out
        assert "CREATE" in out
        lines = out.strip().split("\n")
        assert len(lines) >= 2  # header + 1 row

    def test_search_with_tenant(self, trail):
        trail.log_action("u1", 1, "CREATE", "invoice")
        trail.log_action("u2", 2, "CREATE", "invoice")
        results = trail.search_audit_log("invoice", tenant_id=1)
        assert all(e.tenant_id == 1 for e in results)
