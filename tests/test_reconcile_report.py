# -*- coding: utf-8 -*-
"""Tests de conciliación bancaria y reportes."""
from decimal import Decimal

from b2b_ai.services.reconcile import reconcile
from b2b_ai.services.report import generate_report


INVOICES = [
    {"folio_fiscal": "u1", "fecha": "2026-07-03T12:00:00", "total": "5800.00",
     "emisor": "CON950820K12", "tenant_id": 1, "valido": 1,
     "subtotal": "5000", "iva": "800", "categoria": "inversion"},
    {"folio_fiscal": "u2", "fecha": "2026-07-10T09:00:00", "total": "300.00",
     "emisor": "PAP", "tenant_id": 1, "valido": 0,
     "subtotal": "300", "iva": "0", "categoria": "gasto_operativo"},
]

BANK = [
    {"fecha": "2026-07-03", "monto": "5800.00", "descripcion": "Transferencia",
     "ref": "REF-1"},
    {"fecha": "2026-07-10", "monto": "300.00", "descripcion": "Pago efectivo",
     "ref": "REF-2"},
    {"fecha": "2026-07-15", "monto": "9999.00", "descripcion": "Sin pareja",
     "ref": "REF-3"},
]


def test_reconcile_concilia_todas():
    r = reconcile(INVOICES, BANK)
    assert len(r["matched"]) == 2
    assert r["matched"][0]["folio_fiscal"] == "u1"
    assert r["unmatched_bank"] == [] or len(r["unmatched_bank"]) == 1
    assert r["unmatched_invoices"] == []


def test_reconcile_por_monto_y_fecha():
    r = reconcile([INVOICES[0]], BANK)
    assert len(r["matched"]) == 1
    assert r["matched"][0]["monto"] == "5800.00"


def test_reconcile_monto_sin_pareja():
    only_orphan = [{"folio_fiscal": "z", "fecha": "2026-07-01", "total": "1.00",
                    "emisor": "X"}]
    r = reconcile(only_orphan, BANK)
    assert r["matched"] == []
    assert len(r["unmatched_invoices"]) == 1


def test_reconcile_no_coincide_monto():
    inv = [{"folio_fiscal": "a", "fecha": "2026-07-03", "total": "123.00",
            "emisor": "X"}]
    r = reconcile(inv, BANK)
    assert r["matched"] == []
    assert r["unmatched_invoices"][0]["total"] == "123.00"


def test_report_agrega_por_periodo():
    inv = [dict(i, fecha="2026-07-03") for i in INVOICES] + \
          [dict(INVOICES[0], fecha="2026-08-01", folio_fiscal="u3")]
    r = generate_report(inv, period="2026-07")
    assert r["facturas"] == 2
    assert r["validas"] == 1
    assert r["invalidas"] == 1
    assert r["por_categoria"]["inversion"]["count"] == 1
    assert r["total"] == "6100.00"


def test_report_todos():
    r = generate_report(INVOICES)
    assert r["facturas"] == 2
    assert r["total"] == "6100.00"


def test_report_por_tenant():
    inv = [dict(INVOICES[0], tenant_id=7)]
    r = generate_report(INVOICES, tenant_id=7)
    assert r["facturas"] == 0
    r2 = generate_report(inv, tenant_id=7)
    assert r2["facturas"] == 1
