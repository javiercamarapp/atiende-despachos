# -*- coding: utf-8 -*-
"""Tests de los endpoints de auth enterprise (JWT + RBAC multi-tenant).

Cubre: bootstrap de registro, login, refresh, /me, gestión de usuarios por
tenant (listar/crear/cambiar rol), aislamiento entre tenants y control de
acceso por rol (admin vs auxiliar).

Semántica de register: el PRIMER usuario de un tenant se crea como admin
(bootstrap, sin token). Una vez que el tenant tiene usuarios, register exige
un admin autenticado del mismo tenant.
"""
import os

os.environ.setdefault("B2B_BCRYPT_ROUNDS", "4")

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app


@pytest.fixture
def ctx(tmp_path):
    db = Database(str(tmp_path / "authapi.db"))
    t1 = db.create_tenant("Despacho A", rfc="XAXX010101000")
    t2 = db.create_tenant("Despacho B", rfc="XAXX020202000")
    app = create_app(db)
    return {"client": TestClient(app), "db": db, "t1": t1, "t2": t2}


def _bearer(token):
    return {"Authorization": "Bearer " + token}


def _register(client, tid, email, password, role="contador", name="",
              headers=None):
    return client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "tenant_id": tid,
        "role": role, "name": name}, headers=headers)


def _login(client, tid, email, password):
    return client.post("/api/v1/auth/login", json={
        "email": email, "password": password, "tenant_id": tid})


def _seed(ctx, email="admin@a.mx", pw="Password123!"):
    """Crea el tenant T1 (bootstrap admin) y devuelve client + sesión admin."""
    c = ctx["client"]
    _register(c, ctx["t1"], email, pw, role="contador")
    sess = _login(c, ctx["t1"], email, pw).json()
    return c, sess


# --------------------------------------------------------------------------
# Register / bootstrap
# --------------------------------------------------------------------------
def test_register_bootstrap_primer_usuario_es_admin(ctx):
    c = ctx["client"]
    r = _register(c, ctx["t1"], "admin@a.mx", "Password123!", role="contador")
    assert r.status_code == 200
    body = r.json()["user"]
    assert body["email"] == "admin@a.mx"
    # Bootstrap fuerza admin aunque se pidió contador.
    assert body["role"] == "admin"


def test_register_segundo_usuario_requiere_admin(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    # Sin token -> 401 (el tenant ya tiene usuarios).
    r = _register(c, ctx["t1"], "emp@a.mx", "Password123!")
    assert r.status_code == 401
    # Con token admin -> 200 con el rol pedido.
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    h = _bearer(sess["access_token"])
    r = _register(c, ctx["t1"], "emp@a.mx", "Password123!",
                  role="auxiliar", name="Emp", headers=h)
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "auxiliar"


def test_register_duplicado_409(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    h = _bearer(sess["access_token"])
    r = _register(c, ctx["t1"], "admin@a.mx", "Password123!", headers=h)
    assert r.status_code == 409


def test_register_rol_invalido_422(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    h = _bearer(sess["access_token"])
    r = _register(c, ctx["t1"], "emp@a.mx", "Password123!", role="boss",
                  headers=h)
    assert r.status_code == 422


def test_register_admin_de_otro_tenant_403(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    _register(c, ctx["t2"], "admin2@b.mx", "Password123!")
    # Admin de T1 no puede registrar usuarios en T2.
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    h = _bearer(sess["access_token"])
    r = _register(c, ctx["t2"], "emp@b.mx", "Password123!", headers=h)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Login / refresh / me
# --------------------------------------------------------------------------
def test_login_y_me(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    assert sess["access_token"] and sess["refresh_token"]
    assert sess["user"]["email"] == "admin@a.mx"
    assert sess["tenant_id"] == ctx["t1"]
    me = c.get("/api/v1/auth/me", headers=_bearer(sess["access_token"]))
    assert me.status_code == 200
    assert me.json()["user"]["id"] == sess["user"]["id"]
    assert "password_hash" not in me.json()["user"]


def test_login_wrong_password_401(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    r = _login(c, ctx["t1"], "admin@a.mx", "mala")
    assert r.status_code == 401


def test_me_sin_token_401(ctx):
    r = ctx["client"].get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_token_invalido_401(ctx):
    r = ctx["client"].get("/api/v1/auth/me",
                          headers=_bearer("token.que.no.es"))
    assert r.status_code == 401


def test_refresh_ok(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    r = c.post("/api/v1/auth/refresh",
               json={"refresh_token": sess["refresh_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    me = c.get("/api/v1/auth/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200


def test_refresh_con_access_token_401(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!")
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    r = c.post("/api/v1/auth/refresh",
               json={"refresh_token": sess["access_token"]})
    assert r.status_code == 401


def test_update_me(ctx):
    c = ctx["client"]
    _register(c, ctx["t1"], "admin@a.mx", "Password123!", name="Admin")
    sess = _login(c, ctx["t1"], "admin@a.mx", "Password123!").json()
    r = c.put("/api/v1/auth/me", headers=_bearer(sess["access_token"]),
              json={"name": "Nuevo Nombre", "password": "otrapass123"})
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "Nuevo Nombre"
    r2 = _login(c, ctx["t1"], "admin@a.mx", "otrapass123")
    assert r2.status_code == 200


# --------------------------------------------------------------------------
# Gestión de usuarios por tenant (admin)
# --------------------------------------------------------------------------
def _add_aux(ctx, sess, email="emp@a.mx"):
    """Registra un auxiliar en T1 usando la sesión admin. Devuelve su user."""
    c = ctx["client"]
    h = _bearer(sess["access_token"])
    r = _register(c, ctx["t1"], email, "Password123!", role="auxiliar",
                  name="Emp", headers=h)
    assert r.status_code == 200
    return r.json()["user"]


def test_list_users_admin(ctx):
    c, sess = _seed(ctx)
    r = c.get(f"/api/v1/tenants/{ctx['t1']}/users",
              headers=_bearer(sess["access_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == ctx["t1"]
    assert body["count"] >= 1
    assert all("password_hash" not in u for u in body["users"])


def test_list_users_requiere_admin(ctx):
    c, sess = _seed(ctx)
    emp = _add_aux(ctx, sess)
    esess = _login(c, ctx["t1"], emp["email"], "Password123!").json()
    r = c.get(f"/api/v1/tenants/{ctx['t1']}/users",
              headers=_bearer(esess["access_token"]))
    assert r.status_code == 403


def test_list_users_aislamiento_entre_tenants(ctx):
    c, sess = _seed(ctx)
    r = c.get(f"/api/v1/tenants/{ctx['t2']}/users",
              headers=_bearer(sess["access_token"]))
    assert r.status_code == 403


def test_create_user_en_tenant(ctx):
    c, sess = _seed(ctx)
    r = c.post(f"/api/v1/tenants/{ctx['t1']}/users",
               headers=_bearer(sess["access_token"]),
               json={"email": "nuevo@a.mx", "password": "Password123!",
                     "role": "auditor", "name": "Nuevo"})
    assert r.status_code == 200
    u = r.json()["user"]
    assert u["role"] == "auditor"
    assert u["tenant_id"] == ctx["t1"]


def test_create_user_duplicado_409(ctx):
    c, sess = _seed(ctx)
    h = _bearer(sess["access_token"])
    payload = {"email": "nuevo@a.mx", "password": "Password123!",
               "role": "auxiliar"}
    assert c.post(f"/api/v1/tenants/{ctx['t1']}/users", headers=h,
                  json=payload).status_code == 200
    r = c.post(f"/api/v1/tenants/{ctx['t1']}/users", headers=h, json=payload)
    assert r.status_code == 409


def test_change_role_ok(ctx):
    c, sess = _seed(ctx)
    h = _bearer(sess["access_token"])
    emp = _add_aux(ctx, sess)
    r = c.put(f"/api/v1/tenants/{ctx['t1']}/users/{emp['id']}/role",
              headers=h, json={"role": "contador"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "contador"


def test_change_role_rol_invalido_422(ctx):
    c, sess = _seed(ctx)
    h = _bearer(sess["access_token"])
    emp = _add_aux(ctx, sess)
    r = c.put(f"/api/v1/tenants/{ctx['t1']}/users/{emp['id']}/role",
              headers=h, json={"role": "superadmin"})
    assert r.status_code == 422


def test_change_role_otro_tenant_404(ctx):
    c, sess = _seed(ctx)
    h = _bearer(sess["access_token"])
    # Endpoint del T2 con token de admin de T1 -> 403 (aislamiento).
    r = c.put(f"/api/v1/tenants/{ctx['t2']}/users/1/role",
              headers=h, json={"role": "admin"})
    assert r.status_code in (403, 404)


def test_change_role_ultimo_admin_protegido(ctx):
    c, sess = _seed(ctx)
    h = _bearer(sess["access_token"])
    r = c.put(f"/api/v1/tenants/{ctx['t1']}/users/{sess['user']['id']}/role",
              headers=h, json={"role": "auxiliar"})
    assert r.status_code == 403


def test_change_role_requiere_admin(ctx):
    c, sess = _seed(ctx)
    emp = _add_aux(ctx, sess)
    esess = _login(c, ctx["t1"], emp["email"], "Password123!").json()
    r = c.put(f"/api/v1/tenants/{ctx['t1']}/users/{emp['id']}/role",
              headers=_bearer(esess["access_token"]), json={"role": "contador"})
    assert r.status_code == 403
