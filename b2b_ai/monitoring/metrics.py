# -*- coding: utf-8 -*-
"""
metrics.py — Registro de métricas operativas, de negocio y custom, con
renderizado en formato Prometheus text exposition.

Sin dependencias externas (thread-safe con un lock). Cada worker uvicorn tiene
su propio registro en memoria (esperado); Prometheus scrapea /metrics/prometheus
por worker y agrega en el servidor.

Métricas incluidas:
    Operativas:
        b2b_requests_total{path,status}         contador de peticiones
        b2b_request_duration_seconds{path}      histograma (sum/count + p95)
        b2b_errors_total{path,status}           errores 5xx
    De negocio:
        b2b_invoices_processed_total            facturas procesadas
        b2b_anomalies_detected_total            anomalías detectadas
    Custom:
        b2b_tenant_api_calls{tenant_id}         gauge: uso de API por tenant
        b2b_tenant_invoices_processed{tenant_id} gauge: uso por tenant

Uso:
    from b2b_ai.monitoring.metrics import metrics
    metrics.record_request("/api/v1/invoices", 200, 0.043)
    metrics.inc_invoices()
    metrics.inc_anomalies(3)
    metrics.set_tenant_usage([{"tenant_id":1,"api_calls":9,"invoices_processed":4}])
    print(metrics.render_prometheus())
    metrics.snapshot()  # JSON (para /health/detailed y alerts)
"""
from __future__ import annotations

import collections
import threading
import time

# Tamaño máximo de la ventana de latencia muestreada (para percentiles).
_HISTORY_MAX = 5000

# Definiciones de métricas para el output Prometheus: (tipo, ayuda).
_METRIC_HELP = {
    "b2b_requests_total": ("counter", "Total de peticiones HTTP por ruta y estado."),
    "b2b_request_duration_seconds": ("summary", "Latencia de peticiones en segundos por ruta."),
    "b2b_errors_total": ("counter", "Total de errores HTTP (5xx) por ruta y estado."),
    "b2b_invoices_processed_total": ("counter", "Total de facturas procesadas por el pipeline."),
    "b2b_anomalies_detected_total": ("counter", "Total de anomalías detectadas en facturas."),
    "b2b_tenant_api_calls": ("gauge", "Llamadas a la API acumuladas por tenant."),
    "b2b_tenant_invoices_processed": ("gauge", "Facturas procesadas acumuladas por tenant."),
}


def _quote(value) -> str:
    """Escapa un valor de label según el formato Prometheus."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(labels: dict) -> str:
    if not labels:
        return ""
    parts = ",".join('%s="%s"' % (k, _quote(v)) for k, v in sorted(labels.items()))
    return "{%s}" % parts


class MetricsRegistry:
    """Registro thread-safe de contadores, gauges y resúmenes de latencia."""

    def __init__(self) -> None:
        # RLock (reentrante): snapshot() adquiere el lock y llama a helpers
        # (_counter_value, _tenant_usage_snapshot) que también lo adquieren.
        self._lock = threading.RLock()
        self._started = time.monotonic()
        self._counters: "dict[tuple, int]" = collections.defaultdict(int)
        self._counter_labels: "dict[tuple, dict]" = {}
        self._gauges: "dict[tuple, float]" = {}
        self._gauge_labels: "dict[tuple, dict]" = {}
        # (name, labels) -> {sum, count, samples deque}
        self._summaries: "dict[tuple, dict]" = {}
        self._summary_labels: "dict[tuple, dict]" = {}

    # -- bajo nivel ------------------------------------------------------- #
    def _c_key(self, name: str, labels: dict) -> tuple:
        return (name, tuple(sorted(labels.items())))

    def inc(self, name: str, value: int = 1, labels: dict = None) -> None:
        labels = labels or {}
        with self._lock:
            k = self._c_key(name, labels)
            self._counters[k] += value
            self._counter_labels[k] = labels

    def set(self, name: str, value, labels: dict = None) -> None:
        labels = labels or {}
        with self._lock:
            k = self._c_key(name, labels)
            self._gauges[k] = float(value)
            self._gauge_labels[k] = labels

    def observe(self, name: str, value: float, labels: dict = None) -> None:
        """Registra una muestra para un summary (sum/count/percentiles)."""
        labels = labels or {}
        with self._lock:
            k = self._c_key(name, labels)
            if k not in self._summaries:
                self._summaries[k] = {"sum": 0.0, "count": 0, "samples": collections.deque(maxlen=_HISTORY_MAX)}
                self._summary_labels[k] = labels
            s = self._summaries[k]
            s["sum"] += float(value)
            s["count"] += 1
            s["samples"].append(float(value))

    # -- conveniencia (operativas) --------------------------------------- #
    def record_request(self, path: str, status: int, duration: float) -> None:
        self.inc("b2b_requests_total", 1, {"path": path, "status": str(status)})
        self.observe("b2b_request_duration_seconds", duration, {"path": path})
        if status >= 500:
            self.inc("b2b_errors_total", 1, {"path": path, "status": str(status)})

    # -- conveniencia (negocio / custom) --------------------------------- #
    def inc_invoices(self, n: int = 1) -> None:
        self.inc("b2b_invoices_processed_total", n)

    def inc_anomalies(self, n: int = 1) -> None:
        self.inc("b2b_anomalies_detected_total", n)

    def set_tenant_usage(self, rows) -> None:
        """Actualiza los gauges custom por tenant desde filas de usage."""
        for row in rows or []:
            tid = row.get("tenant_id")
            if tid is None:
                continue
            self.set("b2b_tenant_api_calls", row.get("api_calls", 0), {"tenant_id": str(tid)})
            self.set("b2b_tenant_invoices_processed",
                     row.get("invoices_processed", 0), {"tenant_id": str(tid)})

    # -- lecturas -------------------------------------------------------- #
    def uptime(self) -> float:
        return round(time.monotonic() - self._started, 1)

    def reset(self) -> None:
        """Limpia todos los registros (útil en tests)."""
        with self._lock:
            self._started = time.monotonic()
            self._counters.clear()
            self._counter_labels.clear()
            self._gauges.clear()
            self._gauge_labels.clear()
            self._summaries.clear()
            self._summary_labels.clear()

    @staticmethod
    def _pct(samples, p: float) -> float:
        if not samples:
            return 0.0
        s = sorted(samples)
        idx = min(len(s) - 1, int(round(len(s) * p)) - 1)
        return s[max(0, idx)]

    def snapshot(self) -> dict:
        """Snapshot consistente (JSON-friendly) para /health/detailed y alerts."""
        with self._lock:
            by_path = {}
            for k, labels in self._summary_labels.items():
                s = self._summaries[k]
                path = labels["path"]
                p95 = self._pct(s["samples"], 0.95)
                p99 = self._pct(s["samples"], 0.99)
                by_path[path] = {
                    "count": s["count"],
                    "sum_ms": round(s["sum"] * 1000, 3),
                    "avg_ms": round((s["sum"] / s["count"]) * 1000, 3) if s["count"] else 0.0,
                    "p95_ms": round(p95 * 1000, 3),
                    "p99_ms": round(p99 * 1000, 3),
                }
            total = sum(v for k, v in self._counters.items() if k[0] == "b2b_requests_total")
            errors = sum(v for k, v in self._counters.items() if k[0] == "b2b_errors_total")
            return {
                "service": "b2b-ai",
                "uptime_seconds": self.uptime(),
                "total_requests": total,
                "errors_5xx": errors,
                "error_rate": round(errors / total, 4) if total else 0.0,
                "latency_ms_by_path": by_path,
                "invoices_processed": self._counter_value("b2b_invoices_processed_total"),
                "anomalies_detected": self._counter_value("b2b_anomalies_detected_total"),
                "tenant_usage": self._tenant_usage_snapshot(),
            }

    def _counter_value(self, name: str) -> int:
        with self._lock:
            return sum(v for k, v in self._counters.items() if k[0] == name)

    def _tenant_usage_snapshot(self) -> list:
        with self._lock:
            out = {}
            for k, labels in self._gauge_labels.items():
                name = k[0]
                if name.startswith("b2b_tenant_"):
                    tid = labels.get("tenant_id")
                    out.setdefault(tid, {})[name] = self._gauges[k]
            return [{"tenant_id": tid, **vals} for tid, vals in sorted(out.items())]

    # -- Prometheus ------------------------------------------------------ #
    def render_prometheus(self) -> str:
        """Renderiza todas las métricas en formato Prometheus text exposition."""
        with self._lock:
            lines = []
            for name, (mtype, help_) in sorted(_METRIC_HELP.items()):
                lines.append("# HELP %s %s" % (name, help_))
                lines.append("# TYPE %s %s" % (name, mtype))
                lines.extend(self._render_counter(name, mtype))
                lines.extend(self._render_gauge(name, mtype))
                lines.extend(self._render_summary(name, mtype))
            return "\n".join(lines) + "\n"

    def _render_counter(self, name: str, mtype: str) -> list:
        if mtype != "counter":
            return []
        out = []
        for k, labels in sorted(self._counter_labels.items(), key=lambda x: x[0]):
            if k[0] == name:
                out.append("%s%s %d" % (name, _labels(labels), self._counters[k]))
        return out

    def _render_gauge(self, name: str, mtype: str) -> list:
        if mtype != "gauge":
            return []
        out = []
        for k, labels in sorted(self._gauge_labels.items(), key=lambda x: x[0]):
            if k[0] == name:
                out.append("%s%s %s" % (name, _labels(labels), self._gauges[k]))
        return out

    def _render_summary(self, name: str, mtype: str) -> list:
        if mtype != "summary":
            return []
        out = []
        for k, labels in sorted(self._summary_labels.items(), key=lambda x: x[0]):
            if k[0] != name:
                continue
            s = self._summaries[k]
            base = "%s" % (name,)
            l = _labels(labels)
            out.append("%s_count%s %d" % (base, l, s["count"]))
            out.append("%s_sum%s %s" % (base, l, round(s["sum"], 6)))
            out.append("%s%s p95=%s" % (base, l, round(self._pct(s["samples"], 0.95), 6)))
            out.append("%s%s p99=%s" % (base, l, round(self._pct(s["samples"], 0.99), 6)))
        return out


# Singleton compartido por el proceso.
metrics = MetricsRegistry()
