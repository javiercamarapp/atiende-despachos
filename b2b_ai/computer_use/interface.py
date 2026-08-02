# -*- coding: utf-8 -*-
"""
interface.py — Abstract interface for Computer Use drivers.

Defines ComputerUseDriver, the canonical ABC that every ERP automation driver
(mock, Playwright, native desktop) must implement. Also defines the
DriverResultStatus enum used to classify operation outcomes uniformly.

Design:
    - All operations return a DriverResult (dict-like) with at minimum:
      {status: DriverResultStatus, ok: bool, message: str}
    - Sync and async variants exist: the ABC defines the sync contract;
      async-capable drivers expose awaitable versions.
    - No silent fallbacks: if a real driver fails, the status reflects it.

The factory (factory.py) and config (config.py) are siblings of this module.
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Operation result statuses
# ---------------------------------------------------------------------------
class DriverResultStatus(str, enum.Enum):
    """Canonical outcome states for any Computer Use driver operation."""

    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    BLOCKED_BY_MFA = "blocked_by_mfa"
    BLOCKED_BY_CAPTCHA = "blocked_by_captcha"
    SELECTOR_NOT_FOUND = "selector_not_found"
    SESSION_EXPIRED = "session_expired"
    VERIFICATION_FAILED = "verification_failed"
    CONFIGURATION_ERROR = "configuration_error"


@dataclass
class DriverResult:
    """Uniform result wrapper for all driver operations.

    Attributes:
        status: Canonical status enum.
        ok: Convenience bool (True only for SUCCESS).
        message: Human-readable explanation.
        data: Arbitrary payload (invoices, grid, screenshots, etc.).
    """

    status: DriverResultStatus
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == DriverResultStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the dict format legacy callers expect."""
        d: Dict[str, Any] = {
            "ok": self.ok,
            "status": self.status.value,
            "message": self.message,
        }
        d.update(self.data)
        return d

    # Convenience constructors ------------------------------------------------

    @classmethod
    def success(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.SUCCESS, message=message, data=data)

    @classmethod
    def failed(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.FAILED, message=message, data=data)

    @classmethod
    def needs_human_review(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.NEEDS_HUMAN_REVIEW, message=message, data=data)

    @classmethod
    def blocked_by_mfa(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.BLOCKED_BY_MFA, message=message, data=data)

    @classmethod
    def blocked_by_captcha(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.BLOCKED_BY_CAPTCHA, message=message, data=data)

    @classmethod
    def selector_not_found(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.SELECTOR_NOT_FOUND, message=message, data=data)

    @classmethod
    def session_expired(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.SESSION_EXPIRED, message=message, data=data)

    @classmethod
    def verification_failed(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.VERIFICATION_FAILED, message=message, data=data)

    @classmethod
    def configuration_error(cls, message: str = "", **data: Any) -> "DriverResult":
        return cls(status=DriverResultStatus.CONFIGURATION_ERROR, message=message, data=data)


# ---------------------------------------------------------------------------
# Abstract Computer Use Driver
# ---------------------------------------------------------------------------
class ComputerUseDriver(ABC):
    """Canonical interface for all ERP computer-use automation drivers.

    Every concrete driver (CONTPAQi Playwright, Aspel Playwright, Mock,
    disabled stub) must implement every abstract method here. Methods return
    DriverResult for uniform status classification.

    Lifecycle:
        1. connect()          — establish transport (launch browser, connect to session)
        2. login(credentials)  — authenticate with the ERP
        3. verify_authenticated() — confirm session is alive
        4. navigate_menu(...) — go to a specific module
        5. extract_invoices() / capture_invoice_grid() / register_invoice() / ...
        6. logout()           — clean session
        7. close()            — release all resources
    """

    # -- identity ---------------------------------------------------------------
    @property
    @abstractmethod
    def provider(self) -> str:
        """Return the provider name: 'contpaqi', 'aspel', etc."""
        ...

    @property
    @abstractmethod
    def mode(self) -> str:
        """Return the driver mode: 'mock', 'playwright', 'disabled'."""
        ...

    # -- lifecycle --------------------------------------------------------------
    @abstractmethod
    def connect(self) -> DriverResult:
        """Establish connection (launch browser / open session)."""
        ...

    @abstractmethod
    def login(self, credentials: Dict[str, Any]) -> DriverResult:
        """Authenticate with the ERP using provided credentials."""
        ...

    @abstractmethod
    def verify_authenticated(self) -> DriverResult:
        """Verify the current session is alive and authenticated."""
        ...

    @abstractmethod
    def logout(self) -> DriverResult:
        """Cleanly end the ERP session."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release all resources (browser, event loop, etc.)."""
        ...

    # -- navigation & extraction ------------------------------------------------
    @abstractmethod
    def navigate_menu(self, module: str) -> DriverResult:
        """Navigate to a specific ERP module (facturas, catalogos, etc.)."""
        ...

    @abstractmethod
    def extract_invoices(self) -> DriverResult:
        """Extract invoice data from the current view."""
        ...

    @abstractmethod
    def capture_invoice_grid(self) -> DriverResult:
        """Capture the invoice grid as structured data."""
        ...

    # -- write operations -------------------------------------------------------
    @abstractmethod
    def register_invoice(self, data: Dict[str, Any]) -> DriverResult:
        """Register a CFDI/invoice in the ERP."""
        ...

    @abstractmethod
    def register_poliza(self, data: Dict[str, Any]) -> DriverResult:
        """Register a journal entry (póliza) in the ERP."""
        ...

    @abstractmethod
    def verify_invoice_registered(self, folio_fiscal: str) -> DriverResult:
        """Verify that an invoice was successfully registered."""
        ...

    @abstractmethod
    def verify_poliza_registered(self, poliza_id: str) -> DriverResult:
        """Verify that a póliza was successfully registered."""
        ...

    # -- resilience -------------------------------------------------------------
    @abstractmethod
    def health(self) -> DriverResult:
        """Return health status of the driver and its dependencies."""
        ...

    @abstractmethod
    def recover_from_error(self) -> DriverResult:
        """Attempt automatic recovery from an error state."""
        ...
