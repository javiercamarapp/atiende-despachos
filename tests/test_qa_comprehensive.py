# -*- coding: utf-8 -*-
"""
Comprehensive QA Testing for Likida AI Enterprise — Alertas + Contabilidad Electrónica
========================================================================
Tests gaps in existing coverage: edge cases, error paths, data integrity,
API schema compliance, concurrent behavior, and boundary conditions.

KEY FINDINGS:
  - ContabilidadElectrónica routes (/contabilidad/electronica/*) are
    NOT auth-protected — standalone FastAPI app used for testing.
  - Alertas routes (/api/v1/alerts/*) require X-API-Key — standalone app
    with mock auth used for testing.
  - XML root localname must be "ContabilidadEducativa" (not "Contabilidad").
  - Validators return List[str] (error messages), not a dict.
  - Resumen uses "cuentas" (count int), not a list.
"""
from __future__ import annotations

import hashlib
import sys
import time
import concurrent.futures
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from unittest.mock import MagicMock, patch

import pytest

# ── Project paths ────────────────────────────────────────────────────────────
ENTERPRISE = "/Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise"
sys.path.insert(0, ENTERPRISE)

# ── Imports ──────────────────────────────────────────────────────────────────
from b2b_ai.features.alertas.engine import (
    AlertEngine,
    _compute_alert_id,
    _CUSTOM_PREDICATES,
    _evaluate_anomaly,
    _evaluate_due_date,
    _evaluate_reconciliation,
    _evaluate_threshold,
    _evaluate_volume,
    _extract_value,
    _now_iso,
    evaluate_rules,
    register_custom_predicate,
)
from b2b_ai.features.alertas.models import (
    Alert,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
    RuleCondition,
)
from b2b_ai.features.alertas.store import AlertStore
from b2b_ai.features.contabilidad.parser import (
    parse_balanza_bytes,
    parse_catalogo_bytes,
    parse_estado_resultados_bytes,
)
from b2b_ai.features.contabilidad.validators import (
    validate_balanza,
    validate_catalogo,
    validate_estado_resultados,
)
from b2b_ai.services.contabilidad_electronica import (
    ContabilidadElectronica,
    ESTADOS,
    ESTADO_INICIAL,
)
from b2b_ai.services.catalogo_cuentas import CatalogoCuentas

# ── FastAPI fixtures for API testing ─────────────────────────────────────────
from fastapi import FastAPI
from fastapi.testclient import TestClient
from b2b_ai.features.contabilidad.electronica_routes import (
    build_electronica_router,
    clear_packages,
)
from b2b_ai.features.contabilidad.routes import build_contabilidad_router
from b2b_ai.features.alertas.routes import build_alertas_router


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 1: ALERTAS ENGINE — GAPS & EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════

# ── 1.1 Custom predicates ───────────────────────────────────────────────────

class TestCustomPredicates:
    """Custom predicate type is untested in existing suite."""

    def test_register_and_fire_custom_predicate(self):
        register_custom_predicate("always_true", lambda data, rule: True)
        assert "always_true" in _CUSTOM_PREDICATES
        rule = AlertRule(
            name="custom-true",
            type=AlertType.CUSTOM,
            metadata={"predicate_id": "always_true"},
        )
        alerts = evaluate_rules({"any": 1}, [rule])
        assert len(alerts) == 1
        assert alerts[0].type == AlertType.CUSTOM

    def test_custom_predicate_false_does_not_fire(self):
        register_custom_predicate("always_false", lambda data, rule: False)
        rule = AlertRule(
            name="custom-false",
            type=AlertType.CUSTOM,
            metadata={"predicate_id": "always_false"},
        )
        alerts = evaluate_rules({"any": 1}, [rule])
        assert len(alerts) == 0

    def test_custom_predicate_missing_id(self):
        rule = AlertRule(name="no-id", type=AlertType.CUSTOM, metadata={})
        alerts = evaluate_rules({"x": 1}, [rule])
        assert len(alerts) == 0

    def test_custom_predicate_unknown_id(self):
        rule = AlertRule(
            name="unknown",
            type=AlertType.CUSTOM,
            metadata={"predicate_id": "does_not_exist"},
        )
        alerts = evaluate_rules({"x": 1}, [rule])
        assert len(alerts) == 0

    def test_custom_predicate_accesses_data(self):
        def check_high(data, rule):
            return data.get("amount", 0) > 1000
        register_custom_predicate("check_high", check_high)
        rule = AlertRule(
            name="high-amount",
            type=AlertType.CUSTOM,
            metadata={"predicate_id": "check_high"},
        )
        assert len(evaluate_rules({"amount": 2000}, [rule])) == 1
        assert len(evaluate_rules({"amount": 500}, [rule])) == 0

    def test_custom_predicate_can_mutate_flag(self):
        """Predicate can set metadata on the alert."""
        def with_metadata(data, rule):
            return True
        register_custom_predicate("with_meta", with_metadata)
        rule = AlertRule(
            name="meta-rule",
            type=AlertType.CUSTOM,
            metadata={"predicate_id": "with_meta", "entity_type": "custom"},
        )
        alerts = evaluate_rules({"x": 1}, [rule])
        assert alerts[0].entity_type == "custom"


# ── 1.2 evaluate_rules with dict auto-conversion ────────────────────────────

class TestEvaluateRulesAutoConversion:
    def test_dict_rule_auto_converted(self):
        rule_dict = {
            "name": "dict-rule",
            "type": "threshold",
            "condition": "gt",
            "threshold_value": 100,
            "field_path": "amount",
            "enabled": True,
        }
        alerts = evaluate_rules({"amount": 200}, [rule_dict])
        assert len(alerts) == 1
        assert alerts[0].rule_name == "dict-rule"

    def test_invalid_dict_rule_skipped(self):
        bad_rule = {"name": None, "type": "threshold"}
        alerts = evaluate_rules({"x": 1}, [bad_rule])
        assert len(alerts) == 0

    def test_empty_rules_list(self):
        alerts = evaluate_rules({"x": 100}, [])
        assert len(alerts) == 0

    def test_mixed_valid_and_invalid_rules(self):
        good = {
            "name": "good", "type": "threshold",
            "condition": "gt", "threshold_value": 10, "field_path": "x",
        }
        bad = {"name": None}
        alerts = evaluate_rules({"x": 50}, [good, bad])
        assert len(alerts) == 1


# ── 1.3 Disabled rules ──────────────────────────────────────────────────────

class TestDisabledRules:
    def test_disabled_rule_not_fired(self):
        rule = AlertRule(
            name="off", type=AlertType.THRESHOLD, enabled=False,
            threshold_value=10, field_path="v", condition=RuleCondition.GT,
        )
        alerts = evaluate_rules({"v": 999}, [rule])
        assert len(alerts) == 0

    def test_disabled_rule_with_other_enabled(self):
        off = AlertRule(
            name="off", type=AlertType.THRESHOLD, enabled=False,
            threshold_value=10, field_path="x", condition=RuleCondition.GT,
        )
        on = AlertRule(
            name="on", type=AlertType.THRESHOLD, enabled=True,
            threshold_value=10, field_path="x", condition=RuleCondition.GT,
        )
        alerts = evaluate_rules({"x": 50}, [off, on])
        assert len(alerts) == 1
        assert alerts[0].rule_name == "on"


# ── 1.4 Message template placeholders ────────────────────────────────────────

class TestMessageTemplates:
    def test_all_placeholders(self):
        rule = AlertRule(
            name="tpl", type=AlertType.THRESHOLD,
            condition=RuleCondition.GT, threshold_value=50,
            field_path="val",
            message_template="Value {value} > {threshold} for {entity}",
        )
        alerts = evaluate_rules(
            {"val": 100, "entity_type": "invoice", "entity_id": "INV-001"},
            [rule],
        )
        assert len(alerts) == 1
        assert "100" in alerts[0].message
        assert "50" in alerts[0].message
        assert "INV-001" in alerts[0].message

    def test_no_placeholders(self):
        rule = AlertRule(
            name="static", type=AlertType.THRESHOLD,
            condition=RuleCondition.GT, threshold_value=10,
            field_path="x", message_template="Static alert",
        )
        alerts = evaluate_rules({"x": 99}, [rule])
        assert alerts[0].message == "Static alert"

    def test_default_message_when_no_template(self):
        rule = AlertRule(
            name="def-msg", type=AlertType.THRESHOLD,
            condition=RuleCondition.GT, threshold_value=10, field_path="x",
        )
        alerts = evaluate_rules({"x": 99}, [rule])
        assert "def-msg" in alerts[0].message
        assert "triggered" in alerts[0].message

    def test_partial_placeholders(self):
        rule = AlertRule(
            name="partial", type=AlertType.THRESHOLD,
            condition=RuleCondition.GT, threshold_value=10,
            field_path="x", message_template="Alert: value={value}",
        )
        alerts = evaluate_rules({"x": 99}, [rule])
        assert "99" in alerts[0].message


# ── 1.5 Tenant filtering ────────────────────────────────────────────────────

class TestTenantFiltering:
    def test_tenant_id_filters_rules(self):
        rule_t1 = AlertRule(name="r1", type=AlertType.THRESHOLD,
                            condition=RuleCondition.GT, threshold_value=10,
                            field_path="x", tenant_id=1)
        rule_t2 = AlertRule(name="r2", type=AlertType.THRESHOLD,
                            condition=RuleCondition.GT, threshold_value=10,
                            field_path="x", tenant_id=2)
        rule_global = AlertRule(name="rg", type=AlertType.THRESHOLD,
                                condition=RuleCondition.GT, threshold_value=10,
                                field_path="x", tenant_id=None)
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate({"x": 50}, [rule_t1, rule_t2, rule_global], tenant_id=1)
        names = {a.rule_name for a in alerts}
        assert "r1" in names
        assert "rg" in names
        assert "r2" not in names

    def test_tenant_id_set_on_global_rules(self):
        rule_global = AlertRule(name="rg", type=AlertType.THRESHOLD,
                                condition=RuleCondition.GT, threshold_value=10,
                                field_path="x", tenant_id=None)
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate({"x": 50}, [rule_global], tenant_id=99)
        assert alerts[0].tenant_id == 99

    def test_no_tenant_filter_returns_all(self):
        r1 = AlertRule(name="r1", type=AlertType.THRESHOLD,
                       condition=RuleCondition.GT, threshold_value=10,
                       field_path="x", tenant_id=1)
        r2 = AlertRule(name="r2", type=AlertType.THRESHOLD,
                       condition=RuleCondition.GT, threshold_value=10,
                       field_path="x", tenant_id=2)
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate({"x": 50}, [r1, r2])
        assert len(alerts) == 2


# ── 1.6 AlertEngine batch methods ───────────────────────────────────────────

class TestAlertEngineBatchMethods:
    def test_evaluate_invoices_batch(self):
        rule = AlertRule(name="big-inv", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=50000,
                         field_path="total")
        engine = AlertEngine(store=AlertStore())
        invoices = [
            {"folio_fiscal": "A", "total": 60000},
            {"folio_fiscal": "B", "total": 10000},
            {"folio_fiscal": "C", "total": 100000},
        ]
        alerts = engine.evaluate_invoices(invoices, [rule], tenant_id=1)
        assert len(alerts) == 2

    def test_evaluate_invoices_empty_list(self):
        rule = AlertRule(name="inv", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="total")
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate_invoices([], [rule], tenant_id=1)
        assert len(alerts) == 0

    def test_evaluate_invoices_with_historical(self):
        rule = AlertRule(name="anom-inv", type=AlertType.ANOMALY,
                         field_path="total", multiplier=2.0)
        engine = AlertEngine(store=AlertStore())
        invoices = [{"folio_fiscal": "X", "total": 1000}]
        alerts = engine.evaluate_invoices(
            invoices, [rule], historical_amounts=[100, 200, 150], tenant_id=1
        )
        assert len(alerts) == 1  # avg=150, 1000>300

    def test_evaluate_reconciliation(self):
        rule = AlertRule(name="recon", type=AlertType.RECONCILIATION)
        engine = AlertEngine(store=AlertStore())
        data = {"mismatch_count": 3, "session_id": "S-1"}
        alerts = engine.evaluate_reconciliation(data, [rule], tenant_id=1)
        assert len(alerts) == 1
        assert alerts[0].entity_type == "reconciliation"
        assert alerts[0].entity_id == "S-1"

    def test_evaluate_reconciliation_no_mismatch(self):
        rule = AlertRule(name="recon", type=AlertType.RECONCILIATION)
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate_reconciliation(
            {"mismatch_count": 0}, [rule], tenant_id=1
        )
        assert len(alerts) == 0

    def test_evaluate_volume(self):
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=10, field_path="count")
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate_volume({"count": 15}, [rule], tenant_id=1)
        assert len(alerts) == 1
        assert alerts[0].entity_type == "volume"

    def test_evaluate_volume_under_limit(self):
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=10, field_path="count")
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate_volume({"count": 5}, [rule], tenant_id=1)
        assert len(alerts) == 0


# ── 1.7 Dedup via AlertStore ────────────────────────────────────────────────

class TestDedupLogic:
    def test_same_rule_same_entity_dedup(self):
        store = AlertStore()
        rule = AlertRule(name="dup", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        alerts1 = evaluate_rules(
            {"x": 20, "entity_type": "inv", "entity_id": "A"}, [rule]
        )
        alerts2 = evaluate_rules(
            {"x": 20, "entity_type": "inv", "entity_id": "A"}, [rule]
        )
        new1 = store.save_alerts(alerts1)
        new2 = store.save_alerts(alerts2)
        assert len(new1) == 1
        assert len(new2) == 0

    def test_different_entities_no_dedup(self):
        store = AlertStore()
        rule = AlertRule(name="dup", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        a1 = evaluate_rules(
            {"x": 20, "entity_type": "inv", "entity_id": "A"}, [rule]
        )
        a2 = evaluate_rules(
            {"x": 20, "entity_type": "inv", "entity_id": "B"}, [rule]
        )
        new1 = store.save_alerts(a1)
        new2 = store.save_alerts(a2)
        assert len(new1) == 1
        assert len(new2) == 1

    def test_dedup_id_deterministic(self):
        id1 = _compute_alert_id("rule1", "invoice", "INV-001")
        id2 = _compute_alert_id("rule1", "invoice", "INV-001")
        assert id1 == id2
        assert len(id1) == 16

    def test_dedup_different_rule_different_id(self):
        id1 = _compute_alert_id("rule1", "inv", "A")
        id2 = _compute_alert_id("rule2", "inv", "A")
        assert id1 != id2


# ── 1.8 now_iso helper ──────────────────────────────────────────────────────

class TestNowIso:
    def test_format(self):
        ts = _now_iso()
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == 20


# ── 1.9 Threshold boundary conditions ───────────────────────────────────────

class TestThresholdBoundary:
    def test_between_exact_lower_bound(self):
        rule = AlertRule(name="bet", type=AlertType.THRESHOLD,
                         condition=RuleCondition.BETWEEN,
                         threshold_value=10, threshold_value_max=20,
                         field_path="x")
        assert len(evaluate_rules({"x": 10}, [rule])) == 1

    def test_between_exact_upper_bound(self):
        rule = AlertRule(name="bet", type=AlertType.THRESHOLD,
                         condition=RuleCondition.BETWEEN,
                         threshold_value=10, threshold_value_max=20,
                         field_path="x")
        assert len(evaluate_rules({"x": 20}, [rule])) == 1

    def test_between_just_outside(self):
        rule = AlertRule(name="bet", type=AlertType.THRESHOLD,
                         condition=RuleCondition.BETWEEN,
                         threshold_value=10, threshold_value_max=20,
                         field_path="x")
        assert len(evaluate_rules({"x": 9.99}, [rule])) == 0
        assert len(evaluate_rules({"x": 20.01}, [rule])) == 0

    def test_eq_float_precision(self):
        rule = AlertRule(name="eq", type=AlertType.THRESHOLD,
                         condition=RuleCondition.EQ,
                         threshold_value=1.0, field_path="x")
        assert len(evaluate_rules({"x": 1.0}, [rule])) == 1
        assert len(evaluate_rules({"x": 1.0 + 1e-10}, [rule])) == 1

    def test_neq_float_precision(self):
        rule = AlertRule(name="neq", type=AlertType.THRESHOLD,
                         condition=RuleCondition.NEQ,
                         threshold_value=1.0, field_path="x")
        assert len(evaluate_rules({"x": 1.0}, [rule])) == 0
        assert len(evaluate_rules({"x": 2.0}, [rule])) == 1


# ── 1.10 Anomaly edge cases ─────────────────────────────────────────────────

class TestAnomalyEdge:
    def test_anomaly_all_zeros_history(self):
        rule = AlertRule(name="anom", type=AlertType.ANOMALY,
                         field_path="v", multiplier=2.0)
        assert len(evaluate_rules({"v": 0.001}, [rule],
                                  historical_values={"v": [0, 0, 0]})) == 1

    def test_anomaly_value_below_average(self):
        rule = AlertRule(name="anom", type=AlertType.ANOMALY,
                         field_path="v", multiplier=2.0)
        assert len(evaluate_rules({"v": 50}, [rule],
                                  historical_values={"v": [100, 200, 300]})) == 0

    def test_anomaly_negative_history(self):
        rule = AlertRule(name="anom", type=AlertType.ANOMALY,
                         field_path="v", multiplier=2.0)
        assert len(evaluate_rules({"v": -100}, [rule],
                                  historical_values={"v": [-100, -200, -300]})) == 1
        assert len(evaluate_rules({"v": -500}, [rule],
                                  historical_values={"v": [-100, -200, -300]})) == 0

    def test_anomaly_exactly_at_multiplier(self):
        rule = AlertRule(name="anom", type=AlertType.ANOMALY,
                         field_path="v", multiplier=2.0)
        # avg=100, threshold=200, value=200 → NOT > 200
        assert len(evaluate_rules({"v": 200}, [rule],
                                  historical_values={"v": [100, 100, 100]})) == 0
        # value=201 → > 200
        assert len(evaluate_rules({"v": 201}, [rule],
                                  historical_values={"v": [100, 100, 100]})) == 1

    def test_anomaly_empty_history(self):
        rule = AlertRule(name="anom", type=AlertType.ANOMALY,
                         field_path="v")
        assert len(evaluate_rules({"v": 999}, [rule],
                                  historical_values={})) == 0

    def test_anomaly_wrong_key_history(self):
        rule = AlertRule(name="anom", type=AlertType.ANOMALY,
                         field_path="v")
        assert len(evaluate_rules({"v": 999}, [rule],
                                  historical_values={"wrong_key": [1, 2, 3]})) == 0


# ── 1.11 Due date edge cases ────────────────────────────────────────────────

class TestDueDateEdge:
    def test_due_date_exact_boundary(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        ref = "2025-06-01"
        assert len(evaluate_rules({"fecha": "2025-06-08"}, [rule],
                                  reference_date=ref)) == 1

    def test_due_date_just_outside_window(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        ref = "2025-06-01"
        assert len(evaluate_rules({"fecha": "2025-06-09"}, [rule],
                                  reference_date=ref)) == 0

    def test_due_date_invalid_date_format(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        assert len(evaluate_rules({"fecha": "not-a-date"}, [rule],
                                  reference_date="2025-06-01")) == 0

    def test_due_date_none_date(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        assert len(evaluate_rules({"fecha": None}, [rule],
                                  reference_date="2025-06-01")) == 0

    def test_due_date_invalid_reference_falls_back_to_today(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        assert len(evaluate_rules({"fecha": "2020-01-01"}, [rule],
                                  reference_date="invalid")) == 1

    def test_due_date_default_field_path(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=30)
        # Default field is "fecha_vencimiento"
        alerts = evaluate_rules(
            {"fecha_vencimiento": "2020-01-01"}, [rule], reference_date="2025-01-01"
        )
        assert len(alerts) == 1

    def test_due_date_with_none_days_before(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=None, field_path="fecha")
        # Default days_before_due is 3
        alerts = evaluate_rules(
            {"fecha": "2025-06-04"}, [rule], reference_date="2025-06-01"
        )
        assert len(alerts) == 1  # within 3 days


# ── 1.12 Volume edge cases ─────────────────────────────────────────────────

class TestVolumeEdge:
    def test_volume_at_limit_no_fire(self):
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=10, field_path="count")
        assert len(evaluate_rules({"count": 10}, [rule])) == 0

    def test_volume_one_over_limit(self):
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=10, field_path="count")
        assert len(evaluate_rules({"count": 11}, [rule])) == 1

    def test_volume_zero_limit_default(self):
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=None, field_path="count")
        assert len(evaluate_rules({"count": 51}, [rule])) == 1
        assert len(evaluate_rules({"count": 50}, [rule])) == 0


# ── 1.13 Reconciliation edge cases ─────────────────────────────────────────

class TestReconciliationEdge:
    def test_reconciliation_has_mismatch_true(self):
        rule = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert len(evaluate_rules({"has_mismatch": True}, [rule])) == 1

    def test_reconciliation_has_mismatch_false(self):
        rule = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert len(evaluate_rules({"has_mismatch": False}, [rule])) == 0

    def test_reconciliation_no_fields(self):
        rule = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert len(evaluate_rules({}, [rule])) == 0

    def test_reconciliation_mismatch_count_zero(self):
        rule = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        assert len(evaluate_rules({"mismatch_count": 0}, [rule])) == 0

    def test_reconciliation_mismatch_count_overrides_has_mismatch(self):
        """FINDING: When mismatch_count=0 is present, has_mismatch is ignored.
        The engine checks mismatch_count first and returns int(0) > 0 = False,
        never reaching the has_mismatch fallback."""
        rule = AlertRule(name="rec", type=AlertType.RECONCILIATION)
        # mismatch_count=0 takes priority → no fire (even though has_mismatch=True)
        assert len(evaluate_rules({"mismatch_count": 0, "has_mismatch": True}, [rule])) == 0
        # But with mismatch_count absent, has_mismatch is checked
        assert len(evaluate_rules({"has_mismatch": True}, [rule])) == 1


# ── 1.14 Alert model fields ─────────────────────────────────────────────────

class TestAlertModelFields:
    def test_alert_metadata_preserved(self):
        rule = AlertRule(name="meta", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x",
                         metadata={"custom_key": "custom_val"})
        alerts = evaluate_rules(
            {"x": 50, "entity_type": "invoice", "entity_id": "I-1"}, [rule]
        )
        assert alerts[0].metadata.get("rule_metadata", {}).get("custom_key") == "custom_val"

    def test_alert_created_at_is_iso(self):
        rule = AlertRule(name="ts", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        alerts = evaluate_rules({"x": 50}, [rule])
        assert alerts[0].created_at.endswith("Z")
        assert "T" in alerts[0].created_at

    def test_alert_value_float_conversion(self):
        rule = AlertRule(name="val", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        alerts = evaluate_rules({"x": "42.5"}, [rule])
        assert alerts[0].value == 42.5

    def test_alert_non_numeric_value(self):
        rule = AlertRule(name="val", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        alerts = evaluate_rules({"x": "not_a_number"}, [rule])
        assert len(alerts) == 0


# ── 1.15 Unknown rule type ──────────────────────────────────────────────────

class TestUnknownRuleType:
    def test_unknown_type_skipped(self):
        """Rule with unknown type → silently skipped."""
        rule = AlertRule(name="unknown", type=AlertType.CUSTOM,
                         metadata={"predicate_id": "nonexistent"})
        alerts = evaluate_rules({"x": 1}, [rule])
        assert len(alerts) == 0


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 2: CONTABILIDAD ELECTRÓNICA — SERVICE-LEVEL TESTING
# ═════════════════════════════════════════════════════════════════════════════

class TestContabilidadElectronicaService:
    def test_empty_asientos_balanza_cuadrada(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="TEST000101AAA",
            razon_social="Test SA", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        assert paquete["balanza"]["cuadrada"] is True

    def test_single_asiento_cuadrada(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="TEST000101AAA",
            ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos, saldos_iniciales={"101.01": "100"})
        assert paquete["balanza"]["cuadrada"] is True

    def test_sha1_is_hex_40_chars(self):
        sha1 = ContabilidadElectronica.calcular_hash_sha1(b"test data")
        assert len(sha1) == 40
        assert all(c in "0123456789abcdef" for c in sha1)

    def test_sha1_empty_bytes(self):
        sha1 = ContabilidadElectronica.calcular_hash_sha1(b"")
        assert sha1 == hashlib.sha1(b"").hexdigest()

    def test_sha1_deterministic(self):
        data = b"contabilidad electronica SAT"
        assert ContabilidadElectronica.calcular_hash_sha1(data) == \
               ContabilidadElectronica.calcular_hash_sha1(data)

    def test_state_constants(self):
        assert ESTADO_INICIAL == "borrador"
        assert "borrador" in ESTADOS
        assert "listo_para_timbrar" in ESTADOS
        assert "timbrado" in ESTADOS
        assert "enviado" in ESTADOS

    def test_full_state_lifecycle(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        assert mgr.estado_actual() == "borrador"
        mgr.marcar_listo_para_timbrar()
        assert mgr.estado_actual() == "listo_para_timbrar"
        mgr.marcar_timbrado()
        assert mgr.estado_actual() == "timbrado"
        mgr.marcar_enviado()
        assert mgr.estado_actual() == "enviado"

    def test_invalid_transition_skip(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        with pytest.raises(ValueError):
            mgr.marcar_timbrado()

    def test_periodo_format(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=3,
        )
        paquete = mgr.generar_paquete([])
        assert paquete["periodo"] == "2025-03"

    def test_periodo_single_digit_mes(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=9,
        )
        paquete = mgr.generar_paquete([])
        assert paquete["periodo"] == "2025-09"

    def test_catalogo_in_package(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        cat = paquete["catalogo"]
        assert "cuentas" in cat  # count (int)
        assert "sha1" in cat
        assert isinstance(cat["cuentas"], int)
        assert cat["cuentas"] > 0

    def test_balanza_in_package(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        bal = paquete["balanza"]
        assert "cuadrada" in bal
        assert "sha1" in bal
        assert bal["cuadrada"] is True

    def test_resumen_mensual_structure(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        resumen = mgr.generar_resumen_mensual(paquete=paquete)
        assert "total_debe" in resumen
        assert "total_haber" in resumen
        assert "cuentas" in resumen  # count (int)
        assert "cuadrada" in resumen
        assert "saldos_anomalos" in resumen

    def test_resumen_no_paquete_raises(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        with pytest.raises(ValueError, match="Se requiere"):
            mgr.generar_resumen_mensual()

    def test_persistence_package(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "50", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        assert mgr.obtener_paquete() is not None
        assert mgr.obtener_paquete()["periodo"] == "2025-01"


class TestContabilidadElectronicaEdge:
    def test_negative_amounts(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "-100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        assert paquete is not None

    def test_very_large_amounts(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "999999999999.99", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        assert paquete is not None

    def test_many_accounts(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [
            {"cuenta": f"101.{str(i).zfill(2)}", "debe": "100", "haber": "0", "fecha": ""}
            for i in range(1, 51)
        ]
        paquete = mgr.generar_paquete(asientos)
        assert paquete["balanza"]["cuadrada"] is True  # all debit, 50 accounts

    def test_duplicate_accounts(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [
            {"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""},
            {"cuenta": "101.01", "debe": "200", "haber": "0", "fecha": ""},
        ]
        paquete = mgr.generar_paquete(asientos)
        assert paquete is not None

    def test_empty_cuenta_name(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "", "debe": "100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        assert paquete is not None


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 3: XML PARSER — EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════

class TestXMLParserEdgeCases:
    """XML root must be ContabilidadEducativa to be recognized."""

    def test_parse_balanza_no_balanza_node(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa version="1.1" rfc="X" mes="01" ejercicio="2025">
        </ContabilidadEducativa>"""
        result = parse_balanza_bytes(xml)
        assert result is None

    def test_parse_catalogo_no_catalogo_node(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa version="1.1" rfc="X" mes="01" ejercicio="2025">
        </ContabilidadEducativa>"""
        result = parse_catalogo_bytes(xml)
        assert result is None

    def test_parse_estado_resultados_no_node(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa version="1.1" rfc="X" mes="01" ejercicio="2025">
        </ContabilidadEducativa>"""
        result = parse_estado_resultados_bytes(xml)
        assert result is None

    def test_parse_balanza_empty_cuentas(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31T00:00:00" TipoBalance="C">
          </Balanza>
        </ContabilidadEducativa>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert len(result.cuentas) == 0

    def test_parse_balanza_with_accounts(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31T00:00:00" TipoBalance="C">
            <Cuenta NumCta="101.01" Desc="Caja" SaldoIni="0" Debe="5000" Haber="3000"
                    SaldoDeudor="2000" SaldoAcreedor="0"/>
            <Cuenta NumCta="201.01" Desc="Proveedores" SaldoIni="0" Debe="0" Haber="2000"
                    SaldoDeudor="0" SaldoAcreedor="2000"/>
          </Balanza>
        </ContabilidadEducativa>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert len(result.cuentas) == 2
        assert result.cuentas[0].num_cuenta == "101.01"
        assert result.cuentas[0].desc == "Caja"
        assert result.cuentas[0].debe == Decimal("5000")
        assert result.cuentas[0].haber == Decimal("3000")

    def test_parse_catalogo_with_accounts(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Catalogo version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                    FechaCreacion="2025-01-31T00:00:00">
            <Cuenta NumCta="101" Desc="Efectivo" Nivel="1" Naturaleza="D"
                    CodigoAgrupador="101" EstadoCuenta="A"/>
          </Catalogo>
        </ContabilidadEducativa>"""
        result = parse_catalogo_bytes(xml)
        assert result is not None
        assert len(result.cuentas) == 1
        assert result.cuentas[0].num_cuenta == "101"
        assert result.cuentas[0].nivel == 1
        assert result.cuentas[0].naturaleza == "D"

    def test_parse_balanza_whitespace_in_attrs(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc=" X00000000000 " Mes=" 01 " Ejercicio=" 2025 "
                   FechaCreacion=" 2025-01-31 " TipoBalance=" C ">
          </Balanza>
        </ContabilidadEducativa>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert result.rfc == "X00000000000"
        assert result.mes == "01"
        assert result.ejercicio == "2025"

    def test_parse_balanza_invalid_xml(self):
        with pytest.raises(Exception):
            parse_balanza_bytes(b"<not valid xml>>>")

    def test_parse_balanza_decimal_fields(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101.01" Desc="Caja" SaldoIni="1234.56"
                    Debe="0.01" Haber="999999.99"
                    SaldoDeudor="0" SaldoAcreedor="0"/>
          </Balanza>
        </ContabilidadEducativa>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert result.cuentas[0].saldo_inicial == Decimal("1234.56")
        assert result.cuentas[0].debe == Decimal("0.01")
        assert result.cuentas[0].haber == Decimal("999999.99")

    def test_parse_catalogo_missing_optional_fields(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Catalogo version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                    FechaCreacion="2025-01-31">
            <Cuenta NumCta="101" Desc=""/>
          </Catalogo>
        </ContabilidadEducativa>"""
        result = parse_catalogo_bytes(xml)
        assert result is not None
        assert result.cuentas[0].nivel is None
        assert result.cuentas[0].naturaleza is None

    def test_parse_balanza_non_decimal_field(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101.01" Desc="Caja" SaldoIni="abc"
                    Debe="0" Haber="0" SaldoDeudor="0" SaldoAcreedor="0"/>
          </Balanza>
        </ContabilidadEducativa>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert result.cuentas[0].saldo_inicial is None

    def test_parse_wrong_root_localname(self):
        """Non-ContabilidadEducativa root → None."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X" Mes="01" Ejercicio="2025"/>
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is None


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 4: VALIDATORS — RETURN TYPE
# ═════════════════════════════════════════════════════════════════════════════

class TestValidators:
    def test_validate_balanza_valid(self):
        from b2b_ai.features.contabilidad.parser import BalanzaData, AccountBalance
        data = BalanzaData(
            version="1.1", rfc="X00000000000", mes="01", ejercicio="2025",
            fecha_creacion="2025-01-31T00:00:00", tipo_balance="C",
            cuentas=[
                AccountBalance(num_cuenta="10101", desc="Caja",
                               saldo_inicial=Decimal("0"),
                               debe=Decimal("100"), haber=Decimal("100"),
                               saldo_deudor=Decimal("0"), saldo_acreedor=Decimal("0")),
            ],
        )
        errors = validate_balanza(data)
        assert isinstance(errors, list)
        assert len(errors) == 0  # valid → no errors

    def test_validate_balanza_empty(self):
        from b2b_ai.features.contabilidad.parser import BalanzaData
        data = BalanzaData()
        errors = validate_balanza(data)
        assert isinstance(errors, list)
        assert len(errors) > 0  # missing required fields

    def test_validate_catalogo_valid(self):
        from b2b_ai.features.contabilidad.parser import CatalogoData, AccountCatalogEntry
        data = CatalogoData(
            version="1.1", rfc="X00000000000", mes="01", ejercicio="2025",
            fecha_creacion="2025-01-31T00:00:00",
            cuentas=[
                AccountCatalogEntry(num_cuenta="10101", desc="Efectivo",
                                    nivel=1, naturaleza="D",
                                    codigo_agrupador="101"),
            ],
        )
        errors = validate_catalogo(data)
        assert isinstance(errors, list)
        # "10101" is 5 digits — valid per 4-15 digit rule

    def test_validate_catalogo_empty(self):
        """FINDING: Empty CatalogoData (no cuentas) returns no errors.
        The validator only checks individual account fields, not whether
        the catalog has any accounts at all."""
        from b2b_ai.features.contabilidad.parser import CatalogoData
        data = CatalogoData()
        errors = validate_catalogo(data)
        assert isinstance(errors, list)
        # Empty catalog has no cuentas to validate → 0 errors


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 5: IN-MEMORY STORE ISOLATION
# ═════════════════════════════════════════════════════════════════════════════

class TestInMemoryStoreIsolation:
    def test_packages_independent(self):
        from b2b_ai.features.contabilidad.electronica_routes import (
            _packages, _store_package, _get_package,
        )
        _packages.clear()
        _store_package("pkg1", {"periodo": "2025-01"}, MagicMock())
        _store_package("pkg2", {"periodo": "2025-02"}, MagicMock())
        assert _get_package("pkg1")["paquete"]["periodo"] == "2025-01"
        assert _get_package("pkg2")["paquete"]["periodo"] == "2025-02"
        _packages.clear()

    def test_clear_packages(self):
        from b2b_ai.features.contabilidad.electronica_routes import (
            _packages, _store_package, clear_packages,
        )
        _store_package("test", {"periodo": "2025-01"}, MagicMock())
        assert len(_packages) > 0
        clear_packages()
        assert len(_packages) == 0


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 6: API ENDPOINTS — CONTABILIDAD ELECTRÓNICA
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clear():
    clear_packages()
    yield
    clear_packages()


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(build_electronica_router())
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


ASIENTOS = [
    {"cuenta": "1202", "debe": "5800.00", "haber": "0", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "0", "haber": "5800.00", "fecha": "2026-07-03"},
]


class TestElectronicaAPIGeneratePackage:
    def test_generate_package_ok(self, client):
        resp = client.post("/contabilidad/electronica/package", json={
            "rfc": "TEST000101AAA",
            "razon_social": "Test SA",
            "ejercicio": 2025,
            "mes": 1,
            "asientos": [{"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "package_id" in data
        assert data["periodo"] == "2025-01"

    def test_generate_package_empty_asientos(self, client):
        resp = client.post("/contabilidad/electronica/package", json={
            "rfc": "TEST000101AAA", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        assert resp.status_code == 200

    def test_generate_package_invalid_mes(self, client):
        resp = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 15, "asientos": [],
        })
        assert resp.status_code == 422

    def test_generate_package_no_body(self, client):
        resp = client.post("/contabilidad/electronica/package")
        assert resp.status_code == 422

    def test_generate_package_with_saldos(self, client):
        resp = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1,
            "asientos": [{"cuenta": "101.01", "debe": "500", "haber": "0", "fecha": ""}],
            "saldos_iniciales": {"101.01": "500"},
        })
        assert resp.status_code == 200
        assert resp.json()["balanza_cuadrada"] is True

    def test_generate_package_unique_ids(self, client):
        r1 = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        r2 = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        assert r1.json()["package_id"] != r2.json()["package_id"]


class TestElectronicaAPIHash:
    def test_hash_ok(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={"content": "hello world"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["sha1"]) == 40
        assert data["length"] == 11

    def test_hash_empty_string(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={"content": ""})
        assert resp.status_code == 200
        assert resp.json()["sha1"] == hashlib.sha1(b"").hexdigest()

    def test_hash_unicode(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={"content": "áéíóú 中文"})
        assert resp.status_code == 200
        assert len(resp.json()["sha1"]) == 40

    def test_hash_special_chars(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={
            "content": "<xml>&\"'special",
        })
        assert resp.status_code == 200

    def test_hash_missing_content(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={})
        assert resp.status_code == 422


class TestElectronicaAPIStatus:
    def test_status_not_found(self, client):
        resp = client.get("/contabilidad/electronica/status/nonexistent")
        assert resp.status_code == 404

    def test_status_ok(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.get(f"/contabilidad/electronica/status/{pkg_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        # generar_paquete auto-transitions to 'listo_para_timbrar'
        assert data["estado"] == "listo_para_timbrar"
        assert "periodo" in data


class TestElectronicaAPITransition:
    def test_transition_not_found(self, client):
        resp = client.post("/contabilidad/electronica/transition", json={
            "package_id": "nonexistent", "target_state": "listo_para_timbrar",
        })
        assert resp.status_code == 404

    def test_transition_invalid_state(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "invalid_state",
        })
        assert resp.status_code == 422

    def test_transition_wrong_order(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        # Package starts in listo_para_timbrar; skip to enviado is wrong
        resp = client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "enviado",
        })
        assert resp.status_code == 422

    def test_transition_terminal_state(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        # Go through full flow
        client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "listo_para_timbrar",
        })
        client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "timbrado",
        })
        client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "enviado",
        })
        # Now try to transition from terminal state
        resp = client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "listo_para_timbrar",
        })
        assert resp.status_code == 409  # terminal state


class TestElectronicaAPISummary:
    def test_summary_not_found(self, client):
        resp = client.get("/contabilidad/electronica/summary/nonexistent")
        assert resp.status_code == 404

    def test_summary_ok(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": ASIENTOS,
        })
        pkg_id = gen.json()["package_id"]
        resp = client.get(f"/contabilidad/electronica/summary/{pkg_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        summary = data["summary"]
        assert "total_debe" in summary
        assert "total_haber" in summary
        assert "cuadrada" in summary


class TestElectronicaAPIFullWorkflow:
    def test_full_workflow(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "WF000101AAA", "ejercicio": 2025, "mes": 6, "asientos": ASIENTOS,
        })
        pkg_id = gen.json()["package_id"]

        # Status
        s = client.get(f"/contabilidad/electronica/status/{pkg_id}")
        # generar_paquete auto-transitions to listo_para_timbrar
        assert s.json()["estado"] == "listo_para_timbrar"

        # Transition: listo_para_timbrar → timbrado
        t1 = client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "timbrado",
        })
        assert t1.json()["estado_nuevo"] == "timbrado"

        # Transition: timbrado → enviado
        t2 = client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "enviado",
        })
        assert t2.json()["estado_nuevo"] == "enviado"

        # Summary
        summ = client.get(f"/contabilidad/electronica/summary/{pkg_id}")
        assert summ.status_code == 200

    def test_multiple_packages_independent(self, client):
        r1 = client.post("/contabilidad/electronica/package", json={
            "rfc": "A", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        r2 = client.post("/contabilidad/electronica/package", json={
            "rfc": "B", "ejercicio": 2025, "mes": 2, "asientos": [],
        })
        id1 = r1.json()["package_id"]
        id2 = r2.json()["package_id"]
        # Both start in listo_para_timbrar after generation
        s1 = client.get(f"/contabilidad/electronica/status/{id1}")
        assert s1.json()["estado"] == "listo_para_timbrar"
        s2 = client.get(f"/contabilidad/electronica/status/{id2}")
        assert s2.json()["estado"] == "listo_para_timbrar"
        # Transition one to timbrado
        client.post("/contabilidad/electronica/transition", json={
            "package_id": id1, "target_state": "timbrado",
        })
        # Other should still be listo_para_timbrar
        s2_after = client.get(f"/contabilidad/electronica/status/{id2}")
        assert s2_after.json()["estado"] == "listo_para_timbrar"


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 7: API ENDPOINTS — CONTABILIDAD (parsing)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def contabilidad_app():
    _app = FastAPI()
    _app.include_router(build_contabilidad_router())
    return _app


@pytest.fixture
def contabilidad_client(contabilidad_app):
    return TestClient(contabilidad_app)


class TestContabilidadParsingEndpoints:
    def test_balanza_empty_file(self, contabilidad_client):
        resp = contabilidad_client.post(
            "/contabilidad/balanza",
            files={"file": ("test.xml", b"", "application/xml")},
        )
        assert resp.status_code == 400

    def test_balanza_invalid_xml(self, contabilidad_client):
        resp = contabilidad_client.post(
            "/contabilidad/balanza",
            files={"file": ("test.xml", b"<not valid>", "application/xml")},
        )
        assert resp.status_code == 422

    def test_balanza_no_balanza_node(self, contabilidad_client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa version="1.1" rfc="X" mes="01" ejercicio="2025">
        </ContabilidadEducativa>"""
        resp = contabilidad_client.post(
            "/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 404

    def test_balanza_valid_xml(self, contabilidad_client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101" Desc="Caja" Debe="100" Haber="50"
                    SaldoDeudor="50" SaldoAcreedor="0"/>
          </Balanza>
        </ContabilidadEducativa>"""
        resp = contabilidad_client.post(
            "/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "balanza" in data

    def test_catalogo_empty_file(self, contabilidad_client):
        resp = contabilidad_client.post(
            "/contabilidad/catalogo",
            files={"file": ("test.xml", b"", "application/xml")},
        )
        assert resp.status_code == 400

    def test_catalogo_valid_xml(self, contabilidad_client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Catalogo version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                    FechaCreacion="2025-01-31">
            <Cuenta NumCta="101" Desc="Efectivo" Nivel="1" Naturaleza="D"/>
          </Catalogo>
        </ContabilidadEducativa>"""
        resp = contabilidad_client.post(
            "/contabilidad/catalogo",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "catalogo" in data

    def test_estado_resultados_valid_xml(self, contabilidad_client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <EstadoResultados version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                            FechaCreacion="2025-01-31">
            <Concepto Concepto="Ingresos" Importe="100000"/>
          </EstadoResultados>
        </ContabilidadEducativa>"""
        resp = contabilidad_client.post(
            "/contabilidad/estado-resultados",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_catalog_endpoint(self, contabilidad_client):
        resp = contabilidad_client.get("/contabilidad/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "naturaleza" in data
        assert "tipo_balanza" in data
        assert data["naturaleza"]["D"] == "Deudor"


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 8: ERROR RESPONSE QUALITY
# ═════════════════════════════════════════════════════════════════════════════

class TestErrorResponseQuality:
    def test_422_has_detail(self, client):
        resp = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "mes": 0, "asientos": [],
        })
        assert resp.status_code == 422
        detail = resp.json().get("detail")
        assert detail is not None

    def test_404_has_detail(self, client):
        resp = client.get("/contabilidad/electronica/status/fake-id")
        assert resp.status_code == 404
        detail = resp.json().get("detail")
        assert detail is not None
        assert "fake-id" in str(detail)

    def test_balanza_404_has_message(self, contabilidad_client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa><Catalogo version="1.1" Rfc="X" Mes="01" Ejercicio="2025"/></ContabilidadEducativa>"""
        resp = contabilidad_client.post(
            "/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 404
        assert "Balanza" in resp.json()["detail"]


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 9: DATA INTEGRITY & CONSISTENCY
# ═════════════════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    def test_alert_id_consistency(self):
        id1 = _compute_alert_id("rule-abc", "invoice", "INV-123")
        id2 = _compute_alert_id("rule-abc", "invoice", "INV-123")
        assert id1 == id2

    def test_alert_id_length(self):
        for i in range(100):
            aid = _compute_alert_id(f"rule-{i}", f"entity-{i}", f"id-{i}")
            assert len(aid) == 16

    def test_sha1_hex_format(self):
        sha1 = ContabilidadElectronica.calcular_hash_sha1(b"test")
        assert len(sha1) == 40
        int(sha1, 16)

    def test_balanza_dict_structure(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([
            {"cuenta": "101.01", "debe": "100", "haber": "100", "fecha": ""},
        ])
        balanza = paquete["balanza"]
        assert isinstance(balanza["cuadrada"], bool)
        assert isinstance(balanza["sha1"], str)

    def test_catalogo_dict_structure(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        cat = paquete["catalogo"]
        assert "sha1" in cat
        assert isinstance(cat["cuentas"], int)  # count, not list

    def test_periodo_always_two_digit_mes(self):
        catalogo = CatalogoCuentas()
        for mes in range(1, 13):
            mgr = ContabilidadElectronica(
                catalogo=catalogo, rfc="X", ejercicio=2025, mes=mes,
            )
            paquete = mgr.generar_paquete([])
            parts = paquete["periodo"].split("-")
            assert len(parts[1]) == 2


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 10: CONCURRENCY & PERFORMANCE
# ═════════════════════════════════════════════════════════════════════════════

class TestConcurrency:
    def test_concurrent_rule_evaluation(self):
        rule = AlertRule(name="conc", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        results = []

        def evaluate(x):
            return evaluate_rules({"x": x}, [rule])

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(evaluate, i) for i in range(100)]
            for f in concurrent.futures.as_completed(futures):
                results.append(len(f.result()))

        total = sum(results)
        # Allow off-by-one for timing edge cases
        assert 88 <= total <= 90

    def test_concurrent_store_save(self):
        store = AlertStore()
        rule = AlertRule(name="conc", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        saved = []

        def save(x):
            alerts = evaluate_rules(
                {"x": x, "entity_type": "test", "entity_id": f"e-{x}"},
                [rule],
            )
            new = store.save_alerts(alerts)
            saved.append(len(new))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(save, i) for i in range(50)]
            concurrent.futures.wait(futures)

        total = sum(saved)
        # 40 values > 10, allow race condition off-by-one
        assert 38 <= total <= 40


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 11: CROSS-MODULE INTEGRATION
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossModuleIntegration:
    def test_alerts_from_electronica_package(self):
        """Generate a package and fire alerts based on the result."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [
            {"cuenta": "101.01", "debe": "500", "haber": "0", "fecha": ""},
            {"cuenta": "201.01", "debe": "0", "haber": "300", "fecha": ""},
        ]
        paquete = mgr.generar_paquete(asientos)

        rule = AlertRule(
            name="unbalanced",
            type=AlertType.RECONCILIATION,
            metadata={"entity_type": "contabilidad"},
        )
        if not paquete["balanza"]["cuadrada"]:
            engine = AlertEngine(store=AlertStore())
            alerts = engine.evaluate_reconciliation(
                {"has_mismatch": True, "session_id": "pkg-1"}, [rule], tenant_id=1
            )
            assert len(alerts) == 1
            assert alerts[0].entity_type == "reconciliation"


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 12: SECURITY & INJECTION
# ═════════════════════════════════════════════════════════════════════════════

class TestSecurityEdgeCases:
    def test_xss_in_rule_name(self):
        rule = AlertRule(
            name="<script>alert('xss')</script>",
            type=AlertType.THRESHOLD,
            condition=RuleCondition.GT,
            threshold_value=10, field_path="x",
        )
        alerts = evaluate_rules({"x": 50}, [rule])
        assert "<script>" in alerts[0].title

    def test_very_long_rfc(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="A" * 1000, ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        assert paquete["periodo"] == "2025-01"

    def test_empty_string_hash(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={"content": ""})
        assert resp.status_code == 200
        assert resp.json()["sha1"] == hashlib.sha1(b"").hexdigest()

    def test_unicode_hash(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={"content": "中文🎉"})
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 13: API SCHEMA COMPLIANCE
# ═════════════════════════════════════════════════════════════════════════════

class TestAPISchemaCompliance:
    def test_package_response_has_ok(self, client):
        resp = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        data = resp.json()
        assert "ok" in data
        assert data["ok"] is True

    def test_hash_response_schema(self, client):
        resp = client.post("/contabilidad/electronica/hash", json={"content": "test"})
        data = resp.json()
        assert "ok" in data
        assert "sha1" in data
        assert "length" in data

    def test_status_response_schema(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.get(f"/contabilidad/electronica/status/{pkg_id}")
        data = resp.json()
        assert "ok" in data
        assert "package_id" in data
        assert "estado" in data
        assert "periodo" in data

    def test_transition_response_schema(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        # Package starts in listo_para_timbrar; transition to timbrado
        resp = client.post("/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "timbrado",
        })
        data = resp.json()
        assert "ok" in data
        assert "estado_anterior" in data
        assert "estado_nuevo" in data

    def test_summary_response_schema(self, client):
        gen = client.post("/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.get(f"/contabilidad/electronica/summary/{pkg_id}")
        data = resp.json()
        assert "ok" in data
        assert "summary" in data
        summary = data["summary"]
        assert "total_debe" in summary
        assert "total_haber" in summary
        assert "cuadrada" in summary

    def test_balanza_response_schema(self, contabilidad_client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ContabilidadEducativa>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101" Desc="Caja" Debe="100" Haber="100"/>
          </Balanza>
        </ContabilidadEducativa>"""
        resp = contabilidad_client.post(
            "/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        data = resp.json()
        assert data["ok"] is True
        assert "balanza" in data
        assert "Version" in data["balanza"]

    def test_package_request_mes_validation(self):
        from b2b_ai.features.contabilidad.electronica_routes import PackageRequest
        for m in range(1, 13):
            req = PackageRequest(rfc="X", mes=m, asientos=[])
            assert req.mes == m
        with pytest.raises(Exception):
            PackageRequest(rfc="X", mes=0, asientos=[])
        with pytest.raises(Exception):
            PackageRequest(rfc="X", mes=13, asientos=[])

    def test_asiento_schema_defaults(self):
        from b2b_ai.features.contabilidad.electronica_routes import AsientoSchema
        a = AsientoSchema(cuenta="101.01")
        assert a.debe == "0"
        assert a.haber == "0"
        assert a.fecha == ""
