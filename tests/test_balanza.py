# -*- coding: utf-8 -*-
"""Tests — balanza de comprobación (FASE 3 contabilidad electrónica)."""
import xml.etree.ElementTree as ET

from b2b_ai.services.catalogo_cuentas import CatalogoCuentas
from b2b_ai.services.balanza import BalanzaComprobacion

# Asientos: compra de equipo (debe activo fijo 1202, haber bancos 1101),
# venta de servicios (debe bancos 1101, haber ingresos 4100).
ASIENTOS = [
    {"cuenta": "1202", "debe": "5800.00", "haber": "0", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "0", "haber": "5800.00", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "9000.00", "haber": "0", "fecha": "2026-07-10"},
    {"cuenta": "4100", "debe": "0", "haber": "9000.00", "fecha": "2026-07-10"},
]


def test_generar_acumula_por_cuenta():
    bal = BalanzaComprobacion(CatalogoCuentas())
    resumen = bal.generar(ASIENTOS, periodo="2026-07")
    cuentas = {l["cuenta"] for l in bal.lineas}
    assert {"1101", "1202", "4100"} <= cuentas
    assert resumen["periodo"] == "2026-07"
    assert resumen["cuentas"] == 3


def test_cuadratura():
    bal = BalanzaComprobacion(CatalogoCuentas())
    bal.generar(ASIENTOS, periodo="2026-07")
    assert bal.validar_cuadratura() is True
    resumen = bal.resumen()
    assert resumen["cuadrada"] is True
    # debe = 5800 + 9000 = 14800 ; haber = 5800 + 9000 = 14800
    assert resumen["total_debe"] == "14800.00"
    assert resumen["total_haber"] == "14800.00"


def test_campos_saldo_inicial_final():
    bal = BalanzaComprobacion(CatalogoCuentas())
    bal.generar(ASIENTOS, periodo="2026-07",
                saldos_iniciales={"1101": "1000.00"})
    b1101 = next(l for l in bal.lineas if l["cuenta"] == "1101")
    # 1101 deudora: saldoIni 1000 + debe 9000 - haber 5800 = 4200
    assert b1101["saldo_inicial"] == "1000.00"
    assert b1101["debe"] == "9000.00"
    assert b1101["haber"] == "5800.00"
    assert b1101["saldo_final"] == "4200.00"


def test_acumulacion_por_periodo():
    bal = BalanzaComprobacion(CatalogoCuentas())
    asientos = ASIENTOS + [
        {"cuenta": "6102", "debe": "300.00", "haber": "0",
         "fecha": "2026-08-05"},
        {"cuenta": "1101", "debe": "0", "haber": "300.00",
         "fecha": "2026-08-05"},
    ]
    bal.generar(asientos, periodo="2026-07")
    cuentas = {l["cuenta"] for l in bal.lineas}
    assert "6102" not in cuentas  # movimiento de agosto filtrado
    assert len(bal.lineas) == 3


def test_detectar_saldos_anomalos():
    # Cuenta deudora (1101) con haber > debe -> saldo negativo -> anómala.
    anomalos_asientos = [
        {"cuenta": "1101", "debe": "0", "haber": "5000.00",
         "fecha": "2026-07-01"},
        {"cuenta": "2101", "debe": "5000.00", "haber": "0",
         "fecha": "2026-07-01"},
    ]
    bal = BalanzaComprobacion(CatalogoCuentas())
    bal.generar(anomalos_asientos, periodo="2026-07")
    anomalos = bal.detectar_saldos_anomalos()
    cuentas_anom = {a["cuenta"] for a in anomalos}
    assert "1101" in cuentas_anom  # deudora con saldo negativo
    resumen = bal.resumen()
    assert "1101" in resumen["saldos_anomalos"]


def test_generar_xml_balanza():
    bal = BalanzaComprobacion(CatalogoCuentas())
    bal.generar(ASIENTOS, periodo="2026-07")
    xml = bal.generar_xml(rfc="DESP820101AB1", ejercicio=2026, mes=7)
    root = ET.fromstring(xml)  # XML bien formado
    ns = {"BCE": "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/BalanzaComprobacion"}
    assert root.attrib["Version"] == "1.3"
    assert root.attrib["RFC"] == "DESP820101AB1"
    assert root.attrib["Mes"] == "07"
    assert root.attrib["Anio"] == "2026"
    assert root.attrib["TipoEnvio"] == "B"
    ctas = root.findall("BCE:Ctas/BCE:Cta", ns)
    assert len(ctas) == len(bal.lineas)
    for c in ctas:
        assert c.attrib["NumCta"]
        assert c.attrib["SaldoIni"]
        assert c.attrib["Debe"]
        assert c.attrib["Haber"]
        assert c.attrib["SaldoFin"]
