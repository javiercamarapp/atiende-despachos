# -*- coding: utf-8 -*-
"""
Boost coverage for b2b_ai/services/classify.py.

Targets uncovered lines:
  - main() function (lines 108-117, 121)
"""
from __future__ import annotations

import json
import os
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from b2b_ai.services.classify import classify_cfdi, main as classify_main


@pytest.fixture
def parsed_cfdi(sample_consultoria):
    from b2b_ai.cfdi.parser import parse_cfdi
    return parse_cfdi(sample_consultoria)


class TestClassifyMain:
    def test_main_prints_json(self, fixture_dir):
        """Exercise classify main() (lines 108-117)."""
        xml_path = os.path.join(fixture_dir, "01_gasto_operativo_papeleria.xml")
        with patch("sys.argv", ["classify", xml_path]):
            captured = StringIO()
            sys.stdout = captured
            try:
                classify_main()
            finally:
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            assert output.strip()
            data = json.loads(output)
            assert "categoria" in data
            assert "confianza" in data

    def test_main_no_args_exits(self):
        """classify_main() with no args should sys.exit(1) (line 114-115)."""
        with patch("sys.argv", ["classify"]):
            with pytest.raises(SystemExit) as exc_info:
                classify_main()
            assert exc_info.value.code == 1


class TestClassifyCfdi:
    def test_gasto_operativo(self):
        datos = {
            "conceptos": [{"descripcion": "Papeleria y consumibles de oficina"}],
            "claves_prod_serv": [],
        }
        result = classify_cfdi(datos)
        assert result["categoria"] == "gasto_operativo"

    def test_inversion(self):
        datos = {
            "conceptos": [{"descripcion": "Consultoria de desarrollo de software"}],
            "claves_prod_serv": [],
        }
        result = classify_cfdi(datos)
        assert result["categoria"] == "inversion"

    def test_activo_fijo(self):
        datos = {
            "conceptos": [{"descripcion": "Computadora laptop Dell"}],
            "claves_prod_serv": [],
        }
        result = classify_cfdi(datos)
        assert result["categoria"] == "activo_fijo"

    def test_nomina_by_tipo(self):
        datos = {
            "tipo": "N",
            "conceptos": [{"descripcion": "Sueldo quincenal"}],
            "claves_prod_serv": [],
        }
        result = classify_cfdi(datos)
        assert result["categoria"] == "nomina"

    def test_desconocido_when_no_match(self):
        datos = {
            "conceptos": [{"descripcion": "xyzzy"}],
            "claves_prod_serv": [],
        }
        result = classify_cfdi(datos)
        assert result["categoria"] == "desconocido"
        assert result["requires_human_review"] is True

    def test_confianza_clamped(self):
        """Confianza should be between 0 and 0.98."""
        datos = {
            "conceptos": [{"descripcion": "renta internet telefonia limpieza mantenimiento"}],
            "claves_prod_serv": [],
        }
        result = classify_cfdi(datos)
        assert 0 <= result["confianza"] <= 0.98

    def test_empty_conceptos(self):
        datos = {"conceptos": [], "claves_prod_serv": []}
        result = classify_cfdi(datos)
        assert result["categoria"] == "desconocido"

    def test_with_clave_prod_serv(self):
        datos = {
            "conceptos": [],
            "claves_prod_serv": ["43232300"],  # software
        }
        result = classify_cfdi(datos)
        # Should match something via catalogs
        assert "categoria" in result
