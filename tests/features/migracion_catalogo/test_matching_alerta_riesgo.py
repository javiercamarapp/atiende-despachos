# -*- coding: utf-8 -*-
"""
test_matching_alerta_riesgo.py — REQ-MIG-004.

El motor debe marcar como `tipo_match="alerta_riesgo"` (nunca auto-aprobado)
todo par donde el código coincide pero el nombre difiere, o el nombre
coincide pero el código difiere.

Caso central del requisito: cuenta origen `code="102-001", name="Bancos"`
vs. destino `code="102-001", name="Clientes"` debe producir
`estado="pendiente"`, jamás `"aprobado"`.

Sin mocks: se llama la función real `evaluar_alerta_riesgo` de
`b2b_ai/features/migracion_catalogo/matching.py` sobre instancias reales de
`CuentaCatalogo` y se inspecciona el `MapeoMigracionCuenta` real que
produce (también un modelo pydantic real, no un doble de prueba).
"""
from __future__ import annotations

import pytest

from b2b_ai.features.migracion_catalogo.matching import (
    CuentaCatalogo,
    es_alerta_riesgo,
    evaluar_alerta_riesgo,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)


def _cuenta(cuenta_id: str, codigo: str, nombre: str, **overrides) -> CuentaCatalogo:
    """Construye una `CuentaCatalogo` real con metadatos jerárquicos
    neutros (idénticos por defecto entre origen/destino) para que las
    pruebas se enfoquen exclusivamente en código+nombre, tal como pide
    REQ-MIG-004."""
    base = dict(nivel=3, naturaleza="D", tipo_agregado="Activo", cuenta_padre_codigo=None)
    base.update(overrides)
    return CuentaCatalogo(id=cuenta_id, codigo=codigo, nombre=nombre, **base)


def test_codigo_coincide_nombre_difiere_es_alerta_riesgo_pendiente():
    """Caso exacto del requisito: mismo código, nombre distinto."""
    origen = _cuenta("origen-1", "102-001", "Bancos")
    destino = _cuenta("destino-1", "102-001", "Clientes")

    assert es_alerta_riesgo(origen, destino) is True

    mapeo = evaluar_alerta_riesgo(origen, destino)

    assert mapeo is not None
    assert isinstance(mapeo, MapeoMigracionCuenta)
    assert mapeo.tipo_match == TipoMatchMigracion.ALERTA_RIESGO
    assert mapeo.tipo_match.value == "alerta_riesgo"
    assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
    assert mapeo.estado.value == "pendiente"
    assert mapeo.estado != EstadoMapeoMigracion.APROBADO
    assert mapeo.origen_cuenta_id == "origen-1"
    assert mapeo.destino_cuenta_id == "destino-1"
    assert mapeo.aprobado_por is None
    assert mapeo.aprobado_en is None


def test_nombre_coincide_codigo_difiere_es_alerta_riesgo_pendiente():
    """Espejo del requisito: mismo nombre, código distinto."""
    origen = _cuenta("origen-2", "102-001", "Bancos")
    destino = _cuenta("destino-2", "102-002", "Bancos")

    assert es_alerta_riesgo(origen, destino) is True

    mapeo = evaluar_alerta_riesgo(origen, destino)

    assert mapeo.tipo_match == TipoMatchMigracion.ALERTA_RIESGO
    assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
    assert mapeo.estado != EstadoMapeoMigracion.APROBADO


@pytest.mark.parametrize(
    "origen_codigo,origen_nombre,destino_codigo,destino_nombre",
    [
        # Código idéntico, nombre completamente distinto.
        ("500-010", "Gastos de Viaje", "500-010", "Depreciación Acumulada"),
        # Nombre idéntico, código completamente distinto.
        ("200-100", "Proveedores Nacionales", "200-999", "Proveedores Nacionales"),
        # Código idéntico salvo espacios/guiones (normaliza igual) pero el
        # nombre sí difiere de verdad -> sigue siendo alerta_riesgo.
        ("  102-001 ", "Bancos", "102001", "Documentos por Cobrar"),
        # Nombre idéntico salvo acentos/mayúsculas (normaliza igual) pero
        # el código sí difiere de verdad -> sigue siendo alerta_riesgo.
        ("110-001", "Clientes Nacionales", "110-777", "CLIENTES NACIONALES"),
        # Nombres parecidísimos (1 letra distinta) NO cuentan como
        # coincidencia de nombre: con el código sí idéntico, sigue siendo
        # alerta_riesgo (nunca exacto solo por "casi" coincidir el nombre).
        ("300-050", "Acreedores Diversos", "300-050", "Acreedores Diverso"),
    ],
)
def test_pares_con_una_sola_coincidencia_nunca_quedan_aprobados(
    origen_codigo, origen_nombre, destino_codigo, destino_nombre
):
    origen = _cuenta("o", origen_codigo, origen_nombre)
    destino = _cuenta("d", destino_codigo, destino_nombre)

    mapeo = evaluar_alerta_riesgo(origen, destino)

    assert mapeo is not None
    assert mapeo.tipo_match == TipoMatchMigracion.ALERTA_RIESGO
    assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
    assert mapeo.estado.value != "aprobado"


def test_alerta_riesgo_nunca_es_aprobado_ni_con_score_alto():
    """El score nunca debe usarse para colar una auto-aprobación: aunque
    el score asignado a alerta_riesgo sea alto, el estado debe seguir
    siendo pendiente."""
    origen = _cuenta("o", "102-001", "Bancos")
    destino = _cuenta("d", "102-001", "Bancos Extranjeros")

    mapeo = evaluar_alerta_riesgo(origen, destino)

    assert mapeo.tipo_match == TipoMatchMigracion.ALERTA_RIESGO
    # Sin importar qué tan alto sea el score, jamás implica aprobación.
    assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE


def test_boundary_ambos_coinciden_no_es_alerta_riesgo():
    """Límite necesario de REQ-MIG-004: cuando código Y nombre SÍ coinciden
    (normalizados), el par NO debe clasificarse como alerta_riesgo — ese
    es el único caso de auto-aprobación permitido por el ADR-3
    (REQ-MIG-003, motor de match exacto — no implementado en este
    módulo)."""
    origen = _cuenta("o", " 102-001 ", "Bancos")
    destino = _cuenta("d", "102-001", "BANCOS")

    assert es_alerta_riesgo(origen, destino) is False
    assert evaluar_alerta_riesgo(origen, destino) is None


def test_boundary_ninguno_coincide_no_se_clasifica_como_alerta_riesgo():
    """Límite necesario de REQ-MIG-004: cuando NI código NI nombre
    coinciden, el par no debe colarse como alerta_riesgo tampoco — cae
    fuera del alcance de este módulo (fuzzy/sin_match, REQ-MIG-005/006)."""
    origen = _cuenta("o", "102-001", "Bancos")
    destino = _cuenta("d", "900-900", "Cuentas por Pagar")

    assert es_alerta_riesgo(origen, destino) is False
    assert evaluar_alerta_riesgo(origen, destino) is None


def test_boundary_nombre_vacio_en_ambos_lados_no_cuenta_como_coincidencia():
    """Un nombre vacío en ambos lados no debe interpretarse como
    'coincidencia' que dispare (o evite) alerta_riesgo — dos cadenas
    vacías no son evidencia de nada; el código sí coincide de verdad, así
    que el par cae en alerta_riesgo por el código."""
    origen = _cuenta("o", "102-001", "")
    destino = _cuenta("d", "102-001", "")

    mapeo = evaluar_alerta_riesgo(origen, destino)
    assert mapeo is not None
    assert mapeo.tipo_match == TipoMatchMigracion.ALERTA_RIESGO
    assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE
