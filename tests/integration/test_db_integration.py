# -*- coding: utf-8 -*-
"""
test_db_integration.py — Integration tests for the database layer.

Covers:
  - CRUD invoices: insert, read, update, delete (list)
  - Tenant queries and isolation
  - DB creation with correct table structure
  - Migration verification (schema_version at max)
"""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.db.models import current_version


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db_int(tmp_path):
    """Returns a fresh Database at a temp path with migrations applied."""
    return Database(str(tmp_path / "db_integ.db"))


def _make_invoice_data(overrides=None):
    """Returns a minimal invoice dict ready for insert_invoice."""
    data = {
        "folio_fiscal": "uu-id-test-001",
        "archivo": "factura_test.xml",
        "fecha": "2026-07-15",
        "tipo": "I",
        "serie": "A",
        "folio": "123",
        "emisor_rfc": "EEM111111111",
        "emisor_nombre": "Emisor Test",
        "receptor_rfc": "REC222222222",
        "subtotal": "1000.00",
        "iva": "160.00",
        "total": "1160.00",
        "moneda": "MXN",
        "descripcion": "Servicio de prueba",
    }
    if overrides:
        data.update(overrides)
    return data


def _make_clasif(overrides=None):
    c = {"categoria": "gasto_operativo", "confianza": 0.92, "razon": "Test"}
    if overrides:
        c.update(overrides)
    return c


def _make_validacion(ok=True):
    return {"ok": ok, "issues": [], "requires_human_review": not ok}


# ---------------------------------------------------------------------------
# 1. DB creation with correct tables
# ---------------------------------------------------------------------------
def test_db_se_crea_con_tablas_correctas(db_int):
    """Verify all expected tables exist after construction."""
    tables = {
        r["name"] for r in db_int.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    required = {"tenants", "users", "invoices", "classifications",
                "audit_log", "notifications", "schema_version",
                "api_keys", "leads", "tenant_config", "reviews",
                "webhook_deliveries", "collection_events",
                "outstanding_invoices", "tenant_usage",
                "webhook_subscriptions", "cuentas_contables",
                "asientos_contables", "balanzas_mensuales",
                "paquetes_contabilidad", "client_users",
                "portal_sessions"}
    missing = required - tables
    assert not missing, f"Faltan tablas: {missing}"


def test_db_migraciones_en_ultima_version(db_int):
    assert db_int.schema_version() == current_version()
    assert db_int.schema_version() >= 8  # at least v8 with perf indexes


# ---------------------------------------------------------------------------
# 2. CRUD invoices
# ---------------------------------------------------------------------------
def test_db_insertar_y_leer_factura(db_int):
    tid = db_int.create_tenant("Tenant CRUD")
    datos = _make_invoice_data()
    clasif = _make_clasif()
    val = _make_validacion()

    inv_id, inserted = db_int.insert_invoice(tid, datos, clasif, val)
    assert inserted is True
    assert inv_id is not None

    # Read by ID
    inv = db_int.get_invoice(inv_id, tenant_id=tid)
    assert inv is not None
    assert inv["folio_fiscal"] == "uu-id-test-001"
    assert inv["categoria"] == "gasto_operativo"
    assert inv["total"] == "1160.00"


def test_db_listar_facturas_con_filtros(db_int):
    tid = db_int.create_tenant("Tenant Filtros")
    base = _make_invoice_data()

    # Insert several invoices with different categories
    cats = ["gasto_operativo", "inversion", "activo_fijo", "nomina",
            "gasto_operativo"]
    for i, cat in enumerate(cats):
        d = _make_invoice_data({"folio_fiscal": f"uuid-filtro-{i}",
                                "total": str(100 + i * 10)})
        c = _make_clasif({"categoria": cat})
        db_int.insert_invoice(tid, d, c, _make_validacion())

    # Filter by categoria
    gastos = db_int.list_invoices(tenant_id=tid, categoria="gasto_operativo")
    assert len(gastos) == 2

    # Filter by valido
    validos = db_int.list_invoices(tenant_id=tid, valido=True)
    assert len(validos) == 5  # all are valid

    # Limit
    limited = db_int.list_invoices(tenant_id=tid, limit=2)
    assert len(limited) == 2


def test_db_factura_no_existe_devuelve_none(db_int):
    inv = db_int.get_invoice(99999)
    assert inv is None


def test_db_conteo_facturas(db_int):
    tid = db_int.create_tenant("Conteo")
    assert db_int.count_invoices(tenant_id=tid) == 0
    d = _make_invoice_data()
    db_int.insert_invoice(tid, d, _make_clasif(), _make_validacion())
    assert db_int.count_invoices(tenant_id=tid) == 1


# ---------------------------------------------------------------------------
# 3. Tenant isolation
# ---------------------------------------------------------------------------
def test_db_tenant_aislamiento_lectura(db_int):
    tid_a = db_int.create_tenant("Alpha")
    tid_b = db_int.create_tenant("Beta")

    db_int.insert_invoice(tid_a, _make_invoice_data({"folio_fiscal": "a-1"}),
                          _make_clasif(), _make_validacion())
    db_int.insert_invoice(tid_a, _make_invoice_data({"folio_fiscal": "a-2"}),
                          _make_clasif(), _make_validacion())

    # Beta sees nothing
    assert db_int.count_invoices(tenant_id=tid_b) == 0
    assert len(db_int.list_invoices(tenant_id=tid_b)) == 0

    # Alpha sees 2
    assert db_int.count_invoices(tenant_id=tid_a) == 2


def test_db_tenant_diferentes_folios_permitidos(db_int):
    tid_a = db_int.create_tenant("Alpha")
    tid_b = db_int.create_tenant("Beta")
    # Same folio_fiscal in different tenants is OK
    datos = _make_invoice_data({"folio_fiscal": "mismo-uuid"})
    id_a, _ = db_int.insert_invoice(tid_a, datos, _make_clasif(),
                                    _make_validacion())
    id_b, _ = db_int.insert_invoice(tid_b, datos, _make_clasif(),
                                    _make_validacion())
    assert id_a != id_b


def test_db_tenant_create_y_query(db_int):
    t1 = db_int.create_tenant("Despacho Uno", "AAA010101AAA")
    t2 = db_int.create_tenant("Despacho Dos", "BBB020202BBB")
    all_t = db_int.list_tenants()
    assert len(all_t) >= 2
    names = {t["name"] for t in all_t}
    assert "Despacho Uno" in names
    assert "Despacho Dos" in names
    # Verify RFC stored
    for t in all_t:
        if t["name"] == "Despacho Uno":
            assert t["rfc"] == "AAA010101AAA"


# ---------------------------------------------------------------------------
# 4. Invoice uniqueness constraint
# ---------------------------------------------------------------------------
def test_db_folio_unico_por_tenant_rechaza_duplicado(db_int):
    tid = db_int.create_tenant("Unico")
    datos = _make_invoice_data()
    id1, ins1 = db_int.insert_invoice(tid, datos, _make_clasif(),
                                      _make_validacion())
    id2, ins2 = db_int.insert_invoice(tid, datos, _make_clasif(),
                                      _make_validacion())
    assert ins1 is True
    assert ins2 is False
    assert id1 == id2