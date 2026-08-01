# -*- coding: utf-8 -*-
"""
engine.py — Alert Engine for B&B AI.

Evaluates alert rules against incoming data and produces Alert instances.

Supported rule types:
  - threshold  : fires when a value exceeds / meets a threshold
  - anomaly    : fires when a value is > N times the historical average
  - due_date   : fires when an invoice is due within N days (or overdue)
  - volume     : fires when a count exceeds a limit
  - reconciliation : fires on mismatch detection
  - custom     : user-defined via metadata['predicate']

Design decisions:
  - Pure function `evaluate_rules(data, rules)` — no side effects, easy to test.
  - AlertEngine wraps the store and provides a higher-level interface.
  - The engine is stateless; the store holds dedup and history.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Dict, List, Optional

from b2b_ai.features.alertas.models import (
    Alert,
    AlertHistory,
    AlertStatus,
    AlertType,
    AlertSeverity,
    AlertRule,
    RuleCondition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current time as ISO 8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _extract_value(data: dict, field_path: Optional[str], default: Any = None) -> Any:
    """Extract a value from a nested dict using a dot-separated path.

    Example: _extract_value({"invoice": {"total": 500}}, "invoice.total") → 500
    """
    if not field_path:
        return default
    keys = field_path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _compute_alert_id(rule_id: str, entity_type: str, entity_id: str) -> str:
    """Compute a deterministic alert ID for deduplication.

    Same rule + same entity → same ID → dedup works.
    """
    raw = f"{rule_id}:{entity_type}:{entity_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Rule evaluation functions
# ---------------------------------------------------------------------------

def _evaluate_threshold(data: dict, rule: AlertRule) -> bool:
    """Evaluate a threshold rule against data."""
    value = _extract_value(data, rule.field_path)
    if value is None:
        return False
    try:
        value = float(value)
    except (ValueError, TypeError):
        return False

    threshold = rule.threshold_value
    if threshold is None:
        return False

    cond = rule.condition
    if cond == RuleCondition.GT:
        return value > threshold
    elif cond == RuleCondition.GTE:
        return value >= threshold
    elif cond == RuleCondition.LT:
        return value < threshold
    elif cond == RuleCondition.LTE:
        return value <= threshold
    elif cond == RuleCondition.EQ:
        return abs(value - threshold) < 1e-9
    elif cond == RuleCondition.NEQ:
        return abs(value - threshold) >= 1e-9
    elif cond == RuleCondition.BETWEEN:
        upper = rule.threshold_value_max
        if upper is None:
            return False
        return threshold <= value <= upper
    return False


def _evaluate_anomaly(data: dict, rule: AlertRule, history: List[float]) -> bool:
    """Evaluate an anomaly rule.

    Fires when the current value exceeds `multiplier` times the
    historical average.  With no history, anomaly rules are skipped.
    """
    if not history:
        return False
    value = _extract_value(data, rule.field_path)
    if value is None:
        return False
    try:
        value = float(value)
    except (ValueError, TypeError):
        return False
    multiplier = rule.multiplier or 2.0
    avg = sum(history) / len(history)
    if avg == 0:
        return value > 0
    return value > avg * multiplier


def _evaluate_due_date(
    data: dict,
    rule: AlertRule,
    reference_date: Optional[str] = None,
) -> bool:
    """Evaluate a due-date rule.

    Fires when an invoice is due within `days_before_due` days
    or is already overdue.

    `reference_date` defaults to today (YYYY-MM-DD).
    `data` is expected to contain a date field at `rule.field_path`
    (default: 'fecha_vencimiento').
    """
    from datetime import date as _date

    field = rule.field_path or "fecha_vencimiento"
    due_str = _extract_value(data, field)
    if not due_str:
        return False

    try:
        due = _date.fromisoformat(str(due_str)[:10])
    except (ValueError, TypeError):
        return False

    if reference_date:
        try:
            ref = _date.fromisoformat(str(reference_date)[:10])
        except (ValueError, TypeError):
            ref = _date.today()
    else:
        ref = _date.today()

    days_until = (due - ref).days
    days_before = rule.days_before_due or 3
    # Fires if overdue (days_until < 0) or within the window
    return days_until <= days_before


def _evaluate_volume(data: dict, rule: AlertRule) -> bool:
    """Evaluate a volume rule.

    Fires when the count at `field_path` (default: 'count') exceeds
    `volume_limit`.
    """
    field = rule.field_path or "count"
    count = _extract_value(data, field)
    if count is None:
        return False
    try:
        count = int(count)
    except (ValueError, TypeError):
        return False
    limit = rule.volume_limit or 50
    return count > limit


def _evaluate_reconciliation(data: dict, rule: AlertRule) -> bool:
    """Evaluate a reconciliation mismatch rule.

    Fires when `data['mismatch_count']` > 0, or when `data['has_mismatch']`
    is truthy.
    """
    mismatch_count = _extract_value(data, "mismatch_count")
    has_mismatch = _extract_value(data, "has_mismatch")
    if mismatch_count is not None:
        try:
            return int(mismatch_count) > 0
        except (ValueError, TypeError):
            pass
    return bool(has_mismatch)


# ---------------------------------------------------------------------------
# Public evaluation function
# ---------------------------------------------------------------------------

def evaluate_rules(
    data: dict,
    rules: List[AlertRule],
    historical_values: Optional[Dict[str, List[float]]] = None,
    reference_date: Optional[str] = None,
) -> List[Alert]:
    """Evaluate a list of rules against the given data dict.

    Parameters
    ----------
    data : dict
        The input data to evaluate (invoice data, reconciliation results, etc.)
    rules : list[AlertRule]
        Active rules to evaluate.
    historical_values : dict, optional
        Map of field_path → list of historical float values (for anomaly detection).
    reference_date : str, optional
        Reference date for due-date calculations (YYYY-MM-DD).

    Returns
    -------
    list[Alert]
        Alerts that fired.
    """
    alerts: List[Alert] = []
    now = _now_iso()

    for rule in rules:
        # Auto-convert dict to AlertRule if needed
        if isinstance(rule, dict):
            try:
                rule = AlertRule(**rule)
            except Exception:
                continue

        if not rule.enabled:
            continue

        fired = False
        rule_type = rule.type

        if rule_type == AlertType.THRESHOLD:
            fired = _evaluate_threshold(data, rule)
        elif rule_type == AlertType.ANOMALY:
            history = (historical_values or {}).get(rule.field_path or "", [])
            fired = _evaluate_anomaly(data, rule, history)
        elif rule_type == AlertType.DUE_DATE:
            fired = _evaluate_due_date(data, rule, reference_date=reference_date)
        elif rule_type == AlertType.VOLUME:
            fired = _evaluate_volume(data, rule)
        elif rule_type == AlertType.RECONCILIATION:
            fired = _evaluate_reconciliation(data, rule)
        elif rule_type == AlertType.CUSTOM:
            # Custom rules use a predicate function stored in metadata
            predicate_id = rule.metadata.get("predicate_id")
            if predicate_id and _CUSTOM_PREDICATES.get(predicate_id):
                fired = _CUSTOM_PREDICATES[predicate_id](data, rule)
        else:
            continue

        if not fired:
            continue

        # Build the alert
        value = _extract_value(data, rule.field_path) if rule.field_path else None
        try:
            value_float = float(value) if value is not None else None
        except (ValueError, TypeError):
            value_float = None

        entity_type = data.get("entity_type", rule.metadata.get("entity_type", ""))
        entity_id = str(data.get("entity_id", rule.metadata.get("entity_id", "")))

        alert_id = _compute_alert_id(
            rule.id or rule.name, entity_type, entity_id,
        )

        message = rule.message_template or f"Alert: {rule.name} triggered"
        if value is not None:
            message = message.replace("{value}", str(value))
        if rule.threshold_value is not None:
            message = message.replace("{threshold}", str(rule.threshold_value))
        if entity_id:
            message = message.replace("{entity}", entity_id)

        alerts.append(
            Alert(
                id=alert_id,
                rule_id=rule.id,
                rule_name=rule.name,
                type=rule.type,
                severity=rule.severity,
                status=AlertStatus.ACTIVE,
                title=rule.name,
                message=message,
                entity_type=entity_type or None,
                entity_id=entity_id or None,
                tenant_id=rule.tenant_id,
                value=value_float,
                threshold=rule.threshold_value,
                metadata={"rule_metadata": rule.metadata},
                created_at=now,
            )
        )

    return alerts


# ---------------------------------------------------------------------------
# Custom predicate registry
# ---------------------------------------------------------------------------

_CUSTOM_PREDICATES: Dict[str, Callable[[dict, AlertRule], bool]] = {}


def register_custom_predicate(predicate_id: str, fn: Callable[[dict, AlertRule], bool]):
    """Register a custom predicate for CUSTOM rule type."""
    _CUSTOM_PREDICATES[predicate_id] = fn


# ---------------------------------------------------------------------------
# AlertEngine (high-level wrapper)
# ---------------------------------------------------------------------------

class AlertEngine:
    """High-level alert engine that wraps rule evaluation and the store.

    Usage:
        engine = AlertEngine(store=my_store)
        alerts = engine.evaluate_rules(data, rules)
        engine.store.save_alerts(alerts)
    """

    def __init__(self, store: Optional[Any] = None):
        from b2b_ai.features.alertas.store import AlertStore
        self.store = store or AlertStore()

    def evaluate(
        self,
        data: dict,
        rules: List[AlertRule],
        historical_values: Optional[Dict[str, List[float]]] = None,
        reference_date: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> List[Alert]:
        """Evaluate rules and save resulting alerts to the store.

        Returns only NEW alerts (dedup is applied by the store).
        """
        # Filter rules by tenant if needed
        if tenant_id is not None:
            rules = [r for r in rules if r.tenant_id is None or r.tenant_id == tenant_id]

        raw_alerts = evaluate_rules(
            data, rules,
            historical_values=historical_values,
            reference_date=reference_date,
        )
        # Ensure tenant_id is set
        if tenant_id is not None:
            for a in raw_alerts:
                if a.tenant_id is None:
                    a.tenant_id = tenant_id

        new_alerts = self.store.save_alerts(raw_alerts)
        return new_alerts

    def evaluate_invoices(
        self,
        invoices: List[dict],
        rules: List[AlertRule],
        historical_amounts: Optional[List[float]] = None,
        tenant_id: Optional[int] = None,
    ) -> List[Alert]:
        """Evaluate rules against a batch of invoices.

        Each invoice is evaluated independently.
        """
        all_alerts: List[Alert] = []
        hist_map = {}
        if historical_amounts:
            hist_map["total"] = historical_amounts

        for invoice in invoices:
            # Ensure entity info
            invoice.setdefault("entity_type", "invoice")
            invoice.setdefault("entity_id", invoice.get("folio_fiscal", ""))
            invoice.setdefault("tenant_id", tenant_id)

            alerts = self.evaluate(
                invoice, rules,
                historical_values=hist_map,
                tenant_id=tenant_id,
            )
            all_alerts.extend(alerts)

        return all_alerts

    def evaluate_reconciliation(
        self,
        reconciliation_data: dict,
        rules: List[AlertRule],
        tenant_id: Optional[int] = None,
    ) -> List[Alert]:
        """Evaluate reconciliation mismatch rules."""
        reconciliation_data.setdefault("entity_type", "reconciliation")
        reconciliation_data.setdefault(
            "entity_id",
            reconciliation_data.get("session_id", "unknown"),
        )
        return self.evaluate(
            reconciliation_data, rules,
            tenant_id=tenant_id,
        )

    def evaluate_volume(
        self,
        volume_data: dict,
        rules: List[AlertRule],
        tenant_id: Optional[int] = None,
    ) -> List[Alert]:
        """Evaluate volume-based rules."""
        volume_data.setdefault("entity_type", "volume")
        volume_data.setdefault("entity_id", "aggregate")
        return self.evaluate(
            volume_data, rules,
            tenant_id=tenant_id,
        )
