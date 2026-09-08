# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Devolución de IVA API.

Endpoints:
    POST /api/v1/devolucion-iva/recopilar     — Collect invoices for period
    POST /api/v1/devolucion-iva/diot           — Generate DIOT entries
    POST /api/v1/devolucion-iva/conciliar      — Run full conciliation
    POST /api/v1/devolucion-iva/calcular       — Calculate refund amount
    POST /api/v1/devolucion-iva/solicitud      — Prepare refund request
    GET  /api/v1/devolucion-iva/papel-trabajo/{periodo} — Get working paper
    GET  /api/v1/devolucion-iva/status/{solicitud_id}    — Check status
    GET  /api/v1/devolucion-iva/historical     — List past requests
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.devolucion_iva.service import DevolucionIVAService
from b2b_ai.features.devolucion_iva.workpaper import WorkpaperGenerator
from b2b_ai.features.devolucion_iva.models import (
    FacturaCFDI,
    DeclaracionMensual,
    EstatusDevolucion,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RecopilarRequest(BaseModel):
    """Request to collect invoices for a period."""
    periodo: str = Field(
        ...,
        description="Periodo (YYYY-MM)",
    )
    facturas: List[dict] = Field(
        default_factory=list,
        description="Lista de facturas CFDI",
    )
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")


class DIOTRequest(BaseModel):
    """Request to generate DIOT entries from invoices."""
    facturas: List[dict] = Field(
        ...,
        description="Lista de facturas CFDI",
    )
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")


class ConciliarRequest(BaseModel):
    """Request to run conciliation."""
    facturas: List[dict] = Field(
        default_factory=list,
        description="Lista de facturas CFDI",
    )
    diot_entries: List[dict] = Field(
        default_factory=list,
        description="Entradas DIOT",
    )
    declaraciones: List[dict] = Field(
        default_factory=list,
        description="Declaraciones mensuales",
    )
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")


class CalcularRequest(BaseModel):
    """Request to calculate refund amount."""
    declaraciones: List[dict] = Field(
        ...,
        description="Declaraciones mensuales",
    )
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")


class SolicitudRequest(BaseModel):
    """Request to prepare a refund request."""
    periodo: str = Field(..., description="Periodo (YYYY-MM)")
    saldo_favor: float = Field(..., description="Saldo a favor calculado")
    cuenta_banco: Optional[str] = Field(default=None, description="Nombre del banco")
    clabe: Optional[str] = Field(default=None, description="CLABE interbancaria")
    facturas: List[dict] = Field(default_factory=list, description="Facturas")
    diot_entries: List[dict] = Field(default_factory=list, description="DIOT entries")
    declaraciones: List[dict] = Field(default_factory=list, description="Declaraciones")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")


class PapelTrabajoRequest(BaseModel):
    """Request to generate working paper."""
    periodo: str = Field(..., description="Periodo (YYYY-MM)")
    facturas: List[dict] = Field(default_factory=list, description="Facturas")
    diot_entries: List[dict] = Field(default_factory=list, description="DIOT entries")
    declaraciones: List[dict] = Field(default_factory=list, description="Declaraciones")
    documentos_soporte: List[str] = Field(default_factory=list, description="Documentos soporte")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")


def _tenant_ids_declarados_en_payload(
    tenant_id_top: Optional[str],
    facturas: List[dict],
    diot_entries: List[dict],
    declaraciones: List[dict],
) -> set:
    """Recolecta todos los `tenant_id` declarados dentro del body.

    REQ-IVA-018: `facturas`/`diot_entries`/`declaraciones` llegan como
    dicts libres (no como modelos tipados a nivel de request), así que
    cualquier item puede traer su propio `tenant_id` además del
    `tenant_id` a nivel de request completo. Un tenant autenticado podría
    intentar colar registros marcados con el `tenant_id` de otro tenant
    dentro del body — esto los recolecta todos para poder compararlos
    contra el tenant real del token, sin asumir que "vienen limpios"
    solo porque la lectura (REQ-IVA-007) ya está protegida.
    """
    encontrados: set = set()
    if tenant_id_top:
        encontrados.add(tenant_id_top)
    for coleccion in (facturas, diot_entries, declaraciones):
        for item in coleccion:
            if isinstance(item, dict):
                tid = item.get("tenant_id")
                if tid is not None and str(tid).strip():
                    encontrados.add(tid)
    return encontrados


def _validar_tenant_payload_o_422(
    auth_info: Optional[dict],
    tenant_id_top: Optional[str],
    facturas: List[dict],
    diot_entries: List[dict],
    declaraciones: List[dict],
) -> None:
    """REQ-IVA-018 — 422 si el tenant del token no coincide con el body.

    Complementa REQ-IVA-007 (que blinda la *lectura*, `listar_solicitudes`):
    aquí se blinda la *escritura*/procesamiento — un tenant autenticado
    nunca debe poder hacer que el servicio concilie facturas, entradas
    DIOT o declaraciones marcadas como pertenecientes a otro tenant, así
    el ataque venga en el campo `tenant_id` del request completo o en el
    de cualquier factura/entrada/declaración individual del body.

    Sin `tenant_id` en el token (contexto administrativo/legado, mismo
    criterio que `listar_solicitudes` sin filtro) no hay nada contra qué
    comparar y no se rechaza nada — evita romper usos existentes sin
    tenant en el token.
    """
    auth_tenant_id = auth_info.get("tenant_id") if auth_info else None
    if not auth_tenant_id:
        return

    tenant_ids_payload = _tenant_ids_declarados_en_payload(
        tenant_id_top, facturas, diot_entries, declaraciones,
    )
    ajenos = {tid for tid in tenant_ids_payload if str(tid) != str(auth_tenant_id)}
    if ajenos:
        raise HTTPException(
            status_code=422,
            detail=(
                "El tenant_id del token no coincide con el tenant_id "
                "declarado en las facturas/DIOT/declaraciones del body: "
                f"{sorted(str(t) for t in ajenos)}."
            ),
        )


class DevolucionIVAResponse(BaseModel):
    """Standard response for Devolución de IVA operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_devolucion_iva_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the Devolución de IVA API router.

    Parameters
    ----------
    db : Database instance usada para persistir solicitudes/status/papeles
        de trabajo (REQ-IVA-006: tablas `devolucion_iva_solicitudes` /
        `devolucion_iva_papeles_trabajo`, no dicts de proceso). Cuando es
        `None` se usa la base compartida en memoria del módulo (solo para
        tests/uso standalone del router).
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key
    service = DevolucionIVAService(db=db)
    workpaper_gen = WorkpaperGenerator()

    router = APIRouter(prefix="/api/v1/devolucion-iva", tags=["devolucion-iva"])

    # -------------------------------------------------------------------
    # POST /recopilar — Collect invoices for period
    # -------------------------------------------------------------------
    @router.post(
        "/recopilar",
        summary="Collect and classify invoices for a period.",
        response_model=None,
    )
    def recopilar(
        req: RecopilarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        facturas = service.recopilar_facturas(
            req.facturas, periodo=req.periodo, tenant_id=tenant_id,
        )
        clasificacion = service.clasificar_iva(facturas)

        return {
            "ok": True,
            "message": f"Facturas recopiladas para {req.periodo}: {len(facturas)}.",
            "data": {
                "total_facturas": len(facturas),
                "acreditable_100": len(clasificacion.get("acreditable_100", [])),
                "acreditable_proporcional": len(clasificacion.get("acreditable_proporcional", [])),
                "no_acreditable": len(clasificacion.get("no_acreditable", [])),
                "facturas": [f.model_dump() for f in facturas],
            },
        }

    # -------------------------------------------------------------------
    # POST /diot — Generate DIOT entries
    # -------------------------------------------------------------------
    @router.post(
        "/diot",
        summary="Generate DIOT entries from invoice data.",
        response_model=None,
    )
    def generar_diot(
        req: DIOTRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        diot_entries = service.generar_diot(req.facturas)
        errors = service.validar_diot(diot_entries)

        return {
            "ok": len(errors) == 0,
            "message": (
                f"DIOT generada: {len(diot_entries)} entradas."
                if not errors
                else f"DIOT generada con {len(errors)} error(es)."
            ),
            "data": {
                "total_entries": len(diot_entries),
                "entries": [e.model_dump() for e in diot_entries],
                "errors": errors,
            },
        }

    # -------------------------------------------------------------------
    # POST /conciliar — Run conciliation
    # -------------------------------------------------------------------
    @router.post(
        "/conciliar",
        summary="Run conciliation CFDI ↔ DIOT ↔ Declarations.",
        response_model=None,
    )
    def conciliar(
        req: ConciliarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        _validar_tenant_payload_o_422(
            auth_info,
            req.tenant_id,
            req.facturas,
            req.diot_entries,
            req.declaraciones,
        )

        result = service.conciliar(
            req.facturas,
            req.diot_entries,
            req.declaraciones,
        )

        total_f = len(result["facturas_vs_diot"])
        matches_f = sum(
            1 for c in result["facturas_vs_diot"] if c["status"] == "match"
        )
        total_d = len(result["diot_vs_declaracion"])
        matches_d = sum(
            1 for c in result["diot_vs_declaracion"] if c["status"] == "match"
        )

        return {
            "ok": True,
            "message": (
                f"Conciliación completada. "
                f"CFDI↔DIOT: {matches_f}/{total_f} matches. "
                f"DIOT↔Decl: {matches_d}/{total_d} matches."
            ),
            "data": result,
        }

    # -------------------------------------------------------------------
    # POST /calcular — Calculate refund amount
    # -------------------------------------------------------------------
    @router.post(
        "/calcular",
        summary="Calculate IVA refund amount from declarations.",
        response_model=None,
    )
    def calcular(
        req: CalcularRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        result = service.calcular(req.declaraciones)

        return {
            "ok": True,
            "message": (
                f"Monto de devolución sugerido: "
                f"${result.get('monto_devolucion_sugerido', 0):,.2f} MXN"
            ),
            "data": result,
        }

    # -------------------------------------------------------------------
    # POST /solicitud — Prepare refund request
    # -------------------------------------------------------------------
    @router.post(
        "/solicitud",
        summary="Prepare a refund request for SAT submission.",
        response_model=None,
    )
    def preparar_solicitud(
        req: SolicitudRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id
        saldo = {
            "monto_devolucion_sugerido": req.saldo_favor,
            "saldo_favor_original": req.saldo_favor,
        }

        try:
            solicitud = service.preparar_solicitud(
                periodo=req.periodo,
                saldo=saldo,
                cuenta_banco=req.cuenta_banco,
                clabe=req.clabe,
                tenant_id=tenant_id,
                facturas=req.facturas,
                diot_entries=req.diot_entries,
                declaraciones=req.declaraciones,
            )
            # Register the solicitud
            service.registrar(solicitud)

            return {
                "ok": True,
                "message": f"Solicitud preparada: {solicitud.solicitud_id}",
                "data": solicitud.model_dump(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # -------------------------------------------------------------------
    # GET /papel-trabajo/{periodo} — Get working paper
    # -------------------------------------------------------------------
    @router.get(
        "/papel-trabajo/{periodo}",
        summary="Generate and retrieve the conciliation working paper.",
        response_model=None,
    )
    def papel_trabajo(
        periodo: str,
        facturas_json: Optional[str] = Query(default=None, description="JSON facturas"),
        diot_json: Optional[str] = Query(default=None, description="JSON DIOT entries"),
        declaraciones_json: Optional[str] = Query(default=None, description="JSON declaraciones"),
        tenant_id: Optional[str] = Query(default=None, description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        import json

        facturas = []
        diot_entries = []
        declaraciones = []

        if facturas_json:
            facturas = [FacturaCFDI(**d) for d in json.loads(facturas_json)]
        if diot_json:
            from b2b_ai.features.devolucion_iva.models import DIOTEntry as DE
            diot_entries = [DE(**d) for d in json.loads(diot_json)]
        if declaraciones_json:
            declaraciones = [DeclaracionMensual(**d) for d in json.loads(declaraciones_json)]

        wp = workpaper_gen.generate(
            periodo=periodo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=declaraciones,
            tenant_id=tenant_id,
        )

        return {
            "ok": True,
            "message": f"Papel de trabajo generado para {periodo}.",
            "data": wp,
        }

    # -------------------------------------------------------------------
    # GET /status/{solicitud_id} — Check status
    # -------------------------------------------------------------------
    @router.get(
        "/status/{solicitud_id}",
        summary="Check the status of a refund request.",
        response_model=None,
    )
    def status_solicitud(
        solicitud_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        report = service.generar_reporte(solicitud_id)
        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"Solicitud '{solicitud_id}' no encontrada.",
            )

        return {
            "ok": True,
            "message": f"Status de solicitud {solicitud_id}: {report['status_actual']}",
            "data": report,
        }

    # -------------------------------------------------------------------
    # GET /historical — List past requests
    # -------------------------------------------------------------------
    @router.get(
        "/historical",
        summary="List all past refund requests.",
        response_model=None,
    )
    def historical(
        tenant_id: Optional[str] = Query(default=None, description="Filter by tenant"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        effective_tenant_id = auth_info.get("tenant_id") if auth_info else tenant_id
        solicitudes = service.listar(tenant_id=effective_tenant_id)

        return {
            "ok": True,
            "message": f"{len(solicitudes)} solicitud(es) encontrada(s).",
            "data": {
                "total": len(solicitudes),
                "solicitudes": solicitudes,
            },
        }

    return router
