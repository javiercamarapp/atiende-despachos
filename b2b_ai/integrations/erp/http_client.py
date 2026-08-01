# -*- coding: utf-8 -*-
"""
http_client.py — Shared HTTP client with retry, timeout, and backoff.

Used by all cloud ERP adapters (QuickBooks, Xero, CONTPAQi Web,
Aspel Cloud, Factor D, Taxko, FacturaDirecta) for production-ready
API communication.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_CONNECT_TIMEOUT = 10  # seconds
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 1.0  # seconds
DEFAULT_BACKOFF_MAX = 30.0  # seconds


class ERPAPIError(Exception):
    """Raised when an ERP API call fails after all retries."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        response_body: Any = None,
        attempts: int = 1,
    ):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.attempts = attempts
        super().__init__(self.message)


class ERPAuthError(ERPAPIError):
    """Raised specifically for authentication failures (401/403)."""
    pass


class ERPConnectionError(ERPAPIError):
    """Raised when the ERP endpoint is unreachable."""
    pass


def _should_retry(exc: Exception, attempt: int, max_attempts: int) -> bool:
    """Determine if we should retry the request."""
    if attempt >= max_attempts:
        return False
    # Retry on connection errors and server errors (5xx), not on client errors (4xx)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    if isinstance(exc, ERPAPIError):
        # Don't retry auth errors
        if isinstance(exc, ERPAuthError):
            return False
        # Retry on server errors (5xx)
        if exc.status_code >= 500:
            return True
    return False


def make_request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    backoff_max: float = DEFAULT_BACKOFF_MAX,
) -> httpx.Response:
    """Make an HTTP request with retry logic and exponential backoff.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        url: Full URL to call.
        headers: Request headers (e.g., Authorization, API key).
        json_body: JSON body for POST/PUT/PATCH requests.
        params: Query parameters.
        timeout: Total request timeout in seconds.
        connect_timeout: Connection timeout in seconds.
        retry_attempts: Maximum number of retry attempts.
        backoff_base: Base delay for exponential backoff.
        backoff_max: Maximum backoff delay.

    Returns:
        httpx.Response object.

    Raises:
        ERPAuthError: On 401/403 responses (no retry).
        ERPAPIError: On other HTTP errors or exhausted retries.
        ERPConnectionError: When the endpoint is unreachable after retries.
    """
    headers = headers or {}
    last_exc: Optional[Exception] = None

    for attempt in range(1, retry_attempts + 1):
        try:
            logger.debug(
                f"HTTP {method.upper()} {url} (attempt {attempt}/{retry_attempts})"
            )
            with httpx.Client(
                timeout=httpx.Timeout(timeout=timeout, connect=connect_timeout),
                follow_redirects=True,
            ) as client:
                response = client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                )

                # Auth errors — raise immediately, no retry
                if response.status_code in (401, 403):
                    raise ERPAuthError(
                        f"Authentication failed for {url}: HTTP {response.status_code}",
                        status_code=response.status_code,
                        response_body=_safe_json(response),
                        attempts=attempt,
                    )

                # Client errors (4xx) — raise without retry
                if 400 <= response.status_code < 500:
                    raise ERPAPIError(
                        f"Client error for {url}: HTTP {response.status_code}",
                        status_code=response.status_code,
                        response_body=_safe_json(response),
                        attempts=attempt,
                    )

                # Server errors (5xx) — will trigger retry
                if response.status_code >= 500:
                    raise ERPAPIError(
                        f"Server error for {url}: HTTP {response.status_code}",
                        status_code=response.status_code,
                        response_body=_safe_json(response),
                        attempts=attempt,
                    )

                return response

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            last_exc = ERPConnectionError(
                f"Connection error for {url}: {exc}",
                attempts=attempt,
            )
            logger.warning(
                f"HTTP {method.upper()} {url} connection failed (attempt {attempt}/{retry_attempts}): {exc}"
            )
        except ERPAuthError:
            raise  # Don't retry auth errors
        except ERPAPIError as exc:
            if not _should_retry(exc, attempt, retry_attempts):
                raise
            last_exc = exc
            logger.warning(
                f"HTTP {method.upper()} {url} error (attempt {attempt}/{retry_attempts}): {exc}"
            )

        # Exponential backoff with jitter
        if attempt < retry_attempts:
            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
            logger.debug(f"Retrying in {delay:.1f}s...")
            time.sleep(delay)

    # Exhausted all retries
    if last_exc:
        raise last_exc
    raise ERPAPIError(
        f"All {retry_attempts} attempts failed for {url}",
        attempts=retry_attempts,
    )


def _safe_json(response: httpx.Response) -> Any:
    """Safely parse JSON from response, returning None on failure."""
    try:
        return response.json()
    except Exception:
        return response.text[:500] if response.text else None
