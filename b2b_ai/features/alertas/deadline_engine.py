# -*- coding: utf-8 -*-
"""
deadline_engine.py — SAT fiscal deadline engine.

Detects upcoming fiscal deadlines (SAT 2026) per company and generates
reminder alerts 7 / 3 / 1 business days before each due date.

Components:
  - SAT2026Calendar : loaded fiscal calendar (DIOT, monthly declarations,
    annual returns, provisional ISR, etc.) with non-working-day awareness.
  - DeadlineEngine   : computes per-company upcoming deadlines from an RFC
    and emits DeadlineAlert models at the configured lead windows.

This module is ADDITIVE to the existing alertas package. It reuses the
canonical Alert/AlertSeverity/AlertType models from .models but returns its
own DeadlineAlert structure for clarity. No existing module is modified.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from b2b_ai.features.alertas.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AlertType,
)

# ---------------------------------------------------------------------------
# Fiscal calendar (SAT 2026)
# ---------------------------------------------------------------------------

# Mexican federal statutory holidays observed as non-working days in 2026.
# Dates are (month, day). Weekends are handled separately.
MEXICO_HOLIDAYS_2026: List[tuple] = [
    (1, 1),    # Año Nuevo
    (2, 2),    # Día de la Constitución (observed)
    (3, 16),   # Natalicio de Benito Juárez (observed)
    (5, 1),    # Día del Trabajo
    (9, 16),   # Día de la Independencia
    (11, 16),  # Día de la Revolución (observed)
    (12, 25),  # Navidad
]


@dataclass(frozen=True)
class FiscalObligation:
    """A fiscal obligation with its recurring due-day rule.

    due_rule: (period, due_day)
        - period 'monthly'  → due every month on `due_day` (of the following
          period by default, controlled by `following_month`).
        - period 'annual'   → due once a year on month=`due_month`,
          day=`due_day`.
    """
    code: str
    name: str
    period: str            # 'monthly' | 'annual'
    due_day: int
    due_month: Optional[int] = None   # required for 'annual'
    following_month: bool = True      # monthly obligations: due next month
    rfc_prefix: Optional[str] = None  # e.g. 'PD' for physical persons


# Official SAT obligations applicable to Mexican taxpayers (2026).
SAT_OBLIGATIONS_2026: List[FiscalObligation] = [
    # DIOT — Declaración Informativa de Operaciones con Terceros (mensual)
    FiscalObligation(
        code="DIOT", name="Declaración Informativa de Operaciones con Terceros",
        period="monthly", due_day=17, following_month=True,
    ),
    # Declaración mensual de IVA
    FiscalObligation(
        code="IVA-MEN", name="Declaración mensual de IVA",
        period="monthly", due_day=17, following_month=True,
    ),
    # Pago provisional ISR (personas morales y físicas con actividad)
    FiscalObligation(
        code="ISR-PROV", name="Pago provisional de ISR",
        period="monthly", due_day=17, following_month=True,
    ),
    # Declaración anual de ISR — personas morales (marzo)
    FiscalObligation(
        code="ISR-ANUAL-PM", name="Declaración anual ISR (personas morales)",
        period="annual", due_day=31, due_month=3, rfc_prefix="PM",
    ),
    # Declaración anual de ISR — personas físicas (abril)
    FiscalObligation(
        code="ISR-ANUAL-PF", name="Declaración anual ISR (personas físicas)",
        period="annual", due_day=30, due_month=4,
        rfc_prefix="PF",
    ),
    # Declaración informativa anual (informative annual return)
    FiscalObligation(
        code="DIA", name="Declaración informativa anual",
        period="annual", due_day=15, due_month=2,
    ),
    # Retenciones de ISR / IVA (personas morales) — mensual
    FiscalObligation(
        code="RET-MEN", name="Declaración de retenciones (ISR/IVA)",
        period="monthly", due_day=17, following_month=True,
    ),
]


# ---------------------------------------------------------------------------
# Business-day helpers
# ---------------------------------------------------------------------------

def _holiday_set(holidays: Optional[List[tuple]] = None) -> set:
    """Build a set of (month, day) tuples for holiday lookup."""
    return set(holidays if holidays is not None else MEXICO_HOLIDAYS_2026)


def is_business_day(d: date, holidays: Optional[List[tuple]] = None) -> bool:
    """True if `d` is a working day (not weekend, not a listed holiday)."""
    if d.weekday() >= 5:  # Sat/Sun
        return False
    return (d.month, d.day) not in _holiday_set(holidays)


def next_business_day(d: date, holidays: Optional[List[tuple]] = None) -> date:
    """Return the first business day on or after `d`."""
    candidate = d
    while not is_business_day(candidate, holidays):
        candidate += timedelta(days=1)
    return candidate


# ---------------------------------------------------------------------------
# Deadline models
# ---------------------------------------------------------------------------

@dataclass
class DeadlineAlert:
    """A reminder for an upcoming fiscal deadline."""
    obligation_code: str
    obligation_name: str
    company_rfc: str
    company_name: str
    due_date: date
    days_until: int
    lead_days: int
    severity: AlertSeverity
    title: str
    message: str

    def to_alert(self) -> Alert:
        """Convert to the canonical Alert model used by the rest of the app."""
        return Alert(
            id=deadline_alert_id(self.obligation_code, self.company_rfc,
                                 self.due_date, self.lead_days),
            rule_id=f"deadline:{self.obligation_code}",
            rule_name=f"Deadline {self.obligation_code}",
            type=AlertType.DUE_DATE,
            severity=self.severity,
            status=AlertStatus.ACTIVE,
            title=self.title,
            message=self.message,
            entity_type="deadline",
            entity_id=self.obligation_code,
            tenant_id=None,
            metadata={
                "company_rfc": self.company_rfc,
                "company_name": self.company_name,
                "due_date": self.due_date.isoformat(),
                "days_until": self.days_until,
                "lead_days": self.lead_days,
                "obligation_code": self.obligation_code,
            },
        )


def deadline_alert_id(obligation_code: str, rfc: str, due: date,
                      lead_days: int) -> str:
    """Deterministic, dedup-friendly id for a deadline reminder."""
    raw = f"deadline:{obligation_code}:{rfc}:{due.isoformat()}:lead{lead_days}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# DeadlineEngine
# ---------------------------------------------------------------------------

class DeadlineEngine:
    """Compute upcoming SAT deadlines for companies and emit reminder alerts.

    Usage
    -----
        engine = DeadlineEngine()
        alerts = engine.check_companies([{...company records...}],
                                        reference_date=date(2026, 8, 2))
    """

    def __init__(
        self,
        obligations: Optional[List[FiscalObligation]] = None,
        holidays: Optional[List[tuple]] = None,
        lead_days: Optional[List[int]] = None,
    ):
        self.obligations = obligations or list(SAT_OBLIGATIONS_2026)
        self.holidays = holidays
        self.lead_days = sorted(lead_days if lead_days is not None else (7, 3, 1),
                               reverse=True)

    # -- RFC helpers -----------------------------------------------------

    @staticmethod
    def rfc_type(rfc: str) -> str:
        """Heuristic: classify an RFC as 'moral' (12 chars) or 'fisica' (13).

        Mexican RFCs: personas morales have 12 chars, físicas 13. Empty or
        malformed RFCs default to 'moral' (the generic case).
        """
        r = (rfc or "").strip().upper()
        if len(r) == 13:
            return "PF"
        return "PM"

    def _applicable_obligations(self, rfc: str) -> List[FiscalObligation]:
        """Filter obligations relevant to a given RFC."""
        rfc_type = self.rfc_type(rfc)
        out = []
        for ob in self.obligations:
            if ob.rfc_prefix is not None and ob.rfc_prefix != rfc_type:
                continue
            out.append(ob)
        return out

    # -- Calendar helpers --------------------------------------------------

    def _obligation_due_date(self, ob: FiscalObligation,
                             period: Optional[date] = None) -> date:
        """Compute the raw due date for an obligation.

        For monthly obligations, `period` is the month being declared; the
        due date falls on the 17th of the following month (or next business
        day). When `period` is omitted, the next occurrence relative to today
        is returned.
        """
        today = date.today()
        if ob.period == "annual":
            year = period.year if period else today.year
            due = date(year, ob.due_month or 1, ob.due_day)
            if due < today and (period is None):
                due = date(year + 1, ob.due_month or 1, ob.due_day)
            return due

        # monthly
        if period is not None:
            base_month = period.month + (1 if ob.following_month else 0)
            base_year = period.year
            if base_month > 12:
                base_month -= 12
                base_year += 1
            return date(base_year, base_month, ob.due_day)
        # next occurrence from today
        candidate = date(today.year, today.month, ob.due_day)
        if ob.following_month:
            candidate = date(today.year, today.month, 1) + timedelta(days=31)
            candidate = date(candidate.year, candidate.month, ob.due_day)
        if candidate <= today:
            candidate = date(today.year, today.month, 1) + timedelta(days=31)
            candidate = date(candidate.year, candidate.month, ob.due_day)
            if candidate <= today:
                candidate = date(today.year, today.month, 1) + timedelta(days=62)
                candidate = date(candidate.year, candidate.month, ob.due_day)
        return candidate

    def get_due_date(self, ob: FiscalObligation,
                     period: Optional[date] = None) -> date:
        """Public due-date resolver: returns the next business day due date."""
        raw = self._obligation_due_date(ob, period)
        return next_business_day(raw, self.holidays)

    def upcoming_deadlines(
        self,
        rfc: str,
        reference_date: Optional[date] = None,
        days: int = 30,
    ) -> List[tuple]:
        """Return [(obligation, due_date)] within the next `days` days."""
        ref = reference_date or date.today()
        horizon = ref + timedelta(days=days)
        results = []
        for ob in self._applicable_obligations(rfc):
            due = self.get_due_date(ob)
            # Skip obligations already past or beyond the horizon
            if due < ref or due > horizon:
                continue
            results.append((ob, due))
        results.sort(key=lambda x: x[1])
        return results

    # -- Alert generation ---------------------------------------------------

    def check_companies(
        self,
        companies: List[dict],
        reference_date: Optional[date] = None,
    ) -> List[Alert]:
        """Evaluate a batch of companies and emit deadline reminder alerts.

        Each company record: {rfc, name, ...}. For every obligation whose
        business-day due date is exactly `lead_days` business days ahead,
        a reminder alert is emitted.
        """
        ref = reference_date or date.today()
        alerts: List[Alert] = []

        for company in companies:
            rfc = str(company.get("rfc", "")).strip().upper()
            name = company.get("name") or company.get("company_name") or rfc
            if not rfc:
                continue

            # Collect all obligations for this RFC within a generous window
            all_due = []
            for ob in self._applicable_obligations(rfc):
                due = self.get_due_date(ob)
                if due >= ref:
                    all_due.append((ob, due))

            for ob, due in all_due:
                business_until = self._business_days_between(ref, due)
                for lead in self.lead_days:
                    if business_until == lead:
                        sev = self._severity_for_lead(lead, business_until)
                        alerts.append(self._build_alert(
                            ob, rfc, name, due, business_until, lead, sev,
                        ))
        return alerts

    def _business_days_between(self, start: date, end: date) -> int:
        """Number of business days from `start` (exclusive) to `end`."""
        count = 0
        d = start
        while d < end:
            d += timedelta(days=1)
            if is_business_day(d, self.holidays):
                count += 1
        return count

    @staticmethod
    def _severity_for_lead(lead: int, days_until: int) -> AlertSeverity:
        if lead == 1:
            return AlertSeverity.CRITICAL
        if lead == 3:
            return AlertSeverity.WARNING
        return AlertSeverity.INFO

    def _build_alert(self, ob: FiscalObligation, rfc: str, name: str,
                     due: date, days_until: int, lead: int,
                     sev: AlertSeverity) -> Alert:
        title = f"Vence {ob.name} en {days_until} día(s)"
        message = (
            f"{name} ({rfc}): la obligación fiscal «{ob.name}» "
            f"({ob.code}) vence el {due.isoformat()}. "
            f"Restan {days_until} día(s) hábiles."
        )
        return DeadlineAlert(
            obligation_code=ob.code,
            obligation_name=ob.name,
            company_rfc=rfc,
            company_name=name,
            due_date=due,
            days_until=days_until,
            lead_days=lead,
            severity=sev,
            title=title,
            message=message,
        ).to_alert()
