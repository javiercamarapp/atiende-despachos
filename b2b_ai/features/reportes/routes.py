# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Reportes.

Endpoints:
    POST /reportes/balance             — Genera Balance General.
    POST /reportes/estado-resultados   — Genera Estado de Resultados.
    POST /reportes/conciliacion        — Genera Conciliación Bancaria.
    POST /reportes/nomina              — Genera Reporte de Nómina.
    GET  /reportes/formats             — Lista formatos soportados.

El router se construye con `build_reportes_router()` para inyectar DB y
dependencias de auth en tests.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.reportes.generator import (
    generate_balance_general,
    generate_estado_resultados,
    generate_conciliacion_bancaria,
    generate_reporte_nomina,
)
from b2b_ai.features.reportes.serializers import (
    serialize,
    serialize_json,
    serialize_csv,
    serialize_html,
    SUPPORTED_FORMATS,
)


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class BalanceRequest(BaseModel):
    """Request para generar Balance General."""
    activos_circulantes: list[dict] = Field(default_factory=list, description="Activos circulantes")
    activos_fijos: list[dict] = Field(default_factory=list, description="Activos fijos")
    pasivos_circulantes: list[dict] = Field(default_factory=list, description="Pasivos circulantes")
    pasivos_largo_plazo: list[dict] = Field(default_factory=list, description="Pasivos a largo plazo")
    capital_contable: list[dict] = Field(default_factory=list, description="Capital contable")
    empresa_rfc: str = Field(default="", description="RFC de la empresa")
    empresa_nombre: str = Field(default="", description="Nombre de la empresa")
    periodo_inicio: str = Field(default="", description="Fecha de inicio del periodo (YYYY-MM-DD)")
    periodo_fin: str = Field(default="", description="Fecha de fin del periodo (YYYY-MM-DD)")
    formato: str = Field(default="json", description="Formato de salida: json, csv, html")


class EstadoResultadosRequest(BaseModel):
    """Request para generar Estado de Resultados."""
    ingresos: list[dict] = Field(default_factory=list)
    costos: list[dict] = Field(default_factory=list)
    gastos_operacion: list[dict] = Field(default_factory=list)
    gastos_administracion: list[dict] = Field(default_factory=list)
    otros_ingresos: list[dict] = Field(default_factory=list)
    impuestos: list[dict] = Field(default_factory=list)
    empresa_rfc: str = Field(default="")
    empresa_nombre: str = Field(default="")
    periodo_inicio: str = Field(default="")
    periodo_fin: str = Field(default="")
    formato: str = Field(default="json")


class ConciliacionRequest(BaseModel):
    """Request para generar Conciliación Bancaria."""
    movimientos_banco: list[dict] = Field(default_factory=list)
    movimientos_contabilidad: list[dict] = Field(default_factory=list)
    empresa_rfc: str = Field(default="")
    empresa_nombre: str = Field(default="")
    periodo_inicio: str = Field(default="")
    periodo_fin: str = Field(default="")
    banco_nombre: str = Field(default="")
    numero_cuenta: str = Field(default="")
    formato: str = Field(default="json")


class NominaRequest(BaseModel):
    """Request para generar Reporte de Nómina."""
    empleados: list[dict] = Field(default_factory=list)
    empresa_rfc: str = Field(default="")
    empresa_nombre: str = Field(default="")
    periodo_inicio: str = Field(default="")
    periodo_fin: str = Field(default="")
    periodo_pago: str = Field(default="")
    tipo_nomina: str = Field(default="O", description="O=Ordinaria, E=Extraordinaria")
    formato: str = Field(default="json")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _format_response(report, formato: str):
    """Devuelve la respuesta en el formato solicitado."""
    if formato == "html":
        return HTMLResponse(content=serialize_html(report), status_code=200)
    elif formato == "csv":
        return PlainTextResponse(
            content=serialize_csv(report),
            status_code=200,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=reporte_{report.metadata.get('tipo_reporte', 'reporte')}.csv"},
        )
    elif formato == "json":
        return JSONResponse(content=report.to_dict(), status_code=200)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado: {formato}. Use: {', '.join(SUPPORTED_FORMATS)}",
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_reportes_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /reportes/*.

    Sigue el patrón `build_*_router()` del proyecto para inyección de DB.
    Los endpoints de reportes no requieren auth por ser generación
    de documentos desde datos proporcionados por el cliente.
    """
    router = APIRouter(prefix="/reportes", tags=["reportes"])
    if require_api_key:
        router.dependencies.append(Depends(require_api_key))

    @router.post(
        "/balance",
        summary="Genera un Balance General (Estado de Situación Financiera).",
        response_model=None,
    )
    def generar_balance(req: BalanceRequest):
        """Genera un Balance General con activos, pasivos y capital contable.

        Acepta datos en JSON y retorna el reporte en el formato solicitado
        (json, csv o html).
        """
        report = generate_balance_general(
            activos_circulantes=req.activos_circulantes,
            activos_fijos=req.activos_fijos,
            pasivos_circulantes=req.pasivos_circulantes,
            pasivos_largo_plazo=req.pasivos_largo_plazo,
            capital_contable=req.capital_contable,
            empresa_rfc=req.empresa_rfc,
            empresa_nombre=req.empresa_nombre,
            periodo_inicio=req.periodo_inicio,
            periodo_fin=req.periodo_fin,
        )
        return _format_response(report, req.formato)

    @router.post(
        "/estado-resultados",
        summary="Genera un Estado de Resultados.",
        response_model=None,
    )
    def generar_estado_resultados(req: EstadoResultadosRequest):
        """Genera un Estado de Resultados con ingresos, costos, gastos
        y cálculo de utilidad neta.

        Acepta datos en JSON y retorna el reporte en el formato solicitado.
        """
        report = generate_estado_resultados(
            ingresos=req.ingresos,
            costos=req.costos,
            gastos_operacion=req.gastos_operacion,
            gastos_administracion=req.gastos_administracion,
            otros_ingresos=req.otros_ingresos,
            impuestos=req.impuestos,
            empresa_rfc=req.empresa_rfc,
            empresa_nombre=req.empresa_nombre,
            periodo_inicio=req.periodo_inicio,
            periodo_fin=req.periodo_fin,
        )
        return _format_response(report, req.formato)

    @router.post(
        "/conciliacion",
        summary="Genera un reporte de Conciliación Bancaria.",
        response_model=None,
    )
    def generar_conciliacion(req: ConciliacionRequest):
        """Genera un reporte de Conciliación Bancaria comparando movimientos
        del banco contra los de contabilidad.

        Acepta datos en JSON y retorna el reporte en el formato solicitado.
        """
        report = generate_conciliacion_bancaria(
            movimientos_banco=req.movimientos_banco,
            movimientos_contabilidad=req.movimientos_contabilidad,
            empresa_rfc=req.empresa_rfc,
            empresa_nombre=req.empresa_nombre,
            periodo_inicio=req.periodo_inicio,
            periodo_fin=req.periodo_fin,
            banco_nombre=req.banco_nombre,
            numero_cuenta=req.numero_cuenta,
        )
        return _format_response(report, req.formato)

    @router.post(
        "/nomina",
        summary="Genera un Reporte de Nómina por periodo.",
        response_model=None,
    )
    def generar_nomina(req: NominaRequest):
        """Genera un reporte de nómina con resumen por empleado y departamento.

        Acepta datos en JSON y retorna el reporte en el formato solicitado.
        """
        report = generate_reporte_nomina(
            empleados=req.empleados,
            empresa_rfc=req.empresa_rfc,
            empresa_nombre=req.empresa_nombre,
            periodo_inicio=req.periodo_inicio,
            periodo_fin=req.periodo_fin,
            periodo_pago=req.periodo_pago,
            tipo_nomina=req.tipo_nomina,
        )
        return _format_response(report, req.formato)

    @router.get(
        "/formats",
        summary="Lista los formatos de salida disponibles.",
    )
    def listar_formatos():
        """Retorna los formatos soportados por los endpoints de reportes."""
        return {
            "formats": [
                {"name": "json", "description": "JSON estructurado"},
                {"name": "csv", "description": "CSV plano para importación"},
                {"name": "html", "description": "HTML profesional con estilos inline"},
            ]
        }

    return router
