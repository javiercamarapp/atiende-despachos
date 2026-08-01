# -*- coding: utf-8 -*-
"""Tests — feature flags: defaults, overrides, rollout gradual y seeding."""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.features.flags import FEATURE_DEFAULTS, FeatureFlags


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "flags.db"))


@pytest.fixture
def flags(db):
    return FeatureFlags(db)


# --------------------------------------------------------------------------- #
# defaults del código
# --------------------------------------------------------------------------- #
def test_defaults_sin_override(flags):
    assert flags.is_enabled("portal_cliente", 1) is True
    assert flags.is_enabled("cobranza_automatizada", 1) is False
    # feature desconocida → off
    assert flags.is_enabled("no_existe", 1) is False


def test_default_es_independiente_del_tenant(flags):
    assert flags.is_enabled("portal_cliente", 1) is True
    assert flags.is_enabled("portal_cliente", 99) is True


# --------------------------------------------------------------------------- #
# override enable/disable
# --------------------------------------------------------------------------- #
def test_enable_disable_override(flags):
    # desactivar una feature que por default está ON
    flags.disable("portal_cliente", 7)
    assert flags.is_enabled("portal_cliente", 7) is False
    # no afecta a otros tenants
    assert flags.is_enabled("portal_cliente", 8) is True
    # re-activar
    flags.enable("portal_cliente", 7)
    assert flags.is_enabled("portal_cliente", 7) is True


def test_enable_feature_off_por_default(flags):
    assert flags.is_enabled("billing", 3) is False
    flags.enable("billing", 3)
    assert flags.is_enabled("billing", 3) is True
    # el override es idempotente (upsert)
    flags.enable("billing", 3)
    assert flags.is_enabled("billing", 3) is True


# --------------------------------------------------------------------------- #
# rollout gradual
# --------------------------------------------------------------------------- #
def test_rollout_porcentual_es_determinista(flags):
    flags.enable("nueva_feature", 5, rollout_percentage=50)
    r1 = flags.is_enabled("nueva_feature", 5)
    r2 = flags.is_enabled("nueva_feature", 5)
    assert r1 == r2  # mismo tenant → mismo bucket siempre


def test_rollout_100_y_0(flags):
    flags.enable("r100", 1, rollout_percentage=100)
    assert flags.is_enabled("r100", 1) is True
    flags.enable("r0", 1, rollout_percentage=0)
    assert flags.is_enabled("r0", 1) is False


def test_rollout_reparte_entre_tenants(flags):
    # con 50% de rollout, en 200 tenants debe haber activos e inactivos
    flags.enable("beta", 0, rollout_percentage=50)
    on = sum(flags.is_enabled("beta", tid) for tid in range(200))
    assert 0 < on < 200


# --------------------------------------------------------------------------- #
# get_all_flags + seeding
# --------------------------------------------------------------------------- #
def test_get_all_flags_refleja_origen(db, flags):
    flags.enable("billing", 2)
    allf = {f["name"]: f for f in flags.get_all_flags(2)}
    assert allf["billing"]["enabled"] is True
    assert allf["billing"]["source"] == "tenant"
    assert allf["portal_cliente"]["source"] == "default"
    assert allf["portal_cliente"]["enabled"] is True
    # contiene todas las features conocidas
    assert set(FEATURE_DEFAULTS) <= set(allf)


def test_seed_defaults_materializa_filas(db, flags):
    flags.seed_defaults(42)
    rows = db.conn.execute(
        "SELECT * FROM feature_flags WHERE tenant_id=42").fetchall()
    assert len(rows) == len(FEATURE_DEFAULTS)
    by_name = {r["name"]: r for r in rows}
    assert by_name["portal_cliente"]["enabled"] == 1
    assert by_name["cobranza_automatizada"]["enabled"] == 0
    # idempotente
    flags.seed_defaults(42)
    n = db.conn.execute(
        "SELECT COUNT(*) FROM feature_flags WHERE tenant_id=42").fetchone()[0]
    assert n == len(FEATURE_DEFAULTS)


def test_onboarding_siembra_defaults(db):
    from b2b_ai.db.tenants import TenantManager
    out = TenantManager(db).onboard_tenant("Nuevo", rfc="NUEVO000101ZZZ",
                                           user_name="Ana")
    rows = db.conn.execute(
        "SELECT * FROM feature_flags WHERE tenant_id=?",
        (out["id"],)).fetchall()
    assert len(rows) == len(FEATURE_DEFAULTS)
    assert FeatureFlags(db).is_enabled("portal_cliente", out["id"]) is True
