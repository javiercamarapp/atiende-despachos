# -*- coding: utf-8 -*-
"""test_feature_flags.py — Tests unitarios del módulo de feature flags."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def ff_db(tmp_path):
    """Devuelve una Database temporal con esquema de feature_flags."""
    from b2b_ai.db.db import Database
    return Database(str(tmp_path / "flags_test.db"))


@pytest.fixture
def ff(ff_db):
    from b2b_ai.features.flags import FeatureFlags
    return FeatureFlags(ff_db)


# ---- Models ----

class TestFeatureFlagModel:
    def test_from_row(self):
        from b2b_ai.features.models import FeatureFlag
        row = {"name": "beta", "tenant_id": 1, "enabled": 1,
               "rollout_percentage": 50, "default_enabled": 0,
               "created_at": "2025-01-01"}
        f = FeatureFlag.from_row(row)
        assert f.name == "beta"
        assert f.enabled is True
        assert f.rollout_percentage == 50

    def test_to_dict(self):
        from b2b_ai.features.models import FeatureFlag
        f = FeatureFlag(name="x", enabled=True, rollout_percentage=75)
        d = f.to_dict()
        assert d["name"] == "x"
        assert d["enabled"] is True
        assert d["rollout_percentage"] == 75


# ---- FeatureFlags ----

class TestFeatureFlags:
    def test_enable_disable(self, ff):
        ff.enable("portal_cliente", 1)
        assert ff.is_enabled("portal_cliente", 1) is True
        ff.disable("portal_cliente", 1)
        assert ff.is_enabled("portal_cliente", 1) is False

    def test_default_enabled(self, ff):
        """Sin override, portal_cliente es True por default."""
        assert ff.is_enabled("portal_cliente", 999) is True

    def test_default_disabled(self, ff):
        """Sin override, cobranza_automatizada es False por default."""
        assert ff.is_enabled("cobranza_automatizada", 999) is False

    def test_unknown_feature_defaults_false(self, ff):
        assert ff.is_enabled("nonexistent_feature", 1) is False

    def test_tenant_override(self, ff):
        ff.disable("portal_cliente", 1)
        assert ff.is_enabled("portal_cliente", 1) is False
        # Otro tenant no se ve afectado
        assert ff.is_enabled("portal_cliente", 2) is True

    def test_global_override(self, ff):
        from b2b_ai.features.flags import FEATURE_DEFAULTS
        ff.enable("cobranza_automatizada", None)
        assert ff.is_enabled("cobranza_automatizada", 999) is True

    def test_rollout_partial(self, ff):
        """Con rollout 0%, nadie lo ve; con 100%, todos."""
        ff.enable("billing", 1, rollout_percentage=0)
        assert ff.is_enabled("billing", 1) is False
        ff.enable("billing", 1, rollout_percentage=100)
        assert ff.is_enabled("billing", 1) is True

    def test_rollout_deterministic(self, ff):
        """Mismo tenant siempre cae en el mismo bucket."""
        ff.enable("analytics_dashboard", 5, rollout_percentage=50)
        r1 = ff.is_enabled("analytics_dashboard", 5)
        r2 = ff.is_enabled("analytics_dashboard", 5)
        assert r1 == r2

    def test_get_all_flags(self, ff):
        ff.enable("portal_cliente", 1)
        ff.disable("billing", 1)
        flags = ff.get_all_flags(1)
        names = {f["name"] for f in flags}
        assert "portal_cliente" in names
        assert "billing" in names
        portal = next(f for f in flags if f["name"] == "portal_cliente")
        assert portal["enabled"] is True
        assert portal["source"] == "tenant"

    def test_get_all_flags_source(self, ff):
        flags = ff.get_all_flags(1)
        # portal_cliente is not overridden → source = default
        portal = next(f for f in flags if f["name"] == "portal_cliente")
        assert portal["source"] == "default"
        # enable it → source = tenant
        ff.enable("portal_cliente", 1)
        flags2 = ff.get_all_flags(1)
        portal2 = next(f for f in flags2 if f["name"] == "portal_cliente")
        assert portal2["source"] == "tenant"

    def test_seed_defaults(self, ff):
        ff.seed_defaults(1)
        from b2b_ai.features.flags import FEATURE_DEFAULTS
        for name, enabled in FEATURE_DEFAULTS.items():
            assert ff.is_enabled(name, 1) == enabled

    def test_upsert_idempotent(self, ff):
        ff.enable("billing", 1)
        ff.enable("billing", 1, rollout_percentage=50)
        flags = ff.get_all_flags(1)
        billing = [f for f in flags if f["name"] == "billing"]
        assert len(billing) == 1
