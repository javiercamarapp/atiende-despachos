# -*- coding: utf-8 -*-
"""Integración: la capa Database completa corre contra PostgreSQL.

Reutiliza los mismos métodos que los tests SQLite (test_db.py) pero apunta
Database() al DSN de PG. Verifica que el contrato de datos se preserva.
"""
import os

import pytest

from b2b_ai.db.db import Database

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


pytestmark = pytest.mark.skipif(not _pg_available(),
                                reason="B2B_DB_URL PostgreSQL no disponible")


@pytest.fixture
def pg_db(tmp_path):
    """Database() sobre PostgreSQL (limpiada de datos previos de negocio)."""
    db = Database(PG_DSN)
    # Limpieza: el esquema viene de Alembic; solo borramos datos de negocio
    # para que el test sea determinista.
    for t in ("portal_sessions", "client_users", "classifications", "invoices",
              "reviews", "notifications", "audit_log", "api_keys", "users",
              "tenant_config", "tenant_usage", "webhook_deliveries",
              "webhook_subscriptions", "outstanding_invoices",
              "collection_events", "leads", "asientos_contables",
              "balanzas_mensuales", "paquetes_contabilidad", "cuentas_contables",
              "tenants"):
        try:
            db.conn.execute(f"DELETE FROM {t}")
        except Exception:  # noqa: BLE001
            pass
    db.conn.commit()
    yield db
    db.close()


def test_migraciones_aplican_pg(pg_db):
    assert pg_db.schema_version() >= 1


def test_crud_tenants_pg(pg_db):
    tid = pg_db.create_tenant("Despacho PG", "PG010101AAA")
    tid2 = pg_db.create_tenant("Despacho PG2", "PG010101AAB")
    assert len(pg_db.list_tenants()) == 2
    uid = pg_db.create_user(tid, "Contador", "c@pg.com")
    assert uid is not None


def test_aislamiento_multitenant_pg(pg_db):
    a = pg_db.create_tenant("AlphaPG")
    b = pg_db.create_tenant("BetaPG")
    datos = {"folio_fiscal": "pg-1", "archivo": "a.xml", "fecha": "2026-07-01",
             "tipo": "I", "emisor_rfc": "X1", "emisor_nombre": "E",
             "receptor_rfc": "X2", "subtotal": "100", "iva": "16",
             "total": "116", "moneda": "MXN", "descripcion": "x"}
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"}
    val = {"ok": True, "issues": [], "requires_human_review": False}
    pg_db.insert_invoice(a, datos, clasif, val)
    assert pg_db.count_invoices(tenant_id=a) == 1
    assert pg_db.count_invoices(tenant_id=b) == 0


def test_folio_unico_pg(pg_db):
    tid = pg_db.create_tenant("A")
    datos = {"folio_fiscal": "pg-dup", "archivo": "a.xml", "fecha": "2026-07-01",
             "tipo": "I", "emisor_rfc": "X1", "emisor_nombre": "E",
             "receptor_rfc": "X2", "subtotal": "100", "iva": "16",
             "total": "116", "moneda": "MXN", "descripcion": "x"}
    clasif = {"categoria": "gasto", "confianza": 0.9, "razon": "r"}
    val = {"ok": True, "issues": [], "requires_human_review": False}
    id1, ins1 = pg_db.insert_invoice(tid, datos, clasif, val)
    id2, ins2 = pg_db.insert_invoice(tid, datos, clasif, val)
    assert ins1 is True and ins2 is False
    assert id1 == id2


def test_audit_y_notifications_pg(pg_db):
    tid = pg_db.create_tenant("A")
    pg_db.log_call("parse", "dispatch", payload={"ok": 1}, status="ok",
                   tenant_id=tid)
    pg_db.log_call("validate", "dispatch", status="error", tenant_id=tid)
    assert pg_db.count_audit() == 2
    pg_db.insert_notification(tid, "invoice_processed", "email", "x@y.com",
                              "Asunto", "Cuerpo")
    assert len(pg_db.list_notifications()) == 1


def test_upsert_contracts_pg(pg_db):
    tid = pg_db.create_tenant("A")
    # tenant_config upsert
    pg_db.set_tenant_config(tid, "erp", "contpaqi")
    pg_db.set_tenant_config(tid, "erp", "aspel")
    assert pg_db.get_tenant_config(tid, "erp") == "aspel"
    # outstanding invoice upsert
    pg_db.upsert_outstanding_invoice(tid, "FAC-1", 100.0, "2026-08-01")
    pg_db.upsert_outstanding_invoice(tid, "FAC-1", 250.0, "2026-08-01",
                                     dias_vencido=5)
    row = pg_db.list_outstanding_invoices(tenant_id=tid)[0]
    assert row["monto"] == 250.0
