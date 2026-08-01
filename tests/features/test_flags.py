# -*- coding: utf-8 -*-
"""Tests for b2b_ai/features/flags.py — feature flags with DB."""
import pytest
from b2b_ai.db.db import Database
from b2b_ai.features.flags import FeatureFlags, FEATURE_DEFAULTS


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    d = Database(":memory:")
    return d


@pytest.fixture
def ff(db):
    return FeatureFlags(db)


class TestFeatureFlagsDefaults:
    def test_known_features(self):
        assert "portal_cliente" in FEATURE_DEFAULTS
        assert "cobranza_automatizada" in FEATURE_DEFAULTS

    def test_portal_default_enabled(self):
        assert FEATURE_DEFAULTS["portal_cliente"] is True

    def test_cobranza_default_disabled(self):
        assert FEATURE_DEFAULTS["cobranza_automatizada"] is False


class TestIsEnabled:
    def test_default_when_no_override(self, ff, db):
        tenant = db.create_tenant("Test", "")
        assert ff.is_enabled("portal_cliente", tenant) is True
        assert ff.is_enabled("cobranza_automatizada", tenant) is False

    def test_enable_override(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.enable("cobranza_automatizada", tenant)
        assert ff.is_enabled("cobranza_automatizada", tenant) is True

    def test_disable_override(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.disable("portal_cliente", tenant)
        assert ff.is_enabled("portal_cliente", tenant) is False

    def test_global_override(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.enable("cobranza_automatizada", None)  # global
        assert ff.is_enabled("cobranza_automatizada", tenant) is True

    def test_tenant_override_beats_global(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.enable("cobranza_automatizada", None)  # global on
        ff.disable("cobranza_automatizada", tenant)  # tenant off
        assert ff.is_enabled("cobranza_automatizada", tenant) is False

    def test_unknown_feature_defaults_false(self, ff, db):
        tenant = db.create_tenant("Test", "")
        assert ff.is_enabled("nonexistent_feature", tenant) is False


class TestRollout:
    def test_rollout_100_always_enabled(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.enable("test_feature", tenant, rollout_percentage=100)
        assert ff.is_enabled("test_feature", tenant) is True

    def test_rollout_0_always_disabled(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.enable("test_feature", tenant, rollout_percentage=0)
        assert ff.is_enabled("test_feature", tenant) is False

    def test_rollout_deterministic(self, ff, db):
        """Same tenant always gets same bucket."""
        tenant = db.create_tenant("Test", "")
        ff.enable("test_feature", tenant, rollout_percentage=50)
        results = [ff.is_enabled("test_feature", tenant) for _ in range(10)]
        assert all(r == results[0] for r in results)


class TestGetAllFlags:
    def test_basic(self, ff, db):
        tenant = db.create_tenant("Test", "")
        flags = ff.get_all_flags(tenant)
        assert isinstance(flags, list)
        assert len(flags) > 0

    def test_source_default(self, ff, db):
        tenant = db.create_tenant("Test", "")
        flags = ff.get_all_flags(tenant)
        portal = [f for f in flags if f["name"] == "portal_cliente"]
        assert portal[0]["source"] == "default"

    def test_source_tenant(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.enable("portal_cliente", tenant)
        flags = ff.get_all_flags(tenant)
        portal = [f for f in flags if f["name"] == "portal_cliente"]
        assert portal[0]["source"] == "tenant"
        assert portal[0]["enabled"] is True


class TestSeedDefaults:
    def test_seed(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.seed_defaults(tenant)
        flags = ff.get_all_flags(tenant)
        assert len(flags) >= len(FEATURE_DEFAULTS)

    def test_seed_idempotent(self, ff, db):
        tenant = db.create_tenant("Test", "")
        ff.seed_defaults(tenant)
        ff.seed_defaults(tenant)
        flags = ff.get_all_flags(tenant)
        # No duplicates
        names = [f["name"] for f in flags]
        assert len(names) == len(set(names))
