# -*- coding: utf-8 -*-
"""
routes.py — API endpoints for Close Management Agent.

Endpoints:
    POST /api/v1/close/start         Start a monthly close
    GET  /api/v1/close/status        Get close status
    POST /api/v1/close/approve-step  Approve/reject a step
    POST /api/v1/close/finalize      Finalize (close) a period
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from b2b_ai.features.close_management.close_manager import CloseManager
from b2b_ai.features.close_management.erp_writer import ERPWriter
from b2b_ai.features.close_management.models import (
    CloseApproveStepRequest,
    CloseFinalizeRequest,
    ClosePeriodStatus,
    CloseStartRequest,
    CloseStepStatus,
    ERPType,
)
from b2b_ai.features.close_management.validation_engine import ValidationEngine


class CloseManagementRouter:
    """Builder for the Close Management API router.

    Usage:
        router_builder = CloseManagementRouter(db=db, require_api_key=auth)
        router = router_builder.build()
        app.include_router(router)
    """

    def __init__(self, db=None, require_api_key=None):
        self.db = db
        self.require_api_key = require_api_key or (lambda: {})

    def build(self) -> APIRouter:
        router = APIRouter(
            prefix="/api/v1/close",
            tags=["close-management"],
        )

        def _scope(auth_info) -> Optional[int]:
            return auth_info.get("tenant_id") if auth_info else None

        # Shared manager instance
        erp_writer = ERPWriter(erp_type=ERPType.GENERIC)
        validation_engine = ValidationEngine()
        manager = CloseManager(
            erp_writer=erp_writer,
            validation_engine=validation_engine,
        )

        # -- start -------------------------------------------------------
        @router.post(
            "/start",
            summary="Start a monthly close process",
        )
        async def close_start(
            req: CloseStartRequest,
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Start a new monthly close.

            Creates the checklist (17 steps) and marks the period as
            in_progress. Use POST /close/approve-step to advance steps,
            then POST /close/finalize to close the period.
            """
            tenant = _scope(auth_info)
            if req.tenant_id is None and tenant:
                req.tenant_id = tenant

            close = manager.start_close(req)
            return {
                "ok": True,
                "close_id": close.id,
                "periodo": close.periodo,
                "status": close.status.value,
                "total_steps": close.total_steps,
                "summary": close.summary,
            }

        # -- status ------------------------------------------------------
        @router.get(
            "/status",
            summary="Get close status and progress",
        )
        async def close_status(
            close_id: str = Query(..., description="Close ID"),
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Get the current status of a close process.

            Returns checklist progress, adjustments, validations, and summary.
            """
            close = manager.get_close(close_id)
            if close is None:
                raise HTTPException(404, f"Close {close_id} not found")

            data = {
                "close_id": close.id,
                "periodo": close.periodo,
                "status": close.status.value,
                "rfc": close.rfc,
                "progress_pct": close.progress_pct,
                "steps": [s.model_dump() for s in close.steps],
                "adjustments": [
                    {
                        "type": a.type.value,
                        "description": a.description,
                        "total_debe": a.total_debe,
                        "total_haber": a.total_haber,
                        "is_balanced": a.is_balanced,
                        "status": a.status,
                    }
                    for a in close.adjustments
                ],
                "validations": [v.model_dump() for v in close.validations],
                "summary": close.summary,
                "created_at": close.created_at,
                "updated_at": close.updated_at,
                "closed_at": close.closed_at,
                "closed_by": close.closed_by,
            }

            return data

        # -- approve-step -----------------------------------------------
        @router.post(
            "/approve-step",
            summary="Approve or reject a close checklist step",
        )
        async def close_approve_step(
            req: CloseApproveStepRequest,
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Approve or reject a specific step.

            Steps that require human approval (e.g., inventory adjustments,
            declaration drafts) must be explicitly approved before the period
            can be finalized.
            """
            try:
                close = manager.approve_step(
                    close_id=req.close_id,
                    step_num=req.step,
                    approved=req.approved,
                    by=req.approved_by,
                    notes=req.notes,
                )
            except ValueError as e:
                raise HTTPException(400, str(e))

            step = next(s for s in close.steps if s.step == req.step)
            return {
                "ok": True,
                "close_id": close.id,
                "step": step.step,
                "name": step.name,
                "status": step.status.value,
                "approved_by": step.approved_by,
                "progress_pct": close.progress_pct,
            }

        # -- finalize ---------------------------------------------------
        @router.post(
            "/finalize",
            summary="Finalize (close) the accounting period",
        )
        async def close_finalize(
            req: CloseFinalizeRequest,
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Finalize and close the period.

            All steps must be approved/skipped and all validations must pass.
            Use force=true to close despite warnings (not recommended).
            """
            try:
                close = manager.finalize(
                    close_id=req.close_id,
                    closed_by=req.closed_by,
                    force=req.force,
                )
            except ValueError as e:
                raise HTTPException(400, str(e))

            return {
                "ok": True,
                "close_id": close.id,
                "periodo": close.periodo,
                "status": close.status.value,
                "closed_at": close.closed_at,
                "closed_by": close.closed_by,
                "summary": close.summary,
            }

        # -- run-automatic -----------------------------------------------
        @router.post(
            "/run-automatic",
            summary="Execute all automatic close steps",
        )
        async def close_run_automatic(
            close_id: str = Query(..., description="Close ID"),
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Execute all automatic close steps with default/empty data.

            In production, the data comes from the database and integrated agents.
            This endpoint triggers the full automatic pipeline.
            """
            close = manager.get_close(close_id)
            if close is None:
                raise HTTPException(404, f"Close {close_id} not found")

            # Gather data from DB if available
            data = {"periodo": close.periodo}
            if self.db and close.tenant_id:
                try:
                    data["total_cfdis"] = self.db.count_invoices(tenant_id=close.tenant_id)
                    data["cfdis_procesados"] = data["total_cfdis"]
                except Exception:
                    pass

            close = manager.run_automatic_steps(close_id, data)
            return {
                "ok": True,
                "close_id": close.id,
                "progress_pct": close.progress_pct,
                "summary": close.summary,
            }

        # -- list --------------------------------------------------------
        @router.get(
            "/list",
            summary="List all close periods",
        )
        async def close_list(
            auth_info: dict = Depends(self.require_api_key),
        ):
            """List all close periods for the tenant."""
            tenant = _scope(auth_info)
            closes = manager.list_closes(tenant_id=tenant)
            return {
                "count": len(closes),
                "closes": [
                    {
                        "close_id": c.id,
                        "periodo": c.periodo,
                        "status": c.status.value,
                        "progress_pct": c.progress_pct,
                    }
                    for c in closes
                ],
            }

        return router


def build_close_management_router(db=None, require_api_key=None):
    """Convenience function to build the close management router."""
    builder = CloseManagementRouter(db=db, require_api_key=require_api_key)
    return builder.build()
