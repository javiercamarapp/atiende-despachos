# -*- coding: utf-8 -*-
"""
scheduler.py — Celery/periodic task for automatic monthly close.

Schedules the close to start automatically on the 1st of each month.
Uses Celery beat or APScheduler for scheduling.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def get_close_period() -> str:
    """Get the period to close (previous month as YYYY-MM)."""
    now = datetime.utcnow()
    # Close is for the previous month
    if now.month == 1:
        year = now.year - 1
        month = 12
    else:
        year = now.year
        month = now.month - 1
    return f"{year}-{month:02d}"


def run_monthly_close(
    tenant_id: Optional[int] = None,
    rfc: str = "",
) -> dict:
    """Run the automatic monthly close for a tenant.

    This function is called by the scheduler (Celery beat / APScheduler)
    on the 1st of each month.

    Returns a summary dict with the close result.
    """
    from b2b_ai.features.close_management.close_manager import CloseManager
    from b2b_ai.features.close_management.models import CloseStartRequest

    periodo = get_close_period()
    logger.info(f"[SCHEDULER] Starting automatic close for {periodo}")

    manager = CloseManager()
    request = CloseStartRequest(
        periodo=periodo,
        tenant_id=tenant_id,
        rfc=rfc,
    )

    close = manager.start_close(request)

    # Run automatic steps with available data
    data = {"periodo": periodo}
    close = manager.run_automatic_steps(close.id, data)

    summary = {
        "close_id": close.id,
        "periodo": periodo,
        "status": close.status.value,
        "progress_pct": close.progress_pct,
        "steps_completed": close.completed_steps,
        "steps_total": close.total_steps,
        "validations_passed": close.summary.get("validations_passed", 0),
        "validations_total": close.summary.get("validations_total", 0),
        "requires_human_review": close.summary.get("requires_human_review", True),
    }

    logger.info(f"[SCHEDULER] Close {close.id} completed: {summary}")
    return summary


# ---------------------------------------------------------------------------
# Celery task definition (optional — only if Celery is available)
# ---------------------------------------------------------------------------

def get_celery_task():
    """Return a Celery task for the monthly close, or None if Celery unavailable."""
    try:
        from celery import shared_task

        @shared_task(
            name="close_management.monthly_close",
            bind=True,
            max_retries=3,
            default_retry_delay=300,
        )
        def monthly_close_task(self, tenant_id: Optional[int] = None, rfc: str = ""):
            """Celery task: runs automatic monthly close."""
            try:
                return run_monthly_close(tenant_id=tenant_id, rfc=rfc)
            except Exception as exc:
                logger.error(f"[CELERY] Monthly close failed: {exc}")
                raise self.retry(exc=exc)

        return monthly_close_task
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# APScheduler job definition (optional)
# ---------------------------------------------------------------------------

def get_apscheduler_job():
    """Return an APScheduler-compatible job function."""
    def monthly_close_job():
        """APScheduler job: runs automatic monthly close."""
        return run_monthly_close()

    return monthly_close_job


# ---------------------------------------------------------------------------
# Cron expression helper
# ---------------------------------------------------------------------------

def get_cron_schedule() -> dict:
    """Get the cron schedule for the monthly close.

    Runs at 02:00 UTC on the 1st of every month.
    """
    return {
        "task": "close_management.monthly_close",
        "schedule": {
            "minute": 0,
            "hour": 2,
            "day_of_month": 1,
            "month_of_year": "*",
        },
        "options": {
            "queue": "close",
        },
    }
