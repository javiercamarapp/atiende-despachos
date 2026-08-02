# -*- coding: utf-8 -*-
"""Tests for the Nómina 1.2 CFDI parser and validators."""
from __future__ import annotations
import io
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from b2b_ai.features.nomina.parser import NominaData, parse_nomina_bytes
from b2b_ai.features.nomina.validators import (
    validate_nomina, validate_rfc_patron, validate_fechas,
    validate_num_dias_pagados, validate_periodicidad_pago, validate_tipo_nomina,
    PERIODICIDAD_PAGO_CODES, TIPO_NOMINA_CODES,
)


# Helper: build minimal CFDI with Nomina complement

def _nomina_xml(tipo="O", fecha_pago="2025-01-15", fecha_ini="2025-01-01",
                fecha_fin="2025-01-15", num_dias="15", rfc_patron=None,
                cfdi_rfc="EABC123456789", periodicidad="03"):
    patron = rfc_patron or cfdi_rfc
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4">',
        f'  <cfdi:Emisor Rfc="{cfdi_rfc}" Nombre="Test"/>',
        '  <cfdi:Complemento>',
        f'    <nomina:Nomina xmlns:nomina="http://www.sat.gob.mx/nomina12"',
        f'      Version="1.2" TipoNomina="{tipo}" FechaPago="{fecha_pago}"',
        f'      FechaInicialPago="{fecha_ini}" FechaFinalPago="{fecha_fin}"',
        f'      NumDiasPagados="{num_dias}" TotalPercepciones="10000"',
        '      TotalDeducciones="3000">',
        f'      <nomina:Emisor RegistroPatronal="A1B2C3D4" RfcPatronOrigen="{patron}"/>',
        '      <nomina:Receptor Curp="CURP123456789" NumEmpleado="001"',
        f'        PeriodicidadPago="{periodicidad}" TipoJornada="01"',
        '        RiesgoPuesto="1" SalarioDiarioIntegrado="500"/>',
        '    </nomina:Nomina>',
        '  </cfdi:Complemento>',
        '</cfdi:Comprobante>',
    ]
    return "\n".join(lines).encode()


# ── Parser Tests ──

class TestNominaParser:
    def test_parse_valid(self):
        data = parse_nomina_bytes(_nomina_xml())
        assert data is not None
        assert data.tipo_nomina == "O"
        assert data.version == "1.2"
        assert data.fecha_pago == "2025-01-15"
        assert data.total_percepciones == Decimal("10000")

    def test_parse_extraordinaria(self):
        data = parse_nomina_bytes(_nomina_xml(tipo="E"))
        assert data.tipo_nomina == "E"

    def test_parse_no_nomina(self):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"></cfdi:Comprobante>'
        data = parse_nomina_bytes(xml)
        assert data is None

    def test_parse_invalid_xml(self):
        with pytest.raises(Exception):
            parse_nomina_bytes(b"not xml")

    def test_parse_receptor_fields(self):
        data = parse_nomina_bytes(_nomina_xml())
        assert data.curp == "CURP123456789"
        assert data.num_empleado == "001"
        assert data.periodicidad_pago == "03"

    def test_to_dict(self):
        data = parse_nomina_bytes(_nomina_xml())
        d = data.to_dict()
        assert d["tipo_nomina"] == "O"
        assert d["total_percepciones"] == "10000"
        assert d["curp"] == "CURP123456789"


# ── Validator Tests ──

class TestNominaValidators:
    def test_validate_valid(self):
        data = parse_nomina_bytes(_nomina_xml())
        errors = validate_nomina(data)
        assert errors == []

    def test_validate_none(self):
        errors = validate_nomina(None)
        assert len(errors) == 1

    def test_rfc_patron_no_match(self):
        data = parse_nomina_bytes(_nomina_xml(rfc_patron="XXX999999999"))
        errors = validate_rfc_patron(data)
        assert len(errors) > 0

    def test_rfc_patron_match(self):
        data = parse_nomina_bytes(_nomina_xml())
        errors = validate_rfc_patron(data)
        assert errors == []

    def test_fechas_valid(self):
        data = parse_nomina_bytes(_nomina_xml())
        errors = validate_fechas(data)
        assert errors == []

    def test_fecha_pago_out_of_range(self):
        data = parse_nomina_bytes(_nomina_xml(fecha_pago="2025-02-01"))
        errors = validate_fechas(data)
        assert len(errors) > 0

    def test_num_dias_valid(self):
        data = parse_nomina_bytes(_nomina_xml(num_dias="15"))
        errors = validate_num_dias_pagados(data)
        assert errors == []

    def test_num_dias_exceeds_period(self):
        data = parse_nomina_bytes(_nomina_xml(num_dias="30"))
        errors = validate_num_dias_pagados(data)
        assert len(errors) > 0

    def test_periodicidad_valid(self):
        data = parse_nomina_bytes(_nomina_xml(periodicidad="03"))
        errors = validate_periodicidad_pago(data)
        assert errors == []

    def test_periodicidad_invalid(self):
        data = parse_nomina_bytes(_nomina_xml(periodicidad="99"))
        errors = validate_periodicidad_pago(data)
        assert len(errors) > 0

    def test_tipo_nomina_valid(self):
        data = parse_nomina_bytes(_nomina_xml(tipo="O"))
        errors = validate_tipo_nomina(data)
        assert errors == []

    def test_tipo_nomina_invalid(self):
        data = parse_nomina_bytes(_nomina_xml(tipo="X"))
        errors = validate_tipo_nomina(data)
        assert len(errors) > 0


# ── Route Tests ──

class TestNominaRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.nomina.routes import build_nomina_router
        from fastapi import FastAPI
        app = FastAPI()
        router = build_nomina_router()
        app.include_router(router)
        return TestClient(app)

    def test_parse_nomina(self, client):
        xml = _nomina_xml()
        resp = client.post("/nomina/parse",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["nomina"]["tipo_nomina"] == "O"

    def test_parse_empty(self, client):
        resp = client.post("/nomina/parse",
                           files={"file": ("test.xml", io.BytesIO(b""), "application/xml")})
        assert resp.status_code == 400

    def test_parse_no_nomina(self, client):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"></cfdi:Comprobante>'
        resp = client.post("/nomina/parse",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 404

    def test_validate_nomina_route(self, client):
        xml = _nomina_xml()
        resp = client.post("/nomina/validate",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_catalog(self, client):
        resp = client.get("/nomina/catalog")
        assert resp.status_code == 200
        assert "periodicidad_pago" in resp.json()
        assert "01" in resp.json()["periodicidad_pago"]
