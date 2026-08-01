# -*- coding: utf-8 -*-
"""Tests for Deadline Management (Vencimientos) agent."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from b2b_ai.features.vencimientos.models import (
    DeadlineEstado,
    DeadlineTipo,
    EscalationEstado,
    EscalationLevel,
    Prioridad,
)
from b2b_ai.features.vencimientos.service import (
    acknowledge_deadline,
    calculate_deadlines,
    check_overdue,
    create_deadline,
    escalate,
    get_deadline,
    get_deadline_with_escalations,
    mark_completed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_date(days: int = 10) -> str:
    """Return a date string N days from now."""
    return (datetime.utcnow().date() + timedelta(days=days)).strftime("%Y-%m-%d")


def _past_date(days: int = 5) -> str:
    """Return a date string N days ago."""
    return (datetime.utcnow().date() - timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Tests: Create and retrieve deadlines
# ---------------------------------------------------------------------------

class TestDeadlineCreation:
    """Test creating and retrieving deadlines."""

    def test_create_deadline(self):
        d = create_deadline(
            tenant_id="tenant-1",
            tipo="iva",
            fecha_limite=_future_date(15),
            prioridad="alta",
            descripcion="IVA mensual junio",
        )
        assert d.id != ""
        assert d.tenant_id == "tenant-1"
        assert d.tipo == DeadlineTipo.IVA
        assert d.prioridad == Prioridad.ALTA
        assert d.estado == DeadlineEstado.PENDIENTE

    def test_get_deadline(self):
        d = create_deadline(
            tenant_id="tenant-2",
            tipo="isr",
            fecha_limite=_future_date(10),
        )
        found = get_deadline(d.id)
        assert found is not None
        assert found.id == d.id

    def test_get_nonexistent_deadline(self):
        found = get_deadline("nonexistent-id")
        assert found is None


# ---------------------------------------------------------------------------
# Tests: Calculate upcoming deadlines
# ---------------------------------------------------------------------------

class TestUpcomingDeadlines:
    """Test calculating upcoming deadlines within a date range."""

    def test_upcoming_within_30_days(self):
        tenant = "tenant-upcoming"
        create_deadline(
            tenant_id=tenant,
            tipo="iva",
            fecha_limite=_future_date(10),
            prioridad="alta",
        )
        create_deadline(
            tenant_id=tenant,
            tipo="isr",
            fecha_limite=_future_date(25),
        )
        create_deadline(
            tenant_id=tenant,
            tipo="diot",
            fecha_limite=_future_date(45),  # beyond 30 days
        )
        upcoming = calculate_deadlines(tenant, days_ahead=30)
        assert len(upcoming) == 2

    def test_upcoming_sorted_by_date(self):
        tenant = "tenant-sort"
        create_deadline(tenant_id=tenant, tipo="iva", fecha_limite=_future_date(20))
        create_deadline(tenant_id=tenant, tipo="isr", fecha_limite=_future_date(5))
        upcoming = calculate_deadlines(tenant, days_ahead=30)
        assert len(upcoming) == 2
        assert upcoming[0].fecha_limite <= upcoming[1].fecha_limite

    def test_upcoming_excludes_other_tenants(self):
        create_deadline(tenant_id="other-tenant", tipo="iva", fecha_limite=_future_date(5))
        upcoming = calculate_deadlines("my-tenant", days_ahead=30)
        assert len(upcoming) == 0


# ---------------------------------------------------------------------------
# Tests: Overdue detection
# ---------------------------------------------------------------------------

class TestOverdueDetection:
    """Test detection of overdue deadlines."""

    def test_overdue_detected(self):
        tenant = "tenant-overdue"
        create_deadline(
            tenant_id=tenant,
            tipo="iva",
            fecha_limite=_past_date(5),
        )
        overdue = check_overdue(tenant)
        assert len(overdue) == 1
        assert overdue[0].estado != DeadlineEstado.COMPLETADO

    def test_completed_not_overdue(self):
        tenant = "tenant-completed"
        d = create_deadline(
            tenant_id=tenant,
            tipo="iva",
            fecha_limite=_past_date(5),
        )
        mark_completed(d.id, proof="done")
        overdue = check_overdue(tenant)
        assert len(overdue) == 0

    def test_future_not_overdue(self):
        tenant = "tenant-future"
        create_deadline(
            tenant_id=tenant,
            tipo="iva",
            fecha_limite=_future_date(5),
        )
        overdue = check_overdue(tenant)
        assert len(overdue) == 0


# ---------------------------------------------------------------------------
# Tests: Escalation
# ---------------------------------------------------------------------------

class TestEscalation:
    """Test escalation notification progression."""

    def test_first_escalation_is_email(self):
        d = create_deadline(
            tenant_id="tenant-esc",
            tipo="iva",
            fecha_limite=_past_date(3),
        )
        esc = escalate(d)
        assert esc.level == EscalationLevel.EMAIL
        assert esc.estado == EscalationEstado.ENVIADO

    def test_second_escalation_is_whatsapp(self):
        d = create_deadline(
            tenant_id="tenant-esc2",
            tipo="iva",
            fecha_limite=_past_date(3),
        )
        escalate(d)  # email
        esc2 = escalate(d)  # whatsapp
        assert esc2.level == EscalationLevel.WHATSAPP

    def test_third_escalation_is_call(self):
        d = create_deadline(
            tenant_id="tenant-esc3",
            tipo="iva",
            fecha_limite=_past_date(3),
        )
        escalate(d)  # email
        escalate(d)  # whatsapp
        esc3 = escalate(d)  # call
        assert esc3.level == EscalationLevel.CALL

    def test_escalation_stays_at_max_level(self):
        d = create_deadline(
            tenant_id="tenant-esc4",
            tipo="iva",
            fecha_limite=_past_date(3),
        )
        escalate(d)  # email
        escalate(d)  # whatsapp
        escalate(d)  # call
        esc4 = escalate(d)  # still call
        assert esc4.level == EscalationLevel.CALL

    def test_escalation_updates_deadline_status(self):
        d = create_deadline(
            tenant_id="tenant-esc5",
            tipo="iva",
            fecha_limite=_past_date(3),
        )
        assert d.estado == DeadlineEstado.PENDIENTE
        escalate(d)
        assert d.estado == DeadlineEstado.ESCALADO


# ---------------------------------------------------------------------------
# Tests: Mark completed
# ---------------------------------------------------------------------------

class TestMarkCompleted:
    """Test marking deadlines as completed."""

    def test_mark_completed_with_proof(self):
        d = create_deadline(
            tenant_id="tenant-comp",
            tipo="iva",
            fecha_limite=_future_date(5),
        )
        result = mark_completed(d.id, proof="https://sat.gob.mx/comprobante/123")
        assert result is True
        assert d.estado == DeadlineEstado.COMPLETADO
        assert d.proof_url == "https://sat.gob.mx/comprobante/123"

    def test_mark_completed_without_proof(self):
        d = create_deadline(
            tenant_id="tenant-comp2",
            tipo="isr",
            fecha_limite=_future_date(5),
        )
        result = mark_completed(d.id)
        assert result is True
        assert d.estado == DeadlineEstado.COMPLETADO
        assert d.proof_url is None

    def test_mark_nonexistent_completed(self):
        result = mark_completed("nonexistent-id")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: Acknowledge
# ---------------------------------------------------------------------------

class TestAcknowledge:
    """Test acknowledging deadlines."""

    def test_acknowledge_moves_to_en_proceso(self):
        d = create_deadline(
            tenant_id="tenant-ack",
            tipo="iva",
            fecha_limite=_future_date(10),
        )
        result = acknowledge_deadline(d.id, responsable="Juan Pérez")
        assert result is True
        assert d.estado == DeadlineEstado.EN_PROCESO
        assert d.responsable == "Juan Pérez"

    def test_acknowledge_nonexistent(self):
        result = acknowledge_deadline("nonexistent-id")
        assert result is False
