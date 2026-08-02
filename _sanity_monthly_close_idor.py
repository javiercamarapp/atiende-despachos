# -*- coding: utf-8 -*-
"""Sanity runtime del fix IDOR+RBAC de monthly_close (NO pytest).

Re-verificación commit 4172261: _get_owned_period, make_require_permission,
Permission.CLOSE_VIEW/CLOSE_MANAGE. Ejecutar con el venv del repo.

Uso: .venv/bin/python3 _sanity_monthly_close_idor.py
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.monthly_close.service import _reset_state as mc_reset
from b2b_ai.features.roles.models import _reset_state as roles_reset
from b2b_ai.features.monthly_close.routes import build_monthly_close_router
from b2b_ai.features.roles.service import RolesService
from b2b_ai.features.roles.seed import seed_default_roles

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _auth_for(tenant_id, user_id=""):
    ctx = {"key": "test-key", "tenant_id": tenant_id}
    if user_id:
        ctx["user_id"] = user_id
    return lambda: ctx


def _client(tenant_id, user_id=""):
    app = FastAPI()
    app.include_router(build_monthly_close_router(
        db=None, require_api_key=_auth_for(tenant_id, user_id)))
    return TestClient(app)


def _open(client, tenant_id, year=2024, month=6):
    r = client.post("/api/v1/close-monthly/open",
                    json={"year": year, "month": month})
    assert r.status_code == 200, r.text
    return r.json()["period"]["id"]


def main():
    print("Sanity monthly_close IDOR+RBAC (commit 4172261)\n")
    mc_reset(); roles_reset()

    # ---------- IDOR: aislamiento multi-tenant ----------
    print("[IDOR] período de tenant A vs tenant B")
    c_a = _client("tenant_A")
    c_b = _client("tenant_B")
    pid = _open(c_a, "tenant_A")

    check("dueño ve su período (200)",
          c_a.get(f"/api/v1/close-monthly/{pid}").status_code == 200)

    r = c_b.get(f"/api/v1/close-monthly/{pid}")
    check("otro tenant GET -> 404 (no 403)", r.status_code == 404,
          f"got {r.status_code}")

    body = c_a.get(f"/api/v1/close-monthly/{pid}").json()
    task_id = body["tasks"][0]["id"]

    r = c_b.post(f"/api/v1/close-monthly/{pid}/tasks/{task_id}/complete",
                 json={"task_id": task_id, "user_id": "u_attacker"})
    check("otro tenant complete -> 404", r.status_code == 404,
          f"got {r.status_code}")

    r = c_b.post(f"/api/v1/close-monthly/{pid}/auto-check",
                 json={"module_state": {"cfdi_pending_count": 0}})
    check("otro tenant auto-check -> 404", r.status_code == 404,
          f"got {r.status_code}")

    r = c_b.post(f"/api/v1/close-monthly/{pid}/close",
                 json={"user_id": "u_attacker"})
    check("otro tenant close -> 404", r.status_code == 404,
          f"got {r.status_code}")

    # Dueño sigue pudiendo operar tras los intentos del otro tenant.
    r = c_a.post(f"/api/v1/close-monthly/{pid}/tasks/{task_id}/complete",
                 json={"task_id": task_id, "user_id": "u_owner"})
    check("dueño sigue completando (200)", r.status_code == 200
          and r.json()["task"]["status"] == "DONE", f"got {r.status_code}")

    # ---------- RBAC: CLOSE_VIEW / CLOSE_MANAGE ----------
    print("\n[RBAC] permisos CLOSE_VIEW / CLOSE_MANAGE")
    seed_default_roles()
    svc = RolesService()
    roles = {r.name: r for r in svc.list_roles()}

    check("admin hereda CLOSE_VIEW y CLOSE_MANAGE",
          Permission_CLOSE_VIEW in _perms(roles["admin"])
          and Permission_CLOSE_MANAGE in _perms(roles["admin"]))
    check("contador tiene CLOSE_VIEW y CLOSE_MANAGE",
          Permission_CLOSE_VIEW in _perms(roles["contador"])
          and Permission_CLOSE_MANAGE in _perms(roles["contador"]))
    check("auditor tiene CLOSE_VIEW (solo lectura)",
          Permission_CLOSE_VIEW in _perms(roles["auditor"])
          and Permission_CLOSE_MANAGE not in _perms(roles["auditor"]))
    check("readonly NO tiene permisos de cierre",
          Permission_CLOSE_VIEW not in _perms(roles["readonly"])
          and Permission_CLOSE_MANAGE not in _perms(roles["readonly"]))

    # contador (tiene CLOSE_MANAGE) puede abrir período -> 200
    svc.assign_role("user_contador", "tenant_A", roles["contador"].id)
    c_cont = _client("tenant_A", user_id="user_contador")
    r = c_cont.post("/api/v1/close-monthly/open",
                    json={"year": 2030, "month": 6})
    check("contador CLOSE_MANAGE abre período (200)",
          r.status_code == 200, f"got {r.status_code}")

    # readonly (sin CLOSE_MANAGE) -> 403
    svc.assign_role("user_readonly", "tenant_A", roles["readonly"].id)
    c_ro = _client("tenant_A", user_id="user_readonly")
    r = c_ro.post("/api/v1/close-monthly/open",
                  json={"year": 2025, "month": 1})
    check("readonly sin CLOSE_MANAGE -> 403", r.status_code == 403,
          f"got {r.status_code}")

    mc_reset(); roles_reset()
    print(f"\nRESULTADO: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


def _perms(role):
    return set(role.permissions)


from b2b_ai.features.roles.models import Permission as P
Permission_CLOSE_VIEW = P.CLOSE_VIEW
Permission_CLOSE_MANAGE = P.CLOSE_MANAGE


if __name__ == "__main__":
    import sys
    sys.exit(main())
