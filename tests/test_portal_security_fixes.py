# -*- coding: utf-8 -*-
"""Regression tests para la remediación de seguridad del portal JSON
(`b2b_ai/api/portal.py`), rama fix/portal-security:

  1. Enumeración de cuentas por magic link            -> test_portal_integration.py
  2. tenant_id del cliente permitía búsqueda cross-tenant a ciegas -> aquí
  3. dev_token del magic link expuesto fuera de dev explícito      -> aquí
  4. Sin rate limit en login/magic-link                            -> aquí

(El CSRF de formularios pedido en el ticket no aplica a este archivo: no
tiene templates Jinja ni sesión por cookie -- ver el reporte final.)
"""
from __future__ import annotations

import os

import bcrypt
import pytest
from fastapi.testclient import TestClient

from b2b_ai.api.app import create_app
from b2b_ai.api.portal import (LOGIN_LIMITER, MAGIC_LINK_LIMITER,
                               _dev_token_exposure_allowed)
from b2b_ai.db.db import Database


def _hash(pw):
    return bcrypt.hashpw(pw.encode("utf-8"),
                         bcrypt.gensalt(rounds=4)).decode("utf-8")


@pytest.fixture
def ctx(tmp_path):
    db = Database(str(tmp_path / "portal_sec.db"))
    t1 = db.create_tenant("Despacho A", rfc="XAXX010101000")
    t2 = db.create_tenant("Despacho B", rfc="XAXX020202000")
    app = create_app(db)
    client = TestClient(app)
    return {"client": client, "db": db, "t1": t1, "t2": t2}


def _login(client, email, pw, tenant_id=None):
    body = {"email": email, "password": pw}
    if tenant_id is not None:
        body["tenant_id"] = tenant_id
    return client.post("/portal/auth/login", json=body)


# --------------------------------------------------------------------------
# (2) tenant_id del cliente nunca decide a ciegas a quién se autentica
# --------------------------------------------------------------------------
def test_login_collision_same_email_two_tenants_authenticates_correct_owner(ctx):
    """Antes: get_client_user_by_email(email, tenant_id=None) devolvía el
    PRIMER registro (rowid más bajo = tenant A, creado primero) y sólo se
    verificaba el password contra ESE. Un usuario legítimo de B, cuyo email
    colisiona con uno de A, era rechazado (401) aunque su password fuera
    correcto para su propia cuenta -- porque se probaba contra el hash de A.

    Ahora: se prueba el password contra TODOS los candidatos con ese email
    y se autentica al único que coincide, sin importar el orden de fila."""
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "compartido@x.mx", _hash("passA"), "Uno A")
    db.create_client_user(ctx["t2"], "compartido@x.mx", _hash("passB"), "Uno B")

    r_a = _login(ctx["client"], "compartido@x.mx", "passA")
    assert r_a.status_code == 200, r_a.text
    assert r_a.json()["tenant_id"] == ctx["t1"]

    r_b = _login(ctx["client"], "compartido@x.mx", "passB")
    assert r_b.status_code == 200, r_b.text
    assert r_b.json()["tenant_id"] == ctx["t2"]


def test_login_collision_wrong_password_for_either_tenant_is_rejected(ctx):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "compartido2@x.mx", _hash("passA"), "Uno A")
    db.create_client_user(ctx["t2"], "compartido2@x.mx", _hash("passB"), "Uno B")
    r = _login(ctx["client"], "compartido2@x.mx", "otra-cosa")
    assert r.status_code == 401


def test_login_explicit_tenant_id_still_requires_matching_password(ctx):
    """El tenant_id que sí manda un cliente (p.ej. una integración, aunque
    el SPA real nunca lo hace) sólo acota el filtro SQL -- nunca sustituye
    la verificación de password."""
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "u@x.mx", _hash("secreta"), "Uno")
    # tenant_id correcto + password correcto -> ok
    ok = _login(ctx["client"], "u@x.mx", "secreta", tenant_id=ctx["t1"])
    assert ok.status_code == 200
    # tenant_id de OTRO tenant (donde ese email no existe) + password
    # correcto para t1 -> debe fallar, nunca "colar" al usuario de t1.
    cross = _login(ctx["client"], "u@x.mx", "secreta", tenant_id=ctx["t2"])
    assert cross.status_code == 401


def test_login_rejects_non_positive_tenant_id(ctx):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "u2@x.mx", _hash("secreta"), "Uno")
    r = _login(ctx["client"], "u2@x.mx", "secreta", tenant_id=0)
    assert r.status_code == 422
    r2 = _login(ctx["client"], "u2@x.mx", "secreta", tenant_id=-5)
    assert r2.status_code == 422


# --------------------------------------------------------------------------
# (3) Guard duro: dev_token del magic link nunca fuera de dev explícito
# --------------------------------------------------------------------------
@pytest.mark.parametrize("env_value", [
    "production", "prod", "Production", "PROD", "staging", "stage", "uat",
    "sandbox", "", "qa", "ci",
])
def test_dev_token_never_exposed_outside_dev_envs(ctx, monkeypatch, env_value):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "dev-guard@x.mx", _hash("x"), "Uno")
    monkeypatch.setenv("B2B_ENV", env_value)
    assert _dev_token_exposure_allowed() is False
    r = ctx["client"].post("/portal/auth/magic-link",
                           json={"email": "dev-guard@x.mx"})
    assert r.status_code == 200
    assert "dev_token" not in r.json()


def test_dev_token_unset_env_var_defaults_to_blocked(ctx, monkeypatch):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "dev-guard2@x.mx", _hash("x"), "Uno")
    monkeypatch.delenv("B2B_ENV", raising=False)
    assert _dev_token_exposure_allowed() is False
    r = ctx["client"].post("/portal/auth/magic-link",
                           json={"email": "dev-guard2@x.mx"})
    assert "dev_token" not in r.json()


@pytest.mark.parametrize("env_value", ["dev", "development", "test",
                                       "testing", "local", "  Dev  "])
def test_dev_token_exposed_only_in_explicit_dev_envs(ctx, monkeypatch, env_value):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "dev-guard3@x.mx", _hash("x"), "Uno")
    monkeypatch.setenv("B2B_ENV", env_value)
    assert _dev_token_exposure_allowed() is True
    r = ctx["client"].post("/portal/auth/magic-link",
                           json={"email": "dev-guard3@x.mx"})
    assert r.status_code == 200
    assert r.json()["dev_token"]


# --------------------------------------------------------------------------
# (4) Rate limit en login y magic-link
# --------------------------------------------------------------------------
def test_login_rate_limited_after_max_attempts(ctx):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "bruteforce@x.mx", _hash("correcta"), "Uno")
    c = ctx["client"]
    for _ in range(LOGIN_LIMITER.max_attempts):
        r = _login(c, "bruteforce@x.mx", "incorrecta")
        assert r.status_code == 401
    blocked = _login(c, "bruteforce@x.mx", "incorrecta")
    assert blocked.status_code == 429
    # Ni siquiera con el password CORRECTO se cuela mientras esté bloqueado.
    still_blocked = _login(c, "bruteforce@x.mx", "correcta")
    assert still_blocked.status_code == 429


def test_login_rate_limit_is_scoped_per_email_not_global(ctx):
    """Agotar el límite para un email no debe bloquear a otro usuario."""
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "victima@x.mx", _hash("correcta"), "Uno")
    c = ctx["client"]
    for _ in range(LOGIN_LIMITER.max_attempts + 1):
        _login(c, "atacante-inexistente@x.mx", "loquesea")
    r = _login(c, "victima@x.mx", "correcta")
    assert r.status_code == 200, r.text


def test_magic_link_rate_limited_after_max_attempts(ctx):
    db = ctx["db"]
    db.create_client_user(ctx["t1"], "spam@x.mx", _hash("x"), "Uno")
    c = ctx["client"]
    for _ in range(MAGIC_LINK_LIMITER.max_attempts):
        r = c.post("/portal/auth/magic-link", json={"email": "spam@x.mx"})
        assert r.status_code == 200
    blocked = c.post("/portal/auth/magic-link", json={"email": "spam@x.mx"})
    assert blocked.status_code == 429
