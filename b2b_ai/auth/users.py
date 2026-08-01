# -*- coding: utf-8 -*-
"""
users.py — UserManager: ciclo de vida de usuarios enterprise (RBAC).

Reutiliza la tabla `client_users` (UNIQUE(tenant_id, email)) para no duplicar
el modelo: cada usuario pertenece a un tenant y su rol se guarda en
`client_users.role` (admin | contador | auxiliar | auditor).

Cubre: alta, autenticación (email+password con bcrypt), emisión/refresco de
tokens JWT, consulta, actualización, baja y reset de password.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

import bcrypt

from b2b_ai.db.db import Database
from b2b_ai.auth.middleware import JWTAuth, JWTError, _public_user
from b2b_ai.auth.roles import is_valid_role, normalize_role

# Rounds bcrypt (ajustable por env para acelerar tests / CI).
BCRYPT_ROUNDS = int(os.environ.get("B2B_BCRYPT_ROUNDS", "12"))

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserExistsError(Exception):
    """Email ya registrado en el tenant."""


class UserNotFoundError(Exception):
    """El usuario no existe."""


class LastAdminError(Exception):
    """No se puede borrar / degradar el último admin del tenant."""


class InvalidRoleError(Exception):
    """Rol no soportado."""


class InvalidPasswordError(Exception):
    """Password no cumple la política mínima."""


class InvalidEmailError(Exception):
    """El email no tiene un formato válido."""


class InvalidTokenError(Exception):
    """Token de refresco inválido / caducado / de otro tipo."""


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"),
                         bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def _check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _validate_password(password: str) -> None:
    """Valida que el password cumpla la política de seguridad enterprise.

    Requisitos:
        - Mínimo 10 caracteres (up from 8)
        - Al menos 1 mayúscula
        - Al menos 1 minúscula
        - Al menos 1 dígito
        - Al menos 1 carácter especial (!@#$%^&*...)

    Lanza InvalidPasswordError si no cumple.
    """
    if not password:
        raise InvalidPasswordError("El password no puede estar vacío.")
    errors = []
    if len(password) < 10:
        errors.append("al menos 10 caracteres")
    if not re.search(r"[A-Z]", password):
        errors.append("al menos 1 letra mayúscula")
    if not re.search(r"[a-z]", password):
        errors.append("al menos 1 letra minúscula")
    if not re.search(r"\d", password):
        errors.append("al menos 1 dígito")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", password):
        errors.append("al menos 1 carácter especial (!@#$%^&*...)")
    if errors:
        raise InvalidPasswordError(
            "El password debe tener: " + ", ".join(errors) + "."
        )


class UserManager:
    """Operaciones de usuarios + sesiones JWT por tenant."""

    def __init__(self, db: Optional[Database] = None,
                 jwt_auth: Optional[JWTAuth] = None) -> None:
        self.db = db or Database()
        self.jwt = jwt_auth or JWTAuth(self.db)

    # ---- Alta ------------------------------------------------------------
    def create_user(self, email: str, password: str, tenant_id: int,
                    role: str = "contador", name: str = "") -> Dict[str, Any]:
        """Crea un usuario en el tenant. Devuelve el dict público (sin hash)."""
        email = _norm_email(email)
        if not _EMAIL_RE.match(email):
            raise InvalidEmailError("Email inválido.")
        _validate_password(password)
        normalized = normalize_role(role)
        if not normalized:
            raise InvalidRoleError(f"Rol inválido: {role!r}")
        if self.db.get_client_user_by_email(email, tenant_id=tenant_id):
            raise UserExistsError(
                "El email ya está registrado en este tenant.")
        pw_hash = _hash_password(password)
        user_id = self.db.create_client_user(
            tenant_id, email, pw_hash, name or email, role=normalized)
        return _public_user(self.db.get_client_user(user_id))

    # ---- Autenticación ---------------------------------------------------
    def authenticate(self, email: str, password: str,
                     tenant_id: Optional[int] = None) -> Optional[Dict]:
        """Valida credenciales. Devuelve {user, access_token, refresh_token}
        o None si son inválidas."""
        email = _norm_email(email)
        user = self.db.get_client_user_by_email(email, tenant_id=tenant_id)
        if user is None or not _check_password(password, user["password_hash"]):
            self._audit_failed(email)
            return None
        return self._session(user)

    def _session(self, user: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user": _public_user(user),
            "access_token": self.jwt.access_token(user),
            "refresh_token": self.jwt.refresh_token(user),
        }

    def _audit_failed(self, email: str) -> None:
        try:
            self.db.log_call("auth", "login", entity="user",
                             entity_id="", payload={"email": email},
                             status="denied")
        except Exception:  # noqa: BLE001
            pass

    # ---- Tokens ----------------------------------------------------------
    def refresh_token(self, token: str) -> Dict[str, Any]:
        """Refresca una sesión a partir de un refresh token válido."""
        try:
            claims = self.jwt.decode(token)
        except JWTError:
            raise InvalidTokenError("Token inválido o caducado.")
        if claims.get("type") != "refresh":
            raise InvalidTokenError("No es un token de refresco.")
        try:
            user_id = int(claims["sub"])
        except (KeyError, ValueError, TypeError):
            raise InvalidTokenError("Token malformado.")
        user = self.db.get_client_user(user_id)
        if user is None:
            raise InvalidTokenError("Usuario inexistente.")
        return self._session(user)

    # ---- Consulta / actualización / baja --------------------------------
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        user = self.db.get_client_user(user_id)
        return _public_user(user) if user else None

    def update_user(self, user_id: int, data: Dict[str, Any]) -> Optional[Dict]:
        """Actualiza name / email / password de un usuario. Devuelve el
        usuario público, o None si no existe."""
        if self.db.get_client_user(user_id) is None:
            return None
        update: Dict[str, Any] = {}
        if "name" in data and data["name"] is not None:
            update["name"] = data["name"]
        if "email" in data and data["email"] is not None:
            email = _norm_email(data["email"])
            if not _EMAIL_RE.match(email):
                raise InvalidEmailError("Email inválido.")
            existing = self.db.get_client_user_by_email(
                email, tenant_id=self.db.get_client_user(user_id)["tenant_id"])
            if existing is not None and existing["id"] != user_id:
                raise UserExistsError("Email ya registrado en este tenant.")
            update["email"] = email
        if "password" in data and data["password"] is not None:
            _validate_password(data["password"])
            update["password_hash"] = _hash_password(data["password"])
        if update:
            self.db.update_client_user(user_id, update)
        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> None:
        """Elimina un usuario. Protege al último admin del tenant."""
        user = self.db.get_client_user(user_id)
        if user is None:
            raise UserNotFoundError("Usuario no encontrado.")
        admins = [u for u in self.db.list_client_users(user["tenant_id"])
                  if (u.get("role") or "") == "admin"]
        if (user.get("role") == "admin" and len(admins) <= 1):
            raise LastAdminError(
                "No se puede eliminar al último admin del tenant.")
        self.db.delete_client_user(user_id)

    # ---- Reset de password ----------------------------------------------
    def password_reset(self, email: str,
                       tenant_id: Optional[int] = None) -> Optional[Dict]:
        """Genera un token de reset para el email (si existe). Devuelve
        {user, reset_token} o None (sin revelar si el email existe)."""
        email = _norm_email(email)
        user = self.db.get_client_user_by_email(email, tenant_id=tenant_id)
        if user is None:
            return None
        token = self.jwt.reset_token(user)
        return {"user": _public_user(user), "reset_token": token}
