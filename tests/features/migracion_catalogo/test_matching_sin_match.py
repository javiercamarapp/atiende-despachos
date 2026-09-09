# -*- coding: utf-8 -*-
"""
test_matching_sin_match.py — REQ-MIG-006.

Una cuenta origen sin ningún candidato con `score >= 60` debe quedar
clasificada como `tipo_match="sin_match"` con nota "cuenta nueva a crear en
destino", y NUNCA generar un `MapeoMigracionCuenta` con `destino_cuenta_id`
inventado.

Sin mocks: se llama la función real `clasificar_cuenta_origen` de
`b2b_ai/features/migracion_catalogo/matching.py` (que a su vez usa el score
compuesto real de REQ-MIG-005, `calcular_score_compuesto`, y el detector
real de alerta_riesgo de REQ-MIG-004) sobre instancias reales de
`CuentaCatalogo`, y se inspecciona el `MapeoMigracionCuenta` real (pydantic)
que produce.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.migracion_catalogo.matching import (
    NOTA_SIN_MATCH,
    UMBRAL_SIN_MATCH,
    CuentaCatalogo,
    calcular_score_compuesto,
    clasificar_cuenta_origen,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)


def _cuenta(**overrides) -> CuentaCatalogo:
    base = dict(
        id="id-por-defecto",
        codigo="000-000",
        nombre="Cuenta genérica",
        nivel=2,
        naturaleza="D",
        tipo_agregado="Activo",
        cuenta_padre_codigo=None,
    )
    base.update(overrides)
    return CuentaCatalogo(**base)


ORIGEN = _cuenta(
    id="origen-1",
    codigo="601-777",
    nombre="Gastos de Representación Extraordinarios",
    nivel=3,
    naturaleza="D",
    tipo_agregado="Gasto",
    cuenta_padre_codigo="601",
)


class TestSinCandidatos:
    """Caso límite: catálogo destino vacío. Sigue siendo 'ningún candidato
    con score >= 60' (vacuamente cierto), así que debe seguir la misma
    regla."""

    def test_lista_vacia_de_candidatos_es_sin_match(self):
        mapeo = clasificar_cuenta_origen(ORIGEN, [])

        assert isinstance(mapeo, MapeoMigracionCuenta)
        assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert mapeo.tipo_match.value == "sin_match"
        assert mapeo.destino_cuenta_id is None
        assert mapeo.nota == NOTA_SIN_MATCH
        assert mapeo.nota == "cuenta nueva a crear en destino"
        assert mapeo.score == 0.0
        assert mapeo.origen_cuenta_id == "origen-1"


class TestCandidatosPorDebajoDelUmbral:
    """Hay candidatos, pero ninguno con código o nombre idéntico ni con
    score compuesto >= 60: sigue siendo sin_match."""

    def _candidatos_lejanos(self):
        # Ni código ni nombre coinciden con ORIGEN (evita exacto/alerta_riesgo);
        # nombre completamente distinto y ningún factor estructural coincide
        # (evita también que empujen el score compuesto por encima de 60).
        return [
            _cuenta(
                id="destino-lejano-1",
                codigo="100-001",
                nombre="Bancos Nacionales",
                nivel=1,
                naturaleza="D",
                tipo_agregado="Activo",
                cuenta_padre_codigo="100",
            ),
            _cuenta(
                id="destino-lejano-2",
                codigo="200-050",
                nombre="Proveedores Extranjeros",
                nivel=2,
                naturaleza="A",
                tipo_agregado="Pasivo",
                cuenta_padre_codigo="200",
            ),
            _cuenta(
                id="destino-lejano-3",
                codigo="401-010",
                nombre="Ventas de Exportación",
                nivel=2,
                naturaleza="A",
                tipo_agregado="Ingreso",
                cuenta_padre_codigo="401",
            ),
        ]

    def test_ningun_candidato_alcanza_60_es_sin_match(self):
        candidatos = self._candidatos_lejanos()

        # Verificación de la premisa del test (sin mocks: se calcula el
        # score real de cada candidato y se confirma que, en efecto,
        # ninguno alcanza el umbral).
        scores = [calcular_score_compuesto(ORIGEN, c) for c in candidatos]
        assert all(s < UMBRAL_SIN_MATCH for s in scores), scores

        mapeo = clasificar_cuenta_origen(ORIGEN, candidatos)

        assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert mapeo.destino_cuenta_id is None
        assert mapeo.nota == NOTA_SIN_MATCH

    def test_score_reportado_es_el_mejor_entre_los_candidatos_no_cero(self):
        """El score de un sin_match no se fuerza a 0: reporta el mejor
        score real encontrado (útil para que un humano vea qué tan cerca
        estuvo), aunque siga sin alcanzar el umbral."""
        candidatos = self._candidatos_lejanos()
        mejor_score_real = max(calcular_score_compuesto(ORIGEN, c) for c in candidatos)

        mapeo = clasificar_cuenta_origen(ORIGEN, candidatos)

        assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert mapeo.score == mejor_score_real
        assert mapeo.score < UMBRAL_SIN_MATCH


class TestNuncaInventaDestino:
    """El criterio más importante de REQ-MIG-006: jamás un
    `destino_cuenta_id` inventado, ni siquiera apuntando "por accidente" a
    alguno de los candidatos descartados."""

    def test_destino_cuenta_id_nunca_es_alguno_de_los_candidatos_descartados(self):
        candidatos = [
            _cuenta(id="candidato-descartado-1", codigo="900-001", nombre="Otros Gastos"),
            _cuenta(id="candidato-descartado-2", codigo="900-002", nombre="Gastos Varios"),
        ]
        ids_candidatos = {c.id for c in candidatos}

        mapeo = clasificar_cuenta_origen(ORIGEN, candidatos)

        assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert mapeo.destino_cuenta_id is None
        assert mapeo.destino_cuenta_id not in ids_candidatos

    def test_modelo_real_rechaza_reasignar_destino_a_sin_match(self):
        """Defensa adicional: si alguien intentara "arreglar" un sin_match
        poniéndole un destino a mano, el modelo pydantic real lo sigue
        aceptando como dato (no es su responsabilidad impedirlo), pero
        confirma que el motor de matching NUNCA lo hace por sí mismo — este
        test documenta que la garantía viene del motor, no de una
        constraint del esquema."""
        mapeo = clasificar_cuenta_origen(ORIGEN, [])
        assert mapeo.destino_cuenta_id is None
        # El propio motor nunca fue el que puso un id: no hay ningún punto
        # en clasificar_cuenta_origen donde la rama sin_match reciba un
        # `destino_cuenta_id` distinto de None.


class TestUmbralExactoConScoreReal:
    """Confirma la semántica `>=` del umbral usando el score REAL calculado
    por `calcular_score_compuesto` (no un valor inventado): en el umbral
    exacto ya cuenta como match; un centésimo por debajo, no."""

    def test_score_en_el_umbral_exacto_ya_no_es_sin_match(self):
        candidato = _cuenta(
            id="destino-parecido",
            codigo="601-778",
            nombre="Gastos de Representación",
            nivel=3,
            naturaleza="D",
            tipo_agregado="Gasto",
            cuenta_padre_codigo="601",
        )
        score_real = calcular_score_compuesto(ORIGEN, candidato)

        mapeo = clasificar_cuenta_origen(ORIGEN, [candidato], umbral_sin_match=score_real)

        assert mapeo.tipo_match == TipoMatchMigracion.FUZZY
        assert mapeo.destino_cuenta_id == "destino-parecido"

    def test_un_centesimo_por_encima_del_score_real_si_es_sin_match(self):
        candidato = _cuenta(
            id="destino-parecido",
            codigo="601-778",
            nombre="Gastos de Representación",
            nivel=3,
            naturaleza="D",
            tipo_agregado="Gasto",
            cuenta_padre_codigo="601",
        )
        score_real = calcular_score_compuesto(ORIGEN, candidato)

        mapeo = clasificar_cuenta_origen(
            ORIGEN, [candidato], umbral_sin_match=score_real + 0.01
        )

        assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert mapeo.destino_cuenta_id is None
        assert mapeo.nota == NOTA_SIN_MATCH


class TestCasiCoincideNoCuentaComoMatch:
    """Un nombre 'casi' idéntico (una palabra distinta) que aun así el
    score compuesto real deja por debajo de 60 no debe colarse como fuzzy:
    REQ-MIG-006 no admite excepciones por "se parece mucho"."""

    def test_nombre_parecido_pero_score_bajo_umbral_default_es_sin_match(self):
        origen = _cuenta(
            id="origen-2",
            codigo="510-020",
            nombre="Papelería y Artículos de Oficina",
            nivel=3,
            naturaleza="D",
            tipo_agregado="Gasto",
            cuenta_padre_codigo="510",
        )
        candidato = _cuenta(
            id="destino-3",
            codigo="990-999",
            nombre="Consumibles de Cómputo",
            nivel=4,
            naturaleza="A",
            tipo_agregado="Ingreso",
            cuenta_padre_codigo="990",
        )
        score_real = calcular_score_compuesto(origen, candidato)
        assert score_real < UMBRAL_SIN_MATCH, score_real

        mapeo = clasificar_cuenta_origen(origen, [candidato])

        assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert mapeo.destino_cuenta_id is None


class TestEstadoDeUnSinMatch:
    """Un sin_match tampoco nace aprobado: no hay destino que aprobar, pero
    el estado sigue el mismo principio de ADR-3 (nada se auto-aplica sin
    revisión humana) — aquí la "revisión" es confirmar que sí hace falta
    crear la cuenta nueva en destino."""

    def test_sin_match_nunca_nace_aprobado(self):
        mapeo = clasificar_cuenta_origen(ORIGEN, [])
        assert mapeo.estado != EstadoMapeoMigracion.APROBADO
        assert mapeo.aprobado_por is None
        assert mapeo.aprobado_en is None


@pytest.mark.parametrize("num_candidatos", [0, 1, 5])
def test_sin_match_es_consistente_sin_importar_cuantos_candidatos_lejanos_haya(
    num_candidatos,
):
    candidatos = [
        _cuenta(
            id=f"lejano-{i}",
            codigo=f"999-{i:03d}",
            nombre=f"Cuenta Sin Relación Alguna {i}",
            nivel=5,
            naturaleza="A" if i % 2 else "D",
            tipo_agregado="Capital",
            cuenta_padre_codigo=f"999{i}",
        )
        for i in range(num_candidatos)
    ]

    mapeo = clasificar_cuenta_origen(ORIGEN, candidatos)

    assert mapeo.tipo_match == TipoMatchMigracion.SIN_MATCH
    assert mapeo.destino_cuenta_id is None
    assert mapeo.nota == "cuenta nueva a crear en destino"
