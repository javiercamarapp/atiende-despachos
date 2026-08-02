# -*- coding: utf-8 -*-
"""
middleware.py — Validación de JWT, control de acceso por roles (RBAC),
aislamiento multi-tenant y auditoría por request para la API enterprise.

Sin dependencias externas: los JWT se firman con HMAC-SHA256 (HS256) usando
la librería estándar (hmac / base64 / hashlib), consistente con el estilo del
resto del auth de Likida AI Enterprise (comparaciones en tiempo constante con hmac).

Secret: se lee de `B2B_JWT_SECRET` y debe medir al menos 32 caracteres. Si
falta, el arranque FALLA salvo si `B2B_ENV` dice explícitamente que es un
entorno de desarrollo (dev/development/test/testing/local), donde se genera uno
aleatorio por proceso. `B2B_ENV` sin definir cuenta como producción. No hay
ningún secreto literal en el código: ver el bloque de `jwt_secret()`.

Dependencias FastAPI expuestas por `JWTAuth`:
  - require_auth            : valida el Bearer token y devuelve el contexto
                              del usuario autenticado.
  - require_permission(p)   : exige el permiso `p` (RBAC).
  - require_tenant_admin()  : exige ser admin DEL tenant del path param.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request

from b2b_ai.auth.roles import has_permission

# In-memory token blacklist (JTI -> expiry timestamp).
# In production, replace with Redis SET with TTL or DB table.
_token_blacklist: Dict[str, float] = {}

# TTLs por tipo de token (segundos), ajustables por env.
ACCESS_TTL = int(os.environ.get("B2B_JWT_ACCESS_TTL", "1800"))      # 30 min
REFRESH_TTL = int(os.environ.get("B2B_JWT_REFRESH_TTL", "604800"))  # 7 días
RESET_TTL = int(os.environ.get("B2B_JWT_RESET_TTL", "3600"))        # 1 hora

# Nombre de la variable de entorno (no es un secreto).
_JWT_SECRET_ENV = "B2B_JWT_SECRET"

# Longitud mínima aceptada (32 bytes ≈ el `openssl rand -hex 32` de la doc).
# Un secreto corto es fuerza-brutable offline a partir de un solo token.
MIN_SECRET_LEN = 32

# NO hay secreto de desarrollo literal en el código.
#
# Aquí vivía una constante `_DEV_SECRET` con un literal fijo, usada como
# fallback de `jwt_secret()`. Con la env sin definir, la aplicación arrancaba
# igual y firmaba y validaba tokens con una cadena publicada en el repositorio:
# cualquiera podía forjar un access token con el `tenant_id` y el `role` que
# quisiera. El fallo de configuración más común que existe —un `.env`
# incompleto— dejaba la autenticación entera abierta.
#
# Ahora, sin la env definida:
#   · con B2B_ENV en dev/development/test/testing/local se genera un
#     secreto ALEATORIO por proceso. Los tokens siguen funcionando dentro de una
#     misma corrida y dejan de servir al reiniciar, que es justo lo que se
#     quiere de un entorno de desarrollo.
#   · en cualquier otro caso —incluido B2B_ENV SIN DEFINIR— se lanza y el
#     arranque falla ruidoso.
# `B2B_ENV` SIN DEFINIR NO CUENTA COMO DESARROLLO. El default tiene que ser el
# lado seguro: en Railway, Docker o cualquier PaaS lo normal es no definir esa
# variable, y si "vacío" significara desarrollo, ese despliegue arrancaría en
# silencio con secretos efímeros —sesiones que mueren en cada reinicio y en cada
# worker— sin que nada avise. Hay que pedir el entorno de desarrollo de forma
# explícita.
_DEV_ENVS = ("dev", "development", "test", "testing", "local")

_ephemeral_secret: Optional[str] = None


def _is_dev_env() -> bool:
    return os.environ.get("B2B_ENV", "").strip().lower() in _DEV_ENVS


def jwt_secret() -> str:
    """Secret de firma HS256.

    Lee `B2B_JWT_SECRET`. Si falta o es demasiado corto, falla en producción y
    genera uno efímero por proceso en desarrollo. Nunca devuelve un valor
    constante conocido.
    """
    global _ephemeral_secret
    secret = os.environ.get(_JWT_SECRET_ENV, "").strip()
    if secret:
        if len(secret) < MIN_SECRET_LEN:
            raise RuntimeError(
                f"{_JWT_SECRET_ENV} mide {len(secret)} caracteres; se requieren al "
                f"menos {MIN_SECRET_LEN}. Genera uno con: openssl rand -hex 32")
        return secret
    if not _is_dev_env():
        raise RuntimeError(
            f"{_JWT_SECRET_ENV} no está definida y B2B_ENV="
            f"{os.environ.get('B2B_ENV', '')!r} no es un entorno de desarrollo. "
            f"Sin ella no se pueden firmar tokens de forma segura. "
            f"Genera uno con: openssl rand -hex 32")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
    return _ephemeral_secret


def check_jwt_config() -> None:
    """Valida la configuración de firma al arrancar (fail-fast).

    La llama `create_app`, de modo que un despliegue mal configurado muere en el
    arranque con un mensaje claro en vez de servir tráfico con autenticación
    forjable.
    """
    jwt_secret()


class JWTError(Exception):
    """Token inválido, mal firmado, malformado o caducado."""


# --------------------------------------------------------------------------
# Codificación / decodificación HS256 (stdlib)
# --------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: str, secret: str) -> str:
    return _b64url(hmac.new(secret.encode("utf-8"), payload.encode("utf-8"),
                            hashlib.sha256).digest())


def encode_token(claims: Dict[str, Any], secret: Optional[str] = None,
                 ttl_seconds: Optional[int] = None) -> str:
    """Firma un JWT HS256 con los claims dados + iat/exp."""
    secret = secret or jwt_secret()
    now = int(time.time())
    full = dict(claims)
    full.setdefault("iat", now)
    full.setdefault("exp", now + (ttl_seconds or ACCESS_TTL))
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"},
                                separators=(",", ":")).encode("utf-8"))
    payload = _b64url(json.dumps(full, separators=(",", ":")).encode("utf-8"))
    sig = _sign(f"{header}.{payload}", secret)
    return f"{header}.{payload}.{sig}"


def decode_token(token: str, secret: Optional[str] = None,
                 leeway: int = 0) -> Dict[str, Any]:
    """Valida firma + expiración y devuelve los claims. Lanza JWTError."""
    secret = secret or jwt_secret()
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTError("Estructura de token inválida.")
    header_b64, payload_b64, sig = parts
    expected = _sign(f"{header_b64}.{payload_b64}", secret)
    if not hmac.compare_digest(sig, expected):
        raise JWTError("Firma inválida.")
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise JWTError("Payload inválido.") from exc
    if not isinstance(payload, dict):
        raise JWTError("Payload inválido.")
    now = time.time()
    if payload.get("exp") and now > float(payload["exp"]) + leeway:
        raise JWTError("Token caducado.")
    return payload


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extrae el token de un header `Authorization: Bearer <token>`."""
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Copia del usuario sin el hash de password (nunca se expone)."""
    out = dict(user)
    out.pop("password_hash", None)
    return out


# --------------------------------------------------------------------------
# JWTAuth: emisión de tokens + dependencias FastAPI
# --------------------------------------------------------------------------
class JWTAuth:
    """Encapsula firma/verificación de JWT y las dependencias de auth."""

    def __init__(self, db: Any, secret: Optional[str] = None) -> None:
        self._db = db
        self._secret = secret or jwt_secret()

    # ---- Emisión ---------------------------------------------------------
    def access_token(self, user: Dict[str, Any]) -> str:
        return encode_token(
            {"type": "access", "sub": str(user["id"]),
             "tenant_id": user["tenant_id"], "role": user.get("role"),
             "email": user.get("email"),
             "jti": secrets.token_urlsafe(16)},
            self._secret, ACCESS_TTL)

    def refresh_token(self, user: Dict[str, Any]) -> str:
        return encode_token(
            {"type": "refresh", "sub": str(user["id"]),
             "tenant_id": user["tenant_id"], "role": user.get("role"),
             "jti": secrets.token_urlsafe(12)},
            self._secret, REFRESH_TTL)

    def reset_token(self, user: Dict[str, Any]) -> str:
        return encode_token(
            {"type": "reset", "sub": str(user["id"]),
             "email": user.get("email")},
            self._secret, RESET_TTL)

    def decode(self, token: str) -> Dict[str, Any]:
        return decode_token(token, self._secret)

    # ---- Dependencias ----------------------------------------------------
    def _require_auth(self, request: Request,
                      authorization: Optional[str] = Header(default=None)):
        token = _extract_bearer(authorization)
        if not token:
            raise HTTPException(status_code=401,
                                detail="Se requiere sesión (Bearer token).")
        try:
            claims = self.decode(token)
        except JWTError:
            raise HTTPException(status_code=401,
                                detail="Token inválido o caducado.")
        if claims.get("type") != "access":
            raise HTTPException(status_code=401,
                                detail="Token no es de acceso.")
        # Check token blacklist (revoked tokens)
        jti = claims.get("jti")
        if jti and jti in _token_blacklist:
            raise HTTPException(status_code=401, detail="Token revocado.")
        try:
            user_id = int(claims["sub"])
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=401, detail="Token malformado.")
        user = self._db.get_client_user(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Usuario inexistente.")

        # Aislamiento / bloqueo de tenant: un tenant bloqueado no opera.
        tid = user.get("tenant_id")
        if tid is not None:
            try:
                row = self._db.get_tenant_by_id(tid)
                if row is not None and row.get("blocked"):
                    raise HTTPException(status_code=403,
                                        detail="Tenant bloqueado.")
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 — best-effort
                pass

        # Auditoría por request (best-effort, nunca rompe la petición).
        try:
            self._db.log_call(
                "auth", "access", entity="user", entity_id=str(user_id),
                payload={"path": request.url.path,
                         "method": request.method},
                status="ok", tenant_id=tid)
        except Exception:  # noqa: BLE001
            pass

        return {"user": _public_user(user), "user_id": user_id,
                "tenant_id": tid, "role": user.get("role"),
                "email": user.get("email"), "claims": claims}

    @property
    def require_auth(self):
        return self._require_auth

    def require_permission(self, perm: str):
        """Dependencia: exige el permiso `perm` (RBAC) sobre el contexto."""
        def dep(ctx: dict = Depends(self._require_auth)):
            if not has_permission(ctx["role"], perm):
                raise HTTPException(status_code=403,
                                    detail=f"Permiso denegado: falta '{perm}'.")
            return ctx
        return dep

    def revoke_token(self, token: str) -> None:
        """Blacklist a token so it cannot be reused after logout."""
        try:
            claims = self.decode(token)
        except JWTError:
            return
        jti = claims.get("jti")
        if not jti:
            return
        exp = claims.get("exp", time.time() + ACCESS_TTL)
        _token_blacklist[jti] = float(exp)
        # Cleanup expired entries
        now = time.time()
        expired = [k for k, v in _token_blacklist.items() if v < now]
        for k in expired:
            _token_blacklist.pop(k, None)

    def is_token_revoked(self, token: str) -> bool:
        """Check if a token has been revoked."""
        try:
            claims = self.decode(token)
            jti = claims.get("jti")
            return jti is not None and jti in _token_blacklist
        except JWTError:
            return True

    def require_tenant_admin(self):
        """Dependencia: exige ser admin del tenant del path param `tenant_id`.

        En el endpoint se declara como
        `ctx=Depends(jwt.require_tenant_admin())` y FastAPI inyecta el
        `tenant_id` del path en el parámetro homónimo de esta dependencia.
        """
        def dep(tenant_id: int, ctx: dict = Depends(self._require_auth)):
            if ctx["tenant_id"] != tenant_id:
                raise HTTPException(status_code=403,
                                    detail="Acceso a otro tenant denegado.")
            if not has_permission(ctx["role"], "users.manage"):
                raise HTTPException(status_code=403,
                                    detail="Requiere rol admin.")
            return ctx
        return dep
