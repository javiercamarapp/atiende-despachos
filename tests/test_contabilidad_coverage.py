# -*- coding: utf-8 -*-
"""
test_contabilidad_coverage.py — Additional tests to close coverage gaps in contabilidad module.

Targets specific uncovered lines:
  parser.py: 171, 174-175 (_dec edge cases), 181 (_attr_strip with None node), 283-284 (invalid Nivel)
"""
from __future__ import annotations

from decimal import Decimal
from lxml import etree
import pytest

from b2b_ai.features.contabilidad.parser import (
    _dec,
    _attr_strip,
    parse_catalogo_bytes,
    CatalogoData,
    AccountCatalogEntry,
)


# ---------------------------------------------------------------------------
# _dec() helper — lines 168-175
# ---------------------------------------------------------------------------

class TestDecHelper:
    """Tests for _dec() to cover lines 171, 174-175."""

    def test_dec_none_returns_none(self):
        """Line 171: _dec(None) should return None."""
        assert _dec(None) is None

    def test_dec_empty_string_returns_none(self):
        """Line 171: _dec('') should return None."""
        assert _dec("") is None

    def test_dec_whitespace_returns_none(self):
        """Line 171: _dec('   ') should return None."""
        assert _dec("   ") is None

    def test_dec_invalid_value_returns_none(self):
        """Lines 174-175: _dec('not_a_number') should return None."""
        assert _dec("not_a_number") is None

    def test_dec_invalid_operation_returns_none(self):
        """Lines 174-175: _dec with value causing InvalidOperation."""
        # This should trigger the exception handler
        assert _dec("1.2.3.4") is None

    def test_dec_valid_value_returns_decimal(self):
        """Line 173: _dec('123.45') returns Decimal('123.45')."""
        result = _dec("123.45")
        assert result == Decimal("123.45")

    def test_dec_whitespace_strips(self):
        """Line 173: _dec('  500.00  ') strips and returns Decimal."""
        result = _dec("  500.00  ")
        assert result == Decimal("500.00")


# ---------------------------------------------------------------------------
# _attr_strip() helper — line 181
# ---------------------------------------------------------------------------

class TestAttrStrip:
    """Tests for _attr_strip() to cover line 181."""

    def test_attr_strip_none_node_returns_none(self):
        """Line 181: _attr_strip(None, 'x') should return None."""
        assert _attr_strip(None, "x") is None

    def test_attr_strip_existing_attr(self):
        """Normal case: attribute exists."""
        node = etree.Element("Cuenta", NumCta="1000")
        assert _attr_strip(node, "NumCta") == "1000"

    def test_attr_strip_missing_attr(self):
        """Attribute doesn't exist."""
        node = etree.Element("Cuenta")
        assert _attr_strip(node, "NumCta") is None

    def test_attr_strip_empty_attr(self):
        """Attribute is empty string."""
        node = etree.Element("Cuenta", NumCta="")
        assert _attr_strip(node, "NumCta") is None

    def test_attr_strip_whitespace_attr(self):
        """Attribute is whitespace-only."""
        node = etree.Element("Cuenta", NumCta="  ")
        assert _attr_strip(node, "NumCta") is None


# ---------------------------------------------------------------------------
# _parse_catalogo_account with invalid Nivel — lines 283-284
# ---------------------------------------------------------------------------

class TestCatalogoInvalidNivel:
    """Tests for parsing catalogo accounts with invalid Nivel values (lines 283-284)."""

    def test_catalogo_invalid_nivel_sets_none(self):
        """Line 283-284: Nivel='abc' should be caught and set to None."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="1000" Desc="Caja" Nivel="abc"
                Naturaleza="D" CodigoAgrupador="101" EstadoCuenta="A"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode())
        assert isinstance(data, CatalogoData)
        assert len(data.cuentas) == 1
        cuenta = data.cuentas[0]
        assert cuenta.nivel is None
        assert cuenta.num_cuenta == "1000"

    def test_catalogo_float_nivel_sets_none(self):
        """Nivel='3.5' (float string) should be caught by int() and set to None."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="2000" Desc="Proveedores" Nivel="3.5"
                Naturaleza="A" CodigoAgrupador="201"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode())
        assert len(data.cuentas) == 1
        assert data.cuentas[0].nivel is None

    def test_catalogo_valid_nivel(self):
        """Nivel='3' should parse correctly."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="3000" Desc="Ingresos" Nivel="3"
                Naturaleza="A" CodigoAgrupador="301"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode())
        assert data.cuentas[0].nivel == 3

    def test_catalogo_missing_nivel(self):
        """Nivel attribute not present → nivel=None (covered by different branch, line 280)."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00" TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026" FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="4000" Desc="Gastos"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode())
        assert data.cuentas[0].nivel is None
