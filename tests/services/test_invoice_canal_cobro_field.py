# -*- coding: utf-8 -*-
"""
REQ-CONC-016 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-CONC —
Conciliación bancaria N-a-1).

Criterio de aceptación exacto:
  "Debe añadirse el campo `canal_cobro` (terminal/spei/cheque/efectivo) e
  `id_terminal` opcional al modelo de factura/cobro pendiente que
  alimenta la conciliación (Invoice/Collection), sin romper los tests
  existentes de tests/test_bank_reconciliation.py y
  tests/test_bank_reconciliation_v2.py (deben seguir pasando 100% tras el
  cambio)."

Dos mitades verificadas aquí:
  1. Persistencia real (Postgres): `invoices` (Invoice) y
     `outstanding_invoices` (Collection -- cartera de cobranza pendiente,
     ver `b2b_ai/services/collections.py`) ganan `canal_cobro`/
     `id_terminal` NULLABLE vía `b2b_ai/db/db.py::insert_invoice/
     get_invoice/list_invoices` y `upsert_outstanding_invoice/
     list_outstanding_invoices` -- el dato sobrevive un roundtrip real de
     INSERT + SELECT. Se salta si no hay B2B_DB_URL (mismo patrón que el
     resto de los tests de integración de este módulo).
  2. El campo, una vez presente en el dict de factura/cobro, es
     directamente consumible por `bank_reconciliation.py` (ya cubierto en
     detalle por REQ-CONC-015,
     tests/services/test_filtrado_por_canal_terminal.py) -- un smoke test
     aquí solo confirma que una factura con ese campo sigue matcheando
     normalmente por 1-a-1 (`_pass_exact`), sin que el campo nuevo
     interfiera con el resto del pipeline.

La regresión explícita que pide el criterio
(tests/test_bank_reconciliation.py y tests/test_bank_reconciliation_v2.py
100% verdes) se corre aparte, no se duplica en este archivo -- ver el
comando previsto del blueprint.
"""
from __future__ import annotations

import os
import uuid

import pytest

from b2b_ai.services.bank_reconciliation import BankReconciliation

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


def _split_dsn(dsn):
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


@pytest.fixture
def test_dsn():
    """Base de test efímera y aislada -- nunca corre contra la base local
    compartida (`Database(dsn)` aplica `alembic upgrade heads` al abrir,
    así que debe apuntar siempre a una base dedicada, creada y dropeada
    por este fixture)."""
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_reqconc016_{uuid.uuid4().hex[:10]}"
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()
    dsn = f"{server_dsn}/{dbname}"
    yield dsn
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        # `Database` mantiene un pool de conexiones module-level por DSN
        # (`_get_pg_pool`) que sigue vivo aunque `db.close()` sólo las
        # devuelva al pool -- hay que forzar el cierre de esas sesiones
        # sobre ESTA base efímera antes de poder dropearla.
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid <> pg_backend_pid()", (dbname,))
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1) Persistencia real: roundtrip INSERT + SELECT contra Postgres.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL no disponible")
def test_invoice_canal_cobro_sobrevive_insert_y_select_real(test_dsn):
    from b2b_ai.db.db import Database

    db = Database(test_dsn)
    try:
        with db.conn:
            cur = db.conn.execute(
                "INSERT INTO tenants (name) VALUES ('Test REQ-CONC-016') "
                "RETURNING id")
            tenant_id = cur.fetchone()[0]

        datos = {
            "folio_fiscal": "UUID-CONC-016-1", "archivo": "f.xml",
            "fecha": "2026-07-01", "total": "1000.00",
            "canal_cobro": "terminal", "id_terminal": "TERM-CLIP-01",
        }
        invoice_id, inserted = db.insert_invoice(
            tenant_id, datos, {"categoria": "ingreso", "confianza": 0.9,
                               "razon": "test"},
            {"ok": True, "requires_human_review": False, "issues": []})
        assert inserted

        row = db.get_invoice(invoice_id, tenant_id=tenant_id)
        assert row is not None
        assert row.get("canal_cobro") == "terminal"
        assert row.get("id_terminal") == "TERM-CLIP-01"

        listado = db.list_invoices(tenant_id=tenant_id)
        assert any(r["id"] == invoice_id and r.get("canal_cobro") == "terminal"
                  for r in listado)
    finally:
        db.close()


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL no disponible")
def test_invoice_sin_canal_cobro_queda_null_nunca_inventado(test_dsn):
    """Una factura insertada SIN canal_cobro/id_terminal (caso normal,
    dato opcional) debe leerse con ambos en NULL -- nunca un default
    inventado."""
    from b2b_ai.db.db import Database

    db = Database(test_dsn)
    try:
        with db.conn:
            cur = db.conn.execute(
                "INSERT INTO tenants (name) VALUES "
                "('Test REQ-CONC-016 sin canal') RETURNING id")
            tenant_id = cur.fetchone()[0]

        datos = {"folio_fiscal": "UUID-CONC-016-2", "archivo": "f2.xml",
                 "fecha": "2026-07-02", "total": "500.00"}
        invoice_id, _ = db.insert_invoice(
            tenant_id, datos, {"categoria": "ingreso", "confianza": 0.9,
                               "razon": "test"},
            {"ok": True, "requires_human_review": False, "issues": []})

        row = db.get_invoice(invoice_id, tenant_id=tenant_id)
        assert row.get("canal_cobro") is None
        assert row.get("id_terminal") is None
    finally:
        db.close()


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL no disponible")
def test_outstanding_invoice_canal_cobro_sobrevive_upsert_real(test_dsn):
    from b2b_ai.db.db import Database

    db = Database(test_dsn)
    try:
        with db.conn:
            cur = db.conn.execute(
                "INSERT INTO tenants (name) VALUES "
                "('Test REQ-CONC-016 outstanding') RETURNING id")
            tenant_id = cur.fetchone()[0]

        db.upsert_outstanding_invoice(
            tenant_id, "FACT-COLL-1", 1234.56, "2026-08-01",
            dias_vencido=10, score=0.5,
            canal_cobro="spei", id_terminal="CLABE-000111222")

        rows = db.list_outstanding_invoices(tenant_id=tenant_id,
                                            factura_id="FACT-COLL-1")
        assert len(rows) == 1
        assert rows[0]["canal_cobro"] == "spei"
        assert rows[0]["id_terminal"] == "CLABE-000111222"

        # Upsert de nuevo (mismo tenant+factura) debe actualizar el canal.
        db.upsert_outstanding_invoice(
            tenant_id, "FACT-COLL-1", 1234.56, "2026-08-01",
            dias_vencido=15, score=0.6,
            canal_cobro="terminal", id_terminal="TERM-99")
        rows = db.list_outstanding_invoices(tenant_id=tenant_id,
                                            factura_id="FACT-COLL-1")
        assert len(rows) == 1
        assert rows[0]["canal_cobro"] == "terminal"
        assert rows[0]["id_terminal"] == "TERM-99"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2) Smoke test: el campo no interfiere con el resto del pipeline.
# ---------------------------------------------------------------------------

def test_factura_con_canal_cobro_sigue_matcheando_1_a_1_normal():
    svc = BankReconciliation()
    invoices = [{
        "folio_fiscal": "F-1", "fecha": "2026-07-10", "total": "850.00",
        "emisor": "Proveedor", "emisor_nombre": "Proveedor",
        "canal_cobro": "terminal", "id_terminal": "TERM-1",
    }]
    tx = [{
        "id": "tx1", "fecha": "2026-07-10", "monto": "850.00",
        "monto_signed": "850.00", "naturaleza": "abono",
        "descripcion": "", "ref": "F-1", "banco": "generico",
    }]

    matches = svc.match_transactions(invoices, tx)

    assert len(matches) == 1
    assert matches[0]["method"] == "exact"
    assert matches[0]["invoice_ref"] == "F-1"
