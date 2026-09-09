# -*- coding: utf-8 -*-
"""
test_mapeo_n_a_1_y_1_a_n.py — REQ-MIG-008.

Criterio de aceptación exacto:
  "Un mapeo N:1 (varias cuentas origen apuntando al mismo
  `destino_cuenta_id`) debe requerir que el contador confirme
  explícitamente cómo se concilian los saldos (campo
  `estrategia_conciliacion_saldos` obligatorio no nulo antes de
  aprobar); un mapeo 1:N debe rechazarse por completo (HTTP 422,
  "división 1:N fuera de alcance automático")."

Sin mocks: se ejercita `MigracionCatalogoService` real (aprobar/editar)
y, para el requisito explícito de "HTTP 422", el router FastAPI real vía
`TestClient` -- mismo patrón que
`tests/features/migracion_catalogo/test_routes_aprobacion.py`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.routes import build_migracion_catalogo_router
from b2b_ai.features.migracion_catalogo.service import (
    DivisionUnoANoAutomaticaError,
    EstrategiaConciliacionRequeridaError,
    MigracionCatalogoService,
)

DESTINO_UNICO_ID = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
DESTINO_ALTERNO_ID = "11111111-2222-3333-4444-555555555555"
ORIGEN_A_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
ORIGEN_B_ID = "b2c3d4e5-f6a7-8901-bcde-f21345678901"
ORIGEN_C_ID = "c3d4e5f6-a7b8-9012-cdef-321456789012"


def _mapeo_pendiente(origen_id: str, destino_id: str) -> MapeoMigracionCuenta:
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_id,
        destino_cuenta_id=destino_id,
        tipo_match=TipoMatchMigracion.FUZZY,
        score=87.5,
        estado=EstadoMapeoMigracion.PENDIENTE,
    )


async def _auth_dep():
    return {"key": "test-key", "tenant_id": "T1", "user_id": "u1"}


def _client_con_service(service: MigracionCatalogoService) -> TestClient:
    router = build_migracion_catalogo_router(require_api_key=_auth_dep, service=service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# N:1 — varias cuentas origen hacia el mismo destino: exige
# estrategia_conciliacion_saldos explícita antes de aprobar.
# ---------------------------------------------------------------------------

class TestFusionNa1ExigeEstrategiaDeConciliacion:
    def test_aprobar_sin_estrategia_falla_cuando_hay_mas_de_un_origen_al_mismo_destino(self):
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_UNICO_ID))

        with pytest.raises(EstrategiaConciliacionRequeridaError):
            svc.aprobar(mapeo_a.id, decidido_por="contador_lider")

        # No se debe haber movido de PENDIENTE: un intento fallido no deja
        # el mapeo a medio decidir.
        assert svc.obtener(mapeo_a.id).estado == EstadoMapeoMigracion.PENDIENTE

    def test_aprobar_con_estrategia_vacia_o_solo_espacios_falla_igual(self):
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_UNICO_ID))

        with pytest.raises(EstrategiaConciliacionRequeridaError):
            svc.aprobar(
                mapeo_a.id,
                decidido_por="contador_lider",
                estrategia_conciliacion_saldos="   ",
            )

    def test_aprobar_con_estrategia_explicita_confirma_los_dos_mapeos_del_grupo(self):
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        mapeo_b = svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_UNICO_ID))

        aprobado_a = svc.aprobar(
            mapeo_a.id,
            decidido_por="contador_lider",
            estrategia_conciliacion_saldos="sumar saldos de A y B al corte del periodo",
        )
        assert aprobado_a.estado == EstadoMapeoMigracion.APROBADO
        assert aprobado_a.estrategia_conciliacion_saldos == (
            "sumar saldos de A y B al corte del periodo"
        )

        # El segundo mapeo del mismo grupo N:1 exige SU PROPIA estrategia
        # -- confirmar el primero no exime al segundo, cada decisión es
        # explícita e independiente.
        with pytest.raises(EstrategiaConciliacionRequeridaError):
            svc.aprobar(mapeo_b.id, decidido_por="contador_lider")

        aprobado_b = svc.aprobar(
            mapeo_b.id,
            decidido_por="contador_lider",
            estrategia_conciliacion_saldos="sumar saldos de A y B al corte del periodo",
        )
        assert aprobado_b.estado == EstadoMapeoMigracion.APROBADO

    def test_tercer_origen_al_mismo_destino_tambien_exige_estrategia(self):
        """La cardinalidad N:1 no se limita a pares: 3 orígenes hacia el
        mismo destino siguen siendo N:1."""
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_UNICO_ID))
        mapeo_c = svc.registrar(_mapeo_pendiente(ORIGEN_C_ID, DESTINO_UNICO_ID))

        with pytest.raises(EstrategiaConciliacionRequeridaError):
            svc.aprobar(mapeo_c.id, decidido_por="contador_lider")

        svc.aprobar(
            mapeo_a.id, decidido_por="contador_lider",
            estrategia_conciliacion_saldos="consolidar en la cuenta destino",
        )
        aprobado_c = svc.aprobar(
            mapeo_c.id,
            decidido_por="contador_lider",
            estrategia_conciliacion_saldos="consolidar en la cuenta destino",
        )
        assert aprobado_c.estado == EstadoMapeoMigracion.APROBADO

    def test_un_solo_origen_hacia_el_destino_nunca_exige_estrategia(self):
        """Caso de control: sin cardinalidad N:1 (un único origen hacia el
        destino), aprobar sin estrategia_conciliacion_saldos debe seguir
        funcionando exactamente como antes de REQ-MIG-008 (REQ-MIG-007)."""
        svc = MigracionCatalogoService()
        mapeo = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))

        aprobado = svc.aprobar(mapeo.id, decidido_por="contador_lider")
        assert aprobado.estado == EstadoMapeoMigracion.APROBADO
        assert aprobado.estrategia_conciliacion_saldos is None

    def test_rechazado_no_cuenta_para_la_cardinalidad_n_a_1(self):
        """Un mapeo RECHAZADO explícitamente ya no es parte del grupo N:1
        -- rechazar es una decisión humana de 'esta correspondencia no
        aplica', no un estado neutral."""
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        mapeo_b = svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_UNICO_ID))

        svc.rechazar(mapeo_b.id, decidido_por="contador_lider", nota="no aplica")

        # Ahora solo queda un origen activo hacia el destino: no es N:1.
        aprobado_a = svc.aprobar(mapeo_a.id, decidido_por="contador_lider")
        assert aprobado_a.estado == EstadoMapeoMigracion.APROBADO
        assert aprobado_a.estrategia_conciliacion_saldos is None

    def test_editar_hacia_un_destino_ya_ocupado_tambien_exige_estrategia(self):
        """editar() no es una puerta trasera: fusionar por esta vía exige
        la misma estrategia explícita que aprobar()."""
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.aprobar(mapeo_a.id, decidido_por="contador_lider")

        mapeo_b = svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_ALTERNO_ID))

        with pytest.raises(EstrategiaConciliacionRequeridaError):
            svc.editar(
                mapeo_b.id,
                decidido_por="contador_lider",
                destino_cuenta_id=DESTINO_UNICO_ID,
                nota="en realidad va a la misma cuenta que A",
            )

        editado = svc.editar(
            mapeo_b.id,
            decidido_por="contador_lider",
            destino_cuenta_id=DESTINO_UNICO_ID,
            nota="en realidad va a la misma cuenta que A",
            estrategia_conciliacion_saldos="sumar A y B en destino",
        )
        assert editado.estado == EstadoMapeoMigracion.EDITADO
        assert editado.destino_cuenta_id == DESTINO_UNICO_ID
        assert editado.estrategia_conciliacion_saldos == "sumar A y B en destino"


# ---------------------------------------------------------------------------
# 1:N — la misma cuenta origen hacia destinos distintos: rechazo total,
# sin excepción (HTTP 422, "división 1:N fuera de alcance automático").
# ---------------------------------------------------------------------------

class TestDivision1aNSeRechazaPorCompleto:
    def test_aprobar_cualquiera_de_los_dos_mapeos_en_conflicto_falla(self):
        svc = MigracionCatalogoService()
        mapeo_1 = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        mapeo_2 = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_ALTERNO_ID))

        with pytest.raises(DivisionUnoANoAutomaticaError) as exc_info:
            svc.aprobar(mapeo_1.id, decidido_por="contador_lider")
        assert "división 1:N fuera de alcance automático" in str(exc_info.value)

        with pytest.raises(DivisionUnoANoAutomaticaError) as exc_info2:
            svc.aprobar(mapeo_2.id, decidido_por="contador_lider")
        assert "división 1:N fuera de alcance automático" in str(exc_info2.value)

        # Ningún campo adicional lo autoriza -- ni siquiera con
        # estrategia_conciliacion_saldos declarada.
        with pytest.raises(DivisionUnoANoAutomaticaError):
            svc.aprobar(
                mapeo_1.id,
                decidido_por="contador_lider",
                estrategia_conciliacion_saldos="cualquier estrategia",
            )

        # Ninguno de los dos mapeos se movió de PENDIENTE.
        assert svc.obtener(mapeo_1.id).estado == EstadoMapeoMigracion.PENDIENTE
        assert svc.obtener(mapeo_2.id).estado == EstadoMapeoMigracion.PENDIENTE

    def test_editar_hacia_un_segundo_destino_para_el_mismo_origen_tambien_se_rechaza(self):
        svc = MigracionCatalogoService()
        mapeo_1 = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.aprobar(mapeo_1.id, decidido_por="contador_lider")

        mapeo_2 = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        with pytest.raises(DivisionUnoANoAutomaticaError):
            svc.editar(
                mapeo_2.id,
                decidido_por="contador_lider",
                destino_cuenta_id=DESTINO_ALTERNO_ID,
                nota="mover a otra cuenta destino",
            )

    def test_endpoint_http_aprobar_devuelve_422_con_el_mensaje_exacto(self):
        svc = MigracionCatalogoService()
        mapeo_1 = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_ALTERNO_ID))
        client = _client_con_service(svc)

        resp = client.post(
            f"/api/v1/migracion-catalogo/{mapeo_1.id}/aprobar",
            json={"decidido_por": "contador_lider"},
        )

        assert resp.status_code == 422, resp.text
        assert "división 1:N fuera de alcance automático" in resp.json()["detail"]
        assert svc.obtener(mapeo_1.id).estado == EstadoMapeoMigracion.PENDIENTE

    def test_endpoint_http_aprobar_n_a_1_devuelve_422_sin_estrategia_y_200_con_ella(self):
        svc = MigracionCatalogoService()
        mapeo_a = svc.registrar(_mapeo_pendiente(ORIGEN_A_ID, DESTINO_UNICO_ID))
        svc.registrar(_mapeo_pendiente(ORIGEN_B_ID, DESTINO_UNICO_ID))
        client = _client_con_service(svc)

        sin_estrategia = client.post(
            f"/api/v1/migracion-catalogo/{mapeo_a.id}/aprobar",
            json={"decidido_por": "contador_lider"},
        )
        assert sin_estrategia.status_code == 422, sin_estrategia.text

        con_estrategia = client.post(
            f"/api/v1/migracion-catalogo/{mapeo_a.id}/aprobar",
            json={
                "decidido_por": "contador_lider",
                "estrategia_conciliacion_saldos": "prorratear por antigüedad de saldo",
            },
        )
        assert con_estrategia.status_code == 200, con_estrategia.text
        data = con_estrategia.json()["data"]
        assert data["estado"] == "aprobado"
        assert data["estrategia_conciliacion_saldos"] == (
            "prorratear por antigüedad de saldo"
        )
