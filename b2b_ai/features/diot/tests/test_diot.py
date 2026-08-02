# -*- coding: utf-8 -*-
"""
test_diot.py — Tests del módulo DIOT.
Cubre generación, validación, resumen IVA y exportación TXT/XML + API.
"""
from __future__ import annotations

import tempfile
import pytest
from fastapi import APIRouter

from b2b_ai.features.diot.models import (
    DIOTDeclaration, DIOTPeriod, DIOTRecord, DIOTStatus, DIOTSummary,
    TipoOperacion, TipoIVA,
)
from b2b_ai.features.diot.service import DIOTService
from b2b_ai.features.diot.validators import (
    validate_iva_rate, validate_positive_amount, validate_rfc, validate_records,
)
from b2b_ai.features.diot.routes import build_diot_router


def _period() -> DIOTPeriod:
    return DIOTPeriod(year=2024, quarter=3)


def _record(rfc="EMP850101AB1", nombre="Empresa Proveedora SA de CV",
            tipo=TipoOperacion.A, base=1000.0, iva_t=160.0, iva_a=160.0,
            tasa_iva=TipoIVA.IVA_16) -> DIOTRecord:
    return DIOTRecord(rfc_tercero=rfc, nombre=nombre, regimen_fiscal="601",
                      tipo_operacion=tipo, base_gravable=base,
                      iva_trasladado=iva_t, iva_acreditable=iva_a, tasa_iva=tasa_iva)


def _records() -> list:
    return [
        _record(),
        _record(rfc="SER850101AB1", nombre="Servicios SRL", tipo=TipoOperacion.S,
                base=500.0, iva_t=80.0, iva_a=80.0),
        _record(rfc="IMP850101AB1", nombre="Importadora MX", tipo=TipoOperacion.I,
                base=2000.0, iva_t=0.0, iva_a=320.0, tasa_iva=TipoIVA.IVA_00),
    ]


class TestModels:
    def test_period_label(self):
        p = DIOTPeriod(year=2024, quarter=3)
        assert p.label == "2024-Q3"
        assert p.months == [7, 8, 9]

    def test_period_from_string(self):
        p = DIOTPeriod.from_string("2024-Q3")
        assert p.year == 2024 and p.quarter == 3

    def test_record_negative_iva_rejected(self):
        with pytest.raises(ValueError):
            DIOTRecord(rfc_tercero="EMP850101AB1", nombre="X",
                       tipo_operacion=TipoOperacion.A, base_gravable=100,
                       iva_trasladado=-5)

    def test_declaration_recompute_summary(self):
        d = DIOTDeclaration(client_rfc="CONT601208DZ1", period=_period(), records=_records())
        s = d.recompute_summary()
        assert s.total_operaciones == 3
        assert s.total_iva_trasladado == 240.0
        assert s.total_iva_acreditable == 560.0
        assert s.total_base_gravable == 3500.0
        assert s.por_tipo == {"A": 1, "I": 1, "S": 1}


class TestValidators:
    def test_rfc_moral_valid(self):
        assert validate_rfc("EMP850101AB1") is None

    def test_rfc_fisica_valid(self):
        assert validate_rfc("CACJ850101AB1") is None

    def test_rfc_invalid(self):
        assert validate_rfc("XYZ") is not None

    def test_iva_rate_valid(self):
        assert validate_iva_rate(0.16) is None
        assert validate_iva_rate(0.0) is None

    def test_iva_rate_invalid(self):
        assert validate_iva_rate(0.12) is not None

    def test_positive_amount(self):
        assert validate_positive_amount(100.0, "base") is None
        assert validate_positive_amount(-5.0, "base") is not None

    def test_validate_records_valid(self):
        assert validate_records(_records()).valid

    def test_validate_records_bad_rfc(self):
        assert not validate_records([_record(rfc="BAD")]).valid


class TestService:
    def setup_method(self):
        self.svc = DIOTService()

    def test_generate_diot(self):
        d = self.svc.generate_diot(_period(), "CONT601208DZ1", _records())
        assert isinstance(d, DIOTDeclaration)
        assert d.status == DIOTStatus.GENERADA
        assert d.summary.total_operaciones == 3

    def test_generate_groups_by_type(self):
        d = self.svc.generate_diot(_period(), "CONT601208DZ1", _records())
        assert d.summary.por_tipo == {"A": 1, "I": 1, "S": 1}

    def test_validate_diot(self):
        assert self.svc.validate_diot(_records()).valid

    def test_calculate_iva_summary(self):
        d = self.svc.generate_diot(_period(), "CONT601208DZ1", _records())
        s = self.svc.calculate_iva_summary(d)
        assert isinstance(s, DIOTSummary)
        assert s.diferencia_iva == 240.0 - 560.0

    def test_generate_no_records_errors(self):
        d = self.svc.generate_diot(_period(), "CONT601208DZ1", [])
        assert d.status == DIOTStatus.ERROR

    def test_get_declaration(self):
        self.svc.generate_diot(_period(), "CONT601208DZ1", _records())
        got = self.svc.get_declaration("CONT601208DZ1", _period())
        assert got is not None and got.summary.total_operaciones == 3

    def test_export_to_txt(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.svc.export_to_txt(_records(), td)
            content = open(path, encoding="utf-8").read()
            assert "RFC|NOMBRE|REGIMEN_FISCAL" in content
            assert "EMP850101AB1" in content

    def test_export_to_xml(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.svc.export_to_xml(_records(), td)
            content = open(path, encoding="utf-8").read()
            assert "<DIOT>" in content
            assert "EMP850101AB1" in content


class TestRouter:
    def test_build_router_requires_auth(self):
        with pytest.raises(ValueError):
            build_diot_router(None, None)

    def test_build_router_ok(self):
        def fake_auth():
            return {"tenant_id": "t1"}
        router = build_diot_router(None, fake_auth)
        assert isinstance(router, APIRouter)
        assert router.prefix == "/api/v1/diot"


class TestApi:
    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        def fake_auth():
            return {"tenant_id": "t1"}
        app = FastAPI()
        app.include_router(build_diot_router(None, fake_auth))
        return TestClient(app)

    def test_generate_endpoint(self, client):
        payload = {
            "client_rfc": "CONT601208DZ1", "period": "2024-Q3",
            "records": [{"rfc_tercero": "EMP850101AB1", "nombre": "Empresa Proveedora SA de CV",
                         "regimen_fiscal": "601", "tipo_operacion": "A", "base_gravable": 1000.0,
                         "iva_trasladado": 160.0, "iva_acreditable": 160.0}],
        }
        r = client.post("/api/v1/diot/generate", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["declaration"]["period"] == "2024-Q3"
        assert body["declaration"]["status"] == "GENERADA"

    def test_get_endpoint(self, client):
        payload = {"client_rfc": "CONT601208DZ1", "period": "2024-Q3",
                   "records": [{"rfc_tercero": "EMP850101AB1", "nombre": "Empresa",
                                "tipo_operacion": "A", "base_gravable": 1000.0,
                                "iva_trasladado": 160.0, "iva_acreditable": 160.0}]}
        client.post("/api/v1/diot/generate", json=payload)
        r = client.get("/api/v1/diot/CONT601208DZ1/2024-Q3")
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_get_not_found(self, client):
        r = client.get("/api/v1/diot/CONT601208DZ1/2024-Q1")
        assert r.status_code == 404

    def test_validate_endpoint(self, client):
        r = client.post("/api/v1/diot/CONT601208DZ1/2024-Q3/validate",
                        json={"records": [{"rfc_tercero": "BAD", "tipo_operacion": "A", "base_gravable": 10}]})
        assert r.status_code == 200 and r.json()["ok"] is False

    def test_export_txt_endpoint(self, client):
        payload = {"client_rfc": "CONT601208DZ1", "period": "2024-Q3",
                   "records": [{"rfc_tercero": "EMP850101AB1", "nombre": "Empresa",
                                "tipo_operacion": "A", "base_gravable": 1000.0,
                                "iva_trasladado": 160.0, "iva_acreditable": 160.0}]}
        client.post("/api/v1/diot/generate", json=payload)
        r = client.get("/api/v1/diot/CONT601208DZ1/2024-Q3/export/txt")
        assert r.status_code == 200 and "EMP850101AB1" in r.text

    def test_export_xml_endpoint(self, client):
        payload = {"client_rfc": "CONT601208DZ1", "period": "2024-Q3",
                   "records": [{"rfc_tercero": "EMP850101AB1", "nombre": "Empresa",
                                "tipo_operacion": "A", "base_gravable": 1000.0,
                                "iva_trasladado": 160.0, "iva_acreditable": 160.0}]}
        client.post("/api/v1/diot/generate", json=payload)
        r = client.get("/api/v1/diot/CONT601208DZ1/2024-Q3/export/xml")
        assert r.status_code == 200 and "<DIOT>" in r.text
