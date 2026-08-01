# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Intelligent Alerts Engine.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These are request/response schemas — the engine and store populate them
from rule evaluation and data analysis.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AlertSeverity(str, Enum):
    """Severity level of an alert."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Category of alert."""
    THRESHOLD = "threshold"
    ANOMALY = "anomaly"
    DUE_DATE = "due_date"
    VOLUME = "volume"
    RECONCILIATION = "reconciliation"
    CUSTOM = "custom"


class AlertStatus(str, Enum):
    """Lifecycle status of an alert."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class RuleCondition(str, Enum):
    """Supported comparison operators for threshold rules."""
    GT = "gt"           # greater than
    GTE = "gte"         # greater than or equal
    LT = "lt"           # less than
    LTE = "lte"         # less than or equal
    EQ = "eq"           # equal
    NEQ = "neq"         # not equal
    BETWEEN = "between" # value between two bounds


# ---------------------------------------------------------------------------
# Core schemas
# ---------------------------------------------------------------------------

class AlertRule(BaseModel):
    """A configurable rule that the engine evaluates against incoming data.

    Each rule defines:
    - A type (threshold, anomaly, due_date, volume, reconciliation)
    - A condition to evaluate
    - Parameters specific to the rule type
    - Severity and message template
    """
    id: Optional[str] = Field(default=None, description="Unique rule ID")
    name: str = Field(..., description="Human-readable rule name")
    type: AlertType = Field(..., description="Rule type category")
    enabled: bool = Field(default=True, description="Whether this rule is active")
    condition: RuleCondition = Field(
        default=RuleCondition.GT,
        description="Comparison operator for threshold rules",
    )
    threshold_value: Optional[float] = Field(
        default=None,
        description="Threshold value for threshold rules (e.g. 50000 for $50K invoices)",
    )
    threshold_value_max: Optional[float] = Field(
        default=None,
        description="Upper bound for BETWEEN condition",
    )
    multiplier: Optional[float] = Field(
        default=None,
        description="Multiplier for anomaly rules (e.g. 2.0 for >2x average)",
    )
    days_before_due: Optional[int] = Field(
        default=None,
        description="Days before due date to trigger due_date alerts",
    )
    volume_limit: Optional[int] = Field(
        default=None,
        description="Maximum count for volume alerts",
    )
    field_path: Optional[str] = Field(
        default=None,
        description="Dot-separated path to the value to evaluate (e.g. 'total', 'amount')",
    )
    severity: AlertSeverity = Field(
        default=AlertSeverity.WARNING,
        description="Default severity when this rule fires",
    )
    message_template: str = Field(
        default="",
        description="Alert message template with {value}, {threshold}, {entity} placeholders",
    )
    tenant_id: Optional[int] = Field(
        default=None,
        description="Tenant scope (None = global rule)",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra parameters for custom rules",
    )
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")


class Alert(BaseModel):
    """A single alert instance produced by the engine."""
    id: Optional[str] = Field(default=None, description="Unique alert ID")
    rule_id: Optional[str] = Field(default=None, description="ID of the rule that fired")
    rule_name: str = Field(default="", description="Name of the rule that fired")
    type: AlertType = Field(default=AlertType.CUSTOM, description="Alert type")
    severity: AlertSeverity = Field(
        default=AlertSeverity.WARNING,
        description="Alert severity level",
    )
    status: AlertStatus = Field(
        default=AlertStatus.ACTIVE,
        description="Current status of the alert",
    )
    title: str = Field(default="", description="Short alert title")
    message: str = Field(default="", description="Detailed alert message")
    entity_type: Optional[str] = Field(
        default=None,
        description="Entity type (invoice, reconciliation, etc.)",
    )
    entity_id: Optional[str] = Field(
        default=None,
        description="Entity identifier (invoice ID, etc.)",
    )
    tenant_id: Optional[int] = Field(
        default=None,
        description="Tenant that owns this alert",
    )
    value: Optional[float] = Field(
        default=None,
        description="The actual value that triggered the alert",
    )
    threshold: Optional[float] = Field(
        default=None,
        description="The threshold that was exceeded / matched",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extra context about the alert",
    )
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    acknowledged_at: Optional[str] = Field(
        default=None,
        description="When the alert was acknowledged",
    )
    dismissed_at: Optional[str] = Field(
        default=None,
        description="When the alert was dismissed",
    )
    acknowledged_by: Optional[str] = Field(
        default=None,
        description="User who acknowledged the alert",
    )
    dismissed_by: Optional[str] = Field(
        default=None,
        description="User who dismissed the alert",
    )


class AlertConfig(BaseModel):
    """Global configuration for the alerts engine."""
    enabled: bool = Field(default=True, description="Master switch for alert generation")
    max_alerts_per_hour: int = Field(
        default=100,
        description="Maximum alerts generated per hour (rate limit)",
    )
    dedup_window_seconds: int = Field(
        default=3600,
        description="Deduplication window in seconds",
    )
    auto_dismiss_after_hours: Optional[int] = Field(
        default=None,
        description="Auto-dismiss alerts after N hours (None = never)",
    )
    notify_channels: List[str] = Field(
        default_factory=lambda: ["log"],
        description="Notification channels: log, email, webhook, slack",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="Webhook URL for alert notifications",
    )
    tenant_id: Optional[int] = Field(
        default=None,
        description="Tenant-specific config (None = global default)",
    )


class AlertHistory(BaseModel):
    """Historical record of an alert event for audit trail."""
    alert_id: str = Field(..., description="Alert ID")
    action: str = Field(..., description="Action taken: created, acknowledged, dismissed, resolved")
    user: Optional[str] = Field(default=None, description="User who performed the action")
    timestamp: str = Field(..., description="ISO timestamp of the action")
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context about the action",
    )


class NotificationPreference(BaseModel):
    """Per-tenant notification preferences."""
    tenant_id: int = Field(..., description="Tenant ID")
    channels: List[str] = Field(
        default_factory=lambda: ["log"],
        description="Enabled notification channels for this tenant",
    )
    min_severity: AlertSeverity = Field(
        default=AlertSeverity.WARNING,
        description="Minimum severity to send notifications for",
    )
    email_addresses: List[str] = Field(
        default_factory=list,
        description="Email addresses for email notifications",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="Tenant-specific webhook URL",
    )
    slack_channel: Optional[str] = Field(
        default=None,
        description="Slack channel for notifications",
    )
    quiet_hours_start: Optional[int] = Field(
        default=None,
        description="Hour to start quiet period (0-23)",
    )
    quiet_hours_end: Optional[int] = Field(
        default=None,
        description="Hour to end quiet period (0-23)",
    )
