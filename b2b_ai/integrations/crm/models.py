# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de CRM (HubSpot, Pipedrive).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CRMProvider(str, Enum):
    """Proveedores de CRM."""
    HUBSPOT = "hubspot"
    PIPEDRIVE = "pipedrive"
    SALESFORCE = "salesforce"
    ZOHO_CRM = "zoho_crm"


class DealStage(str, Enum):
    """Etapas de una oportunidad."""
    LEAD = "lead"
    QUALIFIED = "qualified"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class DealStatus(str, Enum):
    """Estado de una oportunidad."""
    OPEN = "open"
    WON = "won"
    LOST = "lost"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class CRMConfig(BaseModel):
    """Configuración del adaptador de CRM."""
    provider: CRMProvider = Field(..., description="Proveedor de CRM")
    api_key: str = Field(default="", description="API key")
    access_token: Optional[str] = Field(default=None, description="Access token (HubSpot)")
    base_url: str = Field(default="", description="Base URL de la API")
    timeout: int = Field(default=30, description="Timeout en segundos")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Contact(BaseModel):
    """Contacto en el CRM."""
    id: str = Field(default="", description="ID del contacto")
    name: str = Field(default="", description="Nombre completo")
    email: Optional[str] = Field(default=None, description="Email")
    phone: Optional[str] = Field(default=None, description="Teléfono")
    company: Optional[str] = Field(default=None, description="Empresa")
    tags: List[str] = Field(default_factory=list, description="Etiquetas")
    created_at: str = Field(default="", description="Fecha de creación")
    updated_at: str = Field(default="", description="Fecha de actualización")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos adicionales")


class Deal(BaseModel):
    """Oportunidad en el CRM."""
    id: str = Field(default="", description="ID de la oportunidad")
    contact_id: str = Field(default="", description="ID del contacto asociado")
    title: str = Field(default="", description="Título")
    value: float = Field(default=0.0, description="Valor monetario")
    currency: str = Field(default="MXN", description="Moneda")
    stage: DealStage = Field(default=DealStage.LEAD, description="Etapa")
    status: DealStatus = Field(default=DealStatus.OPEN, description="Estado")
    created_at: str = Field(default="", description="Fecha de creación")
    updated_at: str = Field(default="", description="Fecha de actualización")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class ContactCreateRequest(BaseModel):
    """Solicitud de creación de contacto."""
    name: str = Field(..., description="Nombre completo")
    email: Optional[str] = Field(default=None, description="Email")
    phone: Optional[str] = Field(default=None, description="Teléfono")
    company: Optional[str] = Field(default=None, description="Empresa")
    tags: List[str] = Field(default_factory=list, description="Etiquetas")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class DealCreateRequest(BaseModel):
    """Solicitud de creación de oportunidad."""
    title: str = Field(..., description="Título")
    value: float = Field(default=0.0, ge=0, description="Valor monetario")
    currency: str = Field(default="MXN", description="Moneda")
    stage: DealStage = Field(default=DealStage.LEAD, description="Etapa inicial")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")
