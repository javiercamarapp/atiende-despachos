# -*- coding: utf-8 -*-
"""
models.py — Esquemas Pydantic del módulo de procesamiento batch de CFDIs.

Permite subir múltiples CFDIs (ZIP de XML o CSV) y procesarlos en una sola
operación asíncrona, con seguimiento de progreso por ítem.

Modelos:
  - BatchJobStatus   : ciclo de vida del trabajo batch
  - BatchItemStatus  : estado de cada CFDI individual
  - BatchItem        : un CFDI dentro del lote (con su resultado)
  - BatchJob         : el lote completo con su reporte resumen
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------


class BatchJobStatus(str, Enum):
    """Ciclo de vida de un trabajo batch."""
    PENDING = "pending"          # recibido, esperando procesar
    PROCESSING = "processing"    # procesándose
    COMPLETED = "completed"      # terminó (con o sin fallos parciales)
    FAILED = "failed"            # fallo catastrófico (nada procesado)


class BatchItemStatus(str, Enum):
    """Estado de un CFDI individual dentro del lote."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# BatchItem — un CFDI del lote
# ---------------------------------------------------------------------------


class BatchItem(BaseModel):
    """Un CFDI del lote con su resultado de validación.

    ``result`` guarda la respuesta normalizada del CFDI procesado (misma forma
    que el endpoint /validate), o ``error`` si el parseo/validación falló.
    """
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    filename: str = Field(..., description="Nombre del archivo dentro del lote")
    status: BatchItemStatus = Field(default=BatchItemStatus.PENDING)
    error: Optional[str] = Field(default=None, description="Motivo de fallo")
    total: Optional[float] = Field(default=None, description="Total del CFDI (si parseó)")
    uuid: Optional[str] = Field(default=None, description="UUID/TimbreFiscalDigital")
    result: Optional[Dict[str, Any]] = Field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status.value,
            "error": self.error,
            "total": self.total,
            "uuid": self.uuid,
            "result": self.result,
        }


# ---------------------------------------------------------------------------
# BatchJob — el lote completo
# ---------------------------------------------------------------------------


class BatchJob(BaseModel):
    """Trabajo batch de CFDIs con su reporte resumen."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    status: BatchJobStatus = Field(default=BatchJobStatus.PENDING)
    total_items: int = Field(default=0, ge=0)
    processed_items: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    total_amount: float = Field(default=0.0, description="Suma de totales de CFDIs OK")
    total_iva: float = Field(default=0.0, description="Suma de IVA trasladado de CFDIs OK")
    items: List[BatchItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    error: Optional[str] = Field(default=None, description="Error catastrófico global")

    def summary(self) -> Dict[str, Any]:
        """Reporte resumen (entregable 6)."""
        return {
            "batch_id": self.id,
            "status": self.status.value,
            "total": self.total_items,
            "processed": self.processed_items,
            "successful": self.success_count,
            "failed": self.failed_count,
            "total_amount": self.total_amount,
            "total_iva": self.total_iva,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.summary(),
            "items": [i.to_dict() for i in self.items],
        }
