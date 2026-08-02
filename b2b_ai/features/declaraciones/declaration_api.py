# -*- coding: utf-8 -*-
"""declaration_api.py — API endpoints for the autonomous declaration engine.

Endpoints:
  POST /api/v1/declarations/calculate  — Calculate taxes (IVA, ISR, IEPS, DIOT)
  POST /api/v1/declarations/generate   — Generate XML/DIOT file
  POST /api/v1/declarations/submit     — Submit to SAT (with FIEL signing)
  GET  /api/v1/declarations/status     — Check submission status

Integrates: DeclarationEngine, DIOTGenerator, XMLGenerator, FIELSigner,
            SATSubmitter, ErrorHandler.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .engine import (
    DeclarationEngine,
    IvaResult,
    IsrResult,
    IepsResult,
    DiotResult,
    DiotRecord,
)
from .diot_generator import DIOTGenerator
from .xml_generator import XMLGenerator
from .sat_submitter import SATSubmitter, SubmissionStatus
from .error_handler import SATErrorHandler, ErrorCode


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CalculateRequest(BaseModel):
    """Request for tax calculation."""
    tenant_id: str = Field(..., description="Tenant identifier")
    rfc: str = Field(..., description="RFC del contribuyente")
    periodo: str = Field(..., description="Periodo (YYYY-MM o YYYY)")
    tipo_contribuyente: str = Field(
        default="PM",
        description="PM (persona moral) o PF (persona física)",
    )
    # ISR inputs
    ingresos: float = Field(default=0.0, description="Ingresos del periodo")
    deducciones: float = Field(default=0.0, description="Deducciones autorizadas")
    pagos_provisionales: float = Field(
        default=0.0, description="Pagos provisionales anteriores"
    )
    # IVA inputs
    iva_trasladado: float = Field(
        default=0.0, description="IVA trasladado (cobrado)"
    )
    iva_acreditable: float = Field(
        default=0.0, description="IVA acreditable (pagado)"
    )
    ingresos_gravados: float = Field(
        default=0.0, description="Ingresos gravados (para proporción IVA)"
    )
    ingresos_totales: float = Field(
        default=0.0, description="Ingresos totales (para proporción IVA)"
    )
    # IEPS inputs
    ieps_items: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Lista de productos IEPS"
    )
    # DIOT inputs (optional: if provided, also generate DIOT)
    invoices: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="CFDIs para DIOT"
    )
    annual: bool = Field(
        default=False, description="Calcular ISR anual (solo PF)"
    )


class CalculateResponse(BaseModel):
    """Response for tax calculation."""
    ok: bool
    isr: Optional[Dict[str, Any]] = None
    iva: Optional[Dict[str, Any]] = None
    ieps: Optional[Dict[str, Any]] = None
    diot: Optional[Dict[str, Any]] = None


class GenerateRequest(BaseModel):
    """Request for XML/file generation."""
    tenant_id: str = Field(..., description="Tenant identifier")
    rfc: str = Field(..., description="RFC del contribuyente")
    periodo: str = Field(..., description="Periodo (YYYY-MM o YYYY)")
    tipo: str = Field(
        ..., description="Tipo de declaración: iva, isr_provisional, isr_anual, diot"
    )
    # Pre-calculated data (from /calculate or provided directly)
    data: Dict[str, Any] = Field(
        ..., description="Datos calculados del impuesto"
    )
    # DIOT-specific
    invoices: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="CFDIs para DIOT"
    )


class GenerateResponse(BaseModel):
    """Response for XML/file generation."""
    ok: bool
    tipo: str
    periodo: str
    xml_content: Optional[str] = None  # Base64-encoded
    diot_content: Optional[str] = None  # Pipe-delimited text
    filename: str = ""
    errors: List[str] = []
    warnings: List[str] = []


class SubmitRequest(BaseModel):
    """Request for SAT submission."""
    declaration_id: str = Field(..., description="Internal declaration ID")
    tenant_id: str = Field(..., description="Tenant identifier")
    rfc: str = Field(..., description="RFC del contribuyente")
    periodo: str = Field(..., description="Periodo")
    tipo: str = Field(..., description="Tipo de declaración")
    xml_signed: str = Field(
        ..., description="XML firmado (base64-encoded)"
    )
    # Certificate paths (read from server-side filesystem only)
    cer_path: Optional[str] = Field(
        default=None, description="Ruta al certificado .cer (solo servidor)"
    )
    key_path: Optional[str] = Field(
        default=None, description="Ruta a llave .key (solo servidor)"
    )
    password: Optional[str] = Field(
        default=None, description="Contraseña FIEL/CSD"
    )
    test_mode: bool = Field(
        default=True, description="Modo simulación (no envía al SAT real)"
    )


class SubmitResponse(BaseModel):
    """Response for SAT submission."""
    ok: bool
    status: str
    folio: Optional[str] = None
    mensaje: str = ""
    errors: List[str] = []
    declaration_id: Optional[str] = None


class StatusResponse(BaseModel):
    """Response for status check."""
    ok: bool
    declaration_id: str
    status: str
    folio: Optional[str] = None
    fecha_recepcion: Optional[str] = None
    mensaje: str = ""


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_declarations_api_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the declarations API router.

    Parameters
    ----------
    db : Database instance (unused for now; engine is stateless).
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # Initialize components
    engine = DeclarationEngine()
    diot_gen = DIOTGenerator()
    xml_gen = XMLGenerator()
    error_handler = SATErrorHandler()
    submitter = SATSubmitter(test_mode=True)  # Default test mode

    router = APIRouter(prefix="/api/v1/declarations", tags=["declarations"])

    # -- Calculate taxes ---------------------------------------------------
    @router.post(
        "/calculate",
        summary="Calculate taxes (IVA, ISR, IEPS, DIOT)",
        response_model=CalculateResponse,
    )
    def calculate(
        req: CalculateRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> CalculateResponse:
        """Calculate all applicable taxes for a period.

        Supports:
          - ISR provisional (PM 30% / PF progressive table)
          - IVA monthly (trasladado – acreditable)
          - IEPS (per-product tasa/tarifa)
          - DIOT aggregation (if invoices provided)
        """
        result = CalculateResponse(ok=True)

        # ISR calculation
        if req.ingresos > 0 or req.deducciones > 0:
            if req.tipo_contribuyente.upper() == "PM":
                utilidad = req.ingresos - req.deducciones
                isr = engine.calculate_isr_pm(
                    utilidad_fiscal=utilidad,
                    pagos_provisionales=req.pagos_provisionales,
                )
            else:
                isr = engine.calculate_isr_pf(
                    base_gravable=req.ingresos - req.deducciones,
                    annual=req.annual,
                    pagos_provisionales=req.pagos_provisionales,
                )
            result.isr = {
                "base_gravable": isr.base_gravable,
                "isr_bruto": isr.isr_bruto,
                "tasa_efectiva": isr.tasa_efectiva,
                "tipo_contribuyente": isr.tipo_contribuyente,
                "tabla_aplicada": isr.tabla_aplicada,
                "isr_neto": isr.isr_neto,
                "pagos_provisionales": isr.pagos_provisionales,
            }

        # IVA calculation
        if req.iva_trasladado > 0 or req.iva_acreditable > 0:
            iva = engine.calculate_iva(
                iva_trasladado=req.iva_trasladado,
                iva_acreditable=req.iva_acreditable,
                ingresos_gravados=req.ingresos_gravados or req.ingresos,
                ingresos_totales=req.ingresos_totales or req.ingresos,
            )
            result.iva = {
                "iva_trasladado": iva.iva_trasladado,
                "iva_acreditable": iva.iva_acreditable,
                "iva_neto": iva.iva_neto,
                "saldo_favor": iva.saldo_favor,
                "saldo_contra": iva.saldo_contra,
                "proporcion_acreditable": iva.proporcion_acreditable,
            }

        # IEPS calculation
        if req.ieps_items:
            ieps = engine.calculate_ieps(req.ieps_items)
            result.ieps = {
                "total_ieps": ieps.total_ieps,
                "entries": [
                    {
                        "concepto": e.concepto,
                        "producto_tipo": e.producto_tipo,
                        "base_gravable": e.base_gravable,
                        "tasa": e.tasa,
                        "ieps": e.ieps,
                    }
                    for e in ieps.entries
                ],
            }

        # DIOT aggregation
        if req.invoices:
            diot = engine.aggregate_diot(
                invoices=req.invoices,
                rfc_contribuyente=req.rfc,
                periodo=req.periodo,
            )
            result.diot = {
                "total_records": diot.total_records,
                "total_monto_neto": diot.total_monto_neto,
                "total_iva_trasladado": diot.total_iva_trasladado,
                "total_iva_acreditable": diot.total_iva_acreditable,
                "records_count": len(diot.records),
            }

        return result

    # -- Generate XML/DIOT file -------------------------------------------
    @router.post(
        "/generate",
        summary="Generate XML declaration or DIOT pipe-delimited file",
        response_model=GenerateResponse,
    )
    def generate(
        req: GenerateRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> GenerateResponse:
        """Generate the declaration file.

        For IVA/ISR: generates SAT-compliant XML.
        For DIOT: generates pipe-delimited TXT per RMF 3.10.7.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if req.tipo == "diot":
            # DIOT generation
            if not req.invoices:
                return GenerateResponse(
                    ok=False,
                    tipo=req.tipo,
                    periodo=req.periodo,
                    errors=["Se requiere 'invoices' para generar DIOT"],
                )

            diot = engine.aggregate_diot(
                invoices=req.invoices,
                rfc_contribuyente=req.rfc,
                periodo=req.periodo,
            )

            content = diot_gen.generate(diot)
            errors.extend(diot_gen.errors)
            warnings.extend(diot_gen.warnings)

            filename = (
                f"DIOT_{req.rfc}_{req.periodo.replace('-', '')}.txt"
            )

            return GenerateResponse(
                ok=len(errors) == 0,
                tipo=req.tipo,
                periodo=req.periodo,
                diot_content=content,
                filename=filename,
                errors=errors,
                warnings=warnings,
            )

        elif req.tipo in ("iva", "isr_provisional", "isr_anual"):
            # XML generation
            data = req.data

            if req.tipo == "iva":
                iva_result = IvaResult(
                    iva_trasladado=float(data.get("iva_trasladado", 0)),
                    iva_acreditable=float(data.get("iva_acreditable", 0)),
                    iva_neto=float(data.get("iva_neto", 0)),
                    saldo_favor=float(data.get("saldo_favor", 0)),
                    saldo_contra=float(data.get("saldo_contra", 0)),
                    proporcion_acreditable=float(
                        data.get("proporcion_acreditable", 1.0)
                    ),
                )
                xml_bytes = xml_gen.generate_iva_declaration(
                    rfc=req.rfc,
                    periodo=req.periodo,
                    iva_result=iva_result,
                )
            else:
                isr_result = IsrResult(
                    base_gravable=float(data.get("base_gravable", 0)),
                    isr_bruto=float(data.get("isr_bruto", 0)),
                    tasa_efectiva=float(data.get("tasa_efectiva", 0)),
                    tipo_contribuyente=data.get("tipo_contribuyente", "PM"),
                    tabla_aplicada=data.get("tabla_aplicada", "pm_30%"),
                    isr_neto=float(data.get("isr_neto", 0)),
                    pagos_provisionales=float(
                        data.get("pagos_provisionales", 0)
                    ),
                )
                xml_bytes = xml_gen.generate_isr_declaration(
                    rfc=req.rfc,
                    periodo=req.periodo,
                    isr_result=isr_result,
                )

            if not xml_gen.validate_xml_structure(xml_bytes):
                errors.extend(xml_gen.errors)

            import base64
            filename = (
                f"{req.tipo.upper()}_{req.rfc}_"
                f"{req.periodo.replace('-', '')}.xml"
            )

            return GenerateResponse(
                ok=len(errors) == 0,
                tipo=req.tipo,
                periodo=req.periodo,
                xml_content=base64.b64encode(xml_bytes).decode("ascii"),
                filename=filename,
                errors=errors,
                warnings=warnings,
            )

        else:
            return GenerateResponse(
                ok=False,
                tipo=req.tipo,
                periodo=req.periodo,
                errors=[f"Tipo de declaración no soportado: {req.tipo}"],
            )

    # -- Submit to SAT -----------------------------------------------------
    @router.post(
        "/submit",
        summary="Submit signed declaration to SAT",
        response_model=SubmitResponse,
    )
    def submit(
        req: SubmitRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> SubmitResponse:
        """Submit a signed declaration to SAT.

        Requires:
          - Signed XML (base64-encoded with Sello, Certificado, NoCertificado)
          - FIEL/CSD certificate paths (server-side only)

        Returns:
          - Status (accepted/rejected/error)
          - SAT folio (if accepted)
          - Error details (if rejected)
        """
        import base64

        try:
            xml_signed = base64.b64decode(req.xml_signed)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="xml_signed no es un base64 válido",
            )

        # Create submitter with provided credentials
        sub = SATSubmitter(
            cer_path=req.cer_path,
            key_path=req.key_path,
            password=req.password,
            test_mode=req.test_mode,
        )

        result = sub.submit_declaration(
            xml_signed=xml_signed,
            declaration_type=req.tipo,
            periodo=req.periodo,
            rfc=req.rfc,
            declaration_id=req.declaration_id,
        )

        # Handle errors if any
        errors = []
        if result.status == SubmissionStatus.ERROR:
            # Try to classify the error
            err_result = error_handler.handle_error(
                ErrorCode.XML_INVALIDO,
                details=result.mensaje,
            )
            errors.append(err_result.message)

        return SubmitResponse(
            ok=result.status in (SubmissionStatus.ACCEPTED, SubmissionStatus.SUBMITTED),
            status=result.status.value,
            folio=result.folio,
            mensaje=result.mensaje,
            errors=errors,
            declaration_id=result.declaration_id,
        )

    # -- Check status ------------------------------------------------------
    @router.get(
        "/status",
        summary="Check declaration submission status",
        response_model=StatusResponse,
    )
    def status(
        declaration_id: str = Query(..., description="Declaration ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> StatusResponse:
        """Check the status of a submitted declaration."""
        result = submitter.check_status(declaration_id)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Declaración '{declaration_id}' no encontrada",
            )

        return StatusResponse(
            ok=True,
            declaration_id=declaration_id,
            status=result.status.value,
            folio=result.folio,
            fecha_recepcion=result.fecha_recepcion,
            mensaje=result.mensaje,
        )

    return router
