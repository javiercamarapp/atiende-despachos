# -*- coding: utf-8 -*-
"""
models.py — Esquemas del módulo de Bank Feeds (importación automática de
transacciones desde bancos mexicanos).

Soportado por el landscape MX: SPEI, CoDi y banca en línea para los bancos
BBVA, Banorte, Santander y HSBC.

Modelos:
  - BankProvider       : banco soportado
  - TransactionType    : dirección del movimiento (INGRESO / EGRESO)
  - PaymentChannel     : medio por el que entró/salió el dinero (SPEI, CoDi, ...)
  - SyncStatus         : ciclo de vida de una sincronización (FeedSync)
  - BankAccount        : cuenta bancaria conectada
  - Transaction        : una transacción importada
  - FeedSync           : registro de una sincronización de un feed
  - FeedSyncResult     : resumen devuelto por sync_transactions
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BankProvider(str, Enum):
    """Bancos mexicanos soportados por el conector de feeds (MVP mock)."""
    BBVA = "BBVA"
    BANORTE = "BANORTE"
    SANTANDER = "SANTANDER"
    HSBC = "HSBC"
    PROMETEO = "PROMETEO"


class TransactionType(str, Enum):
    """Dirección del movimiento. amount es positivo para INGRESO y negativo
    para EGRESO (convención coherente con conciliacion.BankTransaction)."""
    INGRESO = "INGRESO"
    EGRESO = "EGRESO"


class PaymentChannel(str, Enum):
    """Medio por el que se movió el dinero."""
    SPEI = "SPEI"
    CODI = "CODI"
    BANCA_EN_LINEA = "BANCA_EN_LINEA"
    NOMINA = "NOMINA"
    TARJETA = "TARJETA"
    CHEQUE = "CHEQUE"
    EFECTIVO = "EFECTIVO"
    OTRO = "OTRO"


class SyncStatus(str, Enum):
    """Ciclo de vida de una sincronización de feed."""
    PENDING = "pending"          # encolado
    RUNNING = "running"          # ejecutándose
    COMPLETED = "completed"      # terminó OK
    FAILED = "failed"            # falló (red / credenciales / parseo)
    SKIPPED = "skipped"          # sin movimientos nuevos


class TransactionStatus(str, Enum):
    """Estado de vida de una transacción importada."""
    IMPORTED = "imported"        # recién importada
    CATEGORIZED = "categorized"  # con categoría asignada
    RECONCILED = "reconciled"    # conciliada contra CFDI/póliza


class Category(str, Enum):
    """Categorías contables propuestas por categorize_transaction."""
    VENTAS = "VENTAS"
    COMPRAS = "COMPRAS"
    NOMINA = "NOMINA"
    IMPUESTOS = "IMPUESTOS"
    SERVICIOS = "SERVICIOS"
    FINANCIEROS = "FINANCIEROS"
    TRANSFERENCIAS = "TRANSFERENCIAS"
    OTROS = "OTROS"


# ---------------------------------------------------------------------------
# BankAccount
# ---------------------------------------------------------------------------


class BankAccount(BaseModel):
    """Cuenta bancaria conectada a un feed."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(default="", description="Tenant dueño de la cuenta")
    provider: BankProvider = Field(..., description="Banco")
    account_label: str = Field(default="", description="Etiqueta amigable (ej. 'Operativa MXN')")
    clabe: str = Field(default="", description="CLABE interbancaria (18 dígitos)")
    currency: str = Field(default="MXN")
    active: bool = Field(default=True)
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("clabe")
    @classmethod
    def _clabe_len(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not v.isdigit():
            raise ValueError("CLABE debe contener solo dígitos")
        if v and len(v) != 18:
            raise ValueError("CLABE debe tener 18 dígitos")
        return v

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "provider": self.provider.value,
            "account_label": self.account_label,
            "clabe": self.clabe,
            "currency": self.currency,
            "active": self.active,
            "connected_at": self.connected_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------


class Transaction(BaseModel):
    """Una transacción importada desde un feed bancario."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    account_id: str = Field(..., description="BankAccount.id dueño")
    provider: BankProvider = Field(..., description="Banco de origen")
    # Identificador único de la transacción según el banco (dedupe).
    external_id: str = Field(..., description="ID único del banco (FITID/Clave Rastreo)")
    date: str = Field(..., description="Fecha del movimiento YYYY-MM-DD")
    description: str = Field(default="")
    reference: str = Field(default="", description="Referencia bancaria / clave de rastreo")
    amount: float = Field(..., description="Positivo=INGRESO, negativo=EGRESO")
    type: TransactionType = Field(..., description="Dirección del movimiento")
    channel: PaymentChannel = Field(default=PaymentChannel.OTRO)
    counterparty: str = Field(default="", description="Contraparte (RFC/beneficiario si aplica)")
    category: Optional[Category] = Field(default=None)
    status: TransactionStatus = Field(default=TransactionStatus.IMPORTED)
    imported_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("amount")
    @classmethod
    def _amount_not_zero(cls, v: float) -> float:
        if v == 0:
            raise ValueError("amount cannot be zero")
        return v

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "provider": self.provider.value,
            "external_id": self.external_id,
            "date": self.date,
            "description": self.description,
            "reference": self.reference,
            "amount": self.amount,
            "type": self.type.value,
            "channel": self.channel.value,
            "counterparty": self.counterparty,
            "category": self.category.value if self.category else None,
            "status": self.status.value,
            "imported_at": self.imported_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# FeedSync
# ---------------------------------------------------------------------------


class FeedSync(BaseModel):
    """Registro de una sincronización (pull) de un feed bancario."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    account_id: str = Field(..., description="BankAccount.id sincronizado")
    provider: BankProvider = Field(..., description="Banco")
    status: SyncStatus = Field(default=SyncStatus.PENDING)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    found_count: int = Field(default=0, ge=0, description="Movimientos vistos en el feed")
    imported_count: int = Field(default=0, ge=0, description="Movimientos nuevos importados")
    duplicate_count: int = Field(default=0, ge=0, description="Ya existentes (dedupe)")
    error: Optional[str] = Field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "provider": self.provider.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "found": self.found_count,
            "imported": self.imported_count,
            "duplicates": self.duplicate_count,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# FeedSyncResult
# ---------------------------------------------------------------------------


class FeedSyncResult(BaseModel):
    """Resumen devuelto por sync_transactions() para una cuenta."""
    sync: FeedSync
    transactions: List[Transaction] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sync": self.sync.to_dict(),
            "transactions": [t.to_dict() for t in self.transactions],
        }
