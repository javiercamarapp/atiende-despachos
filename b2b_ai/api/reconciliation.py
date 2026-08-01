# -*- coding: utf-8 -*-
"""
reconciliation.py — API real de conciliación bancaria con upload.

Endpoints (protegidos por API key):
    POST /api/v1/reconciliation/upload   sube un estado de cuenta (CSV/PDF)
                                         multipart (campo file) + campo bank.
    GET  /api/v1/reconciliation/matches  cruces calculados (con confidence).
    POST /api/v1/reconciliation/confirm  confirma manualmente un cruce.
    GET  /api/v1/reconciliation/report   reporte de conciliación de la sesión.

Cada sesión vive en memoria, aislada por tenant_id. Las facturas de referencia
se toman de la DB del tenant (db.list_invoices).
"""
from __future__ import annotations

import tempfile
import os
from typing import Optional

from fastapi import (APIRouter, Depends, HTTPException, Query, Request,
                     UploadFile, File, Form)
from pydantic import BaseModel

from b2b_ai.services.bank_reconciliation import (BankReconciliation,
                                                 SUPPORTED_BANKS)
from b2b_ai.services.llm import LLMService


# Sesiones por tenant (en memoria). Se crea una sesión por tenant a demanda.
# Aisladas por tenant_id para que un tenant no vea datos de otro.
_SESSIONS: dict = {}


def _session(tenant_id) -> BankReconciliation:
    key = tenant_id if tenant_id is not None else "global"
    if key not in _SESSIONS:
        _SESSIONS[key] = BankReconciliation(tenant_id=tenant_id,
                                            llm=LLMService())
    return _SESSIONS[key]


class ConfirmRequest(BaseModel):
    transaction_id: str
    invoice_id: str


def _invoices_from_db(db, tenant_id) -> list:
    """Trae las facturas del tenant en el shape que espera el servicio."""
    rows = db.list_invoices(tenant_id=tenant_id) or []
    out = []
    for r in rows:
        out.append({
            "folio_fiscal": r.get("folio_fiscal") or r.get("id"),
            "fecha": r.get("fecha"),
            "total": r.get("total"),
            "emisor": r.get("emisor_nombre") or r.get("emisor_rfc"),
            "emisor_nombre": r.get("emisor_nombre"),
            "emisor_rfc": r.get("emisor_rfc"),
            "descripcion": r.get("descripcion"),
        })
    return out


def build_reconciliation_router(db, require_api_key):
    router = APIRouter(prefix="/api/v1/reconciliation",
                       tags=["reconciliation"])

    def _scope(auth_info) -> Optional[int]:
        return auth_info.get("tenant_id") if auth_info else None

    def _tenant_invoices(tenant_id):
        inv = _invoices_from_db(db, tenant_id)
        return inv

    # -- upload ------------------------------------------------------------
    @router.post("/upload",
                 summary="Sube un estado de cuenta (CSV/PDF) y lo carga.")
    async def upload_statement(
        request: Request,
        auth_info: dict = Depends(require_api_key),
        file: UploadFile = File(...),
        bank: str = Form("generico"),
    ):
        """Sube el estado de cuenta como multipart (campo `file`) e indica el
        banco (campo `bank`): bbva, banorte, santander, hsbc o generico.
        Parsea los movimientos y los carga en la sesión del tenant.
        """
        tenant = _scope(auth_info)
        if bank not in SUPPORTED_BANKS:
            raise HTTPException(400,
                                f"Banco no soportado: {bank}. "
                                f"Soportados: {SUPPORTED_BANKS}.")
        if file is None or not getattr(file, "filename", None):
            raise HTTPException(400, "Debe enviar el archivo (campo file).")

        # Guarda el archivo subido a un temp y lo parsea.
        suffix = os.path.splitext(file.filename or "")[1].lower() or ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
        try:
            svc = _session(tenant)
            res = svc.upload_statement(tmp_path, bank)
            db.log_call("reconciliation", "upload", entity="statement",
                        entity_id=file.filename, payload={"bank": bank,
                                                           "rows": res["movimientos"]},
                        status="ok", tenant_id=tenant)
            return {"ok": True, **res}
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # -- matches -----------------------------------------------------------
    @router.get("/matches",
                summary="Cruces automáticos calculados (con confidence).")
    def matches(auth_info: dict = Depends(require_api_key),
                refresh: bool = Query(default=True)):
        """Recalcula (si `refresh=True`) y devuelve los cruces con su
        confidence score 0-100. Cruza contra las facturas del tenant en DB.
        """
        tenant = _scope(auth_info)
        svc = _session(tenant)
        svc.load_invoices(_tenant_invoices(tenant))
        if refresh or not svc.transactions:
            svc.auto_match()
        return svc.auto_matchconfidence()

    # -- confirm -----------------------------------------------------------
    @router.post("/confirm",
                 summary="Confirma manualmente un cruce transacción-factura.")
    def confirm(req: ConfirmRequest,
                auth_info: dict = Depends(require_api_key)):
        """Confirma que la transacción `transaction_id` concilia la factura
        `invoice_id`. El cruce queda marcado method=manual, confidence=100.
        """
        tenant = _scope(auth_info)
        svc = _session(tenant)
        # Asegura que las facturas estén cargadas para resolver el id.
        svc.load_invoices(_tenant_invoices(tenant))
        try:
            m = svc.manual_match(req.transaction_id, req.invoice_id)
        except ValueError as e:
            raise HTTPException(404, str(e))
        db.log_call("reconciliation", "confirm", entity="match",
                    entity_id=req.transaction_id,
                    payload={"invoice_id": req.invoice_id},
                    status="ok", tenant_id=tenant)
        return {"ok": True, "match": m}

    # -- report ------------------------------------------------------------
    @router.get("/report",
                summary="Reporte de conciliación de la sesión actual.")
    def report(auth_info: dict = Depends(require_api_key)):
        """Genera el reporte agregado de conciliación (conciliados,
        pendientes, tasas, por método) para el tenant.
        """
        tenant = _scope(auth_info)
        svc = _session(tenant)
        if not svc.transactions:
            return {"aviso": "No hay movimientos cargados. Sube un estado "
                             "de cuenta primero.", "ok": False}
        # Recalcula los cruces contra las facturas del tenant antes de reportar
        # (idempotente; conserva confirmaciones manuales previas).
        svc.load_invoices(_tenant_invoices(tenant))
        svc.auto_match()
        rep = svc.generate_reconciliation_report()
        rep["ok"] = True
        return rep

    return router
