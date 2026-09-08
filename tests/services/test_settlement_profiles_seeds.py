# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/settlement_profiles.py — REQ-CONC-001.

Criterio de aceptación (docs/BLUEPRINT-AGENTES-FISCALES.md, REQ-CONC-001):
debe existir el modelo `SettlementProfile` con los 6 campos exigidos y
semillas para `clip` (0.036-0.043, sin MSI), `banorte_tpv`
(0.015-0.036, configurable por contrato) y `spei_transferencia`/`cheque`
(0.0-0.0); verificable listando los 3 perfiles semilla por nombre exacto.
"""
from decimal import Decimal

import pytest

from b2b_ai.services.settlement_profiles import (
    SettlementProfile,
    SEED_PROFILES,
    CANAL_ALIASES,
    get_settlement_profile,
    list_seed_profiles,
)


class TestSettlementProfileModel:
    def test_has_the_six_required_fields(self):
        p = SettlementProfile(
            nombre="x",
            tasa_comision_min=Decimal("0.01"),
            tasa_comision_max=Decimal("0.02"),
            iva_comision=Decimal("0.16"),
            liquidacion_dias_habiles_min=1,
            liquidacion_dias_habiles_max=2,
            incluye_fin_de_semana_en_lunes=True,
        )
        assert p.tasa_comision_min == Decimal("0.01")
        assert p.tasa_comision_max == Decimal("0.02")
        assert p.iva_comision == Decimal("0.16")
        assert p.liquidacion_dias_habiles_min == 1
        assert p.liquidacion_dias_habiles_max == 2
        assert p.incluye_fin_de_semana_en_lunes is True

    def test_rejects_inverted_commission_band(self):
        with pytest.raises(ValueError):
            SettlementProfile(
                nombre="invalido",
                tasa_comision_min=Decimal("0.05"),
                tasa_comision_max=Decimal("0.01"),
                iva_comision=Decimal("0.16"),
                liquidacion_dias_habiles_min=1,
                liquidacion_dias_habiles_max=1,
                incluye_fin_de_semana_en_lunes=False,
            )

    def test_rejects_inverted_settlement_window(self):
        with pytest.raises(ValueError):
            SettlementProfile(
                nombre="invalido",
                tasa_comision_min=Decimal("0.01"),
                tasa_comision_max=Decimal("0.02"),
                iva_comision=Decimal("0.16"),
                liquidacion_dias_habiles_min=3,
                liquidacion_dias_habiles_max=1,
                incluye_fin_de_semana_en_lunes=False,
            )


class TestSeedProfilesExactlyThree:
    """El criterio exige exactamente 3 perfiles semilla, por nombre exacto."""

    def test_exactly_three_seed_profiles(self):
        profiles = list_seed_profiles()
        assert len(profiles) == 3

    def test_seed_profile_names_are_exact(self):
        names = {p.nombre for p in list_seed_profiles()}
        assert names == {"clip", "banorte_tpv", "spei_transferencia"}

    def test_seed_profiles_dict_keys_match_names(self):
        # Cada entrada del dict de semillas está indexada por su propio
        # nombre exacto (no hay desalineación clave/nombre).
        for key, profile in SEED_PROFILES.items():
            assert key == profile.nombre


class TestClipProfile:
    def test_commission_band(self):
        clip = get_settlement_profile("clip")
        assert clip is not None
        assert clip.tasa_comision_min == Decimal("0.036")
        assert clip.tasa_comision_max == Decimal("0.043")

    def test_sin_msi_documented(self):
        clip = get_settlement_profile("clip")
        assert "MSI" in clip.notas

    def test_settlement_window_t_plus_1(self):
        clip = get_settlement_profile("clip")
        assert clip.liquidacion_dias_habiles_min == 1
        assert clip.liquidacion_dias_habiles_max == 1


class TestBanorteTpvProfile:
    def test_commission_band(self):
        banorte = get_settlement_profile("banorte_tpv")
        assert banorte is not None
        assert banorte.tasa_comision_min == Decimal("0.015")
        assert banorte.tasa_comision_max == Decimal("0.036")

    def test_configurable_por_contrato_documented(self):
        banorte = get_settlement_profile("banorte_tpv")
        assert "contrato" in banorte.notas.lower()


class TestSpeiTransferenciaChequeProfile:
    def test_spei_transferencia_zero_commission(self):
        spei = get_settlement_profile("spei_transferencia")
        assert spei is not None
        assert spei.tasa_comision_min == Decimal("0.0")
        assert spei.tasa_comision_max == Decimal("0.0")

    def test_cheque_resolves_to_same_profile_via_alias(self):
        cheque = get_settlement_profile("cheque")
        spei = get_settlement_profile("spei_transferencia")
        assert cheque is not None
        assert cheque is spei
        assert CANAL_ALIASES["cheque"] == "spei_transferencia"

    def test_cheque_also_zero_commission(self):
        cheque = get_settlement_profile("cheque")
        assert cheque.tasa_comision_min == Decimal("0.0")
        assert cheque.tasa_comision_max == Decimal("0.0")


class TestGetSettlementProfileNeverInvents:
    """Nunca inventar un perfil para un canal no declarado (regla dura del
    blueprint aplicada aquí a nivel de configuración, no de matching)."""

    def test_unknown_channel_returns_none(self):
        assert get_settlement_profile("oxxo_pay") is None
        assert get_settlement_profile("paypal") is None

    def test_empty_or_none_name_returns_none(self):
        assert get_settlement_profile("") is None
        assert get_settlement_profile(None) is None

    def test_lookup_is_case_and_whitespace_tolerant_but_exact_otherwise(self):
        assert get_settlement_profile(" CLIP ") is get_settlement_profile("clip")
        # No matching parcial/difuso: un nombre distinto no cae a "clip".
        assert get_settlement_profile("clipp") is None
