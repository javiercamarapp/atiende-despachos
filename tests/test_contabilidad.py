# -*- coding: utf-8 -*-
"""
test_contabilidad.py — Tests del módulo de Contabilidad Electrónica (parser + validators + routes).

Cobertura:
  Parse Balanza: XML válido, XML sin Balanza, XML inválido, bytes, campos extraídos,
                 múltiples cuentas, whitespace, From bytes.
  Parse Catálogo: XML válido, XML sin Catálogo, bytes, campos, múltiples cuentas,
                  campos nivel/naturaleza/agrupador.
  Parse EstadoResultados: XML válido, XML sin ER, bytes, campos, con agrupación.
  Validators Balanza: saldos no negativos, código cuenta, totales cuadran,
                      saldos excluyentes, saldo consistente, vacío, None.
  Validators Catálogo: código cuenta, nivel 1-5, naturaleza D/A, agrupador,
                       vacío, None.
  Validators ER: importe no nulo, vacío, None.
  Routes: POST /balanza, POST /catalogo, POST /estado-resultados, GET /catalog,
          archivo vacío, XML inválido, endpoint no encontrado.
  Edge cases: Many accounts, many entries, whitespace cleaning, to_dict
              serializable, decimal precision.
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
# XML templates
# ---------------------------------------------------------------------------

SIMPLE_BALANZA_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="5000.00" Debe="2000.00" Haber="1000.00"
                SaldoDeudor="6000.00" SaldoAcreedor="0.00"/>
            <ce:Cuenta NumCta="2000" Desc="Proveedores"
                SaldoIni="6000.00" Debe="5000.00" Haber="6000.00"
                SaldoDeudor="0.00" SaldoAcreedor="7000.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""

BALANZA_UNBALANCED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="0.00" Debe="1000.00" Haber="500.00"
                SaldoDeudor="500.00" SaldoAcreedor="0.00"/>
            <ce:Cuenta NumCta="2000" Desc="Proveedores"
                SaldoIni="0.00" Debe="200.00" Haber="500.00"
                SaldoDeudor="0.00" SaldoAcreedor="300.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""

SIMPLE_CATALOGO_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                Nivel="1" Naturaleza="D"
                CodigoAgrupador="101.01.01" EstadoCuenta="A"/>
            <ce:Cuenta NumCta="1100" Desc="Bancos"
                Nivel="2" Naturaleza="D"
                CodigoAgrupador="101.01.02" EstadoCuenta="A"/>
            <ce:Cuenta NumCta="2000" Desc="Proveedores"
                Nivel="1" Naturaleza="A"
                CodigoAgrupador="201.01" EstadoCuenta="A"/>
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""

SIMPLE_ER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="EMISOR010101AAA"
            Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Ingresos>
                <ce:ConceptoIngresos Concepto="Ventas" Importe="100000.00"/>
                <ce:ConceptoIngresos Concepto="Servicios" Importe="50000.00"/>
            </ce:Ingresos>
            <ce:Costos>
                <ce:ConceptoCostos Concepto="Costo de mercancía" Importe="60000.00"/>
            </ce:Costos>
            <ce:Gastos>
                <ce:ConceptoGastos Concepto="Sueldos" Importe="20000.00"/>
                <ce:ConceptoGastos Concepto="Renta" Importe="5000.00"/>
            </ce:Gastos>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""

ER_WITH_UTILIDAD_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:EstadoResultados Version="1.3" Rfc="TEST01" Mes="07"
            Ejercicio="2026" FechaCreacion="2026-07-15" TipoBalanza="C">
            <ce:Ingresos>
                <ce:MontoIngresos Concepto="Ingresos totales" Importe="150000.00"/>
            </ce:Ingresos>
            <ce:Costos>
                <ce:MontoCostos Concepto="Costos totales" Importe="60000.00"/>
            </ce:Costos>
            <ce:Gastos>
                <ce:MontoGastos Concepto="Gastos totales" Importe="25000.00"/>
            </ce:Gastos>
            <ce:Utilidad Concepto="Utilidad del ejercicio" Importe="65000.00"/>
        </ce:EstadoResultados>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_balanza_xml(tmp_path) -> str:
    path = tmp_path / "balanza_simple.xml"
    path.write_text(SIMPLE_BALANZA_XML, encoding="utf-8")
    return str(path)


@pytest.fixture
def simple_catalogo_xml(tmp_path) -> str:
    path = tmp_path / "catalogo_simple.xml"
    path.write_text(SIMPLE_CATALOGO_XML, encoding="utf-8")
    return str(path)


@pytest.fixture
def simple_er_xml(tmp_path) -> str:
    path = tmp_path / "er_simple.xml"
    path.write_text(SIMPLE_ER_XML, encoding="utf-8")
    return str(path)


@pytest.fixture
def no_balanza_xml(tmp_path) -> str:
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa/>
</cfdi:Comprobante>"""
    path = tmp_path / "no_balanza.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def valid_balanza_data() -> BalanzaData:
    """BalanzaData completo y válido para pruebas de validador."""
    return BalanzaData(
        version="1.3",
        rfc="EMISOR010101AAA",
        mes="07",
        ejercicio="2026",
        fecha_creacion="2026-07-15",
        tipo_balance="C",
        cuentas=[
            AccountBalance(
                num_cuenta="1000", desc="Caja",
                saldo_inicial=Decimal("5000.00"),
                debe=Decimal("2000.00"),
                haber=Decimal("1000.00"),
                saldo_deudor=Decimal("6000.00"),
                saldo_acreedor=Decimal("0.00"),
            ),
            AccountBalance(
                num_cuenta="2000", desc="Proveedores",
                saldo_inicial=Decimal("6000.00"),
                debe=Decimal("5000.00"),
                haber=Decimal("6000.00"),
                saldo_deudor=Decimal("0.00"),
                saldo_acreedor=Decimal("7000.00"),
            ),
        ],
    )


@pytest.fixture
def valid_catalogo_data() -> CatalogoData:
    """CatalogoData completo y válido para pruebas de validador."""
    return CatalogoData(
        version="1.3",
        rfc="EMISOR010101AAA",
        mes="07",
        ejercicio="2026",
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
def valid_er_data() -> EstadoResultadosData:
    return EstadoResultadosData(
        version="1.3",
        rfc="EMISOR010101AAA",
        mes="07",
        ejercicio="2026",
        lineas=[
            IncomeStatementLine(concepto="Ingresos", importe=Decimal("150000.00")),
            IncomeStatementLine(concepto="Costos", importe=Decimal("60000.00")),
            IncomeStatementLine(concepto="Gastos", importe=Decimal("25000.00")),
        ],
    )


@pytest.fixture
def client():
    """TestClient FastAPI con el router de contabilidad registrado."""
    app = FastAPI()
    app.include_router(build_contabilidad_router())
    return TestClient(app)


# ===========================================================================
# PARSE BALANZA TESTS
# ===========================================================================

class TestParseBalanza:
    """Tests de parse_balanza_xml() y parse_balanza_bytes()."""

    def test_parse_simple_balanza(self, simple_balanza_xml):
        data = parse_balanza_xml(simple_balanza_xml)
        assert data is not None
        assert data.version == "1.3"
        assert data.rfc == "EMISOR010101AAA"
        assert data.mes == "07"
        assert data.ejercicio == "2026"
        assert data.tipo_balance == "C"
        assert len(data.cuentas) == 2

    def test_parse_balanza_cuenta_fields(self, simple_balanza_xml):
        data = parse_balanza_xml(simple_balanza_xml)
        cta = data.cuentas[0]
        assert cta.num_cuenta == "1000"
        assert cta.desc == "Caja"
        assert cta.saldo_inicial == Decimal("5000.00")
        assert cta.debe == Decimal("2000.00")
        assert cta.haber == Decimal("1000.00")
        assert cta.saldo_deudor == Decimal("6000.00")
        assert cta.saldo_acreedor == Decimal("0.00")

    def test_parse_balanza_second_account(self, simple_balanza_xml):
        data = parse_balanza_xml(simple_balanza_xml)
        cta = data.cuentas[1]
        assert cta.num_cuenta == "2000"
        assert cta.desc == "Proveedores"
        assert cta.saldo_acreedor == Decimal("7000.00")
        assert cta.saldo_deudor == Decimal("0.00")

    def test_parse_balanza_from_bytes(self):
        data = parse_balanza_bytes(SIMPLE_BALANZA_XML.encode("utf-8"))
        assert data is not None
        assert len(data.cuentas) == 2

    def test_parse_balanza_returns_none_no_balanza(self, no_balanza_xml):
        data = parse_balanza_xml(no_balanza_xml)
        assert data is None

    def test_parse_balanza_returns_none_bytes_no_balanza(self):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"><ce:ContabilidadEducativa xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"/></cfdi:Comprobante>'
        data = parse_balanza_bytes(xml)
        assert data is None

    def test_parse_balanza_file_not_found(self):
        with pytest.raises(OSError):
            parse_balanza_xml("/nonexistent/file.xml")

    def test_parse_balanza_invalid_xml(self, tmp_path):
        path = tmp_path / "bad.xml"
        path.write_text("<broken>", encoding="utf-8")
        with pytest.raises(etree.XMLSyntaxError):
            parse_balanza_xml(str(path))

    def test_parse_balanza_to_dict(self):
        data = parse_balanza_bytes(SIMPLE_BALANZA_XML.encode("utf-8"))
        d = data.to_dict()
        assert isinstance(d, dict)
        assert d["Version"] == "1.3"
        assert d["Rfc"] == "EMISOR010101AAA"
        assert len(d["Cuentas"]) == 2
        assert isinstance(d["Cuentas"][0]["Debe"], str)
        json.dumps(d)

    def test_parse_balanza_cuenta_to_dict(self):
        cta = AccountBalance(
            num_cuenta="1000", desc="Caja",
            saldo_inicial=Decimal("5000.00"), debe=Decimal("2000.00"),
            haber=Decimal("1000.00"), saldo_deudor=Decimal("6000.00"),
            saldo_acreedor=Decimal("0.00"),
        )
        d = cta.to_dict()
        assert d["NumCta"] == "1000"
        assert d["Debe"] == "2000.00"

    def test_balanza_unbalanced_xml(self):
        data = parse_balanza_bytes(BALANZA_UNBALANCED_XML.encode("utf-8"))
        assert data is not None
        assert len(data.cuentas) == 2


# ===========================================================================
# PARSE CATÁLOGO TESTS
# ===========================================================================

class TestParseCatalogo:
    """Tests de parse_catalogo_xml() y parse_catalogo_bytes()."""

    def test_parse_simple_catalogo(self, simple_catalogo_xml):
        data = parse_catalogo_xml(simple_catalogo_xml)
        assert data is not None
        assert data.version == "1.3"
        assert data.rfc == "EMISOR010101AAA"
        assert data.mes == "07"
        assert data.ejercicio == "2026"
        assert len(data.cuentas) == 3

    def test_parse_catalogo_cuenta_fields(self, simple_catalogo_xml):
        data = parse_catalogo_xml(simple_catalogo_xml)
        cta = data.cuentas[0]
        assert cta.num_cuenta == "1000"
        assert cta.desc == "Caja"
        assert cta.nivel == 1
        assert cta.naturaleza == "D"
        assert cta.codigo_agrupador == "101.01.01"
        assert cta.estado_cuenta == "A"

    def test_parse_catalogo_acreedor(self, simple_catalogo_xml):
        data = parse_catalogo_xml(simple_catalogo_xml)
        cta = data.cuentas[2]
        assert cta.naturaleza == "A"
        assert cta.num_cuenta == "2000"

    def test_parse_catalogo_from_bytes(self):
        data = parse_catalogo_bytes(SIMPLE_CATALOGO_XML.encode("utf-8"))
        assert data is not None
        assert len(data.cuentas) == 3

    def test_parse_catalogo_returns_none_no_catalogo(self, no_balanza_xml):
        data = parse_catalogo_xml(no_balanza_xml)
        assert data is None

    def test_parse_catalogo_file_not_found(self):
        with pytest.raises(OSError):
            parse_catalogo_xml("/nonexistent/file.xml")

    def test_parse_catalogo_invalid_xml(self, tmp_path):
        path = tmp_path / "bad.xml"
        path.write_text("<broken>", encoding="utf-8")
        with pytest.raises(etree.XMLSyntaxError):
            parse_catalogo_xml(str(path))

    def test_parse_catalogo_to_dict(self):
        data = parse_catalogo_bytes(SIMPLE_CATALOGO_XML.encode("utf-8"))
        d = data.to_dict()
        assert isinstance(d, dict)
        assert d["Version"] == "1.3"
        assert len(d["Cuentas"]) == 3
        json.dumps(d)

    def test_catalogo_entry_to_dict(self):
        entry = AccountCatalogEntry(
            num_cuenta="1000", desc="Caja",
            nivel=1, naturaleza="D",
            codigo_agrupador="101.01", estado_cuenta="A",
        )
        d = entry.to_dict()
        assert d["NumCta"] == "1000"
        assert d["Nivel"] == 1
        assert d["Naturaleza"] == "D"


# ===========================================================================
# PARSE ESTADO RESULTADOS TESTS
# ===========================================================================

class TestParseEstadoResultados:
    """Tests de parse_estado_resultados_xml() y parse_estado_resultados_bytes()."""

    def test_parse_simple_er(self, simple_er_xml):
        data = parse_estado_resultados_xml(simple_er_xml)
        assert data is not None
        assert data.version == "1.3"
        assert data.rfc == "EMISOR010101AAA"
        assert data.mes == "07"
        assert data.ejercicio == "2026"
        assert data.tipo_balanza == "C"
        assert len(data.lineas) >= 3

    def test_parse_er_line_fields(self, simple_er_xml):
        data = parse_estado_resultados_xml(simple_er_xml)
        assert any(l.concepto == "Ventas" for l in data.lineas)
        ventas = [l for l in data.lineas if l.concepto == "Ventas"][0]
        assert ventas.importe == Decimal("100000.00")

    def test_parse_er_from_bytes(self):
        data = parse_estado_resultados_bytes(SIMPLE_ER_XML.encode("utf-8"))
        assert data is not None
        assert len(data.lineas) >= 3

    def test_parse_er_returns_none_no_er(self, no_balanza_xml):
        data = parse_estado_resultados_xml(no_balanza_xml)
        assert data is None

    def test_parse_er_file_not_found(self):
        with pytest.raises(OSError):
            parse_estado_resultados_xml("/nonexistent/file.xml")

    def test_parse_er_invalid_xml(self, tmp_path):
        path = tmp_path / "bad.xml"
        path.write_text("<broken>", encoding="utf-8")
        with pytest.raises(etree.XMLSyntaxError):
            parse_estado_resultados_xml(str(path))

    def test_parse_er_with_utilidad(self):
        data = parse_estado_resultados_bytes(ER_WITH_UTILIDAD_XML.encode("utf-8"))
        assert data is not None
        assert len(data.lineas) >= 4
        concepts = [l.concepto for l in data.lineas]
        assert "Utilidad del ejercicio" in concepts

    def test_parse_er_to_dict(self):
        data = parse_estado_resultados_bytes(SIMPLE_ER_XML.encode("utf-8"))
        d = data.to_dict()
        assert isinstance(d, dict)
        assert d["Version"] == "1.3"
        assert isinstance(d["Lineas"], list)
        json.dumps(d)

    def test_er_line_to_dict(self):
        line = IncomeStatementLine(
            concepto="Ventas", importe=Decimal("100000.00")
        )
        d = line.to_dict()
        assert d["Concepto"] == "Ventas"
        assert d["Importe"] == "100000.00"


# ===========================================================================
# VALIDATORS BALANZA TESTS
# ===========================================================================

class TestValidateBalanza:
    """Tests de validadores de Balanza de Comprobación."""

    def test_valid_balanza_no_errors(self, valid_balanza_data):
        errors = validate_balanza(valid_balanza_data)
        assert errors == []

    def test_balanza_none_returns_error(self):
        errors = validate_balanza(None)
        assert len(errors) == 1
        assert "Balanza" in errors[0]

    def test_balanza_empty_cuentas_totales(self):
        balanza = BalanzaData(cuentas=[])
        errors = validate_balanza_totales_cuadran(balanza)
        assert any("no tiene cuentas" in e for e in errors)

    def test_balanza_saldos_no_negativos_debe(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("-100.00")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert any("Debe" in e for e in errors)

    def test_balanza_saldos_no_negativos_haber(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", haber=Decimal("-50.00")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert any("Haber" in e for e in errors)

    def test_balanza_saldos_no_negativos_deudor(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", saldo_deudor=Decimal("-50.00")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert any("SaldoDeudor" in e for e in errors)

    def test_balanza_saldos_no_negativos_acreedor(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", saldo_acreedor=Decimal("-50.00")),
        ])
        errors = validate_balanza_saldos_no_negativos(balanza)
        assert any("SaldoAcreedor" in e for e in errors)

    def test_balanza_codigo_cuenta_empty(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta=""),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert any("ausente" in e for e in errors)

    def test_balanza_codigo_cuenta_too_short(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="12"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert any("inválido" in e for e in errors)

    def test_balanza_codigo_cuenta_too_long(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1234567890123456"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert any("inválido" in e for e in errors)

    def test_balanza_codigo_cuenta_letters(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="ABCD"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert any("inválido" in e for e in errors)

    def test_balanza_totales_cuadran(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("1000"), haber=Decimal("1000")),
            AccountBalance(num_cuenta="2000", debe=Decimal("500"), haber=Decimal("500")),
        ])
        errors = validate_balanza_totales_cuadran(balanza)
        assert errors == []

    def test_balanza_totales_no_cuadran(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("1000"), haber=Decimal("500")),
        ])
        errors = validate_balanza_totales_cuadran(balanza)
        assert any("Totales no cuadran" in e for e in errors)

    def test_balanza_saldos_excluyentes_both_positive(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000",
                           saldo_deudor=Decimal("100"),
                           saldo_acreedor=Decimal("100")),
        ])
        errors = validate_balanza_saldos_excluyentes(balanza)
        assert any("no pueden ambos ser > 0" in e for e in errors)

    def test_balanza_saldos_excluyentes_ok(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000",
                           saldo_deudor=Decimal("100"),
                           saldo_acreedor=Decimal("0")),
        ])
        errors = validate_balanza_saldos_excluyentes(balanza)
        assert errors == []

    def test_balanza_saldo_consistente_deudor(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="1000",
                saldo_inicial=Decimal("5000"),
                debe=Decimal("2000"),
                haber=Decimal("1000"),
                saldo_deudor=Decimal("6000"),
                saldo_acreedor=Decimal("0"),
            ),
        ])
        errors = validate_balanza_saldo_consistente(balanza)
        assert errors == []

    def test_balanza_saldo_inconsistente_deudor(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="1000",
                saldo_inicial=Decimal("5000"),
                debe=Decimal("2000"),
                haber=Decimal("1000"),
                saldo_deudor=Decimal("5500"),  # incorrecto
                saldo_acreedor=Decimal("0"),
            ),
        ])
        errors = validate_balanza_saldo_consistente(balanza)
        assert any("SaldoDeudor" in e for e in errors)

    def test_balanza_saldo_consistente_acreedor(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="2000",
                saldo_inicial=Decimal("6000"),
                debe=Decimal("5000"),
                haber=Decimal("6000"),
                saldo_deudor=Decimal("0"),
                saldo_acreedor=Decimal("7000"),
            ),
        ])
        errors = validate_balanza_saldo_consistente(balanza)
        assert errors == []

    def test_balanza_saldo_inconsistente_acreedor(self):
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="2000",
                saldo_inicial=Decimal("6000"),
                debe=Decimal("5000"),
                haber=Decimal("6000"),
                saldo_deudor=Decimal("0"),
                saldo_acreedor=Decimal("6500"),  # incorrecto
            ),
        ])
        errors = validate_balanza_saldo_consistente(balanza)
        assert any("SaldoAcreedor" in e for e in errors)


# ===========================================================================
# VALIDATORS CATÁLOGO TESTS
# ===========================================================================

class TestValidateCatalogo:
    """Tests de validadores de Catálogo de Cuentas."""

    def test_valid_catalogo_no_errors(self, valid_catalogo_data):
        errors = validate_catalogo(valid_catalogo_data)
        assert errors == []

    def test_catalogo_none_returns_error(self):
        errors = validate_catalogo(None)
        assert len(errors) == 1
        assert "Catálogo" in errors[0]

    def test_catalogo_codigo_empty(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta=""),
        ])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("ausente" in e for e in errors)

    def test_catalogo_codigo_letters(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="ABCD"),
        ])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("inválido" in e for e in errors)

    def test_catalogo_codigo_short(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="12"),
        ])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("inválido" in e for e in errors)

    def test_catalogo_codigo_long(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1234567890123456"),
        ])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert any("inválido" in e for e in errors)

    def test_catalogo_nivel_none(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", nivel=None),
        ])
        errors = validate_catalogo_nivel(catalogo)
        assert any("ausente" in e for e in errors)

    def test_catalogo_nivel_zero(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", nivel=0),
        ])
        errors = validate_catalogo_nivel(catalogo)
        assert any("inválido" in e for e in errors)

    def test_catalogo_nivel_six(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", nivel=6),
        ])
        errors = validate_catalogo_nivel(catalogo)
        assert any("inválido" in e for e in errors)

    def test_catalogo_nivel_valid_1_to_5(self):
        for nivel in [1, 2, 3, 4, 5]:
            catalogo = CatalogoData(cuentas=[
                AccountCatalogEntry(num_cuenta="1000", nivel=nivel),
            ])
            errors = validate_catalogo_nivel(catalogo)
            assert errors == []

    def test_catalogo_naturaleza_none(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", naturaleza=None),
        ])
        errors = validate_catalogo_naturaleza(catalogo)
        assert any("ausente" in e for e in errors)

    def test_catalogo_naturaleza_invalid(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", naturaleza="X"),
        ])
        errors = validate_catalogo_naturaleza(catalogo)
        assert any("inválida" in e for e in errors)

    def test_catalogo_naturaleza_deudor(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", naturaleza="D"),
        ])
        errors = validate_catalogo_naturaleza(catalogo)
        assert errors == []

    def test_catalogo_naturaleza_acreedor(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", naturaleza="A"),
        ])
        errors = validate_catalogo_naturaleza(catalogo)
        assert errors == []

    def test_catalogo_agrupador_valid(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="101.01"),
        ])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert errors == []

    def test_catalogo_agrupador_letters(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", codigo_agrupador="ABC"),
        ])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert any("inválido" in e for e in errors)

    def test_catalogo_agrupador_none_no_error(self):
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", codigo_agrupador=None),
        ])
        errors = validate_catalogo_codigo_agrupador(catalogo)
        assert errors == []


# ===========================================================================
# VALIDATORS ESTADO RESULTADOS TESTS
# ===========================================================================

class TestValidateEstadoResultados:
    """Tests de validadores de Estado de Resultados."""

    def test_valid_er_no_errors(self, valid_er_data):
        errors = validate_estado_resultados(valid_er_data)
        assert errors == []

    def test_er_none_returns_error(self):
        errors = validate_estado_resultados(None)
        assert len(errors) == 1
        assert "Estado de Resultados" in errors[0]

    def test_er_importe_none(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="Ventas", importe=None),
        ])
        errors = validate_estado_resultados_importes(er)
        assert any("ausente" in e for e in errors)

    def test_er_empty_lineas_no_error(self):
        er = EstadoResultadosData(lineas=[])
        errors = validate_estado_resultados(er)
        assert errors == []

    def test_er_importe_valid(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="Ventas", importe=Decimal("100000.00")),
        ])
        errors = validate_estado_resultados_importes(er)
        assert errors == []


# ===========================================================================
# ROUTE TESTS
# ===========================================================================

class TestRoutes:
    """Tests de endpoints FastAPI de contabilidad."""

    def test_balanza_endpoint_valid(self, client):
        xml_bytes = SIMPLE_BALANZA_XML.encode("utf-8")
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("balanza.xml", xml_bytes, "application/xml")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "balanza" in data
        assert data["balanza"]["Version"] == "1.3"
        assert len(data["balanza"]["Cuentas"]) == 2

    def test_balanza_endpoint_empty_file(self, client):
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("empty.xml", b"", "application/xml")},
        )
        assert response.status_code == 400

    def test_balanza_endpoint_invalid_xml(self, client):
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("bad.xml", b"<broken>", "application/xml")},
        )
        assert response.status_code == 422

    def test_balanza_endpoint_not_found(self, client):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0"/>'
        response = client.post(
            "/contabilidad/balanza",
            files={"file": ("nolabel.xml", xml, "application/xml")},
        )
        assert response.status_code == 404

    def test_catalogo_endpoint_valid(self, client):
        xml_bytes = SIMPLE_CATALOGO_XML.encode("utf-8")
        response = client.post(
            "/contabilidad/catalogo",
            files={"file": ("catalogo.xml", xml_bytes, "application/xml")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "catalogo" in data
        assert data["catalogo"]["Version"] == "1.3"
        assert len(data["catalogo"]["Cuentas"]) == 3

    def test_catalogo_endpoint_empty_file(self, client):
        response = client.post(
            "/contabilidad/catalogo",
            files={"file": ("empty.xml", b"", "application/xml")},
        )
        assert response.status_code == 400

    def test_catalogo_endpoint_invalid_xml(self, client):
        response = client.post(
            "/contabilidad/catalogo",
            files={"file": ("bad.xml", b"<broken>", "application/xml")},
        )
        assert response.status_code == 422

    def test_catalogo_endpoint_not_found(self, client):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0"/>'
        response = client.post(
            "/contabilidad/catalogo",
            files={"file": ("nolabel.xml", xml, "application/xml")},
        )
        assert response.status_code == 404

    def test_estado_resultados_endpoint_valid(self, client):
        xml_bytes = SIMPLE_ER_XML.encode("utf-8")
        response = client.post(
            "/contabilidad/estado-resultados",
            files={"file": ("er.xml", xml_bytes, "application/xml")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "estado_resultados" in data
        assert data["estado_resultados"]["Version"] == "1.3"
        assert len(data["estado_resultados"]["Lineas"]) >= 3

    def test_estado_resultados_endpoint_empty_file(self, client):
        response = client.post(
            "/contabilidad/estado-resultados",
            files={"file": ("empty.xml", b"", "application/xml")},
        )
        assert response.status_code == 400

    def test_estado_resultados_endpoint_invalid_xml(self, client):
        response = client.post(
            "/contabilidad/estado-resultados",
            files={"file": ("bad.xml", b"<broken>", "application/xml")},
        )
        assert response.status_code == 422

    def test_estado_resultados_endpoint_not_found(self, client):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0"/>'
        response = client.post(
            "/contabilidad/estado-resultados",
            files={"file": ("nolabel.xml", xml, "application/xml")},
        )
        assert response.status_code == 404

    def test_catalog_endpoint(self, client):
        response = client.get("/contabilidad/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "naturaleza" in data
        assert "tipo_balanza" in data
        assert data["naturaleza"]["D"] == "Deudor"
        assert data["naturaleza"]["A"] == "Acreedor"
        assert "C" in data["tipo_balanza"]


# ===========================================================================
# EDGE CASE TESTS
# ===========================================================================

class TestEdgeCases:
    """Tests de edge cases y situaciones especiales."""

    def test_many_accounts_balanza(self):
        """XML con muchas cuentas se parsea correctamente."""
        accounts_xml = ""
        for i in range(15):
            accounts_xml += (
                f'<ce:Cuenta NumCta="{1000 + i:04d}" Desc="Cuenta{i+1}" '
                f'SaldoIni="0.00" Debe="{(i+1)*100}.00" '
                f'Haber="{(i+1)*50}.00" '
                f'SaldoDeudor="{(i+1)*50}.00" SaldoAcreedor="0.00"/>\n'
            )
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
{accounts_xml}
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.cuentas) == 15

    def test_many_accounts_catalogo(self):
        """XML con muchas cuentas de catálogo."""
        accounts_xml = ""
        for i in range(20):
            accounts_xml += (
                f'<ce:Cuenta NumCta="{1000+i:04d}" Desc="Cuenta{i+1}" '
                f'Nivel="{(i%5)+1}" Naturaleza="{"D" if i%2==0 else "A"}" '
                f'CodigoAgrupador="{100+i}.01" EstadoCuenta="A"/>\n'
            )
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Catalogo Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15">
{accounts_xml}
        </ce:Catalogo>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_catalogo_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.cuentas) == 20

    def test_balanza_with_zero_values(self):
        """Balanza con valores en cero."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="1000" Desc="Caja"
                SaldoIni="0.00" Debe="0.00" Haber="0.00"
                SaldoDeudor="0.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.cuentas) == 1
        errors = validate_balanza(data)
        assert errors == []

    def test_balanza_negative_values_fail_validation(self):
        """Balanza con valores negativos falla validación."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="1000",
                saldo_inicial=Decimal("100"),
                debe=Decimal("-50"),
                haber=Decimal("0"),
                saldo_deudor=Decimal("50"),
                saldo_acreedor=Decimal("0"),
            ),
        ])
        errors = validate_balanza(balanza)
        assert any("Debe" in e and ">= 0" in e for e in errors)

    def test_catalogo_whitespace_naturaleza(self):
        """Naturaleza con espacios se limpia."""
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", naturaleza=" D "),
        ])
        errors = validate_catalogo_naturaleza(catalogo)
        assert errors == []

    def test_balanza_whitespace_in_num_cuenta(self):
        """NumCta con espacios se limpia en parsing."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa>
        <ce:Balanza Version="1.3" Rfc="TEST01" Mes="07" Ejercicio="2026"
            FechaCreacion="2026-07-15" TipoBalance="C">
            <ce:Cuenta NumCta="  1000  " Desc="Caja"
                SaldoIni="0.00" Debe="0.00" Haber="0.00"
                SaldoDeudor="0.00" SaldoAcreedor="0.00"/>
        </ce:Balanza>
    </ce:ContabilidadEducativa>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.cuentas[0].num_cuenta == "1000"

    def test_balanza_complement_empty_balanza(self):
        """Complemento con ContabilidadEducativa pero sin nodo Balanza."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <ce:ContabilidadEducativa/>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is None

    def test_balanza_no_contabilidad_complement(self):
        """CFDI con otro complemento (no contabilidad)."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="I">
    <cfdi:Complemento/>
</cfdi:Comprobante>"""
        data = parse_balanza_bytes(xml.encode("utf-8"))
        assert data is None

    def test_balanza_one_account_validates(self):
        """Una sola cuenta válida pasa todas las validaciones."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(
                num_cuenta="1000",
                saldo_inicial=Decimal("0"),
                debe=Decimal("500"),
                haber=Decimal("500"),
                saldo_deudor=Decimal("0"),
                saldo_acreedor=Decimal("0"),
            ),
        ])
        errors = validate_balanza(balanza)
        assert errors == []

    def test_catalogo_many_valid_entries(self):
        """Muchas entradas válidas en catálogo pasan validación."""
        entries = [
            AccountCatalogEntry(
                num_cuenta=f"{1000+i:04d}",
                desc=f"Cuenta{i+1}",
                nivel=(i % 5) + 1,
                naturaleza="D" if i % 2 == 0 else "A",
            )
            for i in range(30)
        ]
        catalogo = CatalogoData(cuentas=entries)
        errors = validate_catalogo(catalogo)
        assert errors == []

    def test_er_many_valid_lines(self):
        """Muchas líneas válidas en ER pasan validación."""
        lineas = [
            IncomeStatementLine(
                concepto=f"Ingreso{i+1}",
                importe=Decimal(f"{(i+1)*1000}.00"),
            )
            for i in range(20)
        ]
        er = EstadoResultadosData(lineas=lineas)
        errors = validate_estado_resultados(er)
        assert errors == []

    def test_balanza_to_dict_serializable(self):
        """BalanzaData.to_dict() produce dict JSON-serializable."""
        balanza = BalanzaData(
            version="1.3", rfc="TEST01", mes="07", ejercicio="2026",
            cuentas=[
                AccountBalance(
                    num_cuenta="1000", desc="Caja",
                    saldo_inicial=Decimal("1000"),
                    debe=Decimal("500"), haber=Decimal("300"),
                    saldo_deudor=Decimal("1200"),
                    saldo_acreedor=Decimal("0"),
                ),
            ],
        )
        d = balanza.to_dict()
        json.dumps(d)
        assert isinstance(d["Cuentas"][0]["Debe"], str)

    def test_catalogo_to_dict_serializable(self):
        """CatalogoData.to_dict() produce dict JSON-serializable."""
        catalogo = CatalogoData(
            version="1.3", rfc="TEST01",
            cuentas=[
                AccountCatalogEntry(
                    num_cuenta="1000", desc="Caja",
                    nivel=1, naturaleza="D",
                ),
            ],
        )
        d = catalogo.to_dict()
        json.dumps(d)

    def test_er_to_dict_serializable(self):
        """EstadoResultadosData.to_dict() produce dict JSON-serializable."""
        er = EstadoResultadosData(
            version="1.3",
            lineas=[
                IncomeStatementLine(
                    concepto="Ingresos", importe=Decimal("100000.00"),
                ),
            ],
        )
        d = er.to_dict()
        json.dumps(d)

    def test_catalogo_codigo_valid_4_digits(self):
        """Código de 4 dígitos es válido."""
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000"),
        ])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert errors == []

    def test_catalogo_codigo_valid_15_digits(self):
        """Código de 15 dígitos es válido."""
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="123456789012345"),
        ])
        errors = validate_catalogo_codigo_cuenta(catalogo)
        assert errors == []

    def test_balanza_code_valid_4_digits(self):
        """Código de balanza de 4 dígitos es válido."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert errors == []

    def test_balanza_code_valid_15_digits(self):
        """Código de balanza de 15 dígitos es válido."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="123456789012345"),
        ])
        errors = validate_balanza_codigo_cuenta(balanza)
        assert errors == []

    def test_balanza_mixed_valid_invalid_accounts(self):
        """Balanza mixta con cuentas válidas e inválidas reporta errores."""
        balanza = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("1000"), haber=Decimal("1000")),
            AccountBalance(num_cuenta="AB", debe=Decimal("500"), haber=Decimal("500")),
        ])
        errors = validate_balanza(balanza)
        # Should have error for "AB" code
        assert any("AB" in e for e in errors)

    def test_catalogo_mixed_valid_invalid(self):
        """Catálogo mixto reporta errores de código inválido."""
        catalogo = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", nivel=1, naturaleza="D"),
            AccountCatalogEntry(num_cuenta="12", nivel=1, naturaleza="D"),
        ])
        errors = validate_catalogo(catalogo)
        assert any("12" in e for e in errors)
