# -*- coding: utf-8 -*-
"""
test_classification_rules.py — REQ-IVA-001

El fundamento legal de las clasificaciones 'financiamiento', 'aportacion_socio'
y 'garantia' debe ser "CFF Art. 59 fracción III" (la excepción a la presunción
de depósitos bancarios como ingreso), no "CFF Art. 14" (que no habla de
presunción de depósitos) ni None.

ADR: esta clasificación automática es solo una SUGERENCIA de primera pasada
(origen="automatico_sugerido" en REQ-IVA-013); nunca se aplica la presunción
del Art. 59 fracc. III por cuenta propia como determinación fiscal firme.
Este test no valida ese flujo de aprobación humana (eso es REQ-IVA-013):
valida únicamente que el fundamento legal citado en la regla es el correcto.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.reconciliacion_ingresos_egresos.classification_rules import (
    DEFAULT_RULES,
    ClassificationEngine,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    ClasificacionDeposito,
    DepositoBancario,
)

ARTICULO_ESPERADO = "CFF Art. 59 fracción III"

# Nombres de las 3 reglas cuyo fundamento debe ser corregido.
REGLAS_ART_59 = {"Financiamiento-Bancario", "Aportación-Socio", "Garantía-Depósito"}


def _reglas_por_nombre() -> dict:
    return {regla.name: regla for regla in DEFAULT_RULES}


@pytest.mark.parametrize("nombre_regla", sorted(REGLAS_ART_59))
def test_articulo_cff_es_59_fraccion_iii(nombre_regla: str) -> None:
    """Cada una de las 3 reglas (financiamiento, aportación de socio, garantía)
    debe citar CFF Art. 59 fracción III como fundamento legal."""
    reglas = _reglas_por_nombre()
    assert nombre_regla in reglas, f"No se encontró la regla '{nombre_regla}' en DEFAULT_RULES"
    regla = reglas[nombre_regla]
    assert regla.articulo_cff == ARTICULO_ESPERADO


def test_las_3_reglas_objetivo_tienen_el_articulo_correcto() -> None:
    """Verificación agregada: exactamente las 3 reglas del ADR citan
    CFF Art. 59 fracción III (ninguna quedó en Art. 14 o en None)."""
    reglas = _reglas_por_nombre()
    for nombre in REGLAS_ART_59:
        regla = reglas[nombre]
        assert regla.articulo_cff == ARTICULO_ESPERADO
        # Ya no debe quedar el fundamento incorrecto ni vacío.
        assert regla.articulo_cff != "CFF Art. 14"
        assert regla.articulo_cff is not None


def test_regla_garantia_ya_no_tiene_articulo_cff_nulo() -> None:
    """Antes de este fix, 'Garantía-Depósito' tenía articulo_cff=None."""
    regla = _reglas_por_nombre()["Garantía-Depósito"]
    assert regla.articulo_cff is not None
    assert regla.articulo_cff == ARTICULO_ESPERADO


def test_regla_cfdi_ingreso_no_se_toca() -> None:
    """La regla de ingreso gravado (match a CFDI) no forma parte de este
    requisito y debe conservar su propio fundamento (LIVA Art. 1), no el
    de la presunción de depósitos del Art. 59 fracc. III."""
    regla = _reglas_por_nombre()["CFDI-Ingreso"]
    assert regla.articulo_cff != ARTICULO_ESPERADO
    assert "LIVA" in (regla.articulo_cff or "")


@pytest.mark.parametrize(
    "descripcion,clasificacion_esperada",
    [
        ("Depósito por préstamo bancario Banco XYZ", ClasificacionDeposito.FINANCIAMIENTO),
        ("Aportación de socio Juan Pérez", ClasificacionDeposito.APORTACION_SOCIO),
        ("Depósito en garantía de arrendamiento", ClasificacionDeposito.GARANTIA),
    ],
)
def test_engine_propaga_el_articulo_cff_correcto_en_tiempo_de_ejecucion(
    descripcion: str, clasificacion_esperada: ClasificacionDeposito
) -> None:
    """Prueba de comportamiento real (sin mocks): al clasificar un depósito
    concreto a través de ClassificationEngine, el `articulo_cff` devuelto por
    `classify()` debe ser el fundamento corregido, no solo el dataclass en
    aislamiento."""
    engine = ClassificationEngine()
    deposito = DepositoBancario(
        id="DEP-TEST-001",
        fecha="2026-06-15",
        monto=50000.00,
        descripcion=descripcion,
        referencia="",
        banco="BBVA",
        cuenta="0123456789",
        es_credito=True,
    )

    clasificacion, confianza, razon, articulo_cff = engine.classify(deposito, auxiliares=[])

    assert clasificacion == clasificacion_esperada
    assert articulo_cff == ARTICULO_ESPERADO
    assert confianza > 0
    assert razon is not None
