# -*- coding: utf-8 -*-
"""Tests de la capa de base de datos multi-tenant."""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.db.models import current_version


def test_migraciones_aplican(tmp_db):
    assert tmp_db.schema_version() == current_version()
    assert tmp_db.schema_version() >= 1


def test_crud_tenants_y_users(tmp_db):
    tid = tmp_db.create_tenant("Despacho Alpha", "AAA010101AAA")
    tid2 = tmp_db.create_tenant("Despacho Beta", "BBB010101BBB")
    assert len(tmp_db.list_tenants()) == 2
    uid = tmp_db.create_user(tid, "Contador 1", "c1@a.com")
    assert uid is not None


def test_aislamiento_multi_tenant(tmp_db):
    tid_a = tmp_db.create_tenant("Alpha")
    tid_b = tmp_db.create_tenant("Beta")
    datos = {"folio_fiscal": "u-1", "archivo": "a.xml", "fecha": "2026-07-01",
             "tipo": "I", "emisor_rfc": "X1", "emisor_nombre": "E",
             "receptor_rfc": "X2", "subtotal": "100", "iva": "16",
             "total": "116", "moneda": "MXN", "descripcion": "x"}
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"}
    val = {"ok": True, "issues": [], "requires_human_review": False}
    tmp_db.insert_invoice(tid_a, datos, clasif, val)
    # Beta no debe ver la factura de Alpha
    assert tmp_db.count_invoices(tenant_id=tid_a) == 1
    assert tmp_db.count_invoices(tenant_id=tid_b) == 0
    assert len(tmp_db.list_invoices(tenant_id=tid_b)) == 0


def test_folio_unico_por_tenant(tmp_db):
    tid = tmp_db.create_tenant("A")
    datos = {"folio_fiscal": "u-dup", "archivo": "a.xml", "fecha": "2026-07-01",
             "tipo": "I", "emisor_rfc": "X1", "emisor_nombre": "E",
             "receptor_rfc": "X2", "subtotal": "100", "iva": "16",
             "total": "116", "moneda": "MXN", "descripcion": "x"}
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"}
    val = {"ok": True, "issues": [], "requires_human_review": False}
    id1, ins1 = tmp_db.insert_invoice(tid, datos, clasif, val)
    id2, ins2 = tmp_db.insert_invoice(tid, datos, clasif, val)
    assert ins1 is True and ins2 is False
    assert id1 == id2


def test_audit_log(tmp_db):
    tmp_db.log_call("parse_cfdi", "dispatch", payload={"ok": 1},
                    status="ok", tenant_id=1)
    tmp_db.log_call("parse_cfdi", "dispatch", payload={"ok": 2},
                    status="ok", tenant_id=1)
    tmp_db.log_call("validate_cfdi", "dispatch", status="error", tenant_id=1)
    assert tmp_db.count_audit() == 3
    assert tmp_db.count_audit("parse_cfdi") == 2
    rows = tmp_db.list_audit(tool_name="validate_cfdi")
    assert len(rows) == 1 and rows[0]["status"] == "error"


def test_notifications_crud(tmp_db):
    tid = tmp_db.create_tenant("A")
    tmp_db.insert_notification(tid, "invoice_processed", "email",
                               "x@y.com", "Asunto", "Cuerpo")
    assert len(tmp_db.list_notifications()) == 1


def test_default_db_es_sqlite(tmp_db):
    assert tmp_db.conn.execute("PRAGMA journal_mode").fetchone()[0] in ("delete", "wal")
