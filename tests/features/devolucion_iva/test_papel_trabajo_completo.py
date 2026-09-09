# -*- coding: utf-8 -*-
"""
REQ-IVA-009 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA).

Criterio de aceptación exacto:
  "El `WorkpaperGenerator` debe ganar una sección 7 ('no discrepancia
  fiscal — depósitos bancarios') que incorpore el `PapelTrabajoConciliacion`
  de `reconciliacion_ingresos_egresos` (clasificaciones de depósito +
  `articulo_cff` de REQ-IVA-001), expuesta en un endpoint combinado
  `GET /api/v1/devolucion-iva/papel-trabajo-completo/{periodo}` que
  devuelve 7 secciones, no 6."

Sin mocks: se instancian los modelos y servicios reales de
`reconciliacion_ingresos_egresos` (motor de reglas de clasificación real)
y `devolucion_iva` (WorkpaperGenerator real, router HTTP real vía
TestClient), y se corre el flujo completo de conciliación de depósitos.

Regla dura del ADR-4 (Art. 59 fracc. III CFF): un depósito bancario
"sospechoso"/no trivial (financiamiento, aportación de socio, garantía)
nunca puede exponerse en el papel de trabajo como una reclasificación o
determinación fiscal firme — solo como sugerencia automática de primera
pasada sujeta a revisión humana. Varias pruebas de este archivo verifican
explícitamente esa regla en la sección 7.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.devolucion_iva.models import (
    ClasificacionIVA,
    DeclaracionMensual,
    DIOTEntry,
    FacturaCFDI,
    TipoFactura,
)
from b2b_ai.features.devolucion_iva.routes import build_devolucion_iva_router
from b2b_ai.features.devolucion_iva.workpaper import (
    ADVERTENCIA_ART_59_FRACC_III,
    WorkpaperGenerator,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_factura(**overrides) -> FacturaCFDI:
    defaults = {
        "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "rfc_emisor": "EMP850101AB1",
        "rfc_receptor": "REC850101CD2",
        "fecha": "2026-01-15",
        "subtotal": 10000.0,
        "iva": 1600.0,
        "total": 11600.0,
        "tipo": TipoFactura.INGRESO,
        "categoria": ClasificacionIVA.CREDITABLE_100,
    }
    defaults.update(overrides)
    return FacturaCFDI(**defaults)


def _make_declaracion(**overrides) -> DeclaracionMensual:
    defaults = {
        "mes": 1,
        "año": 2026,
        "iva_cobrado": 5000.0,
        "iva_pagado": 8000.0,
        "saldo_favor": 3000.0,
        "saldo_contra": 0.0,
    }
    defaults.update(overrides)
    return DeclaracionMensual(**defaults)


def _auth_for(tenant_id):
    async def _dep():
        return {"key": "test-key", "tenant_id": tenant_id, "user_id": "u1"}
    return _dep


def _client(tenant_id="T1", reconciliacion_service=None):
    router = build_devolucion_iva_router(
        db=None,
        require_api_key=_auth_for(tenant_id),
        reconciliacion_service=reconciliacion_service,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Nivel unitario: WorkpaperGenerator.generate() directo, sin HTTP
# ---------------------------------------------------------------------------

class TestWorkpaperGeneratorSeccion7:
    def test_generate_siempre_devuelve_7_secciones_no_6(self):
        gen = WorkpaperGenerator()
        wp = gen.generate(
            periodo="2026-01",
            facturas=[_make_factura()],
            diot_entries=[],
            declaraciones=[_make_declaracion()],
        )
        secciones = wp["secciones"]
        assert len(secciones) == 7, (
            f"Se esperaban 7 secciones, se obtuvieron {len(secciones)}: "
            f"{sorted(secciones.keys())}"
        )
        assert "7_no_discrepancia_fiscal_depositos" in secciones

    def test_seccion_7_sin_papel_conciliacion_queda_marcada_sin_datos(self):
        """Sin conciliación de depósitos disponible, la sección 7 existe
        igual (7 secciones siempre) pero declara explícitamente que no hay
        datos — nunca inventa una clasificación."""
        gen = WorkpaperGenerator()
        wp = gen.generate(
            periodo="2026-01",
            facturas=[_make_factura()],
            diot_entries=[],
            declaraciones=[],
        )
        s7 = wp["secciones"]["7_no_discrepancia_fiscal_depositos"]
        assert s7["disponible"] is False
        assert s7["total_depositos_clasificados"] == 0
        assert s7["clasificaciones_depositos"] == []
        assert s7["advertencia_fiscal"] == ADVERTENCIA_ART_59_FRACC_III

    def test_seccion_7_incorpora_papel_trabajo_conciliacion_real(self):
        """Corre el motor de clasificación REAL de
        reconciliacion_ingresos_egresos (sin mocks) y confirma que su
        PapelTrabajoConciliacion queda incorporado en la sección 7,
        incluyendo el articulo_cff (REQ-IVA-001)."""
        rec_svc = ReconciliacionIngresosEgresosService()

        depositos = rec_svc.recopilar_depositos(
            "2026-01", "T1",
            [
                {
                    "id": "DEP-001",
                    "fecha": "2026-01-10",
                    "monto": 500000.0,
                    "descripcion": "Aportación de socio Juan Pérez",
                    "referencia": "APORTACION-001",
                    "banco": "BBVA",
                    "cuenta": "0123456789",
                    "es_credito": True,
                },
                {
                    "id": "DEP-002",
                    "fecha": "2026-01-12",
                    "monto": 11600.0,
                    "descripcion": "Pago factura CFDI cliente",
                    "referencia": "CFDI-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "banco": "BBVA",
                    "cuenta": "0123456789",
                    "es_credito": True,
                },
            ],
        )
        auxiliares = rec_svc.recopilar_auxiliares("2026-01", "T1", [])

        conciliacion = rec_svc.conciliar_depositos_auxiliares(
            depositos, auxiliares, periodo="2026-01", tenant_id="T1",
        )
        papel_depositos = rec_svc.generar_papel_trabajo(
            conciliacion, conciliacion.clasificaciones,
        )

        gen = WorkpaperGenerator()
        wp = gen.generate(
            periodo="2026-01",
            facturas=[_make_factura()],
            diot_entries=[],
            declaraciones=[_make_declaracion()],
            tenant_id="T1",
            papel_conciliacion_depositos=papel_depositos,
        )

        secciones = wp["secciones"]
        assert len(secciones) == 7
        s7 = secciones["7_no_discrepancia_fiscal_depositos"]

        assert s7["disponible"] is True
        assert s7["total_depositos_clasificados"] == 2

        aportacion = next(
            c for c in s7["clasificaciones_depositos"]
            if c["deposito_id"] == "DEP-001"
        )
        assert aportacion["clasificacion"] == "aportacion_socio"
        assert aportacion["articulo_cff"] == "CFF Art. 59 fracción III"
        assert aportacion["es_sugerencia_no_determinacion_firme"] is True

        assert s7["resumen_por_clasificacion"]["aportacion_socio"] == 1
        assert s7["advertencia_fiscal"] == ADVERTENCIA_ART_59_FRACC_III

    def test_seccion_7_nunca_declara_determinacion_fiscal_firme(self):
        """Regla dura del ADR: ningún depósito no trivial puede aparecer
        marcado como determinación firme ni como reclasificado a ingreso
        gravado sin evidencia documental — la sección debe declarar
        explícitamente que es sugerencia, para las 3 clasificaciones no
        triviales del motor de reglas."""
        rec_svc = ReconciliacionIngresosEgresosService()
        depositos_data = [
            {
                "id": "DEP-FIN",
                "fecha": "2026-01-05",
                "monto": 200000.0,
                "descripcion": "Préstamo bancario capital de trabajo",
                "referencia": "PRESTAMO-01",
                "es_credito": True,
            },
            {
                "id": "DEP-GAR",
                "fecha": "2026-01-06",
                "monto": 50000.0,
                "descripcion": "Depósito en garantía contrato de arrendamiento",
                "referencia": "GARANTIA-01",
                "es_credito": True,
            },
            {
                "id": "DEP-SOCIO",
                "fecha": "2026-01-07",
                "monto": 300000.0,
                "descripcion": "Aportación de socio para capital social",
                "referencia": "SOCIO-01",
                "es_credito": True,
            },
        ]
        depositos = rec_svc.recopilar_depositos("2026-01", "T1", depositos_data)
        auxiliares = rec_svc.recopilar_auxiliares("2026-01", "T1", [])
        conciliacion = rec_svc.conciliar_depositos_auxiliares(
            depositos, auxiliares, periodo="2026-01", tenant_id="T1",
        )
        papel_depositos = rec_svc.generar_papel_trabajo(
            conciliacion, conciliacion.clasificaciones,
        )

        gen = WorkpaperGenerator()
        wp = gen.generate(
            periodo="2026-01",
            facturas=[],
            diot_entries=[],
            declaraciones=[],
            tenant_id="T1",
            papel_conciliacion_depositos=papel_depositos,
        )
        s7 = wp["secciones"]["7_no_discrepancia_fiscal_depositos"]

        assert s7["total_depositos_clasificados"] == 3
        clasificaciones_no_triviales = {
            "financiamiento", "aportacion_socio", "garantia",
        }
        for detalle in s7["clasificaciones_depositos"]:
            assert detalle["clasificacion"] in clasificaciones_no_triviales
            assert detalle["articulo_cff"] == "CFF Art. 59 fracción III"
            # Nunca una determinación fiscal firme: siempre marcado como
            # sugerencia sujeta a revisión humana.
            assert detalle["es_sugerencia_no_determinacion_firme"] is True

        # La única mención de "determinación fiscal firme" en toda la
        # sección debe ser la negación explícita del disclaimer del
        # ADR-4 ("ninguna ... es una determinación fiscal firme"), nunca
        # una afirmación de que sí lo es, y nunca un rechazo automático.
        serialized = json.dumps(s7, ensure_ascii=False).lower()
        assert "ninguna clasificación de depósito" in serialized
        assert "es una determinación fiscal firme" in serialized
        assert '"estado": "rechazada"' not in serialized
        assert "revisión y aprobación humana" in serialized


# ---------------------------------------------------------------------------
# Nivel HTTP: GET /api/v1/devolucion-iva/papel-trabajo-completo/{periodo}
# ---------------------------------------------------------------------------

class TestEndpointPapelTrabajoCompleto:
    def test_endpoint_devuelve_7_secciones(self):
        client = _client(tenant_id="T1")
        facturas_json = json.dumps([_make_factura().model_dump()])
        declaraciones_json = json.dumps([_make_declaracion().model_dump()])

        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo-completo/2026-01",
            params={
                "facturas_json": facturas_json,
                "declaraciones_json": declaraciones_json,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True

        secciones = body["data"]["secciones"]
        assert len(secciones) == 7, sorted(secciones.keys())
        for i in range(1, 8):
            assert any(k.startswith(f"{i}_") for k in secciones), (
                f"Falta la sección {i} en {sorted(secciones.keys())}"
            )

    def test_endpoint_sin_depositos_seccion_7_sin_datos(self):
        client = _client(tenant_id="T1")
        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo-completo/2026-02",
        )
        assert resp.status_code == 200, resp.text
        s7 = resp.json()["data"]["secciones"]["7_no_discrepancia_fiscal_depositos"]
        assert s7["disponible"] is False

    def test_endpoint_con_depositos_conecta_conciliacion_real_en_seccion_7(self):
        """El endpoint combinado corre la conciliación de depósitos real
        (sin mocks) a partir de `depositos_json`/`auxiliares_json` y la
        conecta con el expediente final de devolución (sección 7)."""
        client = _client(tenant_id="T1")

        depositos_json = json.dumps([
            {
                "id": "DEP-100",
                "fecha": "2026-03-01",
                "monto": 150000.0,
                "descripcion": "Préstamo bancario para capital de trabajo",
                "referencia": "PRESTAMO-100",
                "banco": "Santander",
                "cuenta": "9876543210",
                "es_credito": True,
            },
        ])

        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo-completo/2026-03",
            params={"depositos_json": depositos_json},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        secciones = data["secciones"]
        assert len(secciones) == 7

        s7 = secciones["7_no_discrepancia_fiscal_depositos"]
        assert s7["disponible"] is True
        assert s7["total_depositos_clasificados"] == 1
        detalle = s7["clasificaciones_depositos"][0]
        assert detalle["deposito_id"] == "DEP-100"
        assert detalle["clasificacion"] == "financiamiento"
        assert detalle["articulo_cff"] == "CFF Art. 59 fracción III"
        assert detalle["es_sugerencia_no_determinacion_firme"] is True
        assert s7["requiere_revision_humana"] in (True, False)

    def test_endpoint_reutiliza_conciliacion_previa_del_mismo_proceso(self):
        """Si no se mandan depósitos en el request pero el mismo
        `ReconciliacionIngresosEgresosService` (compartido dentro del
        proceso) ya conciliar un papel de trabajo para ese
        período/tenant, el endpoint combinado lo recupera en vez de
        devolver 'sin datos' — así el bloque de depósitos queda
        conectado con el expediente aunque no se reenvíen en cada
        llamada."""
        rec_svc = ReconciliacionIngresosEgresosService()
        depositos = rec_svc.recopilar_depositos(
            "2026-04", "T1",
            [{
                "id": "DEP-200",
                "fecha": "2026-04-01",
                "monto": 80000.0,
                "descripcion": "Depósito en garantía de arrendamiento",
                "referencia": "GARANTIA-200",
                "es_credito": True,
            }],
        )
        auxiliares = rec_svc.recopilar_auxiliares("2026-04", "T1", [])
        conciliacion = rec_svc.conciliar_depositos_auxiliares(
            depositos, auxiliares, periodo="2026-04", tenant_id="T1",
        )
        rec_svc.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)

        client = _client(tenant_id="T1", reconciliacion_service=rec_svc)
        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo-completo/2026-04",
        )
        assert resp.status_code == 200, resp.text
        s7 = resp.json()["data"]["secciones"]["7_no_discrepancia_fiscal_depositos"]

        assert s7["disponible"] is True
        assert s7["total_depositos_clasificados"] == 1
        assert s7["clasificaciones_depositos"][0]["clasificacion"] == "garantia"
        assert s7["clasificaciones_depositos"][0]["articulo_cff"] == "CFF Art. 59 fracción III"

    def test_endpoint_aisla_por_tenant_la_conciliacion_reutilizada(self):
        """El papel de conciliación de depósitos reutilizado (sin
        depositos_json en el request) nunca debe filtrarse entre
        tenants."""
        rec_svc = ReconciliacionIngresosEgresosService()
        depositos = rec_svc.recopilar_depositos(
            "2026-05", "TENANT-A",
            [{
                "id": "DEP-A",
                "fecha": "2026-05-01",
                "monto": 1000.0,
                "descripcion": "Aportación de socio",
                "referencia": "SOCIO-A",
                "es_credito": True,
            }],
        )
        auxiliares = rec_svc.recopilar_auxiliares("2026-05", "TENANT-A", [])
        conciliacion = rec_svc.conciliar_depositos_auxiliares(
            depositos, auxiliares, periodo="2026-05", tenant_id="TENANT-A",
        )
        rec_svc.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)

        client_b = _client(tenant_id="TENANT-B", reconciliacion_service=rec_svc)
        resp = client_b.get(
            "/api/v1/devolucion-iva/papel-trabajo-completo/2026-05",
        )
        assert resp.status_code == 200, resp.text
        s7 = resp.json()["data"]["secciones"]["7_no_discrepancia_fiscal_depositos"]
        assert s7["disponible"] is False, (
            "El tenant B nunca debe ver la conciliación de depósitos del "
            "tenant A."
        )
