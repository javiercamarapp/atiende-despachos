# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de firmas electrónicas.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EnvelopeStatus(str, Enum):
    """Estado de un sobre de firma."""
    DRAFT = "draft"
    SENT = "sent"
    COMPLETED = "completed"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SignerStatus(str, Enum):
    """Estado de un firmante."""
    PENDING = "pending"
    SIGNED = "signed"
    DECLINED = "declined"
    DELIVERED = "delivered"


class SignatureProvider(str, Enum):
    """Proveedores de firma."""
    DOCUSIGN = "docusign"
    FIEL = "fiel"
    ADOBE_SIGN = "adobe_sign"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class SignatureConfig(BaseModel):
    """Configuración del adaptador de firmas."""
    provider: SignatureProvider = Field(..., description="Proveedor de firmas")
    api_key: str = Field(default="", description="API key")
    api_secret: str = Field(default="", description="API secret")
    account_id: Optional[str] = Field(default=None, description="Account ID (DocuSign)")
    fiel_cert_path: Optional[str] = Field(default=None, description="Ruta certificado FIEL")
    fiel_key_path: Optional[str] = Field(default=None, description="Ruta llave privada FIEL")
    fiel_password: Optional[str] = Field(default=None, description="Contraseña FIEL")
    base_url: str = Field(default="https://demo.docusign.net", description="Base URL API")
    timeout: int = Field(default=30, description="Timeout en segundos")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Signer(BaseModel):
    """Firmante de un documento."""
    name: str = Field(..., description="Nombre del firmante")
    email: str = Field(..., description="Email del firmante")
    role: str = Field(default="signer", description="Rol (signer, approver, cc)")
    order: int = Field(default=1, description="Orden de firma")
    status: SignerStatus = Field(default=SignerStatus.PENDING, description="Estado")


class SigningRequest(BaseModel):
    """Solicitud de firma electrónica."""
    document_id: str = Field(..., description="ID del documento a firmar")
    document_name: str = Field(default="documento.pdf", description="Nombre del documento")
    subject: str = Field(default="Firma requerida", description="Asunto del sobre")
    message: str = Field(default="Por favor firme el documento adjunto.", description="Mensaje")
    signers: List[Signer] = Field(..., description="Lista de firmantes")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class Envelope(BaseModel):
    """Sobre de firma (respuesta)."""
    id: str = Field(default="", description="ID del sobre")
    status: EnvelopeStatus = Field(default=EnvelopeStatus.DRAFT, description="Estado")
    signers: List[Signer] = Field(default_factory=list, description="Firmantes")
    document_name: str = Field(default="", description="Nombre del documento")
    created_at: str = Field(default="", description="Fecha de creación")
    completed_at: Optional[str] = Field(default=None, description="Fecha de completado")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class SigningStatus(BaseModel):
    """Estado detallado de un sobre de firma."""
    envelope_id: str = Field(..., description="ID del sobre")
    status: EnvelopeStatus = Field(..., description="Estado")
    signers: List[Signer] = Field(default_factory=list, description="Estado de firmantes")
    percent_complete: int = Field(default=0, description="Porcentaje completado")
    details: str = Field(default="", description="Detalles adicionales")
