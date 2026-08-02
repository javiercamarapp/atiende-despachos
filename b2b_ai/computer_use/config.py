# -*- coding: utf-8 -*-
"""
config.py — Configuration for Computer Use drivers.

Reads environment variables, validates them, and exposes a frozen ComputerUseConfig
dataclass. Validation rules:

    - In playwright mode, URLs and credentials are REQUIRED.
    - In production (B2B_ENV=production), mode=mock is REJECTED.
    - No silent fallback from real to mock — ever.
    - example.com URLs are rejected in real (playwright) mode.
    - allow_writes defaults to False (read-only safe by default).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Known providers
# ---------------------------------------------------------------------------
VALID_PROVIDERS = frozenset({"contpaqi", "aspel"})
VALID_MODES = frozenset({"mock", "playwright", "disabled"})


class ComputerUseConfigurationError(Exception):
    """Raised when ComputerUseConfig encounters invalid configuration."""


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ComputerUseConfig:
    """Immutable configuration for a Computer Use driver instance.

    Read from environment variables or constructed explicitly.
    Call ``validate()`` after construction to enforce invariants.
    """

    mode: str = "disabled"
    provider: str = "contpaqi"
    headless: bool = True
    timeout_seconds: int = 30
    max_retries: int = 3
    screenshot_dir: str = "/tmp/b2b_screenshots"
    allow_writes: bool = False

    # Provider-specific credentials
    contpaqi_url: str = ""
    contpaqi_username: str = ""
    contpaqi_password: str = ""
    aspel_url: str = ""
    aspel_username: str = ""
    aspel_password: str = ""

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "ComputerUseConfig":
        """Build config from environment variables.

        Env vars:
            B2B_COMPUTER_USE_MODE          (default: disabled)
            B2B_COMPUTER_USE_PROVIDER      (default: contpaqi)
            B2B_COMPUTER_USE_HEADLESS      (default: true)
            B2B_COMPUTER_USE_TIMEOUT_SECONDS (default: 30)
            B2B_COMPUTER_USE_MAX_RETRIES   (default: 3)
            B2B_COMPUTER_USE_SCREENSHOT_DIR (default: /tmp/b2b_screenshots)
            B2B_COMPUTER_USE_ALLOW_WRITES  (default: false)
            CONTPAQI_URL, CONTPAQI_USERNAME, CONTPAQI_PASSWORD
            ASPEL_URL, ASPEL_USERNAME, ASPEL_PASSWORD
        """
        headless_raw = os.environ.get("B2B_COMPUTER_USE_HEADLESS", "true").lower()
        allow_writes_raw = os.environ.get("B2B_COMPUTER_USE_ALLOW_WRITES", "false").lower()

        cfg = cls(
            mode=os.environ.get("B2B_COMPUTER_USE_MODE", "disabled").strip().lower(),
            provider=os.environ.get("B2B_COMPUTER_USE_PROVIDER", "contpaqi").strip().lower(),
            headless=headless_raw in ("true", "1", "yes"),
            timeout_seconds=int(os.environ.get("B2B_COMPUTER_USE_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.environ.get("B2B_COMPUTER_USE_MAX_RETRIES", "3")),
            screenshot_dir=os.environ.get("B2B_COMPUTER_USE_SCREENSHOT_DIR", "/tmp/b2b_screenshots"),
            allow_writes=allow_writes_raw in ("true", "1", "yes"),
            contpaqi_url=os.environ.get("CONTPAQI_URL", "").strip(),
            contpaqi_username=os.environ.get("CONTPAQI_USERNAME", "").strip(),
            contpaqi_password=os.environ.get("CONTPAQI_PASSWORD", "").strip(),
            aspel_url=os.environ.get("ASPEL_URL", "").strip(),
            aspel_username=os.environ.get("ASPEL_USERNAME", "").strip(),
            aspel_password=os.environ.get("ASPEL_PASSWORD", "").strip(),
        )
        cfg.validate()
        return cfg

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Enforce all configuration invariants.

        Raises:
            ComputerUseConfigurationError on any violation.
        """
        # 1. Provider must be known
        if self.provider not in VALID_PROVIDERS:
            raise ComputerUseConfigurationError(
                f"Unknown provider '{self.provider}'. Valid: {sorted(VALID_PROVIDERS)}"
            )

        # 2. Mode must be known
        if self.mode not in VALID_MODES:
            raise ComputerUseConfigurationError(
                f"Unknown mode '{self.mode}'. Valid: {sorted(VALID_MODES)}"
            )

        # 3. Production rejects mock
        env = os.environ.get("B2B_ENV", "development").strip().lower()
        if env in ("production", "prod") and self.mode == "mock":
            raise ComputerUseConfigurationError(
                "mode=mock is not allowed in production. "
                "Set B2B_COMPUTER_USE_MODE=playwright or disabled."
            )

        # 4. Playwright mode requires credentials for the active provider
        if self.mode == "playwright":
            url, username, password = self._provider_credentials()
            if not url:
                raise ComputerUseConfigurationError(
                    f"Playwright mode requires a URL for provider '{self.provider}'. "
                    f"Set {self.provider.upper()}_URL."
                )
            if not username:
                raise ComputerUseConfigurationError(
                    f"Playwright mode requires a username for provider '{self.provider}'. "
                    f"Set {self.provider.upper()}_USERNAME."
                )
            if not password:
                raise ComputerUseConfigurationError(
                    f"Playwright mode requires a password for provider '{self.provider}'. "
                    f"Set {self.provider.upper()}_PASSWORD."
                )
            # 5. example.com URLs are not valid in real mode
            if "example.com" in url.lower():
                raise ComputerUseConfigurationError(
                    f"URL '{url}' is a placeholder (example.com). "
                    f"Set a real {self.provider.upper()}_URL for playwright mode."
                )

    def _provider_credentials(self) -> tuple[str, str, str]:
        """Return (url, username, password) for the active provider."""
        if self.provider == "contpaqi":
            return self.contpaqi_url, self.contpaqi_username, self.contpaqi_password
        elif self.provider == "aspel":
            return self.aspel_url, self.aspel_username, self.aspel_password
        return "", "", ""

    @property
    def credentials(self) -> dict:
        """Return credentials dict for the active provider."""
        url, username, password = self._provider_credentials()
        return {"url": url, "username": username, "password": password}

    @property
    def is_disabled(self) -> bool:
        return self.mode == "disabled"

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    @property
    def is_playwright(self) -> bool:
        return self.mode == "playwright"

    def __repr__(self) -> str:
        """Mask password in repr."""
        url, username, _ = self._provider_credentials()
        return (
            f"ComputerUseConfig(mode={self.mode!r}, provider={self.provider!r}, "
            f"headless={self.headless}, url={url!r}, username={username!r})"
        )
