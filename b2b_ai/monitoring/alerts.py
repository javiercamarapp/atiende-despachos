# -*- coding: utf-8 -*-
"""
alerts.py — Motor de alertas: reglas, canales (email/webhook) e historial.

Reglas por defecto (configurables):
    - error_rate  > 5%  (window 60s)  severidad warning
    - latency_p95 > 2s  (window 300s) severidad critical

Semántica de disparo con cooldown: una alerta se dispara solo en la transición
(cruzando el umbral), no en cada evaluación; se "limpia" cuando el valor baja
del umbral. El historial guarda ambos eventos (triggered/cleared).

Canales:
    - EmailChannel:   registra la alerta a nivel CRITICAL en el logger JSON. Si
                      se configuran SMTP_HOST/SMTP_PORT (smtplib), envía de
                      verdad; si no, es un mock que no falla. Adecuado para el
                      MVP sin credenciales SMTP.
    - WebhookChannel: hace POST JSON a una URL vía urllib (timeout 5s) y reporta
                      éxito/fallo. Ideal para Slack/Discord/generic webhook.

Sin dependencias externas.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
import urllib.request

from b2b_ai.monitoring.logger import get_logger

log = get_logger("alerts")

# Comparadores soportados por las reglas.
_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}

# Tamaño máximo del historial en memoria.
_HISTORY_MAX = 500


class Alert:
    """Una alerta disparada (o limpiada)."""

    def __init__(self, rule_name, severity, message, value, threshold,
                 status="triggered", ts=None):
        self.ts = ts or time.time()
        self.rule_name = rule_name
        self.severity = severity
        self.message = message
        self.value = value
        self.threshold = threshold
        self.status = status  # "triggered" | "cleared"

    def to_dict(self) -> dict:
        return {
            "ts": round(self.ts, 3),
            "rule": self.rule_name,
            "severity": self.severity,
            "status": self.status,
            "value": round(self.value, 4) if isinstance(self.value, float) else self.value,
            "threshold": self.threshold,
            "message": self.message,
        }


class AlertRule:
    """Definición de una regla de alerta.

    `compute` describe cómo agregar la serie del métrico:
        {"type": "rate", "numerator": "requests_total", "denominator": "errors_total"}
        {"type": "p95", "metric": "latency_ms"}
    `op` es un comparador (">", ">=", "<", "<=").
    `window_seconds` es la ventana temporal sobre la que se agrega.
    """

    def __init__(self, name, compute, op, threshold, window_seconds,
                 severity="warning", description=""):
        self.name = name
        self.compute = compute
        self.op = op
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.severity = severity
        self.description = description

    def evaluate(self, series: dict, now: float):
        """Devuelve (value, fired) o (None, False) si no hay suficientes datos."""
        if self.compute["type"] == "rate":
            num = _window_sum(series.get(self.compute["numerator"]), now, self.window_seconds)
            den = _window_sum(series.get(self.compute["denominator"]), now, self.window_seconds)
            if den <= 0:
                return None, False
            value = num / den
        elif self.compute["type"] == "p95":
            samples = _window_samples(series.get(self.compute["metric"]), now, self.window_seconds)
            if not samples:
                return None, False
            value = sorted(samples)[min(len(samples) - 1, int(round(len(samples) * 0.95)) - 1)]
        elif self.compute["type"] == "sum":
            value = _window_sum(series.get(self.compute["metric"]), now, self.window_seconds)
            if series.get(self.compute["metric"]) is None:
                return None, False
        else:
            return None, False
        fired = _OPERATORS[self.op](value, self.threshold)
        return value, fired


def _window_sum(entries, now: float, window: float) -> float:
    if not entries:
        return 0.0
    cutoff = now - window
    return sum(v for ts, v in entries if ts >= cutoff)


def _window_samples(entries, now: float, window: float) -> list:
    if not entries:
        return []
    cutoff = now - window
    return [v for ts, v in entries if ts >= cutoff]


# --------------------------------------------------------------------------- #
# Canales
# --------------------------------------------------------------------------- #
class EmailChannel:
    """Canal email. Sin SMTP configurado: registra en el logger JSON (mock).

    Con SMTP_HOST/SMTP_PORT y credenciales opcionales SMTP_USER/SMTP_PASSWORD y
    SMTP_TO, envía de verdad usando smtplib. Nunca lanza: reporta éxito/fallo.
    """

    def __init__(self, to=None):
        self.to = to or os.environ.get("SMTP_TO", "")

    def send(self, alert: Alert) -> bool:
        subject = "[%s] %s — %s" % (alert.severity.upper(), alert.rule_name, alert.message)
        log.critical("ALERTA %s | %s | %s",
                     alert.status.upper(), alert.rule_name, alert.message,
                     extra={"extra_fields": alert.to_dict()})
        host = os.environ.get("SMTP_HOST")
        port = int(os.environ.get("SMTP_PORT", "587"))
        if not host or not self.to:
            return True  # mock: canal configurado, envío registrado
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(json.dumps(alert.to_dict(), indent=2), "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = os.environ.get("SMTP_FROM", "monitor@b2b-ai.local")
            msg["To"] = self.to
            with smtplib.SMTP(host, port, timeout=10) as s:
                user = os.environ.get("SMTP_USER")
                if user:
                    s.starttls()
                    s.login(user, os.environ.get("SMTP_PASSWORD", ""))
                s.sendmail(msg["From"], [self.to], msg.as_string())
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("fallo al enviar alerta por email: %s", e)
            return False


class WebhookChannel:
    """Canal webhook: POST JSON a una URL (timeout 5s)."""

    def __init__(self, url: str):
        # La URL de salida del webhook de alertas viene de configuración
        # (B2B_ALERT_WEBHOOK_URL), no de input del usuario; aun así se valida
        # el esquema para bloquear file:/custom (defensa en profundidad).
        from urllib.parse import urlparse
        if (urlparse(url).scheme or "").lower() not in ("http", "https"):
            raise ValueError(f"Esquema de URL de alerta no permitido: {url!r}")
        self.url = url

    def send(self, alert: Alert) -> bool:
        payload = json.dumps(alert.to_dict()).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "b2b-ai-monitor/1.0"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
                return 200 <= resp.status < 300
        except Exception as e:  # noqa: BLE001
            log.warning("fallo al enviar alerta por webhook a %s: %s", self.url, e)
            return False


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #
DEFAULT_RULES = [
    AlertRule("error_rate",
              {"type": "rate", "numerator": "errors_total", "denominator": "requests_total"},
              ">", 0.05, 60, severity="warning",
              description="Tasa de errores 5xx superior al 5% en la última ventana."),
    AlertRule("latency_p95",
              {"type": "p95", "metric": "latency_ms"},
              ">", 2000.0, 300, severity="critical",
              description="Latencia p95 superior a 2 segundos en la última ventana."),
]


class AlertManager:
    """Evalúa reglas contra series temporales y despacha por canales."""

    def __init__(self, rules=None, channels=None, history_max=_HISTORY_MAX):
        self.rules = list(rules) if rules is not None else list(DEFAULT_RULES)
        self.channels = list(channels) if channels is not None else []
        self._series: "dict[str, list]" = collections.defaultdict(list)
        self._lock = threading.Lock()
        self._active: set = set()
        self.history: list = []
        self.history_max = history_max

    def record(self, metric: str, value: float, ts: float = None) -> None:
        """Registra un valor para un métrico (usa el mismo nombre que las reglas)."""
        ts = ts if ts is not None else time.time()
        with self._lock:
            self._series[metric].append((ts, float(value)))
            # Poda: solo guardamos lo que quepa en la ventana más grande.
            max_window = max((r.window_seconds for r in self.rules), default=300) * 2
            cutoff = ts - max_window
            self._series[metric] = [(t, v) for t, v in self._series[metric] if t >= cutoff]

    def record_http(self, status: int, duration: float, ts: float = None) -> None:
        """Atajo: registra el outcome de una petición para las reglas por defecto."""
        self.record("requests_total", 1, ts)
        self.record("errors_total", 1 if status >= 500 else 0, ts)
        self.record("latency_ms", duration * 1000.0, ts)

    def evaluate(self) -> list:
        """Evalúa todas las reglas; dispara/limpia alertas y las despacha.

        Devuelve la lista de alertas nuevas (triggered) de esta evaluación.
        """
        now = time.time()
        fired_new = []
        with self._lock:
            series = dict(self._series)
            for rule in self.rules:
                value, fired = rule.evaluate(series, now)
                if value is None:
                    continue
                if fired and rule.name not in self._active:
                    self._active.add(rule.name)
                    alert = Alert(rule.name, rule.severity,
                                  rule.description or "%s superó el umbral" % rule.name,
                                  value, rule.threshold, status="triggered", ts=now)
                    self._append_history(alert)
                    fired_new.append(alert)
                    log.warning("ALERTA TRIGGERED %s (value=%s threshold=%s)",
                                rule.name, value, rule.threshold)
                elif not fired and rule.name in self._active:
                    self._active.discard(rule.name)
                    alert = Alert(rule.name, rule.severity,
                                  "Recuperado: %s por debajo del umbral" % rule.name,
                                  value, rule.threshold, status="cleared", ts=now)
                    self._append_history(alert)
        for alert in fired_new:
            for channel in self.channels:
                try:
                    channel.send(alert)
                except Exception as e:  # noqa: BLE001 — un canal roto no rompe la evaluación
                    log.error("canal de alertas falló: %s", e)
        return fired_new

    def _append_history(self, alert: Alert) -> None:
        self.history.append(alert)
        if len(self.history) > self.history_max:
            self.history = self.history[-self.history_max:]

    def alert_history(self, limit=50) -> list:
        return [a.to_dict() for a in self.history[-limit:]]

    def active_alerts(self) -> list:
        return [a for a in self.history if a.status == "triggered"]

    def reset(self) -> None:
        """Limpia series, alertas activas e historial (útil en tests)."""
        with self._lock:
            self._series.clear()
            self._active.clear()
            self.history = []


# Singleton compartido por el proceso.
alerts = AlertManager()
