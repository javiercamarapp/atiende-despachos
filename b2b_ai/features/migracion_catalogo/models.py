# -*- coding: utf-8 -*-
"""
models.py — Esquema de datos para la migración/fusión de catálogo de cuentas
(REQ-MIG-002).

Contexto (ver docs/BLUEPRINT-AGENTES-FISCALES.md §3, ADR-3): una fusión de
catálogos entre dos sistemas contables nunca debe reclasificar una cuenta
automáticamente salvo que código y nombre normalizados coincidan de forma
exacta entre origen y destino. `MapeoMigracionCuenta` es el registro central
de esa decisión — para cada cuenta de origen, qué cuenta de destino le
correspondería, con qué confianza (`tipo_match`/`score`), y en qué estado de
revisión humana se encuentra (`estado`).

Este archivo solo define el esquema (REQ-MIG-002). El motor de matching
(REQ-MIG-003..006), los endpoints de aprobación (REQ-MIG-007), el migrador
transaccional (REQ-MIG-009..010) y las verificaciones de integridad
(REQ-MIG-012..015) son requisitos separados de la misma matriz y se
implementan en módulos hermanos (`matching.py`, `routes.py`, `service.py`,
`migrador.py`, `verificacion.py`) que este modelo deja preparados pero que
no se implementan aquí.
"""
from __future__ import annotations

import uuid as _uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TipoMatchMigracion(str, Enum):
    """Cómo se determinó la correspondencia origen→destino de una cuenta.

    Solo `EXACTO` puede llegar a `estado=EstadoMapeoMigracion.APROBADO` sin
    intervención humana (REQ-MIG-003). `ALERTA_RIESGO`, `FUZZY` y
    `SIN_MATCH` siempre nacen en `estado=PENDIENTE` (REQ-MIG-004..006).
    """
    EXACTO = "exacto"
    ALERTA_RIESGO = "alerta_riesgo"
    FUZZY = "fuzzy"
    SIN_MATCH = "sin_match"


class EstadoMapeoMigracion(str, Enum):
    """Estado de revisión humana de un `MapeoMigracionCuenta`.

    Solo el endpoint de revisión humana (REQ-MIG-007) puede mover un mapeo
    fuera de `PENDIENTE`; el motor de matching nunca escribe `APROBADO`
    directamente salvo para `tipo_match=EXACTO` (REQ-MIG-003).
    """
    PENDIENTE = "pendiente"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"
    EDITADO = "editado"


# ---------------------------------------------------------------------------
# Modelo principal
# ---------------------------------------------------------------------------

class MapeoMigracionCuenta(BaseModel):
    """Correspondencia propuesta (o confirmada) entre una cuenta de origen
    y una cuenta de destino durante una migración/fusión de catálogo.

    Campos (9):
      - id: identificador único del propio mapeo.
      - origen_cuenta_id: cuenta del catálogo origen a mapear.
      - destino_cuenta_id: cuenta del catálogo destino propuesta; `None`
        cuando `tipo_match=SIN_MATCH` (nunca se inventa un destino,
        REQ-MIG-006).
      - tipo_match: cómo se determinó la correspondencia.
      - score: confianza de 0 a 100 (100 = coincidencia exacta).
      - estado: estado de revisión humana del mapeo.
      - aprobado_por: identificador de quién decidió el `estado` actual
        (aprobó, rechazó o editó); `None` mientras `estado=PENDIENTE`.
      - aprobado_en: fecha/hora ISO-8601 de esa decisión; `None` mientras
        `estado=PENDIENTE`.
      - nota: justificación o comentario humano (obligatoria en la práctica
        para `RECHAZADO`/`EDITADO`, libre para los demás casos).
      - estrategia_conciliacion_saldos: cómo se concilian los saldos
        cuando este mapeo forma parte de una fusión N:1 (varias cuentas
        origen hacia el mismo `destino_cuenta_id`); obligatoria no nula
        antes de aprobar un mapeo N:1 (REQ-MIG-008), `None` en cualquier
        otro caso.
    """

    id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="ID único del mapeo de migración",
    )
    origen_cuenta_id: str = Field(
        ..., description="ID de la cuenta en el catálogo de origen"
    )
    destino_cuenta_id: Optional[str] = Field(
        default=None,
        description=(
            "ID de la cuenta en el catálogo de destino propuesta; None "
            "si tipo_match=sin_match (nunca se inventa un destino)"
        ),
    )
    tipo_match: TipoMatchMigracion = Field(
        ..., description="Cómo se determinó la correspondencia origen→destino"
    )
    score: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Confianza del match, de 0 a 100",
    )
    estado: EstadoMapeoMigracion = Field(
        default=EstadoMapeoMigracion.PENDIENTE,
        description="Estado de revisión humana del mapeo",
    )
    aprobado_por: Optional[str] = Field(
        default=None,
        description="Quién decidió el estado actual (None si pendiente)",
    )
    aprobado_en: Optional[str] = Field(
        default=None,
        description="Fecha/hora ISO-8601 de la decisión (None si pendiente)",
    )
    nota: Optional[str] = Field(
        default=None,
        description="Justificación o comentario humano sobre el mapeo",
    )
    estrategia_conciliacion_saldos: Optional[str] = Field(
        default=None,
        description=(
            "Cómo se concilian los saldos cuando este mapeo es parte de "
            "una fusión N:1 (varias cuentas origen hacia el mismo "
            "destino_cuenta_id); obligatoria no nula antes de aprobar un "
            "mapeo N:1 (REQ-MIG-008). None fuera de ese caso."
        ),
    )
