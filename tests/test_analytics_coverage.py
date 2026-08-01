# -*- coding: utf-8 -*-
"""
tests/test_analytics_coverage.py — Targeted tests to close the remaining
coverage gaps in b2b_ai/api/analytics.py (lines 209, 235-237, 287-288, 293).

These are all loop bodies that execute when DB calls return non-empty lists.
We use simple mock DB objects so the tests are fast and deterministic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from b2b_ai.api.analytics import (
    _collections_metrics,
    _reconciliation_metrics,
    _report_metrics,
)


def _mock_db(**overrides):
    """Create a mock DB with sensible defaults."""
    db = MagicMock()
    db.list_outstanding_invoices.return_value = []
    db.list_collection_events.return_value = []
    db.list_asientos_contables.return_value = []
    db.list_cuentas_contables.return_value = []
    db.list_balanzas_mensuales.return_value = []
    db.count_audit.return_value = 0
    db.list_notifications.return_value = []
    db.list_reviews.return_value = []
    db.count_pending_reviews.return_value = 0
    for k, v in overrides.items():
        getattr(db, k).return_value = v
    return db


# ---------------------------------------------------------------------------
# Line 209: eventos_por_tipo loop in _collections_metrics
# ---------------------------------------------------------------------------

class TestCollectionsEventsLoop:
    """Cover line 209 — the events loop body in _collections_metrics."""

    def test_collection_events_by_type(self):
        db = _mock_db(
            list_collection_events=[
                {"tipo_recordatorio": "email", "canal": "smtp"},
                {"tipo_recordatorio": "email", "canal": "smtp"},
                {"tipo_recordatorio": "llamada", "canal": "phone"},
            ],
        )
        result = _collections_metrics(db, tenant_id=1)
        assert result["total_intentos_cobranza"] == 3
        assert result["eventos_por_tipo"]["email"] == 2
        assert result["eventos_por_tipo"]["llamada"] == 1

    def test_collection_events_missing_tipo(self):
        """When tipo_recordatorio is missing, default 'otro' is used."""
        db = _mock_db(
            list_collection_events=[
                {"canal": "sms"},  # no tipo_recordatorio
            ],
        )
        result = _collections_metrics(db, tenant_id=1)
        assert result["eventos_por_tipo"]["otro"] == 1


# ---------------------------------------------------------------------------
# Lines 235-237: periodos_balanza loop in _reconciliation_metrics
# ---------------------------------------------------------------------------

class TestReconciliationBalanzaLoop:
    """Cover lines 235-237 — the balanzas loop body in _reconciliation_metrics."""

    def test_balanza_with_period(self):
        db = _mock_db(
            list_balanzas_mensuales=[
                {"periodo": "2026-07", "cuenta_id": "101.01", "saldo_final": "5000"},
                {"periodo": "2026-07", "cuenta_id": "201.01", "saldo_final": "3000"},
                {"periodo": "2026-06", "cuenta_id": "101.01", "saldo_final": "4000"},
            ],
        )
        result = _reconciliation_metrics(db, tenant_id=1)
        assert "2026-07" in result["periodos_con_balanza"]
        assert "2026-06" in result["periodos_con_balanza"]
        assert len(result["periodos_con_balanza"]) == 2

    def test_balanza_empty_period_skipped(self):
        """Empty periodo string should not be added to the set."""
        db = _mock_db(
            list_balanzas_mensuales=[
                {"periodo": "", "cuenta_id": "101.01"},
                {"periodo": "2026-07", "cuenta_id": "101.01"},
            ],
        )
        result = _reconciliation_metrics(db, tenant_id=1)
        assert result["periodos_con_balanza"] == ["2026-07"]


# ---------------------------------------------------------------------------
# Lines 287-288: notification loop in _report_metrics
# ---------------------------------------------------------------------------

class TestReportNotificationsLoop:
    """Cover lines 287-288 — the notifications loop body in _report_metrics."""

    def test_notifications_by_channel_and_status(self):
        db = _mock_db(
            list_notifications=[
                {"channel": "email", "status": "sent"},
                {"channel": "email", "status": "error"},
                {"channel": "sms", "status": "sent"},
            ],
        )
        result = _report_metrics(db, tenant_id=1)
        assert result["total_notificaciones"] == 3
        assert result["notificaciones_por_canal"]["email"] == 2
        assert result["notificaciones_por_canal"]["sms"] == 1
        assert result["notificaciones_por_estado"]["sent"] == 2
        assert result["notificaciones_por_estado"]["error"] == 1

    def test_notifications_missing_channel_and_status(self):
        """Missing channel/status should default to 'unknown'."""
        db = _mock_db(
            list_notifications=[
                {},  # no channel, no status
            ],
        )
        result = _report_metrics(db, tenant_id=1)
        assert result["notificaciones_por_canal"]["unknown"] == 1
        assert result["notificaciones_por_estado"]["unknown"] == 1


# ---------------------------------------------------------------------------
# Line 293: reviews loop in _report_metrics
# ---------------------------------------------------------------------------

class TestReportReviewsLoop:
    """Cover line 293 — the reviews loop body in _report_metrics."""

    def test_reviews_by_status(self):
        db = _mock_db(
            list_reviews=[
                {"status": "pending", "reason": "check"},
                {"status": "pending", "reason": "check"},
                {"status": "resolved", "reason": "ok"},
            ],
        )
        result = _report_metrics(db, tenant_id=1)
        assert result["total_revisiones"] == 3
        assert result["revisiones_por_estado"]["pending"] == 2
        assert result["revisiones_por_estado"]["resolved"] == 1

    def test_reviews_missing_status(self):
        """Missing status should default to 'unknown'."""
        db = _mock_db(
            list_reviews=[
                {},  # no status
            ],
        )
        result = _report_metrics(db, tenant_id=1)
        assert result["revisiones_por_estado"]["unknown"] == 1
