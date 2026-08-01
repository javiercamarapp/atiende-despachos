# -*- coding: utf-8 -*-
"""Tests de los conectores ERP FASE 2 (mocks, sin APIs reales)."""
import os

from b2b_ai.erp.connector import (AbstractERPConnector, CONTPAQiConnector,
                                  AspelConnector, CSVExporter,
                                  cuentas_para_categoria)

VOUCHER = {
    "folio_fiscal": "FAC-2026-0001",
    "emisor_rfc": "CON950820K12",
    "total": "5800.00",
    "fecha": "2026-07-03",
    "categoria": "inversion",
    "concepto": "Consultoría",
}


def test_abstract_no_se_instancia():
    import pytest
    with pytest.raises(TypeError):
        AbstractERPConnector()


def test_contpaqi_create_voucher():
    c = CONTPAQiConnector()
    res = c.create_voucher(VOUCHER)
    assert res["ok"] is True
    assert res["poliza"].startswith("CPQ-")
    assert res["cuenta_cargo"]
    assert res["cuenta_abono"]
    assert res["audit_ref"].startswith("CPQ-")
    assert res["status"] == "registrada"


def test_contpaqi_voucher_queda_en_memoria():
    c = CONTPAQiConnector()
    res = c.create_voucher(VOUCHER)
    assert VOUCHER["folio_fiscal"] in c._polizas
    stored = c._polizas[VOUCHER["folio_fiscal"]]
    assert stored["poliza"] == res["poliza"]


def test_contpaqi_voucher_sin_folio_error():
    c = CONTPAQiConnector()
    res = c.create_voucher({"total": "100"})
    assert res["ok"] is False
    assert res["status"] == "error"
    assert res["audit_ref"]


def test_contpaqi_account_catalog():
    c = CONTPAQiConnector()
    catalogo = c.get_account_catalog()
    assert isinstance(catalogo, list)
    assert catalogo
    assert {"codigo", "descripcion", "tipo"} <= set(catalogo[0].keys())
    tipos = {cuenta["tipo"] for cuenta in catalogo}
    assert {"deudora", "acreedora"} <= tipos


def test_contpaqi_check_connection():
    c = CONTPAQiConnector()
    res = c.check_connection()
    assert res["ok"] is True
    assert "CONTPAQi" in res["backend"]
    assert res["audit_ref"]
    assert res["audited_at"]


def test_aspel_create_voucher():
    a = AspelConnector()
    res = a.create_voucher(VOUCHER)
    assert res["ok"] is True
    assert res["poliza"].startswith("ASL-")
    assert res["audit_ref"].startswith("ASL-")


def test_aspel_backend_distinto():
    assert AspelConnector().backend != CONTPAQiConnector().backend
    assert "Aspel" in AspelConnector().backend


def test_aspel_catalog_and_connection():
    a = AspelConnector()
    assert a.get_account_catalog()
    assert a.check_connection()["ok"] is True


def test_cuentas_para_categoria_default():
    cargo, abono = cuentas_para_categoria("no_existe")
    assert cargo == "6100 Gastos por clasificar"
    assert abono == "1130 Bancos"


def test_csv_exporter_exporta_y_agrega(tmp_path):
    path = str(tmp_path / "polizas.csv")
    e = CSVExporter(path)
    row = e.export_voucher(VOUCHER)
    assert row["folio_fiscal"] == VOUCHER["folio_fiscal"]
    assert row["total"] == "5800.0"
    assert row["audit_ref"]
    # Verificar que se escribió al disco con header
    with open(path, newline="", encoding="utf-8") as fh:
        content = fh.read()
    assert "poliza" in content
    assert "FAC-2026-0001" in content


def test_csv_exporter_export_all(tmp_path):
    e = CSVExporter(str(tmp_path / "lote.csv"))
    filas = e.export_all([VOUCHER, dict(VOUCHER, folio_fiscal="FAC-2")])
    assert len(filas) == 2
    assert len(e.rows) == 2


def test_csv_exporter_health():
    e = CSVExporter("/tmp/polizas_health_test.csv")
    assert e.health()["ok"] is True
