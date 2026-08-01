# -*- coding: utf-8 -*-
"""Tests del router y del logger de tools."""
import pytest

import b2b_ai.tools.tools  # noqa: F401
from b2b_ai.tools.router import route, dispatch, list_routes
from b2b_ai.tools.logger import ToolCallLogger


def test_route_parse():
    assert route("necesito leer y extraer datos del cfdi") == "parse_cfdi"


def test_route_validate():
    assert route("validar fiscalmente esta factura") == "validate_cfdi"


def test_route_precedencia_verbo_sobre_cfdi():
    # "cfdi"/"xml" son genéricos; el verbo de acción debe ganar
    assert route("validar fiscalmente este cfdi") == "validate_cfdi"
    assert route("leer y extraer datos del cfdi xml") == "parse_cfdi"


def test_route_classify():
    assert route("clasificar el gasto en cuenta contable") == "classify_expense"


def test_route_erp():
    assert route("registrar la poliza en el erp contpaqi") == "register_erp"


def test_route_notify():
    assert route("enviar una notificacion por email") == "send_notification"


def test_route_reconcile():
    assert route("conciliar los movimientos bancarios") == "reconcile_bank"


def test_route_report():
    assert route("generar el reporte mensual de metricas") == "generate_report"


def test_route_desconocido():
    assert route("hola como estas") is None


def test_dispatch_ok(sample_consultoria):
    res = dispatch("leer y extraer el cfdi", xml_path=sample_consultoria)
    assert res["status"] == "ok"
    assert res["tool"] == "parse_cfdi"
    assert res["result"]["folio_fiscal"]


def test_dispatch_no_route():
    res = dispatch("texto sin intencion de tool")
    assert res["status"] == "no_route"


def test_logger_registra_llamadas(tmp_db):
    lg = ToolCallLogger(db=tmp_db)
    lg.log("parse_cfdi", "dispatch", entity="intent", entity_id="x",
           payload={"ok": 1}, status="ok", tenant_id=1)
    rows = tmp_db.list_audit()
    assert rows
    assert rows[0]["tool_name"] == "parse_cfdi"
    assert tmp_db.count_audit("parse_cfdi") == 1


def test_dispatch_registra_en_logger(tmp_db, sample_consultoria):
    from b2b_ai.tools.logger import logger as global_logger
    global_logger.set_db(tmp_db)
    dispatch("leer el xml del cfdi", xml_path=sample_consultoria, tenant_id=1)
    assert global_logger.count("parse_cfdi") >= 1


def test_list_routes():
    routes = list_routes()
    assert any(r["tool"] == "reconcile_bank" for r in routes)
