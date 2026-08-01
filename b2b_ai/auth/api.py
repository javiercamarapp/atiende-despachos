# -*- coding: utf-8 -*-
"""
api.py — Endpoints de auth enterprise (JWT + RBAC multi-tenant).

  POST /api/v1/auth/register                  alta (bootstrap del 1er admin o
                                              admin del tenant)
  POST /api/v1/auth/login                     login (email+password) → tokens
  POST /api/v1/auth/refresh                   refresh de tokens
  GET  /api/v1/auth/me                        usuario autenticado
  PUT  /api/v1/auth/me                        actualizar perfil propio
  GET  /api/v1/tenants/{id}/users             listar usuarios (admin)
  POST /api/v1/tenants/{id}/users             crear usuario (admin)
  PUT  /api/v1/tenants/{id}/users/{uid}/role  cambiar rol (admin)

Aislamiento: las rutas /tenants/{id}/* exigen que el token pertenezca al
mismo tenant y al rol admin (require_tenant_admin). /auth/me opera sobre el
propio usuario del token.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from b2b_ai.auth.middleware import JWTAuth, JWTError, _extract_bearer, _public_user
from b2b_ai.auth.roles import has_permission, is_valid_role, normalize_role
from b2b_ai.auth.users import (UserManager, UserExistsError, InvalidRoleError,
                               InvalidEmailError, InvalidPasswordError,
                               InvalidTokenError)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class RegisterBody(BaseModel):
    email: str
    password: str
    tenant_id: int
    role: str = "contador"
    name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str
    tenant_id: Optional[int] = None


class RefreshBody(BaseModel):
    refresh_token: str


class UpdateMeBody(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class CreateUserBody(BaseModel):
    email: str
    password: str
    name: str = ""
    role: str = "contador"


class ChangeRoleBody(BaseModel):
    role: str


def _admin_context(jwt: JWTAuth, db, authorization: Optional[str],
                   tenant_id: int) -> dict:
    """Valida el token y exige admin del `tenant_id`. Usado por register
    (que admite bootstrap sin token) y por las rutas admin explícitas."""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401,
                            detail="Se requiere sesión (Bearer token).")
    try:
        claims = jwt.decode(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o caducado.")
    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token no es de acceso.")
    try:
        user = db.get_client_user(int(claims["sub"]))
    except (KeyError, ValueError, TypeError):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario inexistente.")
    if user["tenant_id"] != tenant_id:
        raise HTTPException(status_code=403, detail="Acceso a otro tenant denegado.")
    if not has_permission(user.get("role"), "users.manage"):
        raise HTTPException(status_code=403, detail="Requiere rol admin.")
    return user


def build_auth_router(db) -> APIRouter:
    um = UserManager(db)
    jwt = um.jwt
    router = APIRouter(prefix="/api/v1", tags=["auth"])

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #
    @router.post("/auth/register", summary="Alta de usuario (bootstrap o admin).")
    def register(body: RegisterBody,
                 authorization: Optional[str] = Header(default=None)):
        tenant_id = body.tenant_id
        existing = db.has_tenant_users(tenant_id)
        role = body.role
        if existing:
            # Requiere admin autenticado del mismo tenant.
            _admin_context(jwt, db, authorization, tenant_id)
        else:
            # Bootstrap: el primer usuario del tenant se crea como admin.
            role = "admin"
        try:
            user = um.create_user(body.email, body.password, tenant_id,
                                  role=role, name=body.name)
        except UserExistsError:
            raise HTTPException(409, "El email ya está registrado en este tenant.")
        except (InvalidEmailError, InvalidPasswordError):
            raise HTTPException(422, "Email inválido o password demasiado corto.")
        except InvalidRoleError:
            raise HTTPException(422, "Rol inválido.")
        db.log_call("auth", "register", entity="user",
                    entity_id=str(user["id"]), payload={"email": user["email"]},
                    status="ok", tenant_id=tenant_id)
        return {"ok": True, "user": user}

    @router.post("/auth/login", summary="Login email+password → tokens JWT.")
    def login(body: LoginBody):
        session = um.authenticate(body.email, body.password,
                                  tenant_id=body.tenant_id)
        if session is None:
            db.log_call("auth", "login", entity="user",
                        payload={"email": (body.email or "").lower()},
                        status="denied")
            raise HTTPException(status_code=401, detail="Credenciales inválidas.")
        db.log_call("auth", "login", entity="user",
                    entity_id=str(session["user"]["id"]),
                    payload={"email": session["user"]["email"]},
                    status="ok", tenant_id=session["user"]["tenant_id"])
        return {"user": session["user"],
                "access_token": session["access_token"],
                "refresh_token": session["refresh_token"],
                "tenant_id": session["user"]["tenant_id"]}

    @router.post("/auth/refresh", summary="Refresca la sesión con un refresh token.")
    def refresh(body: RefreshBody):
        try:
            session = um.refresh_token(body.refresh_token)
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail="Token de refresco inválido.")
        return session

    @router.get("/auth/me", summary="Usuario autenticado.")
    def me(ctx: dict = Depends(jwt.require_auth)):
        return {"user": ctx["user"], "tenant_id": ctx["tenant_id"],
                "role": ctx["role"]}

    @router.put("/auth/me", summary="Actualiza el perfil del usuario autenticado.")
    def update_me(body: UpdateMeBody, ctx: dict = Depends(jwt.require_auth)):
        data = body.model_dump(exclude_none=True)
        try:
            user = um.update_user(ctx["user_id"], data)
        except UserExistsError:
            raise HTTPException(409, "Email ya registrado en este tenant.")
        except (InvalidEmailError, InvalidPasswordError):
            raise HTTPException(422, "Email inválido o password demasiado corto.")
        if user is None:
            raise HTTPException(404, "Usuario no encontrado.")
        return {"user": user}

    # ------------------------------------------------------------------ #
    # Gestión de usuarios por tenant (solo admin)
    # ------------------------------------------------------------------ #
    @router.get("/tenants/{tenant_id}/users", summary="Lista los usuarios del tenant.")
    def list_users(tenant_id: int, ctx: dict = Depends(jwt.require_tenant_admin())):
        users = [_public_user(u) for u in db.list_client_users(tenant_id)]
        return {"tenant_id": tenant_id, "count": len(users), "users": users}

    @router.post("/tenants/{tenant_id}/users", summary="Crea un usuario en el tenant.")
    def create_tenant_user(tenant_id: int, body: CreateUserBody,
                           ctx: dict = Depends(jwt.require_tenant_admin())):
        try:
            user = um.create_user(body.email, body.password, tenant_id,
                                  role=body.role, name=body.name)
        except UserExistsError:
            raise HTTPException(409, "El email ya está registrado en este tenant.")
        except (InvalidEmailError, InvalidPasswordError):
            raise HTTPException(422, "Email inválido o password demasiado corto.")
        except InvalidRoleError:
            raise HTTPException(422, "Rol inválido.")
        db.log_call("auth", "create_user", entity="user",
                    entity_id=str(user["id"]), payload={"email": user["email"]},
                    status="ok", tenant_id=tenant_id)
        return {"ok": True, "user": user}

    @router.put("/tenants/{tenant_id}/users/{user_id}/role",
                summary="Cambia el rol de un usuario (admin).")
    def change_role(tenant_id: int, user_id: int, body: ChangeRoleBody,
                    ctx: dict = Depends(jwt.require_tenant_admin())):
        role = normalize_role(body.role)
        if not role:
            raise HTTPException(422, "Rol inválido.")
        target = db.get_client_user(user_id)
        if target is None or target["tenant_id"] != tenant_id:
            raise HTTPException(404, "Usuario no encontrado.")
        # No degradar al último admin del tenant.
        if (target.get("role") == "admin"
                and role != "admin"
                and ctx["user_id"] == user_id):
            raise HTTPException(403, "No puedes degradar tu propio rol admin.")
        if target.get("role") == "admin" and role != "admin":
            admins = [u for u in db.list_client_users(tenant_id)
                      if (u.get("role") or "") == "admin"]
            if len(admins) <= 1:
                raise HTTPException(403,
                                    "No se puede degradar al último admin.")
        db.update_client_user(user_id, {"role": role})
        db.log_call("auth", "change_role", entity="user", entity_id=str(user_id),
                    payload={"old": target.get("role"), "new": role,
                             "by": ctx["user_id"]},
                    status="ok", tenant_id=tenant_id)
        return {"ok": True, "user": _public_user(db.get_client_user(user_id))}

    return router
