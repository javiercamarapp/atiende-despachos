# -*- coding: utf-8 -*-
"""
api.py — Endpoints FastAPI de integración SAT.

Endpoints (requieren API key en el header `X-API-Key`):

    POST /api/v1/sat/download   descarga masiva de CFDI por rango de fechas.
    POST /api/v1/sat/verify     verifica estatus/cadena de un CFDI.
    GET  /api/v1/sat/status      estado de sesión / scheduler del tenant.
    POST /api/v1/sat/schedule    programa descarga diaria / verificación semanal.

Todos los endpoints usan el transporte mock (no e.firma real). Las
credenciales del tenant (RFC/CIEC) se leen de la config del tenant
(`sat_rfc`, `sat_ciec`) o se pasan por request.

El router se construye con `build_sat_router(db, require_api_key)` para poder
inyectar una DB de prueba y componentes mock en los tests.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.sat.downloader import SATDownloader, TIPOS_CFDI
from b2b_ai.sat.validator import SATValidator
from b2b_ai.sat.scheduler import SATScheduler


# -------------------------------------------------------------------------- #
# Schemas
# -------------------------------------------------------------------------- #
class SATDownloadRequest(BaseModel):
    rfc: str = ""
    ciec: str = ""
    e_firma_path: str = ""
    fecha_inicio: str
    fecha_fin: str
    tipo: str = "emitidas"


class SATVerifyRequest(BaseModel):
    folio_fiscal: str


class SATScheduleRequest(BaseModel):
    rfc: str = ""
    ciec: str = ""
    frequency: str = "daily"        # daily | weekly | both
    tipo: str = "emitidas"          # para la descarga programada


# -------------------------------------------------------------------------- #
# Router
# -------------------------------------------------------------------------- #
def _credentials(db, tenant_id, rfc, ciec):
    """RFC/CIEC efectivos: request > tenant_config > vacío."""
    eff_rfc = rfc or (db.get_tenant_config(tenant_id, "sat_rfc", "")
                      if tenant_id is not None else "")
    eff_ciec = ciec or (db.get_tenant_config(tenant_id, "sat_ciec", "")
                        if tenant_id is not None else "")
    return eff_rfc, eff_ciec


def build_sat_router(db, require_api_key,
                     downloader=None, validator=None, scheduler=None):
    """Devuelve un APIRouter /api/v1/sat/*.

    Args:
        db:              instancia de Database.
        require_api_key: dependencia de auth (Depends).
        downloader/validator/scheduler: componentes opcionales (tests
                        inyectan mocks). Si no, se crean por defecto.
    """
    router = APIRouter(prefix="/api/v1/sat", tags=["sat"])

    @router.post("/download", summary="Descarga masiva de CFDI por rango.")
    def sat_download(req: SATDownloadRequest,
                     auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        eff_rfc, eff_ciec = _credentials(db, tenant, req.rfc, req.ciec)
        dl = downloader or SATDownloader(db=db, tenant_id=tenant,
                                         rfc=eff_rfc, ciec=eff_ciec,
                                         e_firma_path=req.e_firma_path)
        login = dl.login(eff_rfc, eff_ciec, req.e_firma_path)
        if not login.get("ok"):
            raise HTTPException(400, login.get("error", "Login SAT falló."))
        try:
            result = dl.download_cfdi(req.fecha_inicio, req.fecha_fin, req.tipo)
        finally:
            dl.logout()
        if not result.get("ok"):
            raise HTTPException(422, result.get("error", "Descarga fallida."))
        db.log_call("sat", "download", entity="cfdi",
                    entity_id=req.fecha_inicio, payload={
                        "tipo": req.tipo, "count": result.get("count", 0),
                        "fecha_inicio": req.fecha_inicio,
                        "fecha_fin": req.fecha_fin,
                    }, status="ok", tenant_id=tenant)
        return result

    @router.post("/verify", summary="Verifica estatus y cadena de un CFDI.")
    def sat_verify(req: SATVerifyRequest,
                   auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        val = validator or SATValidator(db=db, tenant_id=tenant)
        result = val.verify_cfdi(req.folio_fiscal)
        db.log_call("sat", "verify", entity="cfdi",
                    entity_id=req.folio_fiscal,
                    payload={"estado": result.get("estado")},
                    status="ok" if result.get("ok") else "warn",
                    tenant_id=tenant)
        if not result.get("ok") and result.get("estado") == "no_encontrado":
            raise HTTPException(404, result.get("estatus", {}).get("descripcion",
                                                                   "CFDI no encontrado."))
        return result

    @router.get("/status", summary="Estado de sesión y scheduler SAT.")
    def sat_status(auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        dl = downloader or SATDownloader(db=db, tenant_id=tenant)
        sched = scheduler or SATScheduler(db=db, tenant_id=tenant,
                                          downloader=dl,
                                          validator=validator or SATValidator(db, tenant))
        # RFC configurado del tenant.
        rfc = db.get_tenant_config(tenant, "sat_rfc", "") if tenant is not None else ""
        return {
            "tenant_id": tenant,
            "rfc": rfc or dl.rfc,
            "downloader": dl.status(),
            "scheduler": sched.status(),
        }

    @router.post("/schedule", summary="Programa descarga diaria / verificación semanal.")
    def sat_schedule(req: SATScheduleRequest,
                     auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        if tenant is None:
            raise HTTPException(400, "La programación es por tenant y requiere "
                                     "una API key de tenant.")
        if req.frequency not in ("daily", "weekly", "both"):
            raise HTTPException(422, "frequency debe ser daily, weekly o both.")
        eff_rfc, eff_ciec = _credentials(db, tenant, req.rfc, req.ciec)
        if not eff_rfc:
            raise HTTPException(422, "Se requiere RFC (param o config sat_rfc "
                                     "del tenant).")
        # Guardar configuración del schedule en el tenant.
        db.set_tenant_config(tenant, "sat_schedule_frequency", req.frequency)
        db.set_tenant_config(tenant, "sat_schedule_tipo", req.tipo)
        if eff_rfc:
            db.set_tenant_config(tenant, "sat_rfc", eff_rfc)
        if eff_ciec:
            db.set_tenant_config(tenant, "sat_ciec", eff_ciec)

        sched = scheduler or SATScheduler(db=db, tenant_id=tenant,
                                          downloader=downloader,
                                          validator=validator,
                                          rfc=eff_rfc, ciec=eff_ciec)
        # Ejecuta inmediatamente si daily o both (mejor UX + test real).
        executed = []
        if req.frequency in ("daily", "both"):
            res = sched.run_daily()
            executed.append({"task": "daily", "result": res})
        if req.frequency in ("weekly", "both"):
            res = sched.run_weekly()
            executed.append({"task": "weekly", "result": res})

        db.log_call("sat", "schedule", entity="schedule",
                    entity_id=req.frequency,
                    payload={"rfc": eff_rfc, "tipo": req.tipo},
                    status="ok", tenant_id=tenant)
        return {
            "ok": True,
            "frequency": req.frequency,
            "rfc": eff_rfc,
            "executed": executed,
        }

    return router
