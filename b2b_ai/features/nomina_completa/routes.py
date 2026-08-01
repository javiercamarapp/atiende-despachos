# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Nómina Completa.

Endpoints:
    POST /nomina-completa/process   — Procesa nómina completa del periodo.
    POST /nomina-completa/cfdi      — Genera CFDI de Nómina 1.2.
    GET  /nomina-completa/payslip/{id} — Descarga recibo de nómina.
    GET  /nomina-completa/summary   — Resumen del periodo procesado.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.nomina_completa.service import (
    calculate_taxes,
    generate_cfdi_nomina,
    generate_payslip,
    process_payroll,
)
from b2b_ai.features.nomina_completa.models import PayrollPeriod


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class ProcessPayrollRequest(BaseModel):
    """Request para procesar nómina completa."""
    period: dict = Field(..., description="Periodo: {month, year, dias_pagados}")
    employees: list[dict] = Field(..., description="Lista de empleados con salario")
    tenant_id: Optional[int] = None


class CFDINominaRequest(BaseModel):
    """Request para generar CFDI de Nómina."""
    payroll_data: dict = Field(..., description="Datos de nómina procesada")


class TaxesRequest(BaseModel):
    """Request para calcular impuestos individuales."""
    salary: float = Field(..., description="Salario bruto mensual")
    benefits: float = Field(0.0, description="Prestaciones gravables")
    salary_per_day: float = Field(0.0, description="Salario diario (opcional)")


class PayslipRequest(BaseModel):
    """Request para generar recibo de nómina."""
    payroll_data: dict = Field(..., description="Datos del empleado y periodo")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_nomina_completa_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /nomina-completa/*.

    Almacena nóminas procesadas en memoria (MVP).
    """
    from fastapi import Depends as _Depends
    router = APIRouter(prefix="/nomina-completa", tags=["nomina-completa"])
    _auth = [_Depends(require_api_key)] if require_api_key else []

    # Almacén de nóminas procesadas
    _processed: dict[str, dict] = {}

    @router.post(
        "/process",
        summary="Procesa nómina completa para un periodo.",
        response_model=None,
    )
    def procesar_nomina(req: ProcessPayrollRequest):
        """Calcula ISR, IMSS e INFONAVIT para cada empleado.

        Retorna el periodo de nómina con desglose por empleado y totales.
        """
        period_obj = process_payroll(
            period=req.period,
            employees=req.employees,
            tenant_id=req.tenant_id,
        )
        result = period_obj.to_dict()
        key = f"{req.tenant_id or 'default'}-{req.period.get('year', 2026)}-{req.period.get('month', 1):02d}"
        _processed[key] = result
        return {"ok": True, "payroll": result}

    @router.post(
        "/cfdi",
        summary="Genera un CFDI de Nómina 1.2.",
        response_model=None,
    )
    def generar_cfdi(req: CFDINominaRequest):
        """Genera un CFDI de nómina a partir de datos procesados.

        En producción incluiría timbrado SAT.
        """
        cfdi = generate_cfdi_nomina(req.payroll_data)
        return {"ok": True, "cfdi": cfdi}

    @router.get(
        "/payslip/{employee_id}",
        summary="Descarga el recibo de nómina de un empleado.",
        response_model=None,
    )
    def descargar_payslip(
        employee_id: str,
        month: int = Query(..., ge=1, le=12),
        year: int = Query(..., ge=2020),
        tenant_id: Optional[int] = Query(default=None),
    ):
        """Retorna el recibo de nómina individual de un empleado."""
        key = f"{tenant_id or 'default'}-{year}-{month:02d}"
        period_data = _processed.get(key)
        if not period_data:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró nómina procesada para {year}-{month:02d}.",
            )
        # Buscar empleado
        emp_data = None
        for emp in period_data.get("employees", []):
            if emp.get("employee_id") == employee_id:
                emp_data = emp
                break
        if emp_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Empleado {employee_id} no encontrado en el periodo.",
            )
        payslip = generate_payslip({
            "employee": emp_data,
            "period": {"month": month, "year": year},
            "taxes": emp_data.get("taxes", {}),
            "sueldo_base": emp_data.get("salario_bruto", 0),
            "bonos": 0,
            "prestaciones": emp_data.get("percepciones", 0),
            "subtotal": emp_data.get("salario_bruto", 0) + emp_data.get("percepciones", 0),
            "neto": emp_data.get("neto", 0),
        })
        return {"ok": True, "payslip": payslip}

    @router.get(
        "/summary",
        summary="Resumen de nómina procesada por periodo.",
        response_model=None,
    )
    def resumen_nomina(
        month: int = Query(..., ge=1, le=12),
        year: int = Query(..., ge=2020),
        tenant_id: Optional[int] = Query(default=None),
    ):
        """Retorna el resumen agregado de un periodo de nómina."""
        key = f"{tenant_id or 'default'}-{year}-{month:02d}"
        period_data = _processed.get(key)
        if not period_data:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró nómina procesada para {year}-{month:02d}.",
            )
        return {
            "ok": True,
            "summary": {
                "period": f"{year}-{month:02d}",
                "employee_count": period_data.get("employee_count", 0),
                "totals": period_data.get("totals", {}),
            },
        }

    @router.post(
        "/taxes",
        summary="Calcula impuestos individuales (ISR, IMSS, INFONAVIT).",
        response_model=None,
    )
    def calcular_impuestos(req: TaxesRequest):
        """Calcula los impuestos de nómina para un salario individual."""
        taxes = calculate_taxes(
            salary=req.salary,
            benefits=req.benefits,
            salary_per_day=req.salary_per_day,
        )
        return {"ok": True, "taxes": taxes.to_dict()}

    return router
