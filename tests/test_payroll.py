# -*- coding: utf-8 -*-
"""Tests FASE 2 — nómina: ISR, IMSS, INFONAVIT, PTU, prestaciones y CFDI."""
from decimal import Decimal

from b2b_ai.services.payroll import (calc_isr, calc_imss, calc_infonavit,
                                     calc_ptu, calc_aguinaldo,
                                     dias_vacaciones, calc_vacaciones,
                                     calc_prima_vacacional, calculate_payroll,
                                     generate_payroll_cfdi)


def test_isr_rango_bajo():
    r = calc_isr(8000)
    esperado = Decimal("371.83") + (Decimal("8000") - Decimal("6332.06")) * Decimal("0.1088")
    assert abs(Decimal(r["impuesto"]) - esperado.quantize(Decimal("0.01"))) < Decimal("0.01")


def test_isr_cero():
    assert calc_isr(0)["impuesto"] == "0.00"


def test_isr_ultimo_rango():
    r = calc_isr(500000)
    assert r["rango_aplicado"]["limite_inferior"] == "375975.62"


def test_imss_total_positivo():
    r = calc_imss(15000)
    assert Decimal(r["total"]) > 0
    # total = eym (includes excedente_3uma) + iv + rcva + gmp (LSS arts. 105-109)
    assert Decimal(r["total"]) == (Decimal(r["eym"]) + Decimal(r["iv"])
                                    + Decimal(r["rcva"]) + Decimal(r["gmp"]))


def test_infonavit_cinco_porciento():
    r = calc_infonavit(10000)
    assert r["cuota"] == "500.00"


def test_ptu_diez_porciento():
    r = calc_ptu(100000)
    assert r["ptu"] == "10000.00"


def test_aguinaldo_anio_completo():
    r = calc_aguinaldo(500)
    assert r["aguinaldo"] == "7500.00"  # 15 días


def test_aguinaldo_proporcional():
    r = calc_aguinaldo(500, dias_trabajados=182)
    assert r["proporcional"] is True
    assert Decimal(r["aguinaldo"]) < Decimal("7500.00")


def test_vacaciones_por_antiguedad():
    assert dias_vacaciones(1) == 12
    assert dias_vacaciones(4) == 18
    assert dias_vacaciones(5) == 20
    assert dias_vacaciones(10) == 22


def test_prima_vacacional_25():
    r = calc_prima_vacacional(500, 1)  # 12 días → 6000, 25% → 1500
    assert r["prima"] == "1500.00"
    assert r["dias"] == 12


def test_calculate_payroll_desglose():
    emp = {"nombre": "JUAN PEREZ", "rfc": "JCCP840101HDA", "salario_diario": 1000}
    res = calculate_payroll(emp, 15000, dias_pagados=15)
    assert res["neto_a_pagar"] != "0.00"
    assert res["deducciones"]["isr"] != "0.00"
    assert res["requires_human_review"] is True
    # neto = percepciones - deducciones
    total = Decimal(res["percepciones"]["total"])
    ded = Decimal(res["total_deducciones"])
    neto = Decimal(res["neto_a_pagar"])
    assert neto == (total - ded).quantize(Decimal("0.01"))


def test_generate_payroll_cfdi_xml():
    emp = {"rfc": "JCCP840101HDA", "curp": "JCCP840101HDA000", "nombre": "JUAN PEREZ",
           "salario_diario": 1000, "num_seguridad_social": "111222333", "periodicidad": "Mensual"}
    emisor = {"rfc": "DESP820101AB1", "nombre": "DESPACHO S.C.", "regimen_fiscal": "601"}
    periodo = {"fecha_pago": "2026-07-15", "fecha_inicial": "2026-07-01",
               "fecha_final": "2026-07-15", "dias_pagados": 15}
    xml = generate_payroll_cfdi(emp, emisor, periodo)
    assert "<cfdi:Comprobante" in xml
    assert "TipoDeComprobante=\"N\"" in xml
    assert "<nomina:Nomina" in xml
    assert "TotalDeducciones" in xml
    assert "Curp=" in xml and "NumSeguridadSocial=" in xml


def test_payroll_cfdi_arithmetic():
    """[38] Verify CFDI Total = SubTotal − TotalDeducciones and
    TotalPercepciones = sum of actual percepciones, not just tag presence."""
    import xml.etree.ElementTree as ET
    from b2b_ai.services.payroll import calculate_payroll

    emp = {"rfc": "JCCP840101HDA", "curp": "JCCP840101HDA000", "nombre": "JUAN PEREZ",
           "salario_diario": 1000, "num_seguridad_social": "111222333", "periodicidad": "Mensual"}
    emisor = {"rfc": "DESP820101AB1", "nombre": "DESPACHO S.C.", "regimen_fiscal": "601"}
    periodo = {"fecha_pago": "2026-07-15", "fecha_inicial": "2026-07-01",
               "fecha_final": "2026-07-15", "dias_pagados": 15}

    res = calculate_payroll(emp, sueldo_bruto=15000, dias_pagados=15)
    xml = generate_payroll_cfdi(emp, emisor, periodo, resultados=res)

    # Parse XML
    root = ET.fromstring(xml)
    ns = {"cfdi": "http://www.sat.gob.mx/cfd/4",
          "nomina": "http://www.sat.gob.mx/nomina12"}

    total = Decimal(root.attrib["Total"])
    subtotal = Decimal(root.attrib["SubTotal"])

    # Complemento Nomina
    nomina = root.find(".//nomina:Nomina", ns)
    assert nomina is not None, "Missing nomina:Nomina complement"
    total_percepciones = Decimal(nomina.attrib["TotalPercepciones"])
    total_deducciones = Decimal(nomina.attrib.get("TotalDeducciones", "0"))

    # Total = SubTotal − TotalDeducciones
    assert total == subtotal - total_deducciones, (
        f"Total ({total}) != SubTotal ({subtotal}) − TotalDeducciones ({total_deducciones})")

    # TotalPercepciones == SubTotal (both represent gross pay)
    assert total_percepciones == subtotal, (
        f"TotalPercepciones ({total_percepciones}) != SubTotal ({subtotal})")

    # TotalPercepciones = sum of actual percepciones from calculate_payroll
    expected_percepciones = Decimal(res["percepciones"]["total"])
    assert total_percepciones == expected_percepciones.quantize(Decimal("0.01")), (
        f"TotalPercepciones ({total_percepciones}) != "
        f"calculate_payroll result ({expected_percepciones})")

    # TotalDeducciones = sum of actual deductions from calculate_payroll
    expected_deducciones = Decimal(res["total_deducciones"])
    assert total_deducciones == expected_deducciones.quantize(Decimal("0.01")), (
        f"TotalDeducciones ({total_deducciones}) != "
        f"calculate_payroll result ({expected_deducciones})")
