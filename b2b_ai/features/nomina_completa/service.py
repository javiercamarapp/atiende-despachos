# -*- coding: utf-8 -*-
"""
service.py — Servicio de Nómina Completa.

Calcula ISR, IMSS (patronal + obrero) e INFONAVIT, genera CFDI de nómina
y recibo individual para cada empleado.
"""
from __future__ import annotations

import math
import uuid
from typing import Any, Optional

from b2b_ai.features.nomina_completa.models import (
    EmployeePayroll,
    PayrollDeposit,
    PayrollPeriod,
    PayrollTaxes,
)
from b2b_ai.features.compliance import (
    FiscalOutput, AuditTrail, sanitize_string, mask_rfc,
    verify_tenant_access, SafeError, SAFE_ERRORS, calculate_isr,
)


# ---------------------------------------------------------------------------
# Tablas ISR 2026 (simplificadas — Mensual)
# ---------------------------------------------------------------------------
_ISR_TABLA = [
    (0.01, 5_541.66, 0.00, 0.00),
    (5_541.67, 47_071.37, 0.00, 0.00),
    (47_071.38, 87_472.49, 0.30, 16_623.41),
    (87_472.50, 103_376.40, 0.32, 34_746.75),
    (103_376.41, 124_262.27, 0.34, 56_813.74),
    (124_262.28, 250_000.00, 0.35, 69_274.90),
    (250_000.01, 750_000.00, 0.37, 119_274.90),
    (750_000.01, float('inf'), 0.39, 349_274.90),
]


def _calcular_isr(salario_gravable: float) -> float:
    """Calcula el ISR mensual con tabla progresiva."""
    if salario_gravable <= 0:
        return 0.0
    for lim_inf, lim_sup, tasa, cuota_fija in _ISR_TABLA:
        if lim_inf <= salario_gravable <= lim_sup:
            isr = (salario_gravable - lim_inf) * tasa + cuota_fija
            return max(0.0, isr)
    # Si es mayor al último límite
    lim_inf, tasa, cuota_fija = _ISR_TABLA[-1][0], _ISR_TABLA[-1][2], _ISR_TABLA[-1][3]
    isr = (salario_gravable - lim_inf) * tasa + cuota_fija
    return max(0.0, isr)


def _calcular_imss_obrero(salario_diario: float) -> float:
    """Calcula la cuota obrera del IMSS.

    Cuotas fijas simplificadas por día (2026 estimado):
    - Enfermedades y maternidad: 0.40% del salario base
    - Invalidez y vida: 0.625% del salario base
    - Retiro: 2.00% del salario base
    - Cesantía: 1.125% del salario base
    - Guardarantía: 0.125% del salario base

    Total patronal ~4.475%, total obrero ~0.65%
    """
    base = salario_diario * 30  # salario mensual
    # Obrero paga: enfermedad/maternidad + invalidez/vida
    cuota_enfermedad = base * 0.0040 * 30 / 30  # simplificado
    cuota_invalidez = base * 0.00625
    cuota_gmf = base * 0.0065  # cuota fija obrera estimada
    return cuota_gmf


def _calcular_imss_patronal(salario_diario: float) -> float:
    """Calcula la cuota patronal del IMSS."""
    base = salario_diario * 30
    # Patronal: enfermedad/maternidad + invalidez + retiro + cesantía + guard.
    cuota = base * 0.04475  # ~4.475% total patronal
    return cuota


def _calcular_infonavit(salario_diario: float) -> float:
    """Calcula la aportación al INFONAVIT (5% del salario integrado)."""
    base = salario_diario * 30
    return base * 0.05


def calculate_taxes(salary: float, benefits: float = 0.0,
                    salary_per_day: float = 0.0) -> PayrollTaxes:
    """Calcula ISR, IMSS y INFONAVIT para un salario mensual.

    Args:
        salary: Salario bruto mensual (o diario si se especifica).
        benefits: Prestaciones gravables.
        salary_per_day: Si se provee, salary se interpreta como diario.

    Returns:
        PayrollTaxes con el desglose completo.
    """
    if salary_per_day > 0:
        salario_mensual = salary_per_day * 30
        salario_diario = salary_per_day
    else:
        salario_mensual = salary
        salario_diario = salary / 30 if salary > 0 else 0

    # Ingreso gravable = salario + prestaciones exentas
    gravable = salario_mensual + benefits

    isr = _calcular_isr(gravable)
    imss_obrero = _calcular_imss_obrero(salario_diario)
    imss_patronal = _calcular_imss_patronal(salario_diario)
    infonavit = _calcular_infonavit(salario_diario)

    return PayrollTaxes(
        isr=round(isr, 2),
        imss_patronal=round(imss_patronal, 2),
        imss_obrero=round(imss_obrero, 2),
        infonavit=round(infonavit, 2),
    )


def calculate_deposits(net_salary: float, employee: dict) -> PayrollDeposit:
    """Calcula el depósito bancario con CLABE y monto.

    El neto se deposita en la cuenta bancaria del empleado.
    """
    return PayrollDeposit(
        employee_id=employee.get("employee_id", ""),
        neto=round(net_salary, 2),
        banco=employee.get("banco", ""),
        clabe=employee.get("clabe", ""),
        monto=round(net_salary, 2),
    )


def generate_cfdi_nomina(payroll_data: dict) -> dict:
    """Genera un CFDI de Nómina 1.2 en formato dict (mock XML).

    En producción, esto generaría un XML real con Timbrado SAT.
    """
    uuid_cfdi = str(uuid.uuid4())
    emisor = payroll_data.get("emisor", {})
    receptor = payroll_data.get("receptor", {})
    period = payroll_data.get("period", {})
    taxes = payroll_data.get("taxes", {})

    return {
        "Version": "4.0",
        "Serie": "NOM",
        "Folio": uuid_cfdi[:8].upper(),
        "Fecha": f"{period.get('year', 2026)}-{period.get('month', 1):02d}-01T00:00:00",
        "FormaPago": "03",  # Transferencia
        "NoCertificado": "30001000000500003416",
        "SubTotal": str(round(payroll_data.get("subtotal", 0), 2)),
        "Moneda": "MXN",
        "Total": str(round(payroll_data.get("total", 0), 2)),
        "TipoDeComprobante": "N",
        "MetodoPago": "PUE",
        "LugarExpedicion": "06600",
        "Emisor": {
            "Rfc": emisor.get("rfc", ""),
            "Nombre": emisor.get("nombre", ""),
            "RegimenFiscal": emisor.get("regimen_fiscal", "601"),
        },
        "Receptor": {
            "Rfc": receptor.get("rfc", ""),
            "Nombre": receptor.get("nombre", ""),
            "RegimenFiscalReceptor": receptor.get("regimen_fiscal", "605"),
            "UsoCFDI": "CN01",
        },
        "Complemento": {
            "Nomina12:Nomina": {
                "Version": "1.2",
                "TipoNomina": "O",
                "FechaPago": f"{period.get('year', 2026)}-{period.get('month', 1):02d}-01",
                "FechaInicialPago": f"{period.get('year', 2026)}-{period.get('month', 1):02d}-01",
                "FechaFinalPago": f"{period.get('year', 2026)}-{period.get('month', 1):02d}-28",
                "NumDiasPagados": str(period.get("dias_pagados", 30)),
                "Percepciones": {
                    "TotalSueldos": str(round(payroll_data.get("subtotal", 0), 2)),
                },
                "Deducciones": {
                    "TotalOtrasDeducciones": str(round(taxes.get("isr", 0) + taxes.get("imss_obrero", 0), 2)),
                    "TotalRetenciones": str(round(taxes.get("isr", 0), 2)),
                },
            },
        },
    }


def generate_payslip(payroll_data: dict) -> dict:
    """Genera un recibo de nómina individual en formato dict.

    En producción, esto generaría un PDF con diseño profesional.
    """
    employee = payroll_data.get("employee", {})
    period = payroll_data.get("period", {})
    taxes = payroll_data.get("taxes", {})

    return {
        "tipo": "recibo_nomina",
        "empleado": {
            "employee_id": employee.get("employee_id", ""),
            "nombre": employee.get("nombre", ""),
            "puesto": employee.get("puesto", ""),
            "departamento": employee.get("departamento", ""),
        },
        "periodo": {
            "mes": period.get("month", 1),
            "year": period.get("year", 2026),
            "dias_pagados": period.get("dias_pagados", 30),
        },
        "percepciones": {
            "sueldo_base": round(payroll_data.get("sueldo_base", 0), 2),
            "bonos": round(payroll_data.get("bonos", 0), 2),
            "prestaciones": round(payroll_data.get("prestaciones", 0), 2),
            "total_bruto": round(payroll_data.get("subtotal", 0), 2),
        },
        "deducciones": {
            "isr": round(taxes.get("isr", 0), 2),
            "imss_obrero": round(taxes.get("imss_obrero", 0), 2),
            "infonavit": round(taxes.get("infonavit", 0), 2),
            "total": round(sum([
                taxes.get("isr", 0),
                taxes.get("imss_obrero", 0),
                taxes.get("infonavit", 0),
            ]), 2),
        },
        "neto": round(payroll_data.get("neto", 0), 2),
    }


def process_payroll(period: dict, employees: list[dict],
                    tenant_id: Optional[int] = None) -> PayrollPeriod:
    """Procesa la nómina completa para un periodo.

    Args:
        period: {"month": 7, "year": 2026, "dias_pagados": 30}
        employees: [{"employee_id": "...", "nombre": "...", "salario_bruto": ...,
                      "percepciones": ..., "banco": ..., "clabe": ...}]
        tenant_id: ID del tenant.

    Returns:
        PayrollPeriod con todos los cálculos.
    """
    month = period.get("month", 1)
    year = period.get("year", 2026)
    dias_pagados = period.get("dias_pagados", 30)
    salary_per_day = period.get("salario_diario", None)

    payroll_employees = []
    for emp in employees:
        salario_bruto = float(emp.get("salario_bruto", 0))
        percepciones = float(emp.get("percepciones", 0))
        sal_diario = float(emp.get("salario_diario", 0))
        if salary_per_day and not sal_diario:
            sal_diario = salary_per_day

        # Calcular impuestos
        taxes = calculate_taxes(
            salary=salario_bruto,
            benefits=percepciones,
            salary_per_day=sal_diario,
        )

        # Neto = bruto + percepciones - deducciones
        deducciones = taxes.isr + taxes.imss_obrero + taxes.infonavit
        neto = salario_bruto + percepciones - deducciones

        payroll_emp = EmployeePayroll(
            employee_id=emp.get("employee_id", ""),
            nombre=emp.get("nombre", ""),
            salario_diario=sal_diario,
            salario_bruto=salario_bruto,
            percepciones=percepciones,
            deducciones=round(deducciones, 2),
            taxes=taxes,
            neto=round(max(0, neto), 2),
            dias_pagados=dias_pagados,
        )
        payroll_employees.append(payroll_emp)

    period_obj = PayrollPeriod(
        month=month,
        year=year,
        employees=payroll_employees,
        tenant_id=tenant_id,
    )
    period_obj.recalc_totals()

    # CFF Art. 105 LISR: Nómina deductions must follow ISR table
    # CFF Art. 89: Fiscal output metadata
    total_isr = period_obj.total_isr
    total_deducciones = period_obj.total_deducciones
    period_obj.referencia_legal = "CFF Art. 105, LISR Art. 96"
    period_obj.supuesto = "Procesamiento de nómina con deducciones ISR/IMSS/INFONAVIT"
    # Require human review if total deductions are unusually high
    if period_obj.total_bruto > 0 and total_deducciones / period_obj.total_bruto > 0.4:
        period_obj.requires_human_review = True
        period_obj.human_review_reason = f"Deducciones representan {total_deducciones/period_obj.total_bruto*100:.1f}% del bruto (>40%)"
    else:
        period_obj.requires_human_review = False
    period_obj.idempotency_key = f"nomina-{year}-{month:02d}-{tenant_id}"

    return period_obj
