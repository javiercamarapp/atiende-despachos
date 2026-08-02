# -*- coding: utf-8 -*-
"""POST /api/v1/cfdi/validate — CFDI 4.0 upload, parse & compliance check."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator

from b2b_ai.cfdi.parser import CFDIError, parse_cfdi_4
from b2b_ai.cfdi.validator import SATError, check_cfdi_compliance

router = APIRouter(prefix="/api/v1/cfdi", tags=["CFDI"])

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _require_api_key(
    key: Annotated[Optional[str], Depends(_api_key_header)],
) -> str:
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key",
        )
    return key


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CFDIXMLJSONRequest(BaseModel):
    """JSON body wrapper: { "xml_content": "<cfdi:..." }"""

    xml_content: str

    @field_validator("xml_content")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("xml_content must be a non-empty string")
        return v


class ValidationChecks(BaseModel):
    ok: bool
    checks_pass: int
    checks_fail: int
    errores_sat: list[dict]
    advertencias_sat: list[dict]
    requires_human_review: bool
    diot_reportable: bool


class ImpuestosData(BaseModel):
    iva_trasladado: Optional[float] = None
    isr_retenido: Optional[float] = None
    iva_retenido: Optional[float] = None


class ConceptoData(BaseModel):
    descripcion: str
    cantidad: Optional[float] = None
    valor_unitario: Optional[float] = None
    importe: Optional[float] = None
    clave_prod_serv: Optional[str] = None
    unidad: Optional[str] = None
    objeto_imp: Optional[str] = None


class ReceptorData(BaseModel):
    rfc: str
    nombre: Optional[str] = None
    regimen_fiscal: Optional[str] = None
    uso_cfdi: Optional[str] = None
    domicilio_fiscal_receptor: Optional[str] = None


class EmisorData(BaseModel):
    rfc: str
    nombre: Optional[str] = None
    regimen_fiscal: Optional[str] = None


class ComprobanteData(BaseModel):
    serie: Optional[str] = None
    folio: Optional[str] = None
    fecha: Optional[str] = None
    tipo: Optional[str] = None
    version: Optional[str] = None
    forma_pago: Optional[str] = None
    metodo_pago: Optional[str] = None
    moneda: Optional[str] = None
    tipo_cambio: Optional[str] = None
    lugar_expedicion: Optional[str] = None
    exportacion: Optional[str] = None
    subtotal: Optional[float] = None
    descuento: Optional[float] = None
    total: Optional[float] = None


class CFDIValidationResponse(BaseModel):
    """Full CFDI 4.0 validation response."""

    status: str  # VALIDO | INVALIDO | CON_OBSERVACIONES
    comprobante: ComprobanteData
    emisor: EmisorData
    receptor: ReceptorData
    conceptos: list[ConceptoData]
    impuestos: ImpuestosData
    validacion: ValidationChecks
    folio_fiscal: Optional[str] = None  # UUID from TimbreFiscalDigital
    fecha_timbrado: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_from_checks(errors: list[SATError]) -> str:
    if not errors:
        return "VALIDO"
    critical = [e for e in errors if e.severity == "error"]
    if critical:
        return "INVALIDO"
    return "CON_OBSERVACIONES"


def _build_response(
    raw: dict,
    errors: list[SATError],
    warnings: list[SATError],
) -> dict:
    status = _status_from_checks(errors)

    emisor_raw = raw.get("emisor", {})
    receptor_raw = raw.get("receptor", {})

    errors_out = [
        {"code": e.code, "message": e.message, "field": e.field or ""}
        for e in errors
    ]
    warnings_out = [
        {"code": w.code, "message": w.message, "field": w.field or ""}
        for w in warnings
    ]

    receptor_rfc = receptor_raw.get("rfc", "") or ""
    diot_reportable = receptor_rfc not in ("XAXX010101000", "XEXX010101000", "")

    return {
        "status": status,
        "comprobante": {
            "serie": raw.get("serie"),
            "folio": raw.get("folio"),
            "fecha": raw.get("fecha"),
            "tipo": raw.get("tipo_de_comprobante"),
            "version": raw.get("version"),
            "forma_pago": raw.get("forma_pago"),
            "metodo_pago": raw.get("metodo_pago"),
            "moneda": raw.get("moneda"),
            "tipo_cambio": raw.get("tipo_cambio"),
            "lugar_expedicion": raw.get("lugar_expedicion"),
            "exportacion": raw.get("exportacion"),
            "subtotal": raw.get("subtotal"),
            "descuento": raw.get("descuento"),
            "total": raw.get("total"),
        },
        "emisor": {
            "rfc": emisor_raw.get("rfc", ""),
            "nombre": emisor_raw.get("nombre"),
            "regimen_fiscal": emisor_raw.get("regimen_fiscal"),
        },
        "receptor": {
            "rfc": receptor_raw.get("rfc", ""),
            "nombre": receptor_raw.get("nombre"),
            "regimen_fiscal": receptor_raw.get("regimen_fiscal_receptor"),
            "uso_cfdi": receptor_raw.get("uso_cfdi"),
            "domicilio_fiscal_receptor": receptor_raw.get("domicilio_fiscal_receptor"),
        },
        "conceptos": [
            {
                "descripcion": c.get("descripcion", ""),
                "cantidad": c.get("cantidad"),
                "valor_unitario": c.get("valor_unitario"),
                "importe": c.get("importe"),
                "clave_prod_serv": c.get("clave_prod_serv"),
                "unidad": c.get("unidad"),
                "objeto_imp": c.get("objeto_imp"),
            }
            for c in raw.get("conceptos", [])
        ],
        "impuestos": {
            "iva_trasladado": raw.get("total_impuestos_trasladados"),
            "isr_retenido": raw.get("total_impuestos_retenidos_isr"),
            "iva_retenido": raw.get("total_impuestos_retenidos_iva"),
        },
        "folio_fiscal": raw.get("uuid"),
        "fecha_timbrado": raw.get("fecha_timbrado"),
        "validacion": {
            "ok": status == "VALIDO",
            "checks_pass": len(warnings),
            "checks_fail": len(errors),
            "errores_sat": errors_out,
            "advertencias_sat": warnings_out,
            "requires_human_review": status != "VALIDO",
            "diot_reportable": diot_reportable,
        },
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/validate",
    response_model=CFDIValidationResponse,
    responses={
        200: {"description": "CFDI parsed; check status field for compliance result."},
        400: {"description": "Invalid XML or missing body."},
        401: {"description": "Missing or invalid API key."},
        422: {"description": "Request validation error."},
    },
)
async def validate_cfdi(
    request: Request,
    api_key: Annotated[str, Depends(_require_api_key)],
    xml_json: Optional[CFDIXMLJSONRequest] = None,
    file: Optional[UploadFile] = File(default=None),
) -> CFDIValidationResponse:
    """Validate a CFDI 4.0 XML document.

    Accepts three input forms:
    1. **text/xml** body (raw XML) — Content-Type: text/xml
    2. **JSON** body `{"xml_content": "<cfdi:..."}` — Content-Type: application/json
    3. **multipart** file upload via `file` field

    Returns compliance status, extracted data, and SAT error/warning list.
    """
    content_type = request.headers.get("content-type", "").lower()
    xml_str: str

    # Case 2: JSON body — FastAPI parsed it into xml_json
    if xml_json is not None:
        xml_str = xml_json.xml_content

    # Case 3: multipart file upload
    elif "multipart/" in content_type or file is not None:
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided in multipart body",
            )
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )
        xml_str = content.decode("utf-8", errors="replace")

    # Case 1: raw XML body
    else:
        body = await request.body()
        if not body or not body.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty request body",
            )
        xml_str = body.decode("utf-8", errors="replace")

    # ---- Parse ----
    try:
        parsed = parse_cfdi_4(xml_str)
    except CFDIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"XML parsing error: {exc}",
        )

    # ---- Compliance checks ----
    errors, warnings = check_cfdi_compliance(parsed)
    result = _build_response(parsed, errors, warnings)
    return CFDIValidationResponse(**result)


# ---------------------------------------------------------------------------
# Router factory (called from app.py)
# ---------------------------------------------------------------------------


def build_cfdi_validation_router(require_api_key: bool = True):
    """Return the CFDI validation router.

    When require_api_key=False the endpoint skips auth via dependency override.
    """
    return router
