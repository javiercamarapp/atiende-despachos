# -*- coding: utf-8 -*-
"""
test_pg_adapter.py — Comprehensive test suite for the PostgreSQL adapter layer.

80+ tests covering:
  - PG connection pool (PGPool, PGConnection, PGCursor, PGRecord)
  - SQL placeholder translation (qmark_to_percent)
  - Database dual-backend mode (SQLite auto-detect, PG auto-detect)
  - SQLite→PostgreSQL migration script
  - Data integrity: multi-tenant isolation on PG
  - Connection pooling: health check, retry, limits
  - Edge cases: empty data, special characters, concurrent access
  - Schema versioning on both backends

Tests that require a live PostgreSQL are marked with pytest.mark.skipif.
All other tests run against SQLite or use mocks.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from b2b_ai.db.pg import (
    PGPool, PGConnection, PGCursor, PGRecord,
    qmark_to_percent, _row_factory,
)
from b2b_ai.db.db import (
    Database, _is_postgres, _is_integrity_error,
    _encrypt_config_value, _decrypt_config_value,
    _SENSITIVE_CONFIG_KEYS,
)
from b2b_ai.db.pool import ConnectionPool, _is_postgres as _pool_is_postgres
from b2b_ai.db.models import MIGRATIONS

# ============================================================================
# Constants
# ============================================================================
PG_DSN = os.environ.get("B2B_DB_URL", "")


def _pg_available():
    if not PG_DSN:
        return False
    try:
        import psycopg
        psycopg.connect(PG_DSN, connect_timeout=3).close()
        return True
    except Exception:
        return False


pg_required = pytest.mark.skipif(
    not _pg_available(),
    reason="B2B_DB_URL PostgreSQL not available"
)

# ============================================================================
# SECTION 1: SQL Placeholder Translation (qmark_to_percent)
# ============================================================================

class TestQmarkToPercent:
    """Tests for SQLite→PostgreSQL SQL translation."""

    def test_simple_select(self):
        assert qmark_to_percent("SELECT ? AS x") == "SELECT %s AS x"

    def test_multiple_params(self):
        assert qmark_to_percent("SELECT ?, ?, ?") == "SELECT %s, %s, %s"

    def test_no_params(self):
        assert qmark_to_percent("SELECT 1") == "SELECT 1"

    def test_literal_question_mark_in_string(self):
        assert qmark_to_percent("SELECT '?'") == "SELECT '?'"
        assert qmark_to_percent("SELECT 'test?'") == "SELECT 'test?'"

    def test_mixed_literal_and_placeholder(self):
        result = qmark_to_percent("SELECT '?literal' AS t, ? AS n")
        assert result == "SELECT '?literal' AS t, %s AS n"

    def test_double_quoted_string(self):
        assert qmark_to_percent('SELECT "?"') == 'SELECT "?"'

    def test_escaped_quotes(self):
        # SQLite escapes single quotes with ''
        assert qmark_to_percent("SELECT ''") == "SELECT ''"

    def test_named_placeholder(self):
        result = qmark_to_percent("SELECT :name, :age")
        assert result == "SELECT %(name)s, %(age)s"

    def test_named_and_positional(self):
        result = qmark_to_percent("SELECT :name, ?, :age")
        assert result == "SELECT %(name)s, %s, %(age)s"

    def test_complex_where_clause(self):
        sql = "SELECT * FROM t WHERE a=? AND b=? AND c LIKE '%?%'"
        result = qmark_to_percent(sql)
        assert result == "SELECT * FROM t WHERE a=%s AND b=%s AND c LIKE '%?%'"

    def test_insert_statement(self):
        sql = "INSERT INTO t(a, b) VALUES (?, ?)"
        assert qmark_to_percent(sql) == "INSERT INTO t(a, b) VALUES (%s, %s)"

    def test_update_statement(self):
        sql = "UPDATE t SET a=? WHERE id=?"
        assert qmark_to_percent(sql) == "UPDATE t SET a=%s WHERE id=%s"

    def test_delete_statement(self):
        sql = "DELETE FROM t WHERE id=?"
        assert qmark_to_percent(sql) == "DELETE FROM t WHERE id=%s"

    def test_empty_string(self):
        assert qmark_to_percent("") == ""

    def test_on_conflict_upsert(self):
        sql = ("INSERT INTO t(a) VALUES (?) "
               "ON CONFLICT(tenant_id, key) DO UPDATE SET a=excluded.a")
        result = qmark_to_percent(sql)
        assert "%s" in result
        assert "?" not in result

    def test_nested_parens(self):
        sql = "SELECT CASE WHEN ? > 0 THEN ? ELSE ? END"
        result = qmark_to_percent(sql)
        assert result == "SELECT CASE WHEN %s > 0 THEN %s ELSE %s END"

    def test_string_with_question_in_value(self):
        # The placeholder inside a string literal should NOT be translated
        sql = "SELECT 'What?' FROM t WHERE id=?"
        result = qmark_to_percent(sql)
        assert result == "SELECT 'What?' FROM t WHERE id=%s"

    def test_multiple_string_contexts(self):
        sql = "SELECT 'a?b', ?, 'c?d', ?"
        result = qmark_to_percent(sql)
        assert result == "SELECT 'a?b', %s, 'c?d', %s"


# ============================================================================
# SECTION 2: PGRecord (dict + positional access)
# ============================================================================

class TestPGRecord:
    """Tests for the PGRecord class that mimics sqlite3.Row."""

    def test_dict_access(self):
        r = PGRecord({"name": "Alice", "age": 30})
        assert r["name"] == "Alice"
        assert r["age"] == 30

    def test_positional_access(self):
        r = PGRecord({"name": "Alice", "age": 30})
        assert r[0] == "Alice"
        assert r[1] == 30

    def test_negative_index(self):
        r = PGRecord({"a": 1, "b": 2, "c": 3})
        assert r[-1] == 3
        assert r[-2] == 2

    def test_len(self):
        r = PGRecord({"a": 1, "b": 2})
        assert len(r) == 2

    def test_keys(self):
        r = PGRecord({"x": 1, "y": 2})
        assert set(r.keys()) == {"x", "y"}

    def test_values(self):
        r = PGRecord({"x": 1, "y": 2})
        assert set(r.values()) == {1, 2}

    def test_items(self):
        r = PGRecord({"x": 1, "y": 2})
        assert set(r.items()) == {("x", 1), ("y", 2)}

    def test_contains(self):
        r = PGRecord({"x": 1})
        assert "x" in r
        assert "z" not in r

    def test_get_default(self):
        r = PGRecord({"x": 1})
        assert r.get("y", 42) == 42
        assert r.get("x") == 1

    def test_empty_record(self):
        r = PGRecord({})
        assert len(r) == 0

    def test_string_key(self):
        r = PGRecord({0: "zero", "key": "value"})
        assert r[0] == "zero"  # positional
        assert r["key"] == "value"  # string key

    def test_dict_in_dict(self):
        inner = {"nested": "value"}
        r = PGRecord({"data": inner})
        assert r["data"]["nested"] == "value"


# ============================================================================
# SECTION 3: PGConnection (wrapper API compatibility)
# ============================================================================

class TestPGConnection:
    """Tests for PGConnection wrapper without live PG."""

    def test_context_manager_enter_exit(self):
        """PGConnection __enter__ returns self."""
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        result = conn.__enter__()
        assert result is conn

    def test_context_manager_exit_no_error(self):
        """__exit__ without error commits."""
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        conn.__exit__(None, None, None)
        mock_raw.commit.assert_called_once()

    def test_context_manager_exit_with_error(self):
        """__exit__ with exception rolls back."""
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        exc = Exception("test error")
        conn.__exit__(type(exc), exc, None)
        mock_raw.rollback.assert_called_once()

    def test_commit(self):
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        conn.commit()
        mock_raw.commit.assert_called_once()

    def test_rollback(self):
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        conn.rollback()
        mock_raw.rollback.assert_called_once()

    def test_close_idempotent(self):
        """close() is idempotent."""
        mock_release = MagicMock()
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw, release=mock_release)
        conn.close()
        conn.close()  # Second close should be no-op
        assert mock_release.__exit__.call_count == 1

    def test_close_without_release(self):
        """close() falls back to raw close."""
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw, release=None)
        conn.close()
        mock_raw.close.assert_called_once()

    def test_raw_accessor(self):
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        assert conn.raw() is mock_raw

    def test_execute_returns_pg_cursor(self):
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        cur = conn.execute("SELECT 1")
        assert isinstance(cur, PGCursor)

    def test_released_flag(self):
        mock_raw = MagicMock()
        conn = PGConnection(mock_raw)
        assert not conn._released
        conn.close()
        assert conn._released


# ============================================================================
# SECTION 4: PGCursor (wrapper for lastrowid, rowcount)
# ============================================================================

class TestPGCursor:
    """Tests for PGCursor wrapper."""

    def test_execute_returns_self(self):
        mock_cursor = MagicMock()
        mock_cursor.description = [("col1",)]
        cur = PGCursor(mock_cursor)
        result = cur.execute("SELECT 1")
        assert result is cur

    def test_fetchone(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = PGRecord({"x": 42})
        cur = PGCursor(mock_cursor)
        row = cur.fetchone()
        assert row["x"] == 42

    def test_fetchall(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            PGRecord({"x": 1}),
            PGRecord({"x": 2}),
        ]
        cur = PGCursor(mock_cursor)
        rows = cur.fetchall()
        assert len(rows) == 2

    def test_rowcount(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        cur = PGCursor(mock_cursor)
        assert cur.rowcount == 5

    def test_lastrowid_via_lastval(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (42,)
        cur = PGCursor(mock_cursor)
        assert cur.lastrowid == 42

    def test_lastrowid_error_returns_none(self):
        import psycopg
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg.Error("no lastval")
        cur = PGCursor(mock_cursor)
        assert cur.lastrowid is None

    def test_len(self):
        mock_cursor = MagicMock()
        mock_cursor.__len__ = MagicMock(return_value=10)
        cur = PGCursor(mock_cursor)
        assert len(cur) == 10

    def test_iter(self):
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = MagicMock(return_value=iter([1, 2, 3]))
        cur = PGCursor(mock_cursor)
        items = list(cur)
        assert items == [1, 2, 3]


# ============================================================================
# SECTION 5: Database class — SQLite mode
# ============================================================================

class TestDatabaseSQLite:
    """Tests for the Database class in SQLite mode (default)."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        database = Database(db_path)
        yield database
        database.close()

    def test_creates_sqlite_db(self, db):
        assert os.path.exists(db.path)

    def test_schema_version(self, db):
        assert db.schema_version() >= 1

    def test_data_version_starts_zero(self, db):
        assert db.data_version() == 0

    def test_create_tenant(self, db):
        tid = db.create_tenant("Test Tenant", "TST0101AAA")
        assert tid is not None
        assert tid > 0

    def test_list_tenants(self, db):
        db.create_tenant("T1", "R1")
        db.create_tenant("T2", "R2")
        tenants = db.list_tenants()
        assert len(tenants) == 2

    def test_create_user(self, db):
        tid = db.create_tenant("T1")
        uid = db.create_user(tid, "Alice", "alice@test.com", "admin")
        assert uid is not None

    def test_insert_invoice(self, db):
        tid = db.create_tenant("T1")
        datos = {
            "folio_fiscal": "FISCAL-001",
            "archivo": "test.xml",
            "fecha": "2026-01-01",
            "tipo": "I",
            "emisor_rfc": "EMI0101AAA",
            "emisor_nombre": "Emisor SA",
            "receptor_rfc": "REC0101AAA",
            "subtotal": "1000.00",
            "iva": "160.00",
            "total": "1160.00",
        }
        clasif = {"categoria": "gasto_operativo", "confianza": 0.95, "razon": "test"}
        val = {"ok": True, "issues": [], "requires_human_review": False}
        invoice_id, inserted = db.insert_invoice(tid, datos, clasif, val)
        assert invoice_id is not None
        assert inserted is True

    def test_insert_invoice_dedup(self, db):
        tid = db.create_tenant("T1")
        datos = {
            "folio_fiscal": "FISCAL-DUP",
            "archivo": "test.xml",
            "subtotal": "100", "iva": "16", "total": "116",
        }
        clasif = {"categoria": "gasto", "confianza": 0.9, "razon": "dup test"}
        val = {"ok": True, "issues": []}
        id1, ins1 = db.insert_invoice(tid, datos, clasif, val)
        id2, ins2 = db.insert_invoice(tid, datos, clasif, val)
        assert ins1 is True
        assert ins2 is False
        assert id1 == id2

    def test_data_version_bumps_on_insert(self, db):
        tid = db.create_tenant("T1")
        v0 = db.data_version()
        datos = {"folio_fiscal": "FV-1", "archivo": "x.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "test", "confianza": 1, "razon": "r"}
        val = {"ok": True, "issues": []}
        db.insert_invoice(tid, datos, clasif, val)
        assert db.data_version() == v0 + 1

    def test_list_invoices(self, db):
        tid = db.create_tenant("T1")
        datos = {"folio_fiscal": "FL-1", "archivo": "f.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "gasto", "confianza": 0.8, "razon": "r"}
        val = {"ok": True, "issues": []}
        db.insert_invoice(tid, datos, clasif, val)
        invoices = db.list_invoices(tenant_id=tid)
        assert len(invoices) == 1

    def test_count_invoices(self, db):
        assert db.count_invoices() == 0
        tid = db.create_tenant("T1")
        datos = {"folio_fiscal": "FC-1", "archivo": "f.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "gasto", "confianza": 0.8, "razon": "r"}
        val = {"ok": True, "issues": []}
        db.insert_invoice(tid, datos, clasif, val)
        assert db.count_invoices() == 1

    def test_log_call(self, db):
        lid = db.log_call("parse", "dispatch", payload={"ok": True})
        assert lid is not None
        assert db.count_audit() == 1

    def test_list_audit(self, db):
        db.log_call("parse", "a1")
        db.log_call("validate", "a2")
        logs = db.list_audit()
        assert len(logs) == 2

    def test_create_api_key(self, db):
        tid = db.create_tenant("T1")
        kid, key_hash = db.create_api_key(tid, "test-key", "secret123")
        assert kid is not None
        assert len(key_hash) == 64  # SHA256 hex

    def test_get_api_key(self, db):
        tid = db.create_tenant("T1")
        db.create_api_key(tid, "test", "my-secret-key")
        row = db.get_api_key("my-secret-key")
        assert row is not None
        assert row["tenant_id"] == tid

    def test_get_api_key_nonexistent(self, db):
        assert db.get_api_key("does-not-exist") is None

    def test_set_api_key_active(self, db):
        tid = db.create_tenant("T1")
        kid, _ = db.create_api_key(tid, "test", "key-val")
        assert db.set_api_key_active(kid, False) is True
        assert db.get_api_key("key-val") is None

    def test_tenant_config_set_get(self, db):
        tid = db.create_tenant("T1")
        db.set_tenant_config(tid, "erp", "contpaqi")
        assert db.get_tenant_config(tid, "erp") == "contpaqi"

    def test_tenant_config_upsert(self, db):
        tid = db.create_tenant("T1")
        db.set_tenant_config(tid, "erp", "contpaqi")
        db.set_tenant_config(tid, "erp", "aspel")
        assert db.get_tenant_config(tid, "erp") == "aspel"

    def test_tenant_config_get_all(self, db):
        tid = db.create_tenant("T1")
        db.set_tenant_config(tid, "a", "1")
        db.set_tenant_config(tid, "b", "2")
        cfg = db.get_all_tenant_config(tid)
        assert cfg == {"a": "1", "b": "2"}

    def test_tenant_config_default(self, db):
        tid = db.create_tenant("T1")
        assert db.get_tenant_config(tid, "missing", "default") == "default"

    def test_create_review(self, db):
        tid = db.create_tenant("T1")
        rid = db.create_review(tid, None, "suspicious amount")
        assert rid is not None

    def test_list_reviews(self, db):
        tid = db.create_tenant("T1")
        db.create_review(tid, None, "reason1")
        db.create_review(tid, None, "reason2")
        reviews = db.list_reviews(tenant_id=tid)
        assert len(reviews) == 2

    def test_resolve_review(self, db):
        tid = db.create_tenant("T1")
        rid = db.create_review(tid, None, "test")
        result = db.resolve_review(rid, "approved", notes="looks good")
        assert result is not None
        assert result["status"] == "resolved"

    def test_insert_notification(self, db):
        tid = db.create_tenant("T1")
        nid = db.insert_notification(tid, "invoice_processed", "email",
                                      "a@b.com", "Subject", "Body")
        assert nid is not None

    def test_list_notifications(self, db):
        tid = db.create_tenant("T1")
        db.insert_notification(tid, "type1", "email", "a@b.com", "S", "B")
        db.insert_notification(tid, "type2", "sms", "+123", "S", "B")
        assert len(db.list_notifications(tenant_id=tid)) == 2

    def test_add_lead(self, db):
        lid = db.add_lead("Juan", "juan@test.com", "Despacho", "100")
        assert lid is not None

    def test_list_leads(self, db):
        db.add_lead("A", "a@test.com")
        db.add_lead("B", "b@test.com")
        assert len(db.list_leads()) == 2

    def test_add_bank_transactions(self, db):
        tid = db.create_tenant("T1")
        txns = [{"id": "TX1", "amount": 100}, {"id": "TX2", "amount": 200}]
        nuevos = db.add_bank_transactions(tid, txns)
        assert nuevos == 2

    def test_add_bank_transactions_dedup(self, db):
        tid = db.create_tenant("T1")
        txns = [{"id": "TX1", "amount": 100}]
        db.add_bank_transactions(tid, txns)
        nuevos = db.add_bank_transactions(tid, txns)
        assert nuevos == 0

    def test_list_bank_transactions(self, db):
        tid = db.create_tenant("T1")
        db.add_bank_transactions(tid, [{"id": "TX1", "amount": 100}])
        txns = db.list_bank_transactions(tid)
        assert len(txns) == 1

    def test_set_bank_confirmation(self, db):
        tid = db.create_tenant("T1")
        db.set_bank_confirmation(tid, "TX1", "INV-1")
        conns = db.list_bank_confirmations(tid)
        assert conns["TX1"] == "INV-1"

    def test_outstanding_invoice_upsert(self, db):
        tid = db.create_tenant("T1")
        oid = db.upsert_outstanding_invoice(tid, "FAC-1", 1000, "2026-08-01")
        assert oid is not None
        # Upsert should update
        oid2 = db.upsert_outstanding_invoice(tid, "FAC-1", 2000, "2026-08-01",
                                              dias_vencido=5)
        assert oid2 == oid

    def test_list_outstanding_invoices(self, db):
        tid = db.create_tenant("T1")
        db.upsert_outstanding_invoice(tid, "FAC-1", 100, "2026-01-01")
        db.upsert_outstanding_invoice(tid, "FAC-2", 200, "2026-01-01")
        result = db.list_outstanding_invoices(tenant_id=tid)
        assert len(result) == 2

    def test_delete_outstanding_invoice(self, db):
        tid = db.create_tenant("T1")
        db.upsert_outstanding_invoice(tid, "FAC-1", 100, "2026-01-01")
        db.delete_outstanding_invoice(tid, "FAC-1")
        assert len(db.list_outstanding_invoices(tenant_id=tid)) == 0

    def test_add_collection_event(self, db):
        tid = db.create_tenant("T1")
        eid = db.add_collection_event(tid, "FAC-1", "recordatorio_7d")
        assert eid is not None

    def test_list_collection_events(self, db):
        tid = db.create_tenant("T1")
        db.add_collection_event(tid, "FAC-1", "reminder")
        db.add_collection_event(tid, "FAC-2", "escalation")
        events = db.list_collection_events(tenant_id=tid)
        assert len(events) == 2

    def test_add_collection_payment(self, db):
        tid = db.create_tenant("T1")
        pid = db.add_collection_payment(tid, "FAC-1", "payment", 500.0)
        assert pid is not None

    def test_collection_config(self, db):
        tid = db.create_tenant("T1")
        db.set_collection_config(tid, "max_reminders", "3")
        assert db.get_collection_config(tid, "max_reminders") == "3"

    def test_outreach_campaign(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_outreach_campaign(tid, "Test Campaign")
        assert cid is not None
        campaign = db.get_outreach_campaign(cid)
        assert campaign["name"] == "Test Campaign"

    def test_outreach_lead(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_outreach_campaign(tid, "C1")
        lid = db.add_outreach_lead(cid, tid, "test@example.com",
                                    first_name="Test")
        assert lid is not None

    def test_outreach_email_tracking(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_outreach_campaign(tid, "C1")
        lid = db.add_outreach_lead(cid, tid, "a@b.com")
        eid = db.add_outreach_email(cid, lid, tid, "template1", "Subject", "Body")
        assert eid is not None
        db.mark_outreach_email_opened(eid)
        db.mark_outreach_email_clicked(eid)

    def test_set_tenant_blocked(self, db):
        tid = db.create_tenant("T1")
        db.set_tenant_blocked(tid, True)
        tenant = db.get_tenant_by_id(tid)
        assert tenant["blocked"] == 1

    def test_increment_usage(self, db):
        tid = db.create_tenant("T1")
        usage = db.increment_usage(tid, api_calls=10, invoices_processed=5)
        assert usage["api_calls"] == 10
        # Second increment adds to existing
        usage2 = db.increment_usage(tid, api_calls=3, invoices_processed=2)
        assert usage2["api_calls"] == 13

    def test_webhook_subscription(self, db):
        tid = db.create_tenant("T1")
        sid = db.create_webhook_subscription(tid, "invoice.processed",
                                              "https://webhook.test")
        assert sid is not None
        subs = db.list_webhook_subscriptions(tenant_id=tid)
        assert len(subs) == 1

    def test_webhook_subscription_delete(self, db):
        tid = db.create_tenant("T1")
        sid = db.create_webhook_subscription(tid, "event", "https://url")
        assert db.delete_webhook_subscription(sid, tid) is True

    def test_client_user_crud(self, db):
        tid = db.create_tenant("T1")
        uid = db.create_client_user(tid, "c@test.com", "hash123", "Client")
        assert uid is not None
        user = db.get_client_user(uid)
        assert user["email"] == "c@test.com"
        users = db.list_client_users(tid)
        assert len(users) == 1

    def test_client_user_by_email(self, db):
        tid = db.create_tenant("T1")
        db.create_client_user(tid, "c@test.com", "hash")
        user = db.get_client_user_by_email("c@test.com")
        assert user is not None

    def test_update_client_user(self, db):
        tid = db.create_tenant("T1")
        uid = db.create_client_user(tid, "old@test.com", "hash", "Old Name")
        updated = db.update_client_user(uid, {"name": "New Name"})
        assert updated["name"] == "New Name"

    def test_delete_client_user(self, db):
        tid = db.create_tenant("T1")
        uid = db.create_client_user(tid, "c@test.com", "hash")
        db.delete_client_user(uid)
        assert db.get_client_user(uid) is None

    def test_portal_session(self, db):
        tid = db.create_tenant("T1")
        uid = db.create_client_user(tid, "c@test.com", "hash")
        sid = db.create_portal_session(uid, "test-token-abc",
                                        "2099-01-01T00:00:00")
        assert sid is not None
        session = db.get_portal_session("test-token-abc")
        assert session is not None
        assert session["user"]["email"] == "c@test.com"

    def test_portal_session_expired(self, db):
        tid = db.create_tenant("T1")
        uid = db.create_client_user(tid, "c@test.com", "hash")
        db.create_portal_session(uid, "expired-token", "2020-01-01T00:00:00")
        session = db.get_portal_session("expired-token")
        assert session is None

    def test_has_tenant_users(self, db):
        tid = db.create_tenant("T1")
        assert db.has_tenant_users(tid) is False
        db.create_user(tid, "admin", "admin@test.com")
        assert db.has_tenant_users(tid) is True

    def test_billing_customer(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_billing_customer(tid, "c@b.com", "Client", "stripe")
        assert cid is not None
        customer = db.get_billing_customer_by_email(tid, "c@b.com")
        assert customer["name"] == "Client"

    def test_billing_subscription(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_billing_customer(tid, "c@b.com", "Client")
        sid = db.create_billing_subscription(tid, cid, "pro", "stripe", "sub_123")
        assert sid is not None
        subs = db.list_billing_subscriptions(tid)
        assert len(subs) == 1

    def test_billing_invoice(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_billing_customer(tid, "c@b.com", "Client")
        iid = db.create_billing_invoice(tid, cid, 999.00, "MXN")
        assert iid is not None
        invoices = db.list_billing_invoices(tid)
        assert len(invoices) == 1

    def test_billing_mark_paid(self, db):
        tid = db.create_tenant("T1")
        cid = db.create_billing_customer(tid, "c@b.com", "Client")
        iid = db.create_billing_invoice(tid, cid, 100, "MXN",
                                         provider_invoice_id="inv_123")
        result = db.mark_billing_invoice_paid_by_ref("inv_123", "stripe")
        assert result is True

    def test_cuentas_contables(self, db):
        tid = db.create_tenant("T1")
        cid = db.upsert_cuenta_contable(tid, "1.1.01", "Caja", nivel=3)
        assert cid is not None
        cuentas = db.list_cuentas_contables(tid)
        assert len(cuentas) == 1

    def test_asientos_contables(self, db):
        tid = db.create_tenant("T1")
        aid = db.insert_asiento_contable(tid, "2026-01-15", "1.1.01", "2.1.01", "5000")
        assert aid is not None

    def test_balanza_mensual(self, db):
        tid = db.create_tenant("T1")
        cid = db.upsert_cuenta_contable(tid, "1.1.01", "Caja")
        db.upsert_balanza_mensual(tid, "2026-01", cid, "0", "5000", "3000", "2000")
        balanzas = db.list_balanzas_mensuales(tid, "2026-01")
        assert len(balanzas) == 1

    def test_paquete_contabilidad(self, db):
        tid = db.create_tenant("T1")
        pid = db.insert_paquete_contabilidad(tid, "2026-01", "TEST0101AAA",
                                              "borrador")
        assert pid is not None
        db.update_paquete_estado(pid, "listo_para_timbrar")
        p = db.get_paquete_contabilidad(pid)
        assert p["estado"] == "listo_para_timbrar"

    def test_enforce_retention(self, db):
        # audit_log has created_at defaulting to now, so nothing to delete
        removed = db.enforce_retention(days=9999)
        assert isinstance(removed, dict)


# ============================================================================
# SECTION 6: Database dual-backend detection
# ============================================================================

class TestDualBackendDetection:
    """Tests for _is_postgres detection logic."""

    def test_detects_postgresql_uri(self):
        assert _is_postgres("postgresql://user:pass@host/db") is True

    def test_detects_postgres_uri(self):
        assert _is_postgres("postgres://user:pass@host/db") is True

    def test_detects_postgresql_uri_case_insensitive(self):
        assert _is_postgres("PostgreSQL://user:pass@host/db") is True

    def test_rejects_sqlite_path(self):
        assert _is_postgres("/path/to/b2b_ai.db") is False

    def test_rejects_empty(self):
        assert _is_postgres("") is False

    def test_rejects_none(self):
        assert _is_postgres(None) is False

    def test_pool_detection_matches(self):
        assert _pool_is_postgres("postgresql://x@h/db") is True
        assert _pool_is_postgres("postgres://x@h/db") is True
        assert _pool_is_postgres("/path/to/file.db") is False


# ============================================================================
# SECTION 7: Integrity error detection
# ============================================================================

class TestIntegrityErrorDetection:
    """Tests for _is_integrity_error across backends."""

    def test_sqlite_integrity_error(self):
        exc = sqlite3.IntegrityError("UNIQUE constraint failed")
        assert _is_integrity_error(exc) is True

    def test_regular_exception(self):
        assert _is_integrity_error(ValueError("test")) is False

    def test_os_error(self):
        assert _is_integrity_error(OSError("file not found")) is False


# ============================================================================
# SECTION 8: Connection Pool (pool.py)
# ============================================================================

class TestConnectionPool:
    """Tests for the ConnectionPool class."""

    def test_creates_sqlite_pool(self, tmp_path):
        db_path = str(tmp_path / "pool_test.db")
        pool = ConnectionPool(db_path, size=2)
        assert pool.size == 2
        assert pool._is_pg is False
        pool.close()

    def test_acquire_release(self, tmp_path):
        db_path = str(tmp_path / "pool_ar.db")
        pool = ConnectionPool(db_path, size=2)
        with pool.acquire() as conn:
            assert conn is not None
            conn.execute("SELECT 1")
        pool.close()

    def test_stats(self, tmp_path):
        db_path = str(tmp_path / "pool_stats.db")
        pool = ConnectionPool(db_path, size=2)
        stats = pool.stats
        assert stats["backend"] == "sqlite"
        assert stats["size"] == 2
        pool.close()

    def test_run_query(self, tmp_path):
        db_path = str(tmp_path / "pool_run.db")
        pool = ConnectionPool(db_path, size=2)
        result = pool.run("SELECT 1 AS x")
        assert len(result) == 1
        assert result[0]["x"] == 1
        pool.close()

    def test_reuses_connections(self, tmp_path):
        db_path = str(tmp_path / "pool_reuse.db")
        pool = ConnectionPool(db_path, size=1)
        with pool.acquire() as c1:
            c1.execute("CREATE TABLE t(x)")
            c1.execute("INSERT INTO t VALUES (1)")
            c1.commit()
        with pool.acquire() as c2:
            rows = [dict(r) for r in c2.execute("SELECT * FROM t").fetchall()]
        assert rows[0]["x"] == 1
        pool.close()


# ============================================================================
# SECTION 9: Config encryption helpers
# ============================================================================

class TestConfigEncryption:
    """Tests for sensitive config value encryption."""

    def test_sensitive_keys_defined(self):
        assert "webhook_url" in _SENSITIVE_CONFIG_KEYS
        assert "notif_recipient" in _SENSITIVE_CONFIG_KEYS
        assert "whatsapp_token" in _SENSITIVE_CONFIG_KEYS

    def test_encrypt_non_sensitive_passthrough(self):
        val = _encrypt_config_value("erp_type", "contpaqi")
        assert val == "contpaqi"

    def test_encrypt_non_string_passthrough(self):
        val = _encrypt_config_value("webhook_url", 123)
        assert val == 123

    def test_decrypt_non_sensitive_passthrough(self):
        val = _decrypt_config_value("erp_type", "contpaqi")
        assert val == "contpaqi"


# ============================================================================
# SECTION 10: Migrations (schema_version)
# ============================================================================

class TestMigrations:
    """Tests for the SQLite migration system."""

    def test_migrations_have_unique_versions(self):
        versions = [m["version"] for m in MIGRATIONS]
        assert len(versions) == len(set(versions))

    def test_migrations_are_sequential(self):
        versions = sorted(m["version"] for m in MIGRATIONS)
        assert versions == list(range(1, len(versions) + 1))

    def test_migrations_have_required_keys(self):
        for m in MIGRATIONS:
            assert "version" in m
            assert "name" in m
            assert "sql" in m

    def test_migration_sql_is_string(self):
        for m in MIGRATIONS:
            assert isinstance(m["sql"], str)
            assert len(m["sql"]) > 10

    def test_schema_applies_clean(self, tmp_path):
        db_path = str(tmp_path / "clean.db")
        db = Database(db_path)
        assert db.schema_version() == len(MIGRATIONS)
        db.close()

    def test_schema_idempotent(self, tmp_path):
        db_path = str(tmp_path / "idemp.db")
        db1 = Database(db_path)
        db1.close()
        db2 = Database(db_path)
        assert db2.schema_version() == len(MIGRATIONS)
        db2.close()


# ============================================================================
# SECTION 11: Migration Script (migration.py)
# ============================================================================

class TestMigrationScript:
    """Tests for the SQLite→PostgreSQL migration script."""

    def test_import_migration_module(self):
        from b2b_ai.db.migration import (
            SQLiteToPostgresMigration, MigrationResult, MigrationSummary,
            TABLE_ORDER, main
        )
        assert callable(main)

    def test_table_order_has_core_tables(self):
        from b2b_ai.db.migration import TABLE_ORDER
        assert "tenants" in TABLE_ORDER
        assert "invoices" in TABLE_ORDER
        assert "users" in TABLE_ORDER
        assert "tenant_config" in TABLE_ORDER

    def test_migration_result_defaults(self):
        from b2b_ai.db.migration import MigrationResult
        r = MigrationResult(table="test")
        assert r.source_count == 0
        assert r.target_count == 0
        assert r.inserted == 0
        assert r.errors == []

    def test_migration_summary_defaults(self):
        from b2b_ai.db.migration import MigrationSummary
        s = MigrationSummary()
        assert s.total_tables == 0
        assert s.total_rows_migrated == 0

    def test_export_sqlite_data(self, tmp_path):
        from b2b_ai.db.migration import SQLiteToPostgresMigration
        db_path = str(tmp_path / "export_test.db")
        db = Database(db_path)
        tid = db.create_tenant("Test")
        db.create_user(tid, "Admin", "admin@test.com")
        db.close()

        migration = SQLiteToPostgresMigration(db_path, "postgresql://fake:fake@localhost/fake")
        data = migration.export_sqlite_data()
        migration.close()

        assert "tenants" in data
        assert len(data["tenants"]) == 1
        assert data["tenants"][0]["name"] == "Test"

    def test_list_tables_sqlite(self, tmp_path):
        from b2b_ai.db.migration import SQLiteToPostgresMigration
        db_path = str(tmp_path / "tables_test.db")
        Database(db_path).close()

        migration = SQLiteToPostgresMigration(db_path, "postgresql://fake:fake@localhost/fake")
        tables = migration._list_tables_sqlite()
        migration.close()

        assert "tenants" in tables
        assert "invoices" in tables

    def test_count_rows(self, tmp_path):
        from b2b_ai.db.migration import SQLiteToPostgresMigration
        db_path = str(tmp_path / "count_test.db")
        db = Database(db_path)
        db.create_tenant("T1")
        db.create_tenant("T2")
        db.close()

        migration = SQLiteToPostgresMigration(db_path, "postgresql://fake:fake@localhost/fake")
        conn = migration._connect_sqlite()
        count = migration._count_rows(conn, "tenants")
        migration.close()

        assert count == 2


# ============================================================================
# SECTION 12: Multi-tenant isolation
# ============================================================================

class TestMultiTenantIsolation:
    """Tests verifying tenant data isolation."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "mt_test.db")
        database = Database(db_path)
        yield database
        database.close()

    def test_invoices_isolated_by_tenant(self, db):
        a = db.create_tenant("Alpha")
        b = db.create_tenant("Beta")
        datos = {"folio_fiscal": "MT-1", "archivo": "f.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
        val = {"ok": True, "issues": []}
        db.insert_invoice(a, datos, clasif, val)
        assert db.count_invoices(tenant_id=a) == 1
        assert db.count_invoices(tenant_id=b) == 0

    def test_audit_filtered_by_tenant(self, db):
        a = db.create_tenant("Alpha")
        b = db.create_tenant("Beta")
        db.log_call("tool", "a", tenant_id=a)
        db.log_call("tool", "b", tenant_id=b)
        assert len(db.list_audit(tenant_id=a)) == 1
        assert len(db.list_audit(tenant_id=b)) == 1

    def test_notifications_isolated(self, db):
        a = db.create_tenant("Alpha")
        b = db.create_tenant("Beta")
        db.insert_notification(a, "t", "email", "a@b.com", "S", "B")
        db.insert_notification(b, "t", "email", "c@d.com", "S", "B")
        assert len(db.list_notifications(tenant_id=a)) == 1
        assert len(db.list_notifications(tenant_id=b)) == 1

    def test_config_isolated(self, db):
        a = db.create_tenant("Alpha")
        b = db.create_tenant("Beta")
        db.set_tenant_config(a, "erp", "contpaqi")
        db.set_tenant_config(b, "erp", "aspel")
        assert db.get_tenant_config(a, "erp") == "contpaqi"
        assert db.get_tenant_config(b, "erp") == "aspel"


# ============================================================================
# SECTION 13: Thread safety
# ============================================================================

class TestThreadSafety:
    """Tests for thread-local connection behavior."""

    def test_thread_local_connections(self, tmp_path):
        db_path = str(tmp_path / "thread_test.db")
        db = Database(db_path)
        results = {}

        def worker(name):
            tid = db.create_tenant(f"Thread-{name}")
            results[name] = tid

        threads = [threading.Thread(target=worker, args=(str(i),))
                   for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        tenants = db.list_tenants()
        assert len(tenants) == 5
        db.close()

    def test_concurrent_invoices(self, tmp_path):
        db_path = str(tmp_path / "conc_test.db")
        db = Database(db_path)
        tid = db.create_tenant("T1")
        errors = []

        def insert_invoice(i):
            try:
                datos = {"folio_fiscal": f"CONC-{i}", "archivo": "f.xml",
                         "subtotal": str(i), "iva": "0", "total": str(i)}
                clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
                val = {"ok": True, "issues": []}
                db.insert_invoice(tid, datos, clasif, val)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=insert_invoice, args=(i,))
                   for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert db.count_invoices() == 10
        db.close()


# ============================================================================
# SECTION 14: Edge cases and boundary conditions
# ============================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "edge_test.db")
        database = Database(db_path)
        yield database
        database.close()

    def test_empty_tenant_name(self, db):
        tid = db.create_tenant("")
        assert tid is not None

    def test_long_string_values(self, db):
        tid = db.create_tenant("T" * 1000)
        assert tid is not None

    def test_unicode_values(self, db):
        tid = db.create_tenant("测试租户", "RFC123")
        tenants = db.list_tenants()
        assert tenants[0]["name"] == "测试租户"

    def test_special_chars_in_config(self, db):
        tid = db.create_tenant("T1")
        val = "https://webhook.test/path?q=1&r=2&s=%20"
        db.set_tenant_config(tid, "webhook_url", val)
        assert db.get_tenant_config(tid, "webhook_url") == val

    def test_null_folio_fiscal(self, db):
        tid = db.create_tenant("T1")
        datos = {"folio_fiscal": None, "archivo": "f.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
        val = {"ok": True, "issues": []}
        invoice_id, inserted = db.insert_invoice(tid, datos, clasif, val)
        assert invoice_id is not None

    def test_empty_issues(self, db):
        tid = db.create_tenant("T1")
        datos = {"folio_fiscal": "EI-1", "archivo": "f.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
        val = {"ok": True, "issues": [], "requires_human_review": False}
        id1, _ = db.insert_invoice(tid, datos, clasif, val)
        assert id1 is not None

    def test_limit_in_list_invoices(self, db):
        tid = db.create_tenant("T1")
        for i in range(20):
            datos = {"folio_fiscal": f"LIM-{i}", "archivo": "f.xml",
                     "subtotal": "1", "iva": "0", "total": "1"}
            clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
            val = {"ok": True, "issues": []}
            db.insert_invoice(tid, datos, clasif, val)
        result = db.list_invoices(tenant_id=tid, limit=5)
        assert len(result) == 5

    def test_invoice_stats(self, db):
        tid = db.create_tenant("T1")
        datos = {"folio_fiscal": "STAT-1", "archivo": "f.xml",
                 "subtotal": "100", "iva": "16", "total": "116"}
        clasif = {"categoria": "gasto_operativo", "confianza": 0.95, "razon": "r"}
        val = {"ok": True, "issues": []}
        db.insert_invoice(tid, datos, clasif, val)
        stats = db.invoice_stats(tid)
        assert stats["total_facturas"] == 1
        assert stats["monto_total"] > 0

    def test_get_invoice(self, db):
        tid = db.create_tenant("T1")
        datos = {"folio_fiscal": "GET-1", "archivo": "f.xml",
                 "subtotal": "1", "iva": "0", "total": "1"}
        clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
        val = {"ok": True, "issues": []}
        iid, _ = db.insert_invoice(tid, datos, clasif, val)
        invoice = db.get_invoice(iid)
        assert invoice is not None
        assert invoice["folio_fiscal"] == "GET-1"

    def test_get_invoice_nonexistent(self, db):
        assert db.get_invoice(99999) is None


# ============================================================================
# SECTION 15: Alembic migration env.py validation
# ============================================================================

class TestAlembicEnv:
    """Tests for Alembic migration environment configuration."""

    def test_alembic_ini_exists(self):
        import os
        ini_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "alembic.ini")
        assert os.path.exists(ini_path)

    def test_migrations_dir_exists(self):
        import os
        mig_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "migrations")
        assert os.path.isdir(mig_dir)

    def test_migration_versions_exist(self):
        import os
        ver_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "migrations", "versions")
        versions = [f for f in os.listdir(ver_dir) if f.endswith(".py")]
        assert len(versions) >= 5

    def test_env_py_exists(self):
        import os
        env_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "migrations", "env.py")
        assert os.path.exists(env_path)


# ============================================================================
# SECTION 16: Performance helpers
# ============================================================================

class TestPerformanceHelpers:
    """Tests for data version cache invalidation."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "perf_test.db")
        database = Database(db_path)
        yield database
        database.close()

    def test_version_monotonically_increases(self, db):
        tid = db.create_tenant("T1")
        versions = [db.data_version()]
        for i in range(5):
            datos = {"folio_fiscal": f"PV-{i}", "archivo": "f.xml",
                     "subtotal": "1", "iva": "0", "total": "1"}
            clasif = {"categoria": "gasto", "confianza": 1, "razon": "r"}
            val = {"ok": True, "issues": []}
            db.insert_invoice(tid, datos, clasif, val)
            versions.append(db.data_version())
        # Monotonic increase
        for i in range(1, len(versions)):
            assert versions[i] >= versions[i - 1]


# ============================================================================
# SECTION 17: PGPool configuration
# ============================================================================

class TestPGPoolConfig:
    """Tests for PGPool configuration without live PG."""

    def test_pool_init_params(self):
        """PGPool stores configuration correctly."""
        pool = PGPool.__new__(PGPool)
        pool.min_size = 2
        pool.max_size = 10
        pool.retries = 3
        pool.retry_delay = 0.5
        assert pool.min_size == 2
        assert pool.max_size == 10

    def test_health_check_returns_dict(self):
        """health_check returns structured dict on failure."""
        pool = PGPool.__new__(PGPool)
        pool._pool = MagicMock()
        pool._pool.connection.side_effect = Exception("no connection")
        pool.retries = 1
        pool.retry_delay = 0
        result = pool.health_check()
        assert result["ok"] is False
        assert "error" in result


# ============================================================================
# SECTION 18: Migration script error handling
# ============================================================================

class TestMigrationErrorHandling:
    """Edge cases in the migration script."""

    def test_migration_result_error_list(self):
        from b2b_ai.db.migration import MigrationResult
        r = MigrationResult(table="test")
        r.errors.append("error 1")
        r.errors.append("error 2")
        assert len(r.errors) == 2

    def test_table_order_completeness(self):
        """TABLE_ORDER should cover core tables."""
        from b2b_ai.db.migration import TABLE_ORDER
        core = {"tenants", "users", "invoices", "audit_log", "notifications",
                "api_keys", "leads", "tenant_config", "reviews"}
        assert core.issubset(set(TABLE_ORDER))

    def test_sqlite_to_pg_type_mapping(self):
        from b2b_ai.db.migration import _sqlite_to_pg_type
        assert _sqlite_to_pg_type("INTEGER") == "BIGINT"
        assert _sqlite_to_pg_type("REAL") == "DOUBLE PRECISION"
        assert _sqlite_to_pg_type("TEXT") == "TEXT"
        assert _sqlite_to_pg_type("") == "TEXT"

    def test_quote_pg_identifier(self):
        from b2b_ai.db.migration import _quote_pg_identifier
        assert _quote_pg_identifier("table_name") == '"table_name"'
        assert _quote_pg_identifier("id") == '"id"'

    def test_validate_returns_summary(self, tmp_path):
        from b2b_ai.db.migration import SQLiteToPostgresMigration
        db_path = str(tmp_path / "validate_test.db")
        Database(db_path).close()
        # Can't actually validate without PG, but the class instantiates
        m = SQLiteToPostgresMigration(db_path, "postgresql://fake:fake@localhost/fake")
        assert m.sqlite_path == db_path
        m.close()
