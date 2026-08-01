# -*- coding: utf-8 -*-
"""
models.py — Modelos de Nómina Completa.

PayrollPeriod    — Periodo de nómina con empleados y totales.
EmployeePayroll  — Nómina individual por empleado.
PayrollTaxes     — Desglose de impuestos (ISR, IMSS, INFONAVIT).
PayrollDeposit   — Información de depósito bancario.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PayrollTaxes:
    """Desglose de impuestos de nómina."""

    isr: float = 0.0
    imss_patronal: float = 0.0
    imss_obrero: float = 0.0
    infonavit: float = 0.0
    total: float = 0.0

    def __post_init__(self):
        self.total = self.isr + self.imss_obrero + self.infonavit

    def to_dict(self) -> dict:
        return {
            "isr": round(self.isr, 2),
            "imss_patronal": round(self.imss_patronal, 2),
            "imss_obrero": round(self.imss_obrero, 2),
            "infonavit": round(self.infonavit, 2),
            "total": round(self.total, 2),
        }


@dataclass
class EmployeePayroll:
    """Nómina individual de un empleado."""

    employee_id: str = ""
    nombre: str = ""
    salario_diario: float = 0.0
    salario_bruto: float = 0.0
    percepciones: float = 0.0
    deducciones: float = 0.0
    taxes: PayrollTaxes = field(default_factory=PayrollTaxes)
    neto: float = 0.0
    dias_pagados: int = 30

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "nombre": self.nombre,
            "salario_diario": round(self.salario_diario, 2),
            "salario_bruto": round(self.salario_bruto, 2),
            "percepciones": round(self.percepciones, 2),
            "deducciones": round(self.deducciones, 2),
            "taxes": self.taxes.to_dict(),
            "neto": round(self.neto, 2),
            "dias_pagados": self.dias_pagados,
        }


@dataclass
class PayrollDeposit:
    """Información de depósito bancario dividido por cuenta."""

    employee_id: str = ""
    neto: float = 0.0
    banco: str = ""
    clabe: str = ""
    monto: float = 0.0

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "neto": round(self.neto, 2),
            "banco": self.banco,
            "clabe": self.clabe,
            "monto": round(self.monto, 2),
        }


@dataclass
class PayrollPeriod:
    """Periodo de nómina completo con empleados y totales."""

    month: int = 1
    year: int = 2026
    employees: list[EmployeePayroll] = field(default_factory=list)
    total_bruto: float = 0.0
    total_neto: float = 0.0
    total_deducciones: float = 0.0
    total_isr: float = 0.0
    total_imss_patronal: float = 0.0
    total_imss_obrero: float = 0.0
    total_infonavit: float = 0.0
    tenant_id: Optional[int] = None

    def __post_init__(self):
        self.recalc_totals()

    def recalc_totals(self):
        self.total_bruto = sum(e.salario_bruto + e.percepciones for e in self.employees)
        self.total_neto = sum(e.neto for e in self.employees)
        self.total_deducciones = sum(e.deducciones for e in self.employees)
        self.total_isr = sum(e.taxes.isr for e in self.employees)
        self.total_imss_patronal = sum(e.taxes.imss_patronal for e in self.employees)
        self.total_imss_obrero = sum(e.taxes.imss_obrero for e in self.employees)
        self.total_infonavit = sum(e.taxes.infonavit for e in self.employees)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "year": self.year,
            "employee_count": len(self.employees),
            "employees": [e.to_dict() for e in self.employees],
            "totals": {
                "bruto": round(self.total_bruto, 2),
                "neto": round(self.total_neto, 2),
                "deducciones": round(self.total_deducciones, 2),
                "isr": round(self.total_isr, 2),
                "imss_patronal": round(self.total_imss_patronal, 2),
                "imss_obrero": round(self.total_imss_obrero, 2),
                "infonavit": round(self.total_infonavit, 2),
            },
            "tenant_id": self.tenant_id,
        }
