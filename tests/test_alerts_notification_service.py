# -*- coding: utf-8 -*-
"""Tests for the multi-channel notification service (email/WhatsApp/dashboard)."""
from datetime import datetime, timedelta, timezone

from b2b_ai.features.alertas.notification_service import (
    AlertNotificationService,
    LIKIDA_EMAIL_TEMPLATE,
    NotificationConfig,
)
from b2b_ai.features.alertas.models import Alert, AlertSeverity, AlertType

BASE = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _alert(**kw):
    base = Alert(
        id="a1", rule_id="deadline:DIOT", type=AlertType.DUE_DATE,
        severity=AlertSeverity.CRITICAL, title="Vence DIOT",
        message="La declaración DIOT vence pronto.",
        entity_id="DIOT",
        metadata={"obligation_code": "DIOT"},
    )
    return base.model_copy(update=kw)


class TestEmailRendering:
    def test_template_has_likida_branding(self):
        assert "Likida" in LIKIDA_EMAIL_TEMPLATE
        assert "Inteligencia de Negocio" in LIKIDA_EMAIL_TEMPLATE

    def test_render_email_html_contains_fields(self):
        svc = AlertNotificationService(now_fn=lambda: BASE)
        html = svc.render_email_html(_alert(), "Empresa X", "DIOT", "Asunto", BASE)
        assert "Vence DIOT" in html
        assert "Empresa X" in html
        assert "Crítico" in html
        assert "DIOT" in html

    def test_severity_badge_critical(self):
        svc = AlertNotificationService(now_fn=lambda: BASE)
        html = svc.render_email_html(_alert(), "E", "DIOT", "S", BASE)
        assert "#b91c1c" in html  # critical red


class TestChannels:
    def test_email_sent_with_branding(self):
        captured = []
        svc = AlertNotificationService(
            config=NotificationConfig(),
            send_email=lambda to, subj, html, text: (
                captured.append((to, subj, html)) or True),
            now_fn=lambda: BASE,
        )
        res = svc.notify(
            _alert(), company="Empresa X", category="DIOT",
            channels=["email"], recipients={"email": ["x@likida.mx"]},
        )
        assert len(res) == 1
        assert res[0]["channel"] == "email"
        assert "Likida" in captured[0][2]
        assert captured[0][0] == "x@likida.mx"

    def test_whatsapp_sent(self):
        captured = []
        svc = AlertNotificationService(
            config=NotificationConfig(),
            send_whatsapp=lambda phone, msg: (captured.append((phone, msg)) or True),
            now_fn=lambda: BASE,
        )
        res = svc.notify(
            _alert(), company="E", category="DIOT",
            channels=["whatsapp"], recipients={"whatsapp": ["+5215500000000"]},
        )
        assert len(res) == 1
        assert res[0]["channel"] == "whatsapp"
        assert captured[0][0] == "+5215500000000"

    def test_dashboard_push(self):
        pushed = []
        svc = AlertNotificationService(
            config=NotificationConfig(),
            push_dashboard=lambda a: (pushed.append(a.id) or True),
            now_fn=lambda: BASE,
        )
        res = svc.notify(
            _alert(), company="E", category="DIOT", channels=["dashboard"],
        )
        assert len(res) == 1
        assert res[0]["channel"] == "dashboard"
        assert pushed == ["a1"]

    def test_multi_channel(self):
        svc = AlertNotificationService(
            config=NotificationConfig(),
            send_email=lambda *a, **k: True,
            send_whatsapp=lambda *a, **k: True,
            now_fn=lambda: BASE,
        )
        res = svc.notify(
            _alert(), company="E", category="DIOT",
            channels=["email", "whatsapp"],
            recipients={"email": ["x@likida.mx"], "whatsapp": ["+5215500000000"]},
        )
        channels = {r["channel"] for r in res}
        assert channels == {"email", "whatsapp"}

    def test_unknown_channel_skipped(self):
        svc = AlertNotificationService(now_fn=lambda: BASE)
        assert svc.notify(_alert(), category="DIOT", channels=["sms"]) == []


class TestRateLimit:
    def test_max_one_per_category_per_company_per_day(self):
        cfg = NotificationConfig(max_per_category_per_day=1)
        svc = AlertNotificationService(
            config=cfg, send_email=lambda *a, **k: True, now_fn=lambda: BASE,
        )
        first = svc.notify(_alert(id="a1"), company="E", category="DIOT",
                           channels=["email"], recipients={"email": ["x@likida.mx"]})
        assert len(first) == 1
        # Second in same day, same category+company -> blocked
        second = svc.notify(_alert(id="a2"), company="E", category="DIOT",
                            channels=["email"], recipients={"email": ["x@likida.mx"]})
        assert second == []

    def test_different_category_allowed(self):
        cfg = NotificationConfig(max_per_category_per_day=1)
        svc = AlertNotificationService(
            config=cfg, send_email=lambda *a, **k: True, now_fn=lambda: BASE,
        )
        svc.notify(_alert(id="a1"), company="E", category="DIOT", channels=["email"],
                   recipients={"email": ["x@likida.mx"]})
        # Different category, same company -> allowed
        assert svc.notify(_alert(id="a2"), company="E", category="ANOMALY",
                          channels=["email"], recipients={"email": ["x@likida.mx"]})

    def test_rate_limit_resets_next_day(self):
        cfg = NotificationConfig(max_per_category_per_day=1)
        day2 = BASE + timedelta(days=1)
        now = [BASE]
        svc = AlertNotificationService(
            config=cfg, send_email=lambda *a, **k: True, now_fn=lambda: now[0],
        )
        svc.notify(_alert(id="a1"), company="E", category="DIOT", channels=["email"],
                   recipients={"email": ["x@likida.mx"]})
        assert svc.notify(_alert(id="a2"), company="E", category="DIOT",
                          channels=["email"], recipients={"email": ["x@likida.mx"]}) == []
        # Next day
        now[0] = day2
        assert len(svc.notify(_alert(id="a3"), company="E", category="DIOT",
                              channels=["email"],
                              recipients={"email": ["x@likida.mx"]})) == 1

    def test_can_send_now(self):
        cfg = NotificationConfig(max_per_category_per_day=1)
        svc = AlertNotificationService(config=cfg, send_email=lambda *a, **k: True,
                                       now_fn=lambda: BASE)
        assert svc.can_send_now("DIOT", "E") is True
        svc.notify(_alert(id="a1"), company="E", category="DIOT", channels=["email"],
                   recipients={"email": ["x@likida.mx"]})
        assert svc.can_send_now("DIOT", "E") is False


class TestDedup:
    def test_same_fingerprint_not_resent(self):
        svc = AlertNotificationService(
            config=NotificationConfig(max_per_category_per_day=10),
            send_email=lambda *a, **k: True, now_fn=lambda: BASE,
        )
        recipients = {"email": ["x@likida.mx"]}
        first = svc.notify(_alert(), company="E", category="DIOT", channels=["email"],
                           recipients=recipients)
        second = svc.notify(_alert(), company="E", category="DIOT", channels=["email"],
                            recipients=recipients)
        assert len(first) == 1
        assert second == []  # deduped

    def test_different_message_not_deduped(self):
        svc = AlertNotificationService(
            config=NotificationConfig(max_per_category_per_day=10),
            send_email=lambda *a, **k: True, now_fn=lambda: BASE,
        )
        recipients = {"email": ["x@likida.mx"]}
        svc.notify(_alert(message="msg A"), company="E", category="DIOT",
                   channels=["email"], recipients=recipients)
        second = svc.notify(_alert(message="msg B"), company="E", category="DIOT",
                            channels=["email"], recipients=recipients)
        assert len(second) == 1


class TestLog:
    def test_notification_log(self):
        svc = AlertNotificationService(
            config=NotificationConfig(), send_email=lambda *a, **k: True,
            now_fn=lambda: BASE,
        )
        svc.notify(_alert(), company="E", category="DIOT", channels=["email"],
                   recipients={"email": ["x@likida.mx"]})
        log = svc.get_notification_log()
        assert len(log) == 1
        assert log[0]["category"] == "DIOT"
        assert log[0]["company"] == "E"
        assert "timestamp" in log[0]

    def test_default_category_fallback(self):
        svc = AlertNotificationService(send_email=lambda *a, **k: True,
                                       now_fn=lambda: BASE)
        # Alert with no obligation_code in metadata -> falls back to alert type
        a = _alert(metadata={})
        assert svc._category(a) == "due_date"
