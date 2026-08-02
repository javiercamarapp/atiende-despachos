# -*- coding: utf-8 -*-
"""
config.py — Enterprise configuration validation with Pydantic.

Features:
    - Fail-fast on startup if required env vars are missing
    - Safe defaults for all optional settings
    - Type validation and coercion
    - Environment-specific overrides (dev, staging, production)
    - Secret masking in string representations

Usage:
    from b2b_ai.infrastructure.config import Settings

    # At startup — raises ValidationError if required vars are missing
    settings = Settings.from_env()

    # Access validated config
    print(settings.database.url)
    print(settings.logging.level)
"""
from __future__ import annotations

import os
import sys
from enum import Enum
from typing import Any, Dict, List, Optional, Set

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    from pydantic_settings import BaseSettings
    PYDANTIC_V2 = True
except ImportError:
    try:
        from pydantic import BaseModel, Field, validator, root_validator
        BaseSettings = BaseModel
        PYDANTIC_V2 = False
    except ImportError:
        # Minimal fallback if neither pydantic nor pydantic-settings available
        class BaseModel:
            pass
        BaseSettings = BaseModel
        PYDANTIC_V2 = False
        def Field(*args, **kwargs):
            return kwargs.get("default", None)
        def field_validator(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator
        def model_validator(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# --------------------------------------------------------------------------- #
# Sub-configs
# --------------------------------------------------------------------------- #

class DatabaseSettings(BaseModel):
    """Database connection settings."""
    url: str = Field(
        default="sqlite:///b2b_ai.db",
        description="Database URL (postgresql:// or sqlite:///)",
    )
    pool_min: int = Field(default=2, ge=0, description="Min pool connections")
    pool_max: int = Field(default=10, ge=1, description="Max pool connections")
    pool_overflow: int = Field(default=5, ge=0, description="Overflow connections")
    pool_recycle_seconds: int = Field(default=3600, ge=0, description="Connection recycle interval")
    pool_pre_ping: bool = Field(default=True, description="Health-check connections before use")
    slow_query_threshold_ms: float = Field(default=500.0, ge=0, description="Slow query threshold")
    connect_timeout_seconds: int = Field(default=10, ge=1, description="Connection timeout")


class RedisSettings(BaseModel):
    """Redis connection settings."""
    url: Optional[str] = Field(default=None, description="Redis URL")
    connect_timeout: int = Field(default=5, ge=1)
    socket_timeout: int = Field(default=5, ge=1)


class AuthSettings(BaseModel):
    """Authentication settings."""
    jwt_secret: str = Field(default="", description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60, ge=1)
    api_key: Optional[str] = Field(default=None, description="Static API key for standalone mode")

    if PYDANTIC_V2:
        @field_validator("jwt_secret")
        @classmethod
        def validate_jwt_secret(cls, v: str) -> str:
            env = os.environ.get("B2B_ENV", "development")
            if env != "testing" and (not v or len(v) < 16):
                raise ValueError(
                    "JWT_SECRET must be at least 16 characters. "
                    "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
                )
            return v


class EncryptionSettings(BaseModel):
    """Encryption settings."""
    key: str = Field(default="", description="AES-256 encryption key (base64)")

    if PYDANTIC_V2:
        @field_validator("key")
        @classmethod
        def validate_encryption_key(cls, v: str) -> str:
            env = os.environ.get("B2B_ENV", "development")
            if env != "testing" and (not v or len(v) < 16):
                raise ValueError(
                    "ENCRYPTION_KEY must be at least 16 characters. "
                    "Generate with: openssl rand -hex 24"
                )
            return v


class LoggingSettings(BaseModel):
    """Logging settings."""
    level: LogLevel = Field(default=LogLevel.INFO, description="Global log level")
    format: str = Field(default="json", description="Log format (json or text)")
    enable_file_rotation: bool = Field(default=False)
    log_dir: str = Field(default="logs")
    max_bytes: int = Field(default=52428800, description="Max log file size (50MB)")
    backup_count: int = Field(default=10, description="Rotated log files to keep")
    module_levels: Dict[str, str] = Field(
        default_factory=dict,
        description="Per-module log level overrides",
    )


class CircuitBreakerSettings(BaseModel):
    """Circuit breaker settings."""
    enabled: bool = Field(default=True)
    sat_failure_threshold: int = Field(default=3, ge=1)
    sat_recovery_timeout: float = Field(default=60.0, ge=1)
    facturapi_failure_threshold: int = Field(default=5, ge=1)
    facturapi_recovery_timeout: float = Field(default=30.0, ge=1)
    llm_failure_threshold: int = Field(default=8, ge=1)
    llm_recovery_timeout: float = Field(default=20.0, ge=1)


class ShutdownSettings(BaseModel):
    """Graceful shutdown settings."""
    drain_timeout: float = Field(default=30.0, ge=1, description="Seconds to wait for active requests")
    total_timeout: float = Field(default=60.0, ge=1, description="Total shutdown timeout")


class HealthSettings(BaseModel):
    """Health check settings."""
    check_timeout: float = Field(default=5.0, ge=0.5, description="Health check timeout per component")
    critical_components: List[str] = Field(
        default_factory=lambda: ["database", "redis"],
        description="Components checked in readiness probe",
    )


class MonitoringSettings(BaseModel):
    """Monitoring and metrics settings."""
    prometheus_enabled: bool = Field(default=True)
    alerts_enabled: bool = Field(default=True)
    alert_error_rate_threshold: float = Field(default=0.05, ge=0, le=1)
    alert_latency_threshold_ms: float = Field(default=2000.0, ge=0)


class SATSettings(BaseModel):
    """SAT (Servicio de Administración Tributaria) settings."""
    soap_url: Optional[str] = Field(default=None)
    environment: str = Field(default="cfdi33_pruebas", description="CFDI environment")
    timeout: int = Field(default=30, ge=1)


class FacturapiSettings(BaseModel):
    """Facturapi API settings."""
    api_key: Optional[str] = Field(default=None)
    base_url: str = Field(default="https://www.facturapi.io/v2")
    timeout: int = Field(default=30, ge=1)


class LLMSettings(BaseModel):
    """LLM service settings."""
    provider: str = Field(default="openai", description="LLM provider (openai, anthropic, local)")
    api_key: Optional[str] = Field(default=None)
    model: str = Field(default="gpt-4o-mini")
    max_tokens: int = Field(default=4096, ge=1)
    timeout: int = Field(default=60, ge=1)


# --------------------------------------------------------------------------- #
# Root Settings
# --------------------------------------------------------------------------- #

class Settings(BaseModel):
    """Root application settings — validates all env vars at startup.

    Access via Settings.from_env() for fail-fast validation.
    """
    env: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=False)
    app_name: str = Field(default="b2b-ai-enterprise")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)

    # Sub-configs
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    encryption: EncryptionSettings = Field(default_factory=EncryptionSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    circuit_breaker: CircuitBreakerSettings = Field(default_factory=CircuitBreakerSettings)
    shutdown: ShutdownSettings = Field(default_factory=ShutdownSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    sat: SATSettings = Field(default_factory=SATSettings)
    facturapi: FacturapiSettings = Field(default_factory=FacturapiSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    # Trust proxy
    trust_proxy: Optional[str] = Field(default=None, description="Trusted proxy IPs")

    # Rate limiting
    rate_limit_per_minute: int = Field(default=300, ge=1)

    @classmethod
    def from_env(cls, env_override: Optional[str] = None) -> "Settings":
        """Build Settings from environment variables.

        Environment variables are mapped as:
            B2B_ENV → env
            B2B_DEBUG → debug
            B2B_HOST → host
            B2B_PORT → port
            B2B_DATABASE_URL → database.url
            B2B_PG_POOL_MIN → database.pool_min
            B2B_PG_POOL_MAX → database.pool_max
            B2B_REDIS_URL → redis.url
            B2B_JWT_SECRET → auth.jwt_secret
            B2B_API_KEY → auth.api_key
            B2B_ENCRYPTION_KEY → encryption.key
            B2B_LOG_LEVEL → logging.level
            B2B_LOG_DIR → logging.log_dir
            SAT_SOAP_URL → sat.soap_url
            FACTURAPI_API_KEY → facturapi.api_key
            B2B_LLM_PROVIDER → llm.provider
            B2B_LLM_API_KEY → llm.api_key
            ... etc.
        """
        env = env_override or os.environ.get("B2B_ENV", "development")

        settings_data: Dict[str, Any] = {
            "env": env,
            "debug": os.environ.get("B2B_DEBUG", "false").lower() in ("true", "1", "yes"),
            "host": os.environ.get("B2B_HOST", "0.0.0.0"),
            "port": int(os.environ.get("B2B_PORT", "8000")),
            "workers": int(os.environ.get("B2B_WORKERS", "1")),
            "trust_proxy": os.environ.get("B2B_TRUST_PROXY"),
            "rate_limit_per_minute": int(os.environ.get("B2B_RATE_LIMIT", "300")),
            "database": {
                "url": (
                    os.environ.get("B2B_DATABASE_URL")
                    or os.environ.get("DATABASE_URL")
                    or os.environ.get("B2B_DB_URL")
                    or "sqlite:///b2b_ai.db"
                ),
                "pool_min": int(os.environ.get("B2B_PG_POOL_MIN", "2")),
                "pool_max": int(os.environ.get("B2B_PG_POOL_MAX", "10")),
                "pool_overflow": int(os.environ.get("B2B_PG_POOL_OVERFLOW", "5")),
                "pool_recycle_seconds": int(os.environ.get("B2B_PG_POOL_RECYCLE", "3600")),
                "slow_query_threshold_ms": float(os.environ.get("B2B_SLOW_QUERY_MS", "500")),
                "connect_timeout_seconds": int(os.environ.get("B2B_DB_CONNECT_TIMEOUT", "10")),
            },
            "redis": {
                "url": os.environ.get("REDIS_URL") or os.environ.get("B2B_REDIS_URL"),
            },
            "auth": {
                "jwt_secret": os.environ.get("B2B_JWT_SECRET", ""),
                "jwt_expire_minutes": int(os.environ.get("B2B_JWT_EXPIRE_MINUTES", "60")),
                "api_key": os.environ.get("B2B_API_KEY"),
            },
            "encryption": {
                "key": os.environ.get("B2B_ENCRYPTION_KEY", ""),
            },
            "logging": {
                "level": os.environ.get("B2B_LOG_LEVEL", "INFO"),
                "enable_file_rotation": os.environ.get("B2B_LOG_FILE_ROTATION", "false").lower() in ("true", "1"),
                "log_dir": os.environ.get("B2B_LOG_DIR", "logs"),
                "max_bytes": int(os.environ.get("B2B_LOG_MAX_BYTES", str(50 * 1024 * 1024))),
                "backup_count": int(os.environ.get("B2B_LOG_BACKUP_COUNT", "10")),
            },
            "sat": {
                "soap_url": os.environ.get("SAT_SOAP_URL"),
                "environment": os.environ.get("SAT_ENVIRONMENT", "cfdi33_pruebas"),
            },
            "facturapi": {
                "api_key": os.environ.get("FACTURAPI_API_KEY"),
            },
            "llm": {
                "provider": os.environ.get("B2B_LLM_PROVIDER", "openai"),
                "api_key": os.environ.get("B2B_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
                "model": os.environ.get("B2B_LLM_MODEL", "gpt-4o-mini"),
                "timeout": int(os.environ.get("B2B_LLM_TIMEOUT", "60")),
            },
            "shutdown": {
                "drain_timeout": float(os.environ.get("B2B_DRAIN_TIMEOUT", "30")),
                "total_timeout": float(os.environ.get("B2B_SHUTDOWN_TIMEOUT", "60")),
            },
        }

        return cls(**settings_data)

    def __repr__(self) -> str:
        """Mask secrets in string representation."""
        return (
            f"Settings(env={self.env.value}, host={self.host}, port={self.port}, "
            f"db={'postgresql://***' if 'postgresql' in self.database.url else 'sqlite'}, "
            f"redis={'configured' if self.redis.url else 'none'}, "
            f"auth={'configured' if self.auth.jwt_secret else 'MISSING'})"
        )

    def validate_production_ready(self) -> List[str]:
        """Check if configuration is production-ready.

        Returns list of warnings/errors. Empty list = ready.
        """
        issues = []

        if self.env != Environment.PRODUCTION:
            return issues  # Skip checks for non-production

        if not self.auth.jwt_secret or len(self.auth.jwt_secret) < 16:
            issues.append("CRITICAL: JWT_SECRET is missing or too short")

        if not self.encryption.key or len(self.encryption.key) < 16:
            issues.append("CRITICAL: ENCRYPTION_KEY is missing or too short")

        if "sqlite" in self.database.url.lower():
            issues.append("WARNING: Using SQLite in production — use PostgreSQL")

        if not self.redis.url:
            issues.append("WARNING: No Redis configured — caching/rate-limiting disabled")

        if self.debug:
            issues.append("WARNING: Debug mode is ON in production")

        if self.workers < 2:
            issues.append("WARNING: Single worker in production — consider 2+")

        return issues


# --------------------------------------------------------------------------- #
# Convenience: global settings singleton
# --------------------------------------------------------------------------- #

_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    """Reset the global settings (for testing)."""
    global _settings
    _settings = None
