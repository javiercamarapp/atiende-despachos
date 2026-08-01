# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/analytics.py — analytics and TTL cache."""
import pytest
import time
from b2b_ai.services.analytics import build_analytics, TTLCache


class TestBuildAnalytics:
    def test_basic(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "1000.00", "valido": True,
             "emisor_rfc": "RFC1", "emisor_nombre": "Proveedor A"},
        ]
        r = build_analytics(invoices, periodo="2026-07")
        assert r["periodo"] == "2026-07"
        assert r["validez"]["validas"] == 1

    def test_empty(self):
        r = build_analytics([])
        assert r["validez"]["total"] == 0

    def test_filters(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "1000.00", "valido": True},
            {"fecha": "2026-08-03", "total": "2000.00", "valido": True},
        ]
        r = build_analytics(invoices, periodo="2026-07")
        assert r["validez"]["total"] == 1

    def test_por_proveedor(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "1000.00",
             "emisor_rfc": "RFC1", "emisor_nombre": "Prov A"},
            {"fecha": "2026-07-05", "total": "2000.00",
             "emisor_rfc": "RFC2", "emisor_nombre": "Prov B"},
        ]
        r = build_analytics(invoices)
        assert len(r["por_proveedor"]) == 2

    def test_tendencia_mensual(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "1000.00"},
            {"fecha": "2026-07-05", "total": "2000.00"},
        ]
        r = build_analytics(invoices)
        assert "2026-07" in r["tendencia_mensual"]
        assert r["tendencia_mensual"]["2026-07"]["count"] == 2


class TestTTLCache:
    def test_get_set(self):
        c = TTLCache(ttl_seconds=10)
        c.set("key1", "value1")
        assert c.get("key1") == "value1"

    def test_miss(self):
        c = TTLCache()
        assert c.get("nonexistent") is None

    def test_ttl_expires(self):
        c = TTLCache(ttl_seconds=0.01)
        c.set("key1", "value1")
        time.sleep(0.02)
        assert c.get("key1") is None

    def test_get_or_compute(self):
        c = TTLCache()
        val, hit = c.get_or_compute("k", lambda: 42)
        assert val == 42
        assert hit is False
        val, hit = c.get_or_compute("k", lambda: 99)
        assert val == 42
        assert hit is True

    def test_invalidate_all(self):
        c = TTLCache()
        c.set("a", 1)
        c.set("b", 2)
        c.invalidate()
        assert c.get("a") is None

    def test_invalidate_prefix(self):
        c = TTLCache()
        c.set("analytics:tenant1", 1)
        c.set("analytics:tenant2", 2)
        c.set("audit:tenant1", 3)
        c.invalidate("analytics:")
        assert c.get("analytics:tenant1") is None
        assert c.get("audit:tenant1") == 3

    def test_stats(self):
        c = TTLCache(ttl_seconds=60)
        c.set("a", 1)
        s = c.stats
        assert s["entries"] == 1
        assert s["ttl"] == 60
