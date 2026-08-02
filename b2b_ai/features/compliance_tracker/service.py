# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del Tracking de Obligaciones SAT
(compliance_tracker).

ComplianceService:
  - create_obligation       : crea una obligación fiscal.
  - get_obligations         : lista las obligaciones de un período (año/mes).
  - complete_obligation     : marca una obligación como cumplida.
  - get_overdue             : obligaciones vencidas de un tenant.
  - get_upcoming            : obligaciones próximas a vencer (ventana días).
  - generate_calendar       : calendario anual de obligaciones del tenant.
  - generate_alerts         : genera alertas UPDUE/OVERDUE/CRITICAL.
  - acknowledge_alert       : reconoce una alerta.

Almacenamiento en memoria (dict) con `_reset_state()` para tests, coherente
con el patrón bank_feeds / monthly_close / pilot_tracker. La firma permite
inyectar una capa de persistencia (db) sin romper la interfaz.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.compliance_tracker.models import (
    AlertType,
    ComplianceAlert,
    Obligation,
    ObligationStatus,
    ObligationType,
)
from b2b_ai.features.compliance_tracker.templates import generate_annual_template

# Umbrales de alerta (días antes del vencimiento para UPDUE / CRITICAL).
UPDUE_DAYS = 7
CRITICAL_OVERDUE_DAYS = 15

# ---------------------------------------------------------------------------
# Store en memoria (patrón bank_feeds / monthly_close / pilot_tracker)
# ---------------------------------------------------------------------------

_obligations: Dict[str, Obligation] = {}
_alerts: Dict[str, ComplianceAlert] = {}
# tenant_id -> [obligation_ids]
_tenant_obligations: Dict[str, List[str]] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _obligations.clear()
    _alerts.clear()
    _tenant_obligations.clear()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _today() -> date:
    return date.today()


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class ComplianceService:
    """Servicio de tracking de obligaciones SAT de un despacho."""

    def __init__(self, db: Any = None,
                 upcoming_days: int = UPDUE_DAYS,
                 critical_days: int = CRITICAL_OVERDUE_DAYS):
        self.db = db
        self.upcoming_days = upcoming_days
        self.critical_days = critical_days

    # ------------------------------------------------------------------
    # Creación / lectura
    # ------------------------------------------------------------------
    def create_obligation(
        self,
        tenant_id: str,
        obligation_type: ObligationType,
        due_date: date,
        notes: str = "",
    ) -> Obligation:
        """Crea una obligación fiscal para un tenant."""
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        obl = Obligation(
            tenant_id=tenant_id,
            obligation_type=obligation_type,
            due_date=due_date,
            notes=notes,
        )
        # Computa status inicial según fecha respecto a hoy.
        if obl.due_date < _today():
            obl.status = ObligationStatus.OVERDUE
        _obligations[obl.id] = obl
        _tenant_obligations.setdefault(tenant_id, []).append(obl.id)
        return obl

    def get_obligation(self, obligation_id: str) -> Obligation:
        obl = _obligations.get(obligation_id)
        if obl is None:
            raise KeyError(f"Obligación no encontrada: {obligation_id}")
        return obl

    def get_obligations(
        self,
        tenant_id: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> List[Obligation]:
        """Lista las obligaciones de un tenant, opcionalmente por año/mes."""
        if tenant_id:
            ids = _tenant_obligations.get(tenant_id, [])
            out = [_obligations[i] for i in ids if i in _obligations]
        else:
            out = list(_obligations.values())

        def _matches(o: Obligation) -> bool:
            if year is not None and o.due_date.year != year:
                return False
            if month is not None and o.due_date.month != month:
                return False
            return True

        out = [o for o in out if _matches(o)]
        return sorted(out, key=lambda o: o.due_date)

    def complete_obligation(self, obligation_id: str, user_id: str = "") -> Obligation:
        """Marca una obligación como cumplida."""
        obl = self.get_obligation(obligation_id)
        if obl.status == ObligationStatus.COMPLETED:
            raise ValueError(f"Obligación ya completada: {obligation_id}")
        obl.status = ObligationStatus.COMPLETED
        obl.completed_at = _utcnow()
        obl.completed_by = user_id or None
        return obl

    # ------------------------------------------------------------------
    # Vencidas / próximas
    # ------------------------------------------------------------------
    def get_overdue(self, tenant_id: str) -> List[Obligation]:
        """Obligaciones vencidas de un tenant (due_date < hoy, sin completar)."""
        today = _today()
        out = [
            o for o in self.get_obligations(tenant_id)
            if o.status != ObligationStatus.COMPLETED and o.due_date < today
        ]
        for o in out:
            if o.status == ObligationStatus.PENDING:
                o.status = ObligationStatus.OVERDUE
        return sorted(out, key=lambda o: o.due_date)

    def get_upcoming(self, tenant_id: str, days: int = 7) -> List[Obligation]:
        """Obligaciones próximas a vencer dentro de `days` días."""
        today = _today()
        horizon = today + timedelta(days=days)
        out = [
            o for o in self.get_obligations(tenant_id)
            if o.status != ObligationStatus.COMPLETED
            and today <= o.due_date <= horizon
        ]
        return sorted(out, key=lambda o: o.due_date)

    def generate_calendar(self, tenant_id: str, year: int) -> List[Obligation]:
        """Calendario anual de obligaciones del tenant (SAT).

        Crea las obligaciones del año si aún no existen para el tenant
        (idempotente por tipo+día), y las devuelve ordenadas por fecha.
        """
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        template = generate_annual_template(tenant_id, year)

        existing = self.get_obligations(tenant_id, year=year)
        existing_keys = {
            (o.obligation_type, o.due_date.isoformat()) for o in existing
        }

        created: List[Obligation] = []
        for t in template:
            key = (t.obligation_type, t.due_date.isoformat())
            if key in existing_keys:
                continue
            obl = self.create_obligation(
                tenant_id, t.obligation_type, t.due_date, notes=t.notes)
            created.append(obl)
            existing_keys.add(key)

        return self.get_obligations(tenant_id, year=year)

    # ------------------------------------------------------------------
    # Alertas
    # ------------------------------------------------------------------
    def generate_alerts(self, tenant_id: str) -> List[ComplianceAlert]:
        """Genera alertas para las obligaciones del tenant según su vencimiento.

        Reglas:
          - UPDUE   : due_date dentro de `upcoming_days` (próximas).
          - OVERDUE : due_date ya pasó.
          - CRITICAL: vencida hace más de `critical_days`.
        Devuelve las alertas creadas en esta llamada.
        """
        today = _today()
        created: List[ComplianceAlert] = []
        obligations = self.get_obligations(tenant_id)

        for o in obligations:
            if o.status == ObligationStatus.COMPLETED:
                continue
            delta = (o.due_date - today).days

            if delta < 0:
                # Vencida.
                alert_type = AlertType.OVERDUE
                if -delta > self.critical_days:
                    alert_type = AlertType.CRITICAL
            elif delta <= self.upcoming_days:
                alert_type = AlertType.UPDUE
            else:
                continue  # fuera de la ventana de alerta

            alert = ComplianceAlert(
                tenant_id=tenant_id,
                obligation_id=o.id,
                alert_type=alert_type,
                sent_at=_utcnow(),
                acknowledged=False,
            )
            _alerts[alert.id] = alert
            created.append(alert)
        return created

    def list_alerts(self, tenant_id: str, acknowledged: Optional[bool] = None) -> List[ComplianceAlert]:
        """Lista las alertas de un tenant (opcionalmente filtradas)."""
        out = [a for a in _alerts.values() if a.tenant_id == tenant_id]
        if acknowledged is not None:
            out = [a for a in out if a.acknowledged == acknowledged]
        return sorted(out, key=lambda a: a.sent_at or datetime.min, reverse=True)

    def acknowledge_alert(self, alert_id: str) -> ComplianceAlert:
        """Marca una alerta como reconocida."""
        alert = _alerts.get(alert_id)
        if alert is None:
            raise KeyError(f"Alerta no encontrada: {alert_id}")
        alert.acknowledged = True
        return alert
