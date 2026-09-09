# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Income/Expense Reconciliation API.

Endpoints:
    POST  /api/v1/reconciliacion-ingresos/recopilar         — Collect data
    POST  /api/v1/reconciliacion-ingresos/clasificar         — Classify deposits
    POST  /api/v1/reconciliacion-ingresos/conciliar          — Run reconciliation
    POST  /api/v1/reconciliacion-ingresos/balance-iva        — Calculate IVA balance
    GET   /api/v1/reconciliacion-ingresos/papel-trabajo/{periodo} — Get working paper
    GET   /api/v1/reconciliacion-ingresos/discrepancias/{periodo} — Get discrepancies
    PATCH /api/v1/reconciliacion-ingresos/clasificaciones/{clasificacion_id}/aprobar
          — Confirmación humana de una clasificación (REQ-IVA-013, ADR-4):
            único camino para mover una clasificación de
            origen="automatico_sugerido" a origen="aprobado".
    GET   /api/v1/reconciliacion-ingresos/papel-trabajo/{periodo}/exportable
          — Papel de trabajo exportable (REQ-IVA-003): excluye toda
            clasificación FINANCIAMIENTO/APORTACION_SOCIO/GARANTIA sin
            documento de soporte real todavía adjuntado.
    POST  /api/v1/reconciliacion-ingresos-egresos/{clasificacion_id}/documento-soporte
          — Adjuntar el documento real (contrato de mutuo, acta de
            asamblea, contrato de garantía) que soporta una clasificación
            de depósito ya hecha (REQ-IVA-003 — mecanismo operativo que
            hace cumplible REQ-IVA-002/ADR-4). Sin este adjunto, la
            clasificación queda en `estado_recaracterizacion=
            "requiere_formalizacion"` ("pendiente_evidencia") y no puede
            incluirse en un papel de trabajo exportable.

The router is built with `build_reconciliacion_ingresos_egresos_router(db, require_api_key)`
following the project pattern. It returns a single combined `APIRouter`
that nests both the historical `/api/v1/reconciliacion-ingresos` prefix
and the `/api/v1/reconciliacion-ingresos-egresos` prefix used by the
REQ-IVA-003 endpoint, so a single `app.include_router(...)` call mounts
every route above.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    BalanceIVA,
    ConciliacionIngresosEgresos,
    DepositoBancario,
    DiscrepanciaFiscal,
    PapelTrabajoConciliacion,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.validators import (
    validate_periodo,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RecopilarRequest(BaseModel):
    """Request to collect deposit and auxiliary data."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos bancarios (id, fecha, monto, descripcion, referencia, banco, cuenta, es_credito)",
    )
    auxiliares: List[dict] = Field(
        default_factory=list,
        description="Auxiliares contables (cuenta_id, cuenta_mayor, cuenta_auxiliar, descripcion, saldo_inicial, movimientos, saldo_final)",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ClasificarRequest(BaseModel):
    """Request to classify deposits."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos a clasificar",
    )
    auxiliares: List[dict] = Field(
        default_factory=list,
        description="Auxiliares para matching",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ConciliarRequest(BaseModel):
    """Request to run reconciliation."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos bancarios",
    )
    auxiliares: List[dict] = Field(
        default_factory=list,
        description="Auxiliares contables",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class BalanceIVARequest(BaseModel):
    """Request to calculate IVA balance."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    declaraciones: List[dict] = Field(
        default_factory=list,
        description="Declaraciones de IVA (iva_cobrado, iva_pagado, declarado)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos clasificados",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ReconciliacionResponse(BaseModel):
    """Standard response for reconciliation operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


class AprobarClasificacionRequest(BaseModel):
    """Body (opcional) de la confirmación humana de una clasificación."""
    nota: Optional[str] = Field(
        default=None,
        description="Nota opcional del humano que confirma la clasificación",
    )


class DocumentoSoporteRequest(BaseModel):
    """Body para adjuntar un documento de soporte real a una clasificación
    de depósito ya hecha (REQ-IVA-003). Nunca se sintetiza ni se infiere:
    debe referenciar un documento real (contrato de mutuo, acta de
    asamblea, contrato de garantía) ya cargado al repositorio de
    documentos/adjuntos."""
    documento_soporte_id: str = Field(
        ...,
        description=(
            "Identificador del documento real en el repositorio de "
            "documentos/adjuntos (contrato de mutuo, acta de asamblea o "
            "contrato de garantía)."
        ),
    )
    fecha_documento: str = Field(
        ...,
        description="Fecha del documento de soporte real (YYYY-MM-DD).",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID (si no viene ya resuelto por el token de autenticación)",
    )


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_reconciliacion_ingresos_egresos_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the income/expense reconciliation API router.

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

    # In-memory service
    service = ReconciliacionIngresosEgresosService()

    router = APIRouter(
        prefix="/api/v1/reconciliacion-ingresos",
        tags=["reconciliacion-ingresos"],
    )

    # -------------------------------------------------------------------
    # POST /recopilar — Collect data
    # -------------------------------------------------------------------
    @router.post(
        "/recopilar",
        summary="Recopilar depósitos bancarios y auxiliares contables.",
        response_model=None,
    )
    def recopilar_datos(
        req: RecopilarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Collect and validate bank deposits and auxiliary entries for a period."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        depositos = service.recopilar_depositos(
            req.periodo, tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, tenant_id, req.auxiliares
        )

        return {
            "ok": True,
            "message": f"Datos recopilados para período {req.periodo}.",
            "depositos_recibidos": len(req.depositos),
            "depositos_validos": len(depositos),
            "auxiliares_recibidos": len(req.auxiliares),
            "auxiliares_validos": len(auxiliares),
            "depositos": [d.model_dump() for d in depositos],
            "auxiliares": [a.model_dump() for a in auxiliares],
        }

    # -------------------------------------------------------------------
    # POST /clasificar — Classify deposits
    # -------------------------------------------------------------------
    @router.post(
        "/clasificar",
        summary="Clasificar depósitos bancarios por tipo fiscal.",
        response_model=None,
    )
    def clasificar_depositos(
        req: ClasificarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Classify deposits as income, financing, partner contribution, guarantee, or other."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        depositos = service.recopilar_depositos(
            req.periodo, tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, tenant_id, req.auxiliares
        )

        clasificaciones = service.clasificar_todos(depositos, auxiliares, tenant_id=tenant_id)

        return {
            "ok": True,
            "message": f"Clasificación completada: {len(clasificaciones)} depósitos.",
            "clasificaciones": [c.model_dump() for c in clasificaciones],
        }

    # -------------------------------------------------------------------
    # POST /conciliar — Run reconciliation
    # -------------------------------------------------------------------
    @router.post(
        "/conciliar",
        summary="Conciliar depósitos bancarios con auxiliares contables.",
        response_model=None,
    )
    def conciliar(
        req: ConciliarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Run full reconciliation between bank deposits and auxiliary entries."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        depositos = service.recopilar_depositos(
            req.periodo, tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, tenant_id, req.auxiliares
        )

        conciliacion = service.conciliar_depositos_auxiliares(
            depositos, auxiliares, periodo=req.periodo, tenant_id=tenant_id
        )

        # Generate working paper
        papel = service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)

        return {
            "ok": True,
            "message": f"Conciliación completada para {req.periodo}.",
            "conciliacion": conciliacion.model_dump(),
            "papel_trabajo_id": f"{req.periodo}_{tenant_id or 'default'}",
        }

    # -------------------------------------------------------------------
    # POST /balance-iva — Calculate IVA balance
    # -------------------------------------------------------------------
    @router.post(
        "/balance-iva",
        summary="Calcular balance de IVA para un período.",
        response_model=None,
    )
    def balance_iva(
        req: BalanceIVARequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Calculate IVA balance from declarations and classified deposits."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        depositos = service.recopilar_depositos(
            req.periodo, req.tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, req.tenant_id, []
        )

        clasificaciones = service.clasificar_todos(depositos, auxiliares)

        balance = service.calcular_balance_iva(
            req.declaraciones, clasificaciones, depositos
        )

        return {
            "ok": True,
            "message": f"Balance IVA calculado para {req.periodo}.",
            "balance_iva": balance.model_dump(),
        }

    # -------------------------------------------------------------------
    # GET /papel-trabajo/{periodo} — Get working paper
    # -------------------------------------------------------------------
    @router.get(
        "/papel-trabajo/{periodo}",
        summary="Obtener papel de trabajo de conciliación.",
        response_model=None,
    )
    def get_papel_trabajo(
        periodo: str,
        tenant_id: Optional[str] = Query(default=None, description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve the working paper for a given period."""
        is_valid, period_err = validate_periodo(periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tid = tenant_id
        if auth_info and not tid:
            tid = auth_info.get("tenant_id")

        papel = service.get_papel_trabajo(periodo, tid)
        if not papel:
            raise HTTPException(
                status_code=404,
                detail=f"Papel de trabajo para período '{periodo}' no encontrado.",
            )

        return {
            "ok": True,
            "papel_trabajo": papel.model_dump(),
        }

    # -------------------------------------------------------------------
    # GET /discrepancias/{periodo} — Get discrepancies
    # -------------------------------------------------------------------
    @router.get(
        "/discrepancias/{periodo}",
        summary="Obtener discrepancias de conciliación para un período.",
        response_model=None,
    )
    def get_discrepancias(
        periodo: str,
        tenant_id: Optional[str] = Query(default=None, description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve discrepancies found during reconciliation for a period."""
        is_valid, period_err = validate_periodo(periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tid = tenant_id
        if auth_info and not tid:
            tid = auth_info.get("tenant_id")

        papel = service.get_papel_trabajo(periodo, tid)
        if not papel:
            raise HTTPException(
                status_code=404,
                detail=f"Papel de trabajo para período '{periodo}' no encontrado.",
            )

        return {
            "ok": True,
            "periodo": periodo,
            "discrepancias": [d.model_dump() for d in papel.discrepancias],
            "total": len(papel.discrepancias),
        }

    # -------------------------------------------------------------------
    # GET /papel-trabajo/{periodo}/exportable — Exportable working paper
    # -------------------------------------------------------------------
    @router.get(
        "/papel-trabajo/{periodo}/exportable",
        summary="Obtener el papel de trabajo exportable (excluye evidencia pendiente).",
        response_model=None,
    )
    def get_papel_trabajo_exportable(
        periodo: str,
        tenant_id: Optional[str] = Query(default=None, description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """REQ-IVA-003: versión exportable del papel de trabajo.

        Excluye toda clasificación FINANCIAMIENTO/APORTACION_SOCIO/GARANTIA
        que todavía no tenga un documento de soporte real adjuntado (queda
        en `estado_recaracterizacion="requiere_formalizacion"`, es decir
        "pendiente_evidencia") — esa clasificación no puede incluirse en un
        papel de trabajo exportable hasta que se adjunte el documento vía
        `POST /api/v1/reconciliacion-ingresos-egresos/{id}/documento-soporte`.
        """
        is_valid, period_err = validate_periodo(periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tid = tenant_id
        if auth_info and not tid:
            tid = auth_info.get("tenant_id")

        papel_exportable, excluidas = service.generar_papel_trabajo_exportable(periodo, tid)
        if papel_exportable is None:
            raise HTTPException(
                status_code=404,
                detail=f"Papel de trabajo para período '{periodo}' no encontrado.",
            )

        return {
            "ok": True,
            "papel_trabajo_exportable": papel_exportable.model_dump(),
            "excluidas_por_evidencia_pendiente": excluidas,
            "total_incluidas": len(papel_exportable.clasificaciones),
            "total_excluidas": len(excluidas),
        }

    # -------------------------------------------------------------------
    # PATCH /clasificaciones/{clasificacion_id}/aprobar — Human approval
    # -------------------------------------------------------------------
    @router.patch(
        "/clasificaciones/{clasificacion_id}/aprobar",
        summary="Confirmar humanamente una clasificación de depósito.",
        response_model=None,
    )
    def aprobar_clasificacion(
        clasificacion_id: str,
        req: Optional[AprobarClasificacionRequest] = None,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Único camino para mover una clasificación a origen="aprobado".

        REQ-IVA-013 / ADR-4: el motor de reglas por regex siempre entrega
        `origen="automatico_sugerido"`, nunca `"aprobado"`. Esta es la
        única ruta que puede cambiar ese estado, y solo lo hace tras una
        acción humana explícita (este PATCH). Ninguna clasificación
        automática de primera pasada es una determinación fiscal firme
        sin pasar por aquí.
        """
        tenant_id = auth_info.get("tenant_id") if auth_info else None
        aprobado_por = (auth_info.get("user_id") if auth_info else None) or "desconocido"

        try:
            clas = service.aprobar_clasificacion(
                clasificacion_id, aprobado_por=aprobado_por, tenant_id=tenant_id
            )
        except KeyError:
            # Mismo 404 tanto si el id no existe como si pertenece a otro
            # tenant — no se revela la existencia de clasificaciones ajenas.
            raise HTTPException(
                status_code=404,
                detail=f"Clasificación '{clasificacion_id}' no encontrada.",
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

        return {
            "ok": True,
            "message": f"Clasificación '{clasificacion_id}' aprobada por '{aprobado_por}'.",
            "clasificacion": clas.model_dump(),
        }

    # -------------------------------------------------------------------
    # Second router: /api/v1/reconciliacion-ingresos-egresos
    # (REQ-IVA-003's literal endpoint path — kept as its own prefix so the
    # historical /api/v1/reconciliacion-ingresos paths above are untouched)
    # -------------------------------------------------------------------
    documento_router = APIRouter(
        prefix="/api/v1/reconciliacion-ingresos-egresos",
        tags=["reconciliacion-ingresos-egresos-documento-soporte"],
    )

    # -------------------------------------------------------------------
    # POST /{clasificacion_id}/documento-soporte — Attach real document
    # -------------------------------------------------------------------
    @documento_router.post(
        "/{clasificacion_id}/documento-soporte",
        summary="Adjuntar documento de soporte real a una clasificación ya hecha.",
        response_model=None,
    )
    def adjuntar_documento_soporte(
        clasificacion_id: str,
        req: DocumentoSoporteRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """REQ-IVA-003: adjunta el documento real (contrato de mutuo, acta
        de asamblea, contrato de garantía) que soporta una clasificación de
        depósito ya hecha (financiamiento/aportación de socio/garantía).

        Sin este adjunto, la clasificación queda en
        `estado_recaracterizacion="requiere_formalizacion"`
        ("pendiente_evidencia" en el criterio de aceptación) y
        `assert_puede_persistirse()` la rechaza — no puede incluirse en el
        papel de trabajo exportable
        (`GET .../reconciliacion-ingresos/papel-trabajo/{periodo}/exportable`).
        Nunca se acepta la sola "sospecha" de un depósito como evidencia
        (ADR-4): este endpoint es el único camino para registrar un
        documento real.
        """
        tenant_id = (auth_info.get("tenant_id") if auth_info else None) or req.tenant_id

        try:
            clas = service.adjuntar_documento_soporte(
                clasificacion_id,
                documento_soporte_id=req.documento_soporte_id,
                fecha_documento=req.fecha_documento,
                tenant_id=tenant_id,
            )
        except KeyError:
            # Mismo 404 tanto si el id no existe como si pertenece a otro
            # tenant — no se revela la existencia de clasificaciones ajenas.
            raise HTTPException(
                status_code=404,
                detail=f"Clasificación '{clasificacion_id}' no encontrada.",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        return {
            "ok": True,
            "message": f"Documento de soporte adjuntado a la clasificación '{clasificacion_id}'.",
            "clasificacion": clas.model_dump(),
        }

    # Combine both prefixes under a single router so
    # app.include_router(build_reconciliacion_ingresos_egresos_router(...))
    # keeps mounting every endpoint with one call, unchanged for callers.
    combined_router = APIRouter()
    combined_router.include_router(router)
    combined_router.include_router(documento_router)
    return combined_router
