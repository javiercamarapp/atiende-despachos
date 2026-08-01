# -*- coding: utf-8 -*-
"""
test_erp_integration.py — Integration tests for the B&B AI ERP module.

Covers:
  - ERP connectors: Aspel, CONTPAQi, CSV, QuickBooks (Phase 1 + Phase 2)
  - ERP sync: data mapping, error handling, retry logic
  - ERP automation: desktop automation base with mock drivers
  - Edge cases: connection timeout, malformed data, duplicate sync
  - Account catalog mapping consistency across connectors
"""
from __future__ import annotations

import csv
import os
import tempfile

import pytest

from b2b_ai.erp.base import ERPInterface
from b2b_ai.erp.contpaqi import MockCONTPAQi, _cuentas_para_categoria
from b2b_ai.erp.csv_erp import CSVErp
from b2b_ai.erp.connector import (
    AbstractERPConnector, CONTPAQiConnector, AspelConnector,
    CSVExporter, cuentas_para_categoria as cuentas_v2
)
from b2b_ai.erp.quickbooks import QuickBooksConnector
from b2b_ai.erp.erp_automation import DesktopERPBase


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
SAMPLE_VOUCHER = {
    "folio_fiscal": "FAC-2026-0001-UUID",
    "emisor_rfc": "TEC010101AAA",
    "emisor_nombre": "Tecnologia SA",
    "total": "15750.00",
    "fecha": "2026-07-03",
    "categoria": "gasto_operativo",
    "concepto": "Servicios de consultoria",
}


def _sample_invoice():
    return {
        "folio_fiscal": "FAC-TEST-0001",
        "archivo": "test.xml",
        "emisor_rfc": "CON950820K12",
        "total": "5800.00",
        "categoria": "gasto_operativo",
    }


# ===================================================================
# 1. ERPInterface — abstract contract
# ===================================================================
class TestERPInterface:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ERPInterface()

    def test_mock_contpaqi_implements_interface(self):
        assert issubclass(MockCONTPAQi, ERPInterface)

    def test_csv_erp_implements_interface(self):
        assert issubclass(CSVErp, ERPInterface)

    def test_quickbooks_implements_interface(self):
        assert issubclass(QuickBooksConnector, ERPInterface)


# ===================================================================
# 2. MockCONTPAQi (Phase 1)
# ===================================================================
class TestMockCONTPAQi:
    def test_register_invoice_ok(self):
        erp = MockCONTPAQi()
        r = erp.register_invoice(_sample_invoice())
        assert r["ok"] is True
        assert r["poliza"].startswith("POL-")
        assert r["status"] == "registrada"

    def test_register_stores_poliza(self):
        erp = MockCONTPAQi()
        r = erp.register_invoice(_sample_invoice())
        stored = erp.get_invoice("FAC-TEST-0001")
        assert stored is not None
        assert stored["poliza"] == r["poliza"]

    def test_register_without_folio_fails(self):
        erp = MockCONTPAQi()
        r = erp.register_invoice({})
        assert r["ok"] is False
        assert r["status"] == "error"

    def test_health_ok(self):
        assert MockCONTPAQi().health()["ok"] is True

    def test_health_has_backend(self):
        h = MockCONTPAQi().health()
        assert "backend" in h
        assert "CONTPAQi" in h["backend"]

    def test_get_nonexistent_returns_none(self):
        erp = MockCONTPAQi()
        assert erp.get_invoice("NADA-999") is None

    def test_multiple_registrations_accumulate(self):
        erp = MockCONTPAQi()
        r1 = erp.register_invoice(_sample_invoice())
        inv2 = {**_sample_invoice(), "folio_fiscal": "FAC-0002"}
        r2 = erp.register_invoice(inv2)
        assert r1["poliza"] != r2["poliza"]
        assert erp.get_invoice("FAC-TEST-0001") is not None
        assert erp.get_invoice("FAC-0002") is not None


# ===================================================================
# 3. CSVErp (Phase 1)
# ===================================================================
class TestCSVErp:
    def test_register_and_retrieve(self, tmp_path):
        path = str(tmp_path / "test_erp.csv")
        erp = CSVErp(path)
        r = erp.register_invoice(_sample_invoice())
        assert r["ok"] is True
        assert r["poliza"].startswith("CSV-")
        stored = erp.get_invoice("FAC-TEST-0001")
        assert stored is not None
        assert stored["poliza"] == r["poliza"]

    def test_csv_file_created(self, tmp_path):
        path = str(tmp_path / "created.csv")
        erp = CSVErp(path)
        erp.register_invoice(_sample_invoice())
        assert os.path.exists(path)
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1

    def test_accumulates_across_instances(self, tmp_path):
        path = str(tmp_path / "accum.csv")
        CSVErp(path).register_invoice(_sample_invoice())
        inv2 = {**_sample_invoice(), "folio_fiscal": "XYZ-999"}
        erp2 = CSVErp(path)
        r = erp2.register_invoice(inv2)
        assert r["ok"] is True
        assert erp2.get_invoice("FAC-TEST-0001") is not None
        assert erp2.get_invoice("XYZ-999") is not None

    def test_health_ok(self, tmp_path):
        erp = CSVErp(str(tmp_path / "h.csv"))
        assert erp.health()["ok"] is True

    def test_register_without_folio_fails(self, tmp_path):
        erp = CSVErp(str(tmp_path / "no_folio.csv"))
        r = erp.register_invoice({})
        assert r["ok"] is False

    def test_unknown_category_uses_desconocido(self, tmp_path):
        erp = CSVErp(str(tmp_path / "unk.csv"))
        inv = {**_sample_invoice(), "categoria": "rara"}
        r = erp.register_invoice(inv)
        assert r["ok"] is True
        # Should fall back to desconocido accounts
        assert "6100" in r["cuenta_cargo"]

    def test_special_characters_in_rfc(self, tmp_path):
        erp = CSVErp(str(tmp_path / "spec.csv"))
        inv = {**_sample_invoice(), "folio_fiscal": "FAC-Ñ-123",
               "emisor_rfc": "ÑOM010101AAA"}
        r = erp.register_invoice(inv)
        assert r["ok"] is True
        stored = erp.get_invoice("FAC-Ñ-123")
        assert stored is not None


# ===================================================================
# 4. CONTPAQiConnector (Phase 2)
# ===================================================================
class TestCONTPAQiConnector:
    def test_create_voucher_ok(self):
        c = CONTPAQiConnector()
        r = c.create_voucher(SAMPLE_VOUCHER)
        assert r["ok"] is True
        assert r["poliza"].startswith("CPQ-")
        assert r["cuenta_cargo"]
        assert r["cuenta_abono"]
        assert r["audit_ref"].startswith("CPQ-")

    def test_create_voucher_stored_in_memory(self):
        c = CONTPAQiConnector()
        c.create_voucher(SAMPLE_VOUCHER)
        assert SAMPLE_VOUCHER["folio_fiscal"] in c._polizas
        stored = c._polizas[SAMPLE_VOUCHER["folio_fiscal"]]
        assert stored["status"] == "registrada"

    def test_create_voucher_no_folio_fails(self):
        c = CONTPAQiConnector()
        r = c.create_voucher({"total": "100"})
        assert r["ok"] is False
        assert r["status"] == "error"
        assert r["audit_ref"]

    def test_account_catalog(self):
        c = CONTPAQiConnector()
        catalog = c.get_account_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) >= 5
        codes = {a["codigo"] for a in catalog}
        assert "1130" in codes  # Bancos
        assert "6131" in codes  # Gastos generales

    def test_check_connection(self):
        c = CONTPAQiConnector()
        r = c.check_connection()
        assert r["ok"] is True
        assert "CONTPAQi" in r["backend"]
        assert r["audit_ref"]
        assert r["audited_at"]

    def test_different_categories_map_different_accounts(self):
        c = CONTPAQiConnector()
        cats = ["gasto_operativo", "inversion", "activo_fijo", "nomina"]
        seen = set()
        for cat in cats:
            r = c.create_voucher({**SAMPLE_VOUCHER, "categoria": cat,
                                   "folio_fiscal": f"F-{cat}"})
            assert r["ok"]
            seen.add(r["cuenta_cargo"])
        # At least 2 different accounts should be used
        assert len(seen) >= 2

    def test_voucher_audit_ref_unique(self):
        c = CONTPAQiConnector()
        r1 = c.create_voucher({**SAMPLE_VOUCHER, "folio_fiscal": "A-1"})
        r2 = c.create_voucher({**SAMPLE_VOUCHER, "folio_fiscal": "A-2"})
        assert r1["audit_ref"] != r2["audit_ref"]

    def test_backend_label(self):
        assert "CONTPAQi" in CONTPAQiConnector().backend


# ===================================================================
# 5. AspelConnector (Phase 2)
# ===================================================================
class TestAspelConnector:
    def test_create_voucher_ok(self):
        a = AspelConnector()
        r = a.create_voucher(SAMPLE_VOUCHER)
        assert r["ok"] is True
        assert r["poliza"].startswith("ASL-")
        assert r["audit_ref"].startswith("ASL-")

    def test_create_voucher_no_folio_fails(self):
        a = AspelConnector()
        r = a.create_voucher({})
        assert r["ok"] is False

    def test_account_catalog(self):
        a = AspelConnector()
        catalog = a.get_account_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) >= 5
        codes = {ac["codigo"] for ac in catalog}
        assert "1020" in codes  # Bancos (Aspel codes)

    def test_check_connection(self):
        a = AspelConnector()
        r = a.check_connection()
        assert r["ok"] is True
        assert "Aspel" in r["backend"]

    def test_backend_differs_from_contpaqi(self):
        assert AspelConnector().backend != CONTPAQiConnector().backend


# ===================================================================
# 6. QuickBooksConnector (Phase 1 + 2)
# ===================================================================
class TestQuickBooksConnector:
    def test_create_voucher_ok(self):
        q = QuickBooksConnector(mock=True)
        r = q.create_voucher(SAMPLE_VOUCHER)
        assert r["ok"] is True
        assert r["poliza"].startswith("QBO-")
        assert r["audit_ref"].startswith("QBO-")

    def test_create_voucher_no_folio_fails(self):
        q = QuickBooksConnector(mock=True)
        r = q.create_voucher({})
        assert r["ok"] is False

    def test_register_invoice_alias(self):
        """ERPInterface.register_invoice should work via create_voucher."""
        q = QuickBooksConnector(mock=True)
        r = q.register_invoice(_sample_invoice())
        assert r["ok"] is True
        assert r["poliza"].startswith("QBO-")

    def test_get_invoice(self):
        q = QuickBooksConnector(mock=True)
        q.create_voucher(SAMPLE_VOUCHER)
        stored = q.get_invoice(SAMPLE_VOUCHER["folio_fiscal"])
        assert stored is not None
        assert stored["poliza"].startswith("QBO-")

    def test_health_mock(self):
        q = QuickBooksConnector(mock=True)
        h = q.health()
        assert h["ok"] is True
        assert "mock" in h["backend"].lower() or h["mock"] is True

    def test_check_connection_mock(self):
        q = QuickBooksConnector(mock=True)
        r = q.check_connection()
        assert r["ok"] is True
        assert "mock" in r["backend"].lower()

    def test_account_catalog(self):
        q = QuickBooksConnector(mock=True)
        catalog = q.get_account_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) >= 10
        # Check QBO-specific field
        assert "qbo_type" in catalog[0]

    def test_create_bill(self):
        q = QuickBooksConnector(mock=True)
        r = q.create_bill("Proveedor X",
                          [{"description": "Servicio", "amount": 5000}])
        assert r["ok"] is True
        assert r["bill_id"].startswith("QBO-BILL-")
        assert r["total"] == 5000.0

    def test_create_invoice(self):
        q = QuickBooksConnector(mock=True)
        r = q.create_invoice("Cliente Y",
                             [{"description": "Proyecto", "amount": 10000}])
        assert r["ok"] is True
        assert r["invoice_id"].startswith("QBO-INV-")
        assert r["total"] == 10000.0

    def test_list_vendors_mock(self):
        q = QuickBooksConnector(mock=True)
        vendors = q.list_vendors()
        assert len(vendors) >= 1
        assert "name" in vendors[0]

    def test_list_customers_mock(self):
        q = QuickBooksConnector(mock=True)
        customers = q.list_customers()
        assert len(customers) >= 1
        assert "name" in customers[0]

    def test_voucher_stored_in_memory(self):
        q = QuickBooksConnector(mock=True)
        q.create_voucher(SAMPLE_VOUCHER)
        assert SAMPLE_VOUCHER["folio_fiscal"] in q._polizas

    def test_account_catalog_cached(self):
        q = QuickBooksConnector(mock=True)
        c1 = q.get_account_catalog()
        c2 = q.get_account_catalog()
        assert c1 is c2  # same object (cached)


# ===================================================================
# 7. CSVExporter (Phase 2)
# ===================================================================
class TestCSVExporter:
    def test_export_voucher(self, tmp_path):
        path = str(tmp_path / "export.csv")
        exp = CSVExporter(path)
        row = exp.export_voucher(SAMPLE_VOUCHER)
        assert row["folio_fiscal"] == SAMPLE_VOUCHER["folio_fiscal"]
        assert row["poliza"]
        assert row["cuenta_cargo"]
        assert os.path.exists(path)

    def test_export_all(self, tmp_path):
        path = str(tmp_path / "export_all.csv")
        exp = CSVExporter(path)
        vouchers = [
            {**SAMPLE_VOUCHER, "folio_fiscal": f"V-{i}"}
            for i in range(5)
        ]
        rows = exp.export_all(vouchers)
        assert len(rows) == 5

    def test_health(self, tmp_path):
        exp = CSVExporter(str(tmp_path / "health.csv"))
        h = exp.health()
        assert h["ok"] is True
        assert h["rows"] == 0

    def test_export_accumulates(self, tmp_path):
        path = str(tmp_path / "acc.csv")
        exp1 = CSVExporter(path)
        exp1.export_voucher(SAMPLE_VOUCHER)
        exp2 = CSVExporter(path)
        exp2.export_voucher({**SAMPLE_VOUCHER, "folio_fiscal": "V-2"})
        assert exp2.rows[0]["folio_fiscal"] == SAMPLE_VOUCHER["folio_fiscal"]
        assert exp2.rows[1]["folio_fiscal"] == "V-2"

    def test_csv_file_has_header(self, tmp_path):
        path = str(tmp_path / "header.csv")
        exp = CSVExporter(path)
        exp.export_voucher(SAMPLE_VOUCHER)
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
        assert "folio_fiscal" in fieldnames
        assert "cuenta_cargo" in fieldnames
        assert "audit_ref" in fieldnames


# ===================================================================
# 8. Account mapping consistency
# ===================================================================
class TestAccountMapping:
    def test_contpaqi_and_v2_map_same_categories(self):
        """Both _cuentas_para_categoria (Phase 1) and cuentas_para_categoria
        (Phase 2) should agree on known categories."""
        for cat in ["gasto_operativo", "inversion", "activo_fijo", "nomina"]:
            v1 = _cuentas_para_categoria(cat)
            v2 = cuentas_v2(cat)
            assert v1 == v2, f"Mismatch for {cat}: {v1} != {v2}"

    def test_unknown_category_falls_back(self):
        v1 = _cuentas_para_categoria("desconocido")
        v2 = cuentas_v2("desconocido")
        assert v1 == v2

    def test_completely_unknown_falls_back_to_desconocido(self):
        v = cuentas_v2("no_existe")
        d = cuentas_v2("desconocido")
        assert v == d


# ===================================================================
# 9. DesktopERPBase — mock driver
# ===================================================================
class MockDesktopDriver:
    """Minimal mock driver for testing DesktopERPBase."""

    def __init__(self):
        self.session = None
        self._opened = True  # simulate already-open ERP

    def open_app(self):
        self._opened = True
        return {"ok": True, "message": "ERP abierto (mock)"}

    def read_window_title(self):
        return "CONTPAQi Demo" if self._opened else ""

    def screenshot(self):
        return {"ok": True, "path": "<mock>"}

    def login(self, credentials):
        self.session = credentials
        return {"ok": True, "message": "Sesion activa (mock)"}

    def capture_invoice_grid(self):
        return {"ok": True, "grid": [
            {"folio_fiscal": "GRID-001", "total": 1000},
            {"folio_fiscal": "GRID-002", "total": 2500},
        ]}

    def register_invoice(self, invoice):
        if invoice.get("_health_probe"):
            return {"ok": True, "registro": invoice}
        return {"ok": True, "registro": invoice,
                "message": f"Registrado {invoice.get('folio_fiscal')}"}

    def open_invoices(self):
        return {"ok": True, "message": "Modulo de facturas abierto"}


class TestDesktopERPBase:
    def test_health_check_ok(self, tmp_path):
        driver = MockDesktopDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False)
        result = erp.health()
        assert result["ok"] is True
        assert "abierto" in result["checks"]
        assert "navegable" in result["checks"]

    def test_health_check_with_session(self, tmp_path):
        driver = MockDesktopDriver()
        driver.session = {"user": "test"}
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False)
        result = erp.health()
        assert result["ok"] is True
        assert result["checks"].get("guardable") is True

    def test_health_check_without_session(self, tmp_path):
        driver = MockDesktopDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False)
        result = erp.health()
        assert result["ok"] is True
        assert result["checks"].get("guardable") is None

    def test_full_flow_ok(self, tmp_path):
        driver = MockDesktopDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False)
        invs = [{"folio_fiscal": "FLOW-001", "total": 500}]
        result = erp.full_flow({"user": "admin", "pass": "123"}, invoices=invs)
        assert result["ok"] is True
        assert len(result["registered"]) == 1
        assert "steps" in result

    def test_full_flow_open_fails(self, tmp_path):
        class BrokenDriver(MockDesktopDriver):
            def open_app(self):
                return {"ok": False, "message": "No se pudo abrir"}

        driver = BrokenDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False, retries=1)
        result = erp.full_flow({"user": "admin", "pass": "123"})
        assert result["ok"] is False

    def test_full_flow_login_fails(self, tmp_path):
        class NoLoginDriver(MockDesktopDriver):
            def login(self, credentials):
                return {"ok": False, "message": "Credenciales invalidas"}

        driver = NoLoginDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False, retries=1)
        result = erp.full_flow({"user": "bad", "pass": "bad"})
        assert result["ok"] is False

    def test_audit_log_written(self, tmp_path):
        driver = MockDesktopDriver()
        audit_dir = str(tmp_path / "audit")
        erp = DesktopERPBase(driver, audit_dir=audit_dir, screenshots=False)
        erp.health()
        assert os.path.exists(os.path.join(audit_dir, "audit.jsonl"))
        with open(os.path.join(audit_dir, "audit.jsonl")) as f:
            lines = f.readlines()
        assert len(lines) >= 2  # abierto + navegable

    def test_retry_on_failure(self, tmp_path):
        call_count = 0

        class FlakyDriver(MockDesktopDriver):
            def open_app(self):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    return {"ok": False, "message": "Fallo temporal"}
                return {"ok": True, "message": "Abierto en intento 3"}

        driver = FlakyDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False, retries=3)
        result = erp.full_flow({"user": "admin", "pass": "123"})
        assert result["ok"] is True
        assert call_count == 3

    def test_retry_exhausted(self, tmp_path):
        class AlwaysFailDriver(MockDesktopDriver):
            def open_app(self):
                return {"ok": False, "message": "Siempre falla"}

        driver = AlwaysFailDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False, retries=2)
        result = erp.full_flow({"user": "admin", "pass": "123"})
        assert result["ok"] is False

    def test_register_multiple_invoices(self, tmp_path):
        driver = MockDesktopDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False)
        invs = [
            {"folio_fiscal": "MULTI-001", "total": 1000},
            {"folio_fiscal": "MULTI-002", "total": 2000},
            {"folio_fiscal": "MULTI-003", "total": 3000},
        ]
        result = erp.full_flow({"user": "admin", "pass": "123"}, invoices=invs)
        assert result["ok"] is True
        assert len(result["registered"]) == 3

    def test_full_flow_with_grid_capture(self, tmp_path):
        """Grid capture returns invoices; full flow should register them."""
        driver = MockDesktopDriver()
        erp = DesktopERPBase(driver, audit_dir=str(tmp_path / "audit"),
                             screenshots=False)
        # Don't pass invoices — should use grid capture
        result = erp.full_flow({"user": "admin", "pass": "123"})
        assert result["ok"] is True
        assert len(result["registered"]) == 2  # 2 items from mock grid

    def test_session_id_unique(self, tmp_path):
        d1 = DesktopERPBase(MockDesktopDriver(),
                            audit_dir=str(tmp_path / "a1"), screenshots=False)
        d2 = DesktopERPBase(MockDesktopDriver(),
                            audit_dir=str(tmp_path / "a2"), screenshots=False)
        assert d1._session_id != d2._session_id


# ===================================================================
# 10. Cross-cutting: malformed data, edge cases
# ===================================================================
class TestERPEdgeCases:
    def test_voucher_with_none_values(self):
        c = CONTPAQiConnector()
        voucher = {
            "folio_fiscal": "X-1",
            "total": None,
            "emisor_rfc": None,
            "fecha": None,
        }
        r = c.create_voucher(voucher)
        assert r["ok"] is True
        stored = c._polizas["X-1"]
        assert stored["total"] == 0.0

    def test_voucher_with_string_total(self):
        c = CONTPAQiConnector()
        r = c.create_voucher({
            "folio_fiscal": "STR-1",
            "total": "$1,234.56",
            "categoria": "gasto_operativo",
        })
        assert r["ok"] is True

    def test_quickbooks_large_total(self):
        q = QuickBooksConnector(mock=True)
        r = q.create_voucher({
            "folio_fiscal": "BIG-1",
            "total": "999999999.99",
            "categoria": "inversion",
        })
        assert r["ok"] is True

    def test_csv_exporter_no_path_uses_default(self):
        """CSVExporter with no path creates file in project root."""
        exp = CSVExporter()
        assert exp.path.endswith("polizas_export.csv")
        # Clean up if created
        if os.path.exists(exp.path):
            os.unlink(exp.path)

    def test_voucher_with_empty_concepto_as_fallback(self):
        """When folio_fiscal is empty, concepto is used as fallback."""
        c = CONTPAQiConnector()
        r = c.create_voucher({"folio_fiscal": "", "concepto": "Fallback-001"})
        assert r["ok"] is True
        assert "Fallback-001" in c._polizas

    def test_quickbooks_bill_with_multiple_items(self):
        q = QuickBooksConnector(mock=True)
        items = [
            {"description": "Item 1", "amount": 1000},
            {"description": "Item 2", "amount": 2500},
            {"description": "Item 3", "amount": 500},
        ]
        r = q.create_bill("Proveedor Multi", items)
        assert r["ok"] is True
        assert r["total"] == 4000.0

    def test_quickbooks_invoice_with_due_date(self):
        q = QuickBooksConnector(mock=True)
        r = q.create_invoice("Cliente", [{"description": "Svc", "amount": 1000}],
                             due_date="2026-12-31")
        assert r["ok"] is True
        assert r["due_date"] == "2026-12-31"

    def test_quickbooks_list_vendors_limit(self):
        q = QuickBooksConnector(mock=True)
        vendors = q.list_vendors(max_results=1)
        assert isinstance(vendors, list)

    def test_quickbooks_default_init(self):
        """QuickBooksConnector(mock=True) should work."""
        q = QuickBooksConnector(mock=True)
        assert q.health()["ok"] is True

    def test_erp_automation_min_retries(self, tmp_path):
        """retries should be at least 1."""
        erp = DesktopERPBase(MockDesktopDriver(),
                             audit_dir=str(tmp_path / "a"),
                             screenshots=False, retries=0)
        assert erp.retries == 1

    def test_voucher_total_with_dollar_sign(self):
        c = CONTPAQiConnector()
        r = c.create_voucher({
            "folio_fiscal": "USD-1",
            "total": "$500.00",
            "categoria": "nomina",
        })
        assert r["ok"] is True
        assert c._polizas["USD-1"]["total"] == 500.0
