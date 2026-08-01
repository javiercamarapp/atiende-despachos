# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración bancaria (BBVA, Banorte, Santander, OFX, CSV).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TipoTransaccion(str, Enum):
    """Tipo de transacción bancaria."""
    CARGO = "cargo"
    ABONO = "abono"
    TRANSFERENCIA = "transferencia"
    DEPOSITO = "deposito"
    RETIRO = "retiro"
    COMISION = "comision"
    INTERES = "interes"
    PAGO = "pago"
    CHEQUE = "cheque"


class FormatoEstado(str, Enum):
    """Formatos de estado de cuenta soportados."""
    OFX = "ofx"
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class Banco(str, Enum):
    """Bancos mexicanos soportados."""
    BBVA = "bbva"
    BANORTE = "banorte"
    SANTANDER = "santander"
    HSBC = "hsbc"
    CITIBANAMEX = "citibanamex"
    BAJIO = "bajio"
    SCOTIABANK = "scotiabank"
    INBURSA = "inbursa"
    AZTECA = "azteca"
    GENERIC = "generic"


# ---------------------------------------------------------------------------
# Bank Configuration
# ---------------------------------------------------------------------------

class BankConfig(BaseModel):
    """Configuración de conexión bancaria."""
    bank: Banco = Field(..., description="Banco")
    account_number: str = Field(..., description="Número de cuenta")
    clabe: Optional[str] = Field(default=None, description="CLABE interbancaria")
    username: Optional[str] = Field(default=None, description="Usuario")
    password: Optional[str] = Field(default=None, description="Contraseña (encriptada)")
    empresa: Optional[str] = Field(default=None, description="Nombre de la empresa")
    moneda: str = Field(default="MXN", description="Moneda de la cuenta")
    tipo_cuenta: str = Field(default="cheques", description="Tipo de cuenta (cheques/ahorro/inversion)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "bank": "bbva",
                "account_number": "0123456789",
                "clabe": "012345678901234567",
                "empresa": "Mi Empresa S.A. DE C.V.",
            }]
        }
    }


# ---------------------------------------------------------------------------
# Bank Transaction
# ---------------------------------------------------------------------------

class BankTransaction(BaseModel):
    """Transacción bancaria."""
    fecha: str = Field(..., description="Fecha de la transacción YYYY-MM-DD")
    monto: float = Field(..., description="Monto de la transacción (positivo=abono, negativo=cargo)")
    descripcion: str = Field(default="", description="Descripción de la transacción")
    referencia: str = Field(default="", description="Referencia o folio bancario")
    tipo: TipoTransaccion = Field(default=TipoTransaccion.CARGO, description="Tipo de transacción")
    banco: str = Field(default="", description="Banco")
    cuenta: str = Field(default="", description="Cuenta")
    rfc_contraparte: Optional[str] = Field(default=None, description="RFC de la contraparte")
    nombre_contraparte: Optional[str] = Field(default=None, description="Nombre de la contraparte")
    concepto: str = Field(default="", description="Concepto del movimiento")
    saldo_posterior: Optional[float] = Field(default=None, description="Saldo después del movimiento")
    moneda: str = Field(default="MXN", description="Moneda")
    tipo_cambio: float = Field(default=1.0, description="Tipo de cambio")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "fecha": "2026-01-15",
                "monto": -5000.00,
                "descripcion": "TRANSFERENCIA INTERBANCARIA",
                "referencia": "REF-001",
                "tipo": "transferencia",
            }]
        }
    }


# ---------------------------------------------------------------------------
# Bank Statement
# ---------------------------------------------------------------------------

class BankStatement(BaseModel):
    """Estado de cuenta bancario."""
    account_id: str = Field(default="", description="Identificador de la cuenta")
    bank: Banco = Field(default=Banco.GENERIC, description="Banco")
    periodo: str = Field(default="", description="Periodo del estado YYYY-MM")
    fecha_inicio: str = Field(default="", description="Fecha de inicio")
    fecha_fin: str = Field(default="", description="Fecha de fin")
    transactions: List[BankTransaction] = Field(default_factory=list, description="Transacciones")
    saldo_inicial: float = Field(default=0.0, description="Saldo al inicio del periodo")
    saldo_final: float = Field(default=0.0, description="Saldo al final del periodo")
    total_cargos: float = Field(default=0.0, description="Total de cargos")
    total_abonos: float = Field(default=0.0, description="Total de abonos")
    num_transacciones: int = Field(default=0, description="Número de transacciones")
    moneda: str = Field(default="MXN", description="Moneda")

    def calcular_totales(self) -> None:
        """Recalcula los totales del estado de cuenta."""
        self.total_cargos = sum(t.monto for t in self.transactions if t.monto < 0)
        self.total_abonos = sum(t.monto for t in self.transactions if t.monto > 0)
        self.num_transacciones = len(self.transactions)
        self.saldo_final = self.saldo_inicial + self.total_abonos + self.total_cargos
