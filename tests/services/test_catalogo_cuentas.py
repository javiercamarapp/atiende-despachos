# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/catalogo_cuentas.py — SAT account catalog."""
import pytest
from b2b_ai.services.catalogo_cuentas import (
    CatalogoCuentas, Cuenta, CATEGORIA_A_CUENTA,
)


class TestCuenta:
    def test_as_dict(self):
        c = Cuenta("1101", "BANCOS", 3, "D", "ACTIVO")
        d = c.as_dict()
        assert d["codigo"] == "1101"
        assert d["nivel"] == 3

    def test_defaults(self):
        c = Cuenta("1101", "BANCOS", 3, "D")
        assert c.grupo == ""


class TestCatalogoCuentas:
    def test_default_catalog(self):
        cat = CatalogoCuentas()
        assert len(cat) > 20

    def test_find(self):
        cat = CatalogoCuentas()
        c = cat.find("1101")
        assert c is not None
        assert c.descripcion == "BANCOS"

    def test_find_not_found(self):
        cat = CatalogoCuentas()
        assert cat.find("9999") is None

    def test_add(self):
        cat = CatalogoCuentas([])
        cat.add("9000", "TEST", 1, "D", "TEST")
        assert len(cat) == 1
        assert cat.find("9000") is not None

    def test_len(self):
        cat = CatalogoCuentas()
        assert len(cat) == len(cat.cuentas)


class TestValidation:
    def test_valid_catalog(self):
        cat = CatalogoCuentas()
        assert cat.validar() is True

    def test_duplicate_code(self):
        cat = CatalogoCuentas([])
        cat.add("1101", "BANCOS", 3, "D")
        cat.add("1101", "BANCOS DUPL", 3, "D")
        errs = cat.errores()
        assert any("duplicado" in e for e in errs)

    def test_empty_code(self):
        cat = CatalogoCuentas([])
        cat.add("", "DESC", 3, "D")
        errs = cat.errores()
        assert any("código" in e.lower() for e in errs)

    def test_invalid_nature(self):
        cat = CatalogoCuentas([])
        cat.add("9999", "TEST", 3, "X")
        errs = cat.errores()
        assert any("naturaleza" in e.lower() for e in errs)


class TestAutoAsignacion:
    def test_basic(self):
        cat = CatalogoCuentas()
        result = cat.asignar_automatico({"gasto_operativo": None, "nomina": None})
        assert result["gasto_operativo"] == "6102"
        assert result["nomina"] == "6101"

    def test_explicit_account(self):
        cat = CatalogoCuentas()
        result = cat.asignar_automatico({"gasto_operativo": "6103"})
        assert result["gasto_operativo"] == "6103"

    def test_unknown_account_falls_back(self):
        cat = CatalogoCuentas()
        result = cat.asignar_automatico({"gasto_operativo": "9999"})
        assert result["gasto_operativo"] == "6102"


class TestXMLGeneration:
    def test_generates_xml(self):
        cat = CatalogoCuentas()
        xml = cat.generar_xml(rfc="XAXX010101000", ejercicio=2026, mes=7)
        assert "<?xml" in xml
        assert "XAXX010101000" in xml
        assert "CatalogoCuentas" in xml

    def test_invalid_catalog_raises(self):
        cat = CatalogoCuentas([])
        cat.add("", "", 0, "X")  # all invalid
        with pytest.raises(ValueError):
            cat.generar_xml()


class TestToDict:
    def test_basic(self):
        cat = CatalogoCuentas()
        d = cat.to_dict()
        assert isinstance(d, list)
        assert isinstance(d[0], dict)
