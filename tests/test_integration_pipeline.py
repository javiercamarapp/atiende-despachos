# -*- coding: utf-8 -*-
"""
Test de integración: el pipeline completo corre con tool calling y deja
evidencia en DB (facturas + audit_log de cada tool invocada).
"""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.services.pipeline import process_file, process_batch, summarize
from b2b_ai.tools.logger import logger as global_logger


@pytest.fixture
def db_and_logger(tmp_path):
    db = Database(str(tmp_path / "integ.db"))
    global_logger.set_db(db)
    return db


def test_pipeline_completo_una_factura(db_and_logger, sample_consultoria):
    db = db_and_logger
    res = process_file(sample_consultoria, db=db)
    assert res["validacion"]["ok"] is True
    assert res["clasificacion"]["categoria"] == "inversion"
    assert res["erp"]["ok"] is True
    assert res["insertado"] is True
    assert res["invoice_id"] is not None
    # Evidencia en DB
    assert db.count_invoices() == 1
    inv = db.get_invoice(res["invoice_id"])
    assert inv["folio_fiscal"]
    assert inv["categoria"] == "inversion"
    assert inv["erp_poliza"]


def test_pipeline_registra_audit_de_cada_tool(db_and_logger, sample_consultoria):
    db = db_and_logger
    process_file(sample_consultoria, db=db)
    tools_invocadas = set(r["tool_name"] for r in db.list_audit())
    required = {"parse_cfdi", "validate_cfdi", "classify_expense", "register_erp"}
    assert required <= tools_invocadas


def test_pipeline_multi_tenant_aisla(db_and_logger, sample_consultoria,
                                     sample_nomina):
    db = db_and_logger
    tid_a = db.create_tenant("Alpha")
    tid_b = db.create_tenant("Beta")
    process_file(sample_consultoria, db=db, tenant_id=tid_a)
    process_file(sample_nomina, db=db, tenant_id=tid_b)
    assert db.count_invoices(tenant_id=tid_a) == 1
    assert db.count_invoices(tenant_id=tid_b) == 1
    # Cada tenant solo ve sus facturas
    assert len(db.list_invoices(tenant_id=tid_a)) == 1


def test_pipeline_batch_completo(db_and_logger, fixture_dir):
    db = db_and_logger
    results = process_batch(fixture_dir, db=db)
    s = summarize(results)
    assert s["procesadas"] == 7
    assert s["validas"] >= 5
    assert s["insertadas"] == 7
    # Categorías detectadas
    assert set(s["por_categoria"].keys()) >= {"inversion", "nomina",
                                              "gasto_operativo", "activo_fijo"}
    # Cada factura generó audit + registro en DB
    assert db.count_invoices() == 7
    assert db.count_audit("parse_cfdi") >= 7


def test_pipeline_duplicado_no_reinserta(db_and_logger, sample_consultoria):
    db = db_and_logger
    r1 = process_file(sample_consultoria, db=db)
    r2 = process_file(sample_consultoria, db=db)
    assert r1["insertado"] is True
    assert r2["insertado"] is False
    assert db.count_invoices() == 1


def test_pipeline_nomina_marca_revision_humana(db_and_logger, sample_nomina):
    db = db_and_logger
    res = process_file(sample_nomina, db=db)
    # Nómina siempre requiere revisión humana (flag de diseño)
    assert res["validacion"]["requires_human_review"] is True
    inv = db.get_invoice(res["invoice_id"])
    assert inv["requires_human_review"] == 1
