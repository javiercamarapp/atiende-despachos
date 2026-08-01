# -*- coding: utf-8 -*-
"""
metrics.py — Registro en memoria de métricas de la API (request count,
latencia y códigos de estado). Sin dependencias externas.

En producción multi-replica estas métricas son por-proceso; para agregación
global se recomienda exponer /metrics en Prometheus y usar un job de scrape
(ver docs/DEPLOYMENT.md → Monitoreo). El almacén es thread-safe para convivir
con el threadpool de uvicorn.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, List

# Tamaño máximo del buffer de latencia por ruta (ventana deslizante).
_MAX_LATENCY_BUCKET = 200


class Metrics:
    """Contadores y percentiles de latencia por ruta."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._total = 0
        self._errors_5xx = 0
        self._by_path: Dict[str, int] = defaultdict(int)
        self._by_status: Dict[int, int] = defaultdict(int)
        self._latency: Dict[str, List[float]] = defaultdict(list)

    def record(self, path: str, status: int, duration: float) -> None:
        """Registra una petición completada (thread-safe)."""
        with self._lock:
            self._total += 1
            self._by_path[path] += 1
            self._by_status[status] += 1
            if status >= 500:
                self._errors_5xx += 1
            bucket = self._latency[path]
            bucket.append(duration)
            if len(bucket) > _MAX_LATENCY_BUCKET:
                bucket.pop(0)

    def uptime(self) -> float:
        return round(time.monotonic() - self._started, 1)

    def total_requests(self) -> int:
        return self._total

    @staticmethod
    def _p95(values: List[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = int(round(len(s) * 0.95)) - 1
        if idx < 0:
            idx = 0
        return round(s[idx] * 1000, 2)  # ms

    def snapshot(self) -> dict:
        """Snapshot consistente de las métricas actuales (thread-safe)."""
        with self._lock:
            latency = {}
            for path, bucket in self._latency.items():
                if not bucket:
                    continue
                latency[path] = {
                    "count": len(bucket),
                    "avg_ms": round((sum(bucket) / len(bucket)) * 1000, 2),
                    "p95_ms": self._p95(bucket),
                }
            return {
                "service": "b2b-ai",
                "uptime_seconds": self.uptime(),
                "total_requests": self._total,
                "errors_5xx": self._errors_5xx,
                "requests_by_path": dict(self._by_path),
                "status_codes": {str(k): v for k, v in sorted(self._by_status.items())},
                "latency_ms_by_path": latency,
            }


# Instancia singleton compartida por el proceso (los workers uvicorn tienen
# cada uno la suya — esperado con un registro en memoria por proceso).
metrics = Metrics()
