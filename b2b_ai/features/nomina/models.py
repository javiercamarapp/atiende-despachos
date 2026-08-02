# -*- coding: utf-8 -*-
"""
models.py — Esquemas del módulo de Nómina (payroll).

Modelos Pydantic para el procesamiento de nómina del MVP de Likida AI:

  - NominaStatus    : ciclo de vida de una nómina (DRAFT → VALIDATED → PAID / VOIDED).
  - ConceptType     : tipo de concepto (PERCEPCION / DEDUCCION).
  - NominaConcept   : concepto de nómina (SAT c_ClaveProdServ / c_TipoPercepcion / c_TipoDeduccion).
  - NominaRecord    : registro de nómina de un empleado en un periodo.
  - NominaRecordCreate : schema de alta.
  - PayrollSummary  : resumen agregado por periodo/tenant.

Todos los modelos llevan `tenant_id` para garantizar el aislamiento multi-tenant.

Sigue el patrón de los módulos piloto (ap_ar, conciliacion, monthly_close):
modelos Pydantic + almacenamiento en memoria con `_reset_state()` para tests,
y `to_dict()` para serialización JSON-friendly.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NominaStatus(str, Enum):
    """Ciclo de vida de un registro de nómina."""
    DRAFT = "DRAFT"                # borrador (sin validar)
    VALIDATED = "VALIDATED"        # validado y listo para pago
    PAID = "PAID"                  # pagada
    VOIDED = "VOIDED"              # anulada


class ConceptType(str, Enum):
    """Tipo de concepto de nómina."""
    PERCEPCION = "PERCEPCION"
    DEDUCCION = "DEDUCCION"


# ---------------------------------------------------------------------------
# NominaConcept
# ---------------------------------------------------------------------------

class NominaConcept(BaseModel):
    """Concepto de nómina (percepción o deducción) de un registro.

    `concept_code` sigue el catálogo SAT (claves de percepciones/deducciones
    del complemento Nomina 1.2).
    """
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    nomina_id: str = Field(..., description="ID del NominaRecord padre")
    tenant_id: Optional[str] = Field(default=None)
    concept_type: ConceptType = Field(..., description="PERCEPCION o DEDUCCION")
    concept_code: str = Field(
        default="", description="Clave SAT del concepto (p.ej. '001' percepción ordinaria)")
    description: str = Field(default="", description="Descripción del concepto")
    amount: float = Field(default=0.0, ge=0)
    taxable: bool = Field(default=True, description="¿Gravable para ISR?")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "nomina_id": self.nomina_id,
            "tenant_id": self.tenant_id,
            "concept_type": self.concept_type.value,
            "concept_code": self.concept_code,
            "description": self.description,
            "amount": self.amount,
            "taxable": self.taxable,
        }


# ---------------------------------------------------------------------------
# NominaRecord
# ---------------------------------------------------------------------------

class NominaRecord(BaseModel):
    """Registro de nómina de un empleado en un periodo determinado."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: Optional[str] = Field(default=None)
    employee_rfc: str = Field(..., description="RFC del empleado (13 chars PF)")
    employee_name: str = Field(..., description="Nombre del empleado")
    employee_id: str = Field(default="", description="NumEmpleado interno")
    period_start: str = Field(..., description="Inicio del periodo YYYY-MM-DD")
    period_end: str = Field(..., description="Fin del periodo YYYY-MM-DD")
    base_salary: float = Field(default=0.0, ge=0)
    overtime_pay: float = Field(default=0.0, ge=0)
    bonuses: float = Field(default=0.0, ge=0)
    deductions: float = Field(default=0.0, ge=0)
    isr_retention: float = Field(default=0.0, ge=0)
    imss_employer: float = Field(default=0.0, ge=0)
    imss_employee: float = Field(default=0.0, ge=0)
    net_pay: float = Field(default=0.0, ge=0)
    status: NominaStatus = Field(default=NominaStatus.DRAFT)
    payment_date: Optional[str] = Field(default=None, description="Fecha de pago YYYY-MM-DD")
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())

    @field_validator("employee_rfc")
    @classmethod
    def _rfc_not_blank(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("employee_rfc no puede estar vacío")
        return v

    @field_validator("employee_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("employee_name no puede estar vacío")
        return v

    @property
    def total_gross(self) -> float:
        """Percepciones brutas: sueldo base + horas extra + bonos."""
        return round(self.base_salary + self.overtime_pay + self.bonuses, 2)

    @property
    def total_deductions(self) -> float:
        """Total deducciones: deducciones + ISR + IMSS obrero."""
        return round(self.deductions + self.isr_retention + self.imss_employee, 2)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "employee_rfc": self.employee_rfc,
            "employee_name": self.employee_name,
            "employee_id": self.employee_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "base_salary": self.base_salary,
            "overtime_pay": self.overtime_pay,
            "bonuses": self.bonuses,
            "deductions": self.deductions,
            "isr_retention": self.isr_retention,
            "imss_employer": self.imss_employer,
            "imss_employee": self.imss_employee,
            "net_pay": self.net_pay,
            "total_gross": self.total_gross,
            "total_deductions": self.total_deductions,
            "status": self.status.value,
            "payment_date": self.payment_date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Create schema
# ---------------------------------------------------------------------------

class NominaRecordCreate(BaseModel):
    """Schema de alta de un registro de nómina.

    `net_pay`, `isr_retention`, `imss_*` son opcionales: si no se proveen,
    `NominaManager.create_nomina_record` los calcula con `PayrollCalculator`.
    """
    employee_rfc: str = Field(..., description="RFC del empleado")
    employee_name: str = Field(..., description="Nombre del empleado")
    employee_id: str = Field(default="")
    period_start: str = Field(..., description="Inicio del periodo YYYY-MM-DD")
    period_end: str = Field(..., description="Fin del periodo YYYY-MM-DD")
    base_salary: float = Field(default=0.0, ge=0)
    overtime_pay: float = Field(default=0.0, ge=0)
    bonuses: float = Field(default=0.0, ge=0)
    deductions: float = Field(default=0.0, ge=0)
    payment_date: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# PayrollSummary
# ---------------------------------------------------------------------------

class PayrollSummary(BaseModel):
    """Resumen agregado de nómina por periodo/tenant.

    Se computa a partir de los `NominaRecord` del periodo:
      - total_employees : número de registros.
      - total_gross     : suma de percepciones brutas.
      - total_deductions: suma de deducciones (deducciones + ISR + IMSS obrero).
      - total_isr       : suma de ISR retenido.
      - total_imss      : suma de IMSS (patrón + obrero).
      - total_net       : suma de netos pagados.
    """
    period: str = Field(..., description="Periodo YYYY-MM")
    tenant_id: Optional[str] = Field(default=None)
    total_employees: int = Field(default=0)
    total_gross: float = Field(default=0.0)
    total_deductions: float = Field(default=0.0)
    total_isr: float = Field(default=0.0)
    total_imss: float = Field(default=0.0)
    total_net: float = Field(default=0.0)
    generated_at: datetime = Field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict:
        return {
            "period": self.period,
            "tenant_id": self.tenant_id,
            "total_employees": self.total_employees,
            "total_gross": round(self.total_gross, 2),
            "total_deductions": round(self.total_deductions, 2),
            "total_isr": round(self.total_isr, 2),
            "total_imss": round(self.total_imss, 2),
            "total_net": round(self.total_net, 2),
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }
