# -*- coding: utf-8 -*-
"""test_vencimientos_expert.py — Expert-level tests for Vencimientos module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.vencimientos.service import VencimientosService
from b2b_ai.features.vencimientos.models import (
    Deadline, Escalation, EstadoVencimiento, PrioridadVencimiento, NivelEscalamiento,
)
from b2b_ai.features.vencimientos.validators import validate_date, validate_date_range_venc, validate_priority
from b2b_ai.features.compliance import sanitize_string, mask_rfc, encode_output


class TestIdempotency:
    def test_service_init_idempotent(self):
        s1 = VencimientosService()
        s2 = VencimientosService()
        assert len(s1._deadlines) == len(s2._deadlines) == 0

    def test_calculate_deadlines_returns_consistent_count(self):
        svc = VencimientosService()
        d1 = svc.calculate_deadlines("t1", month=1, year=2024)
        d2 = svc.calculate_deadlines("t1", month=1, year=2024)
        assert len(d1) == len(d2) == 4


class TestAuditTrail:
    def test_log_audit(self):
        svc = VencimientosService()
        entry = svc.log_audit(user="u1", action="escalate", module="vencimientos", result="ok")
        assert entry.action == "escalate"


class TestInputSanitization:
    def test_encode_output(self):
        assert "&lt;" in encode_output("<b>test</b>")

    def test_sanitize_string(self):
        assert sanitize_string("  data  ") == "data"


class TestErrorHandling:
    def test_mark_completed_not_found(self):
        svc = VencimientosService()
        result = svc.mark_completed("nonexistent")
        assert result is False

    def test_escalate_overdue(self):
        svc = VencimientosService()
        deadlines = svc.calculate_deadlines("t1", month=1, year=2023)
        escalation = svc.escalate(deadlines[0])
        assert escalation.level == NivelEscalamiento.NIVEL_4


class TestTenantIsolation:
    def test_get_summary_filtered(self):
        svc = VencimientosService()
        svc.calculate_deadlines("t1", month=1, year=2024)
        svc.calculate_deadlines("t2", month=1, year=2024)
        summary = svc.get_summary("t1")
        assert summary.total == 4


class TestEdgeCases:
    def test_check_overdue_empty(self):
        svc = VencimientosService()
        assert svc.check_overdue("t1") == []

    def test_get_upcoming_empty(self):
        svc = VencimientosService()
        assert svc.get_upcoming("t1") == []

    def test_get_all_deadlines_empty(self):
        svc = VencimientosService()
        assert svc.get_all_deadlines("t1") == []

    def test_mark_completed_proof(self):
        svc = VencimientosService()
        deadlines = svc.calculate_deadlines("t1", month=1, year=2024)
        result = svc.mark_completed(deadlines[0].id, proof="https://proof.com/doc.pdf")
        assert result is True

    def test_priority_calculation(self):
        svc = VencimientosService()
        assert svc._calculate_priority(-1) == PrioridadVencimiento.CRITICA
        assert svc._calculate_priority(0) == PrioridadVencimiento.CRITICA
        assert svc._calculate_priority(2) == PrioridadVencimiento.ALTA
        assert svc._calculate_priority(5) == PrioridadVencimiento.MEDIA
        assert svc._calculate_priority(15) == PrioridadVencimiento.BAJA


class TestConcurrentAccess:
    def test_concurrent_calculate(self):
        svc = VencimientosService()
        results = []
        def run():
            results.append(svc.calculate_deadlines("t1", month=1, year=2024))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5


class TestDataValidation:
    def test_deadline_model_construction(self):
        d = Deadline(tipo="ISR", fecha_limite="2024-02-17")
        assert d.tipo == "ISR"
        assert d.prioridad == PrioridadVencimiento.MEDIA

    def test_deadline_model_bad_date(self):
        with pytest.raises(Exception):
            Deadline(tipo="ISR", fecha_limite="bad-date")


class TestOutputVerification:
    def test_summary_structure(self):
        svc = VencimientosService()
        svc.calculate_deadlines("t1", month=1, year=2024)
        summary = svc.get_summary("t1")
        assert summary.total == 4
        assert summary.pendientes == 4


class TestRetryLogic:
    def test_escalation_notes(self):
        svc = VencimientosService()
        deadlines = svc.calculate_deadlines("t1", month=1, year=2024)
        esc = svc.escalate(deadlines[0])
        assert "Escalamiento automático" in esc.notes
