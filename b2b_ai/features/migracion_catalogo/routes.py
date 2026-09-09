# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router para la revisión humana de mapeos de
migración de catálogo (REQ-MIG-007).

Endpoints:
    POST /api/v1/migracion-catalogo/{mapeo_id}/aprobar
        Aprueba un mapeo pendiente tal cual fue propuesto.
    POST /api/v1/migracion-catalogo/{mapeo_id}/rechazar
        Rechaza un mapeo pendiente (exige nota de justificación).
    POST /api/v1/migracion-catalogo/{mapeo_id}/editar
        Corrige `destino_cuenta_id` de un mapeo pendiente y lo confirma
        (exige nota de justificación).

ADR-3 (docs/BLUEPRINT-AGENTES-FISCALES.md §3/§7): estos tres endpoints
son el ÚNICO código de este repo que mueve un `MapeoMigracionCuenta`
fuera de `estado=PENDIENTE`. El motor de matching (REQ-MIG-003..006)
solo lee/crea mapeos, nunca decide su revisión; el motor de migración de
pólizas (REQ-MIG-009, `migrador.py`) solo lee `estado` para decidir si
migra o lanza `MapeoNoAprobadoError` — nunca lo escribe.

REQ-MIG-008 (cardinalidad N:1 / 1:N): `/aprobar` y `/editar` delegan en
`MigracionCatalogoService._validar_cardinalidad_antes_de_confirmar` antes
de confirmar cualquier cambio. Un mapeo N:1 (varias cuentas origen hacia
el mismo destino) exige `estrategia_conciliacion_saldos` no nula
(`EstrategiaConciliacionRequeridaError` -> HTTP 422); un mapeo 1:N (la
misma cuenta origen hacia destinos distintos) se rechaza por completo,
sin excepción (`DivisionUnoANoAutomaticaError` -> HTTP 422, "división
1:N fuera de alcance automático").
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .service import (
    DecisionSinResponsableError,
    DivisionUnoANoAutomaticaError,
    EstrategiaConciliacionRequeridaError,
    MapeoNoEncontradoError,
    MigracionCatalogoService,
    TransicionEstadoInvalidaError,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AprobarRequest(BaseModel):
    """Body de POST /{mapeo_id}/aprobar."""
    decidido_por: str = Field(
        ..., min_length=1,
        description="Quién aprueba el mapeo (obligatorio, nunca anónimo)",
    )
    nota: Optional[str] = Field(
        default=None, description="Comentario opcional sobre la aprobación",
    )
    estrategia_conciliacion_saldos: Optional[str] = Field(
        default=None,
        description=(
            "Obligatoria (no nula) si este mapeo fusiona varias cuentas "
            "origen hacia el mismo destino (N:1, REQ-MIG-008)"
        ),
    )


class RechazarRequest(BaseModel):
    """Body de POST /{mapeo_id}/rechazar."""
    decidido_por: str = Field(
        ..., min_length=1,
        description="Quién rechaza el mapeo (obligatorio, nunca anónimo)",
    )
    nota: str = Field(
        ..., min_length=1,
        description="Justificación obligatoria del rechazo",
    )


class EditarRequest(BaseModel):
    """Body de POST /{mapeo_id}/editar."""
    decidido_por: str = Field(
        ..., min_length=1,
        description="Quién edita y confirma el mapeo (obligatorio, nunca anónimo)",
    )
    destino_cuenta_id: str = Field(
        ..., min_length=1,
        description="Cuenta destino corregida (nunca vacía ni inventada)",
    )
    nota: str = Field(
        ..., min_length=1,
        description="Justificación obligatoria del cambio de destino",
    )
    estrategia_conciliacion_saldos: Optional[str] = Field(
        default=None,
        description=(
            "Obligatoria (no nula) si el destino corregido fusiona varias "
            "cuentas origen hacia el mismo destino (N:1, REQ-MIG-008)"
        ),
    )


class MigracionCatalogoResponse(BaseModel):
    """Respuesta estándar de los endpoints de revisión de migración de
    catálogo."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_migracion_catalogo_router(
    require_api_key: Any = None,
    service: Optional[MigracionCatalogoService] = None,
) -> APIRouter:
    """Construye el router de revisión humana de migración de catálogo.

    Parameters
    ----------
    require_api_key : FastAPI dependency de autenticación. Obligatoria —
        nunca se construye este router sin auth, dado que aprobar o
        rechazar una reclasificación de cuenta con historial fiscal es
        una operación sensible.
    service : Optional[MigracionCatalogoService]
        Servicio de revisión ya inicializado (y, en tests o en el mismo
        proceso que el motor de matching, ya con mapeos registrados vía
        `service.registrar(...)`). Cuando es `None` se crea una
        instancia propia con repositorio en memoria vacío — solo útil
        para levantar el router de forma aislada; en producción dentro
        de este proceso debe pasarse la misma instancia usada para
        registrar los mapeos generados por el motor de matching.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    svc = service if service is not None else MigracionCatalogoService()

    router = APIRouter(prefix="/api/v1/migracion-catalogo", tags=["migracion-catalogo"])

    def _mapear_error_de_dominio(exc: Exception) -> HTTPException:
        if isinstance(exc, MapeoNoEncontradoError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(
            exc,
            (
                DecisionSinResponsableError,
                TransicionEstadoInvalidaError,
                DivisionUnoANoAutomaticaError,
                EstrategiaConciliacionRequeridaError,
                ValueError,
            ),
        ):
            return HTTPException(status_code=422, detail=str(exc))
        # No debería llegar aquí con las excepciones que el servicio
        # declara; re-lanzar sin envolver deja el 500 real visible en
        # vez de disfrazarlo de error de negocio.
        raise exc

    # -------------------------------------------------------------------
    # POST /{mapeo_id}/aprobar
    # -------------------------------------------------------------------
    @router.post(
        "/{mapeo_id}/aprobar",
        summary="Aprobar un mapeo pendiente tal cual (único camino a estado=aprobado).",
        response_model=None,
    )
    def aprobar(
        mapeo_id: str,
        req: AprobarRequest,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        try:
            mapeo = svc.aprobar(
                mapeo_id,
                decidido_por=req.decidido_por,
                nota=req.nota,
                estrategia_conciliacion_saldos=req.estrategia_conciliacion_saldos,
            )
        except (
            MapeoNoEncontradoError,
            DecisionSinResponsableError,
            TransicionEstadoInvalidaError,
            DivisionUnoANoAutomaticaError,
            EstrategiaConciliacionRequeridaError,
            ValueError,
        ) as e:
            raise _mapear_error_de_dominio(e)
        return {
            "ok": True,
            "message": f"Mapeo {mapeo_id} aprobado por {req.decidido_por}.",
            "data": mapeo.model_dump(),
        }

    # -------------------------------------------------------------------
    # POST /{mapeo_id}/rechazar
    # -------------------------------------------------------------------
    @router.post(
        "/{mapeo_id}/rechazar",
        summary="Rechazar un mapeo pendiente (exige nota de justificación).",
        response_model=None,
    )
    def rechazar(
        mapeo_id: str,
        req: RechazarRequest,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        try:
            mapeo = svc.rechazar(mapeo_id, decidido_por=req.decidido_por, nota=req.nota)
        except (MapeoNoEncontradoError, DecisionSinResponsableError, TransicionEstadoInvalidaError, ValueError) as e:
            raise _mapear_error_de_dominio(e)
        return {
            "ok": True,
            "message": f"Mapeo {mapeo_id} rechazado por {req.decidido_por}.",
            "data": mapeo.model_dump(),
        }

    # -------------------------------------------------------------------
    # POST /{mapeo_id}/editar
    # -------------------------------------------------------------------
    @router.post(
        "/{mapeo_id}/editar",
        summary="Corregir destino_cuenta_id de un mapeo pendiente y confirmarlo.",
        response_model=None,
    )
    def editar(
        mapeo_id: str,
        req: EditarRequest,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        try:
            mapeo = svc.editar(
                mapeo_id,
                decidido_por=req.decidido_por,
                destino_cuenta_id=req.destino_cuenta_id,
                nota=req.nota,
                estrategia_conciliacion_saldos=req.estrategia_conciliacion_saldos,
            )
        except (
            MapeoNoEncontradoError,
            DecisionSinResponsableError,
            TransicionEstadoInvalidaError,
            DivisionUnoANoAutomaticaError,
            EstrategiaConciliacionRequeridaError,
            ValueError,
        ) as e:
            raise _mapear_error_de_dominio(e)
        return {
            "ok": True,
            "message": f"Mapeo {mapeo_id} editado por {req.decidido_por}.",
            "data": mapeo.model_dump(),
        }

    return router
