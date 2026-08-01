# -*- coding: utf-8 -*-
"""Tests FASE — conciliación bancaria real con upload.

Cubre: perfiles de banco, upload CSV/PDF, matching exacto/parcial/AI con
confidence 0-100, confirmación manual, reporte y los 4 endpoints de la API.
"""
import io

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.services.bank_reconciliation import (
    BankReconciliation, SUPPORTED_BANKS, _normalize_bank, _dec)

API_KEY = "tenant1-key"
SERVICE_KEY = "service-master-key"

CSV_BBVA = """Estado de cuenta BBVA
Fecha;Descripcion;Cargo;Abono;Referencia
03/07/2026;Transferencia saliente;5800.00;;REF-1
10/07/2026;Pago efectivo;300.00;;REF-2
15/07/2026;Deposito cliente;;9999.00;REF-3
"""

CSV_GENERICO = ("Fecha,Monto,Descripcion,Referencia\n"
                "2026-07-03,-5800.00,Transferencia,REF-1\n"
                "2026-07-20,777.00,Otro,ORPHAN\n")

INVOICES = [
    {"folio_fiscal": "REF-1", "fecha": "2026-07-03", "total": "5800.00",
     "emisor": "Proveedor A", "emisor_nombre": "Proveedor A"},
    {"folio_fiscal": "REF-2", "fecha": "2026-07-10", "total": "300.00",
     "emisor": "Proveedor B", "emisor_nombre": "Proveedor B"},
]


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------
# Perfiles de banco
# --------------------------------------------------------------------------
def test_banks_soportados():
    assert "bbva" in SUPPORTED_BANKS
    assert "banorte" in SUPPORTED_BANKS
    assert "santander" in SUPPORTED_BANKS
    assert "hsbc" in SUPPORTED_BANKS
    assert "generico" in SUPPORTED_BANKS


def test_normalize_bank_tolerante():
    assert _normalize_bank("BBVA") == "bbva"
    assert _normalize_bank("BBVA Bancomer") == "bbva"
    assert _normalize_bank("banorte") == "banorte"
    assert _normalize_bank("HSBC") == "hsbc"
    assert _normalize_bank("otro") == "generico"
    assert _normalize_bank(None) == "generico"


# --------------------------------------------------------------------------
# upload / parse
# --------------------------------------------------------------------------
def test_upload_csv_bbva(tmp_path):
    path = _write(tmp_path, "bbva.csv", CSV_BBVA)
    svc = BankReconciliation()
    res = svc.upload_statement(path, "bbva")
    assert res["banco"] == "bbva"
    assert res["movimientos"] == 3
    assert len(svc.transactions) == 3
    # El cargo queda negativo, el abono positivo.
    assert svc.transactions[0]["monto_signed"] == "-5800.00"
    assert svc.transactions[2]["monto_signed"] == "9999.00"


def test_upload_csv_generico_single_monto(tmp_path):
    path = _write(tmp_path, "gen.csv", CSV_GENERICO)
    svc = BankReconciliation()
    res = svc.upload_statement(path, "generico")
    assert res["movimientos"] == 2


def test_upload_pdf(tmp_path):
    inner = (b"%(PDF)%\n"
             b"(03/07/2026  5800.00  -5800.00  TRANSFERENCIA REF-1) Tj\n"
             b"(10/07/2026  300.00  -300.00  PAGO EFECTIVO REF-2) Tj\n")
    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
           b"2 0 obj<</Length 0>>stream\n" + inner +
           b"\nendstream endobj\nxref\n%%EOF\n")
    path = tmp_path / "banco.pdf"
    path.write_bytes(pdf)
    svc = BankReconciliation()
    res = svc.upload_statement(str(path), "generico")
    assert res["movimientos"] == 2


def test_parse_csv_file_like():
    svc = BankReconciliation()
    rows = svc.parse_csv_statement(io.StringIO(CSV_BBVA))
    assert len(rows) == 3
    assert rows[0]["ref"] == "REF-1"


# --------------------------------------------------------------------------
# Matching con confidence
# --------------------------------------------------------------------------
def test_match_exacto_confidence_alto():
    svc = BankReconciliation()
    svc.upload_statement(_write_path_buf(), "generico")
    svc.load_invoices(INVOICES)
    res = svc.auto_match()
    matches = res["matches"]
    # 2 facturas deberían conciliar exacto por monto+fecha.
    exact = [m for m in matches if m["method"] == "exact"]
    assert len(exact) == 2
    assert all(m["confidence"] >= 90 for m in exact)
    # Ordenados por confidence (auto_matchconfidence)
    conf = res["auto_matchconfidence"]
    assert conf == sorted(conf, key=lambda m: -m["confidence"])


def test_match_parcial_por_referencia():
    svc = BankReconciliation()
    csv = ("Fecha;Descripcion;Abono;Referencia\n"
           "2026-08-01;Pago;5805.00;REF-1\n")   # monto ~igual + ref
    path = _write_path_buf(csv)
    svc.upload_statement(path, "generico")
    svc.load_invoices([{"folio_fiscal": "REF-1", "fecha": "2026-07-03",
                        "total": "5800.00", "emisor": "A"}])
    res = svc.auto_match(monto_tolerance_pct=5)
    m = res["matches"][0]
    assert m["method"] in ("parcial", "exact")
    assert m["confidence"] > 0


def test_match_ai_fallback_tokens():
    svc = BankReconciliation()
    # Sin LLM configurado -> LLMService mock -> fallback a tokens.
    csv = ("Fecha;Descripcion;Abono;Referencia\n"
           "2026-09-01;Pago factura proveedor A;990.00;\n")
    svc.upload_statement(_write_path_buf(csv), "generico")
    svc.load_invoices([{"folio_fiscal": "X1", "fecha": "2026-07-01",
                        "total": "1000.00", "emisor": "Proveedor A"}])
    res = svc.auto_match(monto_tolerance_pct=20)
    assert res["total"] >= 1
    m = res["matches"][0]
    assert m["confidence"] >= 0 and m["confidence"] <= 100


def test_confidence_siempre_0_100():
    svc = BankReconciliation()
    svc.upload_statement(_write_path_buf(CSV_BBVA), "bbva")
    svc.load_invoices(INVOICES)
    res = svc.auto_match()
    for m in res["matches"]:
        assert 0 <= m["confidence"] <= 100


# --------------------------------------------------------------------------
# Confirmación manual
# --------------------------------------------------------------------------
def test_manual_match_confianza_100():
    svc = BankReconciliation()
    svc.upload_statement(_write_path_buf(CSV_BBVA), "bbva")
    svc.load_invoices(INVOICES)
    tx = svc.transactions[2]   # REF-3 (depósito huérfano)
    m = svc.manual_match(tx["id"], "REF-1")
    assert m["method"] == "manual"
    assert m["confidence"] == 100
    # Al recalcular, el cruce manual está presente.
    found = next((x for x in svc.matches if x["transaction_id"] == tx["id"]),
                 None)
    assert found is not None and found["confidence"] == 100


def test_manual_match_invoice_no_existe():
    svc = BankReconciliation()
    svc.upload_statement(_write_path_buf(CSV_BBVA), "bbva")
    with pytest.raises(ValueError):
        svc.manual_match("tx_x", "no-existe")


# --------------------------------------------------------------------------
# Reporte
# --------------------------------------------------------------------------
def test_generate_reconciliation_report():
    svc = BankReconciliation()
    svc.upload_statement(_write_path_buf(CSV_BBVA), "bbva")
    svc.load_invoices(INVOICES)
    svc.auto_match()
    rep = svc.generate_reconciliation_report()
    assert rep["facturas"] == 2
    assert rep["movimientos_banco"] == 3
    assert rep["conciliados"] == 2
    assert rep["pendientes_banco"] == 1
    assert rep["pendientes_facturas"] == 0
    assert rep["tasa_conciliacion"] > 0
    assert rep["bancos"] == ["bbva"]


# --------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------
import pytest


@pytest.fixture(autouse=True)
def _sin_estado_global_de_reconciliacion():
    """Ya no hay nada que limpiar entre pruebas, y eso es la corrección.

    Aquí había un `_clear_sessions` que vaciaba `rec._SESSIONS` antes y después
    de cada prueba. Era un parche sobre el síntoma: el estado de conciliación
    vivía en un diccionario a nivel de módulo y se filtraba entre pruebas. Lo
    que se arregló es la causa —el estado se persiste por tenant en la base—,
    así que cada prueba queda aislada por su propia `Database` sin ayuda.

    La fixture se conserva vacía a propósito, como guardia: si alguien devuelve
    el global, esto falla y explica por qué.
    """
    import b2b_ai.api.reconciliation as rec
    assert not hasattr(rec, "_SESSIONS"), (
        "volvió el estado global de conciliación: es lo que rompía el "
        "despliegue multi-worker (ver docs/auditoria-2026-08.md, hallazgo 4)")
    yield


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("B2B_API_KEY", SERVICE_KEY)
    db = Database(str(tmp_path / "rec.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")   # id 1
    db.create_api_key(1, "k1", API_KEY)
    # Inyecta una factura de referencia en el tenant 1.
    db.insert_invoice(
        1,
        {"folio_fiscal": "REF-1", "fecha": "2026-07-03", "total": "5800.00",
         "emisor_nombre": "Proveedor A", "emisor_rfc": "XAA010101000"},
        {"categoria": "compras", "confianza": 0.9, "razon": "test"},
        {"ok": True},
        None)
    app = create_app(db)
    return TestClient(app), db


def _h1():
    return {"X-API-Key": API_KEY}


def test_upload_endpoint(client, tmp_path):
    c, _db = client
    path = _write(tmp_path, "bbva.csv", CSV_BBVA)
    with open(path, "rb") as fh:
        r = c.post("/api/v1/reconciliation/upload", headers=_h1(),
                   files={"file": ("bbva.csv", fh, "text/csv")},
                   data={"bank": "bbva"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["banco"] == "bbva"
    assert body["movimientos"] == 3


def test_upload_bank_invalido_rechaza(client, tmp_path):
    c, _db = client
    path = _write(tmp_path, "a.csv", CSV_BBVA)
    with open(path, "rb") as fh:
        r = c.post("/api/v1/reconciliation/upload", headers=_h1(),
                   files={"file": ("a.csv", fh, "text/csv")},
                   data={"bank": "noexiste"})
    assert r.status_code == 400


def test_matches_endpoint(client, tmp_path):
    c, _db = client
    # sube primero
    path = _write(tmp_path, "bbva.csv", CSV_BBVA)
    with open(path, "rb") as fh:
        c.post("/api/v1/reconciliation/upload", headers=_h1(),
               files={"file": ("bbva.csv", fh, "text/csv")},
               data={"bank": "bbva"})
    r = c.get("/api/v1/reconciliation/matches", headers=_h1())
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # La factura REF-1 del tenant concilia con el movimiento REF-1.
    assert any(m.get("invoice_ref") == "REF-1" for m in body)


def test_confirm_endpoint(client, tmp_path):
    c, _db = client
    path = _write(tmp_path, "bbva.csv", CSV_BBVA)
    with open(path, "rb") as fh:
        up = c.post("/api/v1/reconciliation/upload", headers=_h1(),
                    files={"file": ("bbva.csv", fh, "text/csv")},
                    data={"bank": "bbva"}).json()
    tx_id = up["muestra"][2]["id"]   # tercer movimiento (REF-3)
    r = c.post("/api/v1/reconciliation/confirm", headers=_h1(),
               json={"transaction_id": tx_id, "invoice_id": "REF-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["match"]["method"] == "manual"
    assert body["match"]["confidence"] == 100


def test_confirm_transaccion_no_existe(client):
    c, _db = client
    r = c.post("/api/v1/reconciliation/confirm", headers=_h1(),
               json={"transaction_id": "tx_zzz", "invoice_id": "REF-1"})
    assert r.status_code == 404


def test_report_endpoint_sin_movimientos(client):
    c, _db = client
    r = c.get("/api/v1/reconciliation/report", headers=_h1())
    assert r.status_code == 200
    assert r.json().get("ok") is False  # aviso de no hay movimientos


def test_report_endpoint_con_movimientos(client, tmp_path):
    c, _db = client
    path = _write(tmp_path, "bbva.csv", CSV_BBVA)
    with open(path, "rb") as fh:
        c.post("/api/v1/reconciliation/upload", headers=_h1(),
               files={"file": ("bbva.csv", fh, "text/csv")},
               data={"bank": "bbva"})
    r = c.get("/api/v1/reconciliation/report", headers=_h1())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["movimientos_banco"] == 3
    assert body["conciliados"] == 1   # REF-1 concilia; REF-2 no existe en DB


# --------------------------------------------------------------------------
# Helper
# --------------------------------------------------------------------------
def _write_path_buf(content=CSV_BBVA):
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path
