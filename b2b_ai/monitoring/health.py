# -*- coding: utf-8 -*-
"""
health.py — Snapshot de estado detallado para GET /health/detailed.

Reporta: conexión a DB, conexión a Redis, espacio en disco, uso de memoria,
uptime y proceso. Sin dependencias obligatorias: usa psutil/redis si están
instalados y degrada limpio si no.

Redis se reporta "not_configured" si no hay REDIS_URL (el container de
producción la inyecta). Si está configurada, hace un PING (vía el cliente redis
si existe, o un socket TCP host:puerto como fallback sin dependencia).
"""
from __future__ import annotations

import os
import shutil
import socket
import time

from b2b_ai.monitoring.metrics import metrics


def _db_status(db) -> dict:
    info = {"status": "unknown"}
    try:
        start = time.perf_counter()
        db.conn.execute("SELECT 1")
        latency = (time.perf_counter() - start) * 1000
        info = {
            "status": "ok",
            "backend": "sqlite",
            "path": getattr(db, "path", None),
            "schema_version": db.schema_version(),
            "latency_ms": round(latency, 2),
        }
    except Exception as e:  # noqa: BLE001
        info = {"status": "error", "error": str(e)}
    return info


def _redis_status() -> dict:
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return {"status": "not_configured",
                "hint": "REDIS_URL no definido; el container de producción lo inyecta."}
    try:
        import redis  # type: ignore
        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return {"status": "ok", "url": url, "detail": "PING ok"}
    except ImportError:
        pass  # sin cliente: fallback socket TCP
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "url": url, "error": str(e)}
    # Fallback sin dependencia: conecta al host:puerto del URL.
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        host = parts.hostname or "localhost"
        port = parts.port or 6379
        with socket.create_connection((host, port), timeout=2):
            pass
        return {"status": "ok", "url": url, "detail": "TCP ok (sin cliente redis)"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "url": url, "error": str(e)}


def _disk_status(db) -> dict:
    target = getattr(db, "path", None) or os.getcwd()
    base = os.path.dirname(os.path.abspath(target)) if os.path.isabs(target) else os.path.abspath(target)
    try:
        usage = shutil.disk_usage(os.path.dirname(base) if not os.path.isdir(base) else base)
        total = usage.total
        free = usage.free
        used = usage.used
        percent = round((used / total) * 100, 1) if total else None
        status = "ok" if percent is not None and percent < 90 else "warning"
        return {"status": status, "path": base,
                "total_bytes": total, "used_bytes": used, "free_bytes": free,
                "percent": percent}
    except OSError as e:
        return {"status": "error", "path": base, "error": str(e)}


def _memory_status() -> dict:
    """Uso de memoria del proceso + sistema. Degrada si no hay psutil."""
    info = {"status": "ok"}
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        proc = psutil.Process(os.getpid())
        info.update({
            "system_total_bytes": vm.total,
            "system_available_bytes": vm.available,
            "system_percent": vm.percent,
            "rss_bytes": proc.memory_info().rss,
            "rss_percent": proc.memory_percent(),
        })
        return info
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        info["status"] = "degraded"
        info["error"] = str(e)
        return info
    # Fallback stdlib: RSS vía resource + total vía sysctl (macOS).
    try:
        import resource
        import sys as _sys
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS: ru_maxrss viene en bytes; Linux: en KB.
        if _sys.platform == "darwin":
            info["rss_bytes"] = int(rss)
        else:
            info["rss_bytes"] = int(rss * 1024)
    except Exception:  # noqa: BLE001
        info["rss_bytes"] = None
    try:
        import subprocess
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                             text=True, timeout=2)
        info["system_total_bytes"] = int(out.stdout.strip())
    except Exception:  # noqa: BLE001
        info["system_total_bytes"] = None
    info["note"] = "psutil no instalado; métricas parciales."
    return info


def build_health_detailed(db) -> dict:
    """Construye el payload completo de /health/detailed."""
    db_ = _db_status(db)
    redis_ = _redis_status()
    disk_ = _disk_status(db)
    mem_ = _memory_status()

    # Estado agregado: ok si DB ok y (redis ok o not_configured) y disco < 90%.
    problems = []
    if db_.get("status") != "ok":
        problems.append("db")
    if redis_.get("status") == "error":
        problems.append("redis")
    if disk_.get("status") != "ok":
        problems.append("disk")
    if problems:
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "service": "b2b-ai",
        "checked_at": round(time.time(), 3),
        "uptime_seconds": metrics.uptime(),
        "process": {
            "pid": os.getpid(),
            "threads": _thread_count(),
        },
        "db": db_,
        "redis": redis_,
        "disk": disk_,
        "memory": mem_,
        "degraded_components": problems,
    }


def _thread_count():
    try:
        import threading
        return threading.active_count()
    except Exception:  # noqa: BLE001
        return None
