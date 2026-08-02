# -*- coding: utf-8 -*-
"""Tests para los modelos y el servicio de payroll del módulo nómina."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from b2b_ai.features.nomina.models import (
    NominaRecordCreate,
    NominaStatus,
    ConceptType,
    NominaConcept,
)
from b2b_ai.features.nomina.service import (
    NominaManager,
    NominaValidator,
    PayrollCalculator,
    PayrollSummaryGenerator,
    _reset_state,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Resetea el store en memoria antes de cada test."""
    _reset_state()
    yield
    _reset_state()


def _rec(rfc="ABCD123456XYZ", name="Juan Perez", start="2025-01-01",
         end="2025-01-31", base=10000, ot=500, bonuses=200, deductions=300,
         tenant="T1"):
    return NominaRecordCreate(
        employee_rfc=rfc, employee_name=name,
        period_start=start, period_end=end,
        base_salary=base, overtime_pay=ot, bonuses=bonuses,
        deductions=deductions,
    )


# ── NominaValidator ──

class TestNominaValidator:
    def test_rfc_valid_pf(self):
        assert NominaValidator.validate_rfc_format("ABCD123456XYZ") is None

    def test_rfc_valid_pm(self):
        assert NominaValidator.validate_rfc_format("ABC123456789") is None

    def test_rfc_invalid(self):
        assert NominaValidator.validate_rfc_format("mal") is not None
        assert NominaValidator.validate_rfc_format("") is not None

    def test_period_valid(self):
        assert NominaValidator.validate_period("2025-01-01", "2025-01-31") is None

    def test_period_inverted(self):
        assert NominaValidator.validate_period("2025-02-01", "2025-01-01") is not None

    def test_period_bad_format(self):
        assert NominaValidator.validate_period("no-date", "2025-01-31") is not None

    def test_amounts_negative(self):
        # Pydantic ya fuerza ge=0; usamos model_construct para probar el
        # validador de servicio directamente con un monto negativo.
        data = NominaRecordCreate.model_construct(
            employee_rfc="ABCD123456XYZ", employee_name="Juan Perez",
            period_start="2025-01-01", period_end="2025-01-31",
            base_salary=-5, overtime_pay=500, bonuses=200, deductions=300,
        )
        assert NominaValidator.validate_amounts(data) is not None

    def test_duplicate_period(self):
        data = _rec()
        mgr = NominaManager()
        mgr.create_nomina_record("T1", data)
        assert NominaValidator.check_duplicate_period(
            "T1", "ABCD123456XYZ", "2025-01-15", "2025-02-10") is True


# ── PayrollCalculator ──

class TestPayrollCalculator:
    def test_isr_positive(self):
        assert PayrollCalculator.calculate_isr(10000, "03") > 0

    def test_isr_zero(self):
        assert PayrollCalculator.calculate_isr(0, "03") == 0.0

    def test_isr_progressive(self):
        # Mayor ingreso → mayor ISR
        low = PayrollCalculator.calculate_isr(5000, "03")
        high = PayrollCalculator.calculate_isr(50000, "03")
        assert high > low

    def test_imss_split(self):
        imss = PayrollCalculator.calculate_imss(10000)
        assert imss["imss_employer"] > imss["imss_employee"] > 0

    def test_net_pay_less_than_gross(self):
        net = PayrollCalculator.calculate_net_pay(10000, 1000)
        assert net["net_pay"] < 9000.0
        assert net["isr"] > 0


# ── NominaManager ──

class TestNominaManager:
    def test_create_record(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        assert rec.status == NominaStatus.DRAFT
        assert rec.total_gross == 10700.0
        assert rec.net_pay < 10700.0
        assert rec.isr_retention > 0

    def test_create_requires_tenant(self):
        mgr = NominaManager()
        with pytest.raises(ValueError):
            mgr.create_nomina_record("", _rec())

    def test_create_invalid_rfc(self):
        mgr = NominaManager()
        with pytest.raises(ValueError):
            mgr.create_nomina_record("T1", _rec(rfc="bad"))

    def test_duplicate_period_rejected(self):
        mgr = NominaManager()
        mgr.create_nomina_record("T1", _rec())
        with pytest.raises(ValueError):
            mgr.create_nomina_record("T1", _rec(start="2025-01-10", end="2025-02-05"))

    def test_lifecycle(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        mgr.validate_payroll(rec.id, "T1")
        assert rec.status == NominaStatus.VALIDATED
        mgr.mark_paid(rec.id, "T1")
        assert rec.status == NominaStatus.PAID
        assert rec.payment_date is not None

    def test_pay_requires_validated(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        with pytest.raises(ValueError):
            mgr.mark_paid(rec.id, "T1")

    def test_cannot_void_paid(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        mgr.validate_payroll(rec.id, "T1")
        mgr.mark_paid(rec.id, "T1")
        with pytest.raises(ValueError):
            mgr.void_payroll(rec.id, "T1")

    def test_void(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        mgr.void_payroll(rec.id, "T1")
        assert rec.status == NominaStatus.VOIDED

    def test_tenant_isolation(self):
        mgr = NominaManager()
        r1 = mgr.create_nomina_record("T1", _rec())
        mgr.create_nomina_record("T2", _rec(rfc="ZZZZ123456789", name="Otra"))
        assert len(mgr.list_records("T1")) == 1
        assert len(mgr.list_records("T2")) == 1
        # T2 no puede ver el record de T1 (IDOR)
        with pytest.raises(KeyError):
            mgr.get_record(r1.id, "T2")

    def test_list_filters(self):
        mgr = NominaManager()
        mgr.create_nomina_record("T1", _rec())
        mgr.create_nomina_record("T1", _rec(rfc="ZZZZ123456789", name="Otra",
                                            start="2025-02-01", end="2025-02-28"))
        assert len(mgr.list_records("T1", period="2025-01")) == 1
        assert len(mgr.list_records("T1", employee="Otra")) == 1
        assert len(mgr.list_records("T1", status=NominaStatus.DRAFT)) == 2

    def test_concepts(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        concept = NominaConcept(
            nomina_id=rec.id, concept_type=ConceptType.PERCEPCION,
            concept_code="001", description="Sueldo", amount=10000, taxable=True)
        mgr.add_concept(rec.id, "T1", concept)
        assert len(mgr.get_concepts(rec.id, "T1")) == 1


# ── PayrollSummaryGenerator ──

class TestPayrollSummaryGenerator:
    def test_summary(self):
        mgr = NominaManager()
        mgr.create_nomina_record("T1", _rec())
        gen = PayrollSummaryGenerator()
        s = gen.generate_summary("T1", "2025-01")
        assert s.total_employees == 1
        assert s.total_gross == 10700.0
        assert s.total_net > 0
        assert s.total_isr > 0

    def test_summary_excludes_voided(self):
        mgr = NominaManager()
        rec = mgr.create_nomina_record("T1", _rec())
        mgr.void_payroll(rec.id, "T1")
        gen = PayrollSummaryGenerator()
        s = gen.generate_summary("T1", "2025-01")
        assert s.total_employees == 0

    def test_csv_export(self):
        mgr = NominaManager()
        mgr.create_nomina_record("T1", _rec())
        gen = PayrollSummaryGenerator()
        csv_txt = gen.export_to_csv("T1", "2025-01")
        assert "employee_rfc" in csv_txt
        assert "ABCD123456XYZ" in csv_txt

    def test_tenant_isolation_summary(self):
        mgr = NominaManager()
        mgr.create_nomina_record("T1", _rec())
        mgr.create_nomina_record("T2", _rec(rfc="ZZZZ123456789", name="Otra"))
        gen = PayrollSummaryGenerator()
        assert gen.generate_summary("T1", "2025-01").total_employees == 1
        assert gen.generate_summary("T2", "2025-01").total_employees == 1
# ── Payroll Routes ──

def _fake_auth(tenant="T1"):
    def dep():
        return {"key": "k", "tenant_id": tenant, "user_id": "u1"}
    return dep


class TestNominaPayrollRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.nomina.routes import build_nomina_router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(build_nomina_router(_fake_auth()))
        return TestClient(app)

    def _create(self, client, **kw):
        payload = {
            "employee_rfc": "ABCD123456XYZ", "employee_name": "Juan Perez",
            "period_start": "2025-01-01", "period_end": "2025-01-31",
            "base_salary": 10000, "overtime_pay": 500, "bonuses": 200,
            "deductions": 300,
        }
        payload.update(kw)
        return client.post("/nomina/records", json=payload)

    def test_create_and_net(self, client):
        r = self._create(client)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["record"]["net_pay"] < 10700.0

    def test_duplicate_409(self, client):
        self._create(client)
        r = self._create(client, period_start="2025-01-15", period_end="2025-02-10")
        assert r.status_code == 400
        assert "Ya existe" in r.json()["detail"]

    def test_lifecycle_via_route(self, client):
        rid = self._create(client).json()["record"]["id"]
        assert client.post(f"/nomina/records/{rid}/validate").json()["record"]["status"] == "VALIDATED"
        assert client.post(f"/nomina/records/{rid}/pay").json()["record"]["status"] == "PAID"
        assert client.post(f"/nomina/records/{rid}/void").status_code == 409

    def test_summary_and_export(self, client):
        self._create(client)
        s = client.get("/nomina/summary", params={"period": "2025-01"}).json()
        assert s["summary"]["total_employees"] == 1
        csv_txt = client.get("/nomina/export", params={"period": "2025-01"}).text
        assert "ABCD123456XYZ" in csv_txt

    def test_missing_tenant_rejected(self, client):
        # Un auth sin tenant_id debe fallar con 400
        from b2b_ai.features.nomina.routes import build_nomina_router
        from fastapi import FastAPI
        def no_tenant():
            return {"key": "k", "user_id": "u1"}
        app = FastAPI()
        app.include_router(build_nomina_router(no_tenant))
        c = TestClient(app)
        r = c.post("/nomina/records", json={
            "employee_rfc": "ABCD123456XYZ", "employee_name": "Juan",
            "period_start": "2025-01-01", "period_end": "2025-01-31",
            "base_salary": 1000})
        assert r.status_code == 400
