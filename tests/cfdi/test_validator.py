# -*- coding: utf-8 -*-
"""Tests for b2b_ai/cfdi/validator.py — CFDI validation."""
import pytest
from b2b_ai.cfdi.validator import validate_cfdi, ValidationResult


class TestValidateCFDI:
    def test_valid_invoice(self):
        datos = {
            "subtotal": "1000.00", "total": "1160.00", "iva": "160.00",
            "descuento": "0.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "uso_cfdi": "G03", "forma_pago": "03", "metodo_pago": "PUE",
            "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "fecha_timbrado": "2026-07-03T10:01:00",
            "conceptos": [{"cantidad": "1", "valor_unitario": "1000.00",
                           "importe": "1000.00", "traslados": []}],
        }
        r = validate_cfdi(datos)
        assert r["ok"] is True
        assert r["checks"]["fail"] == 0

    def test_concepto_arithmetic_wrong(self):
        datos = {
            "subtotal": "1000.00", "total": "1160.00", "iva": "160.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "uso_cfdi": "G03", "forma_pago": "03", "metodo_pago": "PUE",
            "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "fecha_timbrado": "2026-07-03T10:01:00",
            "conceptos": [{"cantidad": "2", "valor_unitario": "1000.00",
                           "importe": "1000.00", "traslados": []}],
        }
        r = validate_cfdi(datos)
        assert any(i["code"] == "importe_concepto_incoherente" for i in r["issues"])

    def test_total_incoherente(self):
        datos = {
            "subtotal": "1000.00", "total": "5000.00", "iva": "160.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "conceptos": [{"cantidad": "1", "valor_unitario": "1000.00",
                           "importe": "1000.00", "traslados": []}],
        }
        r = validate_cfdi(datos)
        assert any(i["code"] == "total_incoherente" for i in r["issues"])

    def test_rfc_emisor_invalido(self):
        datos = {
            "subtotal": "1000.00", "total": "1160.00", "iva": "160.00",
            "emisor_rfc": "INVALID", "receptor_rfc": "XAXX010101000",
            "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "conceptos": [],
        }
        r = validate_cfdi(datos)
        assert any(i["code"] == "rfc_emisor_invalido" for i in r["issues"])

    def test_uso_cfdi_invalido(self):
        datos = {
            "subtotal": "1000.00", "total": "1160.00", "iva": "160.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "uso_cfdi": "ZZ", "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "conceptos": [],
        }
        r = validate_cfdi(datos)
        assert any(i["code"] == "uso_cfdi_invalido" for i in r["issues"])

    def test_nomina_requires_human(self):
        datos = {
            "subtotal": "25000.00", "total": "25000.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "tipo": "N", "metodo_pago": "PUE",
            "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "nomina": {"total_percepciones": "25000.00"},
            "conceptos": [],
        }
        r = validate_cfdi(datos)
        assert r["requires_human_review"] is True

    def test_returns_validation_result(self):
        datos = {"conceptos": []}
        r = validate_cfdi(datos)
        assert isinstance(r, ValidationResult)

    def test_diot_reportable(self):
        datos = {
            "subtotal": "1000.00", "total": "1160.00", "iva": "160.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "2026-07-03T10:00:00",
            "conceptos": [],
        }
        r = validate_cfdi(datos)
        assert r["diot"]["reportable"] is True
        assert len(r["diot"]["proveedores_reportables"]) == 1

    def test_fecha_invalida(self):
        datos = {
            "subtotal": "1000.00", "total": "1160.00",
            "emisor_rfc": "PAP850101JKL", "receptor_rfc": "XAXX010101000",
            "tipo": "I", "emisor": {"regimen_fiscal": "601"},
            "fecha": "not-a-date",
            "conceptos": [],
        }
        r = validate_cfdi(datos)
        assert any(i["code"] == "fecha_invalida" for i in r["issues"])

    def test_validation_result_getattr(self):
        r = ValidationResult({"ok": True, "issues": []})
        assert r.ok is True
        with pytest.raises(AttributeError):
            _ = r.nonexistent
