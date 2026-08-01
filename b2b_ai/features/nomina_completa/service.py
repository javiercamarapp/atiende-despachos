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


# _ISR_TABLA and _calcular_isr removed — use calculate_isr from
# b2b_ai.features.compliance (LISR Art. 96, 2024 monthly table).
# Previously had a wrong "simplified 2026" table that returned $0 ISR
# for incomes up to $47,071.37, causing incorrect CFDI Nómina totals.


def _calcular_imss_obrero(salario_diario: float, dias_pagados: int = 30) -> float:
    """Calcula la cuota obrera del IMSS sobre SBC diario × dias_pagados.

    Cuotas obreras por día (LSS arts. 105-109, 2026 estimado):
    - Enfermedades y maternidad (cuota fija): 0.25% del SBC
    - Invalidez y vida: 0.625% del SBC
    - Retiro: 2.00% (patronal, no obrero)
    - Cesantía y vejez (cuota obrera): 0.325% del SBC
    - Guardarantía: 0.125% del SBC (patronal, no obrero)

    Obrero paga: EYM cuota fija + IV + RCVA = ~1.20% por día
    Cuota total = SBC_diario × dias_pagados × tasa
    """
    # SBC diario × días pagados = base del periodo
    base_periodo = salario_diario * dias_pagados
    # Cuota obrera simplificada (~1.20% del SBC diario × días)
    # EYM 0.25% + IV 0.625% + RCVA 0.325% = 1.20%
    cuota_obrero = base_periodo * 0.0120
    return cuota_obrero


def _calcular_imss_patronal(salario_diario: float, dias_pagados: int = 30) -> float:
    """Calcula la cuota patronal del IMSS sobre SBC diario × dias_pagados.

    Cuotas patronales por día (LSS arts. 105-109):
    - EYM cuota fija: 20.40% (excedente 3 UMA 1.10%)
    - Invalidez y vida: 1.75%
    - Retiro: 2.00%
    - Cesantía y vejez: 3.150% (excedente 2 UMA 1.400%)
    - Guardarantía: 1.25%
    - Total patronal ~20.40% (simplificado para nómina)
    """
    base_periodo = salario_diario * dias_pagados
    # Patronal simplificada: ~20.40% del SBC × días
    cuota_patronal = base_periodo * 0.2040
    return cuota_patronal


def _calcular_infonavit(salario_diario: float, dias_pagados: int = 30) -> float:
    """Calcula la aportación al INFONAVIT (5% del SBC diario × dias_pagados).

    NOTA: Esta es provisión PATRONAL (Ley INFONAVIT art. 29-II),
    NO deducción al trabajador.
    """
    base_periodo = salario_diario * dias_pagados
    return base_periodo * 0.05


def _calcular_subsidio(ingreso_gravado: float, periodicidad: str = "mensual") -> dict:
    """Calcula el subsidio para el empleo (LISR Art. 113).

    El subsidio es de aplicación obligatoria para el patrón cuando el
    ingreso gravado no excede cierto umbral. Se acredita contra el ISR
    del periodo; si lo excede, se entrega en efectivo al trabajador.

    Devuelve {subsidio, subsidio_efectivo, isr_neto}.
    """
    if ingreso_gravado <= 0:
        return {"subsidio": 0.0, "subsidio_efectivo": 0.0, "isr_neto": 0.0}

    # Tabla de subsidio mensual (Decreto DOF, ~2024-2026)
    # Rangos de subsidio mensual por ingreso gravado
    tabla_subsidio = [
        (0.01, 1866.00, 455.93),
        (1866.01, 2745.50, 440.66),
        (2745.51, 3464.73, 422.10),
        (3464.74, 3889.13, 407.10),
        (3889.14, 4725.53, 387.10),
        (4725.54, 5599.93, 363.27),
        (5599.94, 6318.15, 333.33),
        (6318.16, 7091.11, 303.32),
        (7091.12, 7809.32, 271.63),
        (7809.33, 11318.15, 237.18),
        (11318.16, 14196.00, 172.28),
        (14196.01, 16872.45, 105.31),
        (16872.46, 20058.37, 70.23),
        (20058.38, 23116.81, 30.68),
        (23116.82, float("inf"), 0.00),
    ]

    # Convertir a base quincenal si es necesario
    monto = ingreso_gravado
    if periodicidad == "quincenal":
        monto = ingreso_gravado * 2  # equivalente mensual

    subsidio = 0.0
    for lim_inf, lim_sup, sub_mensual in tabla_subsidio:
        if lim_inf <= monto <= lim_sup:
            subsidio = sub_mensual
            break

    # Convertir a base del periodo
    if periodicidad == "quincenal":
        subsidio_periodo = subsidio / 2
    else:
        subsidio_periodo = subsidio

    # ISR neto: ISR antes del subsidio menos subsidio (si subsidio > ISR, queda 0)
    # El subsidio_efectivo es el excedente que se entrega en efectivo
    return {
        "subsidio": round(subsidio_periodo, 2),
        "subsidio_efectivo": 0.0,  # Se calcula al integrar con ISR
        "isr_neto": 0.0,
    }


def calculate_taxes(salary: float, benefits: float = 0.0,
                    salary_per_day: float = 0.0,
                    dias_pagados: int = 30,
                    periodicidad: str = "mensual") -> PayrollTaxes:
    """Calcula ISR, IMSS y INFONAVIT para un salario mensual.

    Args:
        salary: Salario bruto mensual (o diario si se especifica).
        benefits: Prestaciones gravables.
        salary_per_day: Si se provee, salary se interpreta como diario.
        dias_pagados: Días pagados en el periodo (default 30).
        periodicidad: 'mensual' o 'quincenal' para ISR.

    Returns:
        PayrollTaxes con el desglose completo.
    """
    if salary_per_day > 0:
        salario_mensual = salary_per_day * 30
        salario_diario = salary_per_day
    else:
        salario_mensual = salary
        salario_diario = salary / 30 if salary > 0 else 0

    # Ingreso gravable = salario + prestaciones
    gravable = salario_mensual + benefits

    # ISR: usar tabla según periodicidad
    if periodicidad == "quincenal":
        # Para quincenal, calcular ISR mensual y dividir entre 2
        isr_mensual = calculate_isr(gravable)
        isr = round(isr_mensual / 2, 2)
    else:
        isr = calculate_isr(gravable)

    # IMSS: calcular sobre SBC diario × dias_pagados
    imss_obrero = _calcular_imss_obrero(salario_diario, dias_pagados)
    imss_patronal = _calcular_imss_patronal(salario_diario, dias_pagados)
    infonavit = _calcular_infonavit(salario_diario, dias_pagados)

    # Subsidio para el empleo (LISR Art. 113)
    subsidio_info = _calcular_subsidio(gravable, periodicidad)
    subsidio = subsidio_info["subsidio"]
    # ISR neto = ISR antes del subsidio menos subsidio (si subsidio > ISR, queda 0)
    isr_neto = max(0.0, isr - subsidio)
    # Si subsidio > ISR, el excedente se entrega en efectivo al trabajador
    subsidio_efectivo = max(0.0, subsidio - isr)

    return PayrollTaxes(
        isr=round(isr_neto, 2),
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
            dias_pagados=dias_pagados,
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
