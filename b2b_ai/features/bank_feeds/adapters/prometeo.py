# -*- coding: utf-8 -*-
"""
prometeo.py — Adapter de la Prometeo Banking API (cuentas bancarias reales MX).

Conecta Likida AI con cuentas bancarias reales en México a través de la API
agregadora de Prometeo. A diferencia de los adapters OFX/CNBV/mock, este
adapter hace llamadas HTTP reales a la API de Prometeo:

    Flujo:
      POST /login/                       -> obtiene session key
      GET  /account/                     -> lista cuentas del usuario
      GET  /account/{n}/movement/        -> movimientos de una cuenta

    Auth dual:
      - X-API-Key  (header)  : llave de la aplicación (per-tenant)
      - session key (query)  : llave de sesión devuelta por POST /login/

Entornos:
      - Producción : https://banking.prometeoapi.net/
      - Sandbox    : https://banking.sandbox.prometeoapi.com/  (provider "test")

Modelo de movimiento de Prometeo:
      id, credit, debit, reference, date (DD/MM/YYYY), detail (6 campos)

El adapter normaliza cada movimiento a RawMovement (misma forma intermedia que
los adapters OFX/mock), con date ya convertida a YYYY-MM-DD.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from b2b_ai.features.bank_feeds.adapters.base import BaseBankAdapter, slice_movements
from b2b_ai.features.bank_feeds.models import BankProvider
from b2b_ai.features.bank_feeds.processors.ofx import RawMovement

# ---------------------------------------------------------------------------
# Excepciones específicas de Prometeo
# ---------------------------------------------------------------------------


class PrometeoError(RuntimeError):
    """Error genérico de la API de Prometeo."""


class PrometeoAuthError(PrometeoError):
    """Error de autenticación (401 / 403)."""


class PrometeoRateLimitError(PrometeoError):
    """Se alcanzó el rate limit de la API (429)."""


# ---------------------------------------------------------------------------
# Helpers de formato
# ---------------------------------------------------------------------------

_DATE_DDMYYY_RE = re.compile(r"^(\d{2})[/.\-](\d{2})[/.\-](\d{4})")
_DATE_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_prometeo_date(value: Optional[str]) -> str:
    """Convierte 'DD/MM/YYYY' (formato Prometeo) a 'YYYY-MM-DD'.

    También tolera fechas ya en ISO 'YYYY-MM-DD' y devuelve '' ante vacíos.
    """
    if not value:
        return ""
    s = str(value).strip()
    m = _DATE_ISO_RE.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_DDMYYY_RE.match(s)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
    return s


def _to_amount(value: Any) -> str:
    if value is None:
        return "0"
    return str(value).replace(",", "").strip()


def _detail_field(detail: Any, key: str) -> str:
    if isinstance(detail, dict):
        return str(detail.get(key, "") or "")
    return ""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PrometeoAdapter(BaseBankAdapter):
    """Adaptador para conectar cuentas bancarias reales vía Prometeo API."""

    provider = BankProvider.PROMETEO

    PROD_BASE_URL = "https://banking.prometeoapi.net/"
    SANDBOX_BASE_URL = "https://banking.sandbox.prometeoapi.com/"
    API_KEY_HEADER = "X-API-Key"

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_session=None,
        base_url: Optional[str] = None,
        sandbox: bool = False,
    ):
        default_url = self.SANDBOX_BASE_URL if sandbox else self.PROD_BASE_URL
        super().__init__(http_session=http_session, base_url=base_url or default_url)
        self.api_key = api_key
        self.session_key: Optional[str] = None
        self.sandbox = bool(sandbox)

    # ------------------------------------------------------------------
    # Transporte / errores
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers[self.API_KEY_HEADER] = self.api_key
        return headers

    def _params(self, **extra: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = dict(extra)
        if self.session_key:
            params["session"] = self.session_key
        return params

    def _check_status(self, resp) -> None:
        status = getattr(resp, "status_code", None)
        if status is None:
            raise PrometeoError(f"Respuesta sin status_code: {resp!r}")
        if status in (401, 403):
            raise PrometeoAuthError(f"Prometeo auth falló (HTTP {status})")
        if status == 429:
            raise PrometeoRateLimitError("Prometeo rate limit alcanzado (HTTP 429)")
        if status >= 400:
            raise PrometeoError(f"Prometeo HTTP {status}: {getattr(resp, 'text', '')}")

    def _post(self, url: str, json: Optional[dict] = None) -> Any:
        if self.http is None:
            raise PrometeoError(
                "PrometeoAdapter requiere http_session para llamadas reales"
            )
        resp = self.http.post(url, headers=self._headers(), json=json)
        self._check_status(resp)
        return resp

    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        if self.http is None:
            raise PrometeoError(
                "PrometeoAdapter requiere http_session para llamadas reales"
            )
        merged = self._params(**(params or {}))
        resp = self.http.get(url, headers=self._headers(), params=merged)
        self._check_status(resp)
        return resp

    # ------------------------------------------------------------------
    # Autenticación dual
    # ------------------------------------------------------------------
    def login(
        self,
        provider: str = "test",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """POST /login/ -> guarda y devuelve la session key de Prometeo."""
        payload: Dict[str, Any] = {"provider": provider}
        if username:
            payload["username"] = username
        if password:
            payload["password"] = password
        resp = self._post(f"{self.base_url}login/", json=payload)
        data = resp.json()
        if isinstance(data, dict):
            self.session_key = data.get("key") or data.get("session_key") or data.get("session")
        if not self.session_key:
            raise PrometeoAuthError("Prometeo /login/ no devolvió session key")
        return self.session_key

    def _ensure_login(self, account: dict, provider: str) -> None:
        self.api_key = self.api_key or account.get("api_key")
        if not self.session_key:
            self.login(
                provider=provider,
                username=account.get("username"),
                password=account.get("password"),
            )

    # ------------------------------------------------------------------
    # Cuentas
    # ------------------------------------------------------------------
    def fetch_accounts(self, account: dict, provider: str = "test") -> List[dict]:
        """Login + GET /account/ -> lista de cuentas normalizadas del usuario."""
        self._ensure_login(account, provider)
        resp = self._get(f"{self.base_url}account/")
        data = resp.json()
        if isinstance(data, dict):
            accounts = data.get("accounts", data.get("data", []))
        else:
            accounts = data or []
        normalized: List[dict] = []
        for acct in accounts or []:
            if not isinstance(acct, dict):
                continue
            acct_id = str(acct.get("id") or acct.get("number") or "")
            normalized.append(
                {
                    "id": acct_id,
                    "account_id": acct_id,
                    "provider": self.provider.value,
                    "bank": str(acct.get("bank", "") or ""),
                    "bank_name": str(acct.get("bank_name", "") or acct.get("bank", "") or ""),
                    "clabe": str(acct.get("clabe", "") or ""),
                    "account_number": str(acct.get("number", "") or acct.get("account_number", "") or ""),
                    "currency": str(acct.get("currency", "") or "MXN"),
                    "label": str(acct.get("name", "") or acct.get("alias", "") or ""),
                    "raw": acct,
                }
            )
        return normalized

    # ------------------------------------------------------------------
    # Movimientos
    # ------------------------------------------------------------------
    def fetch_movements(
        self,
        account_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawMovement]:
        """GET /account/{n}/movement/ -> movimientos normalizados a RawMovement."""
        url = f"{self.base_url}account/{account_id}/movement/"
        params: Dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        resp = self._get(url, params=params)
        data = resp.json()
        if isinstance(data, dict):
            movements = data.get("movements", data.get("data", []))
        else:
            movements = data or []
        raw = [
            self._movement_to_raw(m, account_id)
            for m in (movements or [])
            if isinstance(m, dict)
        ]
        return slice_movements(raw, limit)

    def _movement_to_raw(self, mv: dict, account_id: str) -> RawMovement:
        credit = mv.get("credit")
        debit = mv.get("debit")
        has_credit = credit not in (None, "", 0)
        amount = credit if has_credit else debit
        type_raw = "CREDIT" if has_credit else "DEBIT"
        detail = mv.get("detail") or {}
        description = (
            _detail_field(detail, "description")
            or _detail_field(detail, "memo")
            or str(mv.get("reference", "") or "")
        )
        return RawMovement(
            external_id=str(mv.get("id") or ""),
            date=parse_prometeo_date(mv.get("date")),
            amount=_to_amount(amount),
            description=description,
            memo=description,
            type_raw=type_raw,
            bank_name=self.provider.value,
            extra={
                "account_id": str(account_id),
                "reference": str(mv.get("reference", "") or ""),
                "credit": credit,
                "debit": debit,
                "detail": detail,
                "provider": self.provider.value,
            },
        )

    # ------------------------------------------------------------------
    # Interfaz base (fetch_transactions)
    # ------------------------------------------------------------------
    def fetch_transactions(
        self,
        account: dict,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawMovement]:
        """Implementa la interfaz de BaseBankAdapter.

        Hace login (si hace falta) y trae los movimientos de la cuenta Prometeo
        indicada en ``account["account_id"]`` (o ``account["id"]``).
        """
        provider = account.get("provider") or "test"
        self._ensure_login(account, provider)
        account_id = (
            account.get("account_id")
            or account.get("prometeo_account_id")
            or account.get("id")
        )
        if not account_id:
            raise ValueError(
                "account debe incluir 'account_id' (número de cuenta Prometeo)"
            )
        return self.fetch_movements(account_id, from_date, to_date, limit)


__all__ = [
    "PrometeoAdapter",
    "PrometeoError",
    "PrometeoAuthError",
    "PrometeoRateLimitError",
    "parse_prometeo_date",
]
