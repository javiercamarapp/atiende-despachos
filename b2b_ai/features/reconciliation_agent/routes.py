# -*- coding: utf-8 -*-
"""
routes.py — API endpoints for the Reconciliation Agent.

Endpoints:
    POST /api/v1/reconcile/upload   Upload bank statement + auto-reconcile
    GET  /api/v1/reconcile/status   Get reconciliation status/result
    POST /api/v1/reconcile/approve  Approve/reject individual matches

Extends the existing b2b_ai.api.reconciliation router with new capabilities.

State is stored in the database (reconciliation_jobs table) instead of an
in-memory dict, so jobs survive restarts and work across multiple workers.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel

from b2b_ai.features.reconciliation_agent.models import (
    ApprovalRequest,
    BancoMX,
    BankFormat,
    ReconciliationResult,
    ReconciliationStatus,
    UploadRequest,
)
from b2b_ai.features.reconciliation_agent.parsers import BankStatementParser
from b2b_ai.features.reconciliation_agent.matching_engine import MatchingEngine
from b2b_ai.features.reconciliation_agent.alerts import AlertEngine


def _job_to_status(row: dict) -> ReconciliationStatus:
    """Reconstruct a ReconciliationStatus from a DB row."""
    result = None
    if row.get("result_json"):
        try:
            result = ReconciliationResult.model_validate_json(row["result_json"])
        except Exception:
            result = None
    return ReconciliationStatus(
        job_id=row["job_id"],
        status=row["status"],
        progress=row.get("progress", 0.0) or 0.0,
        result=result,
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
        error=row.get("error"),
        bank=row.get("bank", "generic"),
        format=row.get("format", "csv"),
        filename=row.get("filename", ""),
    )


class ReconcileAgentRouter:
    """Builder for the reconciliation agent API router.

    Usage:
        router_builder = ReconcileAgentRouter(db=db, require_api_key=auth)
        router = router_builder.build()
        app.include_router(router)
    """

    def __init__(self, db=None, require_api_key=None):
        self.db = db
        if require_api_key is None:
            raise ValueError(
                "require_api_key es obligatorio. "
                "Nunca construir el router sin dependencia de auth."
            )
        self.require_api_key = require_api_key

    def build(self) -> APIRouter:
        router = APIRouter(
            prefix="/api/v1/reconcile",
            tags=["reconcile-agent"],
        )

        def _scope(auth_info) -> Optional[int]:
            return auth_info.get("tenant_id") if auth_info else None

        # -- upload + auto-reconcile ----------------------------------------
        @router.post(
            "/upload",
            summary="Upload bank statement and run auto-reconciliation",
        )
        async def reconcile_upload(
            auth_info: dict = Depends(self.require_api_key),
            file: UploadFile = File(...),
            bank: str = Form("generic"),
            format: Optional[str] = Form(None),
            date_tolerance_days: int = Form(3),
            monto_tolerance_pct: float = Form(5.0),
            fuzzy_threshold: int = Form(80),
            enable_llm: bool = Form(False),
        ):
            """Upload a bank statement (CSV, OFX, QIF, MT940, PDF) and
            automatically reconcile against book records.

            Returns a job_id to poll via GET /reconcile/status.
            """
            tenant = _scope(auth_info)

            # Validate bank
            bank_norm = bank.strip().lower()
            valid_banks = [b.value for b in BancoMX]
            if bank_norm not in valid_banks:
                bank_norm = "generic"

            # Validate format
            fmt = format.lower() if format else None
            valid_fmts = [f.value for f in BankFormat]
            if fmt and fmt not in valid_fmts:
                raise HTTPException(400, f"Formato no soportado: {fmt}")

            # Save uploaded file
            suffix = os.path.splitext(file.filename or "")[1].lower() or ".csv"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name

            try:
                # Parse
                parser = BankStatementParser()
                movements = parser.parse(tmp_path, bank=bank_norm, format_hint=fmt)

                # Get book records from DB
                book_records = []
                if self.db and tenant:
                    try:
                        invoices = self.db.list_invoices(tenant_id=tenant) or []
                        for inv in invoices:
                            book_records.append({
                                "fecha": str(inv.get("fecha", ""))[:10],
                                "monto": inv.get("total"),
                                "total": inv.get("total"),
                                "descripcion": inv.get("descripcion", ""),
                                "referencia": inv.get("folio_fiscal", ""),
                                "folio_fiscal": inv.get("folio_fiscal", ""),
                                "emisor": inv.get("emisor_nombre", ""),
                            })
                    except Exception:
                        pass  # DB not available, reconcile without book records

                # Match
                engine = MatchingEngine(
                    date_tolerance_days=date_tolerance_days,
                    monto_tolerance_pct=monto_tolerance_pct,
                    fuzzy_threshold=fuzzy_threshold,
                    enable_llm=enable_llm,
                )
                result = engine.match(movements, book_records)

                # Generate alerts
                alert_engine = AlertEngine()
                alerts = alert_engine.generate_alerts(result)
                result.alerts = [a.model_dump() for a in alerts]

                # Store job in DB
                job_id = str(uuid.uuid4())[:12]
                result_json = result.model_dump_json()

                if self.db:
                    try:
                        self.db.create_reconciliation_job(
                            job_id, tenant, bank=bank_norm,
                            fmt=fmt or suffix.lstrip("."),
                            filename=file.filename or "",
                        )
                        self.db.update_reconciliation_job(
                            job_id, status="completed",
                            progress=100.0, result_json=result_json,
                        )
                    except Exception:
                        pass  # Non-critical — job still returns to caller

                # Persist movements to DB if available
                if self.db and tenant:
                    try:
                        for mov in movements:
                            self.db.add_bank_transactions(
                                tenant,
                                [{
                                    "fecha": mov.fecha,
                                    "monto": str(mov.monto),
                                    "descripcion": mov.descripcion,
                                    "ref": mov.referencia or "",
                                    "id": f"agent1_{job_id}_{mov.fecha}",
                                }],
                                banco=bank_norm,
                                filename=file.filename or "",
                            )
                        self.db.log_call(
                            "reconcile-agent", "upload",
                            entity="statement",
                            entity_id=file.filename,
                            payload={
                                "bank": bank_norm,
                                "format": fmt,
                                "movements": len(movements),
                                "matched": result.total_matched,
                            },
                            status="ok",
                            tenant_id=tenant,
                        )
                    except Exception:
                        pass  # Non-critical

                return {
                    "ok": True,
                    "job_id": job_id,
                    "movements_parsed": len(movements),
                    "matched": result.total_matched,
                    "unmatched_bank": len(result.unmatched_bank),
                    "unmatched_books": len(result.unmatched_books),
                    "confidence": result.confidence,
                    "match_rate": result.match_rate,
                    "alerts_count": len(result.alerts),
                    "processing_time_ms": result.processing_time_ms,
                }

            except ValueError as e:
                raise HTTPException(400, str(e))
            except Exception as e:
                raise HTTPException(500, f"Error procesando archivo: {e}")
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        # -- status ----------------------------------------------------------
        @router.get(
            "/status",
            summary="Get reconciliation status and results",
        )
        async def reconcile_status(
            job_id: str = Query(..., description="Job ID from upload"),
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Get the status and results of a reconciliation job.

            Returns the full reconciliation result including matches,
            unmatched items, and alerts.
            """
            tenant = _scope(auth_info)

            if self.db:
                row = self.db.get_reconciliation_job(job_id, tenant_id=tenant)
                if row is None:
                    raise HTTPException(404, f"Job {job_id} no encontrado")
                status = _job_to_status(row)
            else:
                raise HTTPException(404, f"Job {job_id} no encontrado")

            data = status.model_dump()
            # Include result summary if completed
            if status.result:
                data["summary"] = {
                    "total_movements": status.result.total_movements,
                    "total_records": status.result.total_records,
                    "total_matched": status.result.total_matched,
                    "match_rate": status.result.match_rate,
                    "confidence": status.result.confidence,
                    "monto_matched": status.result.monto_matched,
                    "monto_unmatched_bank": status.result.monto_unmatched_bank,
                    "monto_unmatched_books": status.result.monto_unmatched_books,
                    "alerts_count": len(status.result.alerts),
                }
                # Include matches with details
                data["matches"] = [m.model_dump() for m in status.result.matched]
                # Include unmatched summaries
                data["unmatched_bank_count"] = len(status.result.unmatched_bank)
                data["unmatched_books_count"] = len(status.result.unmatched_books)
                # Include alerts
                data["alerts"] = status.result.alerts

            return data

        # -- approve ---------------------------------------------------------
        @router.post(
            "/approve",
            summary="Approve or reject a reconciliation match",
        )
        async def reconcile_approve(
            req: ApprovalRequest,
            auth_info: dict = Depends(self.require_api_key),
        ):
            """Approve or reject a specific match in a reconciliation job.

            Approved matches are persisted to the database.
            """
            tenant = _scope(auth_info)

            if self.db:
                row = self.db.get_reconciliation_job(req.job_id, tenant_id=tenant)
                if row is None:
                    raise HTTPException(404, f"Job {req.job_id} no encontrado")
                status = _job_to_status(row)
            else:
                raise HTTPException(404, f"Job {req.job_id} no encontrado")

            if status.result is None:
                raise HTTPException(400, "El job aún no tiene resultados")
            if req.match_idx < 0 or req.match_idx >= len(status.result.matched):
                raise HTTPException(400, f"Índice de match inválido: {req.match_idx}")

            match = status.result.matched[req.match_idx]

            if req.approved:
                # Persist to DB
                if self.db and tenant:
                    try:
                        self.db.set_bank_confirmation(
                            tenant,
                            f"agent1_{req.job_id}_{match.movement_idx}",
                            str(match.registro_idx),
                        )
                        self.db.log_call(
                            "reconcile-agent", "approve",
                            entity="match",
                            entity_id=f"{req.job_id}:{req.match_idx}",
                            payload={
                                "level": match.level.value,
                                "score": match.score,
                                "notes": req.notes,
                            },
                            status="approved",
                            tenant_id=tenant,
                        )
                    except Exception:
                        pass

                return {
                    "ok": True,
                    "action": "approved",
                    "match": match.model_dump(),
                    "notes": req.notes,
                }
            else:
                # Rejected: move to unmatched
                if self.db and tenant:
                    try:
                        self.db.log_call(
                            "reconcile-agent", "reject",
                            entity="match",
                            entity_id=f"{req.job_id}:{req.match_idx}",
                            payload={"notes": req.notes},
                            status="rejected",
                            tenant_id=tenant,
                        )
                    except Exception:
                        pass

                return {
                    "ok": True,
                    "action": "rejected",
                    "match_idx": req.match_idx,
                    "notes": req.notes,
                }

        return router


def build_reconcile_agent_router(db=None, require_api_key=None) -> APIRouter:
    """Convenience function to build the reconcile agent router."""
    builder = ReconcileAgentRouter(db=db, require_api_key=require_api_key)
    return builder.build()
