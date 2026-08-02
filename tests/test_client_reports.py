# -*- coding: utf-8 -*-
"""
test_client_reports.py — Tests del módulo Reportes PDF para clientes del despacho.

Cubre:
  - Models: construcción, validación de período, serialización, enums.
  - Generator: los 5 generadores producen bytes PDF válidos (magic header %PDF).
  - Service: generación de los 5 reportes, historial, lectura de PDF, schedules.
  - Routes: los 3 endpoints vía TestClient.

Se evita depender de una DB: el módulo es in-memory (patrón del piloto).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from b2b_ai.features.client_reports.generator import PDFReportGenerator
from b2b_ai.features.client_reports.models import (
    ClientReport,
    ReportSchedule,
    ReportStatus,
    ReportType,
    ScheduleFrequency,
    ScheduleRequest,
)
from b2b_ai.features.client_reports.routes import build_client_reports_router
from b2b_ai.features.client_reports.service import ClientReportService


# ===========================================================================
# 1. MODEL TESTS
# ===========================================================================

class TestModels:
    """Construcción y validación de los modelos pydantic."""

    def test_report_type_enum(self):
        assert ReportType.MONTHLY_TAX.value == "monthly_tax"
        assert ReportType.DIOT_SUMMARY.value == "diot_summary"
        assert ReportType.CONCILIACION.value == "conciliacion"
        assert ReportType.NOMINA_SUMMARY.value == "nomina_summary"
        assert ReportType.BALANZA.value == "balanza"
        # Labels legibles
        assert "Fiscal" in ReportType.MONTHLY_TAX.label

    def test_report_type_from_value(self):
        assert ReportType.from_value("balanza") == ReportType.BALANZA

    def test_report_type_from_value_invalid(self):
        with pytest.raises(ValueError):
            ReportType.from_value("no_existe")

    def test_client_report_defaults(self):
        r = ClientReport(report_type=ReportType.BALANZA, period="2024-01")
        assert r.tenant_id == "default"
        assert r.status == ReportStatus.GENERATED
        assert r.id.startswith("crp-")
        assert r.file_path == ""

    def test_client_report_valid_period(self):
        r = ClientReport(report_type=ReportType.BALANZA, period="2024-12")
        assert r.period == "2024-12"

    def test_client_report_invalid_period_month(self):
        with pytest.raises(Exception):
            ClientReport(report_type=ReportType.BALANZA, period="2024-13")

    def test_client_report_invalid_period_format(self):
        with pytest.raises(Exception):
            ClientReport(report_type=ReportType.BALANZA, period="2024")

    def test_client_report_to_dict(self):
        r = ClientReport(report_type=ReportType.DIOT_SUMMARY, period="2024-02")
        d = r.to_dict()
        assert d["report_type"] == "diot_summary"
        assert d["period"] == "2024-02"
        assert "report_type_label" in d

    def test_schedule_request_model(self):
        req = ScheduleRequest(report_type=ReportType.BALANZA, tenant_id="acme")
        assert req.frequency == ScheduleFrequency.MONTHLY
        assert req.recipients == []


# ===========================================================================
# 2. GENERATOR TESTS
# ===========================================================================

class TestGenerator:
    """Los generadores producen bytes PDF válidos con datos reales/vacíos."""

    @pytest.fixture()
    def gen(self):
        return PDFReportGenerator()

    def _assert_pdf(self, pdf_bytes):
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 500, "PDF demasiado pequeño"
        assert pdf_bytes[:5] == b"%PDF-", "No es un PDF válido (falta magic header)"

    def test_monthly_tax_summary(self, gen):
        pdf = gen.generate_monthly_tax_summary(
            "acme", 2024, 1, tenant_name="ACME SA",
            tenant_rfc="ACME123456A",
            iva={"iva_cobrado": 16000, "iva_pagado": 4800, "saldo_contra": 11200},
            isr={"ingresos_acumulables": 100000, "deducciones": 70000,
                 "base_gravable": 30000, "isr_causado": 4500},
        )
        self._assert_pdf(pdf)

    def test_diot_report(self, gen):
        pdf = gen.generate_diot_report(
            "acme", 2024, 2, tenant_name="ACME SA", tenant_rfc="ACME123456A",
            summary={"total_base_gravable": 50000, "total_iva_trasladado": 8000,
                     "total_iva_acreditable": 2400},
            records=[
                {"rfc_tercero": "PROV001", "nombre": "Proveedor A",
                 "tipo_operacion": "A", "base_gravable": 30000,
                 "iva_trasladado": 4800},
            ],
        )
        self._assert_pdf(pdf)

    def test_diot_report_no_records(self, gen):
        pdf = gen.generate_diot_report("acme", 2024, 3)
        self._assert_pdf(pdf)

    def test_conciliacion_report(self, gen):
        pdf = gen.generate_conciliacion_report(
            "acme", "CTA001", 2024, 1,
            conciliacion={"saldo_banco": 150000, "saldo_contable": 150000,
                          "diferencia": 0, "conciliado": True,
                          "movimientos": [
                              {"fecha": "2024-01-05", "descripcion": "Venta",
                               "monto": 50000, "conciliado": True},
                          ]},
        )
        self._assert_pdf(pdf)

    def test_conciliacion_report_no_account(self, gen):
        # Debe generarse igual aunque no haya account_id (vacío).
        pdf = gen.generate_conciliacion_report("acme", "", 2024, 1)
        self._assert_pdf(pdf)

    def test_nomina_summary(self, gen):
        pdf = gen.generate_nomina_summary(
            "acme", 2024, 1,
            nomina={"num_empleados": 3, "total_percepciones": 120000,
                    "total_deducciones": 24000, "total_neto": 96000,
                    "empleados": [
                        {"nombre": "Juan", "puesto": "Contador",
                         "percepciones": 50000, "deducciones": 10000, "neto": 40000},
                    ]},
        )
        self._assert_pdf(pdf)

    def test_balanza(self, gen):
        pdf = gen.generate_balanza(
            "acme", 2024, 1,
            cuentas=[
                {"cuenta": "1000", "nombre": "Caja", "saldo_deudor": 50000,
                 "saldo_acreedor": 0},
                {"cuenta": "2000", "nombre": "Proveedores", "saldo_deudor": 0,
                 "saldo_acreedor": 50000},
            ],
        )
        self._assert_pdf(pdf)

    def test_balanza_empty(self, gen):
        pdf = gen.generate_balanza("acme", 2024, 1)
        self._assert_pdf(pdf)

    def test_all_report_types_generate(self, gen):
        """Los 5 tipos producen un PDF válido."""
        pdfs = [
            gen.generate_monthly_tax_summary("t", 2024, 1),
            gen.generate_diot_report("t", 2024, 1),
            gen.generate_conciliacion_report("t", "C", 2024, 1),
            gen.generate_nomina_summary("t", 2024, 1),
            gen.generate_balanza("t", 2024, 1),
        ]
        for pdf in pdfs:
            self._assert_pdf(pdf)

    def test_despacho_info(self, gen):
        info = gen.despacho_info()
        assert "nombre" in info
        assert "Likida" in info["nombre"]


# ===========================================================================
# 3. SERVICE TESTS
# ===========================================================================

class TestService:
    """Lógica de negocio: generación, historial y programación."""

    @pytest.fixture()
    def svc(self, tmp_path):
        return ClientReportService(output_dir=str(tmp_path / "reports"))

    def test_generate_monthly_tax(self, svc):
        report = svc.generate_monthly_tax_summary("acme", 2024, 1, "ACME SA", "ACME123")
        assert report.report_type == ReportType.MONTHLY_TAX
        assert report.period == "2024-01"
        assert report.file_path  # ruta guardada
        import os
        assert os.path.exists(report.file_path)
        # El PDF en disco es válido
        data = open(report.file_path, "rb").read()
        assert data[:5] == b"%PDF-"

    def test_generate_diot(self, svc):
        report = svc.generate_diot_report("acme", 2024, 2)
        assert report.report_type == ReportType.DIOT_SUMMARY
        assert report.period == "2024-02"

    def test_generate_conciliacion(self, svc):
        report = svc.generate_conciliacion_report("acme", "CTA001", 2024, 3)
        assert report.report_type == ReportType.CONCILIACION
        assert report.account_id == "CTA001"

    def test_generate_nomina(self, svc):
        report = svc.generate_nomina_summary("acme", 2024, 4)
        assert report.report_type == ReportType.NOMINA_SUMMARY

    def test_generate_balanza(self, svc):
        report = svc.generate_balanza("acme", 2024, 5)
        assert report.report_type == ReportType.BALANZA

    def test_history_empty(self, svc):
        assert svc.list_history() == []

    def test_history_after_generations(self, svc):
        svc.generate_balanza("acme", 2024, 1)
        svc.generate_monthly_tax_summary("acme", 2024, 1)
        svc.generate_diot_report("otra", 2024, 1)
        hist = svc.list_history()
        assert len(hist) == 3
        # Más reciente primero (mismo segundo → orden estable por id desc)
        acme_only = svc.list_history(tenant_id="acme")
        assert len(acme_only) == 2
        balanzas = svc.list_history(report_type=ReportType.BALANZA)
        assert len(balanzas) == 1

    def test_get_and_read_pdf(self, svc):
        report = svc.generate_balanza("acme", 2024, 1)
        assert svc.get_report(report.id) is report
        pdf = svc.read_pdf(report.id)
        assert pdf is not None
        assert pdf[:5] == b"%PDF-"
        # Id inexistente → None
        assert svc.read_pdf("no-existe") is None

    def test_schedule_and_list(self, svc):
        sched = svc.schedule_report(
            ReportType.BALANZA, "acme", ScheduleFrequency.MONTHLY, ["a@x.com"]
        )
        assert sched.frequency == ScheduleFrequency.MONTHLY
        assert sched.active is True
        assert len(svc.list_schedules()) == 1
        assert len(svc.list_schedules(tenant_id="acme")) == 1
        assert len(svc.list_schedules(tenant_id="otra")) == 0

    def test_cancel_schedule(self, svc):
        sched = svc.schedule_report(ReportType.BALANZA, "acme")
        assert svc.cancel_schedule(sched.id) is True
        sched2 = svc._schedules[sched.id]
        assert sched2.active is False
        assert svc.cancel_schedule("no-existe") is False


# ===========================================================================
# 4. ROUTE TESTS
# ===========================================================================

class TestRoutes:
    """Endpoints REST vía TestClient."""

    @pytest.fixture()
    def client(self, tmp_path):
        def fake_require_api_key():
            return {"tenant_id": "acme"}
        # Inyectamos output_dir temporal vía monkeypatch del módulo
        from b2b_ai.features import client_reports as cr_mod
        orig = cr_mod.routes.ClientReportService
        cr_mod.routes.ClientReportService = lambda: ClientReportService(
            output_dir=str(tmp_path / "reports")
        )
        app = _make_app(fake_require_api_key)
        yield TestClient(app)
        cr_mod.routes.ClientReportService = orig

    def test_generate_balanza_pdf(self, client):
        resp = client.get(
            "/api/v1/client-reports/balanza",
            params={"tenant_id": "acme", "year": 2024, "month": 1,
                    "tenant_name": "ACME SA", "tenant_rfc": "ACME123456A"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content[:5] == b"%PDF-"

    def test_generate_monthly_tax_pdf(self, client):
        resp = client.get(
            "/api/v1/client-reports/monthly_tax",
            params={"tenant_id": "acme", "year": 2024, "month": 1},
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_generate_diot_pdf(self, client):
        resp = client.get(
            "/api/v1/client-reports/diot_summary",
            params={"tenant_id": "acme", "year": 2024, "month": 1},
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_generate_nomina_pdf(self, client):
        resp = client.get(
            "/api/v1/client-reports/nomina_summary",
            params={"tenant_id": "acme", "year": 2024, "month": 1},
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_generate_conciliacion_requires_account(self, client):
        # Sin account_id → 400
        resp = client.get(
            "/api/v1/client-reports/conciliacion",
            params={"tenant_id": "acme", "year": 2024, "month": 1},
        )
        assert resp.status_code == 400

    def test_generate_conciliacion_with_account(self, client):
        resp = client.get(
            "/api/v1/client-reports/conciliacion",
            params={"tenant_id": "acme", "account_id": "CTA001",
                    "year": 2024, "month": 1},
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_invalid_report_type(self, client):
        resp = client.get(
            "/api/v1/client-reports/no_existe",
            params={"tenant_id": "acme", "year": 2024, "month": 1},
        )
        assert resp.status_code == 400

    def test_invalid_month(self, client):
        resp = client.get(
            "/api/v1/client-reports/balanza",
            params={"tenant_id": "acme", "year": 2024, "month": 13},
        )
        assert resp.status_code == 400

    def test_history_endpoint(self, client):
        # Generar un par de reportes primero
        client.get("/api/v1/client-reports/balanza",
                   params={"tenant_id": "acme", "year": 2024, "month": 1})
        client.get("/api/v1/client-reports/monthly_tax",
                   params={"tenant_id": "acme", "year": 2024, "month": 1})
        resp = client.get("/api/v1/client-reports/history",
                          params={"tenant_id": "acme"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["count"] >= 2

    def test_schedule_endpoint(self, client):
        resp = client.post(
            "/api/v1/client-reports/schedule",
            json={"report_type": "balanza", "tenant_id": "acme",
                  "frequency": "monthly", "recipients": ["a@x.com"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["schedule"]["report_type"] == "balanza"
        assert body["schedule"]["active"] is True

    def test_router_requires_auth(self):
        # Construir sin auth debe fallar
        with pytest.raises(ValueError):
            build_client_reports_router(db=None, require_api_key=None)


def _make_app(require_api_key):
    """Helper: mini app FastAPI que monta el router client_reports."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(
        build_client_reports_router(db=None, require_api_key=require_api_key)
    )
    return app
