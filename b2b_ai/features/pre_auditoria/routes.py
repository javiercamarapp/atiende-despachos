# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Pre-Auditoría Contable.

Endpoints:
    POST /pre-auditoria/run     — Ejecuta una pre-auditoría completa.
    GET  /pre-auditoria/report/{id} — Obtiene un reporte guardado.
    GET  /pre-auditoria/history — Historial de auditorías previas.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.pre_auditoria.service import (
    check_cff_compliance,
    check_consistency,
    check_deductibility,
    generate_audit_report,
    run_pre_audit,
)
from b2b_ai.features.pre_auditoria.models import AuditReport


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class PreAuditRequest(BaseModel):
    """Request para ejecutar una pre-auditoría completa."""
    tenant_id: int
    period: str = Field(..., description="Periodo YYYY-MM")
    invoices: list[dict] = Field(default_factory=list, description="Facturas para verificar deducibilidad")
    ledger: list[dict] = Field(default_factory=list, description="Asientos contables para verificar consistencia")
    cff_data: dict = Field(default_factory=dict, description="Datos para verificar compliance CFF")


class DeductibilityRequest(BaseModel):
    """Request para verificar deducibilidad de gastos."""
    invoices: list[dict] = Field(..., description="Lista de facturas/gastos")


class ConsistencyRequest(BaseModel):
    """Request para verificar consistencia contable."""
    ledger: list[dict] = Field(..., description="Asientos contables")


class CFFComplianceRequest(BaseModel):
    """Request para verificar compliance CFF."""
    rfc: str = ""
    cfdi_count: int = 0
    tiene_contabilidad_electronica: bool = False
    periodos_cerrados: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_pre_auditoria_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /pre-auditoria/*.

    Sigue el patrón `build_*_router()` del proyecto.
    Almacena reportes en memoria (MVP); en producción usar DB.
    """
    router = APIRouter(prefix="/pre-auditoria", tags=["pre-auditoria"])
    _auth = [Depends(require_api_key)] if require_api_key else []
    if _auth:
        router.dependencies.extend(_auth)

    # Almacén temporal de reportes (key = tenant_id-period)
    _reports: dict[str, dict] = {}

    @router.post(
        "/run",
        summary="Ejecuta una pre-auditoría contable completa.",
        response_model=None,
    )
    def ejecutar_pre_auditoria(req: PreAuditRequest):
        """Ejecuta un escaneo pre-audit sobre facturas, contabilidad y CFF.

        Retorna un reporte con hallazgos, score y recomendaciones.
        """
        report = run_pre_audit(
            tenant_id=req.tenant_id,
            period=req.period,
            invoices=req.invoices,
            ledger=req.ledger,
            cff_data=req.cff_data,
        )
        # Guardar en memoria
        key = f"{req.tenant_id}-{req.period}"
        _reports[key] = report.to_dict()
        return {"ok": True, "report": report.to_dict()}

    @router.post(
        "/deductibility",
        summary="Verifica la deducibilidad de gastos (Art. 28 LISR).",
        response_model=None,
    )
    def verificar_deducibilidad(req: DeductibilityRequest):
        """Analiza si cada gasto es deducible según la legislación fiscal."""
        results = check_deductibility(req.invoices)
        return {
            "ok": True,
            "total": len(results),
            "no_deducibles": sum(1 for r in results if not r.es_deducible),
            "results": [r.to_dict() for r in results],
        }

    @router.post(
        "/consistency",
        summary="Verifica la consistencia del libro de contabilidad.",
        response_model=None,
    )
    def verificar_consistencia(req: ConsistencyRequest):
        """Detecta errores de partida doble, fechas y cuentas incompletas."""
        findings = check_consistency(req.ledger)
        return {
            "ok": len(findings) == 0,
            "findings_count": len(findings),
            "findings": [f.to_dict() for f in findings],
        }

    @router.post(
        "/cff-compliance",
        summary="Verifica compliance con el CFF.",
        response_model=None,
    )
    def verificar_cff(req: CFFComplianceRequest):
        """Valida RFC, CFDI, contabilidad electrónica y periodos cerrados."""
        findings = check_cff_compliance({
            "rfc": req.rfc,
            "cfdi_count": req.cfdi_count,
            "tiene_contabilidad_electronica": req.tiene_contabilidad_electronica,
            "periodos_cerrados": req.periodos_cerrados,
        })
        return {
            "ok": len(findings) == 0,
            "findings_count": len(findings),
            "findings": [f.to_dict() for f in findings],
        }

    @router.get(
        "/report/{composite_id}",
        summary="Obtiene un reporte de auditoría guardado.",
        response_model=None,
    )
    def obtener_reporte(composite_id: str):
        """Retorna un reporte de auditoría previamente generado.

        ``composite_id`` tiene formato ``{tenant_id}-{period}``
        (p.ej. ``5-2026-08``).
        """
        parts = composite_id.split("-", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=422,
                detail="composite_id debe tener formato {tenant_id}-{period}.",
            )
        tenant_id = int(parts[0])
        period = parts[1]
        key = f"{tenant_id}-{period}"
        report = _reports.get(key)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró reporte para tenant {tenant_id} periodo {period}.",
            )
        return {"ok": True, "report": report}

    @router.get(
        "/history",
        summary="Historial de auditorías previas.",
        response_model=None,
    )
    def historial_auditorias(
        tenant_id: Optional[int] = Query(default=None),
    ):
        """Lista reportes de auditoría generados."""
        results = []
        for key, report in _reports.items():
            if tenant_id is not None:
                prefix = f"{tenant_id}-"
                if not key.startswith(prefix):
                    continue
            results.append(report)
        return {"ok": True, "count": len(results), "reports": results}

    return router
