"""Comprehensive tests for the DIOT module.

Covers:
- DIOT generation from sample invoices
- Inconsistency detection (IVA mismatch, missing RFC, duplicates)
- XML export format
- Edge cases: multiple RFCs, mixed IVA rates, zero-amount entries
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest

from b2b_ai.features.diot.models import (
    CFDIInvoiceInput,
    DiotEntry,
    DiotReport,
    EstatusDIOT,
    TipoIva,
    TipoOperacion,
)
from b2b_ai.features.diot.service import (
    detect_inconsistencies,
    export_diot_xml,
    generate_diot,
    get_report,
    list_reports,
    validate_diot_data,
)
from b2b_ai.features.diot.validators import (
    ValidationResult,
    detect_duplicate_uuids,
    validate_all_iva,
    validate_all_rfcs,
    validate_cfdi_cross_reference,
    validate_iva_calculation,
    validate_rfc,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_invoices_16pct():
    """Three invoices from different RFCs, all at 16% IVA."""
    return [
        CFDIInvoiceInput(
            uuid="AAAA-1111-BBBB-2222",
            rfc_emisor="EMX010101AAA",
            nombre_emisor="Empresa X SA de CV",
            fecha=datetime(2026, 1, 15),
            subtotal=10000.00,
            iva_trasladado=1600.00,
            iva_acreditable=1600.00,
            total=11600.00,
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.GENERAL_16,
        ),
        CFDIInvoiceInput(
            uuid="CCCC-3333-DDDD-4444",
            rfc_emisor="EMY020202BBB",
            nombre_emisor="Empresa Y SC",
            fecha=datetime(2026, 1, 20),
            subtotal=5000.00,
            iva_trasladado=800.00,
            iva_acreditable=800.00,
            total=5800.00,
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.GENERAL_16,
        ),
        CFDIInvoiceInput(
            uuid="EEEE-5555-FFFF-6666",
            rfc_emisor="EMZ030303CCC",
            nombre_emisor="Empresa Z S de RL",
            fecha=datetime(2026, 1, 25),
            subtotal=3000.00,
            iva_trasladado=480.00,
            iva_acreditable=480.00,
            total=3480.00,
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.GENERAL_16,
        ),
    ]


@pytest.fixture
def sample_invoices_mixed_rates():
    """Invoices with different IVA rates (16%, 8%, 0%)."""
    return [
        CFDIInvoiceInput(
            uuid="MIX1-0001-MIX1-0001",
            rfc_emisor="EMX010101AAA",
            nombre_emisor="Empresa X SA de CV",
            fecha=datetime(2026, 2, 5),
            subtotal=10000.00,
            iva_trasladado=1600.00,
            iva_acreditable=1600.00,
            total=11600.00,
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.GENERAL_16,
        ),
        CFDIInvoiceInput(
            uuid="MIX1-0002-MIX1-0002",
            rfc_emisor="EMX010101AAA",
            nombre_emisor="Empresa X SA de CV",
            fecha=datetime(2026, 2, 10),
            subtotal=2000.00,
            iva_trasladado=160.00,
            iva_acreditable=160.00,
            total=2160.00,
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.FRONTERA_8,
        ),
        CFDIInvoiceInput(
            uuid="MIX1-0003-MIX1-0003",
            rfc_emisor="EMX010101AAA",
            nombre_emisor="Empresa X SA de CV",
            fecha=datetime(2026, 2, 15),
            subtotal=1000.00,
            iva_trasladado=0.00,
            iva_acreditable=0.00,
            total=1000.00,
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.EXENTO_0,
        ),
    ]


@pytest.fixture
def sample_invoices_bad_data():
    """Invoices with various problems for inconsistency detection."""
    return [
        # Bad RFC (too short)
        CFDIInvoiceInput(
            uuid="BAD1-0001-BAD1-0001",
            rfc_emisor="ABC123",
            nombre_emisor="Bad RFC Corp",
            fecha=datetime(2026, 3, 1),
            subtotal=5000.00,
            iva_trasladado=800.00,
            iva_acreditable=800.00,
            total=5800.00,
        ),
        # IVA mismatch (16% of 5000 = 800, but says 500)
        CFDIInvoiceInput(
            uuid="BAD1-0002-BAD1-0002",
            rfc_emisor="EMX010101AAA",
            nombre_emisor="IVA Mismatch Corp",
            fecha=datetime(2026, 3, 5),
            subtotal=5000.00,
            iva_trasladado=500.00,  # wrong!
            iva_acreditable=500.00,
            total=5500.00,
        ),
        # Duplicate UUID
        CFDIInvoiceInput(
            uuid="BAD1-0002-BAD1-0002",  # same UUID as above
            rfc_emisor="EMY020202BBB",
            nombre_emisor="Duplicate Corp",
            fecha=datetime(2026, 3, 10),
            subtotal=3000.00,
            iva_trasladado=480.00,
            iva_acreditable=480.00,
            total=3480.00,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: RFC validation
# ---------------------------------------------------------------------------

class TestRFCValidation:
    def test_valid_rfc_persona_moral(self):
        assert validate_rfc("EMX010101AAA") is None

    def test_valid_rfc_persona_fisica(self):
        assert validate_rfc("CAMJ800101ABC") is None

    def test_empty_rfc(self):
        result = validate_rfc("")
        assert result is not None
        assert "vacío" in result

    def test_rfc_too_short(self):
        result = validate_rfc("ABC123")
        assert result is not None
        assert "longitud" in result

    def test_rfc_too_long(self):
        result = validate_rfc("EMX010101AABBBBB")
        assert result is not None

    def test_rfc_lowercase_is_normalized(self):
        # validate_rfc strips and uppercases internally
        assert validate_rfc("emx010101aaa") is None

    def test_validate_all_rfcs_picks_up_bad(self):
        entries = [
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="Good Corp",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=1000,
            ),
            DiotEntry(
                rfc_tercero="BAD",
                nombre="Bad Corp",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=500,
            ),
        ]
        result = validate_all_rfcs(entries)
        assert not result.valid
        assert any(i.tipo == "rfc_invalido" for i in result.inconsistencies)

    def test_duplicate_rfc_detection(self):
        entries = [
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="Corp A",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=1000,
            ),
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="Corp A again",
                tipo_operacion=TipoOperacion.ACTIVO_FIJO,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=2000,
            ),
        ]
        result = validate_all_rfcs(entries)
        assert any(i.tipo == "rfc_duplicado" for i in result.inconsistencies)


# ---------------------------------------------------------------------------
# Tests: IVA validation
# ---------------------------------------------------------------------------

class TestIVAValidation:
    def test_correct_iva_16pct(self):
        entry = DiotEntry(
            rfc_tercero="EMX010101AAA",
            nombre="Good Corp",
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.GENERAL_16,
            monto_neto=10000.00,
            iva_trasladado=1600.00,
        )
        assert validate_iva_calculation(entry) is None

    def test_incorrect_iva_16pct(self):
        entry = DiotEntry(
            rfc_tercero="EMX010101AAA",
            nombre="Bad Corp",
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.GENERAL_16,
            monto_neto=10000.00,
            iva_trasladado=1500.00,  # should be 1600
        )
        inc = validate_iva_calculation(entry)
        assert inc is not None
        assert inc.tipo == "iva_mismatch"
        assert inc.monto_esperado == 1600.00
        assert inc.monto_real == 1500.00

    def test_correct_iva_8pct_border(self):
        entry = DiotEntry(
            rfc_tercero="EMX010101AAA",
            nombre="Border Corp",
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.FRONTERA_8,
            monto_neto=5000.00,
            iva_trasladado=400.00,
        )
        assert validate_iva_calculation(entry) is None

    def test_correct_iva_0pct_exempt(self):
        entry = DiotEntry(
            rfc_tercero="EMX010101AAA",
            nombre="Exempt Corp",
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.EXENTO_0,
            monto_neto=2000.00,
            iva_trasladado=0.00,
        )
        assert validate_iva_calculation(entry) is None

    def test_mixed_rates_skipped(self):
        entry = DiotEntry(
            rfc_tercero="EMX010101AAA",
            nombre="Mixed Corp",
            tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            tipo_iva=TipoIva.TASAS_MIXTAS,
            monto_neto=10000.00,
            iva_trasladado=1200.00,
        )
        assert validate_iva_calculation(entry) is None  # skipped

    def test_validate_all_iva(self):
        entries = [
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="A",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=10000,
                iva_trasladado=1600,
            ),
            DiotEntry(
                rfc_tercero="EMY020202BBB",
                nombre="B",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=10000,
                iva_trasladado=1000,  # wrong
            ),
        ]
        result = validate_all_iva(entries)
        assert result.error_count == 1


# ---------------------------------------------------------------------------
# Tests: Invoice validation
# ---------------------------------------------------------------------------

class TestInvoiceValidation:
    def test_valid_invoices(self, sample_invoices_16pct):
        result = validate_diot_data(sample_invoices_16pct)
        assert result.valid
        assert result.error_count == 0

    def test_bad_data_detection(self, sample_invoices_bad_data):
        result = validate_diot_data(sample_invoices_bad_data)
        assert not result.valid
        # Should detect: bad RFC, IVA mismatch, duplicate UUID
        tipos = {i.tipo for i in result.inconsistencies}
        assert "rfc_invalido" in tipos
        assert "iva_invoice_mismatch" in tipos
        assert "uuid_duplicado" in tipos

    def test_duplicate_uuid_detection(self):
        invoices = [
            CFDIInvoiceInput(
                uuid="SAME-UUID-SAME-UUID",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="A",
                fecha=datetime(2026, 1, 1),
                subtotal=1000,
                iva_trasladado=160,
                total=1160,
            ),
            CFDIInvoiceInput(
                uuid="SAME-UUID-SAME-UUID",
                rfc_emisor="EMY020202BBB",
                nombre_emisor="B",
                fecha=datetime(2026, 1, 2),
                subtotal=2000,
                iva_trasladado=320,
                total=2320,
            ),
        ]
        issues = detect_duplicate_uuids(invoices)
        assert len(issues) == 1
        assert issues[0].tipo == "uuid_duplicado"


# ---------------------------------------------------------------------------
# Tests: DIOT generation
# ---------------------------------------------------------------------------

class TestDiotGeneration:
    def test_generate_basic(self, sample_invoices_16pct):
        report = generate_diot(
            month=1, year=2026, tenant_id="TENANT-001",
            invoices=sample_invoices_16pct,
        )
        assert report.month == 1
        assert report.year == 2026
        assert report.tenant_id == "TENANT-001"
        assert len(report.entries) == 3  # 3 different RFCs
        assert report.estatus == EstatusDIOT.GENERADA
        assert report.summary.total_operaciones == 3
        assert report.summary.total_monto_neto == 18000.00
        assert report.summary.total_iva_trasladado == 2880.00

    def test_generate_no_invoices(self):
        report = generate_diot(month=1, year=2026, tenant_id="TENANT-002")
        assert report.estatus == EstatusDIOT.ERROR
        assert len(report.inconsistencies) > 0
        assert report.inconsistencies[0].tipo == "sin_facturas"

    def test_generate_mixed_rates(self, sample_invoices_mixed_rates):
        report = generate_diot(
            month=2, year=2026, tenant_id="TENANT-003",
            invoices=sample_invoices_mixed_rates,
        )
        # Same RFC but different IVA rates → 3 separate entries
        assert len(report.entries) == 3
        rates = {e.tipo_iva.value for e in report.entries}
        assert rates == {"16", "8", "0"}

    def test_generate_aggregates_same_rfc_same_rate(self):
        """Two invoices from same RFC + same rate should merge into one entry."""
        invoices = [
            CFDIInvoiceInput(
                uuid="AGG1-0001-AGG1-0001",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="Corp A",
                fecha=datetime(2026, 4, 1),
                subtotal=5000,
                iva_trasladado=800,
                iva_acreditable=800,
                total=5800,
            ),
            CFDIInvoiceInput(
                uuid="AGG1-0002-AGG1-0002",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="Corp A",
                fecha=datetime(2026, 4, 15),
                subtotal=3000,
                iva_trasladado=480,
                iva_acreditable=480,
                total=3480,
            ),
        ]
        report = generate_diot(
            month=4, year=2026, tenant_id="TENANT-004",
            invoices=invoices,
        )
        assert len(report.entries) == 1
        entry = report.entries[0]
        assert entry.monto_neto == 8000.00
        assert entry.iva_trasladado == 1280.00
        assert entry.numero_facturas == 2
        assert len(entry.uuids) == 2

    def test_summary_recompute(self, sample_invoices_16pct):
        report = generate_diot(
            month=1, year=2026, tenant_id="TENANT-005",
            invoices=sample_invoices_16pct,
        )
        summary = report.recompute_summary()
        assert summary.total_monto_neto == sum(e.monto_neto for e in report.entries)
        assert summary.total_iva_trasladado == sum(e.iva_trasladado for e in report.entries)

    def test_generate_stores_report(self, sample_invoices_16pct):
        report = generate_diot(
            month=1, year=2026, tenant_id="TENANT-006",
            invoices=sample_invoices_16pct,
        )
        retrieved = get_report(report.id)
        assert retrieved is not None
        assert retrieved.id == report.id

    def test_list_reports(self, sample_invoices_16pct):
        generate_diot(month=1, year=2026, tenant_id="TENANT-A", invoices=sample_invoices_16pct)
        generate_diot(month=2, year=2026, tenant_id="TENANT-B", invoices=sample_invoices_16pct)

        all_reports = list_reports()
        assert len(all_reports) >= 2

        filtered = list_reports(tenant_id="TENANT-A")
        assert all(r.tenant_id == "TENANT-A" for r in filtered)

        monthly = list_reports(month=1)
        assert all(r.month == 1 for r in monthly)


# ---------------------------------------------------------------------------
# Tests: XML export
# ---------------------------------------------------------------------------

class TestXMLExport:
    def test_export_xml_structure(self, sample_invoices_16pct):
        report = generate_diot(
            month=1, year=2026, tenant_id="TENANT-XML",
            invoices=sample_invoices_16pct,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = export_diot_xml(report, output_dir=tmpdir)
            assert xml_path.endswith(".xml")

            # Parse and verify structure
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Header
            header = root.find("Encabezado")
            assert header is not None
            assert header.find("RFC").text == "TENANT-XML"
            assert header.find("Mes").text == "01"
            assert header.find("Anio").text == "2026"
            assert header.find("TotalOperaciones").text == "3"

            # Entries
            registros = root.findall("Registro")
            assert len(registros) == 3

            # Check first entry
            first = registros[0]
            assert first.get("rfc") is not None
            assert first.find("Nombre") is not None
            assert first.find("MontoNeto") is not None
            assert first.find("IVATrasladado") is not None
            assert first.find("NumFacturas") is not None
            assert first.find("Uuids") is not None

    def test_export_xml_with_inconsistencies(self, sample_invoices_bad_data):
        report = generate_diot(
            month=3, year=2026, tenant_id="TENANT-XML-BAD",
            invoices=sample_invoices_bad_data,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = export_diot_xml(report, output_dir=tmpdir)
            tree = ET.parse(xml_path)
            root = tree.getroot()

            incs = root.find("Inconsistencias")
            if incs is not None:
                items = incs.findall("Inconsistencia")
                assert len(items) > 0
                assert items[0].get("tipo") is not None
                assert items[0].get("severidad") is not None

    def test_export_json_sidecar(self, sample_invoices_16pct):
        import json

        report = generate_diot(
            month=1, year=2026, tenant_id="TENANT-JSON",
            invoices=sample_invoices_16pct,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = export_diot_xml(report, output_dir=tmpdir)
            json_path = xml_path.replace(".xml", ".json")
            with open(json_path) as f:
                data = json.load(f)
            assert data["month"] == 1
            assert data["year"] == 2026
            assert len(data["entries"]) == 3


# ---------------------------------------------------------------------------
# Tests: CFDI cross-reference
# ---------------------------------------------------------------------------

class TestCFDICrossReference:
    def test_missing_uuid_in_entries(self):
        entries = [
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="A",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=1000,
                uuids=["UUID-DOES-NOT-EXIST"],
            ),
        ]
        invoices = [
            CFDIInvoiceInput(
                uuid="UUID-REAL-00001",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="A",
                fecha=datetime(2026, 1, 1),
                subtotal=1000,
                iva_trasladado=160,
                total=1160,
            ),
        ]
        result = validate_cfdi_cross_reference(entries, invoices)
        assert not result.valid
        assert any(i.tipo == "uuid_no_existe" for i in result.inconsistencies)

    def test_invoice_not_included(self):
        entries = [
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="A",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=1000,
                uuids=["UUID-INCLUDED"],
            ),
        ]
        invoices = [
            CFDIInvoiceInput(
                uuid="UUID-INCLUDED",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="A",
                fecha=datetime(2026, 1, 1),
                subtotal=1000,
                iva_trasladado=160,
                total=1160,
            ),
            CFDIInvoiceInput(
                uuid="UUID-MISSING",
                rfc_emisor="EMY020202BBB",
                nombre_emisor="B",
                fecha=datetime(2026, 1, 2),
                subtotal=2000,
                iva_trasladado=320,
                total=2320,
            ),
        ]
        result = validate_cfdi_cross_reference(entries, invoices)
        assert any(i.tipo == "uuid_sin_incluir" for i in result.inconsistencies)

    def test_monto_neto_mismatch(self):
        entries = [
            DiotEntry(
                rfc_tercero="EMX010101AAA",
                nombre="A",
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=9999.00,  # wrong sum
                uuids=["UUID-A"],
            ),
        ]
        invoices = [
            CFDIInvoiceInput(
                uuid="UUID-A",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="A",
                fecha=datetime(2026, 1, 1),
                subtotal=5000,
                iva_trasladado=800,
                total=5800,
            ),
            CFDIInvoiceInput(
                uuid="UUID-B",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="A",
                fecha=datetime(2026, 1, 2),
                subtotal=5000,
                iva_trasladado=800,
                total=5800,
            ),
        ]
        result = validate_cfdi_cross_reference(entries, invoices)
        assert any(i.tipo == "monto_neto_mismatch" for i in result.inconsistencies)


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_amount_invoice(self):
        invoices = [
            CFDIInvoiceInput(
                uuid="ZERO-0001-ZERO-0001",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="Zero Corp",
                fecha=datetime(2026, 5, 1),
                subtotal=0.0,
                iva_trasladado=0.0,
                total=0.0,
            ),
        ]
        report = generate_diot(
            month=5, year=2026, tenant_id="TENANT-ZERO",
            invoices=invoices,
        )
        assert len(report.entries) == 1
        assert report.entries[0].monto_neto == 0.0

    def test_foreign_currency_conversion(self):
        invoices = [
            CFDIInvoiceInput(
                uuid="USD1-0001-USD1-0001",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="USD Corp",
                fecha=datetime(2026, 6, 1),
                subtotal=1000.00,
                iva_trasladado=160.00,
                iva_acreditable=160.00,
                total=1160.00,
                moneda="USD",
                tipo_cambio=17.50,
            ),
        ]
        report = generate_diot(
            month=6, year=2026, tenant_id="TENANT-USD",
            invoices=invoices,
        )
        entry = report.entries[0]
        # 1000 * 17.50 = 17500
        assert entry.monto_neto == 17500.00
        # 160 * 17.50 = 2800
        assert entry.iva_trasladado == 2800.00

    def test_large_number_of_invoices(self):
        invoices = []
        for i in range(100):
            invoices.append(CFDIInvoiceInput(
                uuid=f"BULK-{i:04d}-BULK-{i:04d}",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="Bulk Corp",
                fecha=datetime(2026, 7, 1),
                subtotal=100.0,
                iva_trasladado=16.0,
                total=116.0,
            ))
        report = generate_diot(
            month=7, year=2026, tenant_id="TENANT-BULK",
            invoices=invoices,
        )
        assert len(report.entries) == 1
        assert report.entries[0].numero_facturas == 100
        assert report.entries[0].monto_neto == 10000.00
        assert report.entries[0].iva_trasladado == 1600.00

    def test_no_inconsistencies_when_data_clean(self, sample_invoices_16pct):
        report = generate_diot(
            month=1, year=2026, tenant_id="TENANT-CLEAN",
            invoices=sample_invoices_16pct,
        )
        assert len(report.inconsistencies) == 0

    def test_multiple_operation_types(self):
        invoices = [
            CFDIInvoiceInput(
                uuid="OP1-0001-OP1-0001",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="Activo Corp",
                fecha=datetime(2026, 8, 1),
                subtotal=5000,
                iva_trasladado=800,
                total=5800,
                tipo_operacion=TipoOperacion.ACTIVO_FIJO,
            ),
            CFDIInvoiceInput(
                uuid="OP1-0002-OP1-0002",
                rfc_emisor="EMX010101AAA",
                nombre_emisor="Activo Corp",
                fecha=datetime(2026, 8, 5),
                subtotal=3000,
                iva_trasladado=480,
                total=3480,
                tipo_operacion=TipoOperacion.GASTOS_GENERAL,
            ),
        ]
        report = generate_diot(
            month=8, year=2026, tenant_id="TENANT-OPS",
            invoices=invoices,
        )
        # Same RFC but different operation types → 2 entries
        assert len(report.entries) == 2
        op_types = {e.tipo_operacion for e in report.entries}
        assert TipoOperacion.ACTIVO_FIJO in op_types
        assert TipoOperacion.GASTOS_GENERAL in op_types
