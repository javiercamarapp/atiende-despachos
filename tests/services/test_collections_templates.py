# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/collections_templates.py — template rendering."""
import pytest
from b2b_ai.services.collections_templates import (
    render, render_subject, format_monto, TEMPLATES,
    SEQUENCE, STAGE_OFFSET_DAYS, stages,
)


class TestFormatMonto:
    def test_basic(self):
        assert format_monto(12500) == "$12,500.00 MXN"

    def test_string_number(self):
        assert format_monto("5000.5") == "$5,000.50 MXN"

    def test_none(self):
        r = format_monto(None)
        assert "None" in r

    def test_invalid(self):
        r = format_monto("abc")
        assert "abc" in r


class TestRender:
    def test_email_body(self):
        body = render("pre_vencimiento", "email",
                       nombre_empresa="ACME", monto="$1000",
                       dias_vencido="0", factura_id="F1")
        assert "ACME" in body
        assert "$1000" in body

    def test_whatsapp(self):
        text = render("pre_vencimiento", "whatsapp",
                       nombre_empresa="ACME", monto="$1000",
                       dias_vencido="0", factura_id="F1")
        assert "ACME" in text

    def test_unknown_stage_raises(self):
        with pytest.raises(KeyError, match="Etapa de cobranza desconocida"):
            render("unknown_stage", "email")

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="Canal desconocido"):
            render("pre_vencimiento", "sms")

    def test_all_stages_renderable(self):
        for stage in SEQUENCE:
            body = render(stage, "email", nombre_empresa="X", monto="$1",
                          dias_vencido="0", factura_id="F1")
            assert len(body) > 0

    def test_missing_variables_default_to_empty(self):
        body = render("pre_vencimiento", "email")
        assert isinstance(body, str)


class TestRenderSubject:
    def test_basic(self):
        s = render_subject("pre_vencimiento", factura_id="F123")
        assert "F123" in s

    def test_unknown_stage_raises(self):
        with pytest.raises(KeyError):
            render_subject("no_such_stage")


class TestSequenceAndOffsets:
    def test_sequence_length(self):
        assert len(SEQUENCE) == 5

    def test_offsets_match_sequence(self):
        for stage in SEQUENCE:
            assert stage in STAGE_OFFSET_DAYS

    def test_pre_vencimiento_is_negative(self):
        assert STAGE_OFFSET_DAYS["pre_vencimiento"] < 0

    def test_escalamiento_is_positive(self):
        assert STAGE_OFFSET_DAYS["escalamiento"] > 0

    def test_stages_function(self):
        assert stages() == list(SEQUENCE)


class TestAllTemplates:
    def test_all_have_email_and_whatsapp(self):
        for stage, tpl in TEMPLATES.items():
            assert "email" in tpl
            assert "whatsapp" in tpl
            assert "subject" in tpl["email"]
            assert "body" in tpl["email"]
