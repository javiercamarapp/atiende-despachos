# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Bank Reconciliation API.

Endpoints:
    POST /api/v1/conciliacion/match        — Upload bank CSV + CFDI list, returns matches
    GET  /api/v1/conciliacion/report/{period} — Get reconciliation report for a period
    GET  /api/v1/conciliacion/discrepancies  — List discrepancies
    POST /api/v1/conciliacion/export         — Export reconciliation to CSV

The router is built with `build_conciliacion_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.conciliacion.models import (
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    MatchResult,
)
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.validators import (
    validate_bank_statement,
    validate_cfdi_for_conciliation,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class MatchRequest(BaseModel):
    """Request to match bank transactions with CFDI references."""
    bank_transactions: List[dict] = Field(
        default_factory=list,
        description="List of bank transaction dicts (id, date, amount, type, reference, bank_account)",
    )
    cfdi_list: List[dict] = Field(
        default_factory=list,
        description="List of CFDI reference dicts (uuid, fecha, rfc_emisor, rfc_receptor, total, tipo_comprobante)",
    )
    date_tolerance_days: int = Field(
        default=3,
        ge=0,
        le=30,
        description="Days of tolerance for date-based matching",
    )


class ExportRequest(BaseModel):
    """Request to export reconciliation results to CSV."""
    period: str = Field(..., description="Period (YYYY-MM)")
    matches: List[dict] = Field(
        default_factory=list,
        description="Match results to export",
    )
    bank_transactions: List[dict] = Field(
        default_factory=list,
        description="Original bank transactions (for discrepancy calculation)",
    )
    cfdi_list: List[dict] = Field(
        default_factory=list,
        description="Original CFDI references (for discrepancy calculation)",
    )


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_conciliacion_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the conciliación bancaria API router.

    Parameters
    ----------
    db : Database instance (unused for now; matching is in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    auth_dep = require_api_key or (lambda: None)

    # In-memory store for reports (keyed by period)
    _reports_store: dict[str, ConciliationReport] = {}
    _discrepancies_store: dict[str, list] = {}

    router = APIRouter(prefix="/api/v1/conciliacion", tags=["conciliacion"])

    # -- Match bank transactions with CFDI --------------------------------
    @router.post(
        "/match",
        summary="Match bank transactions with CFDI references.",
        response_model=None,
    )
    def match_transactions(
        req: MatchRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Upload bank transactions and CFDI list, run matching algorithm,
        and return match results with confidence scores."""
        # Validate bank transactions
        is_valid_bank, bank_errors = validate_bank_statement(req.bank_transactions)
        if not is_valid_bank:
            raise HTTPException(
                status_code=422,
                detail=f"Errores en datos bancarios: {'; '.join(bank_errors)}",
            )

        # Validate CFDI
        is_valid_cfdi, cfdi_errors = validate_cfdi_for_conciliation(req.cfdi_list)
        if not is_valid_cfdi:
            raise HTTPException(
                status_code=422,
                detail=f"Errores en datos CFDI: {'; '.join(cfdi_errors)}",
            )

        # Convert dicts to models
        try:
            bank_txns = [BankTransaction(**t) for t in req.bank_transactions]
            cfdi_list = [CFDIReference(**c) for c in req.cfdi_list]
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al convertir datos: {type(e).__name__}: {e}",
            )

        # Run matching
        service = ConciliationService(
            date_tolerance_days=req.date_tolerance_days,
        )
        matches = service.match_transactions(bank_txns, cfdi_list)

        # Detect discrepancies
        discrepancies = service.find_discrepancies(
            matches, bank_txns, cfdi_list,
        )

        # Generate report (store it)
        report = service.generate_report(matches)
        # Determine period from first bank txn date or use current month
        if bank_txns:
            period = bank_txns[0].date[:7]  # YYYY-MM
        else:
            period = "unknown"
        report = service.generate_report(matches, period=period)
        _reports_store[period] = report
        _discrepancies_store[period] = discrepancies

        return {
            "ok": True,
            "period": period,
            "total_transactions": len(bank_txns),
            "total_cfdi": len(cfdi_list),
            "matches": [m.model_dump() for m in matches],
            "discrepancies": discrepancies,
            "report": report.model_dump(),
        }

    # -- Upload bank CSV for matching --------------------------------------
    @router.post(
        "/match/csv",
        summary="Upload a bank statement CSV file for matching.",
        response_model=None,
    )
    async def match_from_csv(
        file: UploadFile = File(...),
        cfdi_json: str = Query(default="[]", description="CFDI list as JSON string"),
        date_tolerance_days: int = Query(default=3, ge=0, le=30),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Upload a bank statement CSV and match against provided CFDI list.
        CSV should have columns: id, date, description, amount, type, reference, bank_account."""
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo CSV vacío.")

        try:
            text = content.decode("utf-8-sig")  # Handle BOM
            reader = csv.DictReader(io.StringIO(text))
            bank_transactions = list(reader)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear CSV: {type(e).__name__}: {e}",
            )

        # Parse CFDI list from JSON string
        try:
            cfdi_list = json.loads(cfdi_json) if isinstance(cfdi_json, str) else cfdi_json
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(
                status_code=422,
                detail="cfdi_json debe ser un JSON válido.",
            )

        # Convert amount to float
        for txn in bank_transactions:
            try:
                txn["amount"] = float(txn.get("amount", 0))
            except (ValueError, TypeError):
                txn["amount"] = 0.0

        # Validate
        is_valid_bank, bank_errors = validate_bank_statement(bank_transactions)
        if not is_valid_bank:
            raise HTTPException(
                status_code=422,
                detail=f"Errores en CSV bancario: {'; '.join(bank_errors)}",
            )

        is_valid_cfdi, cfdi_errors = validate_cfdi_for_conciliation(cfdi_list)
        if not is_valid_cfdi:
            raise HTTPException(
                status_code=422,
                detail=f"Errores en datos CFDI: {'; '.join(cfdi_errors)}",
            )

        try:
            bank_txns = [BankTransaction(**t) for t in bank_transactions]
            cfdi_refs = [CFDIReference(**c) for c in cfdi_list]
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al convertir datos: {type(e).__name__}: {e}",
            )

        service = ConciliationService(date_tolerance_days=date_tolerance_days)
        matches = service.match_transactions(bank_txns, cfdi_refs)
        discrepancies = service.find_discrepancies(matches, bank_txns, cfdi_refs)

        period = bank_txns[0].date[:7] if bank_txns else "unknown"
        report = service.generate_report(matches, period=period)
        _reports_store[period] = report
        _discrepancies_store[period] = discrepancies

        return {
            "ok": True,
            "period": period,
            "total_transactions": len(bank_txns),
            "matches": [m.model_dump() for m in matches],
            "discrepancies": discrepancies,
            "report": report.model_dump(),
        }

    # -- Get report by period ----------------------------------------------
    @router.get(
        "/report/{period}",
        summary="Get reconciliation report for a period.",
        response_model=None,
    )
    def get_report(
        period: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve a previously generated reconciliation report by period (YYYY-MM)."""
        if period not in _reports_store:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró reporte para el período '{period}'.",
            )
        return {"report": _reports_store[period].model_dump()}

    # -- List discrepancies ------------------------------------------------
    @router.get(
        "/discrepancies",
        summary="List all discrepancies across all periods.",
        response_model=None,
    )
    def list_discrepancies(
        auth_info: dict = Depends(auth_dep),
        period: Optional[str] = Query(default=None, description="Filter by period"),
        min_variance: float = Query(default=2.0, ge=0, description="Minimum variance % to include"),
    ) -> dict:
        """List discrepancy records with optional period and variance filters."""
        all_discs = []
        for p, discs in _discrepancies_store.items():
            if period and p != period:
                continue
            for d in discs:
                if d.get("variance", 0) >= min_variance:
                    all_discs.append({**d, "period": p})
        return {"count": len(all_discs), "discrepancies": all_discs}

    # -- Export to CSV -----------------------------------------------------
    @router.post(
        "/export",
        summary="Export reconciliation results to CSV.",
        response_model=None,
    )
    def export_csv(
        req: ExportRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Export match results and discrepancies to CSV format."""
        try:
            matches = [MatchResult(**m) for m in req.matches]
            bank_txns = [BankTransaction(**t) for t in req.bank_transactions]
            cfdi_list = [CFDIReference(**c) for c in req.cfdi_list]
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al convertir datos: {type(e).__name__}: {e}",
            )

        service = ConciliationService()
        report = service.generate_report(matches, period=req.period)
        discrepancies = service.find_discrepancies(matches, bank_txns, cfdi_list)
        csv_content = service.export_csv(report, discrepancies)

        return {
            "ok": True,
            "csv": csv_content,
            "period": req.period,
        }

    # -- Export as downloadable file ---------------------------------------
    @router.post(
        "/export/download",
        summary="Download reconciliation CSV as a file.",
    )
    def export_download(
        req: ExportRequest,
        auth_info: dict = Depends(auth_dep),
    ):
        """Download the CSV export as a file attachment."""
        try:
            matches = [MatchResult(**m) for m in req.matches]
            bank_txns = [BankTransaction(**t) for t in req.bank_transactions]
            cfdi_list = [CFDIReference(**c) for c in req.cfdi_list]
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al convertir datos: {type(e).__name__}: {e}",
            )

        service = ConciliationService()
        report = service.generate_report(matches, period=req.period)
        discrepancies = service.find_discrepancies(matches, bank_txns, cfdi_list)
        csv_content = service.export_csv(report, discrepancies)

        filename = f"conciliacion_{req.period}.csv"
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
