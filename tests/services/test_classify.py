# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/classify.py — keyword classification logic."""
import pytest
from b2b_ai.services.classify import (
    classify_cfdi, KEYWORDS, PRIORITY, CATEGORIA_NOMBRE,
)


class TestClassifyKeywords:
    """Keyword matching and score calculation."""

    def test_nomina_detected_by_tipo_n(self):
        datos = {"conceptos": [{"descripcion": "Pago"}], "tipo": "N",
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "nomina"
        assert r["confianza"] > 0.7

    def test_activo_fijo_by_keyword(self):
        datos = {"conceptos": [{"descripcion": "Laptop Dell para oficina"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "activo_fijo"

    def test_gasto_operativo_by_keyword(self):
        datos = {"conceptos": [{"descripcion": "Papeleria y consumibles de oficina"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "gasto_operativo"

    def test_inversion_by_keyword(self):
        datos = {"conceptos": [{"descripcion": "Desarrollo de software a medida"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "inversion"

    def test_empty_concepts_returns_desconocido(self):
        datos = {"conceptos": [], "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "desconocido"
        assert r["requires_human_review"] is True
        assert r["confianza"] == 0.0

    def test_no_matching_keywords_desconocido(self):
        datos = {"conceptos": [{"descripcion": "XYZABC123"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "desconocido"

    def test_multiple_keywords_increasing_confidence(self):
        datos = {"conceptos": [{"descripcion": "Laptop computadora monitor CPU"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "activo_fijo"
        assert r["confianza"] >= 0.75

    def test_no_concepts_field(self):
        datos = {"claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "desconocido"

    def test_no_concepts_field_at_all(self):
        datos = {"claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "desconocido"

    def test_clave_prod_serv_matching(self):
        """ClaveProdServ prefix 432115 maps to activo_fijo."""
        datos = {"conceptos": [{"descripcion": "Equipo"}],
                 "claves_prod_serv": ["43211500"]}
        r = classify_cfdi(datos)
        assert r["categoria"] == "activo_fijo"

    def test_case_insensitive_keyword_matching(self):
        datos = {"conceptos": [{"descripcion": "LAPTOP para oficina"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["categoria"] == "activo_fijo"

    def test_priority_order_when_tied(self):
        """nomina should win when scores are tied (first in PRIORITY)."""
        datos = {"conceptos": [{"descripcion": ""}],
                 "claves_prod_serv": [], "tipo": "N"}
        r = classify_cfdi(datos)
        assert r["categoria"] == "nomina"

    def test_low_confidence_triggers_human_review(self):
        """Ambiguous input should trigger human review."""
        datos = {"conceptos": [{"descripcion": "something random"}],
                 "claves_prod_serv": []}
        r = classify_cfdi(datos)
        assert r["requires_human_review"] is True  # desconocido always requires review

    def test_high_confidence_no_human_review(self):
        """Many keyword matches should result in high confidence, no review."""
        datos = {"conceptos": [
            {"descripcion": "computadora laptop servidor impresora monitor"}
        ], "claves_prod_serv": ["43211500", "43211800"]}
        r = classify_cfdi(datos)
        assert r["confianza"] >= 0.90
        assert r["requires_human_review"] is False

    def test_categoria_nombre_mapping_complete(self):
        for cat in ["gasto_operativo", "inversion", "activo_fijo",
                     "nomina", "desconocido"]:
            assert cat in CATEGORIA_NOMBRE

    def test_priority_list_covers_all_categories(self):
        for cat in KEYWORDS:
            assert cat in PRIORITY or cat == "desconocido"
