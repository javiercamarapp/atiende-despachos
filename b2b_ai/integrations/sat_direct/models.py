# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración directa con SAT (CFDI 4.0, Cancelación, RFC, Contabilidad Electrónica, DIOT).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CFDIVersion(str, Enum):
    """Versión del CFDI."""
    V33 = "3.3"
    V40 = "4.0"


class DIOTStatus(str, Enum):
    """Estado de la DIOT."""
    PENDIENTE = "pendiente"
    ENVIADA = "enviada"
    ACEPTADA = "aceptada"
    RECHAZADA = "rechazada"


class SATDirectConfig(BaseModel):
    """Configuración de conexión directa con SAT."""
    rfc: str = Field(..., description="RFC del contribuyente")
    password_fiel: str = Field(default="", description="Contraseña de la FIEL")
    cert_path: Optional[str] = Field(default=None, description="Ruta al certificado .cer")
    key_path: Optional[str] = Field(default=None, description="Ruta a la llave privada .key")
    pac_username: Optional[str] = Field(default=None, description="Usuario del PAC (si se usa)")
    pac_password: Optional[str] = Field(default=None, description="Contraseña del PAC")
    pac_rfc: Optional[str] = Field(default=None, description="RFC del PAC")
    base_url: str = Field(default="https://portalcfdi.facturaelectronica.sat.gob.mx", description="URL base del SAT")
    cfdi_version: CFDIVersion = Field(default=CFDIVersion.V40, description="Versión del CFDI")
    timeout: int = Field(default=60, description="Timeout en segundos")
    retry_attempts: int = Field(default=3, description="Intentos de reintento")


class DIOTRecord(BaseModel):
    """Registro de la DIOT (Determinación de Impuestos Operaciones con Terceros)."""
    rfc_tercero: str = Field(..., description="RFC del tercero")
    nombre_tercero: str = Field(default="", description="Nombre del tercero")
    tipo_operacion: str = Field(default="", description="Tipo de operación (A, B, C, D, E, F, G)")
    valor_acumulado: float = Field(default=0.0, description="Valor acumulado de operaciones")
    iva_acreditable: float = Field(default=0.0, description="IVA acreditable")
    mes: int = Field(..., ge=1, le=12, description="Mes del ejercicio")
    ejercicio: int = Field(..., description="Ejercicio fiscal")


class DIOTSubmission(BaseModel):
    """Envío de DIOT al SAT."""
    ejercicio: int = Field(..., description="Ejercicio fiscal")
    mes: int = Field(..., ge=1, le=12, description="Mes")
    rfc: str = Field(..., description="RFC del contribuyente")
    registros: List[DIOTRecord] = Field(default_factory=list, description="Registros de operaciones con terceros")
    total_operaciones: float = Field(default=0.0, description="Total de operaciones")
    status: DIOTStatus = Field(default=DIOTStatus.PENDIENTE, description="Estado del envío")
    fecha_envio: Optional[str] = Field(default=None, description="Fecha de envío")


class ContabilidadElectronicaDirect(BaseModel):
    """Datos para contabilidad electrónica directa al SAT."""
    ejercicio: int = Field(..., description="Ejercicio fiscal")
    mes: int = Field(..., ge=1, le=12, description="Mes")
    rfc: str = Field(..., description="RFC del contribuyente")
    num_reg_id_trib: Optional[str] = Field(default=None, description="Número de registro tributario")
    tipo_envio: str = Field(default="N", description="Tipo de envío (N=nuevo, C=complemento)")
    balanza: Dict[str, Any] = Field(default_factory=dict, description="Balanza de comprobación")
    catalogo: Dict[str, Any] = Field(default_factory=dict, description="Catálogo de cuentas")
    polizas: List[Dict[str, Any]] = Field(default_factory=list, description="Pólizas contables")
    fecha_creacion: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    status: str = Field(default="pendiente", description="Estado del envío")


class SATDirectTimbradoResponse(BaseModel):
    """Respuesta de timbrado directo SAT."""
    exito: bool = Field(default=False, description="Si el timbrado fue exitoso")
    uuid: str = Field(default="", description="UUID del CFDI timbrado")
    fecha_timbrado: str = Field(default="", description="Fecha de timbrado")
    codigo_response: str = Field(default="", description="Código de respuesta")
    mensaje: str = Field(default="", description="Mensaje del SAT/PAC")
    xml_timbrado: Optional[str] = Field(default=None, description="XML timbrado completo")
    cadena_timbre: Optional[str] = Field(default=None, description="Cadena del timbre fiscal")
    sello_cfdi: Optional[str] = Field(default=None, description="Sello del CFDI")
    no_certificado_sat: Optional[str] = Field(default=None, description="No. certificado SAT")
    fecha_creacion: str = Field(default_factory=lambda: datetime.now().isoformat())
