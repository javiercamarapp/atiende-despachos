# -*- coding: utf-8 -*-
"""Tests unitarios de auth enterprise: roles (RBAC), JWT y UserManager.

Cubre la matriz de permisos por rol, firma/verificación de JWT (tamper,
caducidad, secreto incorrecto) y el ciclo de vida de usuarios (alta, login,
refresh, update, delete con protección del último admin, reset).
"""
import os

# Rounds de bcrypt bajos para acelerar los tests.
os.environ.setdefault("B2B_BCRYPT_ROUNDS", "4")

import time

import pytest

from b2b_ai.auth.roles import (VALID_ROLES, is_valid_role, role_permissions,
                                has_permission, normalize_role)
from b2b_ai.auth.middleware import (encode_token, decode_token, JWTError,
                                    JWTAuth, ACCESS_TTL)
from b2b_ai.auth.users import (UserManager, UserExistsError,
                               LastAdminError, UserNotFoundError,
                               InvalidRoleError, InvalidTokenError)
from b2b_ai.db.db import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "auth.db"))


@pytest.fixture
def um(db):
    return UserManager(db)


@pytest.fixture
def tenant(db):
    return db.create_tenant("Despacho A", rfc="XAXX010101000")


# --------------------------------------------------------------------------
# Roles / RBAC
# --------------------------------------------------------------------------
def test_roles_soportados():
    assert set(VALID_ROLES) == {"admin", "contador", "auxiliar", "auditor"}
    for r in VALID_ROLES:
        assert is_valid_role(r)


def test_is_valid_role_case_insensitive():
    assert is_valid_role("Admin")
    assert is_valid_role("AUDITOR")
    assert not is_valid_role("superuser")
    assert not is_valid_role(None)


def test_matriz_de_permisos_admin():
    admin = role_permissions("admin")
    assert "users.manage" in admin
    assert "invoices.view" in admin
    assert "invoices.approve" in admin
    assert "reports.generate" in admin
    assert "audit.view" in admin


def test_matriz_de_permisos_contador():
    cont = role_permissions("contador")
    assert "invoices.view" in cont
    assert "invoices.approve" in cont
    assert "reports.generate" in cont
    assert "users.manage" not in cont


def test_matriz_de_permisos_auxiliar():
    aux = role_permissions("auxiliar")
    assert "invoices.upload" in aux
    assert "invoices.view_own" in aux
    assert "invoices.approve" not in aux
    assert "users.manage" not in aux
    assert "reports.generate" not in aux


def test_matriz_de_permisos_auditor():
    aud = role_permissions("auditor")
    assert "invoices.view" in aud
    assert "audit.view" in aud
    assert "invoices.approve" not in aud
    assert "invoices.upload" not in aud
    assert "users.manage" not in aud


def test_has_permission_unknown_role():
    assert not has_permission("nadie", "invoices.view")
    assert not has_permission(None, "invoices.view")


def test_normalize_role():
    assert normalize_role(" Admin ") == "admin"
    assert normalize_role("AUDITOR") == "auditor"
    assert normalize_role("boss") is None


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def test_jwt_roundtrip():
    tok = encode_token({"sub": "7", "tenant_id": 1, "role": "admin"},
                       ttl_seconds=60)
    claims = decode_token(tok)
    assert claims["sub"] == "7"
    assert claims["tenant_id"] == 1
    assert claims["role"] == "admin"
    assert "exp" in claims and "iat" in claims


def test_jwt_tamper_rechazado():
    tok = encode_token({"sub": "1"}, ttl_seconds=60)
    # Modificar el payload (sub 1 -> 2) invalida la firma.
    head, payload, sig = tok.split(".")
    import base64
    payload = base64.urlsafe_b64encode(
        b'{"sub":"2","iat":1,"exp":9999999999}').rstrip(b"=").decode()
    tampered = f"{head}.{payload}.{sig}"
    with pytest.raises(JWTError):
        decode_token(tampered)


def test_jwt_wrong_secret_rechazado():
    tok = encode_token({"sub": "1"}, secret="secreto-a", ttl_seconds=60)
    with pytest.raises(JWTError):
        decode_token(tok, secret="secreto-b")


def test_jwt_expired_rechazado():
    tok = encode_token({"sub": "1"}, ttl_seconds=-10)
    with pytest.raises(JWTError):
        decode_token(tok)


def test_jwt_malformed_rechazado():
    with pytest.raises(JWTError):
        decode_token("no.es.un.jwt")


# --------------------------------------------------------------------------
# UserManager
# --------------------------------------------------------------------------
def test_create_user_ok(um, tenant):
    u = um.create_user("juan@a.mx", "Password123!", tenant, role="contador",
                       name="Juan")
    assert u["id"] >= 1
    assert u["email"] == "juan@a.mx"
    assert u["role"] == "contador"
    assert "password_hash" not in u  # nunca se expone
    assert u["name"] == "Juan"


def test_create_user_normaliza_email(um, tenant):
    u = um.create_user("  Juan@A.MX ", "Password123!", tenant, role="admin")
    assert u["email"] == "juan@a.mx"


def test_create_user_duplicado_levanta(um, tenant):
    um.create_user("a@a.mx", "Password123!", tenant, role="contador")
    with pytest.raises(UserExistsError):
        um.create_user("a@a.mx", "Password123!", tenant, role="contador")


def test_create_user_rol_invalido(um, tenant):
    with pytest.raises(InvalidRoleError):
        um.create_user("x@a.mx", "Password123!", tenant, role="superuser")


def test_create_user_password_corto(um, tenant):
    with pytest.raises(Exception):
        um.create_user("x@a.mx", "corta", tenant, role="admin")


def test_authenticate_ok(um, tenant):
    um.create_user("juan@a.mx", "Password123!", tenant, role="admin", name="Juan")
    sess = um.authenticate("juan@a.mx", "Password123!", tenant_id=tenant)
    assert sess is not None
    assert sess["access_token"] and sess["refresh_token"]
    assert sess["user"]["email"] == "juan@a.mx"
    assert sess["user"]["role"] == "admin"
    # El access token se puede decodificar y es de tipo access.
    claims = um.jwt.decode(sess["access_token"])
    assert claims["type"] == "access"
    assert claims["tenant_id"] == tenant


def test_authenticate_password_mal(um, tenant):
    um.create_user("juan@a.mx", "Password123!", tenant)
    assert um.authenticate("juan@a.mx", "mala", tenant_id=tenant) is None


def test_authenticate_email_inexistente(um, tenant):
    assert um.authenticate("nadie@a.mx", "Password123!", tenant_id=tenant) is None


def test_refresh_token_ok(um, tenant):
    u = um.create_user("juan@a.mx", "Password123!", tenant)
    sess = um.authenticate("juan@a.mx", "Password123!", tenant_id=tenant)
    new = um.refresh_token(sess["refresh_token"])
    assert new["access_token"]
    assert new["user"]["id"] == u["id"]


def test_refresh_token_acceso_no_sirve(um, tenant):
    u = um.create_user("juan@a.mx", "Password123!", tenant)
    sess = um.authenticate("juan@a.mx", "Password123!", tenant_id=tenant)
    # Un access token no vale como refresh.
    with pytest.raises(InvalidTokenError):
        um.refresh_token(sess["access_token"])


def test_refresh_token_basura_rechazado(um):
    with pytest.raises(InvalidTokenError):
        um.refresh_token("no-un-token")


def test_get_user(um, tenant):
    u = um.create_user("juan@a.mx", "Password123!", tenant, name="Juan")
    got = um.get_user(u["id"])
    assert got["email"] == "juan@a.mx"
    assert "password_hash" not in got
    assert um.get_user(99999) is None


def test_update_user(um, tenant):
    u = um.create_user("juan@a.mx", "Password123!", tenant, name="Juan")
    updated = um.update_user(u["id"], {"name": "Juan Pérez",
                                       "password": "NuevaPass123!"})
    assert updated["name"] == "Juan Pérez"
    # El nuevo password autentica.
    assert um.authenticate("juan@a.mx", "NuevaPass123!", tenant_id=tenant)


def test_update_user_email_duplicado(um, tenant):
    um.create_user("a@a.mx", "Password123!", tenant)
    u2 = um.create_user("b@a.mx", "Password123!", tenant)
    with pytest.raises(UserExistsError):
        um.update_user(u2["id"], {"email": "a@a.mx"})


def test_delete_user(um, tenant):
    admin = um.create_user("admin@a.mx", "Password123!", tenant, role="admin")
    emp = um.create_user("emp@a.mx", "Password123!", tenant, role="auxiliar")
    um.delete_user(emp["id"])
    assert um.get_user(emp["id"]) is None
    assert um.get_user(admin["id"]) is not None


def test_delete_ultimo_admin_protegido(um, tenant):
    admin = um.create_user("admin@a.mx", "Password123!", tenant, role="admin")
    with pytest.raises(LastAdminError):
        um.delete_user(admin["id"])


def test_delete_usuario_inexistente(um, tenant):
    with pytest.raises(UserNotFoundError):
        um.delete_user(99999)


def test_password_reset(um, tenant):
    u = um.create_user("juan@a.mx", "Password123!", tenant)
    res = um.password_reset("juan@a.mx", tenant_id=tenant)
    assert res is not None
    assert res["reset_token"]
    # El token de reset es tipo reset.
    claims = um.jwt.decode(res["reset_token"])
    assert claims["type"] == "reset"


def test_password_reset_email_inexistente(um, tenant):
    assert um.password_reset("nadie@a.mx", tenant_id=tenant) is None
