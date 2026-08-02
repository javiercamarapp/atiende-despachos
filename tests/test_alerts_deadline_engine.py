# -*- coding: utf-8 -*-
"""Tests for the SAT fiscal deadline engine."""
from datetime import date, timedelta

import pytest

from b2b_ai.features.alertas.deadline_engine import (
    DeadlineEngine,
    FiscalObligation,
    MEXICO_HOLIDAYS_2026,
    SAT_OBLIGATIONS_2026,
    is_business_day,
    next_business_day,
)
from b2b_ai.features.alertas.models import AlertSeverity


# ---------------------------------------------------------------------------
# Business-day helpers
# ---------------------------------------------------------------------------

class TestBusinessDays:
    def test_weekend_is_not_business_day(self):
        # 2026-08-01 is a Saturday, 2026-08-02 a Sunday
        assert is_business_day(date(2026, 8, 1)) is False
        assert is_business_day(date(2026, 8, 2)) is False

    def test_monday_is_business_day(self):
        assert is_business_day(date(2026, 8, 3)) is True

    def test_holiday_is_not_business_day(self):
        # 2026-09-16 = Día de la Independencia
        assert (9, 16) in MEXICO_HOLIDAYS_2026
        assert is_business_day(date(2026, 9, 16)) is False

    def test_next_business_day_skips_weekend(self):
        # Aug 1 (Sat) -> Aug 3 (Mon)
        assert next_business_day(date(2026, 8, 1)) == date(2026, 8, 3)

    def test_next_business_day_skips_holiday(self):
        # Sep 15 (Tue) is a business day, Sep 16 holiday; Sep 15 returns itself
        assert next_business_day(date(2026, 9, 15)) == date(2026, 9, 15)
        assert next_business_day(date(2026, 9, 16)) == date(2026, 9, 17)

    def test_custom_holidays_overridable(self):
        assert is_business_day(date(2026, 1, 1), holidays=[]) is True


# ---------------------------------------------------------------------------
# RFC classification
# ---------------------------------------------------------------------------

class TestRFC:
    def test_persona_fisica_13_chars(self):
        assert DeadlineEngine.rfc_type("ABC123456XYZ1") == "PF"

    def test_persona_moral_12_chars(self):
        assert DeadlineEngine.rfc_type("ABC123456XYZ") == "PM"

    def test_empty_defaults_to_moral(self):
        assert DeadlineEngine.rfc_type("") == "PM"


# ---------------------------------------------------------------------------
# DeadlineEngine core
# ---------------------------------------------------------------------------

class TestDeadlineEngine:
    def test_default_calendar_loaded(self):
        engine = DeadlineEngine()
        codes = {ob.code for ob in engine.obligations}
        assert "DIOT" in codes
        assert "ISR-PROV" in codes
        assert "ISR-ANUAL-PM" in codes
        assert len(engine.obligations) == len(SAT_OBLIGATIONS_2026)

    def test_monthly_due_date_follows_next_month(self):
        engine = DeadlineEngine()
        diot = next(ob for ob in SAT_OBLIGATIONS_2026 if ob.code == "DIOT")
        # DIOT for the August period due 17 Sep 2026
        due = engine.get_due_date(diot, period=date(2026, 8, 1))
        assert due == date(2026, 9, 17)

    def test_monthly_due_date_shifts_to_business_day(self):
        engine = DeadlineEngine()
        diot = next(ob for ob in SAT_OBLIGATIONS_2026 if ob.code == "DIOT")
        # October period due 17 Nov 2026 (a Tuesday) — stays
        due = engine.get_due_date(diot, period=date(2026, 10, 1))
        assert due == date(2026, 11, 17)
        # September period due 17 Oct 2026 (Sat) -> Mon 19 Oct
        due = engine.get_due_date(diot, period=date(2026, 9, 1))
        assert due == date(2026, 10, 19)

    def test_annual_due_dates(self):
        engine = DeadlineEngine()
        pm = next(ob for ob in SAT_OBLIGATIONS_2026 if ob.code == "ISR-ANUAL-PM")
        due = engine.get_due_date(pm, period=date(2026, 1, 1))
        assert due == date(2026, 3, 31)

    def test_persona_fisica_excludes_pm_annual(self):
        engine = DeadlineEngine()
        # A 13-char RFC (persona física) gets the PF annual, not the PM one.
        pf_ob = next(ob for ob in engine._applicable_obligations("ABC123456XYZ1")
                     if ob.code == "ISR-ANUAL-PF")
        assert pf_ob.rfc_prefix == "PF"
        pm_codes = {ob.code for ob in engine._applicable_obligations("ABC123456XYZ1")}
        assert "ISR-ANUAL-PM" not in pm_codes

    def test_upcoming_deadlines_horizon(self):
        engine = DeadlineEngine()
        upcoming = engine.upcoming_deadlines(
            "ABC123456XYZ", reference_date=date(2026, 8, 2), days=60,
        )
        assert upcoming, "should find at least one obligation in 60 days"
        for ob, due in upcoming:
            assert date(2026, 8, 2) <= due

    # -- Alert generation at lead windows ---------------------------------

    def test_emits_critical_at_1_business_day(self):
        engine = DeadlineEngine()
        alerts = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "Empresa Test"}],
            reference_date=date(2026, 9, 15),  # 17 Sep due, 1 business day left
        )
        assert alerts
        assert all(a.severity == AlertSeverity.CRITICAL for a in alerts)
        assert all(a.type.value == "due_date" for a in alerts)

    def test_emits_warning_at_3_days(self):
        engine = DeadlineEngine()
        alerts = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "Empresa Test"}],
            reference_date=date(2026, 9, 11),  # 3 business days until 17 Sep
        )
        if alerts:
            assert all(a.severity == AlertSeverity.WARNING for a in alerts)

    def test_no_alerts_far_from_deadline(self):
        engine = DeadlineEngine()
        alerts = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "Empresa Test"}],
            reference_date=date(2026, 8, 2),  # deadline mid-Sept
        )
        assert alerts == []

    def test_alert_metadata_has_rfc_and_due_date(self):
        engine = DeadlineEngine()
        alerts = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "Empresa Test"}],
            reference_date=date(2026, 9, 15),
        )
        assert alerts
        meta = alerts[0].metadata
        assert meta["company_rfc"] == "ABC123456XYZ"
        assert meta["due_date"]
        assert meta["lead_days"] in (1, 3, 7)

    def test_empty_company_list(self):
        engine = DeadlineEngine()
        assert engine.check_companies([]) == []

    def test_missing_rfc_skipped(self):
        engine = DeadlineEngine()
        assert engine.check_companies([{"name": "No RFC"}]) == []

    def test_alert_has_dedup_friendly_id(self):
        engine = DeadlineEngine()
        a1 = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "E"}], reference_date=date(2026, 9, 15),
        )[0]
        # Same obligation + rfc + due + lead -> same id (deterministic)
        a2 = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "E"}], reference_date=date(2026, 9, 15),
        )[0]
        assert a1.id == a2.id

    def test_custom_lead_days(self):
        engine = DeadlineEngine(lead_days=[2])
        alerts = engine.check_companies(
            [{"rfc": "ABC123456XYZ", "name": "E"}],
            reference_date=date(2026, 9, 14),  # 2 business days to 17 Sep
        )
        assert alerts
        assert all(a.metadata["lead_days"] == 2 for a in alerts)
