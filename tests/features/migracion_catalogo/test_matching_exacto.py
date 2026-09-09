# -*- coding: utf-8 -*-
"""
test_matching_exacto.py — REQ-MIG-003.

Criterio de aceptación exacto (docs/BLUEPRINT-AGENTES-FISCALES.md §3):

  "El motor de matching debe auto-aprobar (sin cola de revisión)
  únicamente cuando código normalizado (sin acentos/mayúsculas/espacios
  colapsados) Y nombre normalizado sean idénticos entre origen y
  destino; prueba: 100 pares código+nombre idénticos → 100 mapeos con
  tipo_match="exacto" y estado="aprobado" sin intervención humana."

Sin mocks: se ejercita `evaluar_match_exacto` real de
`b2b_ai/features/migracion_catalogo/matching.py` sobre pares de cuentas
reales (`CuentaCatalogoPar`), incluyendo variantes de acentos/mayúsculas/
espacios que deben normalizar a lo mismo, y se valida el
`MapeoMigracionCuenta` real (pydantic) que produce.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.migracion_catalogo.matching import (
    CuentaCatalogoPar,
    es_match_exacto,
    evaluar_match_exacto,
    normalizar_codigo,
    normalizar_nombre,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    TipoMatchMigracion,
)


def _par_identico(i: int) -> tuple[CuentaCatalogoPar, CuentaCatalogoPar]:
    """Genera un par (origen, destino) con código+nombre idénticos, variando
    el texto real usado para que la prueba no dependa de una sola cadena
    literal repetida 100 veces.
    """
    codigo = f"102-{i:04d}"
    nombre = f"Bancos Sucursal {i}"
    origen = CuentaCatalogoPar(cuenta_id=f"origen-{i}", codigo=codigo, nombre=nombre)
    destino = CuentaCatalogoPar(cuenta_id=f"destino-{i}", codigo=codigo, nombre=nombre)
    return origen, destino


class TestCienParesIdenticosSeAutoAprueban:
    """El caso de aceptación literal de REQ-MIG-003: 100 pares código+nombre
    idénticos → 100 mapeos tipo_match="exacto"/estado="aprobado" sin
    intervención humana."""

    def test_100_pares_identicos_producen_100_mapeos_aprobados(self):
        pares = [_par_identico(i) for i in range(100)]

        mapeos = [evaluar_match_exacto(origen, destino) for origen, destino in pares]

        assert len(mapeos) == 100
        assert all(m is not None for m in mapeos)
        for (origen, destino), mapeo in zip(pares, mapeos):
            assert mapeo.tipo_match == TipoMatchMigracion.EXACTO
            assert mapeo.tipo_match.value == "exacto"
            assert mapeo.estado == EstadoMapeoMigracion.APROBADO
            assert mapeo.estado.value == "aprobado"
            assert mapeo.origen_cuenta_id == origen.cuenta_id
            assert mapeo.destino_cuenta_id == destino.cuenta_id
            assert mapeo.score == 100.0

    def test_100_pares_identicos_no_tienen_intervencion_humana(self):
        """"sin intervención humana": nadie aprobó a mano, por lo tanto no
        hay aprobado_por ni aprobado_en asociado a la decisión."""
        pares = [_par_identico(i) for i in range(100)]
        mapeos = [evaluar_match_exacto(origen, destino) for origen, destino in pares]

        assert all(m.aprobado_por is None for m in mapeos)
        assert all(m.aprobado_en is None for m in mapeos)


class TestNormalizacion:
    """La igualdad exacta se evalúa sobre código/nombre normalizados: sin
    acentos, sin distinción de mayúsculas/minúsculas, con espacios
    colapsados — no sobre las cadenas literales."""

    @pytest.mark.parametrize(
        "crudo,esperado",
        [
            ("Bancos", "BANCOS"),
            ("  Bancos   Nacionales  ", "BANCOS NACIONALES"),
            ("Depósitos en Tránsito", "DEPOSITOS EN TRANSITO"),
            ("PROVEEDORES Y ACREEDORES", "PROVEEDORES Y ACREEDORES"),
            ("Ingresós Ñoño", "INGRESOS NONO"),
            ("", ""),
        ],
    )
    def test_normalizar_nombre(self, crudo, esperado):
        assert normalizar_nombre(crudo) == esperado

    def test_normalizar_codigo_colapsa_espacios(self):
        assert normalizar_codigo("  102 - 001  ") == "102 - 001"

    def test_match_exacto_con_acentos_mayusculas_y_espacios_distintos(self):
        origen = CuentaCatalogoPar(
            cuenta_id="o1", codigo="102-001", nombre="Depósitos en Tránsito"
        )
        destino = CuentaCatalogoPar(
            cuenta_id="d1",
            codigo="  102-001  ",
            nombre="DEPOSITOS   EN   TRANSITO",
        )

        assert es_match_exacto(origen, destino) is True
        mapeo = evaluar_match_exacto(origen, destino)
        assert mapeo is not None
        assert mapeo.tipo_match == TipoMatchMigracion.EXACTO
        assert mapeo.estado == EstadoMapeoMigracion.APROBADO


class TestNuncaAutoApruebaDiferencias:
    """REQ-MIG-003 dice "únicamente cuando... código Y nombre... sean
    idénticos": cualquier diferencia (código solo, nombre solo, o ambos)
    nunca debe producir un mapeo aprobado desde esta función."""

    def test_codigo_igual_nombre_distinto_no_se_autoaprueba(self):
        origen = CuentaCatalogoPar(cuenta_id="o1", codigo="102-001", nombre="Bancos")
        destino = CuentaCatalogoPar(cuenta_id="d1", codigo="102-001", nombre="Clientes")

        assert es_match_exacto(origen, destino) is False
        assert evaluar_match_exacto(origen, destino) is None

    def test_nombre_igual_codigo_distinto_no_se_autoaprueba(self):
        origen = CuentaCatalogoPar(cuenta_id="o1", codigo="102-001", nombre="Bancos")
        destino = CuentaCatalogoPar(cuenta_id="d1", codigo="103-002", nombre="Bancos")

        assert es_match_exacto(origen, destino) is False
        assert evaluar_match_exacto(origen, destino) is None

    def test_ambos_distintos_no_se_autoaprueba(self):
        origen = CuentaCatalogoPar(cuenta_id="o1", codigo="102-001", nombre="Bancos")
        destino = CuentaCatalogoPar(
            cuenta_id="d1", codigo="500-010", nombre="Gastos de Venta"
        )

        assert es_match_exacto(origen, destino) is False
        assert evaluar_match_exacto(origen, destino) is None

    def test_codigo_y_nombre_vacios_en_origen_no_se_autoaprueba(self):
        """Dos registros sin código/nombre no son una coincidencia real:
        no debe auto-aprobarse solo porque ambos lados están vacíos."""
        origen = CuentaCatalogoPar(cuenta_id="o1", codigo="", nombre="")
        destino = CuentaCatalogoPar(cuenta_id="d1", codigo="", nombre="")

        assert es_match_exacto(origen, destino) is False
        assert evaluar_match_exacto(origen, destino) is None
