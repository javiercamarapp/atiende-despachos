# -*- coding: utf-8 -*-
"""test_rbac_fixes.py — Regresión de los 5 bugs P1/P2 del módulo RBAC.

Hallazgos de Leonardo en QA (reporte 209-qa-rbac-roles.md):

  P1-1  RBAC siempre deniega en standalone (API key de entorno sin BD):
        require_permission exigía user_id, que es None en env-key mode, por
        lo que TODO endpoint protegido devolvía 403. Ahora el tenant_id es
        suficiente en modo standalone (el permiso se concede).
  P1-2  Cross-tenant leak vía query param: list_roles aceptaba `?tenant_id=`
        y cualquier usuario podía listar roles de otro tenant. Ahora SIEMPRE
        se usa el tenant del contexto de auth y el query param se ignora.
  P1-3  Escalación cross-tenant editando roles builtin (globales): un admin
        del tenant A podía modificar el rol global admin/contador. Ahora los
        builtin son inmutables (update/delete rechazados).
  P2-1  500 en vez de 400 por permisos inválidos: create_custom_role dejaba
        escapar la ValidationError de pydantic como 500. Ahora se valida
        con is_valid_permission y se levanta RolesError -> 400.
  P2-2  user_id nunca se vinculaba a roles (modo DB): user_id = api_keys.id
        pero nada asignaba roles automáticamente. Ahora el primer usuario de
        un tenant recibe el rol admin (bootstrap) vía ensure_first_user_admin.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.roles.models import Permission, _reset_state
from b2b_ai.features.roles.seed import seed_default_roles
from b2b_ai.features.roles.service import RolesError, RolesService, reset_state
from b2b_ai.features.roles.middleware import make_require_permission

TENANT = "tenant_despacho_1"
ADMIN = "user_admin_1"


@pytest.fixture(autouse=True)
def _clean():
    reset_state()
    yield
    reset_state()


@pytest.fixture
def svc():
    return RolesService()


# --------------------------------------------------------------------------
# P1-1 — RBAC siempre deniega en standalone
# --------------------------------------------------------------------------
def test_p1_1_standalone_sin_user_id_concede_permiso(svc):
    """En modo standalone (env API key) no hay user_id; el tenant_id basta."""
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient

    rp = make_require_permission(lambda: {"tenant_id": TENANT}, svc)
    dep = rp(Permission.USERS_MANAGE)

    app = FastAPI()

    @app.get("/protegido")
    def protegido(auth_info: dict = Depends(dep)) -> dict:
        return {"ok": True}

    # Antes: 403 SIEMPRE. Ahora: 200 (tenant_id suficiente en standalone).
    assert TestClient(app).get("/protegido").status_code == 200


def test_p1_1_sin_tenant_id_sigue_siendo_403(svc):
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient

    rp = make_require_permission(lambda: {}, svc)
    dep = rp(Permission.CFDI_READ)

    app = FastAPI()

    @app.get("/x")
    def x(auth_info: dict = Depends(dep)) -> dict:
        return {"ok": True}

    assert TestClient(app).get("/x").status_code == 403


def test_p1_1_api_standalone_puede_crear_rol_custom():
    """End-to-end: el router completo opera en modo standalone."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    app = FastAPI()
    app.include_router(build_roles_router(
        db=None, require_api_key=lambda: {"tenant_id": TENANT}))
    r = TestClient(app).post("/api/v1/roles/custom", json={
        "name": "socio", "permissions": ["cfdi:read"]})
    # Antes: 403 siempre. Ahora: crea el rol en el tenant del auth.
    assert r.status_code == 200, r.text
    assert r.json()["role"]["tenant_id"] == TENANT


# --------------------------------------------------------------------------
# P1-2 — Cross-tenant leak vía query param
# --------------------------------------------------------------------------
def test_p1_2_query_param_tenant_id_es_ignorado():
    """`?tenant_id=<otro>` no debe exponer roles de otro tenant."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    svc = RolesService()
    svc.create_custom_role("tenant_A", "rolA", [Permission.CFDI_READ])
    svc.create_custom_role("tenant_B", "rolB", [Permission.CFDI_READ])
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, "tenant_A", admin.id)

    app = FastAPI()
    app.include_router(build_roles_router(
        db=None, require_api_key=lambda: {"user_id": ADMIN, "tenant_id": "tenant_A"}))
    c = TestClient(app)

    # Intento de leak: el query param NO debe filtrar roles del tenant_B.
    r = c.get("/api/v1/roles?tenant_id=tenant_B")
    assert r.status_code == 200
    names = {x["name"] for x in r.json()["roles"]}
    assert "rolB" not in names      # NO se filtra el tenant ajeno
    assert "rolA" in names          # sí se ve el propio tenant


def test_p1_2_sin_query_param_usa_tenant_del_auth():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    svc = RolesService()
    svc.create_custom_role("tenant_A", "rolA", [Permission.CFDI_READ])
    svc.create_custom_role("tenant_B", "rolB", [Permission.CFDI_READ])

    app = FastAPI()
    app.include_router(build_roles_router(
        db=None, require_api_key=lambda: {"user_id": ADMIN, "tenant_id": "tenant_A"}))
    names = {x["name"] for x in TestClient(app).get("/api/v1/roles").json()["roles"]}
    assert "rolB" not in names
    assert "rolA" in names


# --------------------------------------------------------------------------
# P1-3 — Roles builtin inmutables (escalación cross-tenant)
# --------------------------------------------------------------------------
def test_p1_3_no_se_puede_editar_rol_builtin(svc):
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    with pytest.raises(RolesError, match="por defecto"):
        svc.update_role(admin.id, description="hack global")


def test_p1_3_no_se_pueden_cambiar_permisos_de_builtin(svc):
    contador = next(r for r in svc.list_roles() if r.name == "contador")
    with pytest.raises(RolesError, match="por defecto"):
        svc.update_role(contador.id, permissions=[Permission.USERS_MANAGE])


def test_p1_3_si_se_puede_editar_rol_custom(svc):
    role = svc.create_custom_role(TENANT, "supervisor", [Permission.CFDI_READ])
    updated = svc.update_role(role.id, description="editado ok")
    assert updated.description == "editado ok"


def test_p1_3_api_editar_builtin_devuelve_400():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    svc = RolesService()
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, admin.id)
    app = FastAPI()
    app.include_router(build_roles_router(
        db=None, require_api_key=lambda: {"user_id": ADMIN, "tenant_id": TENANT}))
    c = TestClient(app)
    r = c.put(f"/api/v1/roles/{admin.id}", json={"description": "hack"})
    assert r.status_code == 400


# --------------------------------------------------------------------------
# P2-1 — 400 (RolesError) en vez de 500 (ValidationError)
# --------------------------------------------------------------------------
def test_p2_1_crear_rol_permiso_invalido_es_roles_error(svc):
    # Antes: pydantic ValidationError escapaba como 500.
    with pytest.raises(RolesError, match="Permiso no reconocido"):
        svc.create_custom_role(TENANT, "rol_malo", ["cafeteria:write"])


def test_p2_1_api_crear_rol_permiso_invalido_devuelve_400():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from b2b_ai.features.roles.routes import build_roles_router

    svc = RolesService()
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role(ADMIN, TENANT, admin.id)
    app = FastAPI()
    app.include_router(build_roles_router(
        db=None, require_api_key=lambda: {"user_id": ADMIN, "tenant_id": TENANT}))
    r = TestClient(app).post("/api/v1/roles/custom", json={
        "name": "rol_malo", "permissions": ["cafeteria:write"]})
    # Antes: 500. Ahora: 400 con el detalle del permiso inválido.
    assert r.status_code == 400
    assert "Permiso no reconocido" in r.json()["detail"]


# --------------------------------------------------------------------------
# P2-2 — Auto-vínculo user_id -> rol admin (primer usuario del tenant)
# --------------------------------------------------------------------------
def test_p2_2_primer_usuario_recibe_admin_automatico(svc):
    # Usuario "nuevo" (modo DB: user_id = api_keys.id) sin roles asignados.
    granted = svc.ensure_first_user_admin("user_db_1", "tenant_db")
    assert granted is True
    assert svc.check_permission("user_db_1", "tenant_db", Permission.USERS_MANAGE)
    assert svc.check_permission("user_db_1", "tenant_db", Permission.CFDI_WRITE)


def test_p2_2_no_reasigna_admin_si_ya_tiene_roles(svc):
    contador = next(r for r in svc.list_roles() if r.name == "contador")
    svc.assign_role(ADMIN, TENANT, contador.id)
    # Ya tiene un rol: el bootstrap NO lo pisa con admin.
    granted = svc.ensure_first_user_admin(ADMIN, TENANT)
    assert granted is False
    roles = svc.get_user_roles(ADMIN, TENANT)
    assert len(roles) == 1
    assert roles[0].name == "contador"


def test_p2_2_middleware_no_auto_asigna_admin_al_sin_rol():
    """El middleware NO promueve a admin en el request path (aislamiento).

    Un usuario sin rol recibe 403; el bootstrap del primer usuario es
    responsabilidad de la capa de creación de api_key/seed, vía
    RolesService.ensure_first_user_admin() — no del request de RBAC.
    """
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient

    svc = RolesService()
    rp = make_require_permission(
        lambda: {"user_id": "user_db_2", "tenant_id": "tenant_db"}, svc)
    dep = rp(Permission.USERS_MANAGE)

    app = FastAPI()

    @app.get("/adminish")
    def adminish(auth_info: dict = Depends(dep)) -> dict:
        return {"ok": True}

    # Sin rol asignado -> 403 (NO se auto-pone admin).
    assert TestClient(app).get("/adminish").status_code == 403
