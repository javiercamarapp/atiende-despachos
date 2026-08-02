# -*- coding: utf-8 -*-
"""Tests for the anomaly detector (duplicates, range, unstamped, UUID gaps)."""
from datetime import datetime, timedelta, timezone

from b2b_ai.features.alertas.anomaly_detector import (
    AnomalyDetector,
    AnomalyThresholds,
)
from b2b_ai.features.alertas.models import AlertSeverity

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _inv(**kw):
    base = {"uuid": None, "emisor_rfc": None, "receptor_rfc": None, "total": None}
    base.update(kw)
    return base


class TestDuplicates:
    def test_exact_uuid_duplicate_critical(self):
        d = AnomalyDetector(now=NOW)
        invs = [
            _inv(uuid="U1", emisor_rfc="R1", fecha="2026-08-01T10:00:00"),
            _inv(uuid="U1", emisor_rfc="R1", fecha="2026-08-02T09:00:00"),
        ]
        alerts = d.detect_duplicates(invs)
        critical = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        assert critical, "duplicate UUID must be critical"

    def test_uuid_duplicate_outside_window_not_flagged(self):
        d = AnomalyDetector(now=NOW, thresholds=AnomalyThresholds(dup_window_hours=24))
        invs = [
            _inv(uuid="U1", emisor_rfc="R1", fecha="2026-07-01T10:00:00"),
            _inv(uuid="U1", emisor_rfc="R1", fecha="2026-08-02T09:00:00"),
        ]
        assert d.detect_duplicates(invs) == []

    def test_logical_duplicate_same_emisor_receptor_amount(self):
        d = AnomalyDetector(now=NOW)
        invs = [
            _inv(uuid="A1", emisor_rfc="R1", receptor_rfc="X", total=1000,
                 fecha="2026-08-01T10:00:00"),
            _inv(uuid="A2", emisor_rfc="R1", receptor_rfc="X", total=1000,
                 fecha="2026-08-02T10:00:00"),
        ]
        alerts = d.detect_duplicates(invs)
        logical = [a for a in alerts if a.metadata.get("detector") == "duplicate_logical"]
        assert logical

    def test_distinct_invoices_no_duplicate(self):
        d = AnomalyDetector(now=NOW)
        invs = [
            _inv(uuid="B1", emisor_rfc="R1", total=100, fecha="2026-08-01T10:00:00"),
            _inv(uuid="B2", emisor_rfc="R1", total=200, fecha="2026-08-02T10:00:00"),
        ]
        assert d.detect_duplicates(invs) == []


class TestOutOfRange:
    def test_flag_when_beyond_stdev(self):
        d = AnomalyDetector()
        hist = [90, 110, 95, 105, 98, 102]
        invs = [_inv(uuid="C1", emisor_rfc="R1", total=5000)]
        alerts = d.detect_out_of_range(invs, hist)
        assert alerts
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_no_flag_within_range(self):
        d = AnomalyDetector()
        hist = [90, 110, 95, 105, 98, 102]
        invs = [_inv(uuid="C1", emisor_rfc="R1", total=100)]
        assert d.detect_out_of_range(invs, hist) == []

    def test_requires_min_history(self):
        d = AnomalyDetector(thresholds=AnomalyThresholds(range_min_history=3))
        assert d.detect_out_of_range([_inv(total=9999)], [100, 200]) == []

    def test_zero_variance_skips(self):
        d = AnomalyDetector()
        assert d.detect_out_of_range([_inv(total=9999)], [100, 100, 100]) == []


class TestUnstamped:
    def test_unstamped_over_24h_warning(self):
        old = (NOW - timedelta(hours=30)).isoformat()
        d = AnomalyDetector(now=NOW)
        invs = [_inv(uuid="D1", emisor_rfc="R1", fecha=old, status="pendiente")]
        alerts = d.detect_unstamped(invs)
        assert alerts
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_unstamped_over_72h_critical(self):
        old = (NOW - timedelta(hours=100)).isoformat()
        d = AnomalyDetector(now=NOW)
        invs = [_inv(uuid="D1", emisor_rfc="R1", fecha=old)]
        alerts = d.detect_unstamped(invs)
        assert alerts
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_stamped_invoice_not_flagged(self):
        d = AnomalyDetector(now=NOW)
        invs = [_inv(uuid="D1", emisor_rfc="R1", fecha="2026-07-01T00:00:00",
                     status="timbrado")]
        assert d.detect_unstamped(invs) == []

    def test_recent_unsamped_not_flagged(self):
        recent = (NOW - timedelta(hours=2)).isoformat()
        d = AnomalyDetector(now=NOW)
        assert d.detect_unstamped([_inv(uuid="D1", emisor_rfc="R1", fecha=recent)]) == []


class TestUUIDGaps:
    def test_gap_detected(self):
        d = AnomalyDetector()
        invs = [
            _inv(uuid="FOL000001", emisor_rfc="R1"),
            _inv(uuid="FOL000003", emisor_rfc="R1"),
        ]
        alerts = d.detect_uuid_gaps(invs)
        assert len(alerts) == 1
        assert "gap" in alerts[0].message.lower()

    def test_sequential_no_gap(self):
        d = AnomalyDetector()
        invs = [
            _inv(uuid="FOL000001", emisor_rfc="R1"),
            _inv(uuid="FOL000002", emisor_rfc="R1"),
            _inv(uuid="FOL000003", emisor_rfc="R1"),
        ]
        assert d.detect_uuid_gaps(invs) == []

    def test_gaps_isolated_per_emisor(self):
        d = AnomalyDetector()
        invs = [
            _inv(uuid="A000001", emisor_rfc="R1"),
            _inv(uuid="A000003", emisor_rfc="R1"),   # gap
            _inv(uuid="B000001", emisor_rfc="R2"),
            _inv(uuid="B000002", emisor_rfc="R2"),   # no gap
        ]
        alerts = d.detect_uuid_gaps(invs)
        assert len(alerts) == 1


class TestPerTenantThresholds:
    def test_tenant_specific_threshold(self):
        relaxed = AnomalyThresholds(dup_window_hours=720)  # 30 days
        d = AnomalyDetector(tenant_thresholds={42: relaxed})
        invs = [
            _inv(uuid="U1", emisor_rfc="R1", fecha="2026-07-01T10:00:00"),
            _inv(uuid="U1", emisor_rfc="R1", fecha="2026-07-25T10:00:00"),  # 24d
        ]
        # Tenant 42 with 30-day window -> duplicate
        assert d.detect_duplicates(invs, tenant_id=42)
        # Default tenant keeps 72h window -> no duplicate
        assert d.detect_duplicates(invs, tenant_id=1) == []

    def test_thresholds_from_dict(self):
        t = AnomalyThresholds.from_dict({"dup_window_hours": 10, "bogus": 1})
        assert t.dup_window_hours == 10


class TestFullDetect:
    def test_detect_runs_all_detectors(self):
        d = AnomalyDetector(now=NOW)
        hist = [90, 110, 95, 105]
        invs = [
            _inv(uuid="Z000001", emisor_rfc="R1", total=1000,  # out of range
                 fecha="2026-08-01T10:00:00", status="timbrado"),
            _inv(uuid="Z000001", emisor_rfc="R1", total=1000,  # duplicate UUID
                 fecha="2026-08-02T09:00:00", status="timbrado"),
        ]
        alerts = d.detect(invs, historical_amounts=hist, tenant_id=1)
        assert alerts
        assert all(a.tenant_id == 1 for a in alerts)

    def test_alert_fields_present(self):
        d = AnomalyDetector(now=NOW)
        invs = [_inv(uuid="Q000001", emisor_rfc="R1", total=5000, fecha="2026-08-01")]
        alerts = d.detect(invs, historical_amounts=[90, 110, 95, 105])
        for a in alerts:
            assert a.id
            assert a.message
            assert a.severity in (AlertSeverity.CRITICAL, AlertSeverity.WARNING,
                                  AlertSeverity.INFO)
