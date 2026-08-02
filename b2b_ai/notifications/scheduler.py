# -*- coding: utf-8 -*-
"""
scheduler.py — Cola y programación de envíos de notificaciones (WhatsApp).

Componentes:
  * RateLimiter           — token bucket: limita el ritmo de envíos para
                            respetar los límites de la WhatsApp Business API
                            (por defecto ~80 msg/seg y rachas controladas).
  * Message               — un mensaje en cola, con reintentos y `run_at`
                            (envío programado/diferido).
  * NotificationScheduler — cola + lógica de envío: procesa los mensajes
                            pendientes, aplica rate limiting, reintenta con
                            backoff exponencial y mueve a "failed" lo que
                            agota sus reintentos.

Uso típico (síncrono, apto para cron / worker):
    sched = NotificationScheduler(wa=WhatsAppBusiness(...))
    sched.enqueue("+5215512345678", "Hola", template="exception")
    n_sent = sched.process_once()   # envía los mensajes vencidos

Los tests usan el RateLimiter con parámetros altos (sin sleep real) o un
transport mock, de modo que no hay red ni esperas.
"""
from __future__ import annotations

import heapq
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


class RateLimiter:
    """Token bucket sencillo y síncrono.

    Permite `rate` operaciones por segundo con un burst máximo de `burst`.
    `acquire()` bloquea (o devuelve False si `blocking=False` y no hay token).
    """

    def __init__(self, rate: float = 80.0, burst: int = 100):
        self.rate = max(float(rate), 1e-6)
        self.burst = max(int(burst), 1)
        self._tokens = float(self.burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.burst,
                           self._tokens + (now - self._last) * self.rate)
        self._last = now

    def acquire(self, blocking: bool = True) -> bool:
        """Toma un token. Con blocking=False devuelve False si no hay token."""
        with self._lock:
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            if not blocking:
                return False
            deficit = (1 - self._tokens) / self.rate
        time.sleep(deficit)
        return True


@dataclass
class Message:
    """Un mensaje en cola para envío por WhatsApp."""

    phone: str
    text: str
    template: Optional[str] = None
    priority: int = 0                      # menor = más prioritario
    run_at: Optional[datetime] = None      # envío diferido/programado
    max_retries: int = 3
    retries: int = 0
    status: str = "queued"                 # queued | sent | failed
    created_at: float = field(default_factory=time.time)

    @property
    def due(self) -> bool:
        """True si ya es hora de enviarse (o no tiene programación)."""
        if self.run_at is None:
            return True
        return time.time() >= self.run_at.timestamp()


class NotificationScheduler:
    """Cola de mensajes con rate limiting, reintentos y programación."""

    def __init__(self, wa=None, rate_limiter: Optional[RateLimiter] = None,
                 max_retries: int = 3, retry_backoff_seconds: float = 1.0):
        from b2b_ai.notifications.whatsapp import WhatsAppBusiness
        self.wa = wa or WhatsAppBusiness()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_retries = int(max_retries)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self._queue: List[Message] = []
        self._lock = threading.Lock()
        # Estadística acumulada de la cola.
        self.sent_count = 0
        self.failed_count = 0

    # ------------------------------------------------------------------ #
    # Cola
    # ------------------------------------------------------------------ #
    def enqueue(self, phone: str, text: str, template: Optional[str] = None,
                run_at: Optional[datetime] = None,
                priority: int = 0, max_retries: Optional[int] = None) -> Message:
        """Mete un mensaje en la cola. Devuelve el Message (con su id en heap)."""
        msg = Message(phone=phone, text=text, template=template,
                      run_at=run_at, priority=priority,
                      max_retries=self.max_retries if max_retries is None
                      else int(max_retries))
        with self._lock:
            heapq.heappush(self._queue,
                           (msg.priority, msg.created_at, msg))
        return msg

    def enqueue_daily_summary(self, summary_data: dict,
                              run_at: Optional[datetime] = None) -> Message:
        """Programa un resumen diario (template daily_summary)."""
        from b2b_ai.notifications.whatsapp import _recipient_from
        from b2b_ai.notifications.templates import render
        phone = _recipient_from(summary_data)
        ctx = {
            "nombre": summary_data.get("nombre", "Cliente"),
            "fecha": summary_data.get("fecha", ""),
            "facturas": summary_data.get("facturas", "0"),
            "monto_total": summary_data.get("monto_total", "0"),
            "pendientes": summary_data.get("pendientes", "0"),
            "anomalias": summary_data.get("anomalias", "0"),
        }
        _, body = render("daily_summary", ctx)
        return self.enqueue(phone, body, template="daily_summary",
                            run_at=run_at)

    def pending(self) -> int:
        """Número de mensajes en cola (pendientes de enviar)."""
        with self._lock:
            return len(self._queue)

    # ------------------------------------------------------------------ #
    # Procesamiento
    # ------------------------------------------------------------------ #
    def _pop_due(self) -> Optional[Message]:
        """Saca el mensaje más prioritario que ya esté vencido (o None)."""
        with self._lock:
            while self._queue:
                _, _, msg = heapq.heappop(self._queue)
                if msg.due:
                    return msg
                # El más prioritario no vence aún → nada más vence.
                heapq.heappush(self._queue, (msg.priority, msg.created_at,
                                             msg))
                return None
        return None

    def _retry_later(self, msg: Message) -> None:
        """Re-programa un mensaje tras un fallo con backoff exponencial."""
        delay = self.retry_backoff_seconds * (2 ** msg.retries)
        from datetime import timedelta
        msg.run_at = datetime.now() + timedelta(seconds=delay)
        with self._lock:
            heapq.heappush(self._queue, (msg.priority, msg.created_at, msg))

    def process_once(self, max_items: int = 1000) -> int:
        """Procesa los mensajes vencidos de la cola.

        Aplica rate limiting por mensaje y reintentos con backoff. Devuelve
        el número de envíos exitosos.
        """
        sent = 0
        for _ in range(max_items):
            if self.pending() == 0:
                break
            msg = self._pop_due()
            if msg is None:
                break
            # Respeta el ritmo de la API (token bucket).
            if not self.rate_limiter.acquire(blocking=False):
                # Sin token aún → re-programar para el siguiente tick.
                msg.run_at = datetime.now()
                with self._lock:
                    heapq.heappush(self._queue,
                                   (msg.priority, msg.created_at, msg))
                break
            try:
                result = self.wa.send_message(msg.phone, msg.text,
                                              template=msg.template)
            except Exception as e:  # noqa: BLE001
                result = {"status": "error", "message": f"{type(e).__name__}: {e}"}

            if result.get("status") in ("sent", "simulado"):
                msg.status = "sent"
                self.sent_count += 1
                sent += 1
            else:
                msg.retries += 1
                if msg.retries <= msg.max_retries:
                    self._retry_later(msg)
                else:
                    msg.status = "failed"
                    self.failed_count += 1
        return sent

    def run(self, iterations: int = 1, interval_seconds: float = 0.0) -> int:
        """Bucle síncrono: procesa la cola `iterations` veces con pausa."""
        total = 0
        for _ in range(max(iterations, 1)):
            total += self.process_once()
            if interval_seconds > 0:
                time.sleep(interval_seconds)
        return total

    def stats(self) -> dict:
        """Estado de la cola (para diagnóstico / métricas)."""
        return {
            "pending": self.pending(),
            "sent": self.sent_count,
            "failed": self.failed_count,
            "rate_limit": {"rate": self.rate_limiter.rate,
                           "burst": self.rate_limiter.burst},
            "backend": getattr(self.wa, "backend", "?"),
        }


# --------------------------------------------------------------------------- #
# Email (SMTP) — cola y programación de correos.
#
# El scheduler de email comparte el mismo patrón (cola + reintentos + rate
# limiting) pero su transporte es un EmailProvider. Permite programar envíos
# diarios (schedule_daily) y reportes semanales (schedule_weekly).
# --------------------------------------------------------------------------- #
@dataclass
class EmailMessage:
    """Un email en cola: destinatario, asunto, cuerpo (HTML/texto)."""

    to: str
    subject: str
    body: str = ""
    html: Optional[str] = None
    template: Optional[str] = None
    context: Optional[dict] = None
    attachments: Optional[list] = None
    priority: int = 0
    run_at: Optional[datetime] = None      # envío diferido/programado
    max_retries: int = 3
    retries: int = 0
    status: str = "queued"                 # queued | sent | failed
    created_at: float = field(default_factory=time.time)

    @property
    def due(self) -> bool:
        if self.run_at is None:
            return True
        return time.time() >= self.run_at.timestamp()


class EmailScheduler:
    """Cola y programación de envíos de email (SMTP).

    Uso:
        sched = EmailScheduler(provider=EmailProvider())
        sched.schedule_daily("ana@corp.com", "daily_summary", ctx,
                             hour=8, minute=0)
        sched.schedule_weekly("ana@corp.com", "weekly_report", ctx,
                              weekday=0, hour=9, minute=0)
        n = sched.process_once()   # envía los vencidos
    """

    def __init__(self, provider=None, rate_limiter: Optional[RateLimiter] = None,
                 max_retries: int = 3, retry_backoff_seconds: float = 1.0):
        from b2b_ai.notifications.email_provider import EmailProvider
        self.provider = provider or EmailProvider()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_retries = int(max_retries)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self._queue: List[EmailMessage] = []
        self._lock = threading.Lock()
        self.sent_count = 0
        self.failed_count = 0

    # ---- Cola --------------------------------------------------------- #
    def enqueue(self, to: str, subject: str, body: str = "",
                html: Optional[str] = None, template: Optional[str] = None,
                context: Optional[dict] = None,
                attachments: Optional[list] = None,
                run_at: Optional[datetime] = None,
                priority: int = 0, max_retries: Optional[int] = None):
        """Mete un email en la cola. Devuelve el EmailMessage."""
        msg = EmailMessage(
            to=to, subject=subject, body=body, html=html, template=template,
            context=dict(context) if context else None,
            attachments=attachments, run_at=run_at, priority=priority,
            max_retries=self.max_retries if max_retries is None
            else int(max_retries))
        with self._lock:
            heapq.heappush(self._queue,
                           (msg.priority, msg.created_at, msg))
        return msg

    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    # ---- Programación -------------------------------------------------- #
    @staticmethod
    def _next_daily(hour: int, minute: int, now: Optional[datetime] = None) -> datetime:
        """Próxima ocurrencia diaria a las `hour:minute`."""
        now = now or datetime.now()
        candidate = now.replace(hour=hour % 24, minute=minute % 60,
                                 second=0, microsecond=0)
        if candidate <= now:
            from datetime import timedelta
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _next_weekly(weekday: int, hour: int, minute: int,
                     now: Optional[datetime] = None) -> datetime:
        """Próxima ocurrencia semanal (weekday: 0=lunes ... 6=domingo)."""
        now = now or datetime.now()
        days_ahead = (weekday - now.weekday()) % 7
        candidate = now.replace(hour=hour % 24, minute=minute % 60,
                                second=0, microsecond=0)
        from datetime import timedelta
        candidate += timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    def schedule_daily(self, to: str, template: str, context: dict,
                       hour: int = 8, minute: int = 0) -> EmailMessage:
        """Programa un envío diario del template en la próxima hora."""
        run_at = self._next_daily(hour, minute)
        return self.enqueue(to, "", template=template, context=context,
                            run_at=run_at)

    def schedule_weekly(self, to: str, template: str, context: dict,
                        weekday: int = 0, hour: int = 9, minute: int = 0) -> EmailMessage:
        """Programa un reporte semanal en la próxima ocurrencia."""
        run_at = self._next_weekly(weekday, hour, minute)
        return self.enqueue(to, "", template=template, context=context,
                            run_at=run_at)

    # ---- Procesamiento ------------------------------------------------ #
    def _render(self, msg: EmailMessage):
        """Resuelve subject/body/html a partir del template si aplica."""
        if msg.template:
            from b2b_ai.notifications.templates import render_html
            subject, html = render_html(msg.template, msg.context or {})
            return subject, html, _html_to_text(html)
        return msg.subject, msg.html, msg.body

    def _pop_due(self) -> Optional[EmailMessage]:
        with self._lock:
            while self._queue:
                _, _, msg = heapq.heappop(self._queue)
                if msg.due:
                    return msg
                heapq.heappush(self._queue, (msg.priority, msg.created_at, msg))
                return None
        return None

    def _retry_later(self, msg: EmailMessage) -> None:
        from datetime import timedelta
        delay = self.retry_backoff_seconds * (2 ** msg.retries)
        msg.run_at = datetime.now() + timedelta(seconds=delay)
        with self._lock:
            heapq.heappush(self._queue, (msg.priority, msg.created_at, msg))

    def process_once(self, max_items: int = 1000) -> int:
        """Procesa los emails vencidos. Devuelve nº de envíos exitosos."""
        sent = 0
        for _ in range(max_items):
            if self.pending() == 0:
                break
            msg = self._pop_due()
            if msg is None:
                break
            if not self.rate_limiter.acquire(blocking=False):
                msg.run_at = datetime.now()
                with self._lock:
                    heapq.heappush(self._queue,
                                   (msg.priority, msg.created_at, msg))
                break
            try:
                subject, html, body = self._render(msg)
                result = self.provider.send(msg.to, subject, body,
                                            html=html, attachments=msg.attachments)
            except Exception as e:  # noqa: BLE001
                result = {"status": "error",
                          "message": f"{type(e).__name__}: {e}"}

            if result.get("status") in ("sent", "simulado"):
                msg.status = "sent"
                self.sent_count += 1
                sent += 1
            else:
                msg.retries += 1
                if msg.retries <= msg.max_retries:
                    self._retry_later(msg)
                else:
                    msg.status = "failed"
                    self.failed_count += 1
        return sent

    def stats(self) -> dict:
        return {
            "pending": self.pending(),
            "sent": self.sent_count,
            "failed": self.failed_count,
            "backend": getattr(self.provider, "configured", False)
            and "smtp" or "simulado",
        }


def _html_to_text(html: str) -> str:
    """Convierte un HTML simple a texto plano (para el cuerpo plain-text)."""
    import re
    text = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]
