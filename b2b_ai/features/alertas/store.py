# -*- coding: utf-8 -*-
"""
store.py — In-memory Alert Store with deduplication, history, and lifecycle.

Features:
  - Deduplication: same alert_id within the dedup window → suppressed
  - History tracking: every action (create, acknowledge, dismiss) is logged
  - Acknowledge / dismiss workflow
  - Filtering by severity, type, status, tenant_id
  - Statistics aggregation
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from b2b_ai.features.alertas.models import (
    Alert,
    AlertConfig,
    AlertHistory,
    AlertSeverity,
    AlertStatus,
    AlertType,
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AlertStore:
    """Thread-safe in-memory store for alerts.

    Parameters
    ----------
    config : AlertConfig, optional
        Engine configuration (dedup window, rate limit, etc.)
    """

    def __init__(self, config: Optional[AlertConfig] = None):
        self.config = config or AlertConfig()
        self._lock = threading.Lock()
        self._alerts: Dict[str, Alert] = {}            # alert_id → Alert
        self._history: Dict[str, List[AlertHistory]] = defaultdict(list)  # alert_id → [History]
        self._rules: Dict[str, dict] = {}               # rule_id → AlertRule dict
        self._rate_timestamps: List[float] = []         # timestamps for rate limiting
        self._notifications: List[dict] = []            # notification log

    # ------------------------------------------------------------------
    # Alert CRUD
    # ------------------------------------------------------------------

    def save_alerts(self, alerts: List[Alert]) -> List[Alert]:
        """Save a batch of alerts, applying dedup and rate limiting.

        Returns only newly created alerts (not suppressed by dedup).
        """
        new_alerts: List[Alert] = []
        now = time.monotonic()

        with self._lock:
            for alert in alerts:
                aid = alert.id
                if not aid:
                    continue

                # Deduplication
                if aid in self._alerts:
                    existing = self._alerts[aid]
                    if existing.status == AlertStatus.ACTIVE:
                        # Within dedup window → suppress
                        if self._within_dedup_window(existing):
                            continue
                    # If acknowledged or dismissed, allow re-creation
                    # but assign a new ID
                    aid = f"{aid}_v{int(now)}"
                    alert.id = aid

                # Rate limiting
                if not self._check_rate_limit():
                    continue

                # Set defaults
                if not alert.created_at:
                    alert.created_at = _now_iso()
                if not alert.status:
                    alert.status = AlertStatus.ACTIVE

                self._alerts[aid] = alert
                self._record_history(aid, "created", details={
                    "rule_id": alert.rule_id,
                    "severity": alert.severity.value if alert.severity else None,
                    "type": alert.type.value if alert.type else None,
                })
                new_alerts.append(alert)

        return new_alerts

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Retrieve a single alert by ID."""
        with self._lock:
            return self._alerts.get(alert_id)

    def list_alerts(
        self,
        tenant_id: Optional[int] = None,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        status: Optional[AlertStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Alert]:
        """List alerts with optional filtering."""
        with self._lock:
            results = list(self._alerts.values())

        # Filter
        if tenant_id is not None:
            results = [a for a in results if a.tenant_id == tenant_id]
        if severity is not None:
            results = [a for a in results if a.severity == severity]
        if alert_type is not None:
            results = [a for a in results if a.type == alert_type]
        if status is not None:
            results = [a for a in results if a.status == status]

        # Sort by created_at descending (newest first)
        results.sort(key=lambda a: a.created_at or "", reverse=True)

        # Paginate
        return results[offset:offset + limit]

    def count_alerts(
        self,
        tenant_id: Optional[int] = None,
        severity: Optional[AlertSeverity] = None,
        status: Optional[AlertStatus] = None,
    ) -> int:
        """Count alerts with optional filtering."""
        with self._lock:
            results = list(self._alerts.values())
        if tenant_id is not None:
            results = [a for a in results if a.tenant_id == tenant_id]
        if severity is not None:
            results = [a for a in results if a.severity == severity]
        if status is not None:
            results = [a for a in results if a.status == status]
        return len(results)

    def acknowledge_alert(
        self,
        alert_id: str,
        user: Optional[str] = None,
    ) -> Optional[Alert]:
        """Acknowledge an alert."""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                return None
            if alert.status != AlertStatus.ACTIVE:
                return alert  # already in terminal state
            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_at = _now_iso()
            alert.acknowledged_by = user
            self._record_history(alert_id, "acknowledged", user=user)
            return alert

    def dismiss_alert(
        self,
        alert_id: str,
        user: Optional[str] = None,
    ) -> Optional[Alert]:
        """Dismiss an alert."""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                return None
            if alert.status in (AlertStatus.DISMISSED, AlertStatus.RESOLVED):
                return alert
            alert.status = AlertStatus.DISMISSED
            alert.dismissed_at = _now_iso()
            alert.dismissed_by = user
            self._record_history(alert_id, "dismissed", user=user)
            return alert

    def delete_alert(self, alert_id: str) -> bool:
        """Permanently delete an alert and its history."""
        with self._lock:
            if alert_id in self._alerts:
                del self._alerts[alert_id]
                self._history.pop(alert_id, None)
                return True
            return False

    def clear_all(self) -> int:
        """Delete all alerts and history. Returns count deleted."""
        with self._lock:
            count = len(self._alerts)
            self._alerts.clear()
            self._history.clear()
            self._rate_timestamps.clear()
            return count

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self, alert_id: str) -> List[AlertHistory]:
        """Get the full history for an alert."""
        with self._lock:
            return list(self._history.get(alert_id, []))

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def save_rule(self, rule_id: str, rule_data: dict) -> dict:
        """Save a rule definition."""
        with self._lock:
            self._rules[rule_id] = rule_data
            return rule_data

    def get_rule(self, rule_id: str) -> Optional[dict]:
        """Get a rule by ID."""
        with self._lock:
            return self._rules.get(rule_id)

    def list_rules(
        self,
        tenant_id: Optional[int] = None,
        enabled_only: bool = False,
    ) -> List[dict]:
        """List all rules with optional filtering."""
        with self._lock:
            results = list(self._rules.values())
        if tenant_id is not None:
            results = [
                r for r in results
                if r.get("tenant_id") is None or r.get("tenant_id") == tenant_id
            ]
        if enabled_only:
            results = [r for r in results if r.get("enabled", True)]
        return results

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule."""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                return True
            return False

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(
        self,
        tenant_id: Optional[int] = None,
    ) -> dict:
        """Aggregate statistics about alerts."""
        with self._lock:
            alerts = list(self._alerts.values())

        if tenant_id is not None:
            alerts = [a for a in alerts if a.tenant_id == tenant_id]

        total = len(alerts)
        by_severity = defaultdict(int)
        by_type = defaultdict(int)
        by_status = defaultdict(int)

        for a in alerts:
            by_severity[a.severity.value] += 1
            by_type[a.type.value] += 1
            by_status[a.status.value] += 1

        return {
            "total": total,
            "active": by_status.get("active", 0),
            "acknowledged": by_status.get("acknowledged", 0),
            "dismissed": by_status.get("dismissed", 0),
            "by_severity": dict(by_severity),
            "by_type": dict(by_type),
            "by_status": dict(by_status),
        }

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def log_notification(self, notification: dict) -> None:
        """Log a notification event."""
        with self._lock:
            notification.setdefault("timestamp", _now_iso())
            self._notifications.append(notification)

    def list_notifications(self, limit: int = 100) -> List[dict]:
        """List recent notifications."""
        with self._lock:
            return list(self._notifications[-limit:])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _within_dedup_window(self, alert: Alert) -> bool:
        """Check if an existing alert is still within the dedup window."""
        if not alert.created_at:
            return False
        try:
            from datetime import datetime
            created = datetime.fromisoformat(alert.created_at.replace("Z", "+00:00"))
            now_str = _now_iso()
            now = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
            diff = (now - created).total_seconds()
            return diff < self.config.dedup_window_seconds
        except (ValueError, TypeError):
            return False

    def _check_rate_limit(self) -> bool:
        """Check and update the rate limit counter."""
        now = time.monotonic()
        window = 3600  # 1 hour

        # Clean old timestamps
        cutoff = now - window
        self._rate_timestamps = [t for t in self._rate_timestamps if t > cutoff]

        if len(self._rate_timestamps) >= self.config.max_alerts_per_hour:
            return False

        self._rate_timestamps.append(now)
        return True

    def _record_history(
        self,
        alert_id: str,
        action: str,
        user: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Record a history entry. Must be called with lock held."""
        entry = AlertHistory(
            alert_id=alert_id,
            action=action,
            user=user,
            timestamp=_now_iso(),
            details=details or {},
        )
        self._history[alert_id].append(entry)
