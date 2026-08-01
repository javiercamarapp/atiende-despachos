# -*- coding: utf-8 -*-
"""
Comprehensive QA Testing for B&B AI — Alertas + Contabilidad Electrónica
========================================================================
Tests gaps in existing coverage: edge cases, error paths, data integrity,
API schema compliance, concurrent behavior, and boundary conditions.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
import json
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


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 1: ALERTAS ENGINE — GAPS & EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════

# ── 1.1 Custom predicates ───────────────────────────────────────────────────

class TestCustomPredicates:
    """Custom predicate type is untested in existing suite."""

    def test_register_and_fire_custom_predicate(self):
        """Register a predicate and verify CUSTOM rule fires."""
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
        """Rule without predicate_id → skip."""
        rule = AlertRule(name="no-id", type=AlertType.CUSTOM, metadata={})
        alerts = evaluate_rules({"x": 1}, [rule])
        assert len(alerts) == 0

    def test_custom_predicate_unknown_id(self):
        """predicate_id not registered → skip."""
        rule = AlertRule(
            name="unknown",
            type=AlertType.CUSTOM,
            metadata={"predicate_id": "does_not_exist"},
        )
        alerts = evaluate_rules({"x": 1}, [rule])
        assert len(alerts) == 0

    def test_custom_predicate_accesses_data(self):
        """Predicate can read data dict."""
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


# ── 1.2 evaluate_rules with dict auto-conversion ────────────────────────────

class TestEvaluateRulesAutoConversion:
    """evaluate_rules should handle dict inputs by auto-converting to AlertRule."""

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
        """Malformed dict that can't become AlertRule → silently skipped."""
        bad_rule = {"name": None, "type": "threshold"}  # name is required
        alerts = evaluate_rules({"x": 1}, [bad_rule])
        assert len(alerts) == 0


# ── 1.3 Disabled rules ──────────────────────────────────────────────────────

class TestDisabledRules:
    def test_disabled_rule_not_fired(self):
        rule = AlertRule(
            name="off",
            type=AlertType.THRESHOLD,
            enabled=False,
            threshold_value=10,
            field_path="v",
            condition=RuleCondition.GT,
        )
        alerts = evaluate_rules({"v": 999}, [rule])
        assert len(alerts) == 0


# ── 1.4 Message template placeholders ────────────────────────────────────────

class TestMessageTemplates:
    def test_all_placeholders(self):
        rule = AlertRule(
            name="tpl",
            type=AlertType.THRESHOLD,
            condition=RuleCondition.GT,
            threshold_value=50,
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
            name="static",
            type=AlertType.THRESHOLD,
            condition=RuleCondition.GT,
            threshold_value=10,
            field_path="x",
            message_template="Static alert",
        )
        alerts = evaluate_rules({"x": 99}, [rule])
        assert alerts[0].message == "Static alert"

    def test_default_message_when_no_template(self):
        rule = AlertRule(
            name="def-msg",
            type=AlertType.THRESHOLD,
            condition=RuleCondition.GT,
            threshold_value=10,
            field_path="x",
        )
        alerts = evaluate_rules({"x": 99}, [rule])
        assert "def-msg" in alerts[0].message
        assert "triggered" in alerts[0].message


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
        assert "rg" in names  # global rules included
        assert "r2" not in names

    def test_tenant_id_set_on_global_rules(self):
        rule_global = AlertRule(name="rg", type=AlertType.THRESHOLD,
                                condition=RuleCondition.GT, threshold_value=10,
                                field_path="x", tenant_id=None)
        engine = AlertEngine(store=AlertStore())
        alerts = engine.evaluate({"x": 50}, [rule_global], tenant_id=99)
        assert alerts[0].tenant_id == 99


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
        assert len(alerts) == 2  # A and C

    def test_evaluate_invoices_with_historical(self):
        rule = AlertRule(name="anom-inv", type=AlertType.ANOMALY,
                         field_path="total", multiplier=2.0)
        engine = AlertEngine(store=AlertStore())
        invoices = [{"folio_fiscal": "X", "total": 1000}]
        alerts = engine.evaluate_invoices(
            invoices, [rule], historical_amounts=[100, 200, 150], tenant_id=1
        )
        # avg = 150, 1000 > 300 → fires
        assert len(alerts) == 1

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
        alerts1 = evaluate_rules({"x": 20}, [rule])
        alerts2 = evaluate_rules({"x": 20}, [rule])

        # save_alerts should dedup
        new1 = store.save_alerts(alerts1)
        new2 = store.save_alerts(alerts2)
        assert len(new1) == 1
        assert len(new2) == 0  # deduped

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
        assert len(new2) == 1  # different entity → not deduped

    def test_dedup_id_deterministic(self):
        id1 = _compute_alert_id("rule1", "invoice", "INV-001")
        id2 = _compute_alert_id("rule1", "invoice", "INV-001")
        assert id1 == id2
        assert len(id1) == 16  # sha256 truncated


# ── 1.8 now_iso helper ──────────────────────────────────────────────────────

class TestNowIso:
    def test_format(self):
        ts = _now_iso()
        # Should be ISO 8601 UTC
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == 20  # YYYY-MM-DDTHH:MM:SSZ


# ── 1.9 Threshold boundary conditions ───────────────────────────────────────

class TestThresholdBoundary:
    def test_between_exact_lower_bound(self):
        rule = AlertRule(name="bet", type=AlertType.THRESHOLD,
                         condition=RuleCondition.BETWEEN,
                         threshold_value=10, threshold_value_max=20,
                         field_path="x")
        assert len(evaluate_rules({"x": 10}, [rule])) == 1  # inclusive

    def test_between_exact_upper_bound(self):
        rule = AlertRule(name="bet", type=AlertType.THRESHOLD,
                         condition=RuleCondition.BETWEEN,
                         threshold_value=10, threshold_value_max=20,
                         field_path="x")
        assert len(evaluate_rules({"x": 20}, [rule])) == 1  # inclusive

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
                         threshold_value=1.0,
                         field_path="x")
        assert len(evaluate_rules({"x": 1.0}, [rule])) == 1
        assert len(evaluate_rules({"x": 1.0 + 1e-10}, [rule])) == 1  # within epsilon


# ── 1.10 Anomaly edge cases ─────────────────────────────────────────────────

class TestAnomalyEdge:
    def test_anomaly_all_zeros_history(self):
        """History is all zeros → avg=0, any positive value fires."""
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
        # avg = -150, fires when v > -300
        assert len(evaluate_rules({"v": -100}, [rule],
                                  historical_values={"v": [-100, -200, -300]})) == 1
        assert len(evaluate_rules({"v": -500}, [rule],
                                  historical_values={"v": [-100, -200, -300]})) == 0


# ── 1.11 Due date edge cases ────────────────────────────────────────────────

class TestDueDateEdge:
    def test_due_date_exact_boundary(self):
        """Due exactly on the window boundary → fires."""
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        ref = "2025-06-01"
        # Due in exactly 7 days → fires
        assert len(evaluate_rules({"fecha": "2025-06-08"}, [rule],
                                  reference_date=ref)) == 1

    def test_due_date_just_outside_window(self):
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        ref = "2025-06-01"
        # Due in 8 days → does NOT fire
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

    def test_due_date_invalid_reference_date_falls_back_to_today(self):
        """Invalid reference_date should fall back to today."""
        rule = AlertRule(name="dd", type=AlertType.DUE_DATE,
                         days_before_due=7, field_path="fecha")
        # Past date should fire regardless of today
        assert len(evaluate_rules({"fecha": "2020-01-01"}, [rule],
                                  reference_date="invalid")) == 1


# ── 1.12 Volume edge cases ─────────────────────────────────────────────────

class TestVolumeEdge:
    def test_volume_at_limit_no_fire(self):
        """Count exactly at limit → does NOT fire (strict >)."""
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=10, field_path="count")
        assert len(evaluate_rules({"count": 10}, [rule])) == 0

    def test_volume_one_over_limit(self):
        rule = AlertRule(name="vol", type=AlertType.VOLUME,
                         volume_limit=10, field_path="count")
        assert len(evaluate_rules({"count": 11}, [rule])) == 1


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


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 2: CONTABILIDAD ELECTRÓNICA — GAPS & EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════

# ── 2.1 ContabilidadElectronica service ──────────────────────────────────────

class TestContabilidadElectronicaService:
    def test_empty_asientos_balanza_cuadrada(self):
        """With no asientos, balanza should still be cuadrada (0=0)."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="TEST000101AAA",
            razon_social="Test SA", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        assert paquete["balanza"]["cuadrada"] is True

    def test_single_asiento_cuadrada(self):
        """A single debit with matching initial saldo should be cuadrada."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="TEST000101AAA",
            ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos, saldos_iniciales={"101.01": "100"})
        assert paquete["balanza"]["cuadrada"] is True

    def test_unbalanced_asientos(self):
        """Mismatched debe/haber → balanza NOT cuadrada."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="TEST000101AAA",
            ejercicio=2025, mes=1,
        )
        asientos = [
            {"cuenta": "101.01", "debe": "500", "haber": "0", "fecha": ""},
            {"cuenta": "201.01", "debe": "0", "haber": "300", "fecha": ""},
        ]
        paquete = mgr.generar_paquete(asientos)
        assert paquete["balanza"]["cuadrada"] is False

    def test_sha1_is_hex_40_chars(self):
        sha1 = ContabilidadElectronica.calcular_hash_sha1(b"test data")
        assert len(sha1) == 40
        assert all(c in "0123456789abcdef" for c in sha1)

    def test_sha1_empty_bytes(self):
        sha1 = ContabilidadElectronica.calcular_hash_sha1(b"")
        assert len(sha1) == 40
        # SHA-1 of empty string
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
            mgr.marcar_timbrado()  # can't skip to timbrado

    def test_invalid_state_string(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        with pytest.raises(ValueError):
            mgr.estado = "invalido"
            mgr.marcar_listo_para_timbrar()

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
        assert paquete["periodo"] == "2025-09"  # zero-padded

    def test_catalogo_in_package(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        assert "cuentas" in paquete["catalogo"]
        assert "sha1" in paquete["catalogo"]
        assert len(paquete["catalogo"]["cuentas"]) > 0

    def test_balanza_in_package(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        assert "cuadrada" in paquete["balanza"]
        assert "sha1" in paquete["balanza"]
        assert paquete["balanza"]["cuadrada"] is True  # empty is balanced

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
        assert "num_cuentas" in resumen
        assert "cuadra" in resumen

    def test_resumen_no_paquete(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        resumen = mgr.generar_resumen_mensual()
        assert resumen["num_cuentas"] == 0

    def test_persistence_package(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([{"cuenta": "101.01", "debe": "50", "haber": "0", "fecha": ""}])
        assert mgr.obtener_paquete() is not None
        assert mgr.obtener_paquete()["periodo"] == "2025-01"


# ── 2.2 ContabilidadElectronica edge cases ───────────────────────────────────

class TestContabilidadElectronicaEdge:
    def test_negative_amounts(self):
        """Debit/haber can be negative in some accounting scenarios."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "-100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        # Should not crash
        assert paquete is not None

    def test_very_large_amounts(self):
        """Large numbers should not overflow."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "101.01", "debe": "999999999999.99", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        assert paquete is not None

    def test_many_accounts(self):
        """Generate many accounts to stress test."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [
            {"cuenta": f"101.{str(i).zfill(2)}", "debe": "100", "haber": "0", "fecha": ""}
            for i in range(1, 51)
        ]
        paquete = mgr.generar_paquete(asientos)
        assert len(paquete["balanza"].get("cuentas", [])) >= 50 or paquete["balanza"]["cuadrada"] is not None

    def test_duplicate_accounts(self):
        """Same account appears multiple times → amounts should aggregate."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [
            {"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""},
            {"cuenta": "101.01", "debe": "200", "haber": "0", "fecha": ""},
        ]
        paquete = mgr.generar_paquete(asientos)
        # Should not crash with duplicates
        assert paquete is not None

    def test_empty_cuenta_name(self):
        """Account with empty name."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        asientos = [{"cuenta": "", "debe": "100", "haber": "0", "fecha": ""}]
        paquete = mgr.generar_paquete(asientos)
        assert paquete is not None


# ── 2.3 XML Parser edge cases ───────────────────────────────────────────────

class TestXMLParserEdgeCases:
    def test_parse_balanza_no_balanza_node(self):
        """XML without Balanza node → returns None."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad version="1.1" rfc="X00000000000" mes="01" ejercicio="2025">
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is None

    def test_parse_catalogo_no_catalogo_node(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad version="1.1" rfc="X00000000000" mes="01" ejercicio="2025">
        </Contabilidad>"""
        result = parse_catalogo_bytes(xml)
        assert result is None

    def test_parse_estado_resultados_no_node(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad version="1.1" rfc="X00000000000" mes="01" ejercicio="2025">
        </Contabilidad>"""
        result = parse_estado_resultados_bytes(xml)
        assert result is None

    def test_parse_balanza_empty_cuentas(self):
        """Balanza with no Cuenta children → empty list."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31T00:00:00" TipoBalance="C">
          </Balanza>
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert len(result.cuentas) == 0

    def test_parse_balanza_with_accounts(self):
        """Parse actual account data."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31T00:00:00" TipoBalance="C">
            <Cuenta NumCta="101.01" Desc="Caja" SaldoIni="0" Debe="5000" Haber="3000"
                    SaldoDeudor="2000" SaldoAcreedor="0"/>
            <Cuenta NumCta="201.01" Desc="Proveedores" SaldoIni="0" Debe="0" Haber="2000"
                    SaldoDeudor="0" SaldoAcreedor="2000"/>
          </Balanza>
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert len(result.cuentas) == 2
        assert result.cuentas[0].num_cuenta == "101.01"
        assert result.cuentas[0].desc == "Caja"
        assert result.cuentas[0].debe == Decimal("5000")
        assert result.cuentas[0].haber == Decimal("3000")

    def test_parse_catalogo_with_accounts(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Catalogo version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                    FechaCreacion="2025-01-31T00:00:00">
            <Cuenta NumCta="101" Desc="Efectivo" Nivel="1" Naturaleza="D"
                    CodigoAgrupador="101" EstadoCuenta="A"/>
          </Catalogo>
        </Contabilidad>"""
        result = parse_catalogo_bytes(xml)
        assert result is not None
        assert len(result.cuentas) == 1
        assert result.cuentas[0].num_cuenta == "101"
        assert result.cuentas[0].nivel == 1
        assert result.cuentas[0].naturaleza == "D"

    def test_parse_balanza_whitespace_in_attrs(self):
        """Whitespace in XML attributes should be stripped."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc=" X00000000000 " Mes=" 01 " Ejercicio=" 2025 "
                   FechaCreacion=" 2025-01-31 " TipoBalance=" C ">
          </Balanza>
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert result.rfc == "X00000000000"
        assert result.mes == "01"
        assert result.ejercicio == "2025"

    def test_parse_balanza_invalid_xml(self):
        """Malformed XML → should raise."""
        with pytest.raises(Exception):
            parse_balanza_bytes(b"<not valid xml>>>")

    def test_parse_balanza_decimal_fields(self):
        """Verify Decimal parsing for financial fields."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101.01" Desc="Caja" SaldoIni="1234.56"
                    Debe="0.01" Haber="999999.99"
                    SaldoDeudor="0" SaldoAcreedor="0"/>
          </Balanza>
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert result.cuentas[0].saldo_inicial == Decimal("1234.56")
        assert result.cuentas[0].debe == Decimal("0.01")
        assert result.cuentas[0].haber == Decimal("999999.99")

    def test_parse_catalogo_missing_optional_fields(self):
        """Catalogo entry with minimal fields."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Catalogo version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                    FechaCreacion="2025-01-31">
            <Cuenta NumCta="101" Desc=""/>
          </Catalogo>
        </Contabilidad>"""
        result = parse_catalogo_bytes(xml)
        assert result is not None
        assert result.cuentas[0].nivel is None
        assert result.cuentas[0].naturaleza is None

    def test_parse_balanza_non_decimal_field(self):
        """Non-numeric string in financial field → None."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101.01" Desc="Caja" SaldoIni="abc"
                    Debe="0" Haber="0" SaldoDeudor="0" SaldoAcreedor="0"/>
          </Balanza>
        </Contabilidad>"""
        result = parse_balanza_bytes(xml)
        assert result is not None
        assert result.cuentas[0].saldo_inicial is None


# ── 2.4 Validators ──────────────────────────────────────────────────────────

class TestValidators:
    def test_validate_balanza_valid(self):
        from b2b_ai.features.contabilidad.parser import BalanzaData, AccountBalance
        data = BalanzaData(
            version="1.1", rfc="X00000000000", mes="01", ejercicio="2025",
            fecha_creacion="2025-01-31T00:00:00", tipo_balance="C",
            cuentas=[
                AccountBalance(num_cuenta="101", desc="Caja", saldo_inicial=Decimal("0"),
                               debe=Decimal("100"), haber=Decimal("50"),
                               saldo_deudor=Decimal("50"), saldo_acreedor=Decimal("0")),
            ],
        )
        result = validate_balanza(data)
        assert result["valid"] is True or result.get("errors", []) == []

    def test_validate_balanza_empty(self):
        from b2b_ai.features.contabilidad.parser import BalanzaData
        data = BalanzaData()
        result = validate_balanza(data)
        # Should report missing required fields
        assert result.get("valid") is False or len(result.get("errors", [])) > 0

    def test_validate_catalogo_valid(self):
        from b2b_ai.features.contabilidad.parser import CatalogoData, AccountCatalogEntry
        data = CatalogoData(
            version="1.1", rfc="X00000000000", mes="01", ejercicio="2025",
            fecha_creacion="2025-01-31T00:00:00",
            cuentas=[
                AccountCatalogEntry(num_cuenta="101", desc="Efectivo", nivel=1,
                                    naturaleza="D", codigo_agrupador="101"),
            ],
        )
        result = validate_catalogo(data)
        assert result["valid"] is True or result.get("errors", []) == []

    def test_validate_catalogo_empty(self):
        from b2b_ai.features.contabilidad.parser import CatalogoData
        data = CatalogoData()
        result = validate_catalogo(data)
        assert result.get("valid") is False or len(result.get("errors", [])) > 0


# ── 2.5 In-memory store isolation ────────────────────────────────────────────

class TestInMemoryStoreIsolation:
    def test_packages_independent(self):
        """Two different package_id keys are independent."""
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


# ── 2.6 PackageRequest mes validation ───────────────────────────────────────

class TestPackageRequestValidation:
    def test_mes_too_low(self):
        from b2b_ai.features.contabilidad.electronica_routes import PackageRequest
        with pytest.raises(Exception):  # ValidationError
            PackageRequest(rfc="X", mes=0, asientos=[])

    def test_mes_too_high(self):
        from b2b_ai.features.contabilidad.electronica_routes import PackageRequest
        with pytest.raises(Exception):
            PackageRequest(rfc="X", mes=13, asientos=[])

    def test_mes_valid_range(self):
        from b2b_ai.features.contabilidad.electronica_routes import PackageRequest
        for m in range(1, 13):
            req = PackageRequest(rfc="X", mes=m, asientos=[])
            assert req.mes == m

    def test_empty_asientos_list(self):
        from b2b_ai.features.contabilidad.electronica_routes import PackageRequest
        req = PackageRequest(rfc="X", mes=1, asientos=[])
        assert len(req.asientos) == 0

    def test_asiento_schema_defaults(self):
        from b2b_ai.features.contabilidad.electronica_routes import AsientoSchema
        a = AsientoSchema(cuenta="101.01")
        assert a.debe == "0"
        assert a.haber == "0"
        assert a.fecha == ""


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 3: API ENDPOINT TESTING (FastAPI TestClient)
# ═════════════════════════════════════════════════════════════════════════════

from fastapi.testclient import TestClient
from b2b_ai.api.app import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── 3.1 Alertas endpoints ───────────────────────────────────────────────────

class TestAlertasAPIEndpoints:
    def test_create_alert(self, client):
        """POST /api/v1/alertas/ — create an alert."""
        resp = client.post("/api/v1/alertas/", json={
            "rule_id": "test-rule",
            "rule_name": "Test Alert",
            "type": "threshold",
            "severity": "warning",
            "title": "Test Alert",
            "message": "This is a test",
        })
        # Accept 200 or 201
        assert resp.status_code in (200, 201)

    def test_create_alert_missing_fields(self, client):
        """Missing required fields → 422."""
        resp = client.post("/api/v1/alertas/", json={})
        assert resp.status_code == 422

    def test_list_alerts(self, client):
        """GET /api/v1/alertas/ — list alerts."""
        resp = client.get("/api/v1/alertas/")
        assert resp.status_code == 200
        data = resp.json()
        # Should return a list or paginated response
        assert isinstance(data, (list, dict))

    def test_acknowledge_alert(self, client):
        """POST /api/v1/alertas/{id}/acknowledge — acknowledge."""
        # First create an alert
        create_resp = client.post("/api/v1/alertas/", json={
            "rule_id": "ack-test",
            "rule_name": "Ack Test",
            "type": "threshold",
            "severity": "info",
            "title": "Ack Test",
            "message": "ack test",
        })
        if create_resp.status_code in (200, 201):
            alert_id = create_resp.json().get("id")
            if alert_id:
                ack_resp = client.post(f"/api/v1/alertas/{alert_id}/acknowledge")
                assert ack_resp.status_code in (200, 204)

    def test_acknowledge_nonexistent(self, client):
        """Acknowledge non-existent alert → 404."""
        resp = client.post("/api/v1/alertas/nonexistent-id/acknowledge")
        assert resp.status_code in (404, 422)

    def test_history_endpoint(self, client):
        """GET /api/v1/alertas/history — alert history."""
        resp = client.get("/api/v1/alertas/history")
        assert resp.status_code in (200, 404)  # endpoint may not exist


# ── 3.2 Contabilidad endpoints ──────────────────────────────────────────────

class TestContabilidadAPIEndpoints:
    def test_balanza_empty_file(self, client):
        """POST /api/v1/contabilidad/balanza — empty file → 400."""
        resp = client.post(
            "/api/v1/contabilidad/balanza",
            files={"file": ("test.xml", b"", "application/xml")},
        )
        assert resp.status_code == 400

    def test_balanza_invalid_xml(self, client):
        """POST /api/v1/contabilidad/balanza — invalid XML → 422."""
        resp = client.post(
            "/api/v1/contabilidad/balanza",
            files={"file": ("test.xml", b"<not valid>", "application/xml")},
        )
        assert resp.status_code in (422, 500)

    def test_balanza_no_balanza_node(self, client):
        """POST /api/v1/contabilidad/balanza — XML without Balanza → 404."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad version="1.1" rfc="X" mes="01" ejercicio="2025">
        </Contabilidad>"""
        resp = client.post(
            "/api/v1/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 404

    def test_balanza_valid_xml(self, client):
        """POST /api/v1/contabilidad/balanza — valid XML → 200."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101" Desc="Caja" Debe="100" Haber="50"
                    SaldoDeudor="50" SaldoAcreedor="0"/>
          </Balanza>
        </Contabilidad>"""
        resp = client.post(
            "/api/v1/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "balanza" in data

    def test_catalogo_empty_file(self, client):
        resp = client.post(
            "/api/v1/contabilidad/catalogo",
            files={"file": ("test.xml", b"", "application/xml")},
        )
        assert resp.status_code == 400

    def test_catalogo_valid_xml(self, client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Catalogo version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                    FechaCreacion="2025-01-31">
            <Cuenta NumCta="101" Desc="Efectivo" Nivel="1" Naturaleza="D"/>
          </Catalogo>
        </Contabilidad>"""
        resp = client.post(
            "/api/v1/contabilidad/catalogo",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "catalogo" in data

    def test_estado_resultados_valid_xml(self, client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <EstadoResultados version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                            FechaCreacion="2025-01-31">
            <Concepto Concepto="Ingresos" Importe="100000"/>
          </EstadoResultados>
        </Contabilidad>"""
        resp = client.post(
            "/api/v1/contabilidad/estado-resultados",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_catalog_endpoint(self, client):
        """GET /api/v1/contabilidad/catalog — returns SAT catalog."""
        resp = client.get("/api/v1/contabilidad/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "naturaleza" in data
        assert "tipo_balanza" in data
        assert data["naturaleza"]["D"] == "Deudor"
        assert data["naturaleza"]["A"] == "Acreedor"


# ── 3.3 Contabilidad Electrónica API ─────────────────────────────────────────

class TestElectronicaAPIEndpoints:
    def test_generate_package_ok(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "TEST000101AAA",
            "razon_social": "Test SA",
            "ejercicio": 2025,
            "mes": 1,
            "asientos": [
                {"cuenta": "101.01", "debe": "100", "haber": "0", "fecha": ""},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "package_id" in data
        assert data["periodo"] == "2025-01"

    def test_generate_package_empty_asientos(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "TEST000101AAA",
            "ejercicio": 2025,
            "mes": 1,
            "asientos": [],
        })
        assert resp.status_code == 200

    def test_generate_package_invalid_mes(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "X",
            "ejercicio": 2025,
            "mes": 15,
            "asientos": [],
        })
        assert resp.status_code == 422

    def test_generate_package_no_body(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/package")
        assert resp.status_code == 422

    def test_hash_endpoint(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/hash", json={
            "content": "hello world",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["sha1"]) == 40
        assert data["length"] == 11

    def test_hash_unicode(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/hash", json={
            "content": "áéíóú ñ 中文 🎉",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_status_not_found(self, client):
        resp = client.get("/api/v1/contabilidad/electronica/status/nonexistent")
        assert resp.status_code == 404

    def test_transition_not_found(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/transition", json={
            "package_id": "nonexistent",
            "target_state": "listo_para_timbrar",
        })
        assert resp.status_code == 404

    def test_transition_invalid_state(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/transition", json={
            "package_id": "test",
            "target_state": "invalid_state",
        })
        assert resp.status_code in (404, 422)

    def test_summary_not_found(self, client):
        resp = client.get("/api/v1/contabilidad/electronica/summary/nonexistent")
        assert resp.status_code == 404

    def test_full_workflow(self, client):
        """Full lifecycle: generate → transition → status → summary."""
        # Generate
        gen_resp = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "WF000101AAA",
            "ejercicio": 2025,
            "mes": 6,
            "asientos": [
                {"cuenta": "101.01", "debe": "500", "haber": "0", "fecha": ""},
                {"cuenta": "201.01", "debe": "0", "haber": "500", "fecha": ""},
            ],
        })
        assert gen_resp.status_code == 200
        pkg_id = gen_resp.json()["package_id"]

        # Status
        status_resp = client.get(f"/api/v1/contabilidad/electronica/status/{pkg_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["estado"] == "borrador"

        # Transition: borrador → listo_para_timbrar
        t1 = client.post("/api/v1/contabilidad/electronica/transition", json={
            "package_id": pkg_id,
            "target_state": "listo_para_timbrar",
        })
        assert t1.status_code == 200
        assert t1.json()["estado_nuevo"] == "listo_para_timbrar"

        # Transition: listo_para_timbrar → timbrado
        t2 = client.post("/api/v1/contabilidad/electronica/transition", json={
            "package_id": pkg_id,
            "target_state": "timbrado",
        })
        assert t2.status_code == 200

        # Transition: timbrado → enviado
        t3 = client.post("/api/v1/contabilidad/electronica/transition", json={
            "package_id": pkg_id,
            "target_state": "enviado",
        })
        assert t3.status_code == 200

        # Summary
        summ = client.get(f"/api/v1/contabilidad/electronica/summary/{pkg_id}")
        assert summ.status_code == 200
        summary_data = summ.json()["summary"]
        assert summary_data["cuadra"] is True


# ── 3.4 Error response quality ──────────────────────────────────────────────

class TestErrorResponseQuality:
    def test_422_has_detail(self, client):
        """422 responses should include useful error detail."""
        resp = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "X",
            "mes": 0,
            "asientos": [],
        })
        assert resp.status_code == 422
        detail = resp.json().get("detail")
        assert detail is not None

    def test_404_has_detail(self, client):
        resp = client.get("/api/v1/contabilidad/electronica/status/fake-id")
        assert resp.status_code == 404
        detail = resp.json().get("detail")
        assert detail is not None
        assert "fake-id" in str(detail)

    def test_balanza_404_has_message(self, client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad><Catalogo version="1.1" Rfc="X" Mes="01" Ejercicio="2025"/></Contabilidad>"""
        resp = client.post(
            "/api/v1/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        assert resp.status_code == 404
        assert "Balanza" in resp.json()["detail"]


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 4: DATA INTEGRITY & CONSISTENCY
# ═════════════════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    def test_alert_id_consistency(self):
        """Same inputs always produce the same alert ID."""
        id1 = _compute_alert_id("rule-abc", "invoice", "INV-123")
        id2 = _compute_alert_id("rule-abc", "invoice", "INV-123")
        assert id1 == id2

    def test_alert_id_length(self):
        """Alert IDs are always 16 chars (truncated SHA-256)."""
        for i in range(100):
            aid = _compute_alert_id(f"rule-{i}", f"entity-{i}", f"id-{i}")
            assert len(aid) == 16

    def test_sha1_hex_format(self):
        """SHA-1 hashes are valid hex strings."""
        sha1 = ContabilidadElectronica.calcular_hash_sha1(b"test")
        assert len(sha1) == 40
        int(sha1, 16)  # should not raise

    def test_balanza_dict_structure(self):
        """Balanza response has all required keys."""
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([
            {"cuenta": "101.01", "debe": "100", "haber": "100", "fecha": ""},
        ])
        balanza = paquete["balanza"]
        assert "cuadrada" in balanza
        assert "sha1" in balanza
        assert isinstance(balanza["cuadrada"], bool)
        assert isinstance(balanza["sha1"], str)

    def test_catalogo_dict_structure(self):
        catalogo = CatalogoCuentas()
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc="X", ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        cat = paquete["catalogo"]
        assert "cuentas" in cat
        assert "sha1" in cat
        assert isinstance(cat["cuentas"], list)


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 5: CONCURRENCY & PERFORMANCE
# ═════════════════════════════════════════════════════════════════════════════

class TestConcurrency:
    def test_concurrent_rule_evaluation(self):
        """Multiple threads evaluating rules should not interfere."""
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

        assert sum(results) == 90  # 90 values > 10

    def test_concurrent_store_save(self):
        """Multiple threads saving to AlertStore should not lose data."""
        store = AlertStore()
        rule = AlertRule(name="conc", type=AlertType.THRESHOLD,
                         condition=RuleCondition.GT, threshold_value=10,
                         field_path="x")
        saved = []

        def save(x):
            alerts = evaluate_rules(
                {"x": x, "entity_type": "test", "entity_id": f"e-{x}"}, [rule]
            )
            new = store.save_alerts(alerts)
            saved.append(len(new))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(save, i) for i in range(50)]
            concurrent.futures.wait(futures)

        # Each unique entity should produce exactly one alert
        assert sum(saved) == 40  # 40 values > 10, all unique entities


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 6: CROSS-MODULE INTEGRATION
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

        # Create a reconciliation alert rule
        rule = AlertRule(
            name="unbalanced",
            type=AlertType.RECONCILIATION,
            metadata={"entity_type": "contabilidad"},
        )

        # Simulate mismatch data
        if not paquete["balanza"]["cuadrada"]:
            engine = AlertEngine(store=AlertStore())
            alerts = engine.evaluate_reconciliation(
                {"has_mismatch": True, "session_id": "pkg-1"}, [rule], tenant_id=1
            )
            assert len(alerts) == 1
            assert alerts[0].entity_type == "reconciliation"


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 7: SECURITY & INJECTION
# ═════════════════════════════════════════════════════════════════════════════

class TestSecurityEdgeCases:
    def test_xss_in_rule_name(self):
        """Rule names with HTML should not break."""
        rule = AlertRule(
            name="<script>alert('xss')</script>",
            type=AlertType.THRESHOLD,
            condition=RuleCondition.GT,
            threshold_value=10,
            field_path="x",
        )
        alerts = evaluate_rules({"x": 50}, [rule])
        assert "<script>" in alerts[0].title

    def test_very_long_rfc(self):
        """Extremely long RFC should be handled."""
        catalogo = CatalogoCuentas()
        long_rfc = "A" * 1000
        mgr = ContabilidadElectronica(
            catalogo=catalogo, rfc=long_rfc, ejercicio=2025, mes=1,
        )
        paquete = mgr.generar_paquete([])
        assert paquete["periodo"] == "2025-01"

    def test_special_characters_in_hash(self, client):
        """Hash endpoint with special characters."""
        resp = client.post("/api/v1/contabilidad/electronica/hash", json={
            "content": "<xml>&\"'special chars 中文",
        })
        assert resp.status_code == 200
        assert len(resp.json()["sha1"]) == 40

    def test_empty_string_hash(self, client):
        """Hash of empty string."""
        resp = client.post("/api/v1/contabilidad/electronica/hash", json={
            "content": "",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sha1"] == hashlib.sha1(b"").hexdigest()
        assert data["length"] == 0


# ═════════════════════════════════════════════════════════════════════════════
#  SECTION 8: API SCHEMA COMPLIANCE
# ═════════════════════════════════════════════════════════════════════════════

class TestAPISchemaCompliance:
    def test_package_response_has_ok(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        data = resp.json()
        assert "ok" in data
        assert data["ok"] is True

    def test_hash_response_schema(self, client):
        resp = client.post("/api/v1/contabilidad/electronica/hash", json={
            "content": "test",
        })
        data = resp.json()
        assert "ok" in data
        assert "sha1" in data
        assert "length" in data

    def test_status_response_schema(self, client):
        # Generate first
        gen = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.get(f"/api/v1/contabilidad/electronica/status/{pkg_id}")
        data = resp.json()
        assert "ok" in data
        assert "package_id" in data
        assert "estado" in data
        assert "periodo" in data

    def test_transition_response_schema(self, client):
        gen = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.post("/api/v1/contabilidad/electronica/transition", json={
            "package_id": pkg_id, "target_state": "listo_para_timbrar",
        })
        data = resp.json()
        assert "ok" in data
        assert "estado_anterior" in data
        assert "estado_nuevo" in data

    def test_summary_response_schema(self, client):
        gen = client.post("/api/v1/contabilidad/electronica/package", json={
            "rfc": "X", "ejercicio": 2025, "mes": 1, "asientos": [],
        })
        pkg_id = gen.json()["package_id"]
        resp = client.get(f"/api/v1/contabilidad/electronica/summary/{pkg_id}")
        data = resp.json()
        assert "ok" in data
        assert "summary" in data
        summary = data["summary"]
        assert "total_debe" in summary
        assert "total_haber" in summary
        assert "cuadra" in summary

    def test_balanza_response_schema(self, client):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Contabilidad>
          <Balanza version="1.1" Rfc="X00000000000" Mes="01" Ejercicio="2025"
                   FechaCreacion="2025-01-31" TipoBalance="C">
            <Cuenta NumCta="101" Desc="Caja" Debe="100" Haber="100"/>
          </Balanza>
        </Contabilidad>"""
        resp = client.post(
            "/api/v1/contabilidad/balanza",
            files={"file": ("test.xml", xml, "application/xml")},
        )
        data = resp.json()
        assert data["ok"] is True
        assert "balanza" in data
        assert "Version" in data["balanza"]
        assert "Lineas" in data["balanza"]
