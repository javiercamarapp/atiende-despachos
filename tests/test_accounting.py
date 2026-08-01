# -*- coding: utf-8 -*-
"""Tests FASE 2 — contabilidad electrónica: catálogo, balanza, envío SAT."""
from b2b_ai.services.accounting import (get_catalogo, find_account,
                                        cuenta_para_categoria, build_balance,
                                        build_balanza_from_entries,
                                        build_balanza_xml,
                                        send_balance_to_sat)

INV = [
    {"fecha": "2026-07-03", "total": "5800.00", "categoria": "inversion",
     "tenant_id": 1, "valido": 1},
    {"fecha": "2026-07-10", "total": "300.00", "categoria": "gasto_operativo",
     "tenant_id": 1, "valido": 1},
    {"fecha": "2026-07-11", "total": "9000.00", "categoria": "ingreso",
     "tenant_id": 1, "valido": 1},
]


def test_catalogo_cuentas():
    cat = get_catalogo()
    assert len(cat) > 20
    assert find_account("1000")["descripcion"] == "ACTIVO"
    assert find_account("99999") is None


def test_cuenta_para_categoria():
    assert cuenta_para_categoria("gasto_operativo") == "6102"
    assert cuenta_para_categoria("nomina") == "6101"
    assert cuenta_para_categoria("ingreso") == "4100"


def test_build_balance_agrupa():
    bal = build_balance(INV, period="2026-07", tenant_id=1)
    cuentas = {l["cuenta"] for l in bal["lineas"]}
    assert "1202" in cuentas      # inversión -> equipo de cómputo (deudora)
    assert "4100" in cuentas      # ingreso -> ingresos (acreedora)
    assert "6102" in cuentas      # gasto operativo
    assert bal["periodo"] == "2026-07"
    # 5800 + 300 de cargo, 9000 de abono
    assert bal["total_cargo"] == "6100.00"
    assert bal["total_abono"] == "9000.00"


def test_build_balance_filtro_periodo():
    inv = INV + [{"fecha": "2026-08-01", "total": "100.00", "categoria": "gasto_operativo",
                  "tenant_id": 1, "valido": 1}]
    bal = build_balance(inv, period="2026-07")
    assert bal["movimientos"] == 3  # ignora el de agosto


def test_build_balanza_from_entries():
    entries = [
        {"cuenta": "1101", "cargo": "1000", "abono": "0"},
        {"cuenta": "4100", "cargo": "0", "abono": "1000"},
    ]
    bal = build_balanza_from_entries(entries)
    assert bal["balanceado"] is True
    assert bal["total_cargo"] == "1000.00"


def test_balanza_xml_tiene_cuentas():
    bal = build_balance(INV)
    xml = build_balanza_xml(bal, 2026, 7, rfc="DESP820101AB1")
    assert "<ct:Balanza" in xml
    assert "NumCta=" in xml
    assert "DESP820101AB1" in xml


def test_send_balance_to_sat_mock():
    bal = build_balance(INV)
    acuse = send_balance_to_sat(bal, 2026, 7, rfc="DESP820101AB1")
    assert acuse["estatus"] == "Aceptado"
    assert acuse["mock"] is True
    assert acuse["folio"]
    assert acuse["ejercicio"] == 2026 and acuse["mes"] == 7
