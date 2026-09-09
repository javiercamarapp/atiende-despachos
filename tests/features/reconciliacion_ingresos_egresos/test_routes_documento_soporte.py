# -*- coding: utf-8 -*-
"""
REQ-IVA-003 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA / conciliación de ingresos y egresos).

Criterio de aceptación exacto:
  "Debe existir un endpoint (`POST /api/v1/reconciliacion-ingresos-egresos/
  {id}/documento-soporte`) para adjuntar el documento (contrato de mutuo,
  acta de asamblea, contrato de garantía) a una clasificación ya hecha;
  sin ese adjunto, la clasificación queda en estado `pendiente_evidencia`
  y no puede incluirse en un papel de trabajo exportable."

Es el mecanismo operativo que hace cumplible REQ-IVA-002 (el modelo
`ClasificacionDepositoResult` gana `documento_soporte_id`, `fecha_documento`
y `estado_recaracterizacion` con los valores `vigente`/
`requiere_formalizacion`/`recaracterizado` — "pendiente_evidencia" en el
lenguaje de este criterio corresponde a `requiere_formalizacion`, el
estado que produce automáticamente `ClassificationEngine` mientras nadie
adjunta el documento real).

ADR-4 (docs/BLUEPRINT-AGENTES-FISCALES.md): un depósito "sospechoso"
nunca se reclasifica automáticamente como ingreso gravado sin evidencia
documental real; toda clasificación automática de primera pasada queda
marcada como sugerencia, nunca como determinación fiscal firme sin
adjuntar el documento real y, en última instancia, sin revisión humana.

Este archivo cubre tres niveles, sin mocks del código bajo prueba:
  1. Servicio (`ReconciliacionIngresosEgresosService.adjuntar_documento_soporte`)
     — unit + adversarial (tenant ajeno, id inexistente, campos vacíos).
  2. Servicio (`generar_papel_trabajo_exportable`) — la clasificación sin
     documento no puede incluirse en el papel de trabajo exportable, y sí
     puede una vez adjuntado el documento.
  3. Router HTTP real (FastAPI TestClient, sin mocks) — ejercitando
     POST /conciliar, GET /papel-trabajo/{periodo}/exportable y
     POST /api/v1/reconciliacion-ingresos-egresos/{id}/documento-soporte
     tal como los vería un cliente real, con una dependencia de auth fake
     que fija el tenant_id del token (mismo patrón que
     tests/adversarial/test_devolucion_iva_payload_tenant_mismatch.py y
     tests/features/reconciliacion_ingresos_egresos/
     test_aprobacion_humana_clasificacion.py).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    ClasificacionDeposito,
    DepositoBancario,
    EstadoRecaracterizacion,
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
        monto=200000.0,
        descripcion="Préstamo de socio según contrato de mutuo",
        referencia="LOAN-001",
        banco="BBVA",
        cuenta="0123456789",
        es_credito=True,
    )
    defaults.update(overrides)
    return DepositoBancario(**defaults)


DEPOSITO_FINANCIAMIENTO = _make_deposito(
    id="DEP-FIN", descripcion="Depósito de préstamo bancario", referencia="LOAN-001",
)
DEPOSITO_APORTACION = _make_deposito(
    id="DEP-APORT", descripcion="Aportación de socio Juan Pérez", referencia="APORT-001",
)
DEPOSITO_GARANTIA = _make_deposito(
    id="DEP-GAR", descripcion="Depósito en garantía arrendamiento", referencia="GAR-001",
)
DEPOSITO_INGRESO = _make_deposito(id="DEP-ING", referencia="CFDI-ABC-002")


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
# 1. Servicio: adjuntar_documento_soporte()
# ---------------------------------------------------------------------------

class TestAdjuntarDocumentoSoporteServicio:

    @pytest.mark.parametrize(
        "deposito,tipo_esperado",
        [
            (DEPOSITO_FINANCIAMIENTO, ClasificacionDeposito.FINANCIAMIENTO),
            (DEPOSITO_APORTACION, ClasificacionDeposito.APORTACION_SOCIO),
            (DEPOSITO_GARANTIA, ClasificacionDeposito.GARANTIA),
        ],
    )
    def test_adjuntar_documento_recaracteriza_la_clasificacion(self, deposito, tipo_esperado):
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(deposito, [])
        assert resultado.clasificacion == tipo_esperado
        # Sin documento: pendiente_evidencia (requiere_formalizacion) y no
        # persistible — este es el estado que el criterio de aceptación
        # describe como "pendiente_evidencia".
        assert resultado.estado_recaracterizacion == EstadoRecaracterizacion.REQUIERE_FORMALIZACION
        assert resultado.puede_persistirse() is False

        actualizada = service.adjuntar_documento_soporte(
            resultado.id,
            documento_soporte_id="DOC-100",
            fecha_documento="2026-05-01",
        )

        assert actualizada.documento_soporte_id == "DOC-100"
        assert actualizada.fecha_documento == "2026-05-01"
        assert actualizada.estado_recaracterizacion == EstadoRecaracterizacion.RECARACTERIZADO
        assert actualizada.puede_persistirse() is True

    def test_get_clasificacion_refleja_el_documento_adjuntado(self):
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(DEPOSITO_FINANCIAMIENTO, [])
        service.adjuntar_documento_soporte(
            resultado.id, documento_soporte_id="DOC-200", fecha_documento="2026-01-10"
        )
        recuperada = service.get_clasificacion(resultado.id)
        assert recuperada.documento_soporte_id == "DOC-200"
        assert recuperada.estado_recaracterizacion == EstadoRecaracterizacion.RECARACTERIZADO

    def test_ingreso_tambien_acepta_documento_pero_no_lo_exige(self):
        """INGRESO no exige documento de soporte, pero adjuntar uno no
        debe fallar (el endpoint no distingue por tipo antes de intentarlo;
        solo `estado_recaracterizacion` no se fuerza a 'recaracterizado')."""
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(DEPOSITO_INGRESO, [])
        assert resultado.puede_persistirse() is True

        actualizada = service.adjuntar_documento_soporte(
            resultado.id, documento_soporte_id="DOC-300", fecha_documento="2026-01-01"
        )
        assert actualizada.documento_soporte_id == "DOC-300"
        assert actualizada.puede_persistirse() is True

    def test_adjuntar_a_clasificacion_inexistente_lanza_keyerror(self):
        service = ReconciliacionIngresosEgresosService()
        with pytest.raises(KeyError):
            service.adjuntar_documento_soporte(
                "id-no-existe", documento_soporte_id="DOC-1", fecha_documento="2026-01-01"
            )

    def test_adjuntar_con_documento_soporte_id_vacio_lanza_valueerror(self):
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(DEPOSITO_FINANCIAMIENTO, [])
        with pytest.raises(ValueError, match="documento_soporte_id"):
            service.adjuntar_documento_soporte(
                resultado.id, documento_soporte_id="", fecha_documento="2026-01-01"
            )
        # No se corrompió el estado existente.
        assert service.get_clasificacion(resultado.id).documento_soporte_id is None

    def test_adjuntar_con_fecha_documento_vacia_lanza_valueerror(self):
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(DEPOSITO_APORTACION, [])
        with pytest.raises(ValueError, match="fecha_documento"):
            service.adjuntar_documento_soporte(
                resultado.id, documento_soporte_id="DOC-1", fecha_documento=""
            )

    def test_adjuntar_con_tenant_ajeno_lanza_keyerror(self):
        """Adversarial: no debe poder adjuntarse un documento a la
        clasificación de otro tenant — mismo criterio de aislamiento que
        `aprobar_clasificacion` (REQ-IVA-013): indistinguible de 'no
        existe', nunca revela la existencia de la clasificación ajena."""
        service = ReconciliacionIngresosEgresosService()
        resultado = service.clasificar_deposito(
            DEPOSITO_GARANTIA, [], tenant_id="tenant_A"
        )
        with pytest.raises(KeyError):
            service.adjuntar_documento_soporte(
                resultado.id,
                documento_soporte_id="DOC-ATACANTE",
                fecha_documento="2026-01-01",
                tenant_id="tenant_B",
            )
        # Sigue sin documento.
        recuperada = service.get_clasificacion(resultado.id, tenant_id="tenant_A")
        assert recuperada.documento_soporte_id is None
        assert recuperada.estado_recaracterizacion == EstadoRecaracterizacion.REQUIERE_FORMALIZACION


# ---------------------------------------------------------------------------
# 2. Servicio: generar_papel_trabajo_exportable() — núcleo del criterio
# ---------------------------------------------------------------------------

class TestPapelTrabajoExportable:

    def _conciliar(self, service, depositos, periodo="2026-06", tenant_id=None):
        conciliacion = service.conciliar_depositos_auxiliares(
            depositos, [], periodo=periodo, tenant_id=tenant_id
        )
        return service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)

    def test_papel_inexistente_devuelve_none_y_lista_vacia(self):
        service = ReconciliacionIngresosEgresosService()
        papel, excluidas = service.generar_papel_trabajo_exportable("2099-01")
        assert papel is None
        assert excluidas == []

    def test_clasificacion_sin_documento_queda_excluida_del_exportable(self):
        service = ReconciliacionIngresosEgresosService()
        self._conciliar(service, [DEPOSITO_FINANCIAMIENTO, DEPOSITO_INGRESO])

        papel_exportable, excluidas = service.generar_papel_trabajo_exportable("2026-06")

        assert papel_exportable is not None
        assert excluidas == ["DEP-FIN"]
        ids_incluidos = {c.deposito_id for c in papel_exportable.clasificaciones}
        assert "DEP-FIN" not in ids_incluidos
        assert "DEP-ING" in ids_incluidos

    def test_tras_adjuntar_documento_la_clasificacion_pasa_a_ser_exportable(self):
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares(
            [DEPOSITO_APORTACION], [], periodo="2026-07",
        )
        service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)
        clasificacion_id = conciliacion.clasificaciones[0].id

        _, excluidas_antes = service.generar_papel_trabajo_exportable("2026-07")
        assert excluidas_antes == ["DEP-APORT"]

        service.adjuntar_documento_soporte(
            clasificacion_id, documento_soporte_id="DOC-500", fecha_documento="2026-06-01"
        )

        papel_despues, excluidas_despues = service.generar_papel_trabajo_exportable("2026-07")
        assert excluidas_despues == []
        assert len(papel_despues.clasificaciones) == 1
        assert papel_despues.clasificaciones[0].estado_recaracterizacion == (
            EstadoRecaracterizacion.RECARACTERIZADO
        )

    def test_papel_original_no_se_muta_por_el_exportable(self):
        """`generar_papel_trabajo_exportable` no debe alterar el papel de
        trabajo original almacenado — devuelve una copia filtrada."""
        service = ReconciliacionIngresosEgresosService()
        self._conciliar(service, [DEPOSITO_GARANTIA])

        papel_exportable, _ = service.generar_papel_trabajo_exportable("2026-06")
        assert len(papel_exportable.clasificaciones) == 0

        papel_original = service.get_papel_trabajo("2026-06")
        assert len(papel_original.clasificaciones) == 1


# ---------------------------------------------------------------------------
# 3. Router HTTP real
# ---------------------------------------------------------------------------

class TestEndpointDocumentoSoporteHTTP:

    def _conciliar(self, client, deposito, periodo="2026-06"):
        resp = client.post(
            "/api/v1/reconciliacion-ingresos/conciliar",
            json={
                "periodo": periodo,
                "depositos": [deposito.model_dump()],
                "auxiliares": [],
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_conciliar_deja_financiamiento_en_pendiente_evidencia(self):
        client = _client(tenant_id="tenant_http_A")
        body = self._conciliar(client, DEPOSITO_FINANCIAMIENTO)
        clas = body["conciliacion"]["clasificaciones"][0]
        assert clas["clasificacion"] == "financiamiento"
        assert clas["estado_recaracterizacion"] == "requiere_formalizacion"
        assert clas["documento_soporte_id"] is None

    def test_exportable_excluye_clasificacion_pendiente_de_evidencia(self):
        client = _client(tenant_id="tenant_http_A")
        self._conciliar(client, DEPOSITO_FINANCIAMIENTO, periodo="2026-08")

        resp = client.get("/api/v1/reconciliacion-ingresos/papel-trabajo/2026-08/exportable")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["total_incluidas"] == 0
        assert data["total_excluidas"] == 1
        assert data["excluidas_por_evidencia_pendiente"] == ["DEP-FIN"]
        assert data["papel_trabajo_exportable"]["clasificaciones"] == []

    def test_post_documento_soporte_recaracteriza_y_vuelve_exportable(self):
        client = _client(tenant_id="tenant_http_A")
        body = self._conciliar(client, DEPOSITO_APORTACION, periodo="2026-09")
        clasificacion_id = body["conciliacion"]["clasificaciones"][0]["id"]

        resp = client.post(
            f"/api/v1/reconciliacion-ingresos-egresos/{clasificacion_id}/documento-soporte",
            json={"documento_soporte_id": "DOC-ACTA-01", "fecha_documento": "2026-08-15"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        clas = data["clasificacion"]
        assert clas["documento_soporte_id"] == "DOC-ACTA-01"
        assert clas["fecha_documento"] == "2026-08-15"
        assert clas["estado_recaracterizacion"] == "recaracterizado"

        exportable = client.get(
            "/api/v1/reconciliacion-ingresos/papel-trabajo/2026-09/exportable"
        )
        assert exportable.status_code == 200
        exportable_data = exportable.json()
        assert exportable_data["total_excluidas"] == 0
        assert exportable_data["total_incluidas"] == 1

    def test_post_documento_soporte_id_inexistente_devuelve_404(self):
        client = _client(tenant_id="tenant_http_A")
        resp = client.post(
            "/api/v1/reconciliacion-ingresos-egresos/id-fantasma/documento-soporte",
            json={"documento_soporte_id": "DOC-1", "fecha_documento": "2026-01-01"},
        )
        assert resp.status_code == 404

    def test_post_documento_soporte_id_vacio_devuelve_422(self):
        client = _client(tenant_id="tenant_http_A")
        body = self._conciliar(client, DEPOSITO_GARANTIA, periodo="2026-10")
        clasificacion_id = body["conciliacion"]["clasificaciones"][0]["id"]

        resp = client.post(
            f"/api/v1/reconciliacion-ingresos-egresos/{clasificacion_id}/documento-soporte",
            json={"documento_soporte_id": "", "fecha_documento": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_post_documento_soporte_campo_faltante_devuelve_422(self):
        """`documento_soporte_id` y `fecha_documento` son obligatorios en
        el body — omitirlos debe rechazarse con 422 (validación de
        FastAPI/Pydantic), nunca crear un documento sintético."""
        client = _client(tenant_id="tenant_http_A")
        body = self._conciliar(client, DEPOSITO_FINANCIAMIENTO, periodo="2026-11")
        clasificacion_id = body["conciliacion"]["clasificaciones"][0]["id"]

        resp = client.post(
            f"/api/v1/reconciliacion-ingresos-egresos/{clasificacion_id}/documento-soporte",
            json={"fecha_documento": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_post_documento_soporte_tenant_ajeno_devuelve_404(self):
        """Adversarial: un tenant no puede adjuntar un documento a una
        clasificación de otro tenant — el router HTTP real, no solo el
        servicio, debe bloquearlo."""
        client_a = _client(tenant_id="tenant_A_docs")
        body = self._conciliar(client_a, DEPOSITO_GARANTIA, periodo="2026-12")
        clasificacion_id = body["conciliacion"]["clasificaciones"][0]["id"]

        router_b = build_reconciliacion_ingresos_egresos_router(
            db=None, require_api_key=_auth_for("tenant_B_docs")
        )
        app_b = FastAPI()
        app_b.include_router(router_b)
        other_tenant_client = TestClient(app_b)

        # El servicio detrás de cada router es una instancia distinta (cada
        # llamada a build_reconciliacion_ingresos_egresos_router crea su
        # propio `ReconciliacionIngresosEgresosService()`), así que el
        # escenario adversarial real de "mismo servicio, tenant distinto"
        # se cubre a nivel de servicio arriba
        # (test_adjuntar_con_tenant_ajeno_lanza_keyerror). Aquí verificamos
        # que, incluso sobre una instancia sin ese id en absoluto, la
        # respuesta sigue siendo 404 (nunca 500 ni una creación implícita).
        resp = other_tenant_client.post(
            f"/api/v1/reconciliacion-ingresos-egresos/{clasificacion_id}/documento-soporte",
            json={"documento_soporte_id": "DOC-ATACANTE", "fecha_documento": "2026-01-01"},
        )
        assert resp.status_code == 404

    def test_exportable_periodo_inexistente_devuelve_404(self):
        client = _client(tenant_id="tenant_http_A")
        resp = client.get("/api/v1/reconciliacion-ingresos/papel-trabajo/2099-01/exportable")
        assert resp.status_code == 404

    def test_ingreso_siempre_exportable_sin_documento(self):
        client = _client(tenant_id="tenant_http_A")
        self._conciliar(client, DEPOSITO_INGRESO, periodo="2027-01")

        resp = client.get("/api/v1/reconciliacion-ingresos/papel-trabajo/2027-01/exportable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_incluidas"] == 1
        assert data["total_excluidas"] == 0
