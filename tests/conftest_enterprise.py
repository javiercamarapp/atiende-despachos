# -*- coding: utf-8 -*-
"""
conftest_enterprise.py — Enterprise-grade test fixtures.

Provides:
  - DB session fixture (SQLite in-memory, isolated per test)
  - Authenticated test client (with API key and JWT)
  - Tenant context (scoped to a specific tenant)
  - Mock Redis for rate limiter tests
  - Test data builders for CFDIs, nóminas, facturas
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional
from unittest.mock import MagicMock

import pytest

# Ensure test env
os.environ.setdefault("B2B_ENV", "test")
os.environ.setdefault("B2B_JWT_SECRET", "test-jwt-secret-safe-for-ci-only-32ch")
os.environ.setdefault("B2B_RATE_LIMIT", "off")  # Disable rate limiting in tests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db_session(tmp_path) -> Generator:
    """Fresh SQLite database per test, fully migrated."""
    from b2b_ai.db.db import Database
    db_path = str(tmp_path / "test_enterprise.db")
    db = Database(db_path)
    yield db
    try:
        db.close()
    except Exception:
        pass


@pytest.fixture
def pg_db_session():
    """PostgreSQL database session for integration tests.

    Skips if B2B_TEST_PG_URL is not set.
    """
    pg_url = os.environ.get("B2B_TEST_PG_URL")
    if not pg_url:
        pytest.skip("B2B_TEST_PG_URL not set — skipping PG integration test")
    from b2b_ai.db.db import Database
    db = Database(pg_url)
    yield db
    try:
        db.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tenant fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tenant_id() -> int:
    """Default tenant ID for tests."""
    return 1


@pytest.fixture
def tenant_context(tenant_id) -> Dict[str, Any]:
    """Simulated tenant context (as returned by auth)."""
    return {
        "tenant_id": tenant_id,
        "name": "Test Despacho",
        "rfc": "TDE220101AB1",
    }


@pytest.fixture
def second_tenant_context() -> Dict[str, Any]:
    """Second tenant for cross-tenant isolation tests."""
    return {
        "tenant_id": 99,
        "name": "Other Despacho",
        "rfc": "ODE220101CD2",
    }


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api_key() -> str:
    """Test API key."""
    return "test-api-key-enterprise-12345678"


@pytest.fixture
def service_api_key() -> str:
    """Service-level API key (no tenant restriction)."""
    return "test-service-key-enterprise-87654321"


@pytest.fixture
def auth_headers(api_key) -> Dict[str, str]:
    """Headers with API key for authenticated requests."""
    return {"X-API-Key": api_key}


@pytest.fixture
def service_headers(service_api_key) -> Dict[str, str]:
    """Headers with service API key."""
    return {"X-API-Key": service_api_key}


@pytest.fixture
def idempotency_headers(auth_headers) -> Dict[str, str]:
    """Headers with API key + idempotency key."""
    return {
        **auth_headers,
        "Idempotency-Key": secrets.token_hex(16),
    }


@pytest.fixture
def jwt_token():
    """Generate a valid JWT token for testing."""
    from b2b_ai.auth.middleware import encode_token
    return encode_token(
        {"type": "access", "sub": "1", "tenant_id": 1,
         "role": "admin", "email": "test@test.com",
         "jti": secrets.token_urlsafe(16)},
        ttl_seconds=3600,
    )


@pytest.fixture
def jwt_headers(jwt_token) -> Dict[str, str]:
    """Headers with JWT Bearer token."""
    return {"Authorization": f"Bearer {jwt_token}"}


# ---------------------------------------------------------------------------
# Test client fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def test_client(db_session, api_key, service_api_key):
    """FastAPI test client with authenticated API key.

    Creates the app with the test database and configures the API keys.
    """
    from fastapi.testclient import TestClient

    os.environ["B2B_API_KEY"] = service_api_key

    # Create a test-specific API key in the DB
    try:
        db_session.create_tenant("Test Despacho", rfc="TDE220101AB1")
        db_session.create_api_key(1, api_key, name="test-key")
    except Exception:
        pass  # Table might not exist yet

    from b2b_ai.api.app import create_app
    app = create_app(db=db_session)
    client = TestClient(app)
    yield client


@pytest.fixture
def authenticated_client(test_client, auth_headers):
    """Test client pre-configured with auth headers."""
    test_client.headers.update(auth_headers)
    return test_client


@pytest.fixture
def admin_client(test_client, service_headers):
    """Test client with service-level (admin) API key."""
    test_client.headers.update(service_headers)
    return test_client


# ---------------------------------------------------------------------------
# Rate limiter mock
# ---------------------------------------------------------------------------
class MockRateLimitBackend:
    """In-memory rate limiter backend for testing."""

    def __init__(self):
        self._usage: Dict[str, int] = {}
        self.limit_reached = False

    def check_and_consume(self, key: str, limit: int, window: float):
        count = self._usage.get(key, 0) + 1
        self._usage[key] = count
        remaining = max(0, limit - count)
        reset = time.time() + window
        if remaining == 0:
            self.limit_reached = True
        return remaining, reset

    def get_usage(self, key: str, window: float) -> int:
        return self._usage.get(key, 0)

    def reset(self, key: str = None):
        if key:
            self._usage.pop(key, None)
        else:
            self._usage.clear()
        self.limit_reached = False

    @property
    def size(self):
        return len(self._usage)


@pytest.fixture
def mock_rate_backend():
    """Mock rate limiter backend."""
    return MockRateLimitBackend()


# ---------------------------------------------------------------------------
# Idempotency mock
# ---------------------------------------------------------------------------
class MockIdempotencyStore:
    """In-memory idempotency store for testing."""

    def __init__(self):
        self._store: Dict[str, Dict] = {}

    def get(self, key, body_hash):
        entry = self._store.get(key)
        if entry and entry["body_hash"] == body_hash:
            return entry["status"], entry["headers"], entry["body"]
        return None

    def is_conflict(self, key, body_hash):
        entry = self._store.get(key)
        return entry is not None and entry["body_hash"] != body_hash

    def set(self, key, body_hash, status, headers, body):
        self._store[key] = {
            "body_hash": body_hash, "status": status,
            "headers": headers, "body": body,
        }

    @property
    def size(self):
        return len(self._store)


@pytest.fixture
def mock_idempotency_store():
    """Mock idempotency store."""
    return MockIdempotencyStore()
