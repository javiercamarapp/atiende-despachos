# -*- coding: utf-8 -*-
"""Tests del adapter Prometeo (bank_feeds) — API real via Prometeo Banking.

IMPORTANTE: estos tests usan un http_session falso (sin red). Se verifican:
normalización de cuentas, parsing de fechas DD/MM/YYYY, auth dual
(X-API-Key header + session key query), urls sandbox vs producción y manejo
de errores de Prometeo.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.bank_feeds.adapters.base import BaseBankAdapter
from b2b_ai.features.bank_feeds.adapters import (
    get_adapter,
    PrometeoAdapter,
)
from b2b_ai.features.bank_feeds.adapters.prometeo import (
    PrometeoAuthError,
    PrometeoError,
    PrometeoRateLimitError,
    parse_prometeo_date,
)
from b2b_ai.features.bank_feeds.models import BankProvider
from b2b_ai.features.bank_feeds.processors.ofx import RawMovement


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload


class FakeHttpSession:
    """Graba llamadas y responde según la URL."""

    def __init__(self, responses=None):
        # responses: dict key->callable(record) -> FakeResponse
        self.responses = responses or {}
        self.calls = []

    def _serve(self, record):
        key = record["url"].split("?")[0]
        handler = self.responses.get(key) or self.responses.get(
            key.replace("account/", "account/{id}/")
        )
        if handler is None:
            return FakeResponse({}, status_code=404)
        return handler(record)

    def post(self, url, headers=None, json=None):
        record = {"method": "POST", "url": url, "headers": headers, "json": json}
        self.calls.append(record)
        return self._serve(record)

    def get(self, url, headers=None, params=None):
        record = {"method": "GET", "url": url, "headers": headers, "params": params}
        self.calls.append(record)
        return self._serve(record)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account(api_key="test-key"):
    return {
        "api_key": api_key,
        "username": "usuario",
        "password": "clave",
        "provider": "test",
        "account_id": "42",
    }


def _session_with_login(login_key="sk_live_abc"):
    def login_handler(rec):
        return FakeResponse({"key": login_key, "session_key": login_key})

    def accounts_handler(rec):
        return FakeResponse(
            {
                "accounts": [
                    {
                        "id": 42,
                        "number": "012345678901234567",
                        "bank": "BBVA",
                        "bank_name": "BBVA México",
                        "clabe": "012345678901234567",
                        "currency": "MXN",
                        "name": "Operativa",
                    }
                ]
            }
        )

    def movements_handler(rec):
        return FakeResponse(
            {
                "movements": [
                    {
                        "id": "mv-1",
                        "credit": "1500.00",
                        "debit": None,
                        "reference": "SPEI-1001",
                        "date": "15/01/2025",
                        "detail": {
                            "description": "Transferencia recibida",
                            "counterparty": "XAXX010101000",
                        },
                    },
                    {
                        "id": "mv-2",
                        "credit": None,
                        "debit": "520.50",
                        "reference": "SPEI-1002",
                        "date": "16/01/2025",
                        "detail": {"description": "Pago proveedor"},
                    },
                ]
            }
        )

    return FakeHttpSession(
        {
            f"{PrometeoAdapter.PROD_BASE_URL}login/": login_handler,
            f"{PrometeoAdapter.PROD_BASE_URL}account/": accounts_handler,
            f"{PrometeoAdapter.PROD_BASE_URL}account/42/movement/": movements_handler,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPrometeoAdapter:
    def test_prometeo_adapter_inherits_base(self):
        assert issubclass(PrometeoAdapter, BaseBankAdapter)
        assert PrometeoAdapter.provider == BankProvider.PROMETEO

    def test_fetch_accounts_returns_normalized(self):
        session = _session_with_login()
        adapter = PrometeoAdapter(api_key="test-key", http_session=session)
        accounts = adapter.fetch_accounts(_account())
        assert len(accounts) == 1
        acct = accounts[0]
        assert acct["account_id"] == "42"
        assert acct["provider"] == "PROMETEO"
        assert acct["bank_name"] == "BBVA México"
        assert acct["clabe"] == "012345678901234567"
        assert acct["currency"] == "MXN"

    def test_fetch_movements_parses_ddmmyyyy(self):
        session = _session_with_login()
        adapter = PrometeoAdapter(api_key="test-key", http_session=session)
        moves = adapter.fetch_movements("42")
        assert len(moves) == 2
        assert all(isinstance(m, RawMovement) for m in moves)
        assert moves[0].date == "2025-01-15"      # DD/MM/YYYY -> ISO
        assert moves[1].date == "2025-01-16"
        assert moves[0].type_raw == "CREDIT"
        assert moves[0].amount == "1500.00"
        assert moves[1].type_raw == "DEBIT"
        assert moves[1].amount == "520.50"
        assert moves[0].extra["reference"] == "SPEI-1001"

    def test_auth_dual_layer(self):
        session = _session_with_login()
        adapter = PrometeoAdapter(api_key="secret-key", http_session=session)
        adapter.fetch_accounts(_account())
        login_call = session.calls[0]
        accounts_call = session.calls[1]
        # Layer 1: X-API-Key en headers
        assert login_call["headers"]["X-API-Key"] == "secret-key"
        assert login_call["json"]["provider"] == "test"
        # Layer 2: session key como query param en llamadas autenticadas
        assert accounts_call["params"]["session"] == "sk_live_abc"
        assert accounts_call["headers"]["X-API-Key"] == "secret-key"

    def test_sandbox_vs_production_urls(self):
        prod = PrometeoAdapter(api_key="k", http_session=FakeHttpSession())
        assert prod.base_url == PrometeoAdapter.PROD_BASE_URL
        assert prod.sandbox is False

        sandbox = PrometeoAdapter(api_key="k", http_session=FakeHttpSession(), sandbox=True)
        assert sandbox.base_url == PrometeoAdapter.SANDBOX_BASE_URL
        assert sandbox.sandbox is True

        # base_url explícito tiene prioridad
        custom = PrometeoAdapter(
            api_key="k", http_session=FakeHttpSession(), base_url="https://proxy.local/"
        )
        assert custom.base_url == "https://proxy.local/"

    def test_parse_prometeo_date(self):
        assert parse_prometeo_date("15/01/2025") == "2025-01-15"
        assert parse_prometeo_date("15-01-2025") == "2025-01-15"
        assert parse_prometeo_date("2025-01-15") == "2025-01-15"
        assert parse_prometeo_date(None) == ""
        assert parse_prometeo_date("") == ""

    def test_fetch_transactions_uses_base_interface(self):
        session = _session_with_login()
        adapter = PrometeoAdapter(api_key="test-key", http_session=session)
        moves = adapter.fetch_transactions(_account())
        assert len(moves) == 2
        assert moves[0].date == "2025-01-15"

    def test_auth_error_401(self):
        def bad_login(rec):
            return FakeResponse({"error": "unauthorized"}, status_code=401)

        session = FakeHttpSession({f"{PrometeoAdapter.PROD_BASE_URL}login/": bad_login})
        adapter = PrometeoAdapter(api_key="k", http_session=session)
        with pytest.raises(PrometeoAuthError):
            adapter.fetch_accounts(_account())

    def test_rate_limit_429(self):
        def limited(rec):
            return FakeResponse({"error": "slow down"}, status_code=429)

        session = FakeHttpSession({f"{PrometeoAdapter.PROD_BASE_URL}login/": limited})
        adapter = PrometeoAdapter(api_key="k", http_session=session)
        with pytest.raises(PrometeoRateLimitError):
            adapter.fetch_accounts(_account())

    def test_no_http_session_raises(self):
        adapter = PrometeoAdapter(api_key="k", http_session=None)
        with pytest.raises(PrometeoError):
            adapter.fetch_accounts(_account())

    def test_get_adapter_returns_prometeo(self):
        assert isinstance(get_adapter("PROMETEO"), PrometeoAdapter)
        assert isinstance(get_adapter(BankProvider.PROMETEO), PrometeoAdapter)

    def test_login_missing_session_key_raises(self):
        def no_key(rec):
            return FakeResponse({})

        session = FakeHttpSession({f"{PrometeoAdapter.PROD_BASE_URL}login/": no_key})
        adapter = PrometeoAdapter(api_key="k", http_session=session)
        with pytest.raises(PrometeoAuthError):
            adapter.login(provider="test")
