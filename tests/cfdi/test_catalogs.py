# -*- coding: utf-8 -*-
"""Tests for b2b_ai/cfdi/catalogs.py — SAT catalog validation."""
import pytest
from b2b_ai.cfdi.catalogs import (
    is_valid_uso_cfdi, is_valid_forma_pago, is_valid_metodo_pago,
    is_valid_tipo_comprobante, is_valid_regimen, is_valid_impuesto,
    describe_impuesto, USOS_CFDI, FORMAS_PAGO, METODOS_PAGO,
    TIPOS_COMPROBANTE, REGIMENES_FISCALES, IMPUESTOS, CP_CATEGORIAS,
)


class TestUsoCFDI:
    def test_valid_g01(self):
        assert is_valid_uso_cfdi("G01") is True

    def test_valid_cp01(self):
        assert is_valid_uso_cfdi("CP01") is True

    def test_invalid(self):
        assert is_valid_uso_cfdi("ZZ") is False

    def test_empty(self):
        assert is_valid_uso_cfdi("") is False


class TestFormaPago:
    def test_valid_01(self):
        assert is_valid_forma_pago("01") is True

    def test_valid_03(self):
        assert is_valid_forma_pago("03") is True

    def test_invalid(self):
        # "99" = "Por definir" is valid; test truly invalid code
        assert is_valid_forma_pago("ZZ") is False


class TestMetodoPago:
    def test_valid_pue(self):
        assert is_valid_metodo_pago("PUE") is True

    def test_valid_ppd(self):
        assert is_valid_metodo_pago("PPD") is True

    def test_invalid(self):
        assert is_valid_metodo_pago("XX") is False


class TestTipoComprobante:
    def test_valid_i(self):
        assert is_valid_tipo_comprobante("I") is True

    def test_valid_n(self):
        assert is_valid_tipo_comprobante("N") is True

    def test_invalid(self):
        assert is_valid_tipo_comprobante("Z") is False


class TestRegimen:
    def test_valid_601(self):
        assert is_valid_regimen("601") is True

    def test_invalid(self):
        assert is_valid_regimen("999") is False


class TestImpuesto:
    def test_valid_iva(self):
        assert is_valid_impuesto("002") is True

    def test_describe(self):
        assert describe_impuesto("001") == "ISR"
        assert describe_impuesto("002") == "IVA"

    def test_unknown(self):
        assert describe_impuesto("999") == "999"


class TestCPCategorias:
    def test_activo_fijo_keys(self):
        assert "432115" in CP_CATEGORIAS["activo_fijo"]

    def test_gasto_operativo_keys(self):
        assert "811111" in CP_CATEGORIAS["gasto_operativo"]
