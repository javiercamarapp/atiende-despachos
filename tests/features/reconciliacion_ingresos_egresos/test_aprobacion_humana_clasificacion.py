# -*- coding: utf-8 -*-
"""
REQ-IVA-013 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA / conciliación de ingresos y egresos).

Criterio de aceptación exacto:
  "Cada clasificación de depósito no trivial (financiamiento/aportación/
  garantía) debe registrar `clasificado_por` y `clasificado_en`
  (timestamp), y el motor de reglas por regex debe marcarse siempre como
  `origen="automatico_sugerido"`, nunca `"aprobado"`, hasta que un humano
  confirme vía `PATCH /clasificaciones/{id}/aprobar`."

Esta es la salvaguarda explícita del ADR-4 (nunca aplicar la presunción
del Art. 59 fracc. III CFF por cuenta propia): ninguna clasificación
automática de primera pasada puede convertirse en una determinación
fiscal firme sin que un humano la confirme explícitamente.

Sin el fix, `ClasificacionDepositoResult` no tenía ni `id`, ni `origen`,
ni `clasificado_por`/`clasificado_en`/`aprobado_por`/`aprobado_en`, y no
existía ningún camino (ni de servicio ni HTTP) para "aprobar" una
clasificación — el estado quedaba implícitamente indefinido, sin
distinguir jamás una sugerencia automática de una determinación
confirmada por un humano.

Este archivo cubre dos niveles, sin mocks del código bajo prueba:
  1. Servicio (`ReconciliacionIngresosEgresosService`) directo — unit +
     adversarial: qué produce el motor de reglas, y qué hace
     `aprobar_clasificacion()`.
  2. Router HTTP real (FastAPI TestClient) — integration — ejercitando
     POST /clasificar y PATCH /clasificaciones/{id}/aprobar tal como los
     vería un cliente real, con una dependencia de auth fake que fija el
     tenant_id/user_id del token (mismo patrón que
     tests/adversarial/test_devolucion_iva_payload_tenant_mismatch.py).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    ClasificacionDeposito,
    DepositoBancario,
    OrigenClasificacion,
    ORIGEN_MOTOR_REGLAS,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.routes import (
    build_reconciliacion_ingresos_egresos_router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deposito(**overrides) -> DepositoBancario:
    defaults = dict(
        id="DEP-001",
        fecha="2026-06-15",
        monto=100000.0,
        descripcion="Pago cliente",
        referencia="CFDI-ABC-001",
        banco="BBVA",
        cuenta="0123456789",
        es_credito=True,
    )
    defaults.update(overrides)
    return DepositoBancario(**defaults)


DEPOSITOS_NO_TRIVIALES = [
    _make_deposito(id="DEP-FIN", descripcion="Depósito de préstamo bancario", referencia="LOAN-001"),
    _make_deposito(id="DEP-APORT", descripcion="Aportación de socio Juan Pérez", referencia="APORT-001"),
    _make_deposito(id="DEP-GAR", descripcion="Depósito en garantía arrendamiento", referencia="GAR-001"),
]

DEPOSITOS_TRIVIALES = [
    _make_deposito(id="DEP-ING", referencia="CFDI-ABC-002"),
    _make_deposito(id="DEP-OTRO", descripcion="Transferencia genérica", referencia="TXF-002"),
]


def _auth_for(tenant_id, user_id="contador_1"):
    async def _dep():
        return {"key": "test-key", "tenant_id": tenant_id, "user_id": user_id}
    return _dep


def _client(tenant_id="tenant_A", user_id="contador_1"):
    router = build_reconciliacion_ingresos_egresos_router(
        db=None, require_api_key=_auth_for(tenant_id, user_id)
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Servicio: qué produce el motor de reglas
# ---------------------------------------------------------------------------

class TestMotorSiempreAutomaticoSugerido:
    """El motor de reglas por regex NUNCA produce 'aprobado' directamente."""

    @pytest.mark.parametrize("dep", DEPOSITOS_NO_TRIVIALES + DEPOSITOS_TRIVIALES)
    def test_clasificacion_recien_creada_es_automatico_sugerido(self, dep):
        """Cualquier clasificación que sale del motor nace en automatico_sugerido."""
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(dep, [])
        assert resultado.origen == OrigenClasificacion.AUTOMATICO_SUGERIDO
        assert resultado.origen.value == "automatico_sugerido"

    def test_motor_nunca_produce_aprobado_ni_via_clasificar_todos(self):
        """Adversarial: ningún resultado de clasificar_todos() es 'aprobado', jamás."""
        service = ReconciliacionIngresosEgresosService()
        resultados = service.clasificar_todos(
            DEPOSITOS_NO_TRIVIALES + DEPOSITOS_TRIVIALES, []
        )
        assert len(resultados) == 5
        assert all(r.origen != OrigenClasificacion.APROBADO for r in resultados)
        assert all(r.origen == OrigenClasificacion.AUTOMATICO_SUGERIDO for r in resultados)

    def test_alta_confianza_no_basta_para_aprobar_directamente(self):
        """Ni siquiera una regla de altísima confianza (0.95, CFDI-Ingreso)
        produce origen='aprobado' — la confianza del motor no sustituye la
        confirmación humana."""
        dep = _make_deposito(referencia="CFDI-999")
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(dep, [])
        assert resultado.confianza >= 0.9
        assert resultado.origen == OrigenClasificacion.AUTOMATICO_SUGERIDO


class TestClasificadoPorYEnNoTriviales:
    """financiamiento/aportación_socio/garantía deben registrar quién y cuándo."""

    @pytest.mark.parametrize("dep,tipo_esperado", [
        (DEPOSITOS_NO_TRIVIALES[0], ClasificacionDeposito.FINANCIAMIENTO),
        (DEPOSITOS_NO_TRIVIALES[1], ClasificacionDeposito.APORTACION_SOCIO),
        (DEPOSITOS_NO_TRIVIALES[2], ClasificacionDeposito.GARANTIA),
    ])
    def test_no_trivial_registra_clasificado_por_y_en(self, dep, tipo_esperado):
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(dep, [])
        assert resultado.clasificacion == tipo_esperado
        assert resultado.clasificado_por is not None
        assert resultado.clasificado_por == ORIGEN_MOTOR_REGLAS
        assert resultado.clasificado_en is not None
        assert resultado.clasificado_en != ""

    @pytest.mark.parametrize("dep", DEPOSITOS_TRIVIALES)
    def test_trivial_no_exige_clasificado_por_en(self, dep):
        """INGRESO/OTRO_NO_GRAVABLE no son el foco de REQ-IVA-013: el
        servicio los deja sin clasificado_por/clasificado_en (no aplica la
        obligación de evidencia documental de financiamiento/aportación/
        garantía)."""
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(dep, [])
        assert resultado.clasificacion in (
            ClasificacionDeposito.INGRESO, ClasificacionDeposito.OTRO_NO_GRAVABLE,
        )
        assert resultado.clasificado_por is None
        assert resultado.clasificado_en is None

    def test_cada_clasificacion_tiene_id_unico(self):
        service = ReconciliacionIngresosEgresosService()
        resultados = service.clasificar_todos(DEPOSITOS_NO_TRIVIALES, [])
        ids = [r.id for r in resultados]
        assert len(ids) == len(set(ids)) == 3
        assert all(isinstance(i, str) and i for i in ids)


# ---------------------------------------------------------------------------
# 2. Servicio: aprobar_clasificacion() — único camino a "aprobado"
# ---------------------------------------------------------------------------

class TestAprobarClasificacionServicio:

    def test_aprobar_clasificacion_cambia_origen_y_registra_aprobador(self):
        service = ReconciliacionIngresosEgresosService()
        dep = DEPOSITOS_NO_TRIVIALES[0]
        resultado = service.clasificar_deposito(dep, [])
        assert resultado.origen == OrigenClasificacion.AUTOMATICO_SUGERIDO

        aprobada = service.aprobar_clasificacion(
            resultado.id, aprobado_por="contador_maria"
        )
        assert aprobada.origen == OrigenClasificacion.APROBADO
        assert aprobada.origen.value == "aprobado"
        assert aprobada.aprobado_por == "contador_maria"
        assert aprobada.aprobado_en is not None

        # El clasificado_por/en originales del motor no se pisan.
        assert aprobada.clasificado_por == ORIGEN_MOTOR_REGLAS

    def test_get_clasificacion_refleja_la_aprobacion(self):
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(DEPOSITOS_NO_TRIVIALES[1], [])
        service.aprobar_clasificacion(resultado.id, aprobado_por="contador_x")

        recuperada = service.get_clasificacion(resultado.id)
        assert recuperada.origen == OrigenClasificacion.APROBADO

    def test_aprobar_clasificacion_inexistente_lanza_keyerror(self):
        service = ReconciliacionIngresosEgresosService()
        with pytest.raises(KeyError):
            service.aprobar_clasificacion("id-no-existe", aprobado_por="contador_x")

    def test_aprobar_clasificacion_dos_veces_lanza_valueerror(self):
        """La aprobación es una acción humana explícita de una sola vez,
        no una operación silenciosamente idempotente."""
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(DEPOSITOS_NO_TRIVIALES[2], [])
        service.aprobar_clasificacion(resultado.id, aprobado_por="contador_x")

        with pytest.raises(ValueError):
            service.aprobar_clasificacion(resultado.id, aprobado_por="contador_y")

    def test_aprobar_clasificacion_tenant_ajeno_lanza_keyerror(self):
        """Adversarial: aprobar con el tenant_id equivocado debe fallar
        exactamente igual que un id inexistente (no debe filtrar que la
        clasificación de otro tenant existe)."""
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(
            DEPOSITOS_NO_TRIVIALES[0], [], tenant_id="tenant_A"
        )
        with pytest.raises(KeyError):
            service.aprobar_clasificacion(
                resultado.id, aprobado_por="atacante", tenant_id="tenant_B"
            )
        # Sigue sin aprobar.
        assert service.get_clasificacion(resultado.id, tenant_id="tenant_A").origen == (
            OrigenClasificacion.AUTOMATICO_SUGERIDO
        )


# ---------------------------------------------------------------------------
# 3. Router HTTP real: POST /clasificar + PATCH /clasificaciones/{id}/aprobar
# ---------------------------------------------------------------------------

class TestEndpointAprobarClasificacionHTTP:

    def _clasificar(self, client, referencia="LOAN-777", descripcion="Depósito de préstamo bancario"):
        resp = client.post(
            "/api/v1/reconciliacion-ingresos/clasificar",
            json={
                "periodo": "2026-06",
                "depositos": [{
                    "id": "DEP-HTTP-1",
                    "fecha": "2026-06-10",
                    "monto": 50000.0,
                    "descripcion": descripcion,
                    "referencia": referencia,
                    "banco": "BBVA",
                    "cuenta": "0123456789",
                    "es_credito": True,
                }],
                "auxiliares": [],
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_clasificar_produce_automatico_sugerido_con_id(self):
        client = _client(tenant_id="tenant_http_A")
        body = self._clasificar(client)
        clasificaciones = body["clasificaciones"]
        assert len(clasificaciones) == 1
        clas = clasificaciones[0]

        assert clas["clasificacion"] == "financiamiento"
        assert clas["origen"] == "automatico_sugerido"
        assert clas["id"]
        assert clas["clasificado_por"] == ORIGEN_MOTOR_REGLAS
        assert clas["clasificado_en"] is not None
        assert clas["aprobado_por"] is None
        assert clas["aprobado_en"] is None

    def test_patch_aprobar_confirma_la_clasificacion(self):
        client = _client(tenant_id="tenant_http_A", user_id="contador_http")
        body = self._clasificar(client)
        clasificacion_id = body["clasificaciones"][0]["id"]

        resp = client.patch(
            f"/api/v1/reconciliacion-ingresos/clasificaciones/{clasificacion_id}/aprobar"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        clas = data["clasificacion"]
        assert clas["origen"] == "aprobado"
        assert clas["aprobado_por"] == "contador_http"
        assert clas["aprobado_en"] is not None

    def test_patch_aprobar_dos_veces_devuelve_409(self):
        client = _client(tenant_id="tenant_http_A")
        body = self._clasificar(client)
        clasificacion_id = body["clasificaciones"][0]["id"]

        path = f"/api/v1/reconciliacion-ingresos/clasificaciones/{clasificacion_id}/aprobar"
        first = client.patch(path)
        assert first.status_code == 200

        second = client.patch(path)
        assert second.status_code == 409

    def test_patch_aprobar_id_inexistente_devuelve_404(self):
        client = _client(tenant_id="tenant_http_A")
        resp = client.patch(
            "/api/v1/reconciliacion-ingresos/clasificaciones/id-fantasma/aprobar"
        )
        assert resp.status_code == 404

    def test_patch_aprobar_no_afecta_otras_clasificaciones(self):
        """Aprobar una clasificación no cambia el origen de las demás."""
        client = _client(tenant_id="tenant_http_A")
        resp = client.post(
            "/api/v1/reconciliacion-ingresos/clasificar",
            json={
                "periodo": "2026-06",
                "depositos": [
                    {
                        "id": "DEP-A", "fecha": "2026-06-10", "monto": 50000.0,
                        "descripcion": "Depósito de préstamo bancario",
                        "referencia": "LOAN-A", "banco": "BBVA", "cuenta": "001",
                        "es_credito": True,
                    },
                    {
                        "id": "DEP-B", "fecha": "2026-06-11", "monto": 20000.0,
                        "descripcion": "Aportación de socio",
                        "referencia": "APORT-B", "banco": "BBVA", "cuenta": "001",
                        "es_credito": True,
                    },
                ],
                "auxiliares": [],
            },
        )
        assert resp.status_code == 200, resp.text
        clasificaciones = resp.json()["clasificaciones"]
        assert len(clasificaciones) == 2
        id_a, id_b = clasificaciones[0]["id"], clasificaciones[1]["id"]

        client.patch(f"/api/v1/reconciliacion-ingresos/clasificaciones/{id_a}/aprobar")

        # Releer vía un segundo /clasificar del mismo depósito B no aplica
        # aquí (crearía una nueva clasificación); en su lugar, confirmamos
        # que aprobar B por separado sigue funcionando (B seguía en
        # automatico_sugerido, no fue tocado por la aprobación de A).
        resp_b = client.patch(f"/api/v1/reconciliacion-ingresos/clasificaciones/{id_b}/aprobar")
        assert resp_b.status_code == 200
        assert resp_b.json()["clasificacion"]["origen"] == "aprobado"
