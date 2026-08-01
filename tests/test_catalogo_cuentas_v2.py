# -*- coding: utf-8 -*-
"""
Comprehensive tests for b2b_ai/services/catalogo_cuentas.py
Covers: Cuenta dataclass, CatalogoCuentas class (init, add, find, len,
        errores, validar, importar_csv, importar_archivo, asignar_automatico,
        generar_xml, to_dict), CATEGORIA_A_CUENTA.
"""
from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime

import pytest

from b2b_ai.services.catalogo_cuentas import (
    Cuenta, CatalogoCuentas, CATEGORIA_A_CUENTA,
    NATURALEZAS_VALIDAS,
)


# ---------------------------------------------------------------------------
# Cuenta dataclass
# ---------------------------------------------------------------------------

class TestCuenta:
    def test_creation(self):
        c = Cuenta("1101", "BANCOS", 3, "D", "ACTIVO")
        assert c.codigo == "1101"
        assert c.descripcion == "BANCOS"
        assert c.nivel == 3
        assert c.naturaleza == "D"
        assert c.grupo == "ACTIVO"

    def test_as_dict(self):
        c = Cuenta("1101", "BANCOS", 3, "D", "ACTIVO")
        d = c.as_dict()
        assert d["codigo"] == "1101"
        assert d["descripcion"] == "BANCOS"
        assert d["nivel"] == 3
        assert d["naturaleza"] == "D"
        assert d["grupo"] == "ACTIVO"

    def test_empty_grupo(self):
        c = Cuenta("X", "DESC", 1, "D")
        assert c.grupo == ""

    def test_as_dict_all_keys(self):
        c = Cuenta("1000", "ACTIVO", 1, "D", "ACTIVO")
        d = c.as_dict()
        assert set(d.keys()) == {"codigo", "descripcion", "nivel", "naturaleza", "grupo"}


# ---------------------------------------------------------------------------
# NATURALEZAS_VALIDAS
# ---------------------------------------------------------------------------

class TestNaturalezas:
    def test_deudora(self):
        assert "D" in NATURALEZAS_VALIDAS

    def test_acreedora(self):
        assert "A" in NATURALEZAS_VALIDAS

    def test_invalid_not_included(self):
        assert "X" not in NATURALEZAS_VALIDAS


# ---------------------------------------------------------------------------
# CATEGORIA_A_CUENTA
# ---------------------------------------------------------------------------

class TestCategoriaACuenta:
    def test_all_categories(self):
        expected = {"gasto_operativo", "inversion", "activo_fijo", "nomina",
                    "ingreso", "venta", "servicios", "costo", "impuestos", "desconocido"}
        assert set(CATEGORIA_A_CUENTA.keys()) == expected

    def test_all_values_are_strings(self):
        for v in CATEGORIA_A_CUENTA.values():
            assert isinstance(v, str)

    def test_gasto_operativo_maps_to_6102(self):
        assert CATEGORIA_A_CUENTA["gasto_operativo"] == "6102"

    def test_nomina_maps_to_6101(self):
        assert CATEGORIA_A_CUENTA["nomina"] == "6101"


# ---------------------------------------------------------------------------
# CatalogoCuentas: __init__
# ---------------------------------------------------------------------------

class TestCatalogoInit:
    def test_default_catalogo(self):
        cat = CatalogoCuentas()
        assert len(cat) > 0

    def test_default_has_key_accounts(self):
        cat = CatalogoCuentas()
        assert cat.find("1101") is not None  # BANCOS
        assert cat.find("6102") is not None  # GASTOS ADMINISTRATIVOS

    def test_custom_cuentas_from_list(self):
        cuentas = [Cuenta("9999", "TEST", 3, "D", "TEST")]
        cat = CatalogoCuentas(cuentas)
        assert len(cat) == 1
        assert cat.find("9999").descripcion == "TEST"

    def test_custom_cuentas_from_dicts(self):
        cuentas = [{"codigo": "9999", "descripcion": "TEST", "nivel": 3,
                    "naturaleza": "D", "grupo": "TEST"}]
        cat = CatalogoCuentas(cuentas)
        assert len(cat) == 1
        assert cat.find("9999").descripcion == "TEST"

    def test_empty_custom(self):
        cat = CatalogoCuentas([])
        assert len(cat) == 0

    def test_index_built(self):
        cat = CatalogoCuentas()
        assert cat._index is not None
        assert "1101" in cat._index


# ---------------------------------------------------------------------------
# CatalogoCuentas: add
# ---------------------------------------------------------------------------

class TestCatalogoAdd:
    def test_add_cuenta(self):
        cat = CatalogoCuentas([])
        c = cat.add("5000", "COSTOS", 1, "D", "COSTOS")
        assert c.codigo == "5000"
        assert c.descripcion == "COSTOS"
        assert len(cat) == 1

    def test_add_updates_index(self):
        cat = CatalogoCuentas([])
        cat.add("5000", "COSTOS", 1, "D", "COSTOS")
        assert cat.find("5000") is not None

    def test_add_naturaleza_uppercase(self):
        cat = CatalogoCuentas([])
        c = cat.add("X", "TEST", 1, "d", "")
        assert c.naturaleza == "D"


# ---------------------------------------------------------------------------
# CatalogoCuentas: find
# ---------------------------------------------------------------------------

class TestCatalogoFind:
    def test_find_existing(self):
        cat = CatalogoCuentas()
        c = cat.find("1101")
        assert c is not None
        assert c.descripcion == "BANCOS"

    def test_find_nonexistent(self):
        cat = CatalogoCuentas()
        assert cat.find("XXXX") is None

    def test_find_string_coercion(self):
        cat = CatalogoCuentas()
        c = cat.find(1101)
        assert c is not None


# ---------------------------------------------------------------------------
# CatalogoCuentas: __len__
# ---------------------------------------------------------------------------

class TestCatalogoLen:
    def test_len_default(self):
        cat = CatalogoCuentas()
        assert len(cat) == len(cat.cuentas)

    def test_len_empty(self):
        cat = CatalogoCuentas([])
        assert len(cat) == 0

    def test_len_after_add(self):
        cat = CatalogoCuentas([])
        cat.add("X1", "D1", 1, "D", "")
        cat.add("X2", "D2", 1, "D", "")
        assert len(cat) == 2


# ---------------------------------------------------------------------------
# CatalogoCuentas: errores
# ---------------------------------------------------------------------------

class TestCatalogoErrores:
    def test_valid_catalogo_no_errors(self):
        cat = CatalogoCuentas()
        errs = cat.errores()
        assert errs == []

    def test_sin_codigo(self):
        cat = CatalogoCuentas([Cuenta("", "DESC", 1, "D", "")])
        errs = cat.errores()
        assert any("sin código" in e for e in errs)

    def test_sin_descripcion(self):
        cat = CatalogoCuentas([Cuenta("9999", "", 1, "D", "")])
        errs = cat.errores()
        assert any("sin descripción" in e for e in errs)

    def test_nivel_invalido(self):
        cat = CatalogoCuentas([Cuenta("9999", "DESC", "abc", "D", "")])
        errs = cat.errores()
        assert any("nivel inválido" in e for e in errs)

    def test_nivel_cero(self):
        cat = CatalogoCuentas([Cuenta("9999", "DESC", 0, "D", "")])
        errs = cat.errores()
        assert any("nivel < 1" in e for e in errs)

    def test_nivel_negativo(self):
        cat = CatalogoCuentas([Cuenta("9999", "DESC", -1, "D", "")])
        errs = cat.errores()
        assert any("nivel < 1" in e for e in errs)

    def test_naturaleza_invalida(self):
        cat = CatalogoCuentas([Cuenta("9999", "DESC", 1, "X", "")])
        errs = cat.errores()
        assert any("naturaleza inválida" in e for e in errs)

    def test_codigo_duplicado(self):
        cat = CatalogoCuentas([
            Cuenta("9999", "A", 1, "D", ""),
            Cuenta("9999", "B", 2, "A", ""),
        ])
        errs = cat.errores()
        assert any("duplicado" in e for e in errs)


# ---------------------------------------------------------------------------
# CatalogoCuentas: validar
# ---------------------------------------------------------------------------

class TestCatalogoValidar:
    def test_valid(self):
        cat = CatalogoCuentas()
        assert cat.validar() is True

    def test_invalid_raises(self):
        cat = CatalogoCuentas([Cuenta("", "DESC", 1, "D", "")])
        with pytest.raises(ValueError, match="inválido"):
            cat.validar()


# ---------------------------------------------------------------------------
# CatalogoCuentas: importar_csv
# ---------------------------------------------------------------------------

class TestCatalogoImportarCSV:
    def test_with_headers(self):
        cat = CatalogoCuentas([])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["codigo", "descripcion", "nivel", "naturaleza", "grupo"])
            writer.writerow(["1101", "BANCOS", "3", "D", "ACTIVO"])
            writer.writerow(["6102", "GASTOS ADMIN", "3", "D", "GASTOS"])
            csv_path = f.name
        try:
            count = cat.importar_csv(csv_path)
            assert count == 2
            assert cat.find("1101") is not None
            assert cat.find("6102") is not None
        finally:
            os.unlink(csv_path)

    def test_without_headers(self):
        cat = CatalogoCuentas([])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["1101", "BANCOS", "3", "D", "ACTIVO"])
            writer.writerow(["6102", "GASTOS ADMIN", "3", "D", "GASTOS"])
            csv_path = f.name
        try:
            count = cat.importar_csv(csv_path)
            assert count == 2
        finally:
            os.unlink(csv_path)

    def test_with_grupo_column(self):
        cat = CatalogoCuentas([])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["codigo", "descripcion", "nivel", "naturaleza", "grupo"])
            writer.writerow(["9999", "CUSTOM", "3", "D", "MI_GRUPO"])
            csv_path = f.name
        try:
            cat.importar_csv(csv_path)
            c = cat.find("9999")
            assert c.grupo == "MI_GRUPO"
        finally:
            os.unlink(csv_path)

    def test_replaces_existing(self):
        cat = CatalogoCuentas([])
        cat.add("OLD", "OLD DESC", 1, "D", "")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["NEW", "NEW DESC", "2", "A", ""])
            csv_path = f.name
        try:
            cat.importar_csv(csv_path)
            assert cat.find("OLD") is None
            assert cat.find("NEW") is not None
        finally:
            os.unlink(csv_path)

    def test_empty_rows(self):
        cat = CatalogoCuentas([])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["codigo", "descripcion", "nivel", "naturaleza", "grupo"])
            writer.writerow(["1101", "BANCOS", "3", "D", ""])
            writer.writerow(["", "", "", "", ""])  # empty row with header present
            csv_path = f.name
        try:
            count = cat.importar_csv(csv_path)
            assert count == 1
        finally:
            os.unlink(csv_path)


# ---------------------------------------------------------------------------
# CatalogoCuentas: importar_archivo
# ---------------------------------------------------------------------------

class TestCatalogoImportarArchivo:
    def test_csv_route(self):
        cat = CatalogoCuentas([])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["1101", "BANCOS", "3", "D", ""])
            csv_path = f.name
        try:
            count = cat.importar_archivo(csv_path)
            assert count == 1
        finally:
            os.unlink(csv_path)


# ---------------------------------------------------------------------------
# CatalogoCuentas: asignar_automatico
# ---------------------------------------------------------------------------

class TestCatalogoAsignarAutomatico:
    def test_basic_assignment(self):
        cat = CatalogoCuentas()
        clasif = {"gasto_operativo": None, "nomina": None}
        result = cat.asignar_automatico(clasif)
        assert result["gasto_operativo"] == CATEGORIA_A_CUENTA["gasto_operativo"]
        assert result["nomina"] == CATEGORIA_A_CUENTA["nomina"]

    def test_explicit_cuenta_exists(self):
        cat = CatalogoCuentas()
        clasif = {"gasto_operativo": "1101"}
        result = cat.asignar_automatico(clasif)
        assert result["gasto_operativo"] == "1101"

    def test_explicit_cuenta_not_found(self):
        cat = CatalogoCuentas()
        clasif = {"gasto_operativo": "XXXX"}
        result = cat.asignar_automatico(clasif)
        # Falls back to default mapping
        assert result["gasto_operativo"] == CATEGORIA_A_CUENTA["gasto_operativo"]

    def test_none_input(self):
        cat = CatalogoCuentas()
        result = cat.asignar_automatico(None)
        assert result == {}

    def test_empty_input(self):
        cat = CatalogoCuentas()
        result = cat.asignar_automatico({})
        assert result == {}

    def test_unknown_category(self):
        cat = CatalogoCuentas()
        clasif = {"unknown_cat": None}
        result = cat.asignar_automatico(clasif)
        # Falls back to default (6102)
        assert result["unknown_cat"] == "6102"


# ---------------------------------------------------------------------------
# CatalogoCuentas: generar_xml
# ---------------------------------------------------------------------------

class TestCatalogoGenerarXML:
    def test_generates_xml(self):
        cat = CatalogoCuentas()
        xml = cat.generar_xml(rfc="ABC010101AB1", ejercicio=2026, mes=7)
        assert '<?xml version="1.0"' in xml
        assert 'RFC="ABC010101AB1"' in xml
        assert 'Anio="2026"' in xml
        assert 'Mes="07"' in xml

    def test_xml_contains_accounts(self):
        cat = CatalogoCuentas([Cuenta("1101", "BANCOS", 3, "D", "ACTIVO")])
        xml = cat.generar_xml(rfc="TEST", ejercicio=2026, mes=1)
        assert 'NumCta="1101"' in xml
        assert 'Desc="BANCOS"' in xml

    def test_xml_version_1_3(self):
        cat = CatalogoCuentas([Cuenta("1000", "ACTIVO", 1, "D", "ACTIVO")])
        xml = cat.generar_xml(rfc="T", ejercicio=2026, mes=1)
        assert 'Version="1.3"' in xml

    def test_xml_schema_location(self):
        cat = CatalogoCuentas([Cuenta("1000", "ACTIVO", 1, "D", "ACTIVO")])
        xml = cat.generar_xml(rfc="T", ejercicio=2026, mes=1)
        assert "CatalogoCuentas" in xml
        assert "xsi:schemaLocation" in xml

    def test_invalid_catalogo_raises(self):
        cat = CatalogoCuentas([Cuenta("", "DESC", 1, "D", "")])
        with pytest.raises(ValueError):
            cat.generar_xml(rfc="T", ejercicio=2026, mes=1)

    def test_xml_mes_padded(self):
        cat = CatalogoCuentas([Cuenta("1000", "ACTIVO", 1, "D", "ACTIVO")])
        xml = cat.generar_xml(rfc="T", ejercicio=2026, mes=1)
        assert 'Mes="01"' in xml

    def test_xml_mes_double_digit(self):
        cat = CatalogoCuentas([Cuenta("1000", "ACTIVO", 1, "D", "ACTIVO")])
        xml = cat.generar_xml(rfc="T", ejercicio=2026, mes=12)
        assert 'Mes="12"' in xml

    def test_xml_sorted_by_codigo(self):
        cat = CatalogoCuentas([
            Cuenta("6000", "GASTOS", 1, "D", ""),
            Cuenta("1000", "ACTIVO", 1, "D", ""),
        ])
        xml = cat.generar_xml(rfc="T", ejercicio=2026, mes=1)
        pos_activo = xml.index('NumCta="1000"')
        pos_gastos = xml.index('NumCta="6000"')
        assert pos_activo < pos_gastos

    def test_xml_escapes_special_chars(self):
        cat = CatalogoCuentas([Cuenta("X", "Cuenta <test> &amp;", 1, "D", "")])
        xml = cat.generar_xml(rfc="T", ejercicio=2026, mes=1)
        assert "&lt;test&gt;" in xml
        assert "&amp;amp;" in xml


# ---------------------------------------------------------------------------
# CatalogoCuentas: to_dict
# ---------------------------------------------------------------------------

class TestCatalogoToDict:
    def test_to_dict(self):
        cat = CatalogoCuentas()
        d = cat.to_dict()
        assert isinstance(d, list)
        assert len(d) > 0
        assert isinstance(d[0], dict)
        assert "codigo" in d[0]

    def test_to_dict_empty(self):
        cat = CatalogoCuentas([])
        assert cat.to_dict() == []

    def test_to_dict_matches_cuentas(self):
        cat = CatalogoCuentas()
        d = cat.to_dict()
        assert len(d) == len(cat.cuentas)
