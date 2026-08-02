# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for Multi-Tenant Data Isolation module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent tenants, configurations, audit logs, and context
used to enforce data isolation across the B&B AI Enterprise platform.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TenantStatus(str, Enum):
    """Estado de un tenant en la plataforma."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"
    BLOCKED = "blocked"
    DELETED = "deleted"


class IsolationLevel(str, Enum):
    """Nivel de aislamiento de datos para un tenant."""
    SHARED_SCHEMA = "shared_schema"      # Misma tabla, columna tenant_id
    SCHEMA_PER_TENANT = "schema_per_tenant"  # Schema separado por tenant
    DATABASE_PER_TENANT = "database_per_tenant"  # Base de datos separada


class AuditAction(str, Enum):
    """Acciones auditables en el contexto multi-tenant."""
    TENANT_CREATED = "tenant_created"
    TENANT_UPDATED = "tenant_updated"
    TENANT_SUSPENDED = "tenant_suspended"
    TENANT_ACTIVATED = "tenant_activated"
    TENANT_BLOCKED = "tenant_blocked"
    TENANT_DELETED = "tenant_deleted"
    CONTEXT_SWITCHED = "context_switched"
    DATA_ACCESSED = "data_accessed"
    CROSS_TENANT_BLOCKED = "cross_tenant_blocked"
    CONFIG_UPDATED = "config_updated"


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------

class Tenant(BaseModel):
    """Modelo de un tenant (despacho/cliente) en la plataforma.

    Cada tenant tiene su propio aislamiento de datos, configuración,
    y auditoría independiente.
    """
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único del tenant (UUID)",
    )
    name: str = Field(
        ...,
        description="Nombre del tenant (despacho o empresa)",
    )
    rfc: str = Field(
        default="",
        description="RFC fiscal del tenant (México)",
    )
    schema_name: str = Field(
        default="",
        description="Nombre del schema de aislamiento (para schema_per_tenant)",
    )
    isolation_level: IsolationLevel = Field(
        default=IsolationLevel.SHARED_SCHEMA,
        description="Nivel de aislamiento de datos",
    )
    status: TenantStatus = Field(
        default=TenantStatus.PENDING,
        description="Estado actual del tenant",
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configuración del tenant (ERP, plantilla, notificaciones)",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos adicionales del tenant",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Fecha de creación ISO format",
    )
    updated_at: Optional[str] = Field(
        default=None,
        description="Fecha de última actualización ISO format",
    )
    blocked: bool = Field(
        default=False,
        description="Si el tenant está bloqueado (no puede autenticarse)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Despacho García y Asociados",
                "rfc": "GYA850101XYZ",
                "schema_name": "tenant_garcia",
                "isolation_level": "shared_schema",
                "status": "active",
                "config": {"erp_type": "contpaqi", "plantilla_contable": "SAT"},
                "blocked": False,
            }]
        }
    }

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("El nombre del tenant no puede estar vacío.")
        return v.strip()


# ---------------------------------------------------------------------------
# TenantConfig
# ---------------------------------------------------------------------------

class TenantConfig(BaseModel):
    """Configuración clave-valor de un tenant.

    Almacena configuraciones específicas como tipo de ERP, plantilla contable,
    canales de notificación, URLs de webhook, etc.
    """
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único de la configuración",
    )
    tenant_id: str = Field(
        ...,
        description="ID del tenant al que pertenece esta configuración",
    )
    key: str = Field(
        ...,
        description="Clave de configuración (ej: 'erp_type', 'notif_channel')",
    )
    value: str = Field(
        default="",
        description="Valor de la configuración",
    )
    description: str = Field(
        default="",
        description="Descripción de la configuración",
    )
    sensitive: bool = Field(
        default=False,
        description="Si el valor debe cifrarse en reposo",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Fecha de creación ISO format",
    )
    updated_at: Optional[str] = Field(
        default=None,
        description="Fecha de última actualización ISO format",
    )

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("La clave de configuración no puede estar vacía.")
        return v.strip()


# ---------------------------------------------------------------------------
# TenantAuditLog
# ---------------------------------------------------------------------------

class TenantAuditLog(BaseModel):
    """Registro de auditoría para acciones en el contexto multi-tenant.

    Registra todas las operaciones relevantes: creación, acceso a datos,
    cambios de contexto, bloqueos cross-tenant, etc.
    """
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único del registro de auditoría",
    )
    tenant_id: str = Field(
        ...,
        description="ID del tenant afectado",
    )
    action: AuditAction = Field(
        ...,
        description="Acción auditada",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="ID del usuario que realizó la acción",
    )
    resource: Optional[str] = Field(
        default=None,
        description="Recurso afectado (tabla, endpoint, etc.)",
    )
    resource_id: Optional[str] = Field(
        default=None,
        description="ID del recurso afectado",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detalles adicionales de la acción",
    )
    ip_address: Optional[str] = Field(
        default=None,
        description="Dirección IP de la solicitud",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp de la acción ISO format",
    )
    success: bool = Field(
        default=True,
        description="Si la acción fue exitosa",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Mensaje de error si la acción falló",
    )


# ---------------------------------------------------------------------------
# TenantContext
# ---------------------------------------------------------------------------

class TenantContext(BaseModel):
    """Contexto de tenant activo en una sesión/request.

    Se utiliza como middleware para propagar el tenant actual
    a través de toda la cadena de servicios.
    """
    tenant_id: str = Field(
        ...,
        description="ID del tenant activo",
    )
    tenant_name: Optional[str] = Field(
        default=None,
        description="Nombre del tenant activo",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="ID del usuario autenticado",
    )
    user_role: Optional[str] = Field(
        default=None,
        description="Rol del usuario (admin, contador, etc.)",
    )
    isolation_level: IsolationLevel = Field(
        default=IsolationLevel.SHARED_SCHEMA,
        description="Nivel de aislamiento del tenant",
    )
    schema_name: Optional[str] = Field(
        default=None,
        description="Schema activo (para schema_per_tenant)",
    )
    ip_address: Optional[str] = Field(
        default=None,
        description="IP del cliente",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp de creación del contexto",
    )


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CreateTenantRequest(BaseModel):
    """Request para crear un nuevo tenant."""
    name: str = Field(
        ...,
        description="Nombre del tenant",
    )
    rfc: str = Field(
        default="",
        description="RFC fiscal del tenant",
    )
    isolation_level: IsolationLevel = Field(
        default=IsolationLevel.SHARED_SCHEMA,
        description="Nivel de aislamiento de datos",
    )
    config: Dict[str, str] = Field(
        default_factory=dict,
        description="Configuración inicial del tenant",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos adicionales",
    )


class TenantResponse(BaseModel):
    """Response estándar para operaciones de tenant."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None
