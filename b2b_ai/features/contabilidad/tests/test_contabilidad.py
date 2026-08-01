# -*- coding: utf-8 -*-
"""Tests for the Contabilidad Electrónica SAT module."""
from __future__ import annotations
import io
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from b2b_ai.features.contabilidad.parser import (
    AccountBalance, BalanzaData, AccountCatalogEntry, CatalogoData,
    IncomeStatementLine, EstadoResultadosData,
    parse_balanza_bytes, parse_catalogo_bytes, parse_estado_resultados_bytes,
)
from b2b_ai.features.contabilidad.validators import (
    validate_balanza, validate_balanza_saldos_no_negativos,
    validate_balanza_codigo_cuenta, validate_balanza_totales_cuadran,
    validate_balanza_saldos_excluyentes, validate_balanza_saldo_consistente,
    validate_catalogo, validate_catalogo_nivel, validate_catalogo_naturaleza,
    validate_estado_resultados,
)


# ── Helper: build minimal SAT XML ──

NS = "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"

def _balanza_xml(cuentas_attrs=None):
    """Build a minimal Balanza XML for testing."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<ce:ContabilidadEducativa xmlns:ce="{NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <ce:Balanza Version="1.3" Rfc="TEST001" Mes="01" Ejercicio="2025" TipoBalance="C">',
    ]
    if cuentas_attrs:
        for attrs in cuentas_attrs:
            line = '    <ce:Cuenta '
            line += ' '.join(f'{k}="{v}"' for k, v in attrs.items())
            line += '/>'
            lines.append(line)
    else:
        lines.append('    <ce:Cuenta NumCta="1000" Debe="1000" Haber="500" SaldoDeudor="500" SaldoIni="0" SaldoAcreedor="0" Desc="Caja"/>')
    lines.append('  </ce:Balanza>')
    lines.append('</ce:ContabilidadEducativa>')
    return "\n".join(lines).encode()


# ── Parser Tests ──

class TestBalanzaParser:
    def test_parse_valid(self):
        xml = _balanza_xml()
        data = parse_balanza_bytes(xml)
        assert data is not None
        assert data.version == "1.3"
        assert data.rfc == "TEST001"
        assert len(data.cuentas) == 1
        assert data.cuentas[0].num_cuenta == "1000"

    def test_parse_no_balanza_node(self):
        xml = b'<?xml version="1.0"?><ce:Root xmlns:ce="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"></ce:Root>'
        data = parse_balanza_bytes(xml)
        assert data is None

    def test_parse_invalid_xml(self):
        with pytest.raises(Exception):
            parse_balanza_bytes(b"not xml")

    def test_to_dict(self):
        xml = _balanza_xml()
        data = parse_balanza_bytes(xml)
        d = data.to_dict()
        assert d["Version"] == "1.3"
        assert len(d["Cuentas"]) == 1

    def test_account_to_dict(self):
        acc = AccountBalance(num_cuenta="1000", debe=Decimal("100"))
        d = acc.to_dict()
        assert d["NumCta"] == "1000"
        assert d["Debe"] == "100"


# ── Validator Tests: Balanza ──

class TestBalanzaValidators:
    def _valid_balanza(self):
        return BalanzaData(
            version="1.3", rfc="TEST", mes="01", ejercicio="2025",
            cuentas=[AccountBalance(num_cuenta="1000", debe=Decimal("1000"),
                                    haber=Decimal("1000"), saldo_deudor=Decimal("0"),
                                    saldo_acreedor=Decimal("0"), saldo_inicial=Decimal("0"))]
        )

    def test_saldos_no_negativos_valid(self):
        b = self._valid_balanza()
        assert validate_balanza_saldos_no_negativos(b) == []

    def test_saldos_no_negativos_negative(self):
        b = BalanzaData(cuentas=[AccountBalance(num_cuenta="1000", debe=Decimal("-100"))])
        errors = validate_balanza_saldos_no_negativos(b)
        assert len(errors) > 0

    def test_codigo_cuenta_valid(self):
        b = self._valid_balanza()
        assert validate_balanza_codigo_cuenta(b) == []

    def test_codigo_cuenta_invalid(self):
        b = BalanzaData(cuentas=[AccountBalance(num_cuenta="AB")])
        errors = validate_balanza_codigo_cuenta(b)
        assert len(errors) > 0

    def test_totales_cuadran(self):
        b = self._valid_balanza()
        assert validate_balanza_totales_cuadran(b) == []

    def test_totales_no_cuadran(self):
        b = BalanzaData(cuentas=[
            AccountBalance(num_cuenta="1000", debe=Decimal("1000"), haber=Decimal("500")),
            AccountBalance(num_cuenta="2000", debe=Decimal("200"), haber=Decimal("500")),
        ])
        errors = validate_balanza_totales_cuadran(b)
        assert len(errors) > 0

    def test_saldos_excluyentes_ok(self):
        b = self._valid_balanza()
        assert validate_balanza_saldos_excluyentes(b) == []

    def test_saldos_excluyentes_conflict(self):
        b = BalanzaData(cuentas=[AccountBalance(
            num_cuenta="1000", saldo_deudor=Decimal("100"), saldo_acreedor=Decimal("100"))])
        errors = validate_balanza_saldos_excluyentes(b)
        assert len(errors) > 0

    def test_validate_balanza_none(self):
        errors = validate_balanza(None)
        assert len(errors) == 1


# ── Validator Tests: Catálogo ──

class TestCatalogoValidators:
    def _valid_catalogo(self):
        return CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", desc="Caja", nivel=1,
                                naturaleza="D", codigo_agrupador="101")
        ])

    def test_validate_catalogo_none(self):
        errors = validate_catalogo(None)
        assert len(errors) == 1

    def test_validate_catalogo_valid(self):
        c = self._valid_catalogo()
        errors = validate_catalogo(c)
        assert errors == []

    def test_nivel_invalid(self):
        c = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", nivel=99, naturaleza="D")
        ])
        errors = validate_catalogo_nivel(c)
        assert len(errors) > 0

    def test_naturaleza_invalid(self):
        c = CatalogoData(cuentas=[
            AccountCatalogEntry(num_cuenta="1000", nivel=1, naturaleza="X")
        ])
        errors = validate_catalogo_naturaleza(c)
        assert len(errors) > 0


# ── Validator Tests: EstadoResultados ──

class TestEstadoResultadosValidators:
    def test_validate_none(self):
        errors = validate_estado_resultados(None)
        assert len(errors) == 1

    def test_validate_valid(self):
        er = EstadoResultadosData(lineas=[
            IncomeStatementLine(concepto="Ingresos", importe=Decimal("1000"))
        ])
        errors = validate_estado_resultados(er)
        assert errors == []


# ── Route Tests ──

class TestContabilidadRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.contabilidad.routes import build_contabilidad_router
        from fastapi import FastAPI
        app = FastAPI()
        router = build_contabilidad_router()
        app.include_router(router)
        return TestClient(app)

    def test_balanza_upload(self, client):
        xml = _balanza_xml()
        resp = client.post("/contabilidad/balanza",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_balanza_empty(self, client):
        resp = client.post("/contabilidad/balanza",
                           files={"file": ("test.xml", io.BytesIO(b""), "application/xml")})
        assert resp.status_code == 400

    def test_balanza_no_balanza_node(self, client):
        xml = b'<?xml version="1.0"?><Root></Root>'
        resp = client.post("/contabilidad/balanza",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 404

    def test_catalog_endpoint(self, client):
        resp = client.get("/contabilidad/catalog")
        assert resp.status_code == 200
        assert "naturaleza" in resp.json()
