# -*- coding: utf-8 -*-
"""
Test de integración FASE 2: el pipeline incorpora detección de anomalías,
gate de aprobación y solo registra en ERP cuando la decisión lo permite.
"""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.services.pipeline import process_file, _tool
from b2b_ai.tools.logger import logger as global_logger
from b2b_ai.tools.registry import get_tool


@pytest.fixture
def db_and_logger(tmp_path):
    db = Database(str(tmp_path / "integ_fase2.db"))
    global_logger.set_db(db)
    return db


def test_pipeline_correr_incluye_anomalias_y_aprobacion(db_and_logger,
                                                        sample_consultoria):
    db = db_and_logger
    res = process_file(sample_consultoria, db=db)
    # La consultoría ($5,800) está bajo el umbral -> auto-aprobada y registrada
    assert "anomalias" in res
    assert "aprobacion" in res
    assert res["aprobacion"]["decision"] == "auto_approved"
    assert res["anomalias"]["summary"]["total"] >= 1  # proveedor nuevo
    assert res["erp"]["ok"] is True


def test_pipeline_registra_audit_de_nuevas_tools(db_and_logger,
                                                 sample_consultoria):
    db = db_and_logger
    process_file(sample_consultoria, db=db)
    tools_invocadas = set(r["tool_name"] for r in db.list_audit())
    assert {"detect_anomalies", "evaluate_approval"} <= tools_invocadas
    assert "register_erp" in tools_invocadas


def test_factura_sobre_umbral_bloquea_erp(db_and_logger):
    """Una factura de $120k requiere aprobación y NO registra en ERP."""
    db = db_and_logger
    invoice = {
        "folio_fiscal": "FAC-ALTA-1", "archivo": "alta.xml",
        "fecha": "2026-07-10", "tipo": "I",
        "emisor_rfc": "EMI990101A01", "emisor_nombre": "Emisor SA",
        "subtotal": "120000.00", "iva": "19200.00", "total": "139200.00",
        "moneda": "MXN", "descripcion": "Servicio alto valor",
        "conceptos": [{"descripcion": "Servicio profesional"}],
    }
    tid = db.create_tenant("Alta")
    # Invocar el pipeline de tools sobre la factura directamente
    res = _tool("evaluate_approval", global_logger, tid, invoice=invoice)
    assert res["decision"] == "requires_approval"
    assert res["requires_efirma"] is True


def test_tools_fase2_registradas():
    assert get_tool("detect_anomalies") is not None
    assert get_tool("evaluate_approval") is not None


def test_router_enruta_anomalia_y_aprobacion():
    from b2b_ai.tools.router import route
    assert route("detecta anomalías en esta factura") == "detect_anomalies"
    assert route("la factura requiere aprobación") == "evaluate_approval"
