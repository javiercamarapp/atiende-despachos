# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Bank Reconciliation API.

Endpoints:
    POST /api/v1/conciliacion/upload              — Upload bank statement (CSV/OFX)
    POST /api/v1/conciliacion/match               — Run matching algorithm
    POST /api/v1/conciliacion/match/csv           — Upload CSV + match
    GET  /api/v1/conciliacion/report/{period}     — Get reconciliation report
    POST /api/v1/conciliacion/apply               — Apply approved adjustments
    GET  /api/v1/conciliacion/discrepancies       — List discrepancies
    POST /api/v1/conciliacion/export              — Export to CSV
    POST /api/v1/conciliacion/export/download     — Download CSV file

The router is built with `build_conciliacion_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.conciliacion.models import (
    Adjustment,
    AdjustmentStatus,
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    Discrepancy,
    MatchResult,
    PolizaContable,
)
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.validators import (
    validate_bank_statement,
    validate_cfdi_for_conciliation,
    validate_polizas_contables,
    validate_reconciliation_data,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class MatchRequest(BaseModel):
    """Request to match bank transactions with CFDI references or polizas."""
    bank_transactions: List[dict] = Field(
        default_factory=list,
        description="List of bank transaction dicts (id, date, amount, type, reference, bank_account)",
    )
    cfdi_list: List[dict] = Field(
        default_factory=list,
        description="List of CFDI reference dicts (uuid, fecha, rfc_emisor, rfc_receptor, total, tipo_comprobante)",
    )
    polizas: Optional[List[dict]] = Field(
        default=None,
        description="Optional list of poliza contable dicts (id, fecha, monto, descripcion, cuenta, concepto, referencia, rfc)",
    )
    date_tolerance_days: int = Field(
        default=3,
        ge=0,
        le=30,
        description="Days of tolerance for date-based matching",
    )


class ReconcileRequest(BaseModel):
    """Full reconciliation request with bank transactions, polizas, and/or CFDI."""
    bank_transactions: List[dict] = Field(
        default_factory=list,
        description="Bank statement transactions",
    )
    polizas: Optional[List[dict]] = Field(
        default=None,
        description="Accounting entries (polizas contables)",
    )
    cfdi_list: Optional[List[dict]] = Field(
        default=None,
        description="CFDI references",
    )
    tolerance_days: int = Field(
        default=3,
        ge=0,
        le=30,
        description="Date tolerance in days for matching",
    )
    period: str = Field(
        default="",
        description="Period string (YYYY-MM). Auto-detected if empty.",
    )


class ApplyAdjustmentsRequest(BaseModel):
    """Request to apply approved adjustments."""
    adjustment_ids: List[str] = Field(
        ...,
        description="List of adjustment IDs to apply",
    )
    applied_by: str = Field(
        default="system",
        description="User or system applying the adjustments",
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
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # In-memory stores
    _reports_store: Dict[str, ConciliationReport] = {}
    _discrepancies_store: Dict[str, list] = {}
    _reconciliation_results_store: Dict[str, dict] = {}
    _adjustments_store: Dict[str, Adjustment] = {}
    _uploaded_statements: Dict[str, dict] = {}

    router = APIRouter(prefix="/api/v1/conciliacion", tags=["conciliacion"])

    # -----------------------------------------------------------------------
    # POST /upload — Upload bank statement (CSV/OFX)
    # -----------------------------------------------------------------------
    @router.post(
        "/upload",
        summary="Upload a bank statement file (CSV) for reconciliation.",
        response_model=None,
    )
    async def upload_bank_statement(
        file: UploadFile = File(...),
        period: Optional[str] = Query(default=None, description="Period (YYYY-MM). Auto-detected from data."),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Upload a bank statement CSV file. CSV should have columns:
        id, date, description, amount, type, reference, bank_account."""
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            text = content.decode("utf-8-sig")  # Handle BOM
            reader = csv.DictReader(io.StringIO(text))
            bank_transactions = list(reader)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear CSV: {type(e).__name__}: {e}",
            )

        if not bank_transactions:
            raise HTTPException(status_code=422, detail="CSV no contiene transacciones.")

        # Convert amount to float
        for txn in bank_transactions:
            try:
                txn["amount"] = float(txn.get("amount", 0))
            except (ValueError, TypeError):
                txn["amount"] = 0.0

        # Validate
        is_valid, errors = validate_bank_statement(bank_transactions)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Errores en datos bancarios: {'; '.join(errors)}",
            )

        # Determine period
        if not period:
            try:
                first_date = bank_transactions[0].get("date", "")
                period = first_date[:7] if first_date else datetime.now().strftime("%Y-%m")
            except (IndexError, ValueError):
                period = datetime.now().strftime("%Y-%m")

        # Store the uploaded statement
        statement_id = f"stmt-{period}-{len(_uploaded_statements) + 1}"
        _uploaded_statements[statement_id] = {
            "id": statement_id,
            "period": period,
            "transactions": bank_transactions,
            "uploaded_at": datetime.now().isoformat(),
            "file_name": file.filename,
            "transaction_count": len(bank_transactions),
        }

        return {
            "ok": True,
            "statement_id": statement_id,
            "period": period,
            "transaction_count": len(bank_transactions),
            "file_name": file.filename,
        }

    # -----------------------------------------------------------------------
    # POST /match — Run matching algorithm
    # -----------------------------------------------------------------------
    @router.post(
        "/match",
        summary="Match bank transactions with polizas and/or CFDI references.",
        response_model=None,
    )
    def match_transactions(
        req: MatchRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Upload bank transactions and polizas/CFDI list, run matching algorithm,
        and return match results with confidence scores."""
        # Validate bank transactions
        is_valid_bank, bank_errors = validate_bank_statement(req.bank_transactions)
        if not is_valid_bank:
            raise HTTPException(
                status_code=422,
                detail=f"Errores en datos bancarios: {'; '.join(bank_errors)}",
            )

        # Validate CFDI if provided
        if req.cfdi_list:
            is_valid_cfdi, cfdi_errors = validate_cfdi_for_conciliation(req.cfdi_list)
            if not is_valid_cfdi:
                raise HTTPException(
                    status_code=422,
                    detail=f"Errores en datos CFDI: {'; '.join(cfdi_errors)}",
                )

        # Validate polizas if provided
        if req.polizas:
            is_valid_pol, pol_errors = validate_polizas_contables(req.polizas)
            if not is_valid_pol:
                raise HTTPException(
                    status_code=422,
                    detail=f"Errores en pólizas: {'; '.join(pol_errors)}",
                )

        # Convert dicts to models
        try:
            bank_txns = [BankTransaction(**t) for t in req.bank_transactions]
            cfdi_list = [CFDIReference(**c) for c in req.cfdi_list] if req.cfdi_list else []
            polizas = [PolizaContable(**p) for p in req.polizas] if req.polizas else []
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al convertir datos: {type(e).__name__}: {e}",
            )

        # Run matching
        service = ConciliationService(
            date_tolerance_days=req.date_tolerance_days,
        )

        # Match against polizas
        poliza_matches = []
        if polizas:
            poliza_matches = service.match_transactions_to_polizas(bank_txns, polizas)

        # Match against CFDI
        cfdi_matches = []
        if cfdi_list:
            cfdi_matches = service.match_transactions(bank_txns, cfdi_list)

        # Detect discrepancies
        discrepancies = []
        if polizas:
            discrepancies = service.identify_discrepancies(
                poliza_matches, bank_txns, polizas
            )
        elif cfdi_list:
            # Legacy discrepancy detection
            disc_dicts = service.find_discrepancies(cfdi_matches, bank_txns, cfdi_list)
            discrepancies = disc_dicts

        # Generate report (store it)
        if bank_txns:
            period = bank_txns[0].date[:7]  # YYYY-MM
        else:
            period = "unknown"

        all_matches = poliza_matches + cfdi_matches
        report = service.generate_report(all_matches, period=period)
        _reports_store[period] = report
        _discrepancies_store[period] = discrepancies

        return {
            "ok": True,
            "period": period,
            "total_transactions": len(bank_txns),
            "total_cfdi": len(cfdi_list),
            "total_polizas": len(polizas),
            "matches": [m.model_dump() for m in poliza_matches],
            "cfdi_matches": [m.model_dump() for m in cfdi_matches],
            "discrepancies": [d.model_dump() if hasattr(d, 'model_dump') else d for d in discrepancies],
            "report": report.model_dump(),
        }

    # -----------------------------------------------------------------------
    # POST /match/csv — Upload CSV and match
    # -----------------------------------------------------------------------
    @router.post(
        "/match/csv",
        summary="Upload a bank statement CSV file for matching.",
        response_model=None,
    )
    async def match_from_csv(
        file: UploadFile = File(...),
        cfdi_json: str = Query(default="[]", description="CFDI list as JSON string"),
        polizas_json: Optional[str] = Query(default=None, description="Polizas list as JSON string"),
        date_tolerance_days: int = Query(default=3, ge=0, le=30),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Upload a bank statement CSV and match against provided CFDI/polizas.
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

        # Parse polizas from JSON string
        polizas_list = []
        if polizas_json:
            try:
                polizas_list = json.loads(polizas_json) if isinstance(polizas_json, str) else polizas_json
            except (json.JSONDecodeError, TypeError):
                raise HTTPException(
                    status_code=422,
                    detail="polizas_json debe ser un JSON válido.",
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

        if cfdi_list:
            is_valid_cfdi, cfdi_errors = validate_cfdi_for_conciliation(cfdi_list)
            if not is_valid_cfdi:
                raise HTTPException(
                    status_code=422,
                    detail=f"Errores en datos CFDI: {'; '.join(cfdi_errors)}",
                )

        if polizas_list:
            is_valid_pol, pol_errors = validate_polizas_contables(polizas_list)
            if not is_valid_pol:
                raise HTTPException(
                    status_code=422,
                    detail=f"Errores en pólizas: {'; '.join(pol_errors)}",
                )

        try:
            bank_txns = [BankTransaction(**t) for t in bank_transactions]
            cfdi_refs = [CFDIReference(**c) for c in cfdi_list] if cfdi_list else []
            polizas = [PolizaContable(**p) for p in polizas_list] if polizas_list else []
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

    # -----------------------------------------------------------------------
    # POST /reconcile — Full reconciliation pipeline
    # -----------------------------------------------------------------------
    @router.post(
        "/reconcile",
        summary="Run full bank reconciliation with polizas and/or CFDI.",
        response_model=None,
    )
    def reconcile(
        req: ReconcileRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Full reconciliation: match, detect discrepancies, propose adjustments."""
        # Validate
        is_valid, errors = validate_reconciliation_data(
            req.bank_transactions, req.polizas, req.cfdi_list
        )
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Errores de validación: {'; '.join(errors)}",
            )

        # Convert to models
        try:
            bank_txns = [BankTransaction(**t) for t in req.bank_transactions]
            polizas = [PolizaContable(**p) for p in req.polizas] if req.polizas else []
            cfdi_list = [CFDIReference(**c) for c in req.cfdi_list] if req.cfdi_list else []
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al convertir datos: {type(e).__name__}: {e}",
            )

        # Run full reconciliation
        service = ConciliationService()
        results = service.reconcile_bank_statement(
            transactions=bank_txns,
            polizas=polizas if polizas else None,
            cfdi_list=cfdi_list if cfdi_list else None,
            tolerance_days=req.tolerance_days,
        )

        # Determine period
        period = req.period
        if not period and bank_txns:
            period = bank_txns[0].date[:7]
        elif not period:
            period = datetime.now().strftime("%Y-%m")

        # Generate report
        report = service.generate_reconciliation_report(results, period=period)
        _reports_store[period] = report
        _reconciliation_results_store[period] = results

        # Store adjustments
        for adj in results.get("adjustments", []):
            _adjustments_store[adj.id] = adj

        # Store discrepancies
        disc_dicts = []
        for d in results.get("discrepancies", []):
            disc_dicts.append(d.model_dump() if hasattr(d, 'model_dump') else d)
        _discrepancies_store[period] = disc_dicts

        return {
            "ok": True,
            "period": period,
            "report": report.model_dump(),
            "summary": {
                "total_transactions": report.total_transactions,
                "matched": report.matched,
                "unmatched": report.unmatched,
                "discrepancies": report.discrepancies,
                "match_rate": report.match_rate,
                "adjustments_proposed": report.adjustments_proposed,
                "total_variance": report.total_variance,
            },
        }

    # -----------------------------------------------------------------------
    # GET /report/{period} — Get reconciliation report
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # POST /apply — Apply approved adjustments
    # -----------------------------------------------------------------------
    @router.post(
        "/apply",
        summary="Apply approved reconciliation adjustments.",
        response_model=None,
    )
    def apply_adjustments(
        req: ApplyAdjustmentsRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Apply approved adjustments. Updates status to APPLIED."""
        applied = []
        not_found = []
        already_applied = []

        for adj_id in req.adjustment_ids:
            if adj_id not in _adjustments_store:
                not_found.append(adj_id)
                continue

            adj = _adjustments_store[adj_id]
            if adj.status == AdjustmentStatus.APPLIED:
                already_applied.append(adj_id)
                continue

            if adj.status not in (AdjustmentStatus.PROPOSED, AdjustmentStatus.APPROVED):
                continue

            # Apply the adjustment
            adj.status = AdjustmentStatus.APPLIED
            adj.applied_by = req.applied_by
            adj.applied_at = datetime.now().isoformat()
            _adjustments_store[adj_id] = adj
            applied.append(adj_id)

        return {
            "ok": True,
            "applied": applied,
            "not_found": not_found,
            "already_applied": already_applied,
            "total_applied": len(applied),
        }

    # -----------------------------------------------------------------------
    # GET /discrepancies — List discrepancies
    # -----------------------------------------------------------------------
    @router.get(
        "/discrepancies",
        summary="List all discrepancies across all periods.",
        response_model=None,
    )
    def list_discrepancies(
        auth_info: dict = Depends(auth_dep),
        period: Optional[str] = Query(default=None, description="Filter by period"),
        discrepancy_type: Optional[str] = Query(default=None, description="Filter by type: monto, fecha, faltante, sobrante, duplicado"),
        min_variance: float = Query(default=0.0, ge=0, description="Minimum variance % to include"),
    ) -> dict:
        """List discrepancy records with optional period, type, and variance filters."""
        all_discs = []
        for p, discs in _discrepancies_store.items():
            if period and p != period:
                continue
            for d in discs:
                if isinstance(d, dict):
                    variance = d.get("variance", 0) or 0
                    disc_type = d.get("type", "")
                else:
                    variance = getattr(d, 'variance', 0) or 0
                    disc_type = getattr(d, 'type', "")

                if variance < min_variance:
                    continue
                if discrepancy_type and disc_type != discrepancy_type:
                    continue
                all_discs.append({**(d if isinstance(d, dict) else d.model_dump()), "period": p})
        return {"count": len(all_discs), "discrepancies": all_discs}

    # -----------------------------------------------------------------------
    # GET /adjustments — List adjustments
    # -----------------------------------------------------------------------
    @router.get(
        "/adjustments",
        summary="List all proposed adjustments.",
        response_model=None,
    )
    def list_adjustments(
        auth_info: dict = Depends(auth_dep),
        status: Optional[str] = Query(default=None, description="Filter by status: PROPOSED, APPROVED, REJECTED, APPLIED"),
    ) -> dict:
        """List adjustment proposals with optional status filter."""
        adjustments = []
        for adj in _adjustments_store.values():
            if status and adj.status.value != status:
                continue
            adjustments.append(adj.model_dump())
        return {"count": len(adjustments), "adjustments": adjustments}

    # -----------------------------------------------------------------------
    # POST /export — Export to CSV
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # POST /export/download — Download CSV as file
    # -----------------------------------------------------------------------
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
