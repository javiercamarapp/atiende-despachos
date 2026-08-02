# -*- coding: utf-8 -*-
"""API Key authentication for the B2B AI API."""
from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

__all__ = ["APIKeyAuth", "make_require_api_key"]


class APIKeyAuth:
    """Resolves API keys against DB table `api_keys` or env B2B_API_KEY."""

    def __init__(self, db=None):
        self.db = db
        self._env_key: Optional[str] = os.environ.get("B2B_API_KEY", "").strip()

    def validate(self, key: str) -> bool:
        """Return True if the key is valid."""
        if not key:
            return False
        # Standalone mode: single key from env
        if self._env_key:
            return key == self._env_key
        # Multi-tenant mode: check DB
        if self.db is not None:
            try:
                row = self.db.query(
                    "SELECT 1 FROM api_keys WHERE key = %s AND active = true LIMIT 1",
                    (key,),
                )
                return bool(row)
            except Exception:
                return False
        # Fallback: allow any non-empty key in dev
        return bool(key)

    def get_tenant_id(self, key: str) -> Optional[str]:
        """Return tenant_id for the given key (multi-tenant mode only)."""
        if self._env_key:
            return None
        if self.db is None:
            return None
        try:
            row = self.db.query(
                "SELECT tenant_id FROM api_keys WHERE key = %s AND active = true LIMIT 1",
                (key,),
            )
            if row:
                return row[0].get("tenant_id")
        except Exception:
            pass
        return None


def make_require_api_key(auth: APIKeyAuth):
    """Build a FastAPI Depends() function for API-key auth."""

    async def _require(key: Annotated[Optional[str], APIKeyHeader(name="X-API-Key")]):
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
        return key

    return _require
