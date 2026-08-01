# -*- coding: utf-8 -*-
"""Tests del framework de tool calling: registry, router y tools."""
import pytest

# Importar para registrar las tools
import b2b_ai.tools.tools  # noqa: F401
from b2b_ai.tools.registry import (tool, get_tool, all_tools, call_tool,
                                   ToolDefinition)


def test_todas_las_tools_registradas():
    names = {t.name for t in all_tools()}
    required = {"parse_cfdi", "validate_cfdi", "classify_expense", "register_erp",
                "send_notification", "reconcile_bank", "generate_report"}
    assert required <= names


def test_tool_definition_metadata():
    t = get_tool("parse_cfdi")
    assert isinstance(t, ToolDefinition)
    assert t.parameters[0]["name"] == "xml_path"
    assert t.parameters[0]["required"] is True


def test_call_tool_parse(sample_consultoria):
    d = call_tool("parse_cfdi", xml_path=sample_consultoria)
    assert d["folio_fiscal"]
    assert d["total"] == "5800.00" or str(d["total"]) == "5800.00"


def test_call_tool_validate(sample_consultoria):
    d = call_tool("parse_cfdi", xml_path=sample_consultoria)
    v = call_tool("validate_cfdi", datos=d)
    assert v["ok"] is True


def test_call_tool_classify(sample_consultoria):
    d = call_tool("parse_cfdi", xml_path=sample_consultoria)
    c = call_tool("classify_expense", datos=d)
    assert c["categoria"] in ("inversion", "gasto_operativo")


def test_call_tool_register_erp(sample_consultoria):
    from b2b_ai.erp.contpaqi import MockCONTPAQi
    d = call_tool("parse_cfdi", xml_path=sample_consultoria)
    r = call_tool("register_erp", invoice=d, erp=MockCONTPAQi())
    assert r["ok"] is True
    assert r["poliza"]


def test_call_tool_send_notification():
    r = call_tool("send_notification",
                  event_type="invoice_processed",
                  to="a@b.com",
                  context={"nombre": "X", "folio": "F1", "emisor": "EM",
                           "monto": "100", "categoria": "gasto",
                           "razon": "r", "uuid": "u", "revision": ""})
    assert r["status"] in ("simulado", "sent")


def test_call_tool_inexistente():
    with pytest.raises(KeyError):
        call_tool("no_existe")


def test_decorator_registro_manual():
    @tool(name="tool_prueba", description="prueba")
    def fn(a, b=1):
        return a + b
    assert get_tool("tool_prueba").fn(1, b=2) == 3
    # limpieza para no contaminar otros tests
    from b2b_ai.tools import registry
    registry._TOOLS.pop("tool_prueba", None)
