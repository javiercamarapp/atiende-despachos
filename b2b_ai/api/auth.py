# -*- coding: utf-8 -*-
"""
auth.py — Autenticación por API key para la API real.

Diseño:
  - Cada cliente (despacho) tiene una API key. Se envía en el header
    `X-API-Key`.
  - La key se resuelve contra una tabla `api_keys` en la DB (multi-tenant:
    cada key está asociada a un tenant_id), con fallback a variables de
    entorno para el caso de una sola key de servicio (B2B_API_KEY).
  - FastAPI dependency `require_api_key` protege los endpoints /api/v1/*.

Seguridad mínima en producción:
  - Las keys se comparan de forma constante (no cortocircuito).
  - Se audita cada intento fallido de autenticación.
  - Nunca se expone la key en respuestas.
"""
from __future__ import annotations

import hmac
import os
from typing import Any, Callable, Dict, Optional

from fastapi import Header, HTTPException, Request

# Variable de entorno con la key maestra de servicio (uso standalone).
ENV_API_KEY = "B2B_API_KEY"


def _constant_time_eq(a: str, b: str) -> bool:
    """Comparación de strings a prueba de timing side-channel."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class APIKeyAuth:
    """Resuelve API keys contra la tabla api_keys de la DB (o env)."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._env_key = os.environ.get(ENV_API_KEY, "") or ""

    def resolve(self, key: str) -> Optional[Dict[str, Any]]:
        """Devuelve {tenant_id, name} si la key es válida; si no, None."""
        if not key:
            return None
        # 1) Key de servicio por env (single-tenant / prueba)
        if self._env_key and _constant_time_eq(key, self._env_key):
            return {"tenant_id": None, "name": "service", "source": "env"}
        # 2) Key en DB (multi-tenant)
        try:
            row = self._db.get_api_key(key)
            if row:
                return {"tenant_id": row["tenant_id"], "name": row["name"],
                        "source": "db"}
        except Exception:  # noqa: BLE001  (tabla ausente en DBs muy viejas)
            return None
        return None


def _extract_key(x_api_key: Optional[str]) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401,
                            detail="Falta header X-API-Key.")
    return x_api_key


def make_require_api_key(auth: APIKeyAuth) -> Callable[..., Dict[str, Any]]:
    """Fabrica una FastAPI dependency que exige API key válida.

    Devuelve el dict {tenant_id, name, source} para inyectar en handlers.
    Los intentos fallidos se registran en el audit_log (cuando la DB lo
    permita).
    """
    def require_api_key(request: Request,
                        x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        key = _extract_key(x_api_key)
        info = auth.resolve(key)
        if info is None:
            _log_failed(request, key, auth)
            raise HTTPException(status_code=401,
                                detail="API key inválida o no autorizada.")
        # Tenant bloqueado (tenant admin): rechaza con 403. Se aplica también
        # a /api/v1/* — un tenant bloqueado no opera con ninguna versión.
        tid = info.get("tenant_id")
        if tid is not None:
            try:
                row = auth._db.get_tenant_by_id(tid)
                if row is not None and row.get("blocked"):
                    raise HTTPException(status_code=403,
                                        detail="Tenant bloqueado.")
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001
                pass
        return info
    return require_api_key


def _log_failed(request: Request, key: str, auth: APIKeyAuth) -> None:
    """Intenta registrar el intento fallido sin romper la petición."""
    try:
        db = auth._db
        # No guardamos la key completa por seguridad (podría ser un secreto
        # tipeado mal); guardamos su longitud y un hash corto para forense.
        import hashlib
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        db.log_call("api_auth", "authorize", entity="api",
                    entity_id=h, payload={"len": len(key)}, status="denied")
    except Exception:  # noqa: BLE001
        pass
