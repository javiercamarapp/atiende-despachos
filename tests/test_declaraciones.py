# -*- coding: utf-8 -*-
"""
test_declaraciones.py — Tests del módulo de Declaraciones Periódicas.

Cobertura:
  IVA:
    - Generación de declaración mensual con datos conocidos
    - Cálculo de saldo a favor/contra
    - Validación de período mensual
    - Validación de RFC
    - IVA sin datos (draft vacío)

  ISR Provisional:
    - Generación con datos conocidos
    - Cálculo de ISR con tabla progresiva
    - Validación de deducciones vs ingresos
    - Utilidad consistente

  ISR Anual:
    - Generación con datos conocidos
    - Cálculo ISR anual con tabla progresiva
    - Pagos provisionales requeridos
    - Período anual (YYYY)

  Deadlines:
    - Cálculo de fechas límite mensuales (IVA/ISR provisional)
    - Cálculo de fecha límite anual (ISR anual)
    - Actualización de días restantes
    - Estados: PENDING → URGENT → OVERDUE

  Reminders:
    - Envío de recordatorios antes del vencimiento
    - No duplicar recordatorios
    - Solo enviar para deadlines pendientes

  Validadores:
    - validate_period_format
    - validate_period_consistency
    - validate_iva_data
    - validate_isr_data
    - validate_deadline_date
    - validate_rfc
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.declaraciones.models import (
    Declaracion,
    DeclaracionStatus,
    DeclaracionType,
    Deadline,
    DeadlineStatus,
    IvaData,
    IsrData,
)
from b2b_ai.features.declaraciones.service import DeclaracionesService
from b2b_ai.features.declaraciones.validators import (
    validate_deadline_date,
    validate_iva_data,
    validate_isr_data,
    validate_period_consistency,
    validate_period_format,
    validate_rfc,
)
from b2b_ai.features.declaraciones.routes import build_declaraciones_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    """Fresh DeclaracionesService instance."""
    return DeclaracionesService()


@pytest.fixture
def client():
    """FastAPI test client with declaraciones router."""
    app = FastAPI()
    router = build_declaraciones_router(db=None, require_api_key=lambda: {"tenant_id": "test", "key": "test"})
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# IVA Tests
# ---------------------------------------------------------------------------

class TestIvaDeclaration:
    """Tests for IVA declaration generation."""

    def test_generate_iva_with_known_data(self, service):
        """IVA declaration with known iva_cobrado and iva_pagado."""
        data = {
            "iva_cobrado": 16000.00,
            "iva_pagado": 8000.00,
        }
        decl = service.generate_monthly_iva(
            month=1, year=2024, tenant_id="t1", rfc="XAXX010101000", data=data,
        )

        assert decl.tipo == DeclaracionType.IVA
        assert decl.periodo == "2024-01"
        assert decl.status == DeclaracionStatus.DRAFT
        assert decl.rfc == "XAXX010101000"

        iva_data = decl.data
        assert iva_data["iva_cobrado"] == 16000.00
        assert iva_data["iva_pagado"] == 8000.00
        assert iva_data["saldo_contra"] == 8000.00
        assert iva_data["saldo_favor"] == 0.0

    def test_iva_saldo_favor(self, service):
        """IVA declaration where iva_pagado > iva_cobrado (credit balance)."""
        data = {
            "iva_cobrado": 5000.00,
            "iva_pagado": 12000.00,
        }
        decl = service.generate_monthly_iva(
            month=3, year=2024, tenant_id="t1", rfc="XAXX010101000", data=data,
        )

        iva_data = decl.data
        assert iva_data["saldo_favor"] == 7000.00
        assert iva_data["saldo_contra"] == 0.0

    def test_iva_equal_amounts(self, service):
        """IVA declaration where cobrado == pagado (balanced)."""
        data = {
            "iva_cobrado": 10000.00,
            "iva_pagado": 10000.00,
        }
        decl = service.generate_monthly_iva(
            month=6, year=2024, tenant_id="t1", rfc="XAXX010101000", data=data,
        )

        iva_data = decl.data
        assert iva_data["saldo_favor"] == 0.0
        assert iva_data["saldo_contra"] == 0.0

    def test_iva_draft_without_data(self, service):
        """IVA declaration as empty draft (no data provided)."""
        decl = service.generate_monthly_iva(
            month=12, year=2024, tenant_id="t1", rfc="XAXX010101000",
        )

        assert decl.tipo == DeclaracionType.IVA
        assert decl.periodo == "2024-12"
        assert decl.data is None

    def test_iva_deadline_next_month(self, service):
        """IVA deadline is 17th of following month."""
        decl = service.generate_monthly_iva(
            month=11, year=2024, tenant_id="t1", rfc="XAXX010101000",
        )

        deadlines = service.calculate_deadlines("t1")
        assert len(deadlines) == 1
        assert deadlines[0].fecha_limite == "2024-12-17"

    def test_iva_deadline_december(self, service):
        """IVA deadline for December is January 17th of next year."""
        decl = service.generate_monthly_iva(
            month=12, year=2024, tenant_id="t1", rfc="XAXX010101000",
        )

        deadlines = service.calculate_deadlines("t1")
        assert len(deadlines) == 1
        assert deadlines[0].fecha_limite == "2025-01-17"

    def test_iva_invalid_month(self, service):
        """IVA with invalid month raises ValueError."""
        with pytest.raises(ValueError, match="(?i)mes.*inválido"):
            service.generate_monthly_iva(
                month=13, year=2024, tenant_id="t1",
            )


# ---------------------------------------------------------------------------
# ISR Provisional Tests
# ---------------------------------------------------------------------------

class TestIsrProvisional:
    """Tests for ISR provisional declaration generation."""

    def test_isr_provisional_with_data(self, service):
        """ISR provisional with known income data."""
        data = {
            "ingresos": 100000.00,
            "deducciones": 30000.00,
            "pagos_provisionales": 5000.00,
        }
        decl = service.generate_provisional_isr(
            month=1, year=2024, tenant_id="t1", rfc="XAXX010101000", data=data,
        )

        assert decl.tipo == DeclaracionType.ISR_PROVISIONAL
        assert decl.periodo == "2024-01"

        isr_data = decl.data
        assert isr_data["ingresos"] == 100000.00
        assert isr_data["deducciones"] == 30000.00
        assert isr_data["utilidad"] == 70000.00
        assert isr_data["isr_calculated"] > 0
        assert isr_data["pagos_provisionales"] == 5000.00

    def test_isr_calculation_monthly(self, service):
        """ISR calculation uses progressive table correctly."""
        # $50,000 monthly income → should fall in 34% bracket
        data = {"ingresos": 50000.00, "deducciones": 0.0}
        decl = service.generate_provisional_isr(
            month=6, year=2024, tenant_id="t1", data=data,
        )

        isr_data = decl.data
        # Expected: 8857.35 + (50000 - 34410.82) * 0.34 = 8857.35 + 5300.32 = 14157.67
        assert isr_data["isr_calculated"] == pytest.approx(14157.67, abs=0.01)

    def test_isr_low_income(self, service):
        """ISR for low income falls in first bracket."""
        data = {"ingresos": 200.00, "deducciones": 0.0}
        decl = service.generate_provisional_isr(
            month=1, year=2024, tenant_id="t1", data=data,
        )

        isr_data = decl.data
        # 200 * 1.92% = 3.84
        assert isr_data["isr_calculated"] == pytest.approx(3.84, abs=0.01)

    def test_isr_provisional_deadline(self, service):
        """ISR provisional deadline is 17th of following month."""
        decl = service.generate_provisional_isr(
            month=5, year=2024, tenant_id="t1",
        )

        deadlines = service.calculate_deadlines("t1")
        assert len(deadlines) == 1
        assert deadlines[0].fecha_limite == "2024-06-17"

    def test_isr_provisional_draft_without_data(self, service):
        """ISR provisional as empty draft."""
        decl = service.generate_provisional_isr(
            month=3, year=2024, tenant_id="t1",
        )

        assert decl.tipo == DeclaracionType.ISR_PROVISIONAL
        assert decl.data is None


# ---------------------------------------------------------------------------
# ISR Anual Tests
# ---------------------------------------------------------------------------

class TestIsrAnual:
    """Tests for ISR annual declaration generation."""

    def test_isr_anual_with_data(self, service):
        """ISR annual with known income data."""
        data = {
            "ingresos": 800000.00,
            "deducciones": 200000.00,
            "pagos_provisionales": 80000.00,
        }
        decl = service.generate_annual_isr(
            year=2024, tenant_id="t1", rfc="XAXX010101000", data=data,
        )

        assert decl.tipo == DeclaracionType.ISR_ANUAL
        assert decl.periodo == "2024"

        isr_data = decl.data
        assert isr_data["ingresos"] == 800000.00
        assert isr_data["deducciones"] == 200000.00
        assert isr_data["utilidad"] == 600000.00
        assert isr_data["isr_calculated"] > 0
        assert isr_data["pagos_provisionales"] == 80000.00

    def test_isr_anual_calculation(self, service):
        """ISR annual calculation uses annual progressive table."""
        # $500,000 annual income → 34% bracket
        data = {"ingresos": 500000.00, "deducciones": 0.0, "pagos_provisionales": 50000.0}
        decl = service.generate_annual_isr(
            year=2024, tenant_id="t1", data=data,
        )

        isr_data = decl.data
        # Expected: 106293.69 + (500000 - 412946.07) * 0.34 = 106293.69 + 29598.34 = 135892.03
        assert isr_data["isr_calculated"] == pytest.approx(135892.03, abs=0.01)

    def test_isr_anual_deadline(self, service):
        """ISR annual deadline is April 30th of following year."""
        decl = service.generate_annual_isr(year=2024, tenant_id="t1")

        deadlines = service.calculate_deadlines("t1")
        assert len(deadlines) == 1
        assert deadlines[0].fecha_limite == "2025-04-30"

    def test_isr_anual_requires_provisional_payments(self, service):
        """ISR annual with income but no provisional payments should error."""
        data = {
            "ingresos": 100000.00,
            "deducciones": 0.0,
            "pagos_provisionales": 0.0,
        }
        with pytest.raises(ValueError, match="pagos provisionales"):
            service.generate_annual_isr(
                year=2024, tenant_id="t1", data=data,
            )


# ---------------------------------------------------------------------------
# Deadline Tests
# ---------------------------------------------------------------------------

class TestDeadlines:
    """Tests for deadline calculation and tracking."""

    def test_multiple_deadlines_sorted(self, service):
        """Multiple deadlines are sorted by fecha_limite."""
        service.generate_monthly_iva(month=1, year=2024, tenant_id="t1")
        service.generate_monthly_iva(month=3, year=2024, tenant_id="t1")
        service.generate_annual_isr(year=2024, tenant_id="t1")

        deadlines = service.calculate_deadlines("t1")
        assert len(deadlines) == 3

        # Should be sorted by date
        dates = [d.fecha_limite for d in deadlines]
        assert dates == sorted(dates)

    def test_deadline_status_pending(self, service):
        """Deadline far in the future has PENDING status."""
        # Generate declaration for a future month
        decl = service.generate_monthly_iva(
            month=12, year=2026, tenant_id="t1",
        )

        deadlines = service.calculate_deadlines("t1")
        assert deadlines[0].estado == DeadlineStatus.PENDING

    def test_deadline_overdue(self, service):
        """Past deadline has OVERDUE status."""
        # Manually create a deadline in the past
        deadline = Deadline(
            id="test-past",
            tenant_id="t1",
            tipo=DeclaracionType.IVA,
            periodo="2020-01",
            fecha_limite="2020-02-17",
            dias_restantes=0,
            estado=DeadlineStatus.PENDING,
        )
        service._deadlines["test-past"] = deadline

        deadlines = service.calculate_deadlines("t1")
        assert len(deadlines) == 1
        assert deadlines[0].estado == DeadlineStatus.OVERDUE
        assert deadlines[0].dias_restantes == 0

    def test_deadline_tenant_filter(self, service):
        """Deadlines are filtered by tenant."""
        service.generate_monthly_iva(month=1, year=2024, tenant_id="t1")
        service.generate_monthly_iva(month=1, year=2024, tenant_id="t2")

        deadlines_t1 = service.calculate_deadlines("t1")
        deadlines_t2 = service.calculate_deadlines("t2")

        assert len(deadlines_t1) == 1
        assert len(deadlines_t2) == 1
        assert deadlines_t1[0].tenant_id == "t1"
        assert deadlines_t2[0].tenant_id == "t2"


# ---------------------------------------------------------------------------
# Reminder Tests
# ---------------------------------------------------------------------------

class TestReminders:
    """Tests for reminder sending logic."""

    def test_reminder_sent_within_window(self, service):
        """Reminder sent for deadlines within days_before window."""
        # Create deadline 5 days from now
        future_date = (date.today() + timedelta(days=5)).isoformat()
        deadline = Deadline(
            id="test-remind",
            tenant_id="t1",
            tipo=DeclaracionType.IVA,
            periodo="2024-06",
            fecha_limite=future_date,
            dias_restantes=5,
            estado=DeadlineStatus.PENDING,
        )
        service._deadlines["test-remind"] = deadline

        reminders = service.send_reminders("t1", days_before=7)
        assert len(reminders) == 1
        assert reminders[0].reminder_sent is True

    def test_reminder_not_sent_outside_window(self, service):
        """Reminder NOT sent for deadlines beyond days_before window."""
        future_date = (date.today() + timedelta(days=30)).isoformat()
        deadline = Deadline(
            id="test-no-remind",
            tenant_id="t1",
            tipo=DeclaracionType.IVA,
            periodo="2024-12",
            fecha_limite=future_date,
            dias_restantes=30,
            estado=DeadlineStatus.PENDING,
        )
        service._deadlines["test-no-remind"] = deadline

        reminders = service.send_reminders("t1", days_before=7)
        assert len(reminders) == 0

    def test_reminder_no_duplicate(self, service):
        """Reminder not sent twice for the same deadline."""
        future_date = (date.today() + timedelta(days=3)).isoformat()
        deadline = Deadline(
            id="test-no-dup",
            tenant_id="t1",
            tipo=DeclaracionType.IVA,
            periodo="2024-06",
            fecha_limite=future_date,
            dias_restantes=3,
            estado=DeadlineStatus.PENDING,
        )
        service._deadlines["test-no-dup"] = deadline

        # Send first reminder
        reminders1 = service.send_reminders("t1", days_before=7)
        assert len(reminders1) == 1

        # Send again — should not duplicate
        reminders2 = service.send_reminders("t1", days_before=7)
        assert len(reminders2) == 0

    def test_reminder_skips_completed(self, service):
        """Reminder not sent for completed deadlines."""
        deadline = Deadline(
            id="test-completed",
            tenant_id="t1",
            tipo=DeclaracionType.IVA,
            periodo="2024-01",
            fecha_limite="2024-02-17",
            dias_restantes=0,
            estado=DeadlineStatus.COMPLETED,
        )
        service._deadlines["test-completed"] = deadline

        reminders = service.send_reminders("t1", days_before=7)
        assert len(reminders) == 0

    def test_reminder_overdue_always_sent(self, service):
        """Overdue deadline always gets reminder if not yet sent."""
        past_date = (date.today() - timedelta(days=10)).isoformat()
        deadline = Deadline(
            id="test-overdue",
            tenant_id="t1",
            tipo=DeclaracionType.IVA,
            periodo="2024-01",
            fecha_limite=past_date,
            dias_restantes=0,
            estado=DeadlineStatus.OVERDUE,
        )
        service._deadlines["test-overdue"] = deadline

        reminders = service.send_reminders("t1", days_before=7)
        assert len(reminders) == 1
        assert reminders[0].dias_restantes == 0


# ---------------------------------------------------------------------------
# Validator Tests
# ---------------------------------------------------------------------------

class TestValidators:
    """Tests for validation functions."""

    def test_validate_period_monthly_valid(self):
        """Valid monthly period format."""
        is_valid, errors = validate_period_format("2024-01")
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_period_monthly_invalid(self):
        """Invalid monthly period format."""
        is_valid, errors = validate_period_format("2024/01")
        assert is_valid is False
        assert len(errors) > 0

    def test_validate_period_annual_valid(self):
        """Valid annual period format."""
        is_valid, errors = validate_period_format("2024", allow_annual=True)
        assert is_valid is True

    def test_validate_period_annual_not_allowed(self):
        """Annual period not allowed when allow_annual=False."""
        is_valid, errors = validate_period_format("2024", allow_annual=False)
        assert is_valid is False

    def test_validate_period_invalid_month(self):
        """Invalid month in period."""
        is_valid, errors = validate_period_format("2024-13")
        assert is_valid is False
        assert any("mes" in e.lower() and "inválido" in e for e in errors)

    def test_validate_period_consistency_iva(self):
        """IVA requires monthly period."""
        is_valid, errors = validate_period_consistency("iva", "2024-01")
        assert is_valid is True

    def test_validate_period_consistency_isr_anual(self):
        """ISR Anual requires annual period."""
        is_valid, errors = validate_period_consistency("isr_anual", "2024")
        assert is_valid is True

    def test_validate_period_consistency_wrong_format(self):
        """Wrong period format for declaration type."""
        is_valid, errors = validate_period_consistency("iva", "2024")
        assert is_valid is False

    def test_validate_iva_data_valid(self):
        """Valid IVA data."""
        data = {"iva_cobrado": 10000.0, "iva_pagado": 5000.0, "saldo_contra": 5000.0}
        is_valid, errors = validate_iva_data(data)
        assert is_valid is True

    def test_validate_iva_data_missing_field(self):
        """IVA data missing required field."""
        data = {"iva_cobrado": 10000.0}
        is_valid, errors = validate_iva_data(data)
        assert is_valid is False

    def test_validate_iva_data_negative_amount(self):
        """IVA data with negative amount."""
        data = {"iva_cobrado": -1000.0, "iva_pagado": 5000.0}
        is_valid, errors = validate_iva_data(data)
        assert is_valid is False

    def test_validate_iva_data_both_balances(self):
        """IVA data with both saldo_favor and saldo_contra > 0."""
        data = {
            "iva_cobrado": 10000.0,
            "iva_pagado": 10000.0,
            "saldo_favor": 100.0,
            "saldo_contra": 100.0,
        }
        is_valid, errors = validate_iva_data(data)
        assert is_valid is False

    def test_validate_isr_data_valid(self):
        """Valid ISR data."""
        data = {
            "ingresos": 100000.0,
            "deducciones": 30000.0,
            "utilidad": 70000.0,
            "isr_calculated": 15000.0,
            "pagos_provisionales": 10000.0,
        }
        is_valid, errors = validate_isr_data(data)
        assert is_valid is True

    def test_validate_isr_deductions_exceed_income(self):
        """ISR data where deductions exceed income."""
        data = {"ingresos": 10000.0, "deducciones": 20000.0}
        is_valid, errors = validate_isr_data(data)
        assert is_valid is False

    def test_validate_isr_utilidad_mismatch(self):
        """ISR data where utilidad doesn't match ingresos - deducciones."""
        data = {"ingresos": 100000.0, "deducciones": 30000.0, "utilidad": 50000.0}
        is_valid, errors = validate_isr_data(data)
        assert is_valid is False

    def test_validate_deadline_date_iva(self):
        """Valid IVA deadline date."""
        is_valid, errors = validate_deadline_date("2024-02-17", "iva", "2024-01")
        assert is_valid is True

    def test_validate_deadline_date_wrong(self):
        """Wrong IVA deadline date."""
        is_valid, errors = validate_deadline_date("2024-02-15", "iva", "2024-01")
        assert is_valid is False

    def test_validate_deadline_date_isr_anual(self):
        """Valid ISR Anual deadline date."""
        is_valid, errors = validate_deadline_date("2025-04-30", "isr_anual", "2024")
        assert is_valid is True

    def test_validate_rfc_moral(self):
        """Valid RFC for moral person (12 chars)."""
        is_valid, errors = validate_rfc("ABC010101000")
        assert is_valid is True

    def test_validate_rfc_fisica(self):
        """Valid RFC for physical person (13 chars)."""
        is_valid, errors = validate_rfc("GARC850101000")
        assert is_valid is True

    def test_validate_rfc_invalid(self):
        """Invalid RFC format."""
        is_valid, errors = validate_rfc("ABC")
        assert is_valid is False


# ---------------------------------------------------------------------------
# API Route Tests
# ---------------------------------------------------------------------------

class TestRoutes:
    """Tests for the FastAPI API routes."""

    def test_post_iva_endpoint(self, client):
        """POST /declaraciones/iva generates IVA declaration."""
        response = client.post(
            "/api/v1/declaraciones/iva",
            json={
                "month": 1,
                "year": 2024,
                "tenant_id": "t1",
                "rfc": "XAXX010101000",
                "data": {
                    "iva_cobrado": 16000.0,
                    "iva_pagado": 8000.0,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["declaracion"]["tipo"] == "iva"
        assert data["declaracion"]["periodo"] == "2024-01"

    def test_post_isr_provisional_endpoint(self, client):
        """POST /declaraciones/isr-provisional generates ISR provisional."""
        response = client.post(
            "/api/v1/declaraciones/isr-provisional",
            json={
                "month": 6,
                "year": 2024,
                "tenant_id": "t1",
                "data": {
                    "ingresos": 100000.0,
                    "deducciones": 30000.0,
                    "pagos_provisionales": 5000.0,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["declaracion"]["tipo"] == "isr_provisional"

    def test_post_isr_anual_endpoint(self, client):
        """POST /declaraciones/isr-anual generates ISR annual."""
        response = client.post(
            "/api/v1/declaraciones/isr-anual",
            json={
                "year": 2024,
                "tenant_id": "t1",
                "data": {
                    "ingresos": 500000.0,
                    "deducciones": 100000.0,
                    "pagos_provisionales": 50000.0,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["declaracion"]["tipo"] == "isr_anual"
        assert data["declaracion"]["periodo"] == "2024"

    def test_get_deadlines_endpoint(self, client):
        """GET /declaraciones/deadlines returns deadlines."""
        # Generate a declaration first
        client.post(
            "/api/v1/declaraciones/iva",
            json={"month": 1, "year": 2024, "tenant_id": "t1"},
        )

        response = client.get(
            "/api/v1/declaraciones/deadlines",
            params={"tenant_id": "t1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["count"] >= 1

    def test_post_reminders_endpoint(self, client):
        """POST /declaraciones/reminders sends reminders."""
        # Generate declaration with deadline in 3 days
        response = client.post(
            "/api/v1/declaraciones/iva",
            json={"month": 1, "year": 2024, "tenant_id": "t1"},
        )

        response = client.post(
            "/api/v1/declaraciones/reminders",
            json={"tenant_id": "t1", "days_before": 30},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_get_declaracion_by_id(self, client):
        """GET /declaraciones/{id} returns declaration."""
        # Generate a declaration
        create_resp = client.post(
            "/api/v1/declaraciones/iva",
            json={"month": 1, "year": 2024, "tenant_id": "t1"},
        )
        decl_id = create_resp.json()["declaracion"]["id"]

        response = client.get(f"/api/v1/declaraciones/{decl_id}")
        assert response.status_code == 200
        assert response.json()["declaracion"]["id"] == decl_id

    def test_get_declaracion_not_found(self, client):
        """GET /declaraciones/{id} returns 404 for missing."""
        response = client.get("/api/v1/declaraciones/nonexistent")
        assert response.status_code == 404

    def test_list_by_tenant(self, client):
        """GET /declaraciones/tenant/{tenant_id} lists declarations."""
        client.post(
            "/api/v1/declaraciones/iva",
            json={"month": 1, "year": 2024, "tenant_id": "t1"},
        )
        client.post(
            "/api/v1/declaraciones/isr-provisional",
            json={"month": 1, "year": 2024, "tenant_id": "t1"},
        )

        response = client.get("/api/v1/declaraciones/tenant/t1")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2

    def test_update_status(self, client):
        """PUT /declaraciones/{id}/status updates declaration status."""
        create_resp = client.post(
            "/api/v1/declaraciones/iva",
            json={"month": 1, "year": 2024, "tenant_id": "t1"},
        )
        decl_id = create_resp.json()["declaracion"]["id"]

        response = client.put(
            f"/api/v1/declaraciones/{decl_id}/status",
            json={"status": "filed"},
        )
        assert response.status_code == 200
        assert response.json()["declaracion"]["status"] == "filed"
        assert response.json()["declaracion"]["fecha_presentacion"] is not None

    def test_invalid_iva_data_returns_422(self, client):
        """POST /declaraciones/iva returns 422 for invalid data."""
        response = client.post(
            "/api/v1/declaraciones/iva",
            json={"month": 13, "year": 2024, "tenant_id": "t1"},
        )
        assert response.status_code == 422

    def test_invalid_isr_data_returns_422(self, client):
        """POST /declaraciones/isr-provisional returns 422 for invalid data."""
        response = client.post(
            "/api/v1/declaraciones/isr-provisional",
            json={
                "month": 1,
                "year": 2024,
                "tenant_id": "t1",
                "data": {"ingresos": 10000, "deducciones": 20000},
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_amounts_iva(self, service):
        """IVA declaration with zero amounts."""
        data = {"iva_cobrado": 0.0, "iva_pagado": 0.0}
        decl = service.generate_monthly_iva(
            month=1, year=2024, tenant_id="t1", data=data,
        )

        iva_data = decl.data
        assert iva_data["saldo_favor"] == 0.0
        assert iva_data["saldo_contra"] == 0.0

    def test_large_amounts_isr(self, service):
        """ISR calculation with large amounts."""
        data = {
            "ingresos": 10000000.0,
            "deducciones": 0.0,
            "pagos_provisionales": 2000000.0,
        }
        decl = service.generate_annual_isr(
            year=2024, tenant_id="t1", data=data,
        )

        isr_data = decl.data
        # Should be in top bracket (35%)
        assert isr_data["isr_calculated"] > 3000000.0

    def test_decimal_precision_iva(self, service):
        """IVA declaration with decimal precision."""
        data = {"iva_cobrado": 16000.33, "iva_pagado": 8000.67}
        decl = service.generate_monthly_iva(
            month=1, year=2024, tenant_id="t1", data=data,
        )

        iva_data = decl.data
        # 8000.67 - 16000.33 = -7999.66 → saldo_contra
        assert iva_data["saldo_contra"] == 7999.66

    def test_many_declarations_same_tenant(self, service):
        """Many declarations for the same tenant."""
        for m in range(1, 13):
            service.generate_monthly_iva(
                month=m, year=2024, tenant_id="t1",
            )

        decls = service.get_declaraciones_by_tenant("t1")
        assert len(decls) == 12

    def test_filter_by_type(self, service):
        """Filter declarations by type."""
        service.generate_monthly_iva(month=1, year=2024, tenant_id="t1")
        service.generate_provisional_isr(month=1, year=2024, tenant_id="t1")
        service.generate_annual_isr(year=2024, tenant_id="t1")

        iva_decls = service.get_declaraciones_by_tenant(
            "t1", tipo=DeclaracionType.IVA,
        )
        assert len(iva_decls) == 1
        assert iva_decls[0].tipo == DeclaracionType.IVA

    def test_update_status_not_found(self, service):
        """Update status for non-existent declaration returns None."""
        result = service.update_status("nonexistent", DeclaracionStatus.FILED)
        assert result is None
