# -*- coding: utf-8 -*-
"""
b2b_ai.auth — Autenticación por JWT + RBAC multi-tenant para la API enterprise.

Módulos:
  - roles.py      : definición de roles y matriz de permisos por endpoint.
  - users.py      : UserManager (ciclo de vida de usuarios, login, tokens).
  - middleware.py : validación de JWT, control de acceso por rol, aislamiento
                    de tenant y auditoría por request (dependencias FastAPI).
  - api.py        : router con los endpoints /api/v1/auth/* y
                    /api/v1/tenants/{id}/users/*.
"""
from b2b_ai.auth.roles import (VALID_ROLES, PERMISSIONS, is_valid_role,
                               role_permissions, has_permission)
from b2b_ai.auth.middleware import (JWTAuth, JWTError, encode_token,
                                    decode_token, jwt_secret,
                                    check_jwt_config)
from b2b_ai.auth.users import (UserManager, UserExistsError,
                               UserNotFoundError, LastAdminError,
                               InvalidRoleError, InvalidEmailError,
                               InvalidTokenError)

__all__ = [
    "VALID_ROLES", "PERMISSIONS", "is_valid_role", "role_permissions",
    "has_permission",
    "JWTAuth", "JWTError", "encode_token", "decode_token", "jwt_secret",
    "check_jwt_config",
    "UserManager", "UserExistsError", "UserNotFoundError", "LastAdminError",
    "InvalidRoleError", "InvalidEmailError", "InvalidTokenError",
]
