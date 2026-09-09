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


def test_count_audit_filtra_por_tenant(tmp_db):
    """Regresión: count_audit() no aceptaba tenant_id y por eso un endpoint
    tenant-scoped (GET /api/v1/dashboard/analytics -> _payroll_metrics /
    _report_metrics en api/analytics.py) no tenía forma de pedir el conteo
    de SU tenant, y terminaba mostrando el total global de audit_log de
    TODOS los despachos — una fuga de datos entre tenants real."""
    tid_a = tmp_db.create_tenant("Alpha")
    tid_b = tmp_db.create_tenant("Beta")
    tmp_db.log_call("calcular_nomina", "dispatch", tenant_id=tid_a)
    tmp_db.log_call("calcular_nomina", "dispatch", tenant_id=tid_a)
    tmp_db.log_call("calcular_nomina", "dispatch", tenant_id=tid_b)
    tmp_db.log_call("parse_cfdi", "dispatch", tenant_id=tid_a)

    # Sin tenant_id: sigue agregando todos los tenants (uso legítimo de
    # dashboards/CLI de administración global) — no rompe el default.
    assert tmp_db.count_audit() == 4
    assert tmp_db.count_audit(tool_name="calcular_nomina") == 3

    # Con tenant_id: cada despacho ve SOLO su propia actividad.
    assert tmp_db.count_audit(tenant_id=tid_a) == 3
    assert tmp_db.count_audit(tenant_id=tid_b) == 1
    assert tmp_db.count_audit(tool_name="calcular_nomina", tenant_id=tid_a) == 2
    assert tmp_db.count_audit(tool_name="calcular_nomina", tenant_id=tid_b) == 1
    assert tmp_db.count_audit(tool_name="parse_cfdi", tenant_id=tid_b) == 0


def test_get_api_key_no_expone_key_hash(tmp_db):
    """get_api_key() ya no hace SELECT *: no debe devolver key_hash al
    llamador (misma convención que list_api_keys, que ya lo excluía)."""
    tid = tmp_db.create_tenant("Alpha")
    tmp_db.create_api_key(tid, "prod", "clave-en-claro-123")
    row = tmp_db.get_api_key("clave-en-claro-123")
    assert row is not None
    assert row["tenant_id"] == tid
    assert "key_hash" not in row


def test_list_tenants_conserva_columna_blocked(tmp_db):
    """list_tenants()/get_tenant_by_id() pasaron de SELECT * a columnas
    explícitas: no debe perderse ningún campo que la API expone (blocked
    se usa para el bloqueo de tenants, ver set_tenant_blocked)."""
    tid = tmp_db.create_tenant("Alpha", "AAA010101AAA")
    tmp_db.set_tenant_blocked(tid, True)
    row = next(t for t in tmp_db.list_tenants() if t["id"] == tid)
    assert row["blocked"] in (1, True)
    assert row["name"] == "Alpha"
    assert row["rfc"] == "AAA010101AAA"
    assert "created_at" in row

    by_id = tmp_db.get_tenant_by_id(tid)
    assert by_id == row


def test_notifications_crud(tmp_db):
    tid = tmp_db.create_tenant("A")
    tmp_db.insert_notification(tid, "invoice_processed", "email",
                               "x@y.com", "Asunto", "Cuerpo")
    assert len(tmp_db.list_notifications()) == 1


def test_default_db_es_sqlite(tmp_db):
    assert tmp_db.conn.execute("PRAGMA journal_mode").fetchone()[0] in ("delete", "wal")
