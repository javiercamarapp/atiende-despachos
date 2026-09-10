# -*- coding: utf-8 -*-
"""b2b_ai.scheduler — scheduler interno (asyncio) del proceso uvicorn.

Ver `internal_scheduler.py` para el detalle. Este paquete reemplaza la
necesidad de un cron externo que llame a los endpoints HTTP manuales de
SAT (`/api/v1/sat/schedule`) y del pipeline (`/api/v1/pipeline/run`).
"""
from b2b_ai.scheduler.internal_scheduler import (
    InternalScheduler,
    scheduler_enabled_from_env,
)

__all__ = ["InternalScheduler", "scheduler_enabled_from_env"]
