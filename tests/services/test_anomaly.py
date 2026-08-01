# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/anomaly.py — anomaly detection."""
import pytest
from b2b_ai.services.anomaly import (
    detect_anomalies, summarize_anomalies, _dec, _close,
)


class TestDecHelper:
    def test_normal(self):
        assert _dec("100.50") == 100.5

    def test_with_commas(self):
        assert _dec("1,234.56") == 1234.56

    def test_none(self):
        assert _dec(None) is None

    def test_garbage(self):
        assert _dec("abc") is None


class TestClose:
    def test_equal(self):
        assert _close(100.0, 100.0) is True

    def test_within_tolerance(self):
        assert _close(100.0, 100.005) is True

    def test_outside_tolerance(self):
        assert _close(100.0, 100.1) is False

    def test_none_values(self):
        assert _close(None, 100.0) is False
        assert _close(100.0, None) is False


class TestDuplicateDetection:
    def test_duplicate_detected(self):
        invoice = {"emisor_rfc": "RFC1", "total": "1000.00",
                   "fecha": "2026-07-03", "folio_fiscal": "F1"}
        historical = [{"emisor_rfc": "RFC1", "total": "1000.00",
                       "fecha": "2026-07-03", "folio_fiscal": "F1"}]
        anomalies = detect_anomalies(invoice, historical)
        types = [a["tipo"] for a in anomalies]
        assert "duplicado" in types

    def test_no_duplicate_different_rfc(self):
        invoice = {"emisor_rfc": "RFC1", "total": "1000.00",
                   "fecha": "2026-07-03"}
        historical = [{"emisor_rfc": "RFC2", "total": "1000.00",
                       "fecha": "2026-07-03"}]
        anomalies = detect_anomalies(invoice, historical)
        assert not any(a["tipo"] == "duplicado" for a in anomalies)

    def test_no_duplicate_outside_date_window(self):
        invoice = {"emisor_rfc": "RFC1", "total": "1000.00",
                   "fecha": "2026-07-03"}
        historical = [{"emisor_rfc": "RFC1", "total": "1000.00",
                       "fecha": "2026-07-10"}]
        anomalies = detect_anomalies(invoice, historical)
        assert not any(a["tipo"] == "duplicado" for a in anomalies)

    def test_duplicate_folio_mismatch_not_flagged(self):
        """Different folio_fiscal = not duplicate."""
        invoice = {"emisor_rfc": "RFC1", "total": "1000.00",
                   "fecha": "2026-07-03", "folio_fiscal": "F1"}
        historical = [{"emisor_rfc": "RFC1", "total": "1000.00",
                       "fecha": "2026-07-03", "folio_fiscal": "F2"}]
        anomalies = detect_anomalies(invoice, historical)
        assert not any(a["tipo"] == "duplicado" for a in anomalies)


class TestAtypicalAmount:
    def test_atypical_detected(self):
        invoice = {"emisor_rfc": "RFC1", "total": "50000.00",
                   "fecha": "2026-07-03"}
        historical = [
            {"emisor_rfc": "RFC1", "total": "1000.00", "fecha": "2026-06-01"},
            {"emisor_rfc": "RFC1", "total": "1100.00", "fecha": "2026-06-15"},
            {"emisor_rfc": "RFC1", "total": "900.00", "fecha": "2026-06-20"},
        ]
        anomalies = detect_anomalies(invoice, historical)
        assert any(a["tipo"] == "monto_atipico" for a in anomalies)

    def test_not_atypical_with_few_history(self):
        invoice = {"emisor_rfc": "RFC1", "total": "50000.00",
                   "fecha": "2026-07-03"}
        historical = [
            {"emisor_rfc": "RFC1", "total": "1000.00", "fecha": "2026-06-01"},
        ]
        anomalies = detect_anomalies(invoice, historical)
        assert not any(a["tipo"] == "monto_atipico" for a in anomalies)

    def test_not_atypical_with_zero_stdev(self):
        """Same amounts historically = zero stdev."""
        invoice = {"emisor_rfc": "RFC1", "total": "1000.00",
                   "fecha": "2026-07-03"}
        historical = [
            {"emisor_rfc": "RFC1", "total": "1000.00", "fecha": "2026-06-01"},
            {"emisor_rfc": "RFC1", "total": "1000.00", "fecha": "2026-06-15"},
            {"emisor_rfc": "RFC1", "total": "1000.00", "fecha": "2026-06-20"},
        ]
        anomalies = detect_anomalies(invoice, historical)
        assert not any(a["tipo"] == "monto_atipico" for a in anomalies)


class TestIVACheck:
    def test_iva_correct(self):
        invoice = {"subtotal": "1000.00", "iva": "160.00"}
        anomalies = detect_anomalies(invoice)
        assert not any(a["tipo"] == "iva_inconsistente" for a in anomalies)

    def test_iva_wrong(self):
        invoice = {"subtotal": "1000.00", "iva": "100.00"}
        anomalies = detect_anomalies(invoice)
        assert any(a["tipo"] == "iva_inconsistente" for a in anomalies)

    def test_iva_none(self):
        invoice = {"subtotal": "1000.00"}
        anomalies = detect_anomalies(invoice)
        assert not any(a["tipo"] == "iva_inconsistente" for a in anomalies)


class TestNewProvider:
    def test_new_provider_detected(self):
        invoice = {"emisor_rfc": "NEWRFC010101AAA"}
        historical = [{"emisor_rfc": "OLDRFC010101BBB"}]
        anomalies = detect_anomalies(invoice, historical)
        assert any(a["tipo"] == "proveedor_nuevo" for a in anomalies)

    def test_known_provider(self):
        invoice = {"emisor_rfc": "RFC1"}
        historical = [{"emisor_rfc": "RFC1"}]
        anomalies = detect_anomalies(invoice, historical)
        assert not any(a["tipo"] == "proveedor_nuevo" for a in anomalies)


class TestSummarizeAnomalies:
    def test_empty(self):
        r = summarize_anomalies([])
        assert r["total"] == 0
        assert r["max_severity"] is None

    def test_with_anomalies(self):
        anomalies = [
            {"tipo": "duplicado", "severity": "high"},
            {"tipo": "iva_inconsistente", "severity": "medium"},
        ]
        r = summarize_anomalies(anomalies)
        assert r["total"] == 2
        assert r["max_severity"] == "high"
        assert r["por_tipo"]["duplicado"] == 1

    def test_empty_list(self):
        r = summarize_anomalies([])
        assert r["por_tipo"] == {}
        assert r["por_severidad"] == {}
