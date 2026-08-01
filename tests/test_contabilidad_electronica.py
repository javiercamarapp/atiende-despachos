# -*- coding: utf-8 -*-
"""
test_contabilidad_electronica.py — Tests del módulo de Contabilidad Electrónica SAT.

Cobertura:
  Models: CuentaContable, BalanzaRow, BalanzaRequest, CatalogoCuenta,
          ContabilidadElectronicaResponse.
  Generator: generate_balanza_xml, generate_catalogo_xml (tags, namespaces,
             formato, cantidades, edge cases).
  Validators: validate_balanza, validate_catalogo, validate_balanza_totals.
  Routes: POST /balanza, POST /catalogo, POST /validate,
          GET /obligaciones/{rfc}.
  Edge cases: empty rows, negative balances, max depth accounts, XML
              structure, serialización.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.contabilidad_electronica.models import (
    CuentaContable,
    BalanzaRow,
    BalanzaRequest,
    CatalogoCuenta,
    ContabilidadElectronicaResponse,
    TipoCuenta,
)
from b2b_ai.features.contabilidad_electronica.generator import (
    generate_balanza_xml,
    generate_catalogo_xml,
)
from b2b_ai.features.contabilidad_electronica.validators import (
    validate_balanza,
    validate_catalogo,
    validate_balanza_totals,
)
from b2b_ai.features.contabilidad_electronica.routes import (
    build_contabilidad_electronica_router,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def sample_balanza_rows():
    """Filas de balanza de ejemplo (balanced)."""
    return [
        BalanzaRow(
            codigo_cuenta="101.01.01",
            saldo_inicial=1000.00,
            debe=500.00,
            haber=200.00,
            saldo_final=1300.00,
        ),
        BalanzaRow(
            codigo_cuenta="201.01.01",
            saldo_inicial=500.00,
            debe=200.00,
            haber=500.00,
            saldo_final=200.00,
        ),
    ]


@pytest.fixture
def sample_balanza_request(sample_balanza_rows):
    """Request de balanza completo."""
    return BalanzaRequest(
        periodo="2025-01",
        ejercicio=2025,
        mes=1,
        rows=sample_balanza_rows,
    )


@pytest.fixture
def sample_catalogo_cuentas():
    """Cuentas de catálogo de ejemplo."""
    return [
        CatalogoCuenta(
            codigo="101.01.01",
            descripcion="Caja",
            tipo=TipoCuenta.ACTIVO,
            nivel=3,
            padre="101.01",
            status="A",
        ),
        CatalogoCuenta(
            codigo="201.01.01",
            descripcion="Proveedores",
            tipo=TipoCuenta.PASIVO,
            nivel=3,
            padre="201.01",
            status="A",
        ),
        CatalogoCuenta(
            codigo="401.01",
            descripcion="Ventas",
            tipo=TipoCuenta.INGRESO,
            nivel=2,
            padre="401",
            status="A",
        ),
    ]


@pytest.fixture
def client():
    """TestClient de FastAPI con el router de contabilidad electrónica."""
    app = FastAPI()
    app.include_router(build_contabilidad_electronica_router())
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Tests: Models
# --------------------------------------------------------------------------- #

class TestModels:
    """Tests de los esquemas Pydantic."""

    def test_cuenta_contable_creation(self):
        """CuentaContable se crea correctamente."""
        cta = CuentaContable(
            codigo="101.01.01",
            descripcion="Caja",
            tipo=TipoCuenta.ACTIVO,
            nivel=3,
        )
        assert cta.codigo == "101.01.01"
        assert cta.tipo == TipoCuenta.ACTIVO
        assert cta.nivel == 3
        assert cta.padre is None
        assert cta.saldo == 0.0

    def test_cuenta_contable_defaults(self):
        """CuentaContable usa valores por defecto correctamente."""
        cta = CuentaContable(
            codigo="101.01.01",
            descripcion="Caja",
            tipo=TipoCuenta.GASTO,
        )
        assert cta.nivel == 1
        assert cta.padre is None
        assert cta.saldo == 0.0

    def test_balanza_row_creation(self):
        """BalanzaRow se crea correctamente."""
        row = BalanzaRow(
            codigo_cuenta="101.01.01",
            saldo_inicial=100.00,
            debe=50.00,
            haber=30.00,
            saldo_final=120.00,
        )
        assert row.codigo_cuenta == "101.01.01"
        assert row.debe == 50.00
        assert row.haber == 30.00
        assert row.saldo_final == 120.00

    def test_balanza_row_negative_debe_rejected(self):
        """BalanzaRow rechaza debe negativo."""
        with pytest.raises(Exception):
            BalanzaRow(
                codigo_cuenta="101.01.01",
                debe=-10.00,
            )

    def test_balanza_request_creation(self):
        """BalanzaRequest se crea correctamente."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[],
        )
        assert req.periodo == "2025-01"
        assert req.ejercicio == 2025
        assert req.mes == 1
        assert req.rows == []

    def test_balanza_request_invalid_periodo(self):
        """BalanzaRequest rechaza periodo inválido."""
        with pytest.raises(Exception):
            BalanzaRequest(
                periodo="2025/01",
                ejercicio=2025,
                mes=1,
            )

    def test_balanza_request_invalid_mes(self):
        """BalanzaRequest rechaza mes fuera de rango."""
        with pytest.raises(Exception):
            BalanzaRequest(
                periodo="2025-01",
                ejercicio=2025,
                mes=13,
            )

    def test_catalogo_cuenta_creation(self):
        """CatalogoCuenta se crea correctamente."""
        cta = CatalogoCuenta(
            codigo="101.01",
            descripcion="Caja",
            tipo=TipoCuenta.ACTIVO,
            nivel=2,
        )
        assert cta.codigo == "101.01"
        assert cta.nivel == 2
        assert cta.status == "A"

    def test_catalogo_cuenta_inactive(self):
        """CatalogoCuenta acepta status Inactivo."""
        cta = CatalogoCuenta(
            codigo="101.01",
            descripcion="Caja",
            tipo=TipoCuenta.ACTIVO,
            nivel=2,
            status="I",
        )
        assert cta.status == "I"

    def test_catalogo_cuenta_invalid_status(self):
        """CatalogoCuenta rechaza status inválido."""
        with pytest.raises(Exception):
            CatalogoCuenta(
                codigo="101.01",
                descripcion="Caja",
                tipo=TipoCuenta.ACTIVO,
                nivel=2,
                status="X",
            )

    def test_contabilidad_electronica_response_defaults(self):
        """ContabilidadElectronicaResponse tiene defaults correctos."""
        resp = ContabilidadElectronicaResponse()
        assert resp.uuid  # auto-generado
        assert resp.fecha_generacion
        assert resp.estado == "generado"
        assert resp.errores == []

    def test_contabilidad_electronica_response_with_errors(self):
        """ContabilidadElectronicaResponse con errores."""
        resp = ContabilidadElectronicaResponse(
            estado="error",
            errores=["Error 1", "Error 2"],
        )
        assert resp.estado == "error"
        assert len(resp.errores) == 2


# --------------------------------------------------------------------------- #
# Tests: Generator - Balanza XML
# --------------------------------------------------------------------------- #

class TestGeneratorBalanza:
    """Tests de generación de XML de Balanza de Comprobación."""

    def test_balanza_xml_basic_structure(self, sample_balanza_request):
        """XML tiene la estructura básica SAT."""
        xml = generate_balanza_xml(sample_balanza_request)
        assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
        assert "ContabilidadEducativa" in xml
        assert "Balanza" in xml
        assert "Cuenta" in xml

    def test_balanza_xml_namespace(self, sample_balanza_request):
        """XML contiene el namespace del SAT."""
        xml = generate_balanza_xml(sample_balanza_request)
        assert "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3" in xml

    def test_balanza_xml_version(self, sample_balanza_request):
        """XML contiene la versión 1.3."""
        xml = generate_balanza_xml(sample_balanza_request)
        assert 'Version="1.3"' in xml

    def test_balanza_xml_ejercicio_mes(self, sample_balanza_request):
        """XML contiene ejercicio y mes correctos."""
        xml = generate_balanza_xml(sample_balanza_request)
        assert 'Ejercicio="2025"' in xml
        assert 'Mes="01"' in xml

    def test_balanza_xml_cuentas_count(self, sample_balanza_request):
        """XML contiene el número correcto de cuentas."""
        xml = generate_balanza_xml(sample_balanza_request)
        # Cada fila genera un nodo Cuenta
        assert xml.count("<ce:Cuenta") == 2

    def test_balanza_xml_account_codes(self, sample_balanza_request):
        """XML contiene los códigos de cuenta correctos."""
        xml = generate_balanza_xml(sample_balanza_request)
        assert 'NumCta="101.01.01"' in xml
        assert 'NumCta="201.01.01"' in xml

    def test_balanza_xml_amounts(self, sample_balanza_request):
        """XML contiene montos formateados con 2 decimales."""
        xml = generate_balanza_xml(sample_balanza_request)
        assert 'Debe="500.00"' in xml
        assert 'Haber="200.00"' in xml
        assert 'SaldoIni="1000.00"' in xml

    def test_balanza_xml_empty_rows(self):
        """XML de balanza vacía genera estructura válida."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[],
        )
        xml = generate_balanza_xml(req)
        assert "Balanza" in xml
        assert "Cuenta" not in xml  # Sin cuentas

    def test_balanza_xml_single_account(self):
        """XML con una sola cuenta."""
        req = BalanzaRequest(
            periodo="2025-06",
            ejercicio=2025,
            mes=6,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=0.0,
                    debe=100.00,
                    haber=0.00,
                    saldo_final=100.00,
                ),
            ],
        )
        xml = generate_balanza_xml(req)
        assert 'NumCta="101"' in xml
        assert 'Mes="06"' in xml

    def test_balanza_xml_saldo_deudor_acreedor(self):
        """XML calcula correctamente saldo deudor/acreedor."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=0.0,
                    debe=100.00,
                    haber=0.00,
                    saldo_final=100.00,  # Deudor
                ),
                BalanzaRow(
                    codigo_cuenta="201",
                    saldo_inicial=0.0,
                    debe=0.00,
                    haber=200.00,
                    saldo_final=-200.00,  # Acreedor
                ),
            ],
        )
        xml = generate_balanza_xml(req)
        # Primera cuenta: deudor
        assert 'SaldoDeudor="100.00"' in xml
        assert 'SaldoAcreedor="0.00"' in xml

    def test_balanza_xml_many_accounts(self):
        """XML maneja múltiples cuentas (10+)."""
        rows = [
            BalanzaRow(
                codigo_cuenta=f"10{i:02d}",
                saldo_inicial=0.0,
                debe=float(i * 100),
                haber=float(i * 50),
                saldo_final=float(i * 50),
            )
            for i in range(1, 11)
        ]
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=rows,
        )
        xml = generate_balanza_xml(req)
        assert xml.count("<ce:Cuenta") == 10


# --------------------------------------------------------------------------- #
# Tests: Generator - Catálogo XML
# --------------------------------------------------------------------------- #

class TestGeneratorCatalogo:
    """Tests de generación de XML de Catálogo de Cuentas."""

    def test_catalogo_xml_basic_structure(self, sample_catalogo_cuentas):
        """XML tiene la estructura básica SAT."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
        assert "ContabilidadEducativa" in xml
        assert "Catalogo" in xml
        assert "Cuenta" in xml

    def test_catalogo_xml_namespace(self, sample_catalogo_cuentas):
        """XML contiene el namespace del SAT."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        assert "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3" in xml

    def test_catalogo_xml_version(self, sample_catalogo_cuentas):
        """XML contiene la versión 1.3."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        assert 'Version="1.3"' in xml

    def test_catalogo_xml_ejercicio(self, sample_catalogo_cuentas):
        """XML contiene el ejercicio correcto."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        assert 'Ejercicio="2025"' in xml

    def test_catalogo_xml_accounts_count(self, sample_catalogo_cuentas):
        """XML contiene el número correcto de cuentas."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        assert xml.count("<ce:Cuenta") == 3

    def test_catalogo_xml_account_attributes(self, sample_catalogo_cuentas):
        """XML contiene los atributos de cuenta correctos."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        assert 'CodAgrup="101.01.01"' in xml
        assert 'Desc="Caja"' in xml
        assert 'Nivel="3"' in xml
        assert 'TipoCta="Activo"' in xml

    def test_catalogo_xml_naturaleza_mapping(self, sample_catalogo_cuentas):
        """XML mapea correctamente tipo de cuenta a naturaleza SAT."""
        xml = generate_catalogo_xml(sample_catalogo_cuentas, ejercicio=2025)
        # Activo → Deudor (D)
        assert xml.count('Naturaleza="D"') >= 1
        # Pasivo → Acreedor (A)
        assert xml.count('Naturaleza="A"') >= 1

    def test_catalogo_xml_empty_list(self):
        """XML de catálogo vacío genera estructura válida."""
        xml = generate_catalogo_xml([], ejercicio=2025)
        assert "Catalogo" in xml
        assert "Cuenta" not in xml

    def test_catalogo_xml_inactive_account(self):
        """XML maneja cuentas inactivas."""
        cuentas = [
            CatalogoCuenta(
                codigo="101.01",
                descripcion="Caja inactiva",
                tipo=TipoCuenta.ACTIVO,
                nivel=2,
                status="I",
            ),
        ]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert 'Estado="I"' in xml

    def test_catalogo_xml_many_accounts(self):
        """XML maneja múltiples cuentas (20+)."""
        cuentas = [
            CatalogoCuenta(
                codigo=f"10{i:02d}",
                descripcion=f"Cuenta {i}",
                tipo=TipoCuenta.ACTIVO,
                nivel=2,
            )
            for i in range(1, 21)
        ]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert xml.count("<ce:Cuenta") == 20


# --------------------------------------------------------------------------- #
# Tests: Validators
# --------------------------------------------------------------------------- #

class TestValidators:
    """Tests de validadores de contabilidad electrónica."""

    def test_validate_balanza_valid(self, sample_balanza_request):
        """Balanza válida retorna errores vacíos."""
        errors = validate_balanza(sample_balanza_request)
        assert errors == []

    def test_validate_balanza_totals_balance(self, sample_balanza_request):
        """Totales cuadran (debe == haber)."""
        errors = validate_balanza_totals(sample_balanza_request)
        assert errors == []

    def test_validate_balanza_totals_unbalanced(self):
        """Totales NO cuadran."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=0.0,
                    debe=100.00,
                    haber=50.00,
                    saldo_final=50.00,
                ),
                BalanzaRow(
                    codigo_cuenta="201",
                    saldo_inicial=0.0,
                    debe=0.00,
                    haber=200.00,  # Suma haber = 250, no cuadra con debe = 100
                    saldo_final=-200.00,
                ),
            ],
        )
        errors = validate_balanza_totals(req)
        assert len(errors) > 0
        assert "Totales no cuadran" in errors[0]

    def test_validate_balanza_negative_debe(self):
        """Debe negativo es rechazado por Pydantic (modelo estricto)."""
        with pytest.raises(Exception):
            BalanzaRow(
                codigo_cuenta="101",
                saldo_inicial=0.0,
                debe=-10.00,
                haber=0.00,
                saldo_final=-10.00,
            )

    def test_validate_balanza_negative_haber(self):
        """Haber negativo es rechazado por Pydantic (modelo estricto)."""
        with pytest.raises(Exception):
            BalanzaRow(
                codigo_cuenta="101",
                saldo_inicial=0.0,
                debe=0.00,
                haber=-5.00,
                saldo_final=5.00,
            )

    def test_validate_balanza_empty_rows(self):
        """Balanza sin filas genera error."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[],
        )
        errors = validate_balanza(req)
        assert len(errors) > 0
        assert "no tiene filas" in errors[0]

    def test_validate_balanza_none(self):
        """Balanza None genera error."""
        errors = validate_balanza(None)
        assert len(errors) > 0

    def test_validate_balanza_invalid_code(self):
        """Código de cuenta inválido genera error."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="ABC",
                    saldo_inicial=0.0,
                    debe=100.00,
                    haber=100.00,
                    saldo_final=0.00,
                ),
            ],
        )
        errors = validate_balanza(req)
        assert any("inválido" in e for e in errors)

    def test_validate_balanza_empty_code(self):
        """Código vacío es rechazado por Pydantic (modelo estricto)."""
        with pytest.raises(Exception):
            BalanzaRow(
                codigo_cuenta="",
                saldo_inicial=0.0,
                debe=100.00,
                haber=100.00,
                saldo_final=0.00,
            )

    def test_validate_balanza_inconsistent_saldo(self):
        """Saldo final inconsistente genera error."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=100.00,
                    debe=50.00,
                    haber=30.00,
                    saldo_final=999.00,  # Debería ser 120.00
                ),
            ],
        )
        errors = validate_balanza(req)
        assert any("SaldoFinal" in e for e in errors)

    def test_validate_balanza_invalid_month(self):
        """Mes inválido es rechazado por Pydantic (modelo estricto)."""
        with pytest.raises(Exception):
            BalanzaRequest(
                periodo="2025-01",
                ejercicio=2025,
                mes=13,
                rows=[],
            )

    def test_validate_catalogo_valid(self, sample_catalogo_cuentas):
        """Catálogo válido retorna errores vacíos."""
        errors = validate_catalogo(sample_catalogo_cuentas)
        assert errors == []

    def test_validate_catalogo_empty(self):
        """Catálogo vacío genera error."""
        errors = validate_catalogo([])
        assert len(errors) > 0
        assert "vacío" in errors[0]

    def test_validate_catalogo_none(self):
        """Catálogo None genera error."""
        errors = validate_catalogo(None)
        assert len(errors) > 0

    def test_validate_catalogo_invalid_level(self):
        """Nivel fuera de rango es rechazado por Pydantic (modelo estricto)."""
        with pytest.raises(Exception):
            CatalogoCuenta(
                codigo="101.01",
                descripcion="Caja",
                tipo=TipoCuenta.ACTIVO,
                nivel=99,
            )

    def test_validate_catalogo_invalid_code(self):
        """Código de cuenta inválido genera error."""
        cuentas = [
            CatalogoCuenta(
                codigo="ABC!@#",
                descripcion="Caja",
                tipo=TipoCuenta.ACTIVO,
                nivel=1,
            ),
        ]
        errors = validate_catalogo(cuentas)
        assert any("inválido" in e for e in errors)

    def test_validate_catalogo_missing_parent(self):
        """Cuenta de nivel > 1 sin padre genera error."""
        cuentas = [
            CatalogoCuenta(
                codigo="101.01",
                descripcion="Caja",
                tipo=TipoCuenta.ACTIVO,
                nivel=3,
                padre=None,
            ),
        ]
        errors = validate_catalogo(cuentas)
        assert any("padre" in e.lower() for e in errors)


# --------------------------------------------------------------------------- #
# Tests: Routes
# --------------------------------------------------------------------------- #

class TestRoutes:
    """Tests de los endpoints FastAPI."""

    def test_balanza_endpoint_ok(self, client, sample_balanza_request):
        """POST /balanza genera XML correctamente."""
        resp = client.post(
            "/contabilidad-electronica/balanza",
            json=sample_balanza_request.model_dump(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "generado"
        assert "xml_content" in data
        assert "ContabilidadEducativa" in data["xml_content"]

    def test_balanza_endpoint_validation_error(self, client):
        """POST /balanza con datos inválidos retorna errores."""
        resp = client.post(
            "/contabilidad-electronica/balanza",
            json={
                "periodo": "2025-01",
                "ejercicio": 2025,
                "mes": 1,
                "rows": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "error"
        assert len(data["errores"]) > 0

    def test_balanza_endpoint_unbalanced(self, client):
        """POST /balanza con totales desbalanceados retorna error."""
        resp = client.post(
            "/contabilidad-electronica/balanza",
            json={
                "periodo": "2025-01",
                "ejercicio": 2025,
                "mes": 1,
                "rows": [
                    {
                        "codigo_cuenta": "101",
                        "saldo_inicial": 0.0,
                        "debe": 100.0,
                        "haber": 50.0,
                        "saldo_final": 50.0,
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Totales no cuadran: debe=100, haber=50
        assert data["estado"] == "error"

    def test_catalogo_endpoint_ok(self, client, sample_catalogo_cuentas):
        """POST /catalogo genera XML correctamente."""
        resp = client.post(
            "/contabilidad-electronica/catalogo",
            json=[cta.model_dump() for cta in sample_catalogo_cuentas],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "generado"
        assert "xml_content" in data
        assert "Catalogo" in data["xml_content"]

    def test_catalogo_endpoint_validation_error(self, client):
        """POST /catalogo con datos inválidos retorna errores."""
        resp = client.post(
            "/contabilidad-electronica/catalogo",
            json=[],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "error"
        assert len(data["errores"]) > 0

    def test_validate_endpoint_balanza(self, client, sample_balanza_request):
        """POST /validate valida balanza correctamente."""
        resp = client.post(
            "/contabilidad-electronica/validate",
            json={
                "balanza": sample_balanza_request.model_dump(),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_validate_endpoint_catalogo(
        self, client, sample_catalogo_cuentas
    ):
        """POST /validate valida catálogo correctamente."""
        resp = client.post(
            "/contabilidad-electronica/validate",
            json={
                "catalogo": [cta.model_dump() for cta in sample_catalogo_cuentas],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_validate_endpoint_both(self, client, sample_balanza_request,
                                     sample_catalogo_cuentas):
        """POST /validate valida balanza + catálogo."""
        resp = client.post(
            "/contabilidad-electronica/validate",
            json={
                "balanza": sample_balanza_request.model_dump(),
                "catalogo": [cta.model_dump() for cta in sample_catalogo_cuentas],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["balanza"]["ok"] is True
        assert data["catalogo"]["ok"] is True

    def test_validate_endpoint_nothing(self, client):
        """POST /validate sin datos retorna error."""
        resp = client.post(
            "/contabilidad-electronica/validate",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_obligaciones_endpoint(self, client):
        """GET /obligaciones/{rfc} retorna obligaciones."""
        resp = client.get("/contabilidad-electronica/obligaciones/EMP820101AB1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rfc"] == "EMP820101AB1"
        assert "mensuales" in data
        assert "anuales" in data
        assert isinstance(data["mensuales"], list)

    def test_obligaciones_endpoint_empty_rfc(self, client):
        """GET /obligaciones/ con RFC vacío retorna 400."""
        resp = client.get("/contabilidad-electronica/obligaciones/%20")
        assert resp.status_code == 400

    def test_obligaciones_endpoint_has_contabilidad_flag(self, client):
        """Obligaciones indica si se requiere contabilidad electrónica."""
        resp = client.get("/contabilidad-electronica/obligaciones/EMP820101AB1")
        data = resp.json()
        assert "contabilidad_electronica" in data
        assert isinstance(data["contabilidad_electronica"], bool)


# --------------------------------------------------------------------------- #
# Tests: Edge Cases
# --------------------------------------------------------------------------- #

class TestEdgeCases:
    """Tests de casos extremos."""

    def test_balanza_xml_zero_amounts(self):
        """XML con montos cero."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=0.0,
                    debe=0.0,
                    haber=0.0,
                    saldo_final=0.0,
                ),
            ],
        )
        xml = generate_balanza_xml(req)
        assert 'Debe="0.00"' in xml
        assert 'Haber="0.00"' in xml

    def test_balanza_xml_large_amounts(self):
        """XML con montos grandes."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=999999999.99,
                    debe=123456789.01,
                    haber=98765432.10,
                    saldo_final=1024699956.90,
                ),
            ],
        )
        xml = generate_balanza_xml(req)
        assert '123456789.01' in xml

    def test_balanza_xml_negative_saldo_final(self):
        """XML con saldo final negativo (acreedor)."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="201",
                    saldo_inicial=100.0,
                    debe=0.0,
                    haber=300.0,
                    saldo_final=-200.0,
                ),
            ],
        )
        xml = generate_balanza_xml(req)
        assert 'SaldoAcreedor="200.00"' in xml

    def test_catalogo_xml_max_level(self):
        """Catálogo con nivel máximo (5)."""
        cuentas = [
            CatalogoCuenta(
                codigo="1.2.3.4.5",
                descripcion="Cuenta nivel 5",
                tipo=TipoCuenta.ACTIVO,
                nivel=5,
                padre="1.2.3.4",
            ),
        ]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert 'Nivel="5"' in xml

    def test_catalogo_xml_min_level(self):
        """Catálogo con nivel mínimo (1)."""
        cuentas = [
            CatalogoCuenta(
                codigo="1",
                descripcion="Cuenta nivel 1",
                tipo=TipoCuenta.ACTIVO,
                nivel=1,
            ),
        ]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert 'Nivel="1"' in xml

    def test_validate_balanza_many_errors(self):
        """Validación retorna múltiples errores con datos válidos pero incorrectos."""
        # Usar model_construct() para bypass de validación Pydantic
        row1 = BalanzaRow.model_construct(
            codigo_cuenta="",
            saldo_inicial=0.0,
            debe=-1.0,
            haber=-1.0,
            saldo_final=0.0,
        )
        row2 = BalanzaRow.model_construct(
            codigo_cuenta="ABC",
            saldo_inicial=0.0,
            debe=-1.0,
            haber=-1.0,
            saldo_final=0.0,
        )
        req = BalanzaRequest.model_construct(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[row1, row2],
        )
        errors = validate_balanza(req)
        # Debe haber múltiples errores (código vacío, código inválido, debe negativo, etc.)
        assert len(errors) >= 3

    def test_validate_catalogo_many_errors(self):
        """Validación de catálogo retorna múltiples errores."""
        cta = CatalogoCuenta.model_construct(
            codigo="",
            descripcion="Sin código",
            tipo=TipoCuenta.ACTIVO,
            nivel=99,
            subtipo_cuenta=None,
            padre=None,
            status="A",
        )
        errors = validate_catalogo([cta])
        # Código vacío + nivel inválido
        assert len(errors) >= 2

    def test_contabilidad_electronica_response_serializable(self):
        """ContabilidadElectronicaResponse es serializable a JSON."""
        resp = ContabilidadElectronicaResponse(
            estado="generado",
            xml_content="<xml/>",
        )
        d = resp.model_dump()
        assert isinstance(d, dict)
        assert d["estado"] == "generado"
        assert d["xml_content"] == "<xml/>"

    def test_balanza_totals_float_precision(self):
        """Validación maneja precisión de floats correctamente."""
        req = BalanzaRequest(
            periodo="2025-01",
            ejercicio=2025,
            mes=1,
            rows=[
                BalanzaRow(
                    codigo_cuenta="101",
                    saldo_inicial=0.0,
                    debe=0.10,
                    haber=0.10,
                    saldo_final=0.0,
                ),
            ],
        )
        errors = validate_balanza_totals(req)
        assert errors == []  # 0.10 == 0.10
