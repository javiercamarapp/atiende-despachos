# -*- coding: utf-8 -*-
"""API Key authentication for the B2B AI API.

Auth flow (multi-tenant + standalone):

- `make_require_api_key(auth)` builds a FastAPI dependency that, for a valid
  key, returns a **dict** context:
      {"key": <raw key>, "tenant_id": <str|int or None>, "user_id": <...>}
  Every router that uses the dependency reads `auth_info.get("tenant_id")`
  (dict-style). Historically this returned a bare string, which crashed every
  router with `AttributeError` -> HTTP 500. Fixed by returning the dict.

- Tenant isolation: a valid key that resolves to NO tenant is **rejected**
  with HTTP 400. The dependency never degrades to a shared "default" tenant
  (that would let one tenant read another's data). To run in standalone /
  single-tenant mode, set `B2B_DEFAULT_TENANT_ID` so a key without a DB
  tenant still resolves to a concrete tenant.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

__all__ = ["APIKeyAuth", "make_require_api_key", "resolve_tenant_from_env"]


def resolve_tenant_from_env() -> Optional[str]:
    """Fallback tenant id for keys without a DB tenant (standalone mode).

    Reads B2B_DEFAULT_TENANT_ID (canonical). Returns None when unset.
    """
    return os.environ.get("B2B_DEFAULT_TENANT_ID", "").strip() or None


class APIKeyAuth:
    """Resolves API keys against DB table `api_keys` or env B2B_API_KEY."""

    def __init__(self, db=None):
        self.db = db
        self._env_key: Optional[str] = os.environ.get("B2B_API_KEY", "").strip()

    # -- key lookup --------------------------------------------------------
    def _lookup(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the api_keys row (dict) for a DB-backed key, or None.

        Uses `Database.get_api_key`, which hashes internally. The old code
        called a non-existent `self.db.query(...)` method, so DB resolution
        silently failed (validate=False / tenant=None). Fixed here.
        """
        if self.db is None:
            return None
        try:
            return self.db.get_api_key(key)
        except Exception:  # noqa: BLE001 — auth must never crash a request
            return None

    def validate(self, key: str) -> bool:
        """Return True if the key is valid."""
        if not key:
            return False
        # Standalone mode: single key from env
        if self._env_key:
            return key == self._env_key
        # Multi-tenant mode: check DB
        if self.db is not None:
            return self._lookup(key) is not None
        # Fallback: allow any non-empty key in dev
        return bool(key)

    def get_tenant_id(self, key: str) -> Optional[str]:
        """Return tenant_id for the given key (multi-tenant mode only)."""
        # Standalone env key has no DB tenant; the env fallback applies
        # (resolve_tenant_from_env) at the dependency level.
        if self._env_key:
            return None
        if self.db is None:
            return None
        row = self._lookup(key)
        if row:
            return row.get("tenant_id")
        return None

    def get_user_id(self, key: str) -> Optional[Any]:
        """Stable actor id derived from the key row (or None)."""
        row = self._lookup(key)
        if row:
            # api_keys has no user column; the row id is a stable pseudo-user
            # that still isolates actors per key.
            return row.get("id")
        return None

    def resolve(self, key: str) -> Optional[Dict[str, Any]]:
        """Full auth context dict (used by audit middleware + tests).

        Returns None if the key is invalid; otherwise a dict with key,
        tenant_id (env-fallback applied), user_id and a source tag.
        """
        if not key or not self.validate(key):
            return None
        tenant_id = self.get_tenant_id(key)
        if tenant_id is None:
            tenant_id = resolve_tenant_from_env()
        return {
            "key": key,
            "tenant_id": tenant_id,
            "user_id": self.get_user_id(key),
            "name": key,
            "source": "env" if self._env_key else "db",
        }


def make_require_api_key(auth: APIKeyAuth):
    """Build a FastAPI Depends() function for API-key auth.

    Returns a dict context:
        {"key": key, "tenant_id": tenant_id, "user_id": user_id}

    Security: a valid key that resolves to no tenant_id is rejected with
    HTTP 400 (multi-tenant isolation). It never degrades to "default".
    """

    async def _require(key: Optional[str] = Depends(_api_key_scheme)):
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-API-Key",
            )
        if not auth.validate(key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        tenant_id = auth.get_tenant_id(key)
        if tenant_id is None:
            tenant_id = resolve_tenant_from_env()

        if tenant_id is None:
            # Multi-tenant isolation: never silently run as a shared tenant.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key is not bound to a tenant. Set B2B_DEFAULT_TENANT_ID "
                       "or bind the key to a tenant; refusing to degrade to a "
                       "shared 'default' tenant.",
            )

        return {
            "key": key,
            "tenant_id": tenant_id,
            "user_id": auth.get_user_id(key),
        }

    return _require
