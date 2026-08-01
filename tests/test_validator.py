# -*- coding: utf-8 -*-
"""Tests del validador fiscal avanzado."""
import pytest

from b2b_ai.cfdi.parser import parse_cfdi
from b2b_ai.cfdi.validator import validate_cfdi
from b2b_ai.cfdi import catalogs


def test_validar_consultoria(parsed_consultoria):
    v = validate_cfdi(parsed_consultoria)
    assert v["ok"] is True
    assert v["checks"]["fail"] == 0
    assert v["diot"]["reportable"] is True


def test_validar_nomina(sample_nomina):
    v = validate_cfdi(parse_cfdi(sample_nomina))
    # Nómina con MetodoPago PUE debe validar sin errores de método
    assert v["ok"] is True


def test_validar_honorarios(sample_honorarios):
    v = validate_cfdi(parse_cfdi(sample_honorarios))
    # Retenciones 10% ISR y 2/3 IVA son referenciales → solo warnings, no fail
    assert v["ok"] is True


def test_importe_concepto_incoherente(tmp_path):
    # Cargar un XML válido y romper el importe de un concepto
    import shutil
    from conftest import fixture_path
    src = fixture_path("02_inversion_consultoria.xml")
    f = tmp_path / "roto.xml"
    shutil.copy(src, f)
    text = f.read_text()
    text = text.replace('Importe="5000.00" ObjetoImp="02"',
                        'Importe="9999.00" ObjetoImp="02"')
    f.write_text(text)
    v = validate_cfdi(parse_cfdi(str(f)))
    assert v["ok"] is False
    codes = [i["code"] for i in v["issues"]]
    assert "importe_concepto_incoherente" in codes


def test_uso_cfdi_invalido(tmp_path):
    import shutil
    from conftest import fixture_path
    src = fixture_path("02_inversion_consultoria.xml")
    f = tmp_path / "uso.xml"
    shutil.copy(src, f)
    text = f.read_text().replace('UsoCFDI="G03"', 'UsoCFDI="ZZ99"')
    f.write_text(text)
    v = validate_cfdi(parse_cfdi(str(f)))
    assert v["ok"] is False
    assert any(i["code"] == "uso_cfdi_invalido" for i in v["issues"])


def test_catalogos():
    assert catalogs.is_valid_uso_cfdi("G03")
    assert not catalogs.is_valid_uso_cfdi("ZZ")
    assert catalogs.is_valid_forma_pago("03")
    assert catalogs.is_valid_metodo_pago("PPD")
    assert catalogs.is_valid_tipo_comprobante("I")
    assert catalogs.is_valid_regimen("601")
    assert catalogs.describe_impuesto("002") == "IVA"


def test_requires_human_review_por_diot(parsed_consultoria):
    v = validate_cfdi(parsed_consultoria)
    assert v["requires_human_review"] is True
    assert any("DIOT" in n for n in v["reference_notes"])
