# -*- coding: utf-8 -*-
"""Tests for the Intelligent Alerts Engine module."""
from __future__ import annotations
import pytest
from b2b_ai.features.alertas.models import (
    Alert, AlertConfig, AlertHistory, AlertRule, AlertSeverity, AlertStatus,
    AlertType, RuleCondition,
)
from b2b_ai.features.alertas.engine import (
    evaluate_rules, _evaluate_threshold, _evaluate_anomaly,
    _evaluate_due_date, _evaluate_volume, _evaluate_reconciliation,
    register_custom_predicate, AlertEngine,
)
from b2b_ai.features.alertas.store import AlertStore


# ── Model Tests ──

class TestAlertModels:
    def test_alert_rule_construction(self):
        r = AlertRule(name="test", type=AlertType.THRESHOLD)
        assert r.name == "test"
        assert r.enabled is True
        assert r.severity == AlertSeverity.WARNING

    def test_alert_rule_empty_id_becomes_none(self):
        r = AlertRule(id="", name="test", type=AlertType.THRESHOLD)
        assert r.id is None

    def test_alert_construction(self):
        a = Alert(title="Hi", message="msg")
        assert a.status == AlertStatus.ACTIVE
        assert a.severity == AlertSeverity.WARNING

    def test_alert_empty_id_becomes_none(self):
        a = Alert(id="", title="Hi")
        assert a.id is None

    def test_alert_config_defaults(self):
        c = AlertConfig()
        assert c.enabled is True
        assert c.max_alerts_per_hour == 100
        assert c.notify_channels == ["log"]

    def test_alert_history_construction(self):
        h = AlertHistory(alert_id="a1", action="created", timestamp="2025-01-01T00:00:00Z")
        assert h.alert_id == "a1"
        assert h.details == {}

    def test_severity_enum_values(self):
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"

    def test_alert_type_enum_values(self):
        assert AlertType.THRESHOLD.value == "threshold"
        assert AlertType.ANOMALY.value == "anomaly"
        assert AlertType.DUE_DATE.value == "due_date"


# ── Engine / Threshold Tests ──

class TestEngineThreshold:
    def _rule(self, **kwargs):
        defaults = dict(name="r1", type=AlertType.THRESHOLD, field_path="total",
                        condition=RuleCondition.GT, threshold_value=100)
        defaults.update(kwargs)
        return AlertRule(**defaults)

    def test_gt_triggers(self):
        data = {"total": 150}
        assert _evaluate_threshold(data, self._rule()) is True

    def test_gt_not_triggered(self):
        data = {"total": 50}
        assert _evaluate_threshold(data, self._rule()) is False

    def test_gte_equal(self):
        r = self._rule(condition=RuleCondition.GTE)
        assert _evaluate_threshold({"total": 100}, r) is True

    def test_lt_triggered(self):
        r = self._rule(condition=RuleCondition.LT)
        assert _evaluate_threshold({"total": 50}, r) is True

    def test_lte_equal(self):
        r = self._rule(condition=RuleCondition.LTE)
        assert _evaluate_threshold({"total": 100}, r) is True

    def test_eq(self):
        r = self._rule(condition=RuleCondition.EQ)
        assert _evaluate_threshold({"total": 100}, r) is True

    def test_neq(self):
        r = self._rule(condition=RuleCondition.NEQ)
        assert _evaluate_threshold({"total": 99}, r) is True

    def test_between(self):
        r = self._rule(condition=RuleCondition.BETWEEN, threshold_value=50, threshold_value_max=200)
        assert _evaluate_threshold({"total": 100}, r) is True
        assert _evaluate_threshold({"total": 250}, r) is False

    def test_between_no_max(self):
        r = self._rule(condition=RuleCondition.BETWEEN, threshold_value=50)
        assert _evaluate_threshold({"total": 100}, r) is False

    def test_missing_field(self):
        assert _evaluate_threshold({}, self._rule()) is False

    def test_non_numeric_value(self):
        assert _evaluate_threshold({"total": "abc"}, self._rule()) is False

    def test_disabled_rule_skipped(self):
        r = self._rule(enabled=False)
        data = {"total": 150}
        alerts = evaluate_rules(data, [r])
        assert len(alerts) == 0


# ── Engine / Anomaly Tests ──

class TestEngineAnomaly:
    def test_anomaly_no_history(self):
        r = AlertRule(name="a", type=AlertType.ANOMALY, field_path="val", multiplier=2.0)
        assert _evaluate_anomaly({"val": 100}, r, []) is False

    def test_anomaly_fires(self):
        r = AlertRule(name="a", type=AlertType.ANOMALY, field_path="val", multiplier=2.0)
        assert _evaluate_anomaly({"val": 100}, r, [10, 10, 10]) is True

    def test_anomaly_not_fired(self):
        r = AlertRule(name="a", type=AlertType.ANOMALY, field_path="val", multiplier=2.0)
        assert _evaluate_anomaly({"val": 10}, r, [10, 10, 10]) is False

    def test_anomaly_zero_average(self):
        r = AlertRule(name="a", type=AlertType.ANOMALY, field_path="val", multiplier=2.0)
        assert _evaluate_anomaly({"val": 5}, r, [0, 0, 0]) is True


# ── Engine / Due Date Tests ──

class TestEngineDueDate:
    def test_overdue(self):
        r = AlertRule(name="d", type=AlertType.DUE_DATE, field_path="fecha", days_before_due=3)
        assert _evaluate_due_date({"fecha": "2025-01-01"}, r, reference_date="2025-01-10") is True

    def test_within_window(self):
        r = AlertRule(name="d", type=AlertType.DUE_DATE, field_path="fecha", days_before_due=5)
        assert _evaluate_due_date({"fecha": "2025-01-08"}, r, reference_date="2025-01-05") is True

    def test_not_due(self):
        r = AlertRule(name="d", type=AlertType.DUE_DATE, field_path="fecha", days_before_due=3)
        assert _evaluate_due_date({"fecha": "2025-02-01"}, r, reference_date="2025-01-01") is False


# ── Engine / Volume + Reconciliation Tests ──

class TestEngineVolumeReconciliation:
    def test_volume_fires(self):
        r = AlertRule(name="v", type=AlertType.VOLUME, field_path="count", volume_limit=5)
        assert _evaluate_volume({"count": 10}, r) is True

    def test_volume_not_fired(self):
        r = AlertRule(name="v", type=AlertType.VOLUME, field_path="count", volume_limit=5)
        assert _evaluate_volume({"count": 3}, r) is False

    def test_reconciliation_mismatch(self):
        r = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert _evaluate_reconciliation({"mismatch_count": 5}, r) is True

    def test_reconciliation_no_mismatch(self):
        r = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert _evaluate_reconciliation({"mismatch_count": 0}, r) is False

    def test_reconciliation_has_mismatch_flag(self):
        r = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert _evaluate_reconciliation({"has_mismatch": True}, r) is True


# ── Engine / evaluate_rules integration ──

class TestEvaluateRules:
    def test_multiple_rules(self):
        rules = [
            AlertRule(name="r1", type=AlertType.THRESHOLD, field_path="total",
                      condition=RuleCondition.GT, threshold_value=100),
            AlertRule(name="r2", type=AlertType.VOLUME, field_path="count",
                      volume_limit=5),
        ]
        data = {"total": 150, "count": 10}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 2

    def test_no_alerts_when_none_fire(self):
        rules = [AlertRule(name="r1", type=AlertType.THRESHOLD, field_path="total",
                           condition=RuleCondition.GT, threshold_value=1000)]
        alerts = evaluate_rules({"total": 10}, rules)
        assert len(alerts) == 0

    def test_message_template_substitution(self):
        r = AlertRule(name="r1", type=AlertType.THRESHOLD, field_path="total",
                      condition=RuleCondition.GT, threshold_value=100,
                      message_template="Value {value} > {threshold} for {entity}")
        alerts = evaluate_rules({"total": 200, "entity_id": "INV-1"}, [r])
        assert len(alerts) == 1
        assert "200" in alerts[0].message
        assert "INV-1" in alerts[0].message


# ── Store Tests ──

class TestAlertStore:
    def setup_method(self):
        self.store = AlertStore()

    def test_save_and_get(self):
        a = Alert(id="a1", title="Test")
        new = self.store.save_alerts([a])
        assert len(new) == 1
        got = self.store.get_alert("a1")
        assert got is not None
        assert got.title == "Test"

    def test_deduplication(self):
        a = Alert(id="a1", title="Test")
        self.store.save_alerts([a])
        new = self.store.save_alerts([a])
        assert len(new) == 0

    def test_list_with_filter(self):
        self.store.save_alerts([Alert(id="a1", title="T1", severity=AlertSeverity.INFO)])
        self.store.save_alerts([Alert(id="a2", title="T2", severity=AlertSeverity.CRITICAL)])
        info = self.store.list_alerts(severity=AlertSeverity.INFO)
        assert len(info) == 1
        assert info[0].severity == AlertSeverity.INFO

    def test_acknowledge(self):
        self.store.save_alerts([Alert(id="a1", title="T")])
        result = self.store.acknowledge_alert("a1", user="admin")
        assert result.status == AlertStatus.ACKNOWLEDGED

    def test_dismiss(self):
        self.store.save_alerts([Alert(id="a1", title="T")])
        result = self.store.dismiss_alert("a1")
        assert result.status == AlertStatus.DISMISSED

    def test_delete(self):
        self.store.save_alerts([Alert(id="a1", title="T")])
        assert self.store.delete_alert("a1") is True
        assert self.store.get_alert("a1") is None

    def test_stats(self):
        self.store.save_alerts([Alert(id="a1", title="T1", severity=AlertSeverity.INFO)])
        self.store.save_alerts([Alert(id="a2", title="T2", severity=AlertSeverity.CRITICAL)])
        stats = self.store.stats()
        assert stats["total"] == 2
        assert stats["by_severity"]["info"] == 1

    def test_clear_all(self):
        self.store.save_alerts([Alert(id="a1", title="T")])
        count = self.store.clear_all()
        assert count == 1
        assert self.store.list_alerts() == []

    def test_history_recorded(self):
        self.store.save_alerts([Alert(id="a1", title="T")])
        self.store.acknowledge_alert("a1")
        history = self.store.get_history("a1")
        assert len(history) == 2  # created + acknowledged


# ── AlertEngine integration ──

class TestAlertEngineIntegration:
    def test_engine_evaluate(self):
        store = AlertStore()
        engine = AlertEngine(store=store)
        rules = [AlertRule(name="r1", type=AlertType.THRESHOLD, field_path="total",
                           condition=RuleCondition.GT, threshold_value=100)]
        alerts = engine.evaluate({"total": 200}, rules)
        assert len(alerts) == 1
        assert store.get_alert(alerts[0].id) is not None
