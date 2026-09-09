# -*- coding: utf-8 -*-
"""test_roles.py — Tests del módulo de roles y permisos (RBAC) multi-tenant.

Cubre:
  - seed de roles por defecto y su matriz de permisos.
  - RolesService: assign_role, check_permission, get_user_roles, list_roles,
    create_custom_role, update_role, delete_role, user_permissions.
  - Middleware require_permission (Depends): concede / deniega 403.
  - API REST /api/v1/roles (con una dependencia de auth que inyecta user_id y
    tenant_id, patrón de los módulos del piloto).
  - Integración con el router de billing piloto: `billing:write` protege
    checkout/cancel, y es retro-compatible (sin fábrica = sin RBAC).
"""
from __future__ import annotations

import pytest

from b2b_ai.features.roles.models import (
    Permission,
    Role,
    UserRole,
    _reset_state,
)
from b2b_ai.features.roles.seed import (
    DEFAULT_ROLE_DEFS,
    seed_default_roles,
)
from b2b_ai.features.roles.service import (
    RolesError,
    RolesService,
    reset_state,
)
from b2b_ai.features.roles.middleware import make_require_permission

TENANT = "tenant_despacho_1"
ADMIN = "user_admin_1"
CONTADOR = "user_contador_1"
READONLY = "user_readonly_1"


@pytest.fixture(autouse=True)
def _clean():
    reset_state()
    yield
    reset_state()


@pytest.fixture
def svc():
    return RolesService()


# --------------------------------------------------------------------------
# Seed y matriz de permisos
# --------------------------------------------------------------------------
def test_seed_crea_roles_por_defecto(svc):
    roles = svc.list_roles()
    names = {r.name for r in roles}
    assert names == {"admin", "contador", "auditor", "readonly"}
    assert all(r.builtin for r in roles)


def test_seed_es_idempotente(svc):
    a = seed_default_roles()
    b = seed_default_roles()
    assert len(a) == 4
    assert len(b) == 4


def test_admin_tiene_todos_los_permisos(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    assert set(admin.permissions) == set(Permission.ALL)
    assert Permission.USERS_MANAGE in admin.permissions


def test_contador_no_gestiona_usuarios(svc):
    contador = next(r for r in svc.list_roles() if r.name == "contador")
    assert Permission.CFDI_WRITE in contador.permissions
    assert Permission.USERS_MANAGE not in contador.permissions


def test_readonly_solo_lectura(svc):
    readonly = next(r for r in svc.list_roles() if r.name == "readonly")
    write = [p for p in readonly.permissions if p.endswith(":write")]
    assert write == []
    assert "users:manage" not in readonly.permissions


def test_matriz_roles_definidos():
    # Todos los roles definidos en el seed usan permisos reconocidos.
    for name, (perms, _desc) in DEFAULT_ROLE_DEFS.items():
        assert set(perms) <= set(Permission.ALL)
    assert set(DEFAULT_ROLE_DEFS) == {"admin", "contador", "auditor", "readonly"}


# --------------------------------------------------------------------------
# Asignación de roles
# --------------------------------------------------------------------------
def test_assign_role_y_check_permission(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    ur = svc.assign_role(ADMIN, TENANT, admin.id, assigned_by="sistema")
    assert isinstance(ur, UserRole)
    assert svc.check_permission(ADMIN, TENANT, Permission.CFDI_WRITE)
    assert svc.check_permission(ADMIN, TENANT, Permission.USERS_MANAGE)


def test_check_permission_false_sin_rol(svc):
    assert not svc.check_permission("usuario_sin_rol", TENANT, Permission.CFDI_READ)


def test_assign_idempotente_sin_duplicar(svc):
    readonly = next(r for r in svc.list_roles() if r.name == "readonly")
    a = svc.assign_role(READONLY, TENANT, readonly.id)
    b = svc.assign_role(READONLY, TENANT, readonly.id)
    assert a.id == b.id
    assert len(svc.get_user_roles(READONLY, TENANT)) == 1


def test_asignar_nuevo_rol_reescribe_el_anterior(svc):
    contador = next(r for r in svc.list_roles() if r.name == "contador")
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, contador.id)
    svc.assign_role(ADMIN, TENANT, admin.id)
    roles = svc.get_user_roles(ADMIN, TENANT)
    assert len(roles) == 1
    assert roles[0].name == "admin"


def test_no_puede_asignar_rol_de_otro_tenant(svc):
    custom = svc.create_custom_role(TENANT, "supervisor",
                                    [Permission.CFDI_READ])
    # Rol custom de TENANT no aplica a otro tenant.
    with pytest.raises(RolesError):
        svc.assign_role("user_x", "tenant_otro", custom.id)


def test_remove_role(svc):
    readonly = next(r for r in svc.list_roles() if r.name == "readonly")
    ur = svc.assign_role(READONLY, TENANT, readonly.id)
    assert svc.remove_role(ur.id)
    assert not svc.get_user_roles(READONLY, TENANT)


def test_get_user_roles_filtra_por_tenant(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, admin.id)
    svc.assign_role(ADMIN, "tenant_otro", admin.id)
    assert len(svc.get_user_roles(ADMIN, TENANT)) == 1
    assert len(svc.get_user_roles(ADMIN)) == 2


# --------------------------------------------------------------------------
# Permisos efectivos
# --------------------------------------------------------------------------
def test_user_permissions_union_sin_duplicados(svc):
    # Un usuario con dos roles: admin da todo, readonly no agrega.
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    readonly = next(r for r in svc.list_roles() if r.name == "readonly")
    svc.assign_role(ADMIN, TENANT, admin.id)
    # Un rol extra (readonly) no debe duplicar permisos.
    ur = svc.assign_role(ADMIN, TENANT, readonly.id)
    svc.remove_role(ur.id)  # para no romper el "1 rol por tenant"
    perms = svc.user_permissions(ADMIN, TENANT)
    assert perms == list(dict.fromkeys(perms))  # sin duplicados


def test_check_permission_permiso_desconocido_es_falso(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, admin.id)
    assert not svc.check_permission(ADMIN, TENANT, "no:existe")


# --------------------------------------------------------------------------
# CRUD de roles custom
# --------------------------------------------------------------------------
def test_create_custom_role(svc):
    role = svc.create_custom_role(
        TENANT, "nominas_admin",
        [Permission.NOMINAS_READ, Permission.NOMINAS_WRITE],
        description="Gestiona nómina")
    assert not role.builtin
    assert role.tenant_id == TENANT
    assert role.has(Permission.NOMINAS_WRITE)
    assert svc.get_role(role.id).name == "nominas_admin"


def test_create_custom_role_permiso_invalido(svc):
    # P2-1: permisos inválidos ahora se traducen a RolesError -> 400
    # (antes escapaba una pydantic ValidationError/ValueError como 500).
    with pytest.raises(RolesError, match="Permiso no reconocido"):
        svc.create_custom_role(TENANT, "rol_malo", ["cafeteria:write"])


def test_create_custom_role_duplicado(svc):
    svc.create_custom_role(TENANT, "supervisor", [Permission.CFDI_READ])
    with pytest.raises(RolesError, match="Ya existe"):
        svc.create_custom_role(TENANT, "supervisor", [Permission.CFDI_READ])


def test_update_role_permisos(svc):
    role = svc.create_custom_role(TENANT, "supervisor", [Permission.CFDI_READ])
    updated = svc.update_role(role.id, permissions=[
        Permission.CFDI_READ, Permission.REPORTES_READ])
    assert updated.has(Permission.REPORTES_READ)
    assert not updated.has(Permission.NOMINAS_WRITE)


def test_update_role_permiso_invalido_es_error(svc):
    role = svc.create_custom_role(TENANT, "supervisor", [Permission.CFDI_READ])
    with pytest.raises(RolesError, match="Permiso no reconocido"):
        svc.update_role(role.id, permissions=["x:y"])


def test_delete_role_custom_solo(svc):
    role = svc.create_custom_role(TENANT, "temporal", [Permission.CFDI_READ])
    assert svc.delete_role(role.id)
    with pytest.raises(RolesError, match="no encontrado"):
        svc.get_role(role.id)


def test_no_se_puede_eliminar_builtin(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    with pytest.raises(RolesError, match="por defecto"):
        svc.delete_role(admin.id)


def test_list_roles_scope_por_tenant(svc):
    svc.create_custom_role(TENANT, "despacho_rol", [Permission.CFDI_READ])
    svc.create_custom_role("tenant_otro", "otro_rol", [Permission.CFDI_READ])
    names = {r.name for r in svc.list_roles(tenant_id=TENANT)}
    assert "despacho_rol" in names
    assert "otro_rol" not in names
    assert "admin" in names  # builtin siempre visible


# --------------------------------------------------------------------------
# Middleware require_permission
# --------------------------------------------------------------------------
def _auth(uid=ADMIN, tid=TENANT):
    def fake_require_api_key():
        return {"user_id": uid, "tenant_id": tid, "api_key": "k"}
    return fake_require_api_key


def test_require_permission_concede(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, admin.id)
    rp = make_require_permission(_auth(), svc)
    dep = rp(Permission.USERS_MANAGE)
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/protegido")
    def protegido(auth_info: dict = Depends(dep)) -> dict:
        return {"ok": True, "user_id": auth_info["user_id"]}

    r = TestClient(app).get("/protegido")
    assert r.status_code == 200
    assert r.json()["user_id"] == ADMIN


def test_require_permission_deniega_403(svc):
    contador = next(r for r in svc.list_roles() if r.name == "contador")
    svc.assign_role(CONTADOR, TENANT, contador.id)
    rp = make_require_permission(_auth(CONTADOR), svc)
    dep = rp(Permission.USERS_MANAGE)  # contador NO gestiona usuarios
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/protegido")
    def protegido(auth_info: dict = Depends(dep)) -> dict:
        return {"ok": True}

    assert TestClient(app).get("/protegido").status_code == 403


def test_require_permission_sin_user_id_concede_200(svc):
    """P1-1: en modo standalone (env API key) no hay user_id; el tenant_id
    del contexto basta para conceder el permiso (no es auto-promoción a admin,
    es el grant standalone del auth de entorno)."""
    rp = make_require_permission(lambda: {"tenant_id": TENANT}, svc)
    dep = rp(Permission.CFDI_READ)
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    app = FastAPI()

    @app.get("/x")
    def x(auth_info: dict = Depends(dep)) -> dict:
        return {"ok": True}

    assert TestClient(app).get("/x").status_code == 200


# --------------------------------------------------------------------------
# API REST /api/v1/roles
# --------------------------------------------------------------------------
@pytest.fixture
def roles_client(svc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, admin.id)  # el actor tiene users:manage

    app = FastAPI()
    app.include_router(build_roles_router(db=None, require_api_key=_auth()))
    return TestClient(app)


def test_api_lista_roles(roles_client):
    r = roles_client.get("/api/v1/roles")
    assert r.status_code == 200
    names = {x["name"] for x in r.json()["roles"]}
    assert names == {"admin", "contador", "auditor", "readonly"}


def test_api_catalogo_permisos(roles_client):
    r = roles_client.get("/api/v1/roles/permissions")
    assert r.status_code == 200
    assert Permission.USERS_MANAGE in r.json()["permissions"]
    assert len(r.json()["permissions"]) == len(Permission.ALL)


def test_api_crea_rol_custom(roles_client):
    r = roles_client.post("/api/v1/roles/custom", json={
        "name": "socios", "permissions": ["cfdi:read", "reportes:read"],
        "description": "Socios del despacho"})
    assert r.status_code == 200, r.text
    body = r.json()["role"]
    assert body["name"] == "socios"
    assert "reportes:read" in body["permissions"]
    assert body["tenant_id"] == TENANT


def test_api_crea_rol_sin_permiso_403():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    # Usuario readonly NO tiene users:manage -> 403 al crear rol.
    rp = make_require_permission(_auth(READONLY))
    app = FastAPI()
    app.include_router(build_roles_router(db=None, require_api_key=_auth(READONLY)))
    r = TestClient(app).post("/api/v1/roles/custom", json={
        "name": "hack", "permissions": ["cfdi:read"]})
    assert r.status_code == 403


def test_api_assign_y_consulta(roles_client):
    contador = next(r for r in roles_client.get("/api/v1/roles").json()["roles"]
                    if r["name"] == "contador")
    r = roles_client.post("/api/v1/roles/assign", json={
        "user_id": CONTADOR, "role_id": contador["id"]})
    assert r.status_code == 200, r.text
    # El contador ya tiene cfdi:write pero no users:manage.
    check = roles_client.get(f"/api/v1/roles/check?permission=cfdi:write")
    # El actor (ADMIN) tiene cfdi:write.
    assert check.status_code == 200
    assert check.json()["granted"] is True


def test_api_me_permissions(roles_client):
    r = roles_client.get("/api/v1/roles/me/permissions")
    assert r.status_code == 200
    assert "users:manage" in r.json()["permissions"]


def test_api_actualiza_rol(roles_client):
    rol = roles_client.post("/api/v1/roles/custom", json={
        "name": "temporal", "permissions": ["cfdi:read"]}).json()["role"]
    r = roles_client.put(f"/api/v1/roles/{rol['id']}", json={
        "permissions": ["cfdi:read", "cfdi:write"]})
    assert r.status_code == 200
    assert "cfdi:write" in r.json()["role"]["permissions"]


def test_api_elimina_rol_custom_y_protege_builtin(roles_client):
    rol = roles_client.post("/api/v1/roles/custom", json={
        "name": "borrable", "permissions": ["cfdi:read"]}).json()["role"]
    assert roles_client.delete(f"/api/v1/roles/{rol['id']}").status_code == 200
    admin = next(r for r in roles_client.get("/api/v1/roles").json()["roles"]
                 if r["name"] == "admin")
    assert roles_client.delete(f"/api/v1/roles/{admin['id']}").status_code == 400


# --------------------------------------------------------------------------
# NOTA (consolidación de billing, fix/billing-consolidacion): este archivo
# tenía dos tests de integración (`test_billing_integracion_billing_write`,
# `test_billing_imports_roles`) que usaban `b2b_ai.features.billing.routes`
# (el módulo "piloto") únicamente como fixture de conveniencia para probar
# que un router real respeta `require_permission`. Ese módulo se eliminó:
# nunca estuvo montado en `create_app()` (no servía tráfico real) y tenía un
# bypass de firma de webhook real e independiente de este RBAC. El
# comportamiento que esos dos tests verificaban -- que `require_permission`
# deniega (403) sin el permiso y concede (200) con él, y que es
# retro-compatible sin `require_permission` inyectado -- sigue cubierto sin
# depender de ningún router de billing por `test_require_permission_concede`,
# `test_require_permission_deniega_403` y
# `test_require_permission_sin_user_id_concede_200` arriba, que ejercitan la
# dependencia `require_permission` directamente.
