# -*- coding: utf-8 -*-
"""Tests for the Contabilidad Electrónica SAT XML generation module."""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from b2b_ai.features.contabilidad_electronica.models import (
    BalanzaRequest, BalanzaRow, CatalogoCuenta, ContabilidadElectronicaResponse,
    TipoCuenta, CuentaContable,
)
from b2b_ai.features.contabilidad_electronica.generator import (
    generate_balanza_xml, generate_catalogo_xml,
)
from b2b_ai.features.contabilidad_electronica.validators import (
    validate_balanza, validate_balanza_totals, validate_catalogo,
)


# ── Model Tests ──

class TestModels:
    def test_balanza_row_construction(self):
        r = BalanzaRow(codigo_cuenta="1001")
        assert r.codigo_cuenta == "1001"
        assert r.debe == 0.0
        assert r.haber == 0.0

    def test_balanza_request_construction(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1)
        assert req.periodo == "2025-01"
        assert req.rows == []

    def test_catalogo_cuenta_construction(self):
        c = CatalogoCuenta(codigo="1001", descripcion="Caja", tipo=TipoCuenta.ACTIVO)
        assert c.nivel == 1
        assert c.status == "A"

    def test_contabilidad_response_defaults(self):
        r = ContabilidadElectronicaResponse()
        assert r.estado == "generado"
        assert r.errores == []

    def test_tipo_cuenta_values(self):
        assert TipoCuenta.ACTIVO.value == "Activo"
        assert TipoCuenta.PASIVO.value == "Pasivo"
        assert TipoCuenta.CAPITAL.value == "Capital"


# ── Generator Tests ──

class TestGenerator:
    def test_balanza_xml_contains_namespace(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[
            BalanzaRow(codigo_cuenta="1001", saldo_inicial=1000, debe=500, haber=200, saldo_final=1300)
        ])
        xml = generate_balanza_xml(req)
        assert "ContabilidadEducativa" in xml
        assert "1001" in xml
        assert "500.00" in xml

    def test_balanza_xml_empty_rows(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[])
        xml = generate_balanza_xml(req)
        assert "Balanza" in xml

    def test_catalogo_xml(self):
        cuentas = [CatalogoCuenta(codigo="1001", descripcion="Caja", tipo=TipoCuenta.ACTIVO)]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert "Catalogo" in xml
        assert "1001" in xml
        assert "Caja" in xml

    def test_deudor_acreedor_calculation(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[
            BalanzaRow(codigo_cuenta="1001", saldo_final=1500.0),
            BalanzaRow(codigo_cuenta="1002", saldo_final=-500.0),
        ])
        xml = generate_balanza_xml(req)
        # First account should have deudor, second acreedor
        assert "1500.00" in xml


# ── Validator Tests: Balanza ──

class TestBalanzaValidators:
    def _valid_balanza(self):
        return BalanzaRequest(
            periodo="2025-01", ejercicio=2025, mes=1,
            rows=[BalanzaRow(codigo_cuenta="1001", saldo_inicial=0, debe=1000, haber=1000, saldo_final=0)]
        )

    def test_validate_valid(self):
        errors = validate_balanza(self._valid_balanza())
        assert errors == []

    def test_validate_none(self):
        errors = validate_balanza(None)
        assert len(errors) == 1

    def test_validate_empty_rows(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[])
        errors = validate_balanza(req)
        assert any("filas" in e.lower() for e in errors)

    def test_validate_negative_debe(self):
        """Test that Pydantic rejects negative debe at model level."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BalanzaRow(codigo_cuenta="1001", debe=-100)

    def test_totals_cuadran(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[
            BalanzaRow(codigo_cuenta="1001", debe=1000, haber=1000),
        ])
        errors = validate_balanza_totals(req)
        assert errors == []

    def test_totals_no_cuadran(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[
            BalanzaRow(codigo_cuenta="1001", debe=1000, haber=500),
        ])
        errors = validate_balanza_totals(req)
        assert len(errors) > 0

    def test_saldo_consistency(self):
        req = BalanzaRequest(periodo="2025-01", ejercicio=2025, mes=1, rows=[
            BalanzaRow(codigo_cuenta="1001", saldo_inicial=100, debe=50, haber=50, saldo_final=100),
        ])
        errors = validate_balanza(req)
        assert errors == []


# ── Validator Tests: Catálogo ──

class TestCatalogoValidators:
    def test_validate_valid(self):
        cuentas = [CatalogoCuenta(codigo="1001", descripcion="Caja", tipo=TipoCuenta.ACTIVO)]
        errors = validate_catalogo(cuentas)
        assert errors == []

    def test_validate_empty(self):
        errors = validate_catalogo([])
        assert len(errors) > 0

    def test_validate_none(self):
        errors = validate_catalogo(None)
        assert len(errors) == 1

    def test_invalid_level(self):
        """Test that Pydantic rejects nivel > 5 at model level."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CatalogoCuenta(codigo="1001", descripcion="Caja", tipo=TipoCuenta.ACTIVO, nivel=99)

    def test_no_padre_for_level2(self):
        cuentas = [CatalogoCuenta(codigo="1001.01", descripcion="Sub", tipo=TipoCuenta.ACTIVO, nivel=2)]
        errors = validate_catalogo(cuentas)
        assert any("padre" in e.lower() for e in errors)


# ── Route Tests ──

class TestRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.contabilidad_electronica.routes import build_contabilidad_electronica_router
        from fastapi import FastAPI
        app = FastAPI()
        router = build_contabilidad_electronica_router()
        app.include_router(router)
        return TestClient(app)

    def test_generate_balanza(self, client):
        resp = client.post("/contabilidad-electronica/balanza", json={
            "periodo": "2025-01", "ejercicio": 2025, "mes": 1,
            "rfc": "ABC850101T1A",
            "rows": [{"codigo_cuenta": "1001", "saldo_inicial": 0, "debe": 1000, "haber": 1000, "saldo_final": 0}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "generado"
        assert "xml_content" in data

    def test_generate_balanza_validation_error(self, client):
        resp = client.post("/contabilidad-electronica/balanza", json={
            "periodo": "2025-01", "ejercicio": 2025, "mes": 1, "rows": []
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "error"

    def test_get_obligaciones(self, client):
        resp = client.get("/contabilidad-electronica/obligaciones/EABC123456789")
        assert resp.status_code == 200
        data = resp.json()
        assert "mensuales" in data
        assert "anuales" in data

    def test_obligaciones_empty_rfc(self, client):
        resp = client.get("/contabilidad-electronica/obligaciones/   ")
        assert resp.status_code == 400

    def test_validate_endpoint(self, client):
        resp = client.post("/contabilidad-electronica/validate", json={
            "balanza": {
                "periodo": "2025-01", "ejercicio": 2025, "mes": 1,
                "rows": [{"codigo_cuenta": "1001", "saldo_inicial": 0, "debe": 1000, "haber": 1000, "saldo_final": 0}]
            }
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
