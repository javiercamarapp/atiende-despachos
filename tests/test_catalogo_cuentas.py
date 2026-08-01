# -*- coding: utf-8 -*-
"""Tests — catálogo de cuentas del SAT (FASE 3 contabilidad electrónica)."""
import os
import tempfile
import xml.etree.ElementTree as ET

import pytest

from b2b_ai.services.catalogo_cuentas import CatalogoCuentas, CATEGORIA_A_CUENTA


def test_catalogo_default_valido():
    cat = CatalogoCuentas()
    assert len(cat) > 20
    assert cat.validar() is True
    assert cat.find("1000").descripcion == "ACTIVO"
    assert cat.find("99999") is None


def test_errores_detectan_cuenta_invalida():
    cat = CatalogoCuentas([
        {"codigo": "1000", "descripcion": "", "nivel": 0, "naturaleza": "X"},
        {"codigo": "1000", "descripcion": "DUP", "nivel": 1, "naturaleza": "D"},
        {"codigo": "2000", "descripcion": "OK", "nivel": 2, "naturaleza": "A"},
    ])
    errs = cat.errores()
    # sin descripción, nivel<1, naturaleza inválida, duplicado -> >=4 errores
    assert len(errs) >= 4
    with pytest.raises(ValueError):
        cat.validar()


def test_importar_csv():
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "catalogo.csv")
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("codigo,descripcion,nivel,naturaleza\n"
                 "7000,VENTAS DE MERCANCIA,1,A\n"
                 "7100,VENTAS NACIONALES,2,A\n")
    cat = CatalogoCuentas()
    n = cat.importar_csv(csv_path)
    assert n == 2
    assert cat.find("7000").naturaleza == "A"
    assert cat.validar() is True


def test_asignar_automatico():
    cat = CatalogoCuentas()
    asign = cat.asignar_automatico({"gasto_operativo": None,
                                    "nomina": "6101",
                                    "ingreso": "99999"})  # cuenta inexistente
    assert asign["gasto_operativo"] == "6102"
    assert asign["nomina"] == "6101"
    # cuenta inexistente -> cae al default del mapeo
    assert asign["ingreso"] == "4100"


def test_generar_xml_catalogo():
    cat = CatalogoCuentas()
    xml = cat.generar_xml(rfc="DESP820101AB1", ejercicio=2026, mes=1)
    root = ET.fromstring(xml)  # XML bien formado
    ns = {"Cat": "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/CatalogoCuentas"}
    ctas = root.findall("Cat:Ctas/Cat:Cta", ns)
    assert len(ctas) == len(cat)
    assert root.attrib["RFC"] == "DESP820101AB1"
    assert root.attrib["Version"] == "1.3"
    assert root.attrib["Mes"] == "01"
    # cada Cta trae NumCta, Desc, Nivel, Natur
    for c in ctas:
        assert c.attrib["NumCta"]
        assert c.attrib["Desc"]
        assert int(c.attrib["Nivel"]) >= 1
        assert c.attrib["Natur"] in ("D", "A")


def test_categoria_a_cuenta_mapeo():
    assert CATEGORIA_A_CUENTA["gasto_operativo"] == "6102"
    assert CATEGORIA_A_CUENTA["nomina"] == "6101"
