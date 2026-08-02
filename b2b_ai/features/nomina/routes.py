# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de nómina.

Endpoints:
    POST /nomina/parse     — Sube XML CFDI 4.0, retorna datos Nomina 1.2.
    POST /nomina/validate  — Sube XML CFDI 4.0, retorna errores de validación.
    GET  /nomina/catalog   — Catálogo SAT de códigos de nómina.
    POST /nomina/records   — Crea un registro de nómina (payroll).
    GET  /nomina/records   — Lista nóminas con filtros (period, employee, status).
    GET  /nomina/records/{id}              — Detalle de una nómina.
    POST /nomina/records/{id}/validate     — Valida (DRAFT → VALIDATED).
    POST /nomina/records/{id}/pay          — Marca como pagada.
    POST /nomina/records/{id}/void         — Anula.
    POST /nomina/records/{id}/concepts     — Agrega un concepto.
    GET  /nomina/records/{id}/concepts     — Lista conceptos.
    GET  /nomina/summary   — Resumen agregado por periodo.
    GET  /nomina/export    — Exporta nóminas a CSV.

El router se construye con `build_nomina_router()` para inyectar DB y
dependencias de auth en tests. Los endpoints de payroll exigen auth
(`require_api_key`) y aislamiento multi-tenant (se lee tenant_id del contexto
de auth); se registran solo si `require_api_key` se provee.
"""
from __future__ import annotations

import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

from b2b_ai.features.nomina.parser import parse_nomina, parse_nomina_bytes
from b2b_ai.features.nomina.validators import (
    validate_nomina,
    PERIODICIDAD_PAGO_CODES,
    TIPO_NOMINA_CODES,
    TIPO_JORNADA_CODES,
    RIESGO_PUESTO_CODES,
)
from b2b_ai.features.nomina.models import (
    NominaRecordCreate,
    NominaStatus,
    NominaConcept,
    ConceptType,
)
from b2b_ai.features.nomina.service import (
    NominaManager,
    PayrollSummaryGenerator,
    _reset_state,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NominaCatalog(BaseModel):
    """Catálogo SAT de códigos de nómina."""
    periodicidad_pago: dict
    tipo_nomina: dict
    tipo_jornada: dict
    riesgo_puesto: dict


class ConceptRequest(BaseModel):
    """Request para agregar un concepto a una nómina."""
    concept_type: ConceptType
    concept_code: str = ""
    description: str = ""
    amount: float = 0.0
    taxable: bool = True


# ---------------------------------------------------------------------------
# Helpers de tenant / auth
# ---------------------------------------------------------------------------

def _require_tenant(auth_info: dict) -> str:
    """Extrae tenant_id del contexto de auth; rechaza si no está presente."""
    tenant_id = (auth_info or {}).get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Falta tenant_id en el contexto de autenticación.",
        )
    return str(tenant_id)


def _record_or_404(service: NominaManager, record_id: str, tenant_id: str):
    """Devuelve la nómina o 404 (sin filtrar existencia cross-tenant)."""
    try:
        return service.get_record(record_id, tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_nomina_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /nomina/*.

    Sigue el patrón `build_*_router()` del proyecto para inyección de DB.
    Los endpoints de parser/validación no requieren auth por ser parsing/
    validación local (sin persistencia). Los endpoints de payroll (records,
    summary, export) exigen auth multi-tenant y se registran solo cuando
    `require_api_key` se provee.
    """
    router = APIRouter(prefix="/nomina", tags=["nomina"])
    if require_api_key:
        router.dependencies.append(Depends(require_api_key))

    @router.post(
        "/parse",
        summary="Parsea complemento Nomina 1.2 de un CFDI XML.",
        response_model=None,
    )
    async def parse_nomina_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo CFDI 4.0 (XML) y extrae el complemento Nomina 1.2.

        Retorna los campos de nómina como JSON o 404 si no hay complemento.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_nomina_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="El XML no contiene complemento de Nómina 1.2.",
            )

        return {"ok": True, "nomina": data.to_dict()}

    @router.post(
        "/validate",
        summary="Valida un CFDI con complemento Nomina 1.2 contra reglas SAT.",
        response_model=None,
    )
    async def validate_nomina_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo CFDI 4.0 (XML) y valida su complemento Nomina.

        Retorna errores de validación (lista vacía = válido).
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_nomina_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        errors = validate_nomina(data)
        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "nomina": data.to_dict() if data is not None else None,
        }

    @router.get(
        "/catalog",
        summary="Catálogo SAT de códigos de nómina.",
    )
    def nomina_catalog():
        """Retorna los catálogos SAT para código de periodicidad, tipo nómina,
        tipo de jornada y riesgo del puesto.
        """
        return {
            "periodicidad_pago": PERIODICIDAD_PAGO_CODES,
            "tipo_nomina": TIPO_NOMINA_CODES,
            "tipo_jornada": TIPO_JORNADA_CODES,
            "riesgo_puesto": RIESGO_PUESTO_CODES,
        }

    # ------------------------------------------------------------------
    # Endpoints de payroll (solo con auth multi-tenant)
    # ------------------------------------------------------------------
    if require_api_key is not None:
        _add_payroll_endpoints(router, require_api_key)

    return router


def _add_payroll_endpoints(router: APIRouter, require_api_key) -> None:
    """Registra los endpoints de payroll (records/summary/export) en el router.

    Exigen `require_api_key` y aislamiento multi-tenant. Usa un `NominaManager`
    y un `PayrollSummaryGenerator` por build (estado en memoria compartido por
    el módulo service, con `_reset_state()` para tests).
    """
    service = NominaManager()
    summary_gen = PayrollSummaryGenerator()

    @router.post(
        "/records",
        summary="Crea un registro de nómina (payroll).",
        response_model=None,
    )
    def create_record(
        req: NominaRecordCreate,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            record = service.create_nomina_record(tenant_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "record": record.to_dict()}

    @router.get(
        "/records",
        summary="Lista nóminas con filtros (period, employee, status).",
        response_model=None,
    )
    def list_records(
        period: Optional[str] = Query(default=None),
        employee: Optional[str] = Query(default=None),
        status: Optional[NominaStatus] = Query(default=None),
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        records = service.list_records(
            tenant_id, period=period, employee=employee, status=status
        )
        return {
            "ok": True,
            "count": len(records),
            "records": [r.to_dict() for r in records],
        }

    @router.get(
        "/records/{record_id}",
        summary="Detalle de una nómina (aislado por tenant).",
        response_model=None,
    )
    def get_record(
        record_id: str,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        record = _record_or_404(service, record_id, tenant_id)
        return {"ok": True, "record": record.to_dict()}

    @router.post(
        "/records/{record_id}/validate",
        summary="Valida una nómina (DRAFT → VALIDATED).",
        response_model=None,
    )
    def validate_record(
        record_id: str,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _record_or_404(service, record_id, tenant_id)
        try:
            record = service.validate_payroll(record_id, tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "record": record.to_dict()}

    @router.post(
        "/records/{record_id}/pay",
        summary="Marca una nómina como pagada (debe estar VALIDATED).",
        response_model=None,
    )
    def pay_record(
        record_id: str,
        payment_date: Optional[str] = Query(default=None),
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _record_or_404(service, record_id, tenant_id)
        try:
            record = service.mark_paid(record_id, tenant_id, payment_date=payment_date)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "record": record.to_dict()}

    @router.post(
        "/records/{record_id}/void",
        summary="Anula una nómina (no puede estar pagada).",
        response_model=None,
    )
    def void_record(
        record_id: str,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _record_or_404(service, record_id, tenant_id)
        try:
            record = service.void_payroll(record_id, tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "record": record.to_dict()}

    @router.post(
        "/records/{record_id}/concepts",
        summary="Agrega un concepto (percepción/deducción) a una nómina.",
        response_model=None,
    )
    def add_concept(
        record_id: str,
        req: ConceptRequest,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _record_or_404(service, record_id, tenant_id)
        concept = NominaConcept(
            nomina_id=record_id,
            tenant_id=tenant_id,
            concept_type=req.concept_type,
            concept_code=req.concept_code,
            description=req.description,
            amount=req.amount,
            taxable=req.taxable,
        )
        saved = service.add_concept(record_id, tenant_id, concept)
        return {"ok": True, "concept": saved.to_dict()}

    @router.get(
        "/records/{record_id}/concepts",
        summary="Lista conceptos de una nómina.",
        response_model=None,
    )
    def list_concepts(
        record_id: str,
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _record_or_404(service, record_id, tenant_id)
        concepts = service.get_concepts(record_id, tenant_id)
        return {
            "ok": True,
            "count": len(concepts),
            "concepts": [c.to_dict() for c in concepts],
        }

    @router.get(
        "/summary",
        summary="Resumen agregado de nómina por periodo.",
        response_model=None,
    )
    def payroll_summary(
        period: str = Query(..., description="Periodo YYYY-MM"),
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        summary = summary_gen.generate_summary(tenant_id, period)
        return {"ok": True, "summary": summary.to_dict()}

    @router.get(
        "/export",
        summary="Exporta nóminas del periodo a CSV.",
        response_model=None,
    )
    def export_csv(
        period: str = Query(..., description="Periodo YYYY-MM"),
        auth_info: dict = Depends(require_api_key),
    ):
        tenant_id = _require_tenant(auth_info)
        csv_content = summary_gen.export_to_csv(tenant_id, period)
        return io.StringIO(csv_content).getvalue()
