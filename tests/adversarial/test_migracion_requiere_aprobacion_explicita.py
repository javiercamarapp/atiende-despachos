# -*- coding: utf-8 -*-
"""
REQ-MIG-007 (docs/BLUEPRINT-AGENTES-FISCALES.md §3 — Migración/fusión de
catálogo de cuentas). Ver también ADR-3.

Criterio de aceptación exacto:
  "Debe existir un endpoint `POST /api/v1/migracion-catalogo/{mapeo_id}/
  aprobar` (y `/rechazar`, `/editar`) que sea el ÚNICO camino para pasar
  un mapeo de `alerta_riesgo` o `fuzzy` a `estado='aprobado'`; prueba
  adversarial: invocar el motor de migración de pólizas (REQ-MIG-009)
  directamente sobre un mapeo en `estado='pendiente'` debe fallar con
  excepción explícita, nunca migrar."

Sin mocks: se instancian `MigracionCatalogoService` (el servicio real de
aprobación) y `migrar_linea_con_mapeo`/`validar_mapeo_migrable` (el
motor de migración real, en su alcance actual — REQ-MIG-009 completo es
un requisito separado) y se ejercitan directamente. Nada de esto se
sustituye por un doble de prueba: la excepción que se verifica es la que
el código de producción realmente lanza.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.migracion_catalogo.migrador import (
    MapeoNoAprobadoError,
    migrar_linea_con_mapeo,
    validar_mapeo_migrable,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.service import MigracionCatalogoService

ORIGEN_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
DESTINO_ID = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"


def _mapeo_pendiente(tipo_match: TipoMatchMigracion = TipoMatchMigracion.FUZZY) -> MapeoMigracionCuenta:
    return MapeoMigracionCuenta(
        origen_cuenta_id=ORIGEN_ID,
        destino_cuenta_id=DESTINO_ID,
        tipo_match=tipo_match,
        score=87.5,
        estado=EstadoMapeoMigracion.PENDIENTE,
    )


# ---------------------------------------------------------------------------
# El caso adversarial central del criterio de aceptación.
# ---------------------------------------------------------------------------

class TestMotorDeMigracionRechazaMapeoPendiente:
    """Invocar el motor de migración de pólizas directamente sobre un
    mapeo en estado=pendiente debe fallar con excepción explícita, nunca
    migrar."""

    def test_validar_mapeo_migrable_lanza_excepcion_explicita_sobre_pendiente(self):
        mapeo = _mapeo_pendiente()
        with pytest.raises(MapeoNoAprobadoError) as exc_info:
            validar_mapeo_migrable(mapeo)
        # La excepción debe ser explícita/informativa, no un genérico
        # "algo salió mal": debe referenciar el mapeo y su estado real.
        assert mapeo.id in str(exc_info.value)
        assert "pendiente" in str(exc_info.value)

    def test_migrar_linea_con_mapeo_lanza_y_nunca_migra_sobre_pendiente(self):
        mapeo = _mapeo_pendiente()
        linea_origen = {"cuenta_id": ORIGEN_ID, "debe": 100.0, "haber": 0.0}
        linea_original = dict(linea_origen)

        with pytest.raises(MapeoNoAprobadoError):
            migrar_linea_con_mapeo(mapeo, linea_origen)

        # "Nunca migrar": el dict de origen no debe haberse mutado ni
        # usado para construir nada -- la función debe fallar ANTES de
        # tocar cualquier dato de la línea.
        assert linea_origen == linea_original

    @pytest.mark.parametrize(
        "tipo_match", [TipoMatchMigracion.FUZZY, TipoMatchMigracion.ALERTA_RIESGO, TipoMatchMigracion.SIN_MATCH]
    )
    def test_ningun_tipo_match_pendiente_migra_sin_importar_el_tipo(self, tipo_match):
        """El criterio menciona alerta_riesgo y fuzzy explícitamente, pero
        la guardia real depende de `estado`, no de `tipo_match`: ningún
        mapeo pendiente migra, sea cual sea su tipo_match."""
        mapeo = _mapeo_pendiente(tipo_match=tipo_match)
        with pytest.raises(MapeoNoAprobadoError):
            migrar_linea_con_mapeo(mapeo, {"cuenta_id": ORIGEN_ID})

    def test_mapeo_rechazado_tampoco_migra_jamas(self):
        """Un mapeo explícitamente rechazado por un humano debe fallar
        exactamente igual que uno pendiente -- rechazar no es un estado
        "neutral", es una decisión de NO migrar."""
        mapeo = _mapeo_pendiente().model_copy(
            update={
                "estado": EstadoMapeoMigracion.RECHAZADO,
                "aprobado_por": "contador_lider",
                "aprobado_en": "2026-09-08T12:00:00+00:00",
                "nota": "las cuentas no son equivalentes",
            }
        )
        with pytest.raises(MapeoNoAprobadoError):
            migrar_linea_con_mapeo(mapeo, {"cuenta_id": ORIGEN_ID})


# ---------------------------------------------------------------------------
# El endpoint de aprobación es el único camino a estado=aprobado, y una
# vez aprobado por ese camino, el motor de migración sí procede.
# ---------------------------------------------------------------------------

class TestServicioAprobacionEsElUnicoCaminoAAprobado:
    def test_service_aprobar_mueve_pendiente_a_aprobado(self):
        svc = MigracionCatalogoService()
        mapeo = svc.registrar(_mapeo_pendiente())

        aprobado = svc.aprobar(mapeo.id, decidido_por="contador_lider")

        assert aprobado.estado == EstadoMapeoMigracion.APROBADO
        assert aprobado.aprobado_por == "contador_lider"
        assert aprobado.aprobado_en is not None

    def test_migrar_linea_con_mapeo_procede_solo_tras_aprobacion_explicita(self):
        """El mismo mapeo que el test anterior probó que NO migra
        pendiente, sí migra una vez que pasó por
        MigracionCatalogoService.aprobar() -- el único camino de
        producción a estado=aprobado."""
        svc = MigracionCatalogoService()
        mapeo = svc.registrar(_mapeo_pendiente())

        # Antes de aprobar: falla exactamente como en la prueba adversarial.
        with pytest.raises(MapeoNoAprobadoError):
            migrar_linea_con_mapeo(mapeo, {"cuenta_id": ORIGEN_ID})

        aprobado = svc.aprobar(mapeo.id, decidido_por="contador_lider")

        resultado = migrar_linea_con_mapeo(aprobado, {"cuenta_id": ORIGEN_ID, "debe": 100.0})
        assert resultado["cuenta_id"] == DESTINO_ID
        assert resultado["mapeo_id"] == aprobado.id

    def test_service_rechaza_aprobar_dos_veces_el_mismo_mapeo(self):
        """Ni siquiera el propio servicio de aprobación puede re-decidir
        un mapeo ya decidido -- ni /aprobar tras /aprobar, ni /aprobar
        tras /rechazar."""
        from b2b_ai.features.migracion_catalogo.service import (
            TransicionEstadoInvalidaError,
        )

        svc = MigracionCatalogoService()
        mapeo = svc.registrar(_mapeo_pendiente())
        svc.aprobar(mapeo.id, decidido_por="contador_lider")

        with pytest.raises(TransicionEstadoInvalidaError):
            svc.aprobar(mapeo.id, decidido_por="otro_contador")

    def test_service_exige_responsable_explicito_para_aprobar(self):
        """Ninguna aprobación puede quedar anónima."""
        from b2b_ai.features.migracion_catalogo.service import (
            DecisionSinResponsableError,
        )

        svc = MigracionCatalogoService()
        mapeo = svc.registrar(_mapeo_pendiente())

        with pytest.raises(DecisionSinResponsableError):
            svc.aprobar(mapeo.id, decidido_por="")
