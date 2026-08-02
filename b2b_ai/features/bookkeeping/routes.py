# -*- coding: utf-8 -*-
"""routes.py — FastAPI router for the Bookkeeping Agent (Agente 5).

Endpoints:
    POST /api/v1/bookkeeping/process     Process CFDIs through full pipeline
    GET  /api/v1/bookkeeping/status      Get pipeline status
    POST /api/v1/bookkeeping/override    Submit human override
    GET  /api/v1/bookkeeping/suggestions Get CFDIs needing review

Built with `build_bookkeeping_router(...)` following the project pattern.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.bookkeeping.models import (
    ERPSystem,
    OverrideAction,
)
from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator
from b2b_ai.features.bookkeeping.auto_classifier import AutoClassifier
from b2b_ai.features.bookkeeping.rules_engine import AccountingRulesEngine
from b2b_ai.features.bookkeeping.journal_generator import JournalEntryGenerator
from b2b_ai.features.bookkeeping.erp_registrar import ERPRegistrar
from b2b_ai.features.bookkeeping.human_override import HumanOverrideManager


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    """Request to process CFDIs through the bookkeeping pipeline."""
    cfdis: List[Dict[str, Any]] = Field(..., description="List of parsed CFDI dicts")
    tenant_id: str = Field(default="", description="Tenant identifier")
    periodo: str = Field(default="", description="Period YYYY-MM")
    fecha: Optional[str] = Field(default=None, description="Override date for journal entries")
    auto_register_erp: bool = Field(default=True, description="Auto-register in ERP")


class OverrideRequest(BaseModel):
    """Request to submit a human override."""
    cfdi_uuid: str = Field(..., description="CFDI UUID to correct")
    action: OverrideAction = Field(default=OverrideAction.RECLASSIFY)
    new_categoria: str = Field(default="", description="New category")
    new_cuenta_cargo: str = Field(default="", description="New debit account")
    new_cuenta_abono: str = Field(default="", description="New credit account")
    original_categoria: str = Field(default="", description="Original category")
    reason: str = Field(default="", description="Reason for correction")
    corrected_by: str = Field(default="", description="User making correction")
    rfc_emisor: str = Field(default="", description="Issuer RFC for learning")
    tenant_id: str = Field(default="")


class SuggestionsResponse(BaseModel):
    """Response with classification suggestions."""
    suggestions: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_bookkeeping_router(
    db=None,
    require_api_key=None,
    erp_system: ERPSystem = ERPSystem.MOCK,
) -> APIRouter:
    """Build the bookkeeping agent router.

    Args:
        db: Database instance (unused for now, kept for pattern consistency)
        require_api_key: Auth dependency
        erp_system: ERP system to use

    Returns:
        FastAPI APIRouter
    """
    router = APIRouter(
        prefix="/api/v1/bookkeeping",
        tags=["bookkeeping"],
    )

    # SECURITY: Require API key on ALL bookkeeping endpoints.
    if require_api_key is not None:
        router.dependencies.append(Depends(require_api_key))

    # Shared components (in production, inject via DI)
    classifier = AutoClassifier()
    rules = AccountingRulesEngine()
    journal_gen = JournalEntryGenerator(rules)
    erp = ERPRegistrar(erp_system=erp_system)
    overrides = HumanOverrideManager()
    orchestrator = PipelineOrchestrator(
        classifier=classifier,
        rules_engine=rules,
        journal_generator=journal_gen,
        erp_registrar=erp,
        override_manager=overrides,
    )

    # Lazy-train classifier on first use (not on startup)
    # classifier.train() is now called automatically on first predict()
    try:
        classifier._lazy_train = True
    except Exception:
        pass  # Graceful if sklearn not available

    # -----------------------------------------------------------------------
    # POST /bookkeeping/process
    # -----------------------------------------------------------------------
    @router.post(
        "/process",
        summary="Process CFDIs through the bookkeeping pipeline",
    )
    async def process_cfdis(request: ProcessRequest):
        """Process a batch of CFDIs through the full bookkeeping pipeline:
        CFDI → classification → journal entry → ERP registration.

        Returns the pipeline job with all results.
        """
        if not request.cfdis:
            raise HTTPException(400, "At least one CFDI is required")

        job = orchestrator.process_cfdis(
            cfdis=request.cfdis,
            tenant_id=request.tenant_id,
            periodo=request.periodo,
            fecha=request.fecha,
            auto_register_erp=request.auto_register_erp,
        )

        return {
            "job_id": job.job_id,
            "stage": job.stage.value,
            "progress_pct": job.progress_pct,
            "classifications": [c.model_dump() for c in job.classifications],
            "polizas": [p.model_dump() for p in job.polizas],
            "erp_references": job.erp_references,
            "overrides_needed": job.overrides_needed,
            "errors": job.errors,
        }

    # -----------------------------------------------------------------------
    # GET /bookkeeping/status
    # -----------------------------------------------------------------------
    @router.get(
        "/status",
        summary="Get bookkeeping pipeline status",
    )
    async def get_status(
        tenant_id: str = Query(default="", description="Filter by tenant"),
        job_id: Optional[str] = Query(default=None, description="Specific job ID"),
    ):
        """Get pipeline status. If job_id is provided, returns that job's
        details. Otherwise returns overall pipeline status.
        """
        if job_id:
            job = orchestrator.get_job(job_id)
            if not job:
                raise HTTPException(404, f"Job {job_id} not found")
            return {
                "job_id": job.job_id,
                "stage": job.stage.value,
                "progress_pct": job.progress_pct,
                "classifications_count": len(job.classifications),
                "polizas_count": len(job.polizas),
                "erp_references": job.erp_references,
                "overrides_needed": job.overrides_needed,
                "errors": job.errors,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }

        return orchestrator.get_pipeline_status(tenant_id)

    # -----------------------------------------------------------------------
    # POST /bookkeeping/override
    # -----------------------------------------------------------------------
    @router.post(
        "/override",
        summary="Submit a human override for a CFDI classification",
    )
    async def submit_override(request: OverrideRequest):
        """Allow a human accountant to correct the agent's classification.

        The agent learns from feedback: repeated corrections for the same
        RFC improve future predictions.
        """
        record = overrides.submit_override(
            cfdi_uuid=request.cfdi_uuid,
            action=request.action,
            new_categoria=request.new_categoria,
            new_cuenta_cargo=request.new_cuenta_cargo,
            new_cuenta_abono=request.new_cuenta_abono,
            original_categoria=request.original_categoria,
            reason=request.reason,
            corrected_by=request.corrected_by,
            rfc_emisor=request.rfc_emisor,
            tenant_id=request.tenant_id,
        )

        # Learn from the override
        if request.rfc_emisor and request.new_categoria:
            classifier.add_override(request.rfc_emisor, request.new_categoria)

        return {
            "override_id": record.id,
            "cfdi_uuid": record.cfdi_uuid,
            "action": record.action.value,
            "new_categoria": record.new_categoria,
            "timestamp": record.timestamp.isoformat(),
            "learned": bool(request.rfc_emisor and request.new_categoria),
        }

    # -----------------------------------------------------------------------
    # GET /bookkeeping/suggestions
    # -----------------------------------------------------------------------
    @router.get(
        "/suggestions",
        summary="Get CFDIs needing human review with suggestions",
    )
    async def get_suggestions(
        tenant_id: str = Query(default="", description="Filter by tenant"),
    ):
        """Get CFDIs that the agent couldn't classify with high confidence,
        along with alternative suggestions.
        """
        suggestions = orchestrator.get_suggestions(tenant_id)
        # Also include RFC-level feedback suggestions
        retraining_suggestions = overrides.get_suggestions_for_retraining()

        return {
            "pending_review": [s.model_dump() for s in suggestions],
            "retraining_suggestions": retraining_suggestions,
            "total_pending": len(suggestions),
        }

    return router
