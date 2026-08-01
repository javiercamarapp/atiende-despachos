# -*- coding: utf-8 -*-
"""
Suite E2E del enterprise MVP (FASE: cobertura completa).

Cubre lo que pide el ticket:

1. Flujo completo por la API: upload CFDI XML -> parse -> validate -> classify
   -> store -> report -> export.
   Nota: el MVP no tiene endpoint de "export" dedicado; la exportación se
   materializa en (a) generate_report (GET /api/v1/stats.report) y (b) el
   JSON del dashboard (GET /api/v1/dashboard/data), ambos verificados aquí.

2. Multi-tenant: 3 tenants con aislamiento verificado (lecturas, stats,
   detalle por id, IDOR bloqueado).

3. Batch processing: 100 CFDI generados en lote por la API (process_batch).

4. Error recovery: CFDI corrupto (422), duplicado (insertado=False, sin
   re-insertar), cancelado (gate de cancelación -> requiere revisión humana
   y no cancela sin confirmación).

5. Cobertura API + CLI completa (process, batch, report, status).
"""
import glob
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from gen_cfdis import generate  # noqa: E402

from b2b_ai.db.db import Database  # noqa: E402
from b2b_ai.api.app import create_app  # noqa: E402
from b2b_ai.cli import main as cli_main  # noqa: E402
from b2b_ai.cfdi.cancellation import (evaluate_cancellation,  # noqa: E402
                                      prepare_cancellation_request)

FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")


@pytest.fixture
def ctx(tmp_path):
    db = Database(str(tmp_path / "e2e.db"))
    tenants = []
    keys = {}
    for i, name in enumerate(["Despacho A", "Despacho B", "Despacho C"]):
        t = db.create_tenant(name, rfc=f"XAXX01010100{i}")
        tenants.append(t)
        keys[t] = f"key-{name.lower().replace(' ', '-')}-000{i}"
        db.create_api_key(t, name, keys[t])
    app = create_app(db)
    client = TestClient(app)
    return {"client": client, "db": db, "tenants": tenants, "keys": keys}


def _fixture(name):
    return os.path.join(FIXTURES, name)


def _all_fixtures():
    return sorted(glob.glob(os.path.join(FIXTURES, "*.xml")))


# --------------------------------------------------------------------------- #
# 1. Flujo completo (API): upload -> parse -> validate -> classify -> store
#    -> report -> export
# --------------------------------------------------------------------------- #
def test_flujo_completo_upload_a_export(ctx):
    c = ctx["client"]
    k = ctx["keys"][ctx["tenants"][0]]
    h = {"X-API-Key": k}

    # upload multipart
    with open(_fixture("02_inversion_consultoria.xml"), "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("02.xml", fh, "text/xml")})
    assert r.status_code == 200
    res = r.json()["result"]
    # parse + validate + classify + store
    assert res["valido"] is True
    assert res["categoria"] == "inversion"
    assert res["confianza"] >= 0.5
    assert res["insertado"] is True
    assert res["erp_poliza"]
    # total devuelto por _strip (numérico, desde el parsing del XML)
    assert float(res["total"]) == 5800.0

    # report: stats trae agregados sobre lo almacenado
    st = c.get("/api/v1/stats", headers=h).json()
    assert st["total_facturas"] == 1
    assert st["report"]["total"] == "5800.00"
    assert st["report"]["por_categoria"]["inversion"]["count"] == 1

    # export: JSON del dashboard refleja la misma factura
    dd = c.get("/api/v1/dashboard/data", headers=h).json()
    assert dd["metricas"]["total_facturas"] == 1
    assert float(dd["metricas"]["monto_total"]) == 5800.00
    assert "inversion" in [x["categoria"] for x in dd["graficas"]["por_categoria"]]

    # la factura quedó persistida en DB
    assert ctx["db"].count_invoices() == 1


# --------------------------------------------------------------------------- #
# 2. Multi-tenant con 3 tenants
# --------------------------------------------------------------------------- #
def test_multi_tenant_3_tenants_aislados(ctx):
    c, db = ctx["client"], ctx["db"]
    t0, t1, t2 = ctx["tenants"]
    ha, hb, hc = ({"X-API-Key": ctx["keys"][t]} for t in (t0, t1, t2))

    files = {"02_inversion_consultoria.xml": t0,
             "01_gasto_operativo_papeleria.xml": t1,
             "04_nomina_pago.xml": t2}
    for name, t in files.items():
        hdr = {"X-API-Key": ctx["keys"][t]}
        r = c.post("/api/v1/invoices/process", headers=hdr,
                   json={"xml_path": _fixture(name)})
        assert r.status_code == 200, name
        assert r.json()["result"]["insertado"] is True

    # cada tenant ve exactamente 1 factura (la suya)
    assert c.get("/api/v1/invoices", headers=ha).json()["count"] == 1
    assert c.get("/api/v1/invoices", headers=hb).json()["count"] == 1
    assert c.get("/api/v1/invoices", headers=hc).json()["count"] == 1
    assert db.count_invoices() == 3

    # stats aislados
    assert c.get("/api/v1/stats", headers=ha).json()["total_facturas"] == 1

    # A no puede leer el detalle de B ni de C
    id_b = c.get("/api/v1/invoices", headers=hb).json()["invoices"][0]["id"]
    id_c = c.get("/api/v1/invoices", headers=hc).json()["invoices"][0]["id"]
    assert c.get(f"/api/v1/invoices/{id_b}", headers=ha).status_code == 404
    assert c.get(f"/api/v1/invoices/{id_c}", headers=ha).status_code == 404

    # B no puede forzar el tenant de A vía query param (regresión IDOR)
    forced = c.get("/api/v1/invoices", headers=hb,
                   params={"tenant_id": t0}).json()
    assert forced["tenant_id"] == t1
    assert forced["count"] == 1


# --------------------------------------------------------------------------- #
# 3. Batch processing: 100 CFDI en lote
# --------------------------------------------------------------------------- #
def test_batch_100_cfdi_api(ctx, tmp_path):
    c, db = ctx["client"], ctx["db"]
    k = ctx["keys"][ctx["tenants"][0]]
    batch_dir = str(tmp_path / "batch100")
    generate(100, batch_dir)
    h = {"X-API-Key": k}

    # procesar el lote vía endpoint legacy (folder) que usa process_batch
    r = c.post("/process", headers=h, json={"folder": batch_dir})
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["procesadas"] == 100
    # Some CFDIs may be flagged as invalid by the new SAT validation
    # (folios ending in '0' are reported as "cancelado" by the mock validator).
    assert summary["validas"] + summary["con_observaciones"] == 100
    assert summary["insertadas"] == 100

    # todo persistido
    assert db.count_invoices() == 100
    lst = c.get("/api/v1/invoices", headers=h,
                params={"limit": 1000}).json()
    assert lst["count"] == 100


# --------------------------------------------------------------------------- #
# 4. Error recovery
# --------------------------------------------------------------------------- #
def test_error_recovery_corrupto(ctx, tmp_path):
    c = ctx["client"]
    h = {"X-API-Key": ctx["keys"][ctx["tenants"][0]]}
    bad = tmp_path / "corrupto.xml"
    bad.write_text("<?xml version='1.0'?><root><not/></root>")

    # XML que no es CFDI -> 422 controlado (no 500, no crash)
    with open(bad, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("corrupto.xml", fh, "text/xml")})
    assert r.status_code == 422

    # XML que ni siquiera es XML válido
    garbled = tmp_path / "basura.txt"
    garbled.write_text("not xml at all {{{")
    with open(garbled, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("basura.txt", fh, "text/xml")})
    assert r.status_code == 422

    # el sistema sigue sano después de los errores
    assert c.get("/api/v1/stats", headers=h).status_code == 200
    assert c.get("/health").status_code == 200


def test_error_recovery_duplicado(ctx):
    c, db = ctx["client"], ctx["db"]
    h = {"X-API-Key": ctx["keys"][ctx["tenants"][0]]}
    f = _fixture("02_inversion_consultoria.xml")

    r1 = c.post("/api/v1/invoices/process", headers=h, json={"xml_path": f})
    r2 = c.post("/api/v1/invoices/process", headers=h, json={"xml_path": f})
    assert r1.json()["result"]["insertado"] is True
    assert r2.json()["result"]["insertado"] is False
    # no se duplicó el registro (mismo UUID de folio fiscal)
    assert db.count_invoices() == 1


def test_error_recovery_cancelado(ctx):
    """Un CFDI con monto alto NO se cancela sin confirmación humana: el gate
    devuelve decision=requiere_aceptacion_receptor y prepare exige
    confirmacion_humana (dry_run). El sistema no permite cancelarlo a ciegas."""
    factura_alta = {"tipo": "I", "total": "100000.00",
                    "folio_fiscal": "uuid-cancel-test",
                    "emisor_rfc": "CON950820K12", "metodo_pago": "PUE",
                    "cfdi_relacionados": []}

    ev = evaluate_cancellation(factura_alta)
    assert ev["decision"] == "requiere_aceptacion_receptor"
    assert ev["requires_human_review"] is True

    # sin confirmación -> bloqueado
    payload, errores = prepare_cancellation_request(factura_alta)
    assert errores, "debe exigir confirmación humana para cancelar monto alto"
    assert payload["dry_run"] is True
    assert payload["estado"] == "preparado_para_revision_humana"


# --------------------------------------------------------------------------- #
# 5. Cobertura CLI
# --------------------------------------------------------------------------- #
def test_cli_process_y_report(ctx, tmp_path, capsys):
    db_path = str(tmp_path / "cli.db")
    os.environ["B2B_DB_PATH"] = db_path
    try:
        assert cli_main(["process", _fixture("03_activo_fijo_computadora.xml")]) == 0
        assert cli_main(["report", "--period", "2026-07"]) == 0
        assert cli_main(["status"]) == 0
    finally:
        os.environ.pop("B2B_DB_PATH", None)
    out = capsys.readouterr().out
    assert "PROCESADO" in out.upper() or "Procesado" in out
    assert "Total" in out


def test_cli_batch(ctx, tmp_path):
    db_path = str(tmp_path / "cli_batch.db")
    batch_dir = str(tmp_path / "cli_batch_in")
    generate(10, batch_dir)
    os.environ["B2B_DB_PATH"] = db_path
    try:
        assert cli_main(["batch", batch_dir]) == 0
    finally:
        os.environ.pop("B2B_DB_PATH", None)


def test_cli_error_salida_no_cero(ctx, tmp_path, capsys):
    """Archivo inexistente -> mensaje limpio en stderr y código != 0."""
    db_path = str(tmp_path / "cli_err.db")
    os.environ["B2B_DB_PATH"] = db_path
    try:
        assert cli_main(["process", "/no/existe.xml"]) == 1
    finally:
        os.environ.pop("B2B_DB_PATH", None)
    err = capsys.readouterr().err
    assert "Error" in err
