# -*- coding: utf-8 -*-
"""Tests FASE 2 — conciliación bancaria: parsers CSV/PDF y reporte."""
import os

import pytest

from b2b_ai.services.reconcile import (parse_bank_statement_csv,
                                       parse_bank_statement_pdf,
                                       build_reconciliation_report,
                                       reconcile)

CSV_BANCO = """Estado de cuenta mensual
Fecha;Descripcion;Cargo;Abono;Referencia
03/07/2026;Transferencia saliente;5800.00;;REF-1
10/07/2026;Pago efectivo;300.00;;REF-2
15/07/2026;Deposito cliente;;9999.00;REF-3
"""

INVOICES = [
    {"folio_fiscal": "u1", "fecha": "2026-07-03", "total": "5800.00", "emisor": "X"},
    {"folio_fiscal": "u2", "fecha": "2026-07-10", "total": "300.00", "emisor": "Y"},
]


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_parse_csv_cargo_abono(tmp_path):
    path = _write(tmp_path, "banco.csv", CSV_BANCO)
    rows = parse_bank_statement_csv(path)
    assert len(rows) == 3
    assert rows[0]["fecha"] == "2026-07-03"
    assert str(rows[0]["monto"]) == "-5800.00"  # cargo = negativo
    assert rows[0]["ref"] == "REF-1"
    # fila de depósito (abono, sin cargo) también se captura
    assert str(rows[2]["monto"]) == "9999.00"


def test_parse_csv_columna_monto_unica(tmp_path):
    csv_single = ("Fecha,Monto,Descripcion\n"
                  "2026-07-03,-5800.00,Transferencia\n"
                  "2026-07-15,9999.00,Deposito\n")
    path = _write(tmp_path, "single.csv", csv_single)
    rows = parse_bank_statement_csv(path)
    assert len(rows) == 2
    assert str(rows[0]["monto"]) == "-5800.00"
    assert str(rows[1]["monto"]) == "9999.00"


def test_parse_csv_archivo_vacio(tmp_path):
    path = _write(tmp_path, "vacio.csv", "")
    assert parse_bank_statement_csv(path) == []


def _fake_pdf(inner):
    return (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\n"
            b"2 0 obj<</Type/Page/Parent 1 0 R>>endobj\n"
            b"3 0 obj<</Length 0>>stream\n" + inner.encode() +
            b"\nendstream endobj\nxref\n%%EOF\n")


def test_parse_pdf_con_texto(tmp_path):
    pdf = _fake_pdf(
        "(Estado de cuenta)\\n"
        "(03/07/2026  5800.00  -5800.00  TRANSFERENCIA REF-1) Tj\n"
        "(10/07/2026  300.00  -300.00  PAGO EFECTIVO REF-2) Tj\n")
    path = tmp_path / "banco.pdf"
    path.write_bytes(pdf)
    rows = parse_bank_statement_pdf(str(path))
    assert len(rows) == 2
    assert rows[0]["fecha"] == "2026-07-03"
    assert rows[0]["ref"] == "REF-1"


def test_parse_pdf_no_es_pdf(tmp_path):
    path = _write(tmp_path, "no.pdf", "no es un pdf")
    with pytest.raises(ValueError):
        parse_bank_statement_pdf(path)


def test_reconcile_por_referencia():
    # fecha fuera de tolerancia pero referencia exacta -> concilia
    inv = [{"folio_fiscal": "REF-9", "fecha": "2026-01-01", "total": "123.00",
            "emisor": "Z"}]
    bank = [{"fecha": "2026-07-20", "monto": "9999.00",
             "descripcion": "pago", "ref": "REF-9"}]
    r = reconcile(inv, bank, date_tolerance_days=3)
    assert len(r["matched"]) == 1
    assert r["matched"][0]["via"] == "referencia"


def test_build_reconciliation_report():
    bank = [
        {"fecha": "2026-07-03", "monto": "5800.00", "descripcion": "T", "ref": "REF-1"},
        {"fecha": "2026-07-10", "monto": "300.00", "descripcion": "T", "ref": "REF-2"},
        {"fecha": "2026-07-20", "monto": "777.00", "descripcion": "huérfano", "ref": "ORPHAN"},
    ]
    rep = build_reconciliation_report(INVOICES, bank)
    assert rep["conciliados"] == 2
    assert rep["pendientes_banco"] == 1
    assert rep["pendientes_facturas"] == 0
    assert rep["monto_conciliado"] == "6100.00"
    assert rep["tasa_conciliacion"] > 0
    assert rep["por_periodo"]["2026-07"]["conciliados"] == 2
