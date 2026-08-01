# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/contabilidad_electronica.py — e-accounting orchestrator."""
import pytest
from b2b_ai.services.contabilidad_electronica import ContabilidadElectronica, ESTADOS
from b2b_ai.services.catalogo_cuentas import CatalogoCuentas


class TestHash:
    def test_sha1(self):
        h = ContabilidadElectronica.calcular_hash_sha1(b"test content")
        assert len(h) == 40
        assert all(c in "0123456789abcdef" for c in h)

    def test_sha1_deterministic(self):
        h1 = ContabilidadElectronica.calcular_hash_sha1(b"hello")
        h2 = ContabilidadElectronica.calcular_hash_sha1(b"hello")
        assert h1 == h2


class TestContabilidadElectronica:
    def setup_method(self):
        self.ce = ContabilidadElectronica(
            rfc="XAXX010101000", ejercicio=2026, mes=7
        )

    def test_initial_state(self):
        assert self.ce.estado == "borrador"

    def test_generate_package(self):
        asientos = [
            {"cuenta": "1101", "debe": "1000.00", "haber": "0.00"},
            {"cuenta": "6102", "debe": "1000.00", "haber": "0.00"},
        ]
        paq = self.ce.generar_paquete(asientos)
        assert paq["estado"] == "listo_para_timbrar"
        assert "catalogo" in paq
        assert "balanza" in paq
        assert len(paq["catalogo"]["sha1"]) == 40

    def test_state_transitions(self):
        self.ce.estado = "borrador"
        self.ce.marcar_listo_para_timbrar()
        assert self.ce.estado == "listo_para_timbrar"

        self.ce.marcar_timbrado()
        assert self.ce.estado == "timbrado"

        self.ce.marcar_enviado()
        assert self.ce.estado == "enviado"

    def test_invalid_transition(self):
        self.ce.estado = "borrador"
        with pytest.raises(ValueError, match="No se puede timbrar"):
            self.ce.marcar_timbrado()

    def test_invalid_state(self):
        with pytest.raises(ValueError, match="Estado inválido"):
            self.ce._avanzar_estado("invalido")

    def test_resumen_mensual(self):
        asientos = [
            {"cuenta": "1101", "debe": "1000.00", "haber": "0.00"},
            {"cuenta": "6102", "debe": "1000.00", "haber": "0.00"},
        ]
        self.ce.generar_paquete(asientos)
        res = self.ce.generar_resumen_mensual()
        assert res["periodo"] == "2026-07"
        assert res["rfc"] == "XAXX010101000"

    def test_resumen_no_paquete_no_asientos(self):
        with pytest.raises(ValueError):
            self.ce.generar_resumen_mensual()

    def test_obtener_paquete(self):
        assert self.ce.obtener_paquete() is None

    def test_estados_tuple(self):
        assert len(ESTADOS) == 4
        assert "borrador" in ESTADOS
        assert "enviado" in ESTADOS
