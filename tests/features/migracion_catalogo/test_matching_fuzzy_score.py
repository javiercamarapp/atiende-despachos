# -*- coding: utf-8 -*-
"""
test_matching_fuzzy_score.py — REQ-MIG-005.

Criterio de aceptación exacto (docs/BLUEPRINT-AGENTES-FISCALES.md §3):

  "El motor debe calcular un tipo_match="fuzzy" con score compuesto
  (similitud de nombre vía rapidfuzz token_sort_ratio, ponderada con
  coincidencia de nivel jerárquico, naturaleza D/A, tipo agregado y
  cuenta padre) para pares sin match exacto ni alerta de riesgo; todo
  resultado fuzzy debe quedar con estado="pendiente" sin excepción,
  incluso con score=99."

Sin mocks para el cálculo del score: `calcular_score_compuesto` se
ejercita con rapidfuzz real (mismo `token_sort_ratio` que usa la
implementación) sobre pares de `CuentaCatalogo` reales, y se verifica el
resultado contra el mismo cálculo ponderado hecho a mano en la prueba.

La ÚNICA prueba que sustituye `calcular_score_compuesto` por un valor
fijo (`test_invariante_estado_pendiente_sin_importar_el_score`) no
disfraza la lógica bajo prueba: esa lógica (el score compuesto) ya se
verifica de extremo a extremo en `TestScoreCompuesto` con rapidfuzz real.
Lo que esa prueba aislada verifica es un invariante distinto —
`construir_match_fuzzy` nunca lee el score para decidir el estado— y
aislarlo del valor concreto que devuelva el cálculo es la forma más
directa de probar "sin excepción, incluso con score=99" para cualquier
score, no solo para el que la aritmética real sea capaz de producir en
un ejemplo construido a mano.
"""
from __future__ import annotations

import pytest
from rapidfuzz import fuzz

from b2b_ai.features.migracion_catalogo import matching
from b2b_ai.features.migracion_catalogo.matching import (
    PESO_CUENTA_PADRE,
    PESO_NATURALEZA,
    PESO_NIVEL,
    PESO_NOMBRE,
    PESO_TIPO_AGREGADO,
    CuentaCatalogo,
    calcular_score_compuesto,
    construir_match_fuzzy,
    normalizar_texto,
    similitud_nombre,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)


def _cuenta(
    cuenta_id: str,
    codigo: str,
    nombre: str,
    nivel: int = 2,
    naturaleza: str = "D",
    tipo_agregado: str = "Activo",
    cuenta_padre_codigo: str | None = "100",
) -> CuentaCatalogo:
    return CuentaCatalogo(
        id=cuenta_id,
        codigo=codigo,
        nombre=nombre,
        nivel=nivel,
        naturaleza=naturaleza,
        tipo_agregado=tipo_agregado,
        cuenta_padre_codigo=cuenta_padre_codigo,
    )


def _score_esperado(
    nombre_score: float,
    nivel_coincide: bool,
    naturaleza_coincide: bool,
    tipo_coincide: bool,
    padre_coincide: bool,
) -> float:
    """Recalcula el score compuesto a mano, con la misma fórmula descrita
    en el criterio de aceptación, para comparar contra la implementación
    real sin usar sus propios helpers internos."""
    total = (
        nombre_score * PESO_NOMBRE
        + (100.0 if nivel_coincide else 0.0) * PESO_NIVEL
        + (100.0 if naturaleza_coincide else 0.0) * PESO_NATURALEZA
        + (100.0 if tipo_coincide else 0.0) * PESO_TIPO_AGREGADO
        + (100.0 if padre_coincide else 0.0) * PESO_CUENTA_PADRE
    )
    return round(total, 2)


class TestPonderaciones:
    """Las ponderaciones documentadas en el criterio de aceptación deben
    sumar 1.0 (un score compuesto, no una suma libre)."""

    def test_pesos_suman_1(self):
        total = (
            PESO_NOMBRE + PESO_NIVEL + PESO_NATURALEZA + PESO_TIPO_AGREGADO + PESO_CUENTA_PADRE
        )
        assert total == pytest.approx(1.0)

    def test_nombre_es_el_factor_de_mayor_peso(self):
        """El nombre es la señal más informativa; ningún otro factor por
        sí solo debe pesar más que la similitud de nombre."""
        assert PESO_NOMBRE > PESO_NIVEL
        assert PESO_NOMBRE > PESO_NATURALEZA
        assert PESO_NOMBRE > PESO_TIPO_AGREGADO
        assert PESO_NOMBRE > PESO_CUENTA_PADRE


class TestScoreCompuesto:
    """`calcular_score_compuesto` real, con rapidfuzz real — cada caso se
    verifica contra el mismo cálculo ponderado hecho a mano en la prueba
    (`_score_esperado`), usando `similitud_nombre` (la misma función de
    producción, que a su vez llama a `fuzz.token_sort_ratio` sin mocks)
    para obtener el ingrediente de nombre."""

    def test_todo_coincide_nombre_identico_da_score_100(self):
        origen = _cuenta("o1", "102-001", "Bancos Nacionales")
        destino = _cuenta("d1", "102-002", "Bancos Nacionales")  # mismo resto

        score = calcular_score_compuesto(origen, destino)

        assert score == 100.0
        assert score == _score_esperado(100.0, True, True, True, True)

    def test_solo_cuenta_padre_distinta(self):
        origen = _cuenta("o1", "102-001", "Bancos Nacionales", cuenta_padre_codigo="100")
        destino = _cuenta("d1", "102-002", "Bancos Nacionales", cuenta_padre_codigo="200")

        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(100.0, True, True, True, False)
        assert score == 90.0

    def test_solo_nivel_distinto(self):
        origen = _cuenta("o1", "102-001", "Bancos Nacionales", nivel=2)
        destino = _cuenta("d1", "102-002", "Bancos Nacionales", nivel=3)

        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(100.0, False, True, True, True)
        assert score == 85.0

    def test_solo_naturaleza_distinta(self):
        origen = _cuenta("o1", "102-001", "Bancos Nacionales", naturaleza="D")
        destino = _cuenta("d1", "102-002", "Bancos Nacionales", naturaleza="A")

        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(100.0, True, False, True, True)
        assert score == 85.0

    def test_solo_tipo_agregado_distinto(self):
        origen = _cuenta("o1", "102-001", "Bancos Nacionales", tipo_agregado="Activo")
        destino = _cuenta("d1", "102-002", "Bancos Nacionales", tipo_agregado="Pasivo")

        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(100.0, True, True, False, True)
        assert score == 90.0

    def test_cuenta_padre_ausente_en_ambos_lados_no_suma_puntos(self):
        """Dos cuentas de nivel 1 (sin padre) no deben "ganar" el bonus de
        cuenta padre por tener ambas `None` — ausencia de dato no es
        evidencia de coincidencia (mismo criterio que REQ-MIG-004 aplica
        a código/nombre vacíos)."""
        origen = _cuenta("o1", "100", "Activo", nivel=1, cuenta_padre_codigo=None)
        destino = _cuenta("d1", "200", "Activo", nivel=1, cuenta_padre_codigo=None)

        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(100.0, True, True, True, False)
        assert score == 90.0

    def test_cuenta_padre_coincide_con_formato_distinto(self):
        """El código de la cuenta padre se compara de forma laxa (sin
        guiones/espacios): "102-001" y "102 001" deben contar como el
        mismo padre."""
        origen = _cuenta("o1", "500-010", "Gastos", cuenta_padre_codigo="102-001")
        destino = _cuenta("d1", "500-020", "Gastos", cuenta_padre_codigo="102 001")

        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(100.0, True, True, True, True)
        assert score == 100.0

    def test_nombres_completamente_distintos_y_ningun_factor_estructural_coincide(self):
        origen = _cuenta(
            "o1", "102-001", "Bancos", nivel=1, naturaleza="D",
            tipo_agregado="Activo", cuenta_padre_codigo=None,
        )
        destino = _cuenta(
            "d1", "500-010", "Gastos de Papelería", nivel=3, naturaleza="A",
            tipo_agregado="Gasto", cuenta_padre_codigo="500",
        )

        nombre_score_real = similitud_nombre(origen.nombre, destino.nombre)
        score = calcular_score_compuesto(origen, destino)

        assert score == _score_esperado(nombre_score_real, False, False, False, False)
        # Con ningún factor estructural a favor, el score no puede superar
        # lo que aporta, por sí sola, la similitud de nombre.
        assert score <= nombre_score_real * PESO_NOMBRE + 0.01

    def test_similitud_nombre_usa_token_sort_ratio_real_de_rapidfuzz(self):
        """`similitud_nombre` no reinventa el algoritmo: debe coincidir
        exactamente con `fuzz.token_sort_ratio` sobre el texto normalizado
        (acentos fuera, mayúsculas, espacios colapsados)."""
        nombre_origen = "Depósitos en Tránsito"
        nombre_destino = "TRANSITO EN DEPOSITOS"  # mismas palabras, orden distinto

        esperado = float(
            fuzz.token_sort_ratio(
                normalizar_texto(nombre_origen), normalizar_texto(nombre_destino)
            )
        )
        assert similitud_nombre(nombre_origen, nombre_destino) == esperado
        # token_sort_ratio ignora el orden de las palabras -> debería ser
        # una similitud perfecta una vez normalizado.
        assert esperado == 100.0

    def test_score_nunca_sale_del_rango_0_100(self):
        casos = [
            _cuenta("a", "1", "Bancos", nivel=1, naturaleza="D", tipo_agregado="Activo"),
            _cuenta("b", "2", "Zzzzz Completamente Distinto", nivel=9, naturaleza="A",
                    tipo_agregado="Gasto", cuenta_padre_codigo="999"),
        ]
        score = calcular_score_compuesto(casos[0], casos[1])
        assert 0.0 <= score <= 100.0

    def test_score_es_simetrico_en_los_factores_estructurales(self):
        """El score no depende de cuál cuenta se pase como "origen" y cuál
        como "destino" (todas las comparaciones estructurales son de
        igualdad, y `token_sort_ratio` es simétrico)."""
        a = _cuenta("a", "102-001", "Bancos Nacionales", nivel=2, naturaleza="D")
        b = _cuenta("b", "102-002", "Nacionales Bancos", nivel=2, naturaleza="D")

        assert calcular_score_compuesto(a, b) == calcular_score_compuesto(b, a)


class TestConstruirMatchFuzzy:
    """`construir_match_fuzzy` produce el `MapeoMigracionCuenta` real
    (pydantic) — REQ-MIG-005."""

    def test_tipo_match_es_fuzzy_y_estado_pendiente(self):
        origen = _cuenta("origen-1", "102-001", "Bancos Nacionales")
        destino = _cuenta("destino-1", "102-002", "Banco Nacional")  # similar, no idéntico

        mapeo = construir_match_fuzzy(origen, destino)

        assert isinstance(mapeo, MapeoMigracionCuenta)
        assert mapeo.tipo_match == TipoMatchMigracion.FUZZY
        assert mapeo.tipo_match.value == "fuzzy"
        assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
        assert mapeo.estado.value == "pendiente"
        assert mapeo.origen_cuenta_id == "origen-1"
        assert mapeo.destino_cuenta_id == "destino-1"

    def test_score_del_mapeo_coincide_con_calcular_score_compuesto(self):
        origen = _cuenta("o", "102-001", "Documentos por Cobrar")
        destino = _cuenta("d", "102-777", "Documentos x Cobrar")

        esperado = calcular_score_compuesto(origen, destino)
        mapeo = construir_match_fuzzy(origen, destino)

        assert mapeo.score == esperado

    def test_nota_menciona_el_score_y_no_viene_vacia(self):
        origen = _cuenta("o", "102-001", "Bancos")
        destino = _cuenta("d", "300-050", "Bancos Extranjeros")

        mapeo = construir_match_fuzzy(origen, destino)

        assert mapeo.nota
        assert f"{mapeo.score:.2f}" in mapeo.nota

    def test_nunca_asigna_aprobado_por_ni_aprobado_en(self):
        """Un fuzzy nace pendiente: no hay decisión humana todavía, así
        que no debe traer aprobado_por/aprobado_en."""
        origen = _cuenta("o", "102-001", "Bancos")
        destino = _cuenta("d", "300-050", "Bancos Extranjeros")

        mapeo = construir_match_fuzzy(origen, destino)

        assert mapeo.aprobado_por is None
        assert mapeo.aprobado_en is None

    def test_score_muy_alto_real_sigue_pendiente(self):
        """Caso real (sin monkeypatch) con score genuinamente alto: nombre
        casi idéntico + todos los factores estructurales coinciden. Aun
        así, el estado debe seguir siendo pendiente."""
        origen = _cuenta("o", "102-001", "Bancos Nacionales")
        destino = _cuenta("d", "102-777", "Banco Nacionales")  # 1 letra distinta

        mapeo = construir_match_fuzzy(origen, destino)

        assert mapeo.score >= 90.0  # score real, no inventado
        assert mapeo.tipo_match == TipoMatchMigracion.FUZZY
        assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE


class TestInvarianteADR3SinExcepcion:
    """El corazón de REQ-MIG-005: "todo resultado fuzzy debe quedar con
    estado=pendiente sin excepción, incluso con score=99".

    `calcular_score_compuesto` ya se verificó con aritmética real y
    rapidfuzz real arriba (`TestScoreCompuesto`); aquí se sustituye
    exclusivamente por un valor fijo para poder afirmar el invariante
    para CUALQUIER score posible (0, 59, 60, 99, 99.99, 100), no solo
    para los que un ejemplo de texto concreto sea capaz de producir.
    `construir_match_fuzzy` bajo prueba es la función real, sin doble
    alguno.
    """

    @pytest.mark.parametrize("score_forzado", [0.0, 1.0, 50.0, 59.99, 60.0, 89.0, 99.0, 99.99, 100.0])
    def test_estado_siempre_pendiente_sin_importar_el_score(self, monkeypatch, score_forzado):
        monkeypatch.setattr(matching, "calcular_score_compuesto", lambda o, d: score_forzado)

        origen = _cuenta("o", "102-001", "Bancos")
        destino = _cuenta("d", "300-050", "Cualquier Cosa")

        mapeo = construir_match_fuzzy(origen, destino)

        assert mapeo.score == score_forzado
        assert mapeo.tipo_match == TipoMatchMigracion.FUZZY
        assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
        assert mapeo.estado.value == "pendiente"
        assert mapeo.estado != EstadoMapeoMigracion.APROBADO

    def test_score_99_exacto_del_criterio_de_aceptacion_nunca_es_aprobado(self, monkeypatch):
        """Repite, de forma literal, el ejemplo del criterio de
        aceptación: "incluso con score=99"."""
        monkeypatch.setattr(matching, "calcular_score_compuesto", lambda o, d: 99.0)

        origen = _cuenta("o", "102-001", "Bancos Nacionales S.A.")
        destino = _cuenta("d", "102-777", "Bancos Nacionales SA")

        mapeo = construir_match_fuzzy(origen, destino)

        assert mapeo.score == 99.0
        assert mapeo.tipo_match == TipoMatchMigracion.FUZZY
        assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
        assert mapeo.aprobado_por is None
        assert mapeo.aprobado_en is None

    def test_no_existe_ninguna_ruta_en_construir_match_fuzzy_que_dependa_del_score(
        self, monkeypatch
    ):
        """Ejercita `construir_match_fuzzy` con una familia amplia de
        scores forzados y confirma que el conjunto de estados producidos
        es exactamente {PENDIENTE} — nunca aparece APROBADO/RECHAZADO/
        EDITADO para ningún valor, alto o bajo."""
        origen = _cuenta("o", "1", "X")
        destino = _cuenta("d", "2", "Y")

        estados_vistos = set()
        for score_forzado in [0.0, 25.0, 59.99, 60.0, 75.0, 99.0, 100.0]:
            monkeypatch.setattr(matching, "calcular_score_compuesto", lambda o, d, s=score_forzado: s)
            mapeo = construir_match_fuzzy(origen, destino)
            estados_vistos.add(mapeo.estado)

        assert estados_vistos == {EstadoMapeoMigracion.PENDIENTE}
