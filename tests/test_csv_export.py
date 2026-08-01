# -*- coding: utf-8 -*-
"""Tests de la exportación CSV multi-formato (CONTPAQi/Aspel/SAT/custom)."""
import csv
import os
import pytest

from b2b_ai.erp.csv_export import (
    CSVExport, ERP_FORMATS, export_to, register_custom_format, resolve_format,
)

VOUCHER = {
    "folio_fiscal": "FAC-2026-0001",
    "emisor_rfc": "CON950820K12",
    "emisor": "CONSULTORA SA",
    "fecha": "2026-07-03",
    "categoria": "inversion",
    "total": 5800.00,
    "concepto": "Servicios de consultoría",
}


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_formats_disponibles():
    assert set(ERP_FORMATS) == {"contpaqi", "aspel", "sat"}


def test_resolve_format_tolerante():
    assert resolve_format("CONTPAQi") == "contpaqi"
    assert resolve_format("aspel-sae") == "aspel"
    assert resolve_format("sat") == "sat"
    assert resolve_format("balanza") == "sat"
    assert resolve_format("nope") is None


def test_formato_desconocido_lanza():
    with pytest.raises(ValueError):
        CSVExport("no_existe")


def test_export_contpaqi(tmp_path):
    path = str(tmp_path / "contpaqi.csv")
    res = export_to("contpaqi", [VOUCHER], path=path)
    assert res["template"] == "CONTPAQi"
    assert os.path.exists(path)
    rows = _read(path)
    assert len(rows) == 1
    r = rows[0]
    assert r["folio_fiscal"] == "FAC-2026-0001"
    assert r["fecha"] == "2026-07-03"
    assert r["cargo"] == "5800.00"
    assert r["cuenta_cargo"]
    assert r["cuenta_abono"]


def test_export_aspel(tmp_path):
    path = str(tmp_path / "aspel.csv")
    res = export_to("aspel", [VOUCHER], path=path)
    assert res["template"] == "Aspel"
    rows = _read(path)
    r = rows[0]
    assert "tipo_movimiento" in r
    assert r["concepto"] == "Servicios de consultoría"


def test_export_sat_deriva_ejercicio_mes(tmp_path):
    path = str(tmp_path / "sat.csv")
    res = export_to("sat", [VOUCHER], path=path)
    assert res["template"] == "SAT"
    rows = _read(path)
    r = rows[0]
    assert r["ejercicio"] == "2026"
    assert r["mes"] == "07"
    assert r["rfc"] == "CON950820K12"
    assert r["razon_social"] == "CONSULTORA SA"


def test_export_append_no_duplica_header(tmp_path):
    path = str(tmp_path / "e.csv")
    export_to("contpaqi", [VOUCHER], path=path)
    export_to("contpaqi", [VOUCHER], path=path, overwrite=False)  # append
    rows = _read(path)
    # header contado 1 sola vez: 2 filas de datos
    assert len(rows) == 2
    assert all(r["folio_fiscal"] == "FAC-2026-0001" for r in rows)


def test_custom_format(tmp_path):
    key = register_custom_format("MiERP", ["sku", "importe"],
                                 lambda v: {"sku": v["folio_fiscal"],
                                            "importe": str(v["total"])})
    assert key in ERP_FORMATS
    path = str(tmp_path / "custom.csv")
    res = export_to(key, [VOUCHER], path=path)
    assert res["template"] == "Custom"
    rows = _read(path)
    assert rows[0]["sku"] == "FAC-2026-0001"


def test_csv_export_health(tmp_path):
    e = CSVExport("sat", path=str(tmp_path / "h.csv"))
    h = e.health()
    assert h["ok"] is True
    assert "SAT" in h["backend"]
    assert "rfc" in h["fieldnames"]
