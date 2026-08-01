# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración SAT (CFDI, Cancelación, RFC, Contabilidad Electrónica).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CFDIStatus(str, Enum):
    """Estados posibles de un CFDI."""
    TIMBRADO = "timbrado"
    CANCELADO = "cancelado"
    PENDIENTE = "pendiente"
    ERROR = "error"


class TipoCancelacion(str, Enum):
    """Motivos de cancelación de CFDI según SAT."""
    FACTURA_ERRORES = "01"
    FACTURA_CANCELACION = "02"
    CONCEPTOS_FACTURA = "03"
    FACTURA_DUPLICIDAD = "04"
    EMISOR_DEFINITIVO = "05"


class TipoComprobante(str, Enum):
    """Tipos de comprobante fiscal digital."""
    INGRESO = "I"
    EGRESO = "E"
    NOMINA = "N"
    TRASLADO = "T"
    PAGO = "P"


# ---------------------------------------------------------------------------
# CFDI Models
# ---------------------------------------------------------------------------

class CFDI(BaseModel):
    """CFDI timbrado."""
    uuid: str = Field(default="", description="UUID del CFDI")
    rfc_emisor: str = Field(default="", description="RFC del emisor")
    rfc_receptor: str = Field(default="", description="RFC del receptor")
    fecha: str = Field(default="", description="Fecha de emisión YYYY-MM-DD")
    subtotal: float = Field(default=0.0, ge=0, description="Subtotal antes de impuestos")
    iva: float = Field(default=0.0, ge=0, description="Monto del IVA")
    total: float = Field(default=0.0, ge=0, description="Total del comprobante")
    status: CFDIStatus = Field(default=CFDIStatus.PENDIENTE, description="Estado del CFDI")
    tipo: TipoComprobante = Field(default=TipoComprobante.INGRESO, description="Tipo de comprobante")
    serie: str = Field(default="", description="Serie del comprobante")
    folio: str = Field(default="", description="Folio del comprobante")
    rfc_emisor_nombre: str = Field(default="", description="Nombre del emisor")
    rfc_receptor_nombre: str = Field(default="", description="Nombre del receptor")
    regimen_fiscal_emisor: str = Field(default="", description="Régimen fiscal del emisor")
    uso_cfdi: str = Field(default="", description="Uso del CFDI")
    fecha_timbrado: Optional[str] = Field(default=None, description="Fecha de timbrado")
    timbre_fiscal_digital: Optional[str] = Field(default=None, description="Sello del timbre fiscal")
    no_certificado: str = Field(default="", description="Número de certificado")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "rfc_emisor": "XAXX010101000",
                "rfc_receptor": "AAA010101AAA",
                "fecha": "2026-01-15",
                "subtotal": 10000.00,
                "iva": 1600.00,
                "total": 11600.00,
                "status": "timbrado",
            }]
        }
    }


class CFDIRequest(BaseModel):
    """Datos para timbrar un CFDI."""
    rfc_emisor: str = Field(..., description="RFC del emisor")
    rfc_receptor: str = Field(..., description="RFC del receptor")
    fecha: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"),
                       description="Fecha de emisión")
    subtotal: float = Field(..., gt=0, description="Subtotal")
    iva: float = Field(default=0.0, ge=0, description="IVA")
    total: float = Field(..., gt=0, description="Total")
    tipo: TipoComprobante = Field(default=TipoComprobante.INGRESO)
    serie: str = Field(default="A")
    conceptos: List[Dict[str, Any]] = Field(default_factory=list, description="Conceptos del comprobante")
    regimen_fiscal: str = Field(default="601", description="Régimen fiscal del emisor")
    uso_cfdi: str = Field(default="G03", description="Uso del CFDI")
    metodo_pago: str = Field(default="PUE", description="Método de pago")
    forma_pago: str = Field(default="01", description="Forma de pago")
    lugar_expedicion: str = Field(default="06600", description="Código postal de expedición")


class CancelacionRequest(BaseModel):
    """Solicitud de cancelación de CFDI."""
    uuid: str = Field(..., description="UUID del CFDI a cancelar")
    motivo: TipoCancelacion = Field(..., description="Motivo de cancelación")
    rfc: str = Field(..., description="RFC del solicitante")
    fecha_cancelacion: Optional[str] = Field(default=None, description="Fecha de cancelación")
    uuid_sustitucion: Optional[str] = Field(default=None, description="UUID de sustitución (si aplica)")


class RFCStatus(BaseModel):
    """Estado de un RFC ante el SAT."""
    rfc: str = Field(..., description="RFC consultado")
    razon_social: str = Field(default="", description="Razón social")
    regimen_fiscal: List[str] = Field(default_factory=list, description="Régimen fiscal vigente")
    obligaciones: List[str] = Field(default_factory=list, description="Obligaciones tributarias")
    estatus: str = Field(default="activo", description="Estatus del RFC (activo/inactivo/suspendido)")
    fecha_alta: Optional[str] = Field(default=None, description="Fecha de alta")
    fecha_baja: Optional[str] = Field(default=None, description="Fecha de baja")
    domicilio_fiscal: str = Field(default="", description="Domicilio fiscal registrado")
    nombre_comercial: str = Field(default="", description="Nombre comercial")
    num_reg_id_trib: Optional[str] = Field(default=None, description="Número de registro tributario")


class ContabilidadElectronica(BaseModel):
    """Datos para enviar contabilidad electrónica al SAT."""
    ejercicio: int = Field(..., description="Año del ejercicio fiscal")
    mes: int = Field(..., ge=1, le=12, description="Mes del ejercicio")
    rfc: str = Field(..., description="RFC del contribuyente")
    balanza: Dict[str, Any] = Field(default_factory=dict, description="Balanza de comprobación")
    catalogo: Dict[str, Any] = Field(default_factory=dict, description="Catálogo de cuentas")
    polizas: List[Dict[str, Any]] = Field(default_factory=list, description="Pólizas contables")
    fecha_envio: Optional[str] = Field(default=None, description="Fecha de envío")
    status: str = Field(default="pendiente", description="Estado del envío")


class TimbradoResponse(BaseModel):
    """Respuesta del timbrado de un CFDI."""
    exito: bool = Field(default=False, description="Si el timbrado fue exitoso")
    uuid: str = Field(default="", description="UUID del CFDI timbrado")
    fecha_timbrado: str = Field(default="", description="Fecha de timbrado")
    codigo_response: str = Field(default="", description="Código de respuesta del PAC")
    mensaje: str = Field(default="", description="Mensaje del PAC")
    xml_timbrado: Optional[str] = Field(default=None, description="XML timbrado")
    cadena_timbre: Optional[str] = Field(default=None, description="Cadena del timbre fiscal digital")
    sello_cfdi: Optional[str] = Field(default=None, description="Sello del CFDI")
    no_certificado_sat: Optional[str] = Field(default=None, description="Número de certificado SAT")
    fecha_envio: str = Field(default_factory=lambda: datetime.now().isoformat())
