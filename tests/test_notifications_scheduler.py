# -*- coding: utf-8 -*-
"""Tests del scheduler de notificaciones: cola, rate limiting, reintentos."""
from datetime import datetime, timedelta

from b2b_ai.notifications.scheduler import (RateLimiter, NotificationScheduler,
                                            Message)
from b2b_ai.notifications.whatsapp import WhatsAppBusiness, MockWhatsApp


# ---- RateLimiter --------------------------------------------------------- #
def test_rate_limiter_tokens_burst():
    rl = RateLimiter(rate=1.0, burst=5)
    allowed = sum(1 for _ in range(5) if rl.acquire(blocking=False))
    assert allowed == 5
    # el sexto no tiene token sin esperar
    assert rl.acquire(blocking=False) is False


def test_rate_limiter_bloquea_hasta_refill():
    rl = RateLimiter(rate=1000.0, burst=1)
    assert rl.acquire(blocking=False) is True
    # muy poco tiempo pasa → aún sin token
    assert rl.acquire(blocking=False) is False
    assert rl.acquire(blocking=True) is True  # espera el refill


# ---- Scheduler: envío con mock ------------------------------------------- #
def test_scheduler_envia_y_vacia_cola():
    wa = MockWhatsApp()
    sched = NotificationScheduler(wa=wa, max_retries=1)
    sched.enqueue("+5215512345678", "Mensaje 1", template="exception")
    sched.enqueue("+5215512345679", "Mensaje 2")
    assert sched.pending() == 2
    sent = sched.process_once()
    assert sent == 2
    assert sched.pending() == 0
    assert len(wa.messages) == 2
    assert sched.stats()["sent"] == 2


def test_scheduler_rate_limit_respetado():
    # burst 1 → solo procesa 1 mensaje por tick si los demás no tienen token
    wa = MockWhatsApp()
    rl = RateLimiter(rate=0.0, burst=1)
    sched = NotificationScheduler(wa=wa, rate_limiter=rl)
    for i in range(3):
        sched.enqueue("+5215512345678", f"M{i}")
    sent = sched.process_once()
    assert sent == 1
    assert sched.pending() == 2  # 1 enviado, 2 re-programados sin token
    assert len(wa.messages) == 1


def test_scheduler_retry_luego_exito():
    """Primer intento falla y el reintento (mismo tick, backoff 0) tiene éxito."""
    class Flaky:
        backend = "flaky"
        def __init__(self):
            self.calls = 0

        def send_message(self, phone, text, template=None):
            self.calls += 1
            if self.calls == 1:
                return {"status": "error", "message": "transient"}
            return {"status": "sent", "id": "x", "to": phone, "text": text,
                    "template": template}

    flaky = Flaky()
    sched = NotificationScheduler(wa=flaky, max_retries=2,
                                  retry_backoff_seconds=0.0)
    sched.enqueue("+5215512345678", "Hola")
    # con backoff 0, el reintento vence de inmediato y se agota en un tick:
    # 1er intento falla → se re-encola → 2º intento (mismo tick) tiene éxito.
    sched.process_once()
    assert sched.sent_count == 1
    assert flaky.calls == 2
    assert sched.pending() == 0


def test_scheduler_agota_reintentos_marca_failed():
    class AlwaysFail:
        backend = "always-fail"

        def send_message(self, phone, text, template=None):
            return {"status": "error", "message": "nope"}

    sched = NotificationScheduler(wa=AlwaysFail(), max_retries=2,
                                  retry_backoff_seconds=0.0)
    sched.enqueue("+5215512345678", "Hola")
    # 1 inicial + 2 reintentos = 3 intentos fallidos → marca failed.
    sched.process_once()
    assert sched.failed_count == 1
    assert sched.pending() == 0


def test_scheduler_reintento_con_backoff_se_difiere():
    """Con backoff > 0 el reintento NO vence en el mismo tick (queda en cola)."""
    class AlwaysFail:
        backend = "always-fail"

        def send_message(self, phone, text, template=None):
            return {"status": "error", "message": "nope"}

    sched = NotificationScheduler(wa=AlwaysFail(), max_retries=5,
                                  retry_backoff_seconds=60.0)
    sched.enqueue("+5215512345678", "Hola")
    sched.process_once()
    # primer intento falló → re-encolado con run_at futuro → sigue pendiente
    assert sched.pending() == 1
    assert sched.failed_count == 0
    # un segundo tick no lo re-envía (aún no vence)
    sched.process_once()
    assert sched.failed_count == 0


# ---- programación / envío diferido --------------------------------------- #
def test_scheduler_envio_diferido():
    wa = MockWhatsApp()
    sched = NotificationScheduler(wa=wa)
    sched.enqueue("+5215512345678", "Futuro",
                  run_at=datetime.now() + timedelta(days=1))
    assert sched.pending() == 1
    sent = sched.process_once()
    assert sent == 0          # no vence aún → no se envía
    assert len(wa.messages) == 0
    assert sched.pending() == 1


def test_scheduler_enqueue_daily_summary():
    wa = MockWhatsApp()
    sched = NotificationScheduler(wa=wa)
    sched.enqueue_daily_summary({
        "phone": "+5215512345678", "nombre": "Ana", "fecha": "2026-07-31",
        "facturas": "5", "monto_total": "1,000", "pendientes": "1",
        "anomalias": "0"})
    assert sched.pending() == 1
    sched.process_once()
    assert len(wa.messages) == 1
    assert "2026-07-31" in wa.messages[0]["text"]


def test_message_due():
    assert Message("+1", "x").due is True
    future = Message("+1", "x", run_at=datetime.now() + timedelta(hours=1))
    assert future.due is False
