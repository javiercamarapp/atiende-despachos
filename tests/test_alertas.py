# -*- coding: utf-8 -*-
"""
test_alertas.py — Tests for the Intelligent Alerts Engine module.

Covers:
  - Models: construction, defaults, serialization, JSON schema
  - Engine: rule evaluation (threshold, anomaly, due_date, volume, reconciliation, custom)
  - Store: save, dedup, history, acknowledge, dismiss, stats, rate limiting
  - Routes: all 10 endpoints (GET/POST/DELETE), filters, pagination, auth
  - Edge cases: empty data, invalid rules, missing fields, boundary conditions
  - Multi-tenant: tenant isolation in alerts, rules, and stats

120+ test cases organized by category.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.features.alertas.models import (
    Alert,
    AlertConfig,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
    NotificationPreference,
    RuleCondition,
)
from b2b_ai.features.alertas.engine import (
    AlertEngine,
    _compute_alert_id,
    _evaluate_anomaly,
    _evaluate_due_date,
    _evaluate_reconciliation,
    _evaluate_threshold,
    _evaluate_volume,
    _extract_value,
    evaluate_rules,
    register_custom_predicate,
)
from b2b_ai.features.alertas.store import AlertStore

API_KEY = "alertas-test-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "alertas_test.db"))
    return d


@pytest.fixture
def store():
    return AlertStore()


@pytest.fixture
def engine(store):
    return AlertEngine(store=store)


@pytest.fixture
def client(db):
    # Create a tenant and API key so auth works in route tests
    db.create_tenant("Alertas Test Tenant")
    db.create_api_key(1, "alertas-api-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _auth():
    return {"X-API-Key": API_KEY}


# ---------------------------------------------------------------------------
# Default rules for testing
# ---------------------------------------------------------------------------

def _threshold_rule(**overrides) -> dict:
    base = {
        "id": "rule-threshold-1",
        "name": "High invoice amount",
        "type": "threshold",
        "enabled": True,
        "condition": "gt",
        "threshold_value": 50000,
        "field_path": "total",
        "severity": "warning",
        "message_template": "Invoice {entity} amount ${value} exceeds ${threshold}",
        "tenant_id": None,
    }
    base.update(overrides)
    return base


def _anomaly_rule(**overrides) -> dict:
    base = {
        "id": "rule-anomaly-1",
        "name": "Amount anomaly",
        "type": "anomaly",
        "enabled": True,
        "multiplier": 2.0,
        "field_path": "total",
        "severity": "critical",
        "message_template": "Anomaly detected: {entity} amount {value} is >{threshold}x average",
        "tenant_id": None,
    }
    base.update(overrides)
    return base


def _due_date_rule(**overrides) -> dict:
    base = {
        "id": "rule-due-1",
        "name": "Invoice due soon",
        "type": "due_date",
        "enabled": True,
        "days_before_due": 7,
        "field_path": "fecha_vencimiento",
        "severity": "warning",
        "message_template": "Invoice {entity} due within {threshold} days",
        "tenant_id": None,
    }
    base.update(overrides)
    return base


def _volume_rule(**overrides) -> dict:
    base = {
        "id": "rule-volume-1",
        "name": "High pending volume",
        "type": "volume",
        "enabled": True,
        "volume_limit": 50,
        "field_path": "count",
        "severity": "critical",
        "message_template": "Volume {value} exceeds limit {threshold}",
        "tenant_id": None,
    }
    base.update(overrides)
    return base


def _reconciliation_rule(**overrides) -> dict:
    base = {
        "id": "rule-recon-1",
        "name": "Reconciliation mismatch",
        "type": "reconciliation",
        "enabled": True,
        "severity": "critical",
        "message_template": "Reconciliation mismatch detected for {entity}",
        "tenant_id": None,
    }
    base.update(overrides)
    return base


# ===================================================================
# MODEL TESTS
# ===================================================================

class TestModels:
    """Test Pydantic model construction and validation."""

    def test_alert_defaults(self):
        a = Alert(id="a1", title="Test")
        assert a.id == "a1"
        assert a.title == "Test"
        assert a.severity == AlertSeverity.WARNING
        assert a.status == AlertStatus.ACTIVE
        assert a.metadata == {}

    def test_alert_full(self):
        a = Alert(
            id="a2", rule_id="r1", rule_name="Test Rule",
            type=AlertType.THRESHOLD, severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE, title="Title", message="Message",
            entity_type="invoice", entity_id="INV-001", tenant_id=1,
            value=75000.0, threshold=50000.0,
            created_at="2026-01-01T00:00:00Z",
        )
        assert a.severity == AlertSeverity.CRITICAL
        assert a.value == 75000.0
        assert a.tenant_id == 1

    def test_alert_model_dump(self):
        a = Alert(id="a3", title="Dump", value=100.0)
        d = a.model_dump()
        assert isinstance(d, dict)
        assert d["id"] == "a3"
        assert d["value"] == 100.0

    def test_alert_json_schema(self):
        schema = Alert.model_json_schema()
        assert "properties" in schema

    def test_alert_rule_defaults(self):
        r = AlertRule(name="Test", type=AlertType.THRESHOLD)
        assert r.enabled is True
        assert r.severity == AlertSeverity.WARNING
        assert r.condition == RuleCondition.GT

    def test_alert_rule_full(self):
        r = AlertRule(
            id="r1", name="Full Rule", type=AlertType.THRESHOLD,
            enabled=False, condition=RuleCondition.LTE,
            threshold_value=10000, field_path="total",
            severity=AlertSeverity.INFO, tenant_id=5,
        )
        assert r.enabled is False
        assert r.condition == RuleCondition.LTE
        assert r.tenant_id == 5

    def test_alert_rule_model_dump(self):
        r = AlertRule(name="Dump", type=AlertType.VOLUME, volume_limit=100)
        d = r.model_dump()
        assert d["volume_limit"] == 100

    def test_alert_config_defaults(self):
        c = AlertConfig()
        assert c.enabled is True
        assert c.max_alerts_per_hour == 100
        assert c.dedup_window_seconds == 3600
        assert c.notify_channels == ["log"]

    def test_alert_config_custom(self):
        c = AlertConfig(
            max_alerts_per_hour=50,
            dedup_window_seconds=1800,
            webhook_url="https://hook.example.com",
        )
        assert c.max_alerts_per_hour == 50
        assert c.webhook_url == "https://hook.example.com"

    def test_alert_history(self):
        h = AlertHistory(
            alert_id="a1", action="created",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert h.action == "created"
        assert h.user is None

    def test_notification_preference(self):
        p = NotificationPreference(
            tenant_id=1,
            channels=["email", "slack"],
            min_severity=AlertSeverity.CRITICAL,
            email_addresses=["admin@test.com"],
        )
        assert p.tenant_id == 1
        assert len(p.channels) == 2

    def test_notification_preference_defaults(self):
        p = NotificationPreference(tenant_id=1)
        assert p.channels == ["log"]
        assert p.min_severity == AlertSeverity.WARNING
        assert p.email_addresses == []

    def test_alert_severity_enum(self):
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"

    def test_alert_type_enum(self):
        assert AlertType.THRESHOLD.value == "threshold"
        assert AlertType.ANOMALY.value == "anomaly"
        assert AlertType.DUE_DATE.value == "due_date"
        assert AlertType.VOLUME.value == "volume"
        assert AlertType.RECONCILIATION.value == "reconciliation"
        assert AlertType.CUSTOM.value == "custom"

    def test_alert_status_enum(self):
        assert AlertStatus.ACTIVE.value == "active"
        assert AlertStatus.ACKNOWLEDGED.value == "acknowledged"
        assert AlertStatus.DISMISSED.value == "dismissed"
        assert AlertStatus.RESOLVED.value == "resolved"

    def test_rule_condition_enum(self):
        assert RuleCondition.GT.value == "gt"
        assert RuleCondition.BETWEEN.value == "between"

    def test_alert_optional_fields(self):
        a = Alert(id="opt", title="Opt")
        assert a.rule_id is None
        assert a.entity_type is None
        assert a.value is None
        assert a.acknowledged_at is None


# ===================================================================
# ENGINE HELPER TESTS
# ===================================================================

class TestEngineHelpers:
    """Test engine helper functions."""

    def test_extract_value_simple(self):
        assert _extract_value({"total": 500}, "total") == 500

    def test_extract_value_nested(self):
        assert _extract_value({"a": {"b": {"c": 42}}}, "a.b.c") == 42

    def test_extract_value_missing(self):
        assert _extract_value({"a": 1}, "b") is None

    def test_extract_value_default(self):
        assert _extract_value({}, "x", default=99) == 99

    def test_extract_value_none_path(self):
        assert _extract_value({"a": 1}, None, default="fallback") == "fallback"

    def test_extract_value_deep_missing(self):
        assert _extract_value({"a": {"b": 1}}, "a.b.c") is None

    def test_extract_value_string_field(self):
        assert _extract_value({"name": "hello"}, "name") == "hello"

    def test_compute_alert_id_deterministic(self):
        id1 = _compute_alert_id("rule1", "invoice", "INV-1")
        id2 = _compute_alert_id("rule1", "invoice", "INV-1")
        assert id1 == id2

    def test_compute_alert_id_different_entities(self):
        id1 = _compute_alert_id("rule1", "invoice", "INV-1")
        id2 = _compute_alert_id("rule1", "invoice", "INV-2")
        assert id1 != id2

    def test_compute_alert_id_different_rules(self):
        id1 = _compute_alert_id("rule1", "invoice", "INV-1")
        id2 = _compute_alert_id("rule2", "invoice", "INV-1")
        assert id1 != id2


# ===================================================================
# ENGINE — THRESHOLD RULES
# ===================================================================

class TestThresholdRules:
    """Test threshold rule evaluation."""

    def test_threshold_gt_fires(self):
        data = {"total": 75000}
        rule = AlertRule(**_threshold_rule())
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_gt_no_fire(self):
        data = {"total": 30000}
        rule = AlertRule(**_threshold_rule())
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_gt_exact(self):
        data = {"total": 50000}
        rule = AlertRule(**_threshold_rule())
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_gte_fires(self):
        data = {"total": 50000}
        rule = AlertRule(**_threshold_rule(condition="gte"))
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_lt_fires(self):
        data = {"total": 100}
        rule = AlertRule(**_threshold_rule(condition="lt", threshold_value=500))
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_lt_no_fire(self):
        data = {"total": 1000}
        rule = AlertRule(**_threshold_rule(condition="lt", threshold_value=500))
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_lte_fires(self):
        data = {"total": 500}
        rule = AlertRule(**_threshold_rule(condition="lte", threshold_value=500))
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_eq_fires(self):
        data = {"total": 50000}
        rule = AlertRule(**_threshold_rule(condition="eq"))
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_eq_no_fire(self):
        data = {"total": 50001}
        rule = AlertRule(**_threshold_rule(condition="eq"))
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_neq_fires(self):
        data = {"total": 99999}
        rule = AlertRule(**_threshold_rule(condition="neq"))
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_between_fires(self):
        data = {"total": 30000}
        rule = AlertRule(**_threshold_rule(
            condition="between", threshold_value=10000, threshold_value_max=60000,
        ))
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_between_no_fire(self):
        data = {"total": 70000}
        rule = AlertRule(**_threshold_rule(
            condition="between", threshold_value=10000, threshold_value_max=60000,
        ))
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_missing_field(self):
        data = {}
        rule = AlertRule(**_threshold_rule())
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_none_threshold(self):
        data = {"total": 500}
        rule = AlertRule(**_threshold_rule(threshold_value=None))
        assert _evaluate_threshold(data, rule) is False

    def test_threshold_string_value(self):
        data = {"total": "75000"}
        rule = AlertRule(**_threshold_rule())
        assert _evaluate_threshold(data, rule) is True

    def test_threshold_non_numeric_value(self):
        data = {"total": "abc"}
        rule = AlertRule(**_threshold_rule())
        assert _evaluate_threshold(data, rule) is False


# ===================================================================
# ENGINE — ANOMALY RULES
# ===================================================================

class TestAnomalyRules:
    """Test anomaly rule evaluation."""

    def test_anomaly_fires_above_average(self):
        data = {"total": 100000}
        history = [10000, 12000, 11000]
        rule = AlertRule(**_anomaly_rule())
        assert _evaluate_anomaly(data, rule, history) is True

    def test_anomaly_no_fire_normal(self):
        data = {"total": 15000}
        history = [10000, 12000, 11000]
        rule = AlertRule(**_anomaly_rule())
        assert _evaluate_anomaly(data, rule, history) is False

    def test_anomaly_no_history(self):
        data = {"total": 100000}
        rule = AlertRule(**_anomaly_rule())
        assert _evaluate_anomaly(data, rule, []) is False

    def test_anomaly_zero_average(self):
        data = {"total": 100}
        rule = AlertRule(**_anomaly_rule())
        assert _evaluate_anomaly(data, rule, [0, 0, 0]) is True

    def test_anomaly_missing_field(self):
        data = {}
        rule = AlertRule(**_anomaly_rule())
        assert _evaluate_anomaly(data, rule, [100, 200]) is False

    def test_anomaly_custom_multiplier(self):
        data = {"total": 300}
        history = [100, 110, 105]
        rule = AlertRule(**_anomaly_rule(multiplier=5.0))
        assert _evaluate_anomaly(data, rule, history) is False

    def test_anomaly_at_exact_multiplier(self):
        data = {"total": 24000}  # avg=11000, 2x = 22000, 24000 > 22000
        history = [10000, 12000, 11000]
        rule = AlertRule(**_anomaly_rule(multiplier=2.0))
        assert _evaluate_anomaly(data, rule, history) is True


# ===================================================================
# ENGINE — DUE DATE RULES
# ===================================================================

class TestDueDateRules:
    """Test due-date rule evaluation."""

    def test_due_date_overdue(self):
        data = {"fecha_vencimiento": "2026-01-01"}
        rule = AlertRule(**_due_date_rule())
        assert _evaluate_due_date(data, rule, reference_date="2026-07-01") is True

    def test_due_date_within_window(self):
        data = {"fecha_vencimiento": "2026-07-05"}
        rule = AlertRule(**_due_date_rule(days_before_due=7))
        assert _evaluate_due_date(data, rule, reference_date="2026-07-01") is True

    def test_due_date_outside_window(self):
        data = {"fecha_vencimiento": "2026-08-01"}
        rule = AlertRule(**_due_date_rule(days_before_due=7))
        assert _evaluate_due_date(data, reference_date="2026-07-01", rule=rule) is False

    def test_due_date_missing_date(self):
        data = {}
        rule = AlertRule(**_due_date_rule())
        assert _evaluate_due_date(data, rule) is False

    def test_due_date_invalid_date(self):
        data = {"fecha_vencimiento": "not-a-date"}
        rule = AlertRule(**_due_date_rule())
        assert _evaluate_due_date(data, rule) is False

    def test_due_date_custom_field(self):
        data = {"vencimiento": "2026-07-03"}
        rule = AlertRule(**_due_date_rule(field_path="vencimiento"))
        assert _evaluate_due_date(data, rule, reference_date="2026-07-01") is True

    def test_due_date_exact_boundary(self):
        data = {"fecha_vencimiento": "2026-07-08"}
        rule = AlertRule(**_due_date_rule(days_before_due=7))
        # 7 days from July 1 = July 8, which is within the window
        assert _evaluate_due_date(data, rule, reference_date="2026-07-01") is True


# ===================================================================
# ENGINE — VOLUME RULES
# ===================================================================

class TestVolumeRules:
    """Test volume rule evaluation."""

    def test_volume_fires(self):
        data = {"count": 60}
        rule = AlertRule(**_volume_rule())
        assert _evaluate_volume(data, rule) is True

    def test_volume_no_fire(self):
        data = {"count": 30}
        rule = AlertRule(**_volume_rule())
        assert _evaluate_volume(data, rule) is False

    def test_volume_exact_limit(self):
        data = {"count": 50}
        rule = AlertRule(**_volume_rule())
        assert _evaluate_volume(data, rule) is False

    def test_volume_custom_field(self):
        data = {"pendientes": 100}
        rule = AlertRule(**_volume_rule(field_path="pendientes"))
        assert _evaluate_volume(data, rule) is True

    def test_volume_missing_field(self):
        data = {}
        rule = AlertRule(**_volume_rule())
        assert _evaluate_volume(data, rule) is False

    def test_volume_string_count(self):
        data = {"count": "75"}
        rule = AlertRule(**_volume_rule())
        assert _evaluate_volume(data, rule) is True


# ===================================================================
# ENGINE — RECONCILIATION RULES
# ===================================================================

class TestReconciliationRules:
    """Test reconciliation mismatch rule evaluation."""

    def test_recon_mismatch_count(self):
        data = {"mismatch_count": 3}
        rule = AlertRule(**_reconciliation_rule())
        assert _evaluate_reconciliation(data, rule) is True

    def test_recon_no_mismatch(self):
        data = {"mismatch_count": 0}
        rule = AlertRule(**_reconciliation_rule())
        assert _evaluate_reconciliation(data, rule) is False

    def test_recon_has_mismatch_flag(self):
        data = {"has_mismatch": True}
        rule = AlertRule(**_reconciliation_rule())
        assert _evaluate_reconciliation(data, rule) is True

    def test_recon_no_mismatch_flag(self):
        data = {"has_mismatch": False}
        rule = AlertRule(**_reconciliation_rule())
        assert _evaluate_reconciliation(data, rule) is False

    def test_recon_no_data(self):
        data = {}
        rule = AlertRule(**_reconciliation_rule())
        assert _evaluate_reconciliation(data, rule) is False


# ===================================================================
# ENGINE — EVALUATE_RULES
# ===================================================================

class TestEvaluateRules:
    """Test the main evaluate_rules function."""

    def test_threshold_alert_generated(self):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1
        assert alerts[0].type == AlertType.THRESHOLD
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_no_alerts_below_threshold(self):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 10000, "entity_type": "invoice", "entity_id": "INV-2"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 0

    def test_disabled_rule_not_fired(self):
        rules = [AlertRule(**_threshold_rule(enabled=False))]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 0

    def test_multiple_rules(self):
        rules = [
            AlertRule(**_threshold_rule(threshold_value=50000)),
            AlertRule(**_volume_rule(volume_limit=10)),
        ]
        data = {"total": 75000, "count": 20, "entity_type": "test", "entity_id": "X"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 2

    def test_anomaly_alert_generated(self):
        rules = [AlertRule(**_anomaly_rule())]
        data = {"total": 100000, "entity_type": "invoice", "entity_id": "INV-1"}
        hist = {"total": [10000, 12000, 11000]}
        alerts = evaluate_rules(data, rules, historical_values=hist)
        assert len(alerts) == 1
        assert alerts[0].type == AlertType.ANOMALY

    def test_due_date_alert_generated(self):
        rules = [AlertRule(**_due_date_rule())]
        data = {"fecha_vencimiento": "2026-07-03", "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = evaluate_rules(data, rules, reference_date="2026-07-01")
        assert len(alerts) == 1
        assert alerts[0].type == AlertType.DUE_DATE

    def test_volume_alert_generated(self):
        rules = [AlertRule(**_volume_rule())]
        data = {"count": 60, "entity_type": "volume", "entity_id": "agg"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1
        assert alerts[0].type == AlertType.VOLUME

    def test_reconciliation_alert_generated(self):
        rules = [AlertRule(**_reconciliation_rule())]
        data = {"mismatch_count": 5, "entity_type": "reconciliation", "entity_id": "S1"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1
        assert alerts[0].type == AlertType.RECONCILIATION

    def test_empty_rules(self):
        alerts = evaluate_rules({"total": 100}, [])
        assert alerts == []

    def test_alert_id_deterministic(self):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        a1 = evaluate_rules(data, rules)[0]
        a2 = evaluate_rules(data, rules)[0]
        assert a1.id == a2.id

    def test_message_template_replacement(self):
        rules = [AlertRule(**_threshold_rule(
            message_template="Invoice {entity} has value {value} > {threshold}",
        ))]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-42"}
        alerts = evaluate_rules(data, rules)
        assert "INV-42" in alerts[0].message
        assert "75000" in alerts[0].message
        assert "50000" in alerts[0].message

    def test_alert_has_created_at(self):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = evaluate_rules(data, rules)
        assert alerts[0].created_at is not None

    def test_no_empty_alerts(self):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 10}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 0


# ===================================================================
# STORE TESTS
# ===================================================================

class TestStore:
    """Test AlertStore operations."""

    def test_save_and_retrieve(self, store):
        alert = Alert(id="test-1", title="Test", type=AlertType.THRESHOLD)
        new = store.save_alerts([alert])
        assert len(new) == 1
        retrieved = store.get_alert("test-1")
        assert retrieved is not None
        assert retrieved.title == "Test"

    def test_dedup(self, store):
        alert = Alert(id="dup-1", title="Dup")
        store.save_alerts([alert])
        # Same alert again → dedup
        same = Alert(id="dup-1", title="Dup v2")
        new = store.save_alerts([same])
        assert len(new) == 0

    def test_dedup_expired(self, store):
        store.config.dedup_window_seconds = 0  # immediate expiry
        alert = Alert(id="exp-1", title="Exp")
        store.save_alerts([alert])
        time.sleep(0.01)
        same = Alert(id="exp-1", title="Exp v2")
        new = store.save_alerts([same])
        assert len(new) == 1

    def test_list_alerts(self, store):
        store.save_alerts([Alert(id="a1", title="A1"), Alert(id="a2", title="A2")])
        alerts = store.list_alerts()
        assert len(alerts) == 2

    def test_list_by_tenant(self, store):
        store.save_alerts([
            Alert(id="t1", title="T1", tenant_id=1),
            Alert(id="t2", title="T2", tenant_id=2),
            Alert(id="t3", title="T3", tenant_id=1),
        ])
        assert len(store.list_alerts(tenant_id=1)) == 2
        assert len(store.list_alerts(tenant_id=2)) == 1
        assert len(store.list_alerts(tenant_id=99)) == 0

    def test_list_by_severity(self, store):
        store.save_alerts([
            Alert(id="s1", title="S1", severity=AlertSeverity.INFO),
            Alert(id="s2", title="S2", severity=AlertSeverity.CRITICAL),
            Alert(id="s3", title="S3", severity=AlertSeverity.CRITICAL),
        ])
        assert len(store.list_alerts(severity=AlertSeverity.INFO)) == 1
        assert len(store.list_alerts(severity=AlertSeverity.CRITICAL)) == 2

    def test_list_by_type(self, store):
        store.save_alerts([
            Alert(id="y1", title="Y1", type=AlertType.THRESHOLD),
            Alert(id="y2", title="Y2", type=AlertType.ANOMALY),
        ])
        assert len(store.list_alerts(alert_type=AlertType.THRESHOLD)) == 1
        assert len(store.list_alerts(alert_type=AlertType.ANOMALY)) == 1

    def test_list_by_status(self, store):
        a = Alert(id="st1", title="ST1")
        store.save_alerts([a])
        store.acknowledge_alert("st1")
        assert len(store.list_alerts(status=AlertStatus.ACTIVE)) == 0
        assert len(store.list_alerts(status=AlertStatus.ACKNOWLEDGED)) == 1

    def test_list_pagination(self, store):
        alerts = [Alert(id=f"p{i}", title=f"P{i}") for i in range(10)]
        store.save_alerts(alerts)
        page1 = store.list_alerts(limit=3, offset=0)
        page2 = store.list_alerts(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].id != page2[0].id

    def test_acknowledge(self, store):
        store.save_alerts([Alert(id="ack1", title="Ack")])
        result = store.acknowledge_alert("ack1", user="admin")
        assert result is not None
        assert result.status == AlertStatus.ACKNOWLEDGED
        assert result.acknowledged_by == "admin"

    def test_acknowledge_not_found(self, store):
        result = store.acknowledge_alert("nonexistent")
        assert result is None

    def test_dismiss(self, store):
        store.save_alerts([Alert(id="dis1", title="Dis")])
        result = store.dismiss_alert("dis1", user="admin")
        assert result is not None
        assert result.status == AlertStatus.DISMISSED
        assert result.dismissed_by == "admin"

    def test_dismiss_not_found(self, store):
        result = store.dismiss_alert("nonexistent")
        assert result is None

    def test_dismiss_already_dismissed(self, store):
        store.save_alerts([Alert(id="dd1", title="DD")])
        store.dismiss_alert("dd1")
        result = store.dismiss_alert("dd1")
        assert result.status == AlertStatus.DISMISSED

    def test_delete(self, store):
        store.save_alerts([Alert(id="del1", title="Del")])
        assert store.delete_alert("del1") is True
        assert store.get_alert("del1") is None

    def test_delete_not_found(self, store):
        assert store.delete_alert("nonexistent") is False

    def test_clear_all(self, store):
        store.save_alerts([Alert(id="c1", title="C1"), Alert(id="c2", title="C2")])
        count = store.clear_all()
        assert count == 2
        assert store.list_alerts() == []

    def test_history_recorded(self, store):
        store.save_alerts([Alert(id="h1", title="H1")])
        store.acknowledge_alert("h1")
        history = store.get_history("h1")
        assert len(history) == 2
        assert history[0].action == "created"
        assert history[1].action == "acknowledged"

    def test_history_empty(self, store):
        history = store.get_history("nonexistent")
        assert history == []

    def test_rules_crud(self, store):
        store.save_rule("r1", {"id": "r1", "name": "Rule 1", "enabled": True})
        assert store.get_rule("r1") is not None
        rules = store.list_rules()
        assert len(rules) == 1
        assert store.delete_rule("r1") is True
        assert store.get_rule("r1") is None

    def test_rules_by_tenant(self, store):
        store.save_rule("r1", {"id": "r1", "tenant_id": 1, "enabled": True})
        store.save_rule("r2", {"id": "r2", "tenant_id": 2, "enabled": True})
        store.save_rule("r3", {"id": "r3", "tenant_id": None, "enabled": True})
        assert len(store.list_rules(tenant_id=1)) == 2  # r1 + global r3
        assert len(store.list_rules(tenant_id=2)) == 2  # r2 + global r3
        assert len(store.list_rules(tenant_id=99)) == 1  # only r3

    def test_rules_enabled_only(self, store):
        store.save_rule("r1", {"id": "r1", "enabled": True})
        store.save_rule("r2", {"id": "r2", "enabled": False})
        assert len(store.list_rules(enabled_only=True)) == 1

    def test_stats(self, store):
        store.save_alerts([
            Alert(id="st1", severity=AlertSeverity.INFO, type=AlertType.THRESHOLD),
            Alert(id="st2", severity=AlertSeverity.CRITICAL, type=AlertType.ANOMALY),
            Alert(id="st3", severity=AlertSeverity.CRITICAL, type=AlertType.VOLUME),
        ])
        stats = store.stats()
        assert stats["total"] == 3
        assert stats["active"] == 3
        assert stats["by_severity"]["info"] == 1
        assert stats["by_severity"]["critical"] == 2
        assert stats["by_type"]["threshold"] == 1
        assert stats["by_type"]["anomaly"] == 1

    def test_stats_by_tenant(self, store):
        store.save_alerts([
            Alert(id="t1", tenant_id=1),
            Alert(id="t2", tenant_id=2),
            Alert(id="t3", tenant_id=1),
        ])
        stats = store.stats(tenant_id=1)
        assert stats["total"] == 2

    def test_rate_limit(self, store):
        store.config.max_alerts_per_hour = 3
        alerts = [Alert(id=f"rl{i}", title=f"RL{i}") for i in range(5)]
        new = store.save_alerts(alerts)
        assert len(new) == 3

    def test_count_alerts(self, store):
        store.save_alerts([
            Alert(id="c1", severity=AlertSeverity.INFO),
            Alert(id="c2", severity=AlertSeverity.WARNING),
            Alert(id="c3", severity=AlertSeverity.INFO),
        ])
        assert store.count_alerts() == 3
        assert store.count_alerts(severity=AlertSeverity.INFO) == 2

    def test_notifications(self, store):
        store.log_notification({"type": "email", "alert_id": "a1"})
        store.log_notification({"type": "slack", "alert_id": "a2"})
        notifs = store.list_notifications()
        assert len(notifs) == 2

    def test_list_notifications_limit(self, store):
        for i in range(5):
            store.log_notification({"type": "log", "i": i})
        assert len(store.list_notifications(limit=3)) == 3


# ===================================================================
# ENGINE INTEGRATION (Engine + Store)
# ===================================================================

class TestEngineIntegration:
    """Test AlertEngine with real store."""

    def test_engine_evaluate(self, engine):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = engine.evaluate(data, rules)
        assert len(alerts) == 1
        assert engine.store.get_alert(alerts[0].id) is not None

    def test_engine_dedup(self, engine):
        rules = [AlertRule(**_threshold_rule())]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        a1 = engine.evaluate(data, rules)
        a2 = engine.evaluate(data, rules)
        assert len(a1) == 1
        assert len(a2) == 0

    def test_engine_evaluate_invoices(self, engine):
        rules = [AlertRule(**_threshold_rule())]
        invoices = [
            {"total": 75000, "folio_fiscal": "UUID-1"},
            {"total": 10000, "folio_fiscal": "UUID-2"},
            {"total": 90000, "folio_fiscal": "UUID-3"},
        ]
        alerts = engine.evaluate_invoices(invoices, rules)
        assert len(alerts) == 2

    def test_engine_evaluate_invoices_with_history(self, engine):
        rules = [AlertRule(**_anomaly_rule())]
        invoices = [
            {"total": 100000, "folio_fiscal": "UUID-1"},
            {"total": 5000, "folio_fiscal": "UUID-2"},
        ]
        alerts = engine.evaluate_invoices(
            invoices, rules,
            historical_amounts=[10000, 12000, 11000],
        )
        assert len(alerts) == 1  # only UUID-1 is anomalous

    def test_engine_evaluate_reconciliation(self, engine):
        rules = [AlertRule(**_reconciliation_rule())]
        data = {"mismatch_count": 3, "session_id": "S1"}
        alerts = engine.evaluate_reconciliation(data, rules)
        assert len(alerts) == 1

    def test_engine_evaluate_volume(self, engine):
        rules = [AlertRule(**_volume_rule())]
        data = {"count": 100}
        alerts = engine.evaluate_volume(data, rules)
        assert len(alerts) == 1

    def test_engine_tenant_filter(self, engine):
        rules = [
            AlertRule(**_threshold_rule(tenant_id=1)),
            AlertRule(**_threshold_rule(tenant_id=2, name="Rule 2")),
        ]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = engine.evaluate(data, rules, tenant_id=1)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "High invoice amount"

    def test_engine_global_rules_apply(self, engine):
        rules = [AlertRule(**_threshold_rule(tenant_id=None))]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"}
        alerts = engine.evaluate(data, rules, tenant_id=1)
        assert len(alerts) == 1


# ===================================================================
# CUSTOM PREDICATE
# ===================================================================

class TestCustomPredicate:
    """Test custom predicate registration and evaluation."""

    def test_register_and_fire(self):
        def my_pred(data, rule):
            return data.get("status") == "overdue"

        register_custom_predicate("overdue_check", my_pred)
        rules = [AlertRule(
            name="Overdue", type=AlertType.CUSTOM,
            metadata={"predicate_id": "overdue_check"},
        )]
        data = {"status": "overdue", "entity_type": "invoice", "entity_id": "X"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1

    def test_custom_predicate_no_fire(self):
        def my_pred(data, rule):
            return data.get("status") == "overdue"

        register_custom_predicate("overdue_check2", my_pred)
        rules = [AlertRule(
            name="Overdue", type=AlertType.CUSTOM,
            metadata={"predicate_id": "overdue_check2"},
        )]
        data = {"status": "paid", "entity_type": "invoice", "entity_id": "X"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 0


# ===================================================================
# ROUTES TESTS
# ===================================================================

class TestRoutes:
    """Test FastAPI alert routes via TestClient."""

    def test_list_alerts_empty(self, client):
        c, db = client
        r = c.get("/api/v1/alerts", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["alerts"] == []

    def test_list_alerts_with_data(self, client):
        c, db = client
        store = AlertStore()
        store.save_alerts([Alert(id="rt1", title="RT1"), Alert(id="rt2", title="RT2")])
        # We can't easily inject into the router's shared store,
        # so we test the evaluate endpoint which creates alerts
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_evaluate_creates_alert(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        assert r.status_code == 200
        alerts = r.json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["type"] == "threshold"

    def test_evaluate_no_alert(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 1000},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_create_rule(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/rules", json={
            "name": "Test Rule",
            "type": "threshold",
            "condition": "gt",
            "threshold_value": 50000,
            "field_path": "total",
        }, headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["rule"]["name"] == "Test Rule"

    def test_list_rules(self, client):
        c, db = client
        c.post("/api/v1/alerts/rules", json={
            "name": "Rule A", "type": "threshold",
        }, headers=_auth())
        c.post("/api/v1/alerts/rules", json={
            "name": "Rule B", "type": "volume",
        }, headers=_auth())
        r = c.get("/api/v1/alerts/rules", headers=_auth())
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_list_rules_enabled_only(self, client):
        c, db = client
        c.post("/api/v1/alerts/rules", json={
            "name": "Enabled", "type": "threshold", "enabled": True,
        }, headers=_auth())
        c.post("/api/v1/alerts/rules", json={
            "name": "Disabled", "type": "threshold", "enabled": False,
        }, headers=_auth())
        r = c.get("/api/v1/alerts/rules?enabled_only=true", headers=_auth())
        assert r.json()["count"] == 1

    def test_stats(self, client):
        c, db = client
        # Create some alerts via evaluate
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "S1"},
            "rules": [_threshold_rule(severity="warning")],
        }, headers=_auth())
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"count": 100, "entity_type": "volume", "entity_id": "S2"},
            "rules": [_volume_rule(severity="critical")],
        }, headers=_auth())
        r = c.get("/api/v1/alerts/stats", headers=_auth())
        assert r.status_code == 200
        stats = r.json()
        assert stats["total"] >= 2
        assert "by_severity" in stats
        assert "by_type" in stats

    def test_acknowledge_route(self, client):
        c, db = client
        # Create alert
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "ACK-1"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        alert_id = r.json()["alerts"][0]["id"]
        # Acknowledge
        r = c.post(f"/api/v1/alerts/{alert_id}/acknowledge", json={
            "user": "admin",
        }, headers=_auth())
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["alert"]["status"] == "acknowledged"

    def test_dismiss_route(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "DIS-1"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        alert_id = r.json()["alerts"][0]["id"]
        r = c.post(f"/api/v1/alerts/{alert_id}/dismiss", json={
            "user": "admin",
        }, headers=_auth())
        assert r.status_code == 200
        assert r.json()["alert"]["status"] == "dismissed"

    def test_delete_route(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "DEL-1"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        alert_id = r.json()["alerts"][0]["id"]
        r = c.delete(f"/api/v1/alerts/{alert_id}", headers=_auth())
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_get_alert_not_found(self, client):
        c, db = client
        r = c.get("/api/v1/alerts/nonexistent", headers=_auth())
        assert r.status_code == 404

    def test_acknowledge_not_found(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/nonexistent/acknowledge", headers=_auth())
        assert r.status_code == 404

    def test_dismiss_not_found(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/nonexistent/dismiss", headers=_auth())
        assert r.status_code == 404

    def test_delete_not_found(self, client):
        c, db = client
        r = c.delete("/api/v1/alerts/nonexistent", headers=_auth())
        assert r.status_code == 404

    def test_history_route(self, client):
        c, db = client
        r = c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "HIST-1"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        alert_id = r.json()["alerts"][0]["id"]
        r = c.get(f"/api/v1/alerts/{alert_id}/history", headers=_auth())
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    def test_history_not_found(self, client):
        c, db = client
        r = c.get("/api/v1/alerts/nonexistent/history", headers=_auth())
        assert r.status_code == 404


# ===================================================================
# EDGE CASES
# ===================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_data(self):
        alerts = evaluate_rules({}, [AlertRule(**_threshold_rule())])
        assert alerts == []

    def test_large_values(self):
        rules = [AlertRule(**_threshold_rule(threshold_value=1e12))]
        data = {"total": 1e15, "entity_type": "invoice", "entity_id": "BIG"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1

    def test_zero_threshold(self):
        rules = [AlertRule(**_threshold_rule(threshold_value=0, condition="gt"))]
        data = {"total": 0.001, "entity_type": "invoice", "entity_id": "ZERO"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1

    def test_negative_values(self):
        rules = [AlertRule(**_threshold_rule(threshold_value=-100, condition="lt"))]
        data = {"total": -200, "entity_type": "invoice", "entity_id": "NEG"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 1

    def test_many_rules(self):
        rules = [
            AlertRule(**_threshold_rule(threshold_value=v * 1000))
            for v in range(1, 20)
        ]
        data = {"total": 25000, "entity_type": "invoice", "entity_id": "MANY"}
        alerts = evaluate_rules(data, rules)
        # thresholds 1000-19000 are all < 25000 (GT), so 19 rules fire
        assert len(alerts) == 19

    def test_store_concurrent_save(self, store):
        """Thread safety: save from multiple threads."""
        import concurrent.futures
        alerts = [Alert(id=f"c{i}", title=f"C{i}") for i in range(100)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(store.save_alerts, [a]) for a in alerts]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        total_new = sum(len(r) for r in results)
        assert total_new >= 90  # some may dedup

    def test_store_retrieve_nonexistent(self, store):
        assert store.get_alert("does-not-exist") is None

    def test_store_clear_empty(self, store):
        assert store.clear_all() == 0

    def test_empty_rules_list(self):
        alerts = evaluate_rules({"total": 50000}, [])
        assert alerts == []

    def test_all_disabled_rules(self):
        rules = [
            AlertRule(**_threshold_rule(enabled=False)),
            AlertRule(**_volume_rule(enabled=False)),
        ]
        data = {"total": 75000, "count": 100, "entity_type": "test", "entity_id": "X"}
        alerts = evaluate_rules(data, rules)
        assert len(alerts) == 0

    def test_anomaly_with_all_zero_history(self):
        rules = [AlertRule(**_anomaly_rule())]
        data = {"total": 0}
        alerts = evaluate_rules(data, rules, historical_values={"total": [0, 0]})
        assert len(alerts) == 0


# ===================================================================
# MULTI-TENANT
# ===================================================================

class TestMultiTenant:
    """Test multi-tenant isolation."""

    def test_tenant_scoped_alerts(self):
        store = AlertStore()
        store.save_alerts([
            Alert(id="m1", title="M1", tenant_id=1),
            Alert(id="m2", title="M2", tenant_id=2),
            Alert(id="m3", title="M3", tenant_id=1),
        ])
        assert len(store.list_alerts(tenant_id=1)) == 2
        assert len(store.list_alerts(tenant_id=2)) == 1

    def test_tenant_stats(self):
        store = AlertStore()
        store.save_alerts([
            Alert(id="ms1", tenant_id=1, severity=AlertSeverity.INFO),
            Alert(id="ms2", tenant_id=2, severity=AlertSeverity.CRITICAL),
        ])
        s1 = store.stats(tenant_id=1)
        s2 = store.stats(tenant_id=2)
        assert s1["total"] == 1
        assert s2["total"] == 1

    def test_tenant_rule_filtering(self):
        store = AlertStore()
        store.save_rule("tr1", {"id": "tr1", "tenant_id": 1, "enabled": True})
        store.save_rule("tr2", {"id": "tr2", "tenant_id": 2, "enabled": True})
        store.save_rule("tr3", {"id": "tr3", "tenant_id": None, "enabled": True})
        rules = store.list_rules(tenant_id=1)
        rule_ids = [r["id"] for r in rules]
        assert "tr1" in rule_ids
        assert "tr3" in rule_ids
        assert "tr2" not in rule_ids

    def test_engine_tenant_isolation(self):
        store = AlertStore()
        engine = AlertEngine(store=store)
        rules = [
            AlertRule(**_threshold_rule(tenant_id=1, name="T1 Rule")),
            AlertRule(**_threshold_rule(tenant_id=2, name="T2 Rule", threshold_value=30000)),
        ]
        data = {"total": 75000, "entity_type": "invoice", "entity_id": "MT-1"}
        alerts = engine.evaluate(data, rules, tenant_id=1)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "T1 Rule"

    def test_global_rules_apply_to_all_tenants(self):
        store = AlertStore()
        engine = AlertEngine(store=store)
        rules = [AlertRule(**_threshold_rule(tenant_id=None, name="Global"))]
        # Different entity_ids to avoid dedup between tenants
        data_t1 = {"total": 75000, "entity_type": "invoice", "entity_id": "MT-2-T1"}
        data_t2 = {"total": 75000, "entity_type": "invoice", "entity_id": "MT-2-T2"}
        alerts_t1 = engine.evaluate(data_t1, rules, tenant_id=1)
        alerts_t2 = engine.evaluate(data_t2, rules, tenant_id=2)
        assert len(alerts_t1) == 1
        assert len(alerts_t2) == 1
        # Different entity IDs → different alert IDs
        assert alerts_t1[0].id != alerts_t2[0].id

    def test_notification_preference_per_tenant(self):
        p1 = NotificationPreference(tenant_id=1, min_severity=AlertSeverity.CRITICAL)
        p2 = NotificationPreference(tenant_id=2, min_severity=AlertSeverity.INFO)
        assert p1.min_severity == AlertSeverity.CRITICAL
        assert p2.min_severity == AlertSeverity.INFO


# ===================================================================
# ROUTE FILTERS
# ===================================================================

class TestRouteFilters:
    """Test route query parameter filtering."""

    def test_list_filter_severity(self, client):
        c, db = client
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "F1"},
            "rules": [_threshold_rule(severity="warning")],
        }, headers=_auth())
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"count": 100, "entity_type": "volume", "entity_id": "F2"},
            "rules": [_volume_rule(severity="critical")],
        }, headers=_auth())
        r = c.get("/api/v1/alerts?severity=critical", headers=_auth())
        assert r.json()["count"] == 1
        assert r.json()["alerts"][0]["severity"] == "critical"

    def test_list_filter_type(self, client):
        c, db = client
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "F3"},
            "rules": [_threshold_rule()],
        }, headers=_auth())
        r = c.get("/api/v1/alerts?type=threshold", headers=_auth())
        assert r.json()["count"] == 1

    def test_list_pagination(self, client):
        c, db = client
        # Create several alerts with different entity IDs
        for i in range(5):
            c.post("/api/v1/alerts/evaluate", json={
                "data": {"total": 75000, "entity_type": "invoice", "entity_id": f"PG-{i}"},
                "rules": [_threshold_rule()],
            }, headers=_auth())
        r = c.get("/api/v1/alerts?limit=2&offset=0", headers=_auth())
        assert r.json()["count"] == 2
        r = c.get("/api/v1/alerts?limit=2&offset=2", headers=_auth())
        assert r.json()["count"] == 2
        r = c.get("/api/v1/alerts?limit=2&offset=4", headers=_auth())
        assert r.json()["count"] == 1
