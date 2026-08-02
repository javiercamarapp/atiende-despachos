# -*- coding: utf-8 -*-
"""
notification_service.py — Multi-channel alert notification service.

Sends alerts over email (SMTP), WhatsApp (HTTP API) and dashboard push,
with a clean Likida-branded HTML template for email.

Rate limiting & dedup:
  - Rate limit: max 1 notification per (category, company) per day.
  - Dedup: identical alert fingerprint not re-sent within the dedup window.

The service is transport-agnostic: SMTP / WhatsApp / dashboard senders are
injected via callables, so tests never touch the network and the class works
both synchronously and with a queueing sender.

This module is ADDITIVE. No existing module is modified.
"""
from __future__ import annotations

import hashlib
import logging
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional

from b2b_ai.features.alertas.models import Alert, AlertSeverity

logger = logging.getLogger(__name__)

# Default category for alerts without an explicit category in metadata.
DEFAULT_CATEGORY = "general"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class NotificationConfig:
    """Configuration for the notification service."""
    max_per_category_per_day: int = 1
    dedup_window_hours: int = 24
    sender_email: str = "alertas@likida.mx"
    brand_name: str = "Likida"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    whatsapp_endpoint: Optional[str] = None
    whatsapp_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Likida email template
# ---------------------------------------------------------------------------

LIKIDA_EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f8;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
        <!-- Header -->
        <tr>
          <td style="background-color:#0b2545;padding:20px 32px;border-radius:12px 12px 0 0;">
            <span style="font-size:22px;font-weight:700;color:#ffffff;">{brand_name}</span>
            <span style="float:right;color:#8bb0d6;font-size:12px;">Inteligencia de Negocio</span>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="background-color:#ffffff;padding:32px;border-left:1px solid #e3e8ee;border-right:1px solid #e3e8ee;">
            <div style="margin-bottom:8px;">
              <span style="display:inline-block;padding:4px 12px;border-radius:999px;font-size:12px;font-weight:600;{severity_badge}">{severity_label}</span>
              <span style="margin-left:8px;color:#6b7280;font-size:13px;">{category}</span>
            </div>
            <h1 style="margin:12px 0 8px;font-size:20px;color:#0b2545;">{title}</h1>
            <p style="margin:0 0 20px;color:#374151;font-size:15px;line-height:1.55;">{message}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc;border:1px solid #e3e8ee;border-radius:8px;">
              <tr><td style="padding:16px 20px;font-size:13px;color:#4b5563;">
                <strong style="color:#0b2545;">Empresa:</strong> {company}<br>
                <strong style="color:#0b2545;">Entidad:</strong> {entity}<br>
                <strong style="color:#0b2545;">Fecha:</strong> {timestamp}
              </td></tr>
            </table>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background-color:#0b2545;padding:16px 32px;border-radius:0 0 12px 12px;">
            <span style="color:#8bb0d6;font-size:12px;">© 2026 {brand_name}. Alertas automáticas de cumplimiento fiscal.</span>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

_SEVERITY_BADGE = {
    AlertSeverity.CRITICAL: "background-color:#fee2e2;color:#b91c1c;",
    AlertSeverity.WARNING: "background-color:#fef3c7;color:#b45309;",
    AlertSeverity.INFO: "background-color:#dbeafe;color:#1d4ed8;",
}
_SEVERITY_LABEL = {
    AlertSeverity.CRITICAL: "Crítico",
    AlertSeverity.WARNING: "Advertencia",
    AlertSeverity.INFO: "Informativo",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AlertNotificationService:
    """Route alerts to email / WhatsApp / dashboard with rate limit + dedup.

    Parameters
    ----------
    config : NotificationConfig
    send_email : callable, optional
        fn(recipient, subject, html, text) → bool. Defaults to SMTP.
    send_whatsapp : callable, optional
        fn(phone, message) → bool. Defaults to HTTP API call.
    push_dashboard : callable, optional
        fn(alert) → bool. Defaults to a no-op returning True.
    now_fn : callable, optional
        Returns current UTC datetime (injectable for tests).
    """

    def __init__(
        self,
        config: Optional[NotificationConfig] = None,
        send_email: Optional[Callable[..., bool]] = None,
        send_whatsapp: Optional[Callable[..., bool]] = None,
        push_dashboard: Optional[Callable[[Alert], bool]] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config or NotificationConfig()
        self._send_email = send_email or self._default_send_email
        self._send_whatsapp = send_whatsapp or self._default_send_whatsapp
        self._push_dashboard = push_dashboard or (lambda a: True)
        self._now_fn = now_fn or (lambda: datetime.now(timezone_utc()))
        # State: {(category, company, fingerprint): last_sent_datetime}
        self._sent: Dict[tuple, datetime] = {}
        self._daily_counts: Dict[tuple, tuple] = {}  # (category, company, day) -> (count, window_start)
        self._notifications: List[dict] = []

    # -- Public API -------------------------------------------------------

    def notify(
        self,
        alert: Alert,
        company: str = "",
        category: Optional[str] = None,
        channels: Optional[List[str]] = None,
        recipients: Optional[Dict[str, List[str]]] = None,
    ) -> List[dict]:
        """Send an alert on the requested channels.

        Returns a list of sent notification records (dicts). Empty list means
        nothing was sent (rate-limited or deduped).
        """
        cat = category or self._category(alert)
        fingerprint = self._fingerprint(alert)
        sent: List[dict] = []

        if not self._allow_send(cat, company, fingerprint):
            return []

        channels = channels or ["email"]
        now = self._now_fn()
        for channel in channels:
            ok, rec = self._dispatch(
                channel, alert, company, cat, recipients or {}, now,
            )
            if ok:
                rec["channel"] = channel
                rec["fingerprint"] = fingerprint
                rec["category"] = cat
                rec["company"] = company
                rec["timestamp"] = now.isoformat()
                sent.append(rec)
                self._notifications.append(rec)

        if sent:
            self._record_send(cat, company, fingerprint, now)
        return sent

    def get_notification_log(self, limit: int = 100) -> List[dict]:
        return list(self._notifications[-limit:])

    # -- Rate limit & dedup -----------------------------------------------

    def _allow_send(self, category: str, company: str, fingerprint: str) -> bool:
        # Dedup
        if (category, company, fingerprint) in self._sent:
            last = self._sent[(category, company, fingerprint)]
            if (self._now_fn() - last) < timedelta(
                    hours=self.config.dedup_window_hours):
                return False
        # Daily rate limit per (category, company)
        day = self._now_fn().strftime("%Y-%m-%d")
        key = (category, company, day)
        count, _ = self._daily_counts.get(key, (0, None))
        if count >= self.config.max_per_category_per_day:
            return False
        return True

    def _record_send(self, category: str, company: str, fingerprint: str,
                     now: datetime) -> None:
        self._sent[(category, company, fingerprint)] = now
        day = now.strftime("%Y-%m-%d")
        key = (category, company, day)
        count, _ = self._daily_counts.get(key, (0, None))
        self._daily_counts[key] = (count + 1, now)

    def can_send_now(self, category: str, company: str) -> bool:
        """Public check: is a new send allowed for this category+company today?"""
        day = self._now_fn().strftime("%Y-%m-%d")
        count, _ = self._daily_counts.get((category, company, day), (0, None))
        return count < self.config.max_per_category_per_day

    # -- Channel dispatch -------------------------------------------------

    def _dispatch(self, channel: str, alert: Alert, company: str, category: str,
                  recipients: Dict[str, List[str]], now: datetime):
        if channel == "email":
            to = (recipients.get("email") or [self.config.sender_email])[0]
            subject = f"[{self.config.brand_name}] {alert.title}"
            html = self.render_email_html(alert, company, category, subject, now)
            text = f"{alert.title}\n\n{alert.message}"
            return self._send_email(to, subject, html, text), {
                "recipient": to, "subject": subject,
            }
        if channel == "whatsapp":
            phone = (recipients.get("whatsapp") or [""])[0]
            if not phone:
                return False, {}
            message = f"*{alert.title}*\n{alert.message}"
            return self._send_whatsapp(phone, message), {"phone": phone}
        if channel == "dashboard":
            return self._push_dashboard(alert), {"alert_id": alert.id}
        logger.warning("Unknown channel %s", channel)
        return False, {}

    # -- Email rendering ----------------------------------------------------

    def render_email_html(self, alert: Alert, company: str, category: str,
                          subject: str, now: Optional[datetime] = None) -> str:
        sev = alert.severity or AlertSeverity.INFO
        return LIKIDA_EMAIL_TEMPLATE.format(
            subject=subject,
            brand_name=self.config.brand_name,
            severity_badge=_SEVERITY_BADGE[sev],
            severity_label=_SEVERITY_LABEL[sev],
            category=category,
            title=alert.title,
            message=alert.message.replace("\n", "<br>"),
            company=company or "—",
            entity=alert.entity_id or "—",
            timestamp=(now or self._now_fn()).strftime("%Y-%m-%d %H:%M"),
        )

    # -- Default senders -----------------------------------------------------

    def _default_send_email(self, to: str, subject: str, html: str,
                            text: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.config.sender_email
            msg["To"] = to
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port,
                              timeout=15) as server:
                if self.config.smtp_use_tls:
                    server.starttls()
                if self.config.smtp_username:
                    server.login(self.config.smtp_username,
                                 self.config.smtp_password or "")
                server.sendmail(self.config.sender_email, [to],
                                msg.as_string())
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("SMTP send failed: %s", exc)
            return False

    def _default_send_whatsapp(self, phone: str, message: str) -> bool:
        if not self.config.whatsapp_endpoint:
            logger.warning("WhatsApp endpoint not configured; skipped.")
            return False
        try:
            import requests
            resp = requests.post(
                self.config.whatsapp_endpoint,
                headers={"Authorization": f"Bearer {self.config.whatsapp_token or ''}"},
                json={"phone": phone, "message": message},
                timeout=15,
            )
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp send failed: %s", exc)
            return False

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _category(alert: Alert) -> str:
        meta = alert.metadata or {}
        return str(meta.get("category") or meta.get("obligation_code")
                   or alert.type.value if alert.type else DEFAULT_CATEGORY)

    @staticmethod
    def _fingerprint(alert: Alert) -> str:
        raw = f"{alert.rule_id}|{alert.type.value if alert.type else ''}|" \
              f"{alert.entity_id}|{alert.message}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def timezone_utc():
    from datetime import timezone
    return timezone.utc
