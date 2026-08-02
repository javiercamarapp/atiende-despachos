# -*- coding: utf-8 -*-
"""test_diot_automation.py — Tests del motor de automatización de la DIOT.

Cubre:
  - Ingestión de CFDIs y filtrado por periodo (month/year).
  - Clasificación de IVA acreditable/deducible por proveedor.
  - Detección de proveedores omitidos (sin CFDI en el periodo).
  - Generación de XML DIOT (bytes, esquema, valores).
  - Edge cases: mes inválido, sin CFDIs, proveedor sin RFC.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from b2b_ai.features.diot.automation import (
    DIOTAutomation,
    DIOTAutomationError,
    MissingProvider,
    ProviderClassification,
    _reset_state,
    ingest_cfdi,
    register_provider,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_state()
    yield
    _reset_state()


def _cfdi(rfc="ABC123456789", nombre="Proveedor SA", subtotal=10000.0,
          iva=1600.0, fecha="2024-03-15", ret_iva=0.0):
    return {
        "emisor_rfc": rfc,
        "emisor_nombre": nombre,
        "emisor": {"rfc": rfc, "regimen_fiscal": "601"},
        "subtotal": subtotal,
        "iva": iva,
        "retenciones_iva": ret_iva,
        "fecha_dt": datetime.fromisoformat(fecha).isoformat(),
        "fecha": fecha,
    }


# ---------------------------------------------------------------------------
# Ingestión y filtrado por periodo
# ---------------------------------------------------------------------------

def test_ingest_and_filter_by_period():
    ingest_cfdi("T1", _cfdi(fecha="2024-03-15"))
    ingest_cfdi("T1", _cfdi(rfc="ZZZ987654321", nombre="Otro", fecha="2024-04-01"))

    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    assert result.declaration.period.month == 3
    assert result.declaration.period.quarter == 1
    assert len(result.declaration.records) == 1
    assert result.declaration.records[0].rfc_tercero == "ABC123456789"


def test_no_cfdis_for_period_produces_empty_declaration():
    ingest_cfdi("T1", _cfdi(fecha="2024-03-15"))
    result = DIOTAutomation("T1").auto_generate_diot(month=5, year=2024)
    assert result.declaration.records == []
    assert result.declaration.summary.total_operaciones == 0


# ---------------------------------------------------------------------------
# Clasificación de IVA por proveedor
# ---------------------------------------------------------------------------

def test_classification_aggregates_per_provider():
    ingest_cfdi("T1", _cfdi(rfc="ABC123456789", nombre="Proveedor SA",
                            subtotal=10000.0, iva=1600.0))
    ingest_cfdi("T1", _cfdi(rfc="ABC123456789", nombre="Proveedor SA",
                            subtotal=5000.0, iva=800.0))
    ingest_cfdi("T1", _cfdi(rfc="XYZ987654321", nombre="Servicios SL",
                            subtotal=2000.0, iva=320.0))

    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    by_rfc = {c.rfc_tercero: c for c in result.classification}
    assert set(by_rfc) == {"ABC123456789", "XYZ987654321"}
    assert by_rfc["ABC123456789"].base_gravable == 15000.0
    assert by_rfc["ABC123456789"].iva_acreditable == 2400.0
    assert by_rfc["ABC123456789"].iva_deducible == 2400.0
    assert by_rfc["ABC123456789"].num_cfdis == 2
    assert result.declaration.summary.total_iva_acreditable == 2720.0


def test_iva_acreditable_net_of_retencion():
    ingest_cfdi("T1", _cfdi(subtotal=10000.0, iva=1600.0, ret_iva=533.33))
    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    rec = result.declaration.records[0]
    assert round(rec.iva_acreditable, 2) == round(1600.0 - 533.33, 2)


# ---------------------------------------------------------------------------
# Detección de proveedores omitidos
# ---------------------------------------------------------------------------

def test_detects_missing_providers():
    ingest_cfdi("T1", _cfdi(rfc="ABC123456789"))
    register_provider("T1", "ABC123456789", "Proveedor SA")
    register_provider("T1", "OMI987654321", "Omitido SL")

    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    assert [m.rfc_tercero for m in result.missing_providers] == ["OMI987654321"]
    assert isinstance(result.missing_providers[0], MissingProvider)


def test_no_missing_when_all_providers_emitted():
    ingest_cfdi("T1", _cfdi(rfc="ABC123456789"))
    register_provider("T1", "ABC123456789")
    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    assert result.missing_providers == []


# ---------------------------------------------------------------------------
# Generación de XML
# ---------------------------------------------------------------------------

def test_generate_diot_xml_bytes():
    ingest_cfdi("T1", _cfdi())
    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    assert isinstance(result.xml_bytes, bytes)
    xml = result.xml_bytes.decode("utf-8")
    assert "DIOT" in xml
    assert "ABC123456789" in xml
    assert "1600.00" in xml


def test_generate_diot_xml_from_dict():
    ingest_cfdi("T1", _cfdi())
    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    xml = DIOTAutomation("T1").generate_diot_xml(result.declaration.to_dict())
    assert b"<DIOT" in xml


def test_diot_xml_sha256_is_stable():
    ingest_cfdi("T1", _cfdi())
    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    h1 = DIOTAutomation("T1").diot_xml_sha256(result.xml_bytes)
    h2 = DIOTAutomation("T1").diot_xml_sha256(result.xml_bytes)
    assert h1 == h2
    assert len(h1) == 64


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_invalid_month_raises():
    with pytest.raises(DIOTAutomationError):
        DIOTAutomation("T1").auto_generate_diot(month=13, year=2024)


def test_invalid_year_raises():
    with pytest.raises(DIOTAutomationError):
        DIOTAutomation("T1").auto_generate_diot(month=3, year=1999)


def test_cfdi_without_rfc_is_skipped():
    ingest_cfdi("T1", {"fecha_dt": "2024-03-15T00:00:00", "subtotal": 100.0})
    result = DIOTAutomation("T1").auto_generate_diot(month=3, year=2024)
    assert result.declaration.records == []
