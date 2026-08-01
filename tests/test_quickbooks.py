# -*- coding: utf-8 -*-
"""
test_quickbooks.py — Tests completos del conector QuickBooks Online.

Cubre: mock mode, register_invoice, create_voucher, get_invoice, health,
check_connection, get_account_catalog, create_bill, create_invoice,
list_vendors, list_customers, edge cases (sin folio, total None).
"""
from __future__ import annotations

import pytest

from b2b_ai.erp.quickbooks import QuickBooksConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def qbo():
    """Instancia mock de QuickBooksConnector."""
    return QuickBooksConnector(empresa="Test Despacho", mock=True)


@pytest.fixture
def sample_voucher():
    """Póliza de ejemplo para tests."""
    return {
        "folio_fiscal": "A1B2C3D4-E5F6-7890-ABCD-EF1234567890",
        "emisor_rfc": "EMX010101AAA",
        "total": "15000.00",
        "fecha": "2026-08-01",
        "categoria": "gasto_operativo",
        "concepto": "Servicios de consultoría",
    }


# ---------------------------------------------------------------------------
# Basic initialization
# ---------------------------------------------------------------------------

class TestQuickBooksInit:
    def test_explicit_mock(self):
        qbo = QuickBooksConnector(mock=True)
        assert qbo._mock is True

    def test_explicit_no_mock(self):
        qbo = QuickBooksConnector(mock=False, company_id="123", access_token="tok")
        assert qbo._mock is False

    def test_empresa_set(self, qbo):
        assert qbo.empresa == "Test Despacho"

    def test_company_id_from_env(self, monkeypatch):
        monkeypatch.setenv("QBO_COMPANY_ID", "12345678")
        monkeypatch.setenv("QBO_ACCESS_TOKEN", "test_token")
        monkeypatch.setenv("QBO_MOCK_MODE", "0")
        qbo = QuickBooksConnector()
        assert qbo.company_id == "12345678"
        assert qbo.access_token == "test_token"


# ---------------------------------------------------------------------------
# create_voucher (AbstractERPConnector)
# ---------------------------------------------------------------------------

class TestCreateVoucher:
    def test_success(self, qbo, sample_voucher):
        result = qbo.create_voucher(sample_voucher)
        assert result["ok"] is True
        assert result["poliza"].startswith("QBO-")
        assert result["cuenta_cargo"] == "6131 Gastos generales"
        assert result["cuenta_abono"] == "1130 Bancos"
        assert result["status"] == "registrada"
        assert "mock" in result["message"].lower()

    def test_audit_ref_present(self, qbo, sample_voucher):
        result = qbo.create_voucher(sample_voucher)
        assert "audit_ref" in result
        assert result["audit_ref"].startswith("QBO-")

    def test_sin_folio_fiscal(self, qbo):
        result = qbo.create_voucher({"emisor_rfc": "XAXX010101000"})
        assert result["ok"] is False
        assert result["poliza"] is None
        assert result["status"] == "error"
        assert "folio fiscal" in result["message"].lower()

    def test_folio_from_concepto(self, qbo):
        result = qbo.create_voucher({"concepto": "Póliza manual"})
        assert result["ok"] is True
        assert result["poliza"].startswith("QBO-")

    def test_categorias_diferentes(self, qbo):
        for cat, expected_cargo in [
            ("gasto_operativo", "6131 Gastos generales"),
            ("inversion", "1115 Gastos de instalacion"),
            ("activo_fijo", "1210 Mobiliario y equipo"),
            ("nomina", "6110 Sueldos y salarios"),
            ("desconocido", "6100 Gastos por clasificar"),
        ]:
            result = qbo.create_voucher({
                "folio_fiscal": f"folio-{cat}",
                "categoria": cat,
                "total": "1000",
            })
            assert result["ok"] is True
            assert result["cuenta_cargo"] == expected_cargo

    def test_total_none_tolerance(self, qbo):
        result = qbo.create_voucher({
            "folio_fiscal": "folio-none-total",
            "total": None,
        })
        assert result["ok"] is True

    def test_voucher_persisted(self, qbo, sample_voucher):
        qbo.create_voucher(sample_voucher)
        found = qbo.get_invoice(sample_voucher["folio_fiscal"])
        assert found is not None
        assert found["poliza"].startswith("QBO-")

    def test_multiple_vouchers(self, qbo):
        for i in range(5):
            result = qbo.create_voucher({
                "folio_fiscal": f"folio-{i:03d}",
                "total": str(i * 1000),
                "categoria": "gasto_operativo",
            })
            assert result["ok"] is True
        assert len(qbo._polizas) == 5


# ---------------------------------------------------------------------------
# get_invoice / register_invoice (ERPInterface)
# ---------------------------------------------------------------------------

class TestERPInterface:
    def test_register_invoice_alias(self, qbo, sample_voucher):
        result = qbo.register_invoice(sample_voucher)
        assert result["ok"] is True

    def test_get_invoice_found(self, qbo, sample_voucher):
        qbo.create_voucher(sample_voucher)
        found = qbo.get_invoice(sample_voucher["folio_fiscal"])
        assert found is not None
        assert found["folio_fiscal"] == sample_voucher["folio_fiscal"]

    def test_get_invoice_not_found(self, qbo):
        found = qbo.get_invoice("nonexistent-uuid")
        assert found is None


# ---------------------------------------------------------------------------
# health / check_connection
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_mock(self, qbo):
        h = qbo.health()
        assert h["ok"] is True
        assert "mock" in h["backend"].lower()
        assert h["mock"] is True
        assert h["voucher_count"] == 0

    def test_health_after_voucher(self, qbo, sample_voucher):
        qbo.create_voucher(sample_voucher)
        h = qbo.health()
        assert h["voucher_count"] == 1

    def test_check_connection_mock(self, qbo):
        conn = qbo.check_connection()
        assert conn["ok"] is True
        assert "mock" in conn["backend"].lower()
        assert "audit_ref" in conn
        assert "audited_at" in conn

    def test_check_connection_no_creds(self):
        qbo = QuickBooksConnector(mock=False, company_id="", access_token="")
        conn = qbo.check_connection()
        assert conn["ok"] is False
        assert "QBO_COMPANY_ID" in conn["detail"]


# ---------------------------------------------------------------------------
# Account catalog
# ---------------------------------------------------------------------------

class TestAccountCatalog:
    def test_catalog_returns_list(self, qbo):
        catalog = qbo.get_account_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) > 0

    def test_catalog_has_required_fields(self, qbo):
        catalog = qbo.get_account_catalog()
        for acct in catalog:
            assert "codigo" in acct
            assert "descripcion" in acct
            assert "tipo" in acct

    def test_catalog_cached(self, qbo):
        c1 = qbo.get_account_catalog()
        c2 = qbo.get_account_catalog()
        assert c1 is c2  # same cached list

    def test_catalog_includes_key_accounts(self, qbo):
        codigos = {a["codigo"] for a in qbo.get_account_catalog()}
        assert "1130" in codigos  # Bancos
        assert "6100" in codigos  # Gastos por clasificar
        assert "6110" in codigos  # Sueldos y salarios
        assert "2010" in codigos  # Proveedores


# ---------------------------------------------------------------------------
# QBO-specific: Bill, Invoice, Vendor, Customer
# ---------------------------------------------------------------------------

class TestQBOBill:
    def test_create_bill_mock(self, qbo):
        result = qbo.create_bill(
            vendor_name="Proveedor ABC",
            line_items=[
                {"description": "Servicio A", "amount": 5000},
                {"description": "Servicio B", "amount": 3000},
            ],
            due_date="2026-09-01",
        )
        assert result["ok"] is True
        assert result["bill_id"].startswith("QBO-BILL-")
        assert result["vendor"] == "Proveedor ABC"
        assert result["total"] == 8000
        assert result["due_date"] == "2026-09-01"

    def test_create_bill_empty_items(self, qbo):
        result = qbo.create_bill("Proveedor", line_items=[])
        assert result["ok"] is True
        assert result["total"] == 0


class TestQBOInvoice:
    def test_create_invoice_mock(self, qbo):
        result = qbo.create_invoice(
            customer_name="Cliente XYZ",
            line_items=[
                {"description": "Consultoría", "amount": 25000},
            ],
            due_date="2026-09-15",
        )
        assert result["ok"] is True
        assert result["invoice_id"].startswith("QBO-INV-")
        assert result["customer"] == "Cliente XYZ"
        assert result["total"] == 25000

    def test_create_invoice_no_date(self, qbo):
        result = qbo.create_invoice("Cliente", line_items=[{"description": "X", "amount": 100}])
        assert result["ok"] is True
        assert result["due_date"] == ""


class TestQBOLists:
    def test_list_vendors(self, qbo):
        vendors = qbo.list_vendors()
        assert isinstance(vendors, list)
        assert len(vendors) > 0
        assert "name" in vendors[0]

    def test_list_customers(self, qbo):
        customers = qbo.list_customers()
        assert isinstance(customers, list)
        assert len(customers) > 0
        assert "name" in customers[0]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_voucher(self, qbo):
        result = qbo.create_voucher({})
        assert result["ok"] is False

    def test_voucher_with_extra_fields(self, qbo):
        result = qbo.create_voucher({
            "folio_fiscal": "extra-fields-test",
            "total": "5000",
            "random_field": "ignored",
            "another": 42,
        })
        assert result["ok"] is True

    def test_unicode_folio(self, qbo):
        result = qbo.create_voucher({
            "folio_fiscal": "FOLIO-Ñ-ACENTOS-ÁÉÍÓÚ",
            "total": "1000",
        })
        assert result["ok"] is True

    def test_negative_total(self, qbo):
        result = qbo.create_voucher({
            "folio_fiscal": "neg-total",
            "total": "-5000",
        })
        assert result["ok"] is True

    def test_very_large_total(self, qbo):
        result = qbo.create_voucher({
            "folio_fiscal": "large-total",
            "total": "999999999.99",
        })
        assert result["ok"] is True
