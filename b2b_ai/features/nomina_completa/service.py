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
from b2b_ai.fiscal_tables import (
    UMA_MENSUAL_2026,
    get_isr_table,
    get_subsidio_table,
)


# ---------------------------------------------------------------------------
# Parámetros de cuotas IMSS e INFONAVIT (ejercicio 2026).
# Referencia: LSS arts. 105-109 y Ley del INFONAVIT art. 29-II.
#
# El SBC (Salario Base de Cotización) se topa en 25 UMA diarias
# (LSS art. 28), por lo que las cuotas no pueden crecer sin límite.
# ---------------------------------------------------------------------------
# UMA diaria 2026 = UMA mensual / 30.4 (factor legal).
_UMA_DIARIA_2026: float = round(float(UMA_MENSUAL_2026) / 30.4, 2)
_SBC_MAX_UMA: float = 25.0  # tope SBC = 25 UMA diarias (LSS art. 28)

# Cuotas obreras (% del SBC por día) — LSS arts. 105-109.
# EYM (cuota fija) 0.250% + IV 0.625% + Cesantía y Vejez 0.375%
_IMSS_OBRERO_TASA: float = 0.01250

# Cuotas patronales (% del SBC por día) — LSS arts. 105-109.
# EYM excedente 1.10% + IV 1.75% + Retiro 2.00% + Cesantía y Vejez 3.150%
# + Guardería 1.25% + Infonavit 5.00% → total patronal 14.25% del SBC.
# NOTA: EYM cuota fija (20.40% de UMA) es un gasto fijo del patrón que se
# paga independientemente del salario; se omite por claridad en nómina.
_IMSS_PATRONAL_TASA: float = 0.1425

# INFONAVIT (patronal) 5% del SBC — Ley INFONAVIT art. 29-II.
_INFONAVIT_TASA: float = 0.05


def _sbc_diario_topado(salario_diario: float) -> float:
    """Topa el salario diario al máximo SBC = 25 UMA diarias (LSS art. 28)."""
    max_sbc = _UMA_DIARIA_2026 * _SBC_MAX_UMA
    return min(salario_diario, max_sbc)


def _calcular_imss_obrero(salario_diario: float, dias_pagados: int = 30) -> float:
    """Calcula la cuota obrera del IMSS sobre SBC diario × dias_pagados.

    Cuota obrera (LSS arts. 105-109, ejercicio 2026):
    - Enfermedades y maternidad (cuota fija): 0.250% del SBC
    - Invalidez y vida: 0.625% del SBC
    - Cesantía y vejez (cuota obrera): 0.375% del SBC
    Total obrero = 1.25% del SBC diario, con SBC topado a 25 UMA.
    """
    base_periodo = _sbc_diario_topado(salario_diario) * dias_pagados
    return base_periodo * _IMSS_OBRERO_TASA


def _calcular_imss_patronal(salario_diario: float, dias_pagados: int = 30) -> float:
    """Calcula la cuota patronal del IMSS sobre SBC diario × dias_pagados.

    Cuota patronal (LSS arts. 105-109, ejercicio 2026):
    - EYM excedente 1.10% + IV 1.75% + Retiro 2.00% + Cesantía y vejez 3.150%
      + Guardería 1.25% = 9.25%
    Total patronal = 14.25% del SBC (incluye aportación INFONAVIT 5%).
    SBC topado a 25 UMA diarias.
    """
    base_periodo = _sbc_diario_topado(salario_diario) * dias_pagados
    return base_periodo * _IMSS_PATRONAL_TASA


def _calcular_infonavit(salario_diario: float, dias_pagados: int = 30) -> float:
    """Calcula la aportación al INFONAVIT (5% del SBC diario × dias_pagados).

    NOTA: Es provisión PATRONAL (Ley INFONAVIT art. 29-II), gasto del patrón.
    NO es deducción al salario neto del trabajador.
    """
    base_periodo = _sbc_diario_topado(salario_diario) * dias_pagados
    return base_periodo * _INFONAVIT_TASA


def _calcular_subsidio(ingreso_gravado: float, periodicidad: str = "mensual",
                       year: Optional[int] = None) -> dict:
    """Calcula el subsidio para el empleo (LISR Art. 113 / Art. 174).

    El subsidio es de aplicación obligatoria para el patrón cuando el
    ingreso gravado no excede cierto umbral. Se acredita contra el ISR
    del periodo; si lo excede, se entrega en efectivo al trabajador.

    Devuelve {subsidio, subsidio_efectivo, isr_neto}.
    """
    if ingreso_gravado <= 0:
        return {"subsidio": 0.0, "subsidio_efectivo": 0.0, "isr_neto": 0.0}

    # Tabla de subsidio vigente (LISR art. 174) según el ejercicio fiscal.
    # La clave de periodo en fiscal_tables es "monthly"/"quincenal".
    tabla_period = "monthly" if periodicidad == "mensual" else periodicidad
    tabla_subsidio = get_subsidio_table(year, tabla_period)
    # Las filas son (lim_inf, lim_sup, subsidio_mensual) como strings.
    monto = ingreso_gravado

    subsidio = 0.0
    for lim_inf, lim_sup, sub_mensual in tabla_subsidio:
        if float(lim_inf) <= monto <= float(lim_sup):
            subsidio = float(sub_mensual)
            break

    # La tabla ya viene en la periodicidad solicitada (mensual/quincenal).
    subsidio_periodo = subsidio

    # ISR neto: ISR antes del subsidio menos subsidio (si subsidio > ISR, queda 0)
    return {
        "subsidio": round(subsidio_periodo, 2),
        "subsidio_efectivo": 0.0,  # Se calcula al integrar con ISR
        "isr_neto": 0.0,
    }


def calculate_taxes(salary: float, benefits: float = 0.0,
                    salary_per_day: float = 0.0,
                    dias_pagados: int = 30,
                    periodicidad: str = "mensual",
                    year: Optional[int] = None) -> PayrollTaxes:
    """Calcula ISR, IMSS y INFONAVIT para un salario mensual.

    Args:
        salary: Salario bruto mensual (o diario si se especifica).
        benefits: Prestaciones gravables.
        salary_per_day: Si se provee, salary se interpreta como diario.
        dias_pagados: Días pagados en el periodo (default 30).
        periodicidad: 'mensual' o 'quincenal' para ISR.
        year: Ejercicio fiscal para ISR/subsidio (default: vigente).

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

    # ISR: usar tabla según periodicidad y ejercicio vigente (parametrizable).
    if periodicidad == "quincenal":
        # Para quincenal, calcular ISR mensual y dividir entre 2
        isr_mensual = calculate_isr(gravable)
        isr = round(isr_mensual / 2, 2)
    else:
        isr = calculate_isr(gravable)

    # IMSS: calcular sobre SBC diario (topado a 25 UMA) × dias_pagados
    imss_obrero = _calcular_imss_obrero(salario_diario, dias_pagados)
    imss_patronal = _calcular_imss_patronal(salario_diario, dias_pagados)
    infonavit = _calcular_infonavit(salario_diario, dias_pagados)

    # Subsidio para el empleo (LISR Art. 113)
    subsidio_info = _calcular_subsidio(gravable, periodicidad, year)
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
    """Genera un CFDI de Nómina 1.2 en formato dict (retrocompatibilidad).

    Para generación real de XML conforme al XSD del SAT, use
    `generate_cfdi_nomina_xml()`.
    """
    import calendar
    uuid_cfdi = str(uuid.uuid4())
    emisor = payroll_data.get("emisor", {})
    receptor = payroll_data.get("receptor", {})
    period = payroll_data.get("period", {})
    taxes = payroll_data.get("taxes", {})

    year = period.get('year', 2026)
    month = period.get('month', 1)
    # Calcular último día del mes correctamente (considera febrero bisiesto)
    last_day = calendar.monthrange(year, month)[1]

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
                "FechaFinalPago": f"{year:04d}-{month:02d}-{last_day:02d}",
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


def generate_cfdi_nomina_xml(payroll_data: dict) -> str:
    """Genera el XML real de CFDI Nómina 4.0 conforme al XSD del SAT.

    Construye el comprobante CFDI 4.0 (cfdi:Comprobante) con el complemento
    de nómina 1.2 (nomina12:Nomina) según el estándar del SAT.

    Campos obligatorios del XSD que se validan/pueblan:
      - cfdi:Comprobante: Version, Fecha, Serie, Folio, FormaPago,
        MetodoPago, TipoDeComprobante, LugarExpedicion, Moneda, SubTotal,
        Total, NoCertificado, Certificado.
      - cfdi:Emisor: Rfc, Nombre, RegimenFiscal.
      - cfdi:Receptor: Rfc, Nombre, DomicilioFiscalReceptor,
        RegimenFiscalReceptor, UsoCFDI.
      - nomina12:Nomina: Version, TipoNomina, FechaPago, FechaInicialPago,
        FechaFinalPago, NumDiasPagados, Percepciones, Deducciones.

    Raises:
        ValueError: si faltan campos obligatorios del emisor/receptor.
    """
    import calendar
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    emisor = payroll_data.get("emisor", {})
    receptor = payroll_data.get("receptor", {})
    period = payroll_data.get("period", {})
    taxes = payroll_data.get("taxes", {})
    employee = payroll_data.get("employee", {})

    # --- Validación de campos obligatorios (P1-7 análogo para nómina) ---
    emisor_rfc = (emisor.get("rfc") or "").strip()
    receptor_rfc = (receptor.get("rfc") or "").strip()
    if not emisor_rfc:
        raise ValueError("CFDI Nómina: el RFC del emisor es obligatorio.")
    if not receptor_rfc:
        raise ValueError("CFDI Nómina: el RFC del receptor es obligatorio.")
    if not (emisor.get("nombre") or "").strip():
        raise ValueError("CFDI Nómina: el nombre del emisor es obligatorio.")
    if not (receptor.get("nombre") or "").strip():
        raise ValueError("CFDI Nómina: el nombre del receptor es obligatorio.")

    year = period.get("year", 2026)
    month = period.get("month", 1)
    last_day = calendar.monthrange(year, month)[1]
    folio = (payroll_data.get("folio") or str(uuid.uuid4())[:8].upper())

    _CFDI_NS = "http://www.sat.gob.mx/cfd/4"
    _XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
    _NOMINA_NS = "http://www.sat.gob.mx/nomina12"
    _XSI_SCHEMALOC = (
        "http://www.sat.gob.mx/cfd/4 "
        "http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd "
        "http://www.sat.gob.mx/nomina12 "
        "http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd"
    )

    ET.register_namespace("cfdi", _CFDI_NS)
    ET.register_namespace("xsi", _XSI_NS)
    ET.register_namespace("nomina12", _NOMINA_NS)

    subtotal = float(payroll_data.get("subtotal", 0) or 0)
    total = float(payroll_data.get("total", subtotal) or subtotal)

    comprobante = ET.Element(
        f"{{{_CFDI_NS}}}Comprobante",
        attrib={
            "Version": "4.0",
            "Serie": "NOM",
            "Folio": folio,
            "Fecha": f"{year:04d}-{month:02d}-01T00:00:00",
            "FormaPago": "03",
            "NoCertificado": payroll_data.get("no_certificado", "30001000000500003416"),
            "Certificado": payroll_data.get("certificado", ""),
            "SubTotal": f"{subtotal:.2f}",
            "Moneda": "MXN",
            "Total": f"{total:.2f}",
            "TipoDeComprobante": "N",
            "MetodoPago": "PUE",
            "LugarExpedicion": payroll_data.get("lugar_expedicion", "06600"),
            f"{{{_XSI_NS}}}schemaLocation": _XSI_SCHEMALOC,
        },
    )

    emisor_el = ET.SubElement(
        comprobante, f"{{{_CFDI_NS}}}Emisor",
        attrib={
            "Rfc": emisor_rfc,
            "Nombre": emisor.get("nombre", ""),
            "RegimenFiscal": emisor.get("regimen_fiscal", "601"),
        },
    )

    receptor_el = ET.SubElement(
        comprobante, f"{{{_CFDI_NS}}}Receptor",
        attrib={
            "Rfc": receptor_rfc,
            "Nombre": receptor.get("nombre", ""),
            "DomicilioFiscalReceptor": receptor.get(
                "domicilio_fiscal", receptor.get("codigo_postal", "06600")
            ),
            "RegimenFiscalReceptor": receptor.get("regimen_fiscal", "605"),
            "UsoCFDI": "CN01",
        },
    )

    complemento = ET.SubElement(comprobante, f"{{{_CFDI_NS}}}Complemento")
    nomina_el = ET.SubElement(
        complemento, f"{{{_NOMINA_NS}}}Nomina",
        attrib={
            "Version": "1.2",
            "TipoNomina": payroll_data.get("tipo_nomina", "O"),
            "FechaPago": f"{year:04d}-{month:02d}-01",
            "FechaInicialPago": f"{year:04d}-{month:02d}-01",
            "FechaFinalPago": f"{year:04d}-{month:02d}-{last_day:02d}",
            "NumDiasPagados": str(period.get("dias_pagados", 30)),
            "TotalPercepciones": f"{subtotal:.2f}",
            "TotalDeducciones": f"{float(taxes.get('isr', 0) or 0) + float(taxes.get('imss_obrero', 0) or 0):.2f}",
        },
    )

    percepciones_el = ET.SubElement(
        nomina_el, f"{{{_NOMINA_NS}}}Percepciones",
        attrib={"TotalSueldos": f"{subtotal:.2f}"},
    )
    sueldo_el = ET.SubElement(
        percepciones_el, f"{{{_NOMINA_NS}}}Percepcion",
        attrib={
            "TipoPercepcion": "001",
            "Clave": "001",
            "Concepto": "Sueldos, Salarios, Rayas y Jornales",
            "ImporteGravado": f"{subtotal:.2f}",
            "ImporteExento": "0.00",
        },
    )

    if float(taxes.get("isr", 0) or 0) > 0 or float(taxes.get("imss_obrero", 0) or 0) > 0:
        deducciones_el = ET.SubElement(
            nomina_el, f"{{{_NOMINA_NS}}}Deducciones",
            attrib={
                "TotalOtrasDeducciones": f"{float(taxes.get('imss_obrero', 0) or 0):.2f}",
                "TotalImpuestosRetenidos": f"{float(taxes.get('isr', 0) or 0):.2f}",
            },
        )
        if float(taxes.get("isr", 0) or 0) > 0:
            ET.SubElement(
                deducciones_el, f"{{{_NOMINA_NS}}}Deduccion",
                attrib={
                    "TipoDeduccion": "002",
                    "Clave": "002",
                    "Concepto": "ISR",
                    "Importe": f"{float(taxes.get('isr', 0) or 0):.2f}",
                },
            )
        if float(taxes.get("imss_obrero", 0) or 0) > 0:
            ET.SubElement(
                deducciones_el, f"{{{_NOMINA_NS}}}Deduccion",
                attrib={
                    "TipoDeduccion": "001",
                    "Clave": "001",
                    "Concepto": "Seguridad social (IMSS)",
                    "Importe": f"{float(taxes.get('imss_obrero', 0) or 0):.2f}",
                },
            )

    ET.indent(comprobante, space="  ")
    raw = ET.tostring(comprobante, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + raw


def calculate_aguinaldo(salario_diario: float, dias_aguinaldo: int = 15) -> float:
    """Calcula el aguinaldo (LFT art. 87).

    Todo trabajador tiene derecho a un aguinaldo anual equivalente a al menos
    15 días de salario. Si no laboró el año completo, se paga proporcional.

    Args:
        salario_diario: Salario diario del trabajador.
        dias_aguinaldo: Días de aguinaldo a pagar (mínimo legal: 15).

    Returns:
        Importe del aguinaldo.
    """
    return round(max(0, salario_diario) * dias_aguinaldo, 2)


def calculate_prima_vacacional(salario_diario: float,
                               dias_vacaciones: float = 6,
                               porcentaje: float = 0.25) -> float:
    """Calcula la prima vacacional (LFT art. 80).

    Los trabajadores con más de un año de servicios disfrutan de un periodo
    anual de vacaciones pagadas (mínimo 6 días el primer año), que no podrá
    ser inferior a 25% del salario de los días de vacaciones.

    Args:
        salario_diario: Salario diario del trabajador.
        dias_vacaciones: Días de vacaciones del periodo (mínimo 6 el 1er año).
        porcentaje: % de prima vacacional (mínimo legal: 0.25).

    Returns:
        Importe de la prima vacacional.
    """
    base_vacaciones = max(0, salario_diario) * dias_vacaciones
    return round(base_vacaciones * porcentaje, 2)


def generate_payslip(payroll_data: dict) -> dict:
    """Genera un recibo de nómina individual en formato dict.

    En producción, esto generaría un PDF con diseño profesional.
    """
    employee = payroll_data.get("employee", {})
    period = payroll_data.get("period", {})
    taxes = payroll_data.get("taxes", {})

    # Deducciones del trabajador: ISR + IMSS obrero.
    # INFONAVIT es aportación PATRONAL; NO se descuenta del salario neto.
    deducciones_isr = round(taxes.get("isr", 0), 2)
    deducciones_imss = round(taxes.get("imss_obrero", 0), 2)
    deducciones_total = deducciones_isr + deducciones_imss

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
            "isr": deducciones_isr,
            "imss_obrero": deducciones_imss,
            # INFONAVIT patronal se reporta como prestación del patrón,
            # no como deducción al trabajador (Ley INFONAVIT art. 29-II).
            "infonavit": round(taxes.get("infonavit", 0), 2),
            "es_patronal": {
                "infonavit": True,
            },
            "total": round(deducciones_total, 2),
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

        # Neto = bruto + percepciones - deducciones del trabajador.
        # INFONAVIT es aportación PATRONAL (gasto del patrón, Ley INFONAVIT
        # art. 29-II); NO se descuenta del salario del trabajador.
        deducciones = taxes.isr + taxes.imss_obrero
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
