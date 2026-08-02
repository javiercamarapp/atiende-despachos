# -*- coding: utf-8 -*-
"""seed.py — Roles por defecto con permisos predefinidos.

Define la matriz de permisos de los cuatro roles del piloto del despacho:

    admin     — todos los permisos (es el rol de gestión).
    contador  — operación completa de CFDI / nómina + lectura de reportes,
                billing y settings (no gestiona usuarios).
    auditor   — solo lectura de todo (no escribe ni gestiona usuarios).
    readonly  — solo lectura de CFDI y reportes (usuario externo).

`seed_default_roles()` es idempotente: si ya existe un rol con el mismo nombre
builtin, no lo duplica.
"""
from __future__ import annotations

from typing import List

from b2b_ai.features.roles.models import (
    Permission,
    Role,
    find_role_by_name,
    save_role,
)

# name -> (permisos, descripción)
DEFAULT_ROLE_DEFS: "dict[str, tuple[list[str], str]]" = {
    "admin": (
        list(Permission.ALL),
        "Administrador: acceso total, incluida la gestión de usuarios y roles.",
    ),
    "contador": (
        [
            Permission.CFDI_READ, Permission.CFDI_WRITE,
            Permission.NOMINAS_READ, Permission.NOMINAS_WRITE,
            Permission.REPORTES_READ,
            Permission.BILLING_READ,
            Permission.SETTINGS_READ,
        ],
        "Contador: opera CFDI y nómina; lee reportes, billing y settings.",
    ),
    "auditor": (
        [
            Permission.CFDI_READ,
            Permission.NOMINAS_READ,
            Permission.REPORTES_READ,
            Permission.BILLING_READ,
            Permission.SETTINGS_READ,
        ],
        "Auditor: solo lectura de toda la información del despacho.",
    ),
    "readonly": (
        [
            Permission.CFDI_READ,
            Permission.REPORTES_READ,
        ],
        "Solo lectura: consulta CFDI y reportes (usuario externo).",
    ),
}


def seed_default_roles() -> List[Role]:
    """Crea los roles por defecto (builtin) si no existen. Idempotente."""
    created: List[Role] = []
    for name, (perms, desc) in DEFAULT_ROLE_DEFS.items():
        existing = find_role_by_name(name)
        if existing is not None:
            created.append(existing)
            continue
        role = Role(
            name=name,
            permissions=perms,
            description=desc,
            tenant_id=None,
            builtin=True,
        )
        save_role(role)
        created.append(role)
    return created
