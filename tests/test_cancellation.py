# -*- coding: utf-8 -*-
"""Tests de evaluación/preparación de cancelación de CFDI."""
import pytest

from b2b_ai.cfdi.cancellation import evaluate_cancellation, prepare_cancellation_request


def _factura(tipo="I", total="5800.00", uuid="x", metodo="PUE"):
    return {"tipo": tipo, "total": total, "folio_fiscal": uuid,
            "emisor_rfc": "CON950820K12", "metodo_pago": metodo,
            "cfdi_relacionados": []}


def test_cancelacion_monto_alto_requiere_aceptacion():
    r = evaluate_cancellation(_factura(total="100000.00"))
    assert r["decision"] == "requiere_aceptacion_receptor"
    assert r["requiere_aceptacion_receptor"] is True
    assert r["requires_human_review"] is True


def test_cancelacion_monto_bajo_directa():
    r = evaluate_cancellation(_factura(total="300.00"))
    assert r["decision"] == "cancelacion_directa"
    assert r["requiere_aceptacion_receptor"] is False


def test_cancelacion_egreso_no_cancela():
    r = evaluate_cancellation(_factura(tipo="E"))
    assert r["decision"] == "no_cancelar_usar_egreso"


def test_cancelacion_nomina_revision_especial():
    r = evaluate_cancellation(_factura(tipo="N", metodo="PUE"))
    assert r["decision"] == "revisar_especial"


def test_prepare_requiere_confirmacion_humana():
    payload, errores = prepare_cancellation_request(_factura(total="100000.00"))
    assert errores, "debe exigir confirmación humana"
    assert payload["dry_run"] is True
    assert payload["estado"] == "preparado_para_revision_humana"


def test_prepare_con_confirmacion():
    payload, errores = prepare_cancellation_request(
        _factura(total="300.00"), confirmacion_humana=True)
    assert errores == []
    assert payload["uuid"] == "x"
