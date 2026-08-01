# -*- coding: utf-8 -*-
"""Tests for b2b_ai/cfdi/cancellation.py — CFDI cancellation evaluation."""
import pytest
from decimal import Decimal
from b2b_ai.cfdi.cancellation import (
    evaluate_cancellation, prepare_cancellation_request, UMBRAL_ACEPTACION,
)


class TestEvaluateCancellation:
    def test_tipo_i_below_threshold(self):
        datos = {"tipo": "I", "total": "100.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "cancelacion_directa"
        assert r["requiere_aceptacion_receptor"] is False

    def test_tipo_i_above_threshold(self):
        datos = {"tipo": "I", "total": "1000.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "requiere_aceptacion_receptor"
        assert r["requiere_aceptacion_receptor"] is True

    def test_tipo_i_no_total(self):
        datos = {"tipo": "I", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "requiere_revision"

    def test_tipo_e(self):
        datos = {"tipo": "E", "total": "100.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "no_cancelar_usar_egreso"

    def test_tipo_n(self):
        datos = {"tipo": "N", "total": "100.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "revisar_especial"

    def test_tipo_p(self):
        datos = {"tipo": "P", "total": "100.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "no_cancelar_complemento"

    def test_no_tipo(self):
        datos = {"total": "100.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["decision"] == "no_aplica"

    def test_relacionados_warning(self):
        datos = {"tipo": "I", "total": "100.00", "folio_fiscal": "UUID1",
                 "cfdi_relacionados": ["UUID2"]}
        r = evaluate_cancellation(datos)
        assert any("relacionado" in s.lower() for s in r["sugerencias"])

    def test_always_requires_human(self):
        datos = {"tipo": "I", "total": "10.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert r["requires_human_review"] is True

    def test_ref_legal_present(self):
        datos = {"tipo": "I", "total": "10.00", "folio_fiscal": "UUID1"}
        r = evaluate_cancellation(datos)
        assert "CFF" in r["ref_legal"]


class TestPrepareCancellationRequest:
    def test_basic(self):
        datos = {"tipo": "I", "total": "100.00", "folio_fiscal": "UUID1",
                 "emisor_rfc": "RFC1"}
        payload, errores = prepare_cancellation_request(
            datos, motivo="Error", confirmacion_humana=True)
        assert payload["dry_run"] is True
        assert payload["uuid"] == "UUID1"
        assert len(errores) == 0

    def test_no_confirmation(self):
        datos = {"tipo": "I", "total": "100.00", "folio_fiscal": "UUID1"}
        payload, errores = prepare_cancellation_request(
            datos, confirmacion_humana=False)
        assert len(errores) > 0
        assert any("confirmación" in e.lower() for e in errores)

    def test_no_folio(self):
        datos = {"tipo": "I", "total": "100.00"}
        payload, errores = prepare_cancellation_request(
            datos, confirmacion_humana=True)
        assert any("folio fiscal" in e.lower() for e in errores)
