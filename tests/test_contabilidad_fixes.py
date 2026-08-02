# -*- coding: utf-8 -*-
"""
test_contabilidad_fixes.py — Regression tests para los 4 bugs P1 del módulo
Contabilidad Electrónica (QA 187).

Cubre:
  P1-7  XML con RFC emisor vacío: el endpoint valida que el RFC sea obligatorio.
  P1-8  El catálogo usa NumCta (XSD SAT), no CodAgrup.
  P1-9  FechaCreacion se llena con datetime (nunca queda vacía).
  P1-10 Validación de RFC y régimen fiscal contra catálogos del SAT.
"""
from __future__ import annotations

import re

import pytest

from b2b_ai.features.contabilidad_electronica.models import (
    BalanzaRequest,
    BalanzaRow,
    CatalogoCuenta,
    TipoCuenta,
)
from b2b_ai.features.contabilidad_electronica.generator import (
    generate_balanza_xml,
    generate_catalogo_xml,
)
from b2b_ai.features.contabilidad_electronica.validators import (
    validate_rfc,
    validate_regimen_fiscal,
    validate_balanza,
)


# ---------------------------------------------------------------------------
# P1-7: RFC obligatorio en el XML (XSD SAT)
# ---------------------------------------------------------------------------
class TestP1_7RFCObligatorio:
    def test_balanza_incluye_rfc(self):
        req = BalanzaRequest(
            periodo="2025-01", ejercicio=2025, mes=1, rfc="ABC850101T1A",
            rows=[BalanzaRow(codigo_cuenta="1001")],
        )
        xml = generate_balanza_xml(req, rfc="ABC850101T1A")
        assert 'RFC="ABC850101T1A"' in xml

    def test_balanza_rfc_vacio_es_error_de_validacion(self):
        """validate_balanza rechaza un RFC vacío (obligatorio en el XSD)."""
        req = BalanzaRequest(
            periodo="2025-01", ejercicio=2025, mes=1, rfc="",
            rows=[BalanzaRow(codigo_cuenta="1001", debe=1, haber=1)],
        )
        errors = validate_balanza(req)
        assert any("RFC" in e for e in errors)

    def test_validate_rfc_vacio(self):
        assert validate_rfc("") != []
        assert validate_rfc(None) != []


# ---------------------------------------------------------------------------
# P1-8: Catálogo usa NumCta, no CodAgrup
# ---------------------------------------------------------------------------
class TestP1_8NumCta:
    def test_catalogo_usa_numcta(self):
        cuentas = [CatalogoCuenta(
            codigo="101.01.01", descripcion="Caja", tipo=TipoCuenta.ACTIVO, nivel=3,
        )]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert 'NumCta="101.01.01"' in xml

    def test_catalogo_no_usa_codagrup(self):
        cuentas = [CatalogoCuenta(
            codigo="101.01.01", descripcion="Caja", tipo=TipoCuenta.ACTIVO, nivel=3,
        )]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        assert "CodAgrup" not in xml


# ---------------------------------------------------------------------------
# P1-9: FechaCreacion nunca vacía
# ---------------------------------------------------------------------------
class TestP1_9FechaCreacion:
    _FECHA_PATTERN = re.compile(r'FechaCreacion="([^"]+)"')

    def test_balanza_fecha_creacion_poblada(self):
        req = BalanzaRequest(
            periodo="2025-01", ejercicio=2025, mes=1, rfc="ABC850101T1A",
            rows=[BalanzaRow(codigo_cuenta="1001")],
        )
        xml = generate_balanza_xml(req, rfc="ABC850101T1A")
        m = self._FECHA_PATTERN.search(xml)
        assert m is not None
        assert m.group(1) != ""
        # Formato ISO 8601 básico: AAAA-MM-DDThh:mm:ss
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", m.group(1))

    def test_catalogo_fecha_creacion_poblada(self):
        cuentas = [CatalogoCuenta(codigo="1001", descripcion="Caja",
                                  tipo=TipoCuenta.ACTIVO)]
        xml = generate_catalogo_xml(cuentas, ejercicio=2025)
        m = self._FECHA_PATTERN.search(xml)
        assert m is not None
        assert m.group(1) != ""


# ---------------------------------------------------------------------------
# P1-10: Validación contra catálogos del SAT (RFC y régimen fiscal)
# ---------------------------------------------------------------------------
class TestP1_10ValidacionSAT:
    def test_rfc_valido(self):
        assert validate_rfc("ABC850101T1A") == []

    def test_rfc_formato_invalido(self):
        assert validate_rfc("ABC") != []
        assert validate_rfc("123") != []

    def test_regimen_fiscal_valido(self):
        assert validate_regimen_fiscal("601") == []
        assert validate_regimen_fiscal("612") == []

    def test_regimen_fiscal_invalido(self):
        assert validate_regimen_fiscal("999") != []

    def test_validate_balanza_rfc_invalido(self):
        req = BalanzaRequest(
            periodo="2025-01", ejercicio=2025, mes=1, rfc="INVALIDO",
            rows=[BalanzaRow(codigo_cuenta="1001", debe=1, haber=1)],
        )
        errors = validate_balanza(req)
        assert any("RFC" in e for e in errors)
