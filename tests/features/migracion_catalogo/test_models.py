# -*- coding: utf-8 -*-
"""
test_models.py — REQ-MIG-002.

`MapeoMigracionCuenta` debe existir en
`b2b_ai/features/migracion_catalogo/models.py` con los 9 campos:
id, origen_cuenta_id, destino_cuenta_id, tipo_match, score, estado,
aprobado_por, aprobado_en, nota.

Sin mocks: se instancia el modelo real (pydantic v2) y se validan sus
constraints reales (enums, rango de score, opcionalidad de campos que no
deben "inventarse" mientras el mapeo sigue pendiente — REQ-MIG-006).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)

ORIGEN_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
DESTINO_ID = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"


def _base_kwargs(**overrides) -> dict:
    base = dict(
        origen_cuenta_id=ORIGEN_ID,
        destino_cuenta_id=DESTINO_ID,
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=EstadoMapeoMigracion.APROBADO,
        aprobado_por="contador_lider",
        aprobado_en="2026-09-08T12:00:00",
        nota="código y nombre normalizados idénticos",
    )
    base.update(overrides)
    return base


class TestEsquemaCompleto:
    """El modelo se puede instanciar con sus 9 campos."""

    def test_instancia_con_los_9_campos(self):
        mapeo = MapeoMigracionCuenta(**_base_kwargs())

        # Los 9 campos del criterio de aceptación.
        assert mapeo.id  # generado por default_factory, no vacío
        assert mapeo.origen_cuenta_id == ORIGEN_ID
        assert mapeo.destino_cuenta_id == DESTINO_ID
        assert mapeo.tipo_match == TipoMatchMigracion.EXACTO
        assert mapeo.score == 100.0
        assert mapeo.estado == EstadoMapeoMigracion.APROBADO
        assert mapeo.aprobado_por == "contador_lider"
        assert mapeo.aprobado_en == "2026-09-08T12:00:00"
        assert mapeo.nota == "código y nombre normalizados idénticos"

    def test_id_es_unico_por_instancia(self):
        m1 = MapeoMigracionCuenta(**_base_kwargs())
        m2 = MapeoMigracionCuenta(**_base_kwargs())
        assert m1.id != m2.id


class TestValoresPorDefecto:
    """Campos opcionales tienen defaults seguros: nada de mapeo aprobado
    ni destino inventado por accidente."""

    def test_defaults_minimos_quedan_pendientes_sin_destino(self):
        mapeo = MapeoMigracionCuenta(
            origen_cuenta_id=ORIGEN_ID,
            tipo_match=TipoMatchMigracion.SIN_MATCH,
        )
        assert mapeo.destino_cuenta_id is None
        assert mapeo.score == 0.0
        assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
        assert mapeo.aprobado_por is None
        assert mapeo.aprobado_en is None
        assert mapeo.nota is None


class TestEnums:
    """`tipo_match` y `estado` solo aceptan los valores del catálogo."""

    @pytest.mark.parametrize(
        "valor",
        ["exacto", "alerta_riesgo", "fuzzy", "sin_match"],
    )
    def test_tipo_match_acepta_los_4_valores_del_catalogo(self, valor):
        mapeo = MapeoMigracionCuenta(
            origen_cuenta_id=ORIGEN_ID, tipo_match=valor
        )
        assert mapeo.tipo_match.value == valor

    def test_tipo_match_rechaza_valor_fuera_de_catalogo(self):
        with pytest.raises(ValidationError):
            MapeoMigracionCuenta(
                origen_cuenta_id=ORIGEN_ID, tipo_match="coincidencia_magica"
            )

    @pytest.mark.parametrize(
        "valor",
        ["pendiente", "aprobado", "rechazado", "editado"],
    )
    def test_estado_acepta_los_4_valores_del_catalogo(self, valor):
        mapeo = MapeoMigracionCuenta(
            origen_cuenta_id=ORIGEN_ID,
            tipo_match=TipoMatchMigracion.FUZZY,
            estado=valor,
        )
        assert mapeo.estado.value == valor

    def test_estado_rechaza_valor_fuera_de_catalogo(self):
        with pytest.raises(ValidationError):
            MapeoMigracionCuenta(
                origen_cuenta_id=ORIGEN_ID,
                tipo_match=TipoMatchMigracion.FUZZY,
                estado="en_limbo",
            )


class TestScoreRango:
    """`score` está acotado a [0, 100] — es una confianza, no un puntaje libre."""

    @pytest.mark.parametrize("score", [-1, -0.01, 100.01, 101, 1000])
    def test_score_fuera_de_rango_es_rechazado(self, score):
        with pytest.raises(ValidationError):
            MapeoMigracionCuenta(
                origen_cuenta_id=ORIGEN_ID,
                tipo_match=TipoMatchMigracion.FUZZY,
                score=score,
            )

    @pytest.mark.parametrize("score", [0, 0.0, 59.99, 60, 99, 100, 100.0])
    def test_score_dentro_de_rango_es_aceptado(self, score):
        mapeo = MapeoMigracionCuenta(
            origen_cuenta_id=ORIGEN_ID,
            tipo_match=TipoMatchMigracion.FUZZY,
            score=score,
        )
        assert mapeo.score == score


class TestCamposRequeridos:
    """`origen_cuenta_id` y `tipo_match` son obligatorios: no existe un
    mapeo sin decir qué cuenta de origen se está mapeando ni cómo se
    determinó la correspondencia."""

    def test_falta_origen_cuenta_id(self):
        with pytest.raises(ValidationError):
            MapeoMigracionCuenta(tipo_match=TipoMatchMigracion.EXACTO)

    def test_falta_tipo_match(self):
        with pytest.raises(ValidationError):
            MapeoMigracionCuenta(origen_cuenta_id=ORIGEN_ID)
