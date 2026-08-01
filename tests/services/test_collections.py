# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/collections.py — collections manager."""
import pytest
from datetime import date
from b2b_ai.services.collections import (
    age_bucket, days_overdue, reminder_stage, CollectionsManager,
    _parse_date, _dec,
)


class TestAgeBucket:
    def test_not_overdue(self):
        assert age_bucket(0) == "0-30"
        assert age_bucket(-5) == "0-30"

    def test_1_to_30(self):
        assert age_bucket(15) == "0-30"
        assert age_bucket(30) == "0-30"

    def test_31_to_60(self):
        assert age_bucket(31) == "31-60"
        assert age_bucket(60) == "31-60"

    def test_61_to_90(self):
        assert age_bucket(61) == "61-90"
        assert age_bucket(90) == "61-90"

    def test_90_plus(self):
        assert age_bucket(91) == "90+"
        assert age_bucket(200) == "90+"

    def test_invalid_input(self):
        assert age_bucket("abc") == "0-30"
        assert age_bucket(None) == "0-30"


class TestDaysOverdue:
    def test_basic(self):
        d = days_overdue("2026-07-01", today=date(2026, 7, 10))
        assert d == 9

    def test_not_yet_due(self):
        d = days_overdue("2026-07-20", today=date(2026, 7, 10))
        assert d < 0

    def test_none_date(self):
        d = days_overdue(None)
        assert d == 0


class TestParseDate:
    def test_iso(self):
        assert _parse_date("2026-07-03") == date(2026, 7, 3)

    def test_slash_format(self):
        assert _parse_date("03/07/2026") == date(2026, 7, 3)

    def test_date_object(self):
        assert _parse_date(date(2026, 7, 3)) == date(2026, 7, 3)

    def test_none(self):
        assert _parse_date(None) is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None


class TestDec:
    def test_normal(self):
        assert _dec("100.50") is not None

    def test_none(self):
        assert _dec(None) is None

    def test_empty(self):
        assert _dec("") is None

    def test_with_dollar(self):
        assert _dec("$500.00") is not None


class TestReminderStage:
    def test_no_reminder_today(self):
        stage = reminder_stage("2026-07-03", today=date(2026, 7, 2))
        assert stage is None

    def test_none_date(self):
        assert reminder_stage(None) is None


class TestCollectionsManager:
    def setup_method(self):
        self.mgr = CollectionsManager()

    def test_analyze_basic(self):
        invoices = [
            {"factura_id": "F1", "monto": 1000, "fecha_vencimiento": "2026-07-01",
             "nombre_empresa": "ACME"},
        ]
        r = self.mgr.analyze(invoices, today=date(2026, 7, 15))
        assert r["total_invoices"] == 1
        assert float(r["total_monto"]) == 1000

    def test_analyze_empty(self):
        r = self.mgr.analyze([])
        assert r["total_invoices"] == 0

    def test_collectability_score(self):
        inv = {"factura_id": "F1", "monto": 1000, "fecha_vencimiento": "2026-07-01"}
        score = self.mgr.collectability_score(inv, dias_vencido=15)
        assert 0 <= score <= 1

    def test_score_with_history_pagado(self):
        inv = {"factura_id": "F1"}
        history = [{"respuesta": "pagado"}]
        score = self.mgr.collectability_score(inv, dias_vencido=60, history=history)
        assert score == 1.0

    def test_score_with_history_promesa(self):
        inv = {"factura_id": "F1"}
        history = [{"respuesta": "promesa_pago"}]
        score = self.mgr.collectability_score(inv, dias_vencido=15, history=history)
        assert score > 0.75

    def test_build_reminder_email(self):
        inv = {"factura_id": "F1", "monto": 1000, "nombre_empresa": "ACME",
               "fecha_vencimiento": "2026-07-01"}
        r = self.mgr.build_reminder(inv, "recordatorio_formal", "email",
                                     today=date(2026, 7, 8))
        assert r["channel"] == "email"
        assert "subject" in r

    def test_build_reminder_whatsapp(self):
        inv = {"factura_id": "F1", "monto": 1000, "nombre_empresa": "ACME",
               "fecha_vencimiento": "2026-07-01"}
        r = self.mgr.build_reminder(inv, "recordatorio_formal", "whatsapp",
                                     today=date(2026, 7, 8))
        assert r["channel"] == "whatsapp"
        assert "whatsapp" in r

    def test_send_reminder_no_db(self):
        inv = {"factura_id": "F1", "monto": 1000, "nombre_empresa": "ACME",
               "fecha_vencimiento": "2026-07-01"}
        r = self.mgr.send_reminder(inv, "recordatorio_formal", "email",
                                    today=date(2026, 7, 8))
        assert r["sent"] is False

    def test_register_response_no_db(self):
        assert self.mgr.register_response("F1", "pagado") is None

    def test_sync_outstanding_no_db(self):
        assert self.mgr.sync_outstanding([]) == 0
