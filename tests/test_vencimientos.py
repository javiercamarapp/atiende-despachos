# -*- coding: utf-8 -*-
"""Tests for the Vencimientos module."""
import pytest
from datetime import datetime, timedelta
from b2b_ai.features.vencimientos.models import (
    Deadline,
    Escalation,
    EstadoVencimiento,
    NivelEscalamiento,
    PrioridadVencimiento,
    VencimientoSummary,
)
from b2b_ai.features.vencimientos.service import VencimientosService
from b2b_ai.features.vencimientos.validators import (
    validate_date,
    validate_date_range_venc,
    validate_priority,
)


# ---------------------------------------------------------------------------
# Validators tests
# ---------------------------------------------------------------------------

class TestValidateDate:
    def test_valid_date(self):
        ok, err = validate_date("2024-01-15")
        assert ok is True
        assert err == ""

    def test_invalid_format(self):
        ok, err = validate_date("15/01/2024")
        assert ok is False
        assert "inválido" in err

    def test_empty_date(self):
        ok, err = validate_date("")
        assert ok is False

    def test_invalid_day(self):
        ok, err = validate_date("2024-02-30")
        assert ok is False


class TestValidatePriority:
    def test_valid_priorities(self):
        for p in ["critica", "alta", "media", "baja"]:
            ok, err = validate_priority(p)
            assert ok is True

    def test_invalid_priority(self):
        ok, err = validate_priority("urgente")
        assert ok is False
        assert "inválida" in err


class TestValidateDateRange:
    def test_valid_range(self):
        ok, err = validate_date_range_venc("2024-01-01", "2024-01-31")
        assert ok is True

    def test_invalid_range(self):
        ok, err = validate_date_range_venc("2024-01-31", "2024-01-01")
        assert ok is False
        assert "posterior" in err

    def test_same_date(self):
        ok, err = validate_date_range_venc("2024-01-15", "2024-01-15")
        assert ok is True


# ---------------------------------------------------------------------------
# Models tests
# ---------------------------------------------------------------------------

class TestDeadline:
    def test_create_deadline(self):
        d = Deadline(
            tipo="ISR",
            fecha_limite="2024-02-17",
        )
        assert d.tipo == "ISR"
        assert d.fecha_limite == "2024-02-17"
        assert d.estado == EstadoVencimiento.PENDIENTE
        assert d.prioridad == PrioridadVencimiento.MEDIA

    def test_invalid_date_format(self):
        with pytest.raises(Exception):
            Deadline(tipo="ISR", fecha_limite="17/02/2024")


class TestEscalation:
    def test_create_escalation(self):
        e = Escalation(
            deadline_id="VENC-ISR-2024-02-abc",
            level=NivelEscalamiento.NIVEL_2,
            sent_at=datetime.now().isoformat(),
        )
        assert e.deadline_id == "VENC-ISR-2024-02-abc"
        assert e.level == NivelEscalamiento.NIVEL_2
        assert e.response is None


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestVencimientosService:
    def test_calculate_deadlines(self):
        service = VencimientosService()
        deadlines = service.calculate_deadlines(tenant_id="t1", month=1, year=2024)
        assert len(deadlines) == 4
        tipos = {d.tipo for d in deadlines}
        assert tipos == {"ISR", "IVA", "DIOT", "Nómina"}
        # All should have the same deadline date (Feb 17, 2024)
        for d in deadlines:
            assert d.fecha_limite == "2024-02-17"
            assert d.tenant_id == "t1"

    def test_check_overdue(self):
        service = VencimientosService()
        # Create a deadline in the past
        past_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        deadline = Deadline(
            id="VENC-PAST-001",
            tipo="ISR",
            fecha_limite=past_date,
            tenant_id="t1",
        )
        service._deadlines[deadline.id] = deadline

        overdue = service.check_overdue(tenant_id="t1")
        assert len(overdue) == 1
        assert overdue[0].estado == EstadoVencimiento.VENCIDO

    def test_escalate(self):
        service = VencimientosService()
        deadline = Deadline(
            id="VENC-TEST-001",
            tipo="IVA",
            fecha_limite=(datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
        )
        escalation = service.escalate(deadline)
        assert escalation.deadline_id == "VENC-TEST-001"
        assert escalation.level == NivelEscalamiento.NIVEL_1
        assert deadline.estado == EstadoVencimiento.ESCALADO

    def test_escalate_overdue(self):
        service = VencimientosService()
        deadline = Deadline(
            id="VENC-OVERDUE-001",
            tipo="ISR",
            fecha_limite=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        escalation = service.escalate(deadline)
        assert escalation.level == NivelEscalamiento.NIVEL_4

    def test_mark_completed(self):
        service = VencimientosService()
        deadline = Deadline(
            id="VENC-COMP-001",
            tipo="DIOT",
            fecha_limite="2024-02-17",
        )
        service._deadlines[deadline.id] = deadline

        result = service.mark_completed("VENC-COMP-001", proof="https://sat.gob.mx/comp")
        assert result is True
        assert deadline.estado == EstadoVencimiento.COMPLETADO
        assert deadline.comprobante_url == "https://sat.gob.mx/comp"

    def test_mark_completed_nonexistent(self):
        service = VencimientosService()
        result = service.mark_completed("nonexistent")
        assert result is False

    def test_get_upcoming(self):
        service = VencimientosService()
        # Create deadlines at various distances
        today = datetime.now()
        deadlines_data = [
            ("VENC-1", (today + timedelta(days=3)).strftime("%Y-%m-%d")),
            ("VENC-2", (today + timedelta(days=10)).strftime("%Y-%m-%d")),
            ("VENC-3", (today + timedelta(days=30)).strftime("%Y-%m-%d")),
        ]
        for did, fecha in deadlines_data:
            d = Deadline(id=did, tipo="ISR", fecha_limite=fecha, tenant_id="t1")
            service._deadlines[did] = d

        upcoming = service.get_upcoming(tenant_id="t1", days_ahead=7)
        assert len(upcoming) == 1
        assert upcoming[0].id == "VENC-1"

    def test_get_summary(self):
        service = VencimientosService()
        # Create some deadlines
        today = datetime.now()
        service._deadlines["d1"] = Deadline(
            id="d1", tipo="ISR", fecha_limite=(today + timedelta(days=5)).strftime("%Y-%m-%d"),
            estado=EstadoVencimiento.PENDIENTE, tenant_id="t1",
        )
        service._deadlines["d2"] = Deadline(
            id="d2", tipo="IVA", fecha_limite=(today + timedelta(days=10)).strftime("%Y-%m-%d"),
            estado=EstadoVencimiento.COMPLETADO, tenant_id="t1",
        )
        service._deadlines["d3"] = Deadline(
            id="d3", tipo="DIOT", fecha_limite=(today - timedelta(days=2)).strftime("%Y-%m-%d"),
            estado=EstadoVencimiento.VENCIDO, tenant_id="t1",
        )

        summary = service.get_summary(tenant_id="t1")
        assert summary.total == 3
        assert summary.pendientes == 1
        assert summary.completados == 1
        assert summary.vencidos == 1

    def test_get_all_deadlines(self):
        service = VencimientosService()
        service._deadlines["d1"] = Deadline(id="d1", tipo="ISR", fecha_limite="2024-02-17", tenant_id="t1")
        service._deadlines["d2"] = Deadline(id="d2", tipo="IVA", fecha_limite="2024-02-17", tenant_id="t2")

        all_d = service.get_all_deadlines()
        assert len(all_d) == 2

        t1_d = service.get_all_deadlines(tenant_id="t1")
        assert len(t1_d) == 1
