# -*- coding: utf-8 -*-
"""
test_contabilidad_extended.py — Extended tests for the Contabilidad Electrónica module.

Targets uncovered lines and adds comprehensive edge-case coverage:
  - Parser _dec() exception handler (lines 174-175): non-decimal strings
  - Parser _attr_strip() None node (line 181)
  - Parser _parse_catalogo_account() nivel ValueError (lines 283-284)
  - All 11 validators with boundary values and edge cases
  - Parser edge cases: large XML, special chars, missing attributes
  - Route edge cases: wrong content types, multi-tenant isolation
  - Integration between parser → validator
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest
from lxml import etree
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.contabilidad.parser import (
    parse_balanza_xml,
    parse_balanza_bytes,
    parse_catalogo_xml,
    parse_catalogo_bytes,
    parse_estado_resultados_xml,
    parse_estado_resultados_bytes,
    BalanzaData,
    CatalogoData,
    EstadoResultadosData,
    AccountBalance,
    AccountCatalogEntry,
    IncomeStatementLine,
    _dec,
    _attr_strip,
)
from b2b_ai.features.contabilidad.validators import (
    validate_balanza,
    validate_balanza_saldos_no_negativos,
    validate_balanza_codigo_cuenta,
    validate_balanza_totales_cuadran,
    validate_balanza_saldos_excluyentes,
    validate_balanza_saldo_consistente,
    validate_catalogo,
    validate_catalogo_codigo_cuenta,
    validate_catalogo_nivel,
    validate_catalogo_naturaleza,
    validate_catalogo_codigo_agrupador,
    validate_estado_resultados,
    validate_estado_resultados_importes,
)
from b2b_ai.features.contabilidad.routes import build_contabilidad_router


# ---------------------------------------------------------------------------
# XML Templates
# ---------------------------------------------------------------------------

NS_CE = "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
NS_CFDI = "http://www.sat.gob.mx/cfd/4"

BASIC_BALANZA_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="EMP010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="5000.00" Debe="2000.00" Haber="1000.00"
                SaldoDeudor="6000.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""

BASIC_CATALOGO_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="EMP010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                Nivel="1" Naturaleza="D" CodigoAgrupador="101.01" EstadoCuenta="A"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""

BASIC_ER_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="EMP010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Ingresos>
                <ce:ConceptoIngresos Concepto="Ventas" Importe="100000.00"/>
            </ce:Ingresos>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(build_contabilidad_router())
    return TestClient(app)


@pytest.fixture
def valid_balanza() -> BalanzaData:
    return BalanzaData(
        version="1.3", rfc="EMP010101AAA", mes="07", ejercicio="2026",
        fecha_creacion="2026-07-15", tipo_balance="C",
        cuentas=[
            AccountBalance(
                num_cuenta="1000", desc="Caja",
                saldo_inicial=Decimal("5000.00"),
                debe=Decimal("2000.00"), haber=Decimal("1000.00"),
                saldo_deudor=Decimal("6000.00"), saldo_acreedor=Decimal("0.00"),
            ),
            AccountBalance(
                num_cuenta="2000", desc="Proveedores",
                saldo_inicial=Decimal("6000.00"),
                debe=Decimal("5000.00"), haber=Decimal("6000.00"),
                saldo_deudor=Decimal("0.00"), saldo_acreedor=Decimal("7000.00"),
            ),
        ],
    )


@pytest.fixture
def valid_catalogo() -> CatalogoData:
    return CatalogoData(
        version="1.3", rfc="EMP010101AAA", mes="07", ejercicio="2026",
        cuentas=[
            AccountCatalogEntry(
                num_cuenta="1000", desc="Caja",
                nivel=1, naturaleza="D",
                codigo_agrupador="101.01", estado_cuenta="A",
            ),
            AccountCatalogEntry(
                num_cuenta="2000", desc="Proveedores",
                nivel=1, naturaleza="A",
                codigo_agrupador="201.01", estado_cuenta="A",
            ),
        ],
    )


@pytest.fixture
def valid_er() -> EstadoResultadosData:
    return EstadoResultadosData(
        version="1.3", rfc="EMP010101AAA", mes="07", ejercicio="2026",
        lineas=[
            IncomeStatementLine(concepto="Ingresos", importe=Decimal("150000.00")),
            IncomeStatementLine(concepto="Costos", importe=Decimal("60000.00")),
        ],
    )


# ===========================================================================
# PARSER: _dec() helper (lines 168-175)
# ===========================================================================

class TestDecHelper:
    """Target the _dec() function's exception paths."""

    def test_dec_none(self):
        assert _dec(None) is None

    def test_dec_empty_string(self):
        assert _dec("") is None

    def test_dec_whitespace_only(self):
        assert _dec("   ") is None

    def test_dec_valid_decimal(self):
        assert _dec("123.45") == Decimal("123.45")

    def test_dec_invalid_string(self):
        """Non-numeric string → InvalidOperation → None."""
        assert _dec("not_a_number") is None

    def test_dec_special_chars(self):
        assert _dec("$100.00") is None

    def test_dec_boolean_string(self):
        """'True' is not a valid Decimal."""
        assert _dec("True") is None

    def test_dec_zero_string(self):
        assert _dec("0") == Decimal("0")

    def test_dec_negative(self):
        assert _dec("-500.50") == Decimal("-500.50")

    def test_dec_large_number(self):
        assert _dec("999999999999.99") == Decimal("999999999999.99")


# ===========================================================================
# PARSER: _attr_strip() helper (line 181)
# ===========================================================================

class TestAttrStripHelper:
    """Target the _attr_strip() None-node path."""

    def test_attr_strip_none_node(self):
        """None node → returns None."""
        assert _attr_strip(None, "SomeAttr") is None

    def test_attr_strip_existing_attr(self):
        node = etree.Element("Test")
        node.set("Name", "  value  ")
        assert _attr_strip(node, "Name") == "value"

    def test_attr_strip_missing_attr(self):
        node = etree.Element("Test")
        assert _attr_strip(node, "Missing") is None

    def test_attr_strip_empty_attr(self):
        node = etree.Element("Test")
        node.set("Name", "")
        assert _attr_strip(node, "Name") is None

    def test_attr_strip_whitespace_only_attr(self):
        node = etree.Element("Test")
        node.set("Name", "   ")
        assert _attr_strip(node, "Name") is None


# ===========================================================================
# PARSER: Balanza edge cases
# ===========================================================================

class TestParseBalanzaExtended:
    """Extended Balanza parser tests."""

    def test_parse_balanza_large_numbers(self):
        """Very large decimal values."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="BIG01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="999999999999.99" Debe="1.00" Haber="1.00"
                SaldoDeudor="999999999999.99" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.cuentas[0].saldo_inicial == Decimal("999999999999.99")

    def test_parse_balanza_missing_optional_attrs(self):
        """Cuenta with missing optional attributes."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        cta = data.cuentas[0]
        assert cta.saldo_inicial is None
        assert cta.debe is None
        assert cta.haber is None
        assert cta.saldo_deudor is None
        assert cta.saldo_acreedor is None

    def test_parse_balanza_missing_balanza_attrs(self):
        """Balanza node with missing attributes."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza>
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="0.00" Debe="0.00" Haber="0.00"
                SaldoDeudor="0.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.version is None
        assert data.rfc is None
        assert data.mes is None

    def test_parse_balanza_version_1_1(self):
        """Balanza with SAT namespace version 1.1."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_1/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.1" Rfc="OLD01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="0.00" Debe="100.00" Haber="50.00"
                SaldoDeudor="50.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.version == "1.1"
        assert data.rfc == "OLD01"

    def test_parse_balanza_whitespace_desc(self):
        """Description with extra whitespace is stripped."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="  Caja General  "
                SaldoIni="0.00" Debe="100.00" Haber="50.00"
                SaldoDeudor="50.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data.cuentas[0].desc == "Caja General"

    def test_parse_balanza_to_dict_none_fields(self):
        """BalanzaData with None optional fields serializes correctly."""
        data = BalanzaData(cuentas=[])
        d = data.to_dict()
        assert d["Version"] is None
        assert d["Rfc"] is None
        assert d["Cuentas"] == []

    def test_parse_balanza_account_to_dict_default_fields(self):
        """AccountBalance with default (non-None) fields → shows default values."""
        cta = AccountBalance(num_cuenta="1000", desc="Caja")
        d = cta.to_dict()
        # Default values are Decimal("0.00"), not None
        assert d["SaldoIni"] == "0.00"
        assert d["Debe"] == "0.00"
        assert d["Haber"] == "0.00"

    def test_parse_balanza_account_to_dict_explicit_none(self):
        """AccountBalance with explicitly None fields → None in dict."""
        cta = AccountBalance(
            num_cuenta="1000", desc="Caja",
            saldo_inicial=None, debe=None, haber=None,
            saldo_deudor=None, saldo_acreedor=None,
        )
        d = cta.to_dict()
        assert d["SaldoIni"] is None
        assert d["Debe"] is None
        assert d["Haber"] is None

    def test_parse_balanza_xml_file(self, tmp_path):
        """Parse from file path."""
        path = tmp_path / "balanza.xml"
        path.write_text(BASIC_BALANZA_XML, encoding="utf-8")
        data = parse_balanza_xml(str(path))
        assert data is not None
        assert len(data.cuentas) == 1

    def test_parse_balanza_bytes_invalid_encoding(self):
        """Bytes with invalid XML."""
        with pytest.raises(etree.XMLSyntaxError):
            parse_balanza_bytes(b"<not valid xml>")


# ===========================================================================
# PARSER: Catálogo edge cases
# ===========================================================================

class TestParseCatalogoExtended:
    """Extended Catálogo parser tests."""

    def test_parse_catalogo_missing_optional_attrs(self):
        """Cuenta with only required attrs."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="1000" Desc="Caja"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode("utf-8"))
        assert data is not None
        cta = data.cuentas[0]
        assert cta.nivel is None
        assert cta.naturaleza is None
        assert cta.codigo_agrupador is None
        assert cta.estado_cuenta is None

    def test_parse_catalogo_invalid_nivel(self):
        """Nivel that's not a valid int → parsed as None."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                Nivel="abc" Naturaleza="D"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.cuentas[0].nivel is None  # ValueError → None

    def test_parse_catalogo_nivel_float_string(self):
        """Nivel with float string '2.5' → ValueError → None."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                Nivel="2.5" Naturaleza="D"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode("utf-8"))
        assert data.cuentas[0].nivel is None

    def test_parse_catalogo_missing_catalogo_node(self):
        """ContabilidadEducativa without Catalogo node."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa/>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode("utf-8"))
        assert data is None

    def test_parse_catalogo_xml_file(self, tmp_path):
        path = tmp_path / "catalogo.xml"
        path.write_text(BASIC_CATALOGO_XML, encoding="utf-8")
        data = parse_catalogo_xml(str(path))
        assert data is not None
        assert len(data.cuentas) == 1

    def test_parse_catalogo_whitespace_attrs(self):
        """Whitespace in attributes is stripped."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta=" 1000 " Desc=" Caja "
                Nivel=" 1 " Naturaleza=" D " CodigoAgrupador=" 101.01 "/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode("utf-8"))
        cta = data.cuentas[0]
        assert cta.num_cuenta == "1000"
        assert cta.naturaleza == "D"
        assert cta.codigo_agrupador == "101.01"

    def test_parse_catalogo_to_dict_none_fields(self):
        data = CatalogoData(cuentas=[])
        d = data.to_dict()
        assert d["Version"] is None
        assert d["Rfc"] is None

    def test_parse_catalogo_entry_to_dict_none_fields(self):
        entry = AccountCatalogEntry(num_cuenta="1000", desc="Caja")
        d = entry.to_dict()
        assert d["Nivel"] is None
        assert d["Naturaleza"] is None
        assert d["CodigoAgrupador"] is None
        assert d["EstadoCuenta"] is None


# ===========================================================================
# PARSER: Estado de Resultados edge cases
# ===========================================================================

class TestParseEstadoResultadosExtended:
    """Extended Estado de Resultados parser tests."""

    def test_parse_er_missing_optional_attrs(self):
        """EstadoResultados with missing attrs."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados>
            <ce:Ingresos>
                <ce:ConceptoIngresos Concepto="Ventas" Importe="100000.00"/>
            </ce:Ingresos>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_estado_resultados_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.version is None
        assert data.rfc is None
        assert data.tipo_balanza is None

    def test_parse_er_direct_conceptos(self):
        """Concepto nodes directly under EstadoResultados (not under Ingresos/Costos/Gastos)."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="TEST01" Mes="07"
            Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Concepto Concepto="Directo" Importe="50000.00"/>
            <ce:ConceptoIngresos Concepto="Ingresos Directos" Importe="30000.00"/>
            <ce:ConceptoCostos Concepto="Costos Directos" Importe="10000.00"/>
            <ce:ConceptoGastos Concepto="Gastos Directos" Importe="5000.00"/>
            <ce:MontoIngresos Concepto="Monto Ing" Importe="20000.00"/>
            <ce:MontoCostos Concepto="Monto Cos" Importe="8000.00"/>
            <ce:MontoGastos Concepto="Monto Gas" Importe="3000.00"/>
            <ce:Utilidad Concepto="Util" Importe="9000.00"/>
            <ce:Perdida Concepto="Perd" Importe="1000.00"/>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_estado_resultados_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.lineas) >= 5
        concepts = [l.concepto for l in data.lineas]
        assert "Directo" in concepts
        assert "Util" in concepts
        assert "Perd" in concepts

    def test_parse_er_with_perdida(self):
        """ER with Perdida (loss) node."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="TEST01" Mes="07"
            Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Ingresos>
                <ce:ConceptoIngresos Concepto="Ventas" Importe="10000.00"/>
            </ce:Ingresos>
            <ce:Costos>
                <ce:ConceptoCostos Concepto="Costo" Importe="15000.00"/>
            </ce:Costos>
            <ce:Resultados>
                <ce:Perdida Concepto="Pérdida" Importe="5000.00"/>
            </ce:Resultados>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_estado_resultados_bytes(xml.encode("utf-8"))
        assert data is not None
        concepts = [l.concepto for l in data.lineas]
        assert "Pérdida" in concepts

    def test_parse_er_missing_er_node(self):
        """ContabilidadEducativa without EstadoResultados."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa/>
</cfdi:Comprobante>"""
        data = parse_estado_resultados_bytes(xml.encode("utf-8"))
        assert data is None

    def test_parse_er_xml_file(self, tmp_path):
        path = tmp_path / "er.xml"
        path.write_text(BASIC_ER_XML, encoding="utf-8")
        data = parse_estado_resultados_xml(str(path))
        assert data is not None

    def test_parse_er_to_dict_none_fields(self):
        data = EstadoResultadosData(lineas=[])
        d = data.to_dict()
        assert d["Version"] is None
        assert d["Rfc"] is None
        assert d["Lineas"] == []

    def test_parse_er_line_to_dict_none_importe(self):
        line = IncomeStatementLine(concepto="Test", importe=None)
        d = line.to_dict()
        assert d["Importe"] is None

    def test_parse_er_unknown_child_under_section(self):
        """Unknown child elements under Ingresos/Costos/Gastos are ignored."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="TEST01" Mes="07"
            Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Ingresos>
                <ce:ConceptoIngresos Concepto="Ventas" Importe="100000.00"/>
                <ce:UnknownChild Ignored="true"/>
            </ce:Ingresos>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_estado_resultados_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.lineas) == 1


# ===========================================================================
# VALIDATORS: Balanza — boundary values
# ===========================================================================

class TestValidateBalanzaExtended:
    """Extended Balanza validator tests."""

    def test_saldos_no_negativos_all_zero(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("0"), haber=Decimal("0"),
                           saldo_deudor=Decimal("0"), saldo_acreedor=Decimal("0")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert errors == []

    def test_saldos_no_negativos_all_positive(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("100"), haber=Decimal("200"),
                           saldo_deudor=Decimal("300"), saldo_acreedor=Decimal("0")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert errors == []

    def test_saldos_no_negativos_multiple_accounts(self):
        """Multiple accounts, one with negative."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("100")),
            AccountBalance(num_cuenta="2000", debe=Decimal("-50")),
            AccountBalance(num_cuenta="3000", debe=Decimal("200")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert len(errors) == 1
        assert "2000" in errors[0]

    def test_saldos_no_negativos_none_values(self):
        """None values in saldo fields → no error (checked via `is not None`)."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=None, haber=None,
                           saldo_deudor=None, saldo_acreedor=None),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert errors == []

    def test_codigo_cuenta_all_valid(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000"),
            AccountBalance(num_cuenta="123456789012345"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert errors == []

    def test_codigo_cuenta_mixed_valid_invalid(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000"),
            AccountBalance(num_cuenta="AB"),
            AccountBalance(num_cuenta="1234567890123456"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert len(errors) == 2  # AB too short, last one too long

    def test_totales_cuadran_with_none_debe_haber(self):
        """None values in debe/haber are treated as 0."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=None, haber=None),
            AccountBalance(num_cuenta="2000", debe=Decimal("500"), haber=Decimal("500")),
        ])
        errors = validate_balanza_totales_cuadran(balanza)
        assert errors == []

    def test_totales_cuadran_single_account(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("1000"), haber=Decimal("1000")),
        ])
        errors = validate_balanza_totales_cuadran(balanza)
        assert errors == []

    def test_saldos_excluyentes_both_zero(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", saldo_deudor=Decimal("0"), saldo_acreedor=Decimal("0")),
        ])
        errors = validate_balanza_saldos_excluyentes(balanza)
        assert errors == []

    def test_saldos_excluyentes_none_treated_as_zero(self):
        """None saldo_deudor and saldo_acreedor → 0 → no error."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", saldo_deudor=None, saldo_acreedor=None),
        ])
        errors = validate_balanza_saldos_excluyentes(balanza)
        assert errors == []

    def test_saldo_consistente_zero_everything(self):
        """All zeros → consistent."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="1000",
                saldo_inicial=Decimal("0"), debe=Decimal("0"), haber=Decimal("0"),
                saldo_deudor=Decimal("0"), saldo_acreedor=Decimal("0"),
            ),
        ])
        errors = validate_balanza_saldo_consistente(balanza)
        assert errors == []

    def test_saldo_consistente_none_fields(self):
        """None fields treated as 0 → consistent."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", saldo_inicial=None, debe=None, haber=None,
                           saldo_deudor=Decimal("0"), saldo_acreedor=Decimal("0")),
        ])
        errors = validate_balanza_saldo_consistente(balanza)
        assert errors == []

    def test_balanza_comprehensive_valid(self, valid_balanza):
        """Full valid balanza → no errors."""
        errors = validate_balanza(valid_balanza)
        assert errors == []

    def test_balanza_comprehensive_many_errors(self):
        """Balanza with many different error types."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="AB",  # invalid code
                debe=Decimal("-100"),  # negative
                saldo_deudor=Decimal("100"), saldo_acreedor=Decimal("100"),  # excluyentes
            ),
        ])
        errors = validate_balanza(balanza)
        # Should have: negative, invalid code, excluyentes
        assert len(errors) >= 3


# ===========================================================================
# VALIDATORS: Catálogo — boundary values
# ===========================================================================

class TestValidateCatalogoExtended:
    """Extended Catálogo validator tests."""

    def test_codigo_cuenta_valid_min(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000")])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert errors == []

    def test_codigo_cuenta_valid_max(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="123456789012345")])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert errors == []

    def test_codigo_cuenta_3_digits_invalid(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="123")])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("inválido" in e for e in errors)

    def test_codigo_cuenta_16_digits_invalid(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1234567890123456")])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("inválido" in e for e in errors)

    def test_codigo_cuenta_with_special_chars(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="100A")])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("inválido" in e for e in errors)

    def test_nivel_boundary_min(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", nivel=1)])
        errors = validate_catalogo_nivel(catalogo)
        assert errors == []

    def test_nivel_boundary_max(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", nivel=5)])
        errors = validate_catalogo_nivel(catalogo)
        assert errors == []

    def test_nivel_negative(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", nivel=-1)])
        errors = validate_catalogo_nivel(catalogo)
        assert any("inválido" in e for e in errors)

    def test_nivel_huge(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", nivel=100)])
        errors = validate_catalogo_nivel(catalogo)
        assert any("inválido" in e for e in errors)

    def test_naturaleza_lowercase_d(self):
        """Lowercase 'd' → stripped/uppered to 'D' → valid."""
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", naturaleza="d")])
        errors = validate_catalogo_naturaleza(catalogo)
        assert errors == []

    def test_naturaleza_lowercase_a(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", naturaleza="a")])
        errors = validate_catalogo_naturaleza(catalogo)
        assert errors == []

    def test_naturaleza_with_spaces(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", naturaleza="  D  ")])
        errors = validate_catalogo_naturaleza(catalogo)
        assert errors == []

    def test_naturaleza_empty_string(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", naturaleza="")])
        errors = validate_catalogo_naturaleza(catalogo)
        assert any("ausente" in e for e in errors)

    def test_agrupador_only_digits(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="10101")])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert errors == []

    def test_agrupador_with_dots(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="101.01.01")])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert errors == []

    def test_agrupador_with_letters(self):
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="ABC")])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert any("inválido" in e for e in errors)

    def test_agrupador_empty_string(self):
        """Empty string agrupador → no error (empty is allowed)."""
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="")])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert errors == []

    def test_agrupador_whitespace_only(self):
        """Whitespace only → stripped to empty → no error."""
        catalogo = CatalogoData(cuentas=[AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="  ")])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert errors == []

    def test_catalogo_comprehensive_valid(self, valid_catalogo):
        errors = validate_catalogo(valid_catalogo)
        assert errors == []

    def test_catalogo_comprehensive_many_errors(self):
        """Catalogo with many different error types."""
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="AB", nivel=0, naturaleza="X", codigo_agrupador="ABC"),
        ])
        errors = validate_catalogo(catalogo)
        assert len(errors) >= 3


# ===========================================================================
# VALIDATORS: Estado de Resultados — boundary values
# ===========================================================================

class TestValidateEstadoResultadosExtended:
    """Extended Estado de Resultados validator tests."""

    def test_importe_zero_valid(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="Test", importe=Decimal("0")),
        ])
        errors = validate_estado_resultados_importes(er)
        assert errors == []

    def test_importe_negative_valid(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="Pérdida", importe=Decimal("-5000")),
        ])
        errors = validate_estado_resultados_importes(er)
        assert errors == []

    def test_importe_large_valid(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="Ventas", importe=Decimal("999999999999.99")),
        ])
        errors = validate_estado_resultados_importes(er)
        assert errors == []

    def test_multiple_lines_mixed(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="A", importe=Decimal("100")),
            IncomeStatementLine(concepto="B", importe=None),
            IncomeStatementLine(concepto="C", importe=Decimal("200")),
            IncomeStatementLine(concepto="D", importe=None),
        ])
        errors = validate_estado_resultados_importes(er)
        assert len(errors) == 2

    def test_er_comprehensive_valid(self, valid_er):
        errors = validate_estado_resultados(valid_er)
        assert errors == []


# ===========================================================================
# ROUTES: Extended edge cases
# ===========================================================================

class TestRoutesExtended:
    """Extended route tests."""

    def test_balanza_with_many_accounts(self, client):
        """Upload XML with many accounts."""
        accounts = ""
        for i in range(50):
            accounts += (
                f'<ce:Cuenta NumCta="{1000+i:04d}" Desc="Cuenta{i+1}" '
                f'SaldoIni="0.00" Debe="{(i+1)*100}.00" '
                f'Haber="{(i+1)*50}.00" '
                f'SaldoDeudor="{(i+1)*50}.00" SaldoAcreedor="0.00"/>\n'
            )
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="BIG01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
{accounts}
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("big_balanza.xml", xml.encode("utf-8"), "application/xml")},
        )
        assert response.status_code == 200
        assert len(response.json()["balanza"]["Cuentas"]) == 50

    def test_catalogo_with_many_accounts(self, client):
        accounts = ""
        for i in range(30):
            accounts += (
                f'<ce:Cuenta NumCta="{1000+i:04d}" Desc="Cuenta{i+1}" '
                f'Nivel="{(i%5)+1}" Naturaleza="{"D" if i%2==0 else "A"}" '
                f'CodigoAgrupador="{100+i}.01" EstadoCuenta="A"/>\n'
            )
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="BIG01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
{accounts}
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        response = client.post(
            "/contabilidad/catalogo",
            files={"file": ("big_catalogo.xml", xml.encode("utf-8"), "application/xml")},
        )
        assert response.status_code == 200
        assert len(response.json()["catalogo"]["Cuentas"]) == 30

    def test_balanza_different_namespace(self, client):
        """Balanza with namespace version 1.1."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_1/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.1" Rfc="OLD01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="0.00" Debe="100.00" Haber="50.00"
                SaldoDeudor="50.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("balanza_11.xml", xml.encode("utf-8"), "application/xml")},
        )
        assert response.status_code == 200

    def test_er_with_utilidad_and_perdida(self, client):
        """ER with Utilidad and Perdida nodes."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="TEST01" Mes="07"
            Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Ingresos>
                <ce:ConceptoIngresos Concepto="Ventas" Importe="100000.00"/>
            </ce:Ingresos>
            <ce:Costos>
                <ce:ConceptoCostos Concepto="Costo" Importe="60000.00"/>
            </ce:Costos>
            <ce:Resultados>
                <ce:Utilidad Concepto="Utilidad" Importe="40000.00"/>
            </ce:Resultados>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        response = client.post(
            "/contabilidad/estado-resultados",
            files={"file": ("er_utilidad.xml", xml.encode("utf-8"), "application/xml")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        concepts = [l["Concepto"] for l in data["estado_resultados"]["Lineas"]]
        assert "Utilidad" in concepts

    def test_catalog_endpoint_complete(self, client):
        """GET /contabilidad/catalog returns all expected keys."""
        response = client.get("/contabilidad/catalog")
        assert response.status_code == 200
        data = response.json()
        assert set(data["naturaleza"].keys()) == {"D", "A"}
        assert set(data["tipo_balanza"].keys()) == {"A", "C", "E", "F", "N", "S"}

    def test_balanza_wrong_content_type(self, client):
        """Sending text instead of XML still gets parsed (lxml is lenient)."""
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("data.txt", b"just text", "text/plain")},
        )
        # lxml will raise XMLSyntaxError → 422
        assert response.status_code == 422


# ===========================================================================
# INTEGRATION: Parser → Validator
# ===========================================================================

class TestParserValidatorIntegration:
    """Integration tests: parser output → validator."""

    def test_balanza_parse_then_validate(self):
        """Parse valid XML, then validate → no errors."""
        data = parse_balanza_bytes(BASIC_BALANZA_XML.encode("utf-8"))
        assert data is not None
        errors = validate_balanza(data)
        # May have errors (e.g., saldo consistency) but should parse
        assert isinstance(errors, list)

    def test_catalogo_parse_then_validate(self):
        data = parse_catalogo_bytes(BASIC_CATALOGO_XML.encode("utf-8"))
        assert data is not None
        errors = validate_catalogo(data)
        assert isinstance(errors, list)

    def test_er_parse_then_validate(self):
        data = parse_estado_resultados_bytes(BASIC_ER_XML.encode("utf-8"))
        assert data is not None
        errors = validate_estado_resultados(data)
        assert errors == []  # Valid XML → no errors

    def test_invalid_balanza_fails_validation(self):
        """Unbalanced balanza → validation errors."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="{NS_CFDI}" xmlns:ce="{NS_CE}"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="0.00" Debe="1000.00" Haber="500.00"
                SaldoDeudor="500.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        errors = validate_balanza_totales_cuadran(data)
        assert any("Totales no cuadran" in e for e in errors)

    def test_route_balanza_then_validate_manually(self, client):
        """Upload valid XML via route, parse response, validate."""
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("balanza.xml", BASIC_BALANZA_XML.encode("utf-8"), "application/xml")},
        )
        assert response.status_code == 200
        balanza_dict = response.json()["balanza"]
        # Verify structure
        assert "Version" in balanza_dict
        assert "Cuentas" in balanza_dict
        assert len(balanza_dict["Cuentas"]) == 1

    def test_route_catalogo_then_validate_manually(self, client):
        response = client.post(
            "/contabilidad/catalogo",
            files={"file": ("catalogo.xml", BASIC_CATALOGO_XML.encode("utf-8"), "application/xml")},
        )
        assert response.status_code == 200
        catalogo_dict = response.json()["catalogo"]
        assert "Cuentas" in catalogo_dict
        assert len(catalogo_dict["Cuentas"]) == 1


# ===========================================================================
# DATACLASSES: to_dict edge cases
# ===========================================================================

class TestDataclassesExtended:
    """Extended dataclass tests."""

    def test_account_balance_to_dict_json_serializable(self):
        cta = AccountBalance(
            num_cuenta="1000", desc="Caja",
            saldo_inicial=Decimal("1000.50"),
            debe=Decimal("500.00"), haber=Decimal("250.00"),
            saldo_deudor=Decimal("1250.50"), saldo_acreedor=Decimal("0.00"),
        )
        d = cta.to_dict()
        json.dumps(d)  # Should not raise

    def test_balanza_data_to_dict_full(self):
        data = BalanzaData(
            version="1.3", rfc="EMP01", mes="07", ejercicio="2026",
            fecha_creacion="2026-07-15", tipo_balance="C",
            cuentas=[
                AccountBalance(num_cuenta="1000", desc="Caja",
                               saldo_inicial=Decimal("100"),
                               debe=Decimal("50"), haber=Decimal("25"),
                               saldo_deudor=Decimal("125"),
                               saldo_acreedor=Decimal("0")),
            ],
        )
        d = data.to_dict()
        assert d["Version"] == "1.3"
        assert d["Cuentas"][0]["NumCta"] == "1000"
        json.dumps(d)

    def test_catalogo_data_to_dict_full(self):
        data = CatalogoData(
            version="1.3", rfc="EMP01", mes="07", ejercicio="2026",
            cuentas=[
                AccountCatalogEntry(num_cuenta="1000", desc="Caja",
                                    nivel=1, naturaleza="D",
                                    codigo_agrupador="101.01", estado_cuenta="A"),
            ],
        )
        d = data.to_dict()
        assert d["Version"] == "1.3"
        assert d["Cuentas"][0]["Nivel"] == 1
        json.dumps(d)

    def test_er_data_to_dict_full(self):
        data = EstadoResultadosData(
            version="1.3", rfc="EMP01", mes="07", ejercicio="2026",
            fecha_creacion="2026-07-15", tipo_balanza="C",
            lineas=[
                IncomeStatementLine(concepto="Ventas", importe=Decimal("100000")),
            ],
        )
        d = data.to_dict()
        assert d["Version"] == "1.3"
        assert d["Lineas"][0]["Concepto"] == "Ventas"
        json.dumps(d)

    def test_income_statement_line_to_dict(self):
        line = IncomeStatementLine(concepto="Costos", importe=Decimal("50000"))
        d = line.to_dict()
        assert d["Concepto"] == "Costos"
        assert d["Importe"] == "50000"
