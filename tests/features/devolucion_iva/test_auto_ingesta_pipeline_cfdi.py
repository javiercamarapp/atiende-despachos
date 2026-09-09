# -*- coding: utf-8 -*-
"""
test_auto_ingesta_pipeline_cfdi.py

Gap de auditoría (2026-09): todos los endpoints/funciones del módulo de
devolución de IVA recibían `facturas_json`/`diot_json`/`declaraciones_json`
armados a mano por quien llama -- nunca se conectaban solos a los CFDIs YA
parseados y validados por el pipeline real
(`b2b_ai.services.pipeline.process_file`, `b2b_ai/cfdi/parser.py`).

Prueba de integración real (sin mocks): procesa 3 CFDIs reales (fixtures
del repo, `fixtures/cfdis/`) a través del pipeline real -- parse, validate,
classify, ERP, persistencia en la tabla `invoices` -- y luego corre la
auto-ingesta de devolución de IVA para ese mismo tenant/periodo, sin que el
test construya un solo `FacturaCFDI`/`facturas_json` a mano. Confirma que
el papel de trabajo generado refleja esos 3 CFDIs reales.
"""
from __future__ import annotations

from b2b_ai.db.db import Database
from b2b_ai.features.devolucion_iva.service import (
    DevolucionIVAService,
    auto_ingestar_facturas,
)
from b2b_ai.features.devolucion_iva.workpaper import WorkpaperGenerator
from b2b_ai.services.pipeline import process_file


class TestAutoIngestaDesdePipelineReal:
    def test_auto_ingesta_arma_facturas_desde_cfdis_procesados_por_el_pipeline(
        self, tmp_path, sample_papeleria, sample_consultoria, sample_honorarios,
    ):
        db = Database(str(tmp_path / "auto_ingesta.db"))
        tenant_id = db.create_tenant("Despacho Auto-Ingesta Test")

        # 1. Procesar 3 CFDIs REALES a través del pipeline real. Nada de
        #    esto lo toca el módulo de devolución de IVA.
        r1 = process_file(sample_papeleria, db=db, tenant_id=tenant_id)
        r2 = process_file(sample_consultoria, db=db, tenant_id=tenant_id)
        r3 = process_file(sample_honorarios, db=db, tenant_id=tenant_id)
        assert r1["insertado"] and r2["insertado"] and r3["insertado"]
        assert db.count_invoices(tenant_id=tenant_id) == 3

        uuids_reales = {
            r1["datos"]["folio_fiscal"],
            r2["datos"]["folio_fiscal"],
            r3["datos"]["folio_fiscal"],
        }
        assert all(uuids_reales)  # ningún UUID vacío

        periodo = r1["datos"]["fecha"][:7]  # p.ej. "2026-07"
        assert periodo == r2["datos"]["fecha"][:7] == r3["datos"]["fecha"][:7]

        # 2. Auto-ingesta de devolución de IVA: SIN facturas_json, SIN que
        #    el test construya un solo FacturaCFDI a mano -- solo
        #    tenant_id + periodo, reutilizando lo ya parseado/persistido.
        svc = DevolucionIVAService(db=db)
        facturas = svc.auto_ingestar_facturas(tenant_id=tenant_id, periodo=periodo)

        assert len(facturas) == 3
        assert {f.uuid for f in facturas} == uuids_reales

        # El concepto real del CFDI (Conceptos/Descripcion -- gap #1 de
        # esta misma auditoría) también llega vía auto-ingesta, intacto.
        assert all(f.concepto for f in facturas)
        conceptos_reales = {r["datos"]["descripcion"] for r in (r1, r2, r3)}
        assert {f.concepto for f in facturas} == conceptos_reales

        # 3. El papel de trabajo generado con esas facturas auto-ingeridas
        #    refleja los 3 CFDIs reales.
        diot_entries = svc.generar_diot(facturas)
        wp = WorkpaperGenerator().generate(
            periodo=periodo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=[],
            tenant_id=str(tenant_id),
        )

        assert wp["secciones"]["1_resumen_periodo"]["resumen_facturas"]["total_facturas"] == 3
        assert wp["metadata"]["total_facturas"] == 3

        # Los folios fiscales de las 3 facturas reales aparecen en el
        # desglose de proveedores DIOT (sección 2).
        folios_en_papel = set()
        for proveedor in wp["secciones"]["2_diot_por_proveedor"]["proveedores"]:
            folios_en_papel.update(proveedor["folios_fiscales"])
        assert folios_en_papel == uuids_reales

    def test_auto_ingesta_filtra_por_periodo(self, tmp_path, sample_papeleria):
        """Un período sin CFDIs reales no debe traer nada -- nunca se
        inventan facturas para completar el período pedido."""
        db = Database(str(tmp_path / "auto_ingesta_periodo.db"))
        tenant_id = db.create_tenant("Despacho Auto-Ingesta Periodo")

        r1 = process_file(sample_papeleria, db=db, tenant_id=tenant_id)
        periodo_real = r1["datos"]["fecha"][:7]

        otro_periodo = "1999-01"
        assert otro_periodo != periodo_real

        assert auto_ingestar_facturas(db, tenant_id, otro_periodo) == []

        facturas_periodo_real = auto_ingestar_facturas(db, tenant_id, periodo_real)
        assert len(facturas_periodo_real) == 1
        assert facturas_periodo_real[0].uuid == r1["datos"]["folio_fiscal"]

    def test_auto_ingesta_aisla_por_tenant(
        self, tmp_path, sample_papeleria, sample_consultoria,
    ):
        """Los CFDIs de un tenant nunca aparecen en la auto-ingesta de otro."""
        db = Database(str(tmp_path / "auto_ingesta_tenant.db"))
        tenant_a = db.create_tenant("Despacho A")
        tenant_b = db.create_tenant("Despacho B")

        r_a = process_file(sample_papeleria, db=db, tenant_id=tenant_a)
        r_b = process_file(sample_consultoria, db=db, tenant_id=tenant_b)
        periodo = r_a["datos"]["fecha"][:7]
        assert periodo == r_b["datos"]["fecha"][:7]

        facturas_a = auto_ingestar_facturas(db, tenant_a, periodo)
        facturas_b = auto_ingestar_facturas(db, tenant_b, periodo)

        assert {f.uuid for f in facturas_a} == {r_a["datos"]["folio_fiscal"]}
        assert {f.uuid for f in facturas_b} == {r_b["datos"]["folio_fiscal"]}

    def test_modo_manual_sigue_disponible_como_fallback(self, sample_papeleria):
        """El modo manual (pasar `facturas` explícitas) sigue funcionando
        igual que antes -- la auto-ingesta es una vía adicional, no un
        reemplazo obligatorio."""
        from b2b_ai.cfdi.parser import parse_cfdi
        from b2b_ai.features.devolucion_iva.models import FacturaCFDI, TipoFactura

        datos = parse_cfdi(sample_papeleria)
        factura_manual = FacturaCFDI(
            uuid=datos["folio_fiscal"],
            rfc_emisor=datos["emisor_rfc"],
            rfc_receptor=datos["receptor_rfc"],
            fecha=datos["fecha"][:10],
            subtotal=float(datos["subtotal"]),
            iva=float(datos["iva"]),
            total=float(datos["total"]),
            tipo=TipoFactura.INGRESO,
            concepto=datos["descripcion"],
        )

        svc = DevolucionIVAService()
        facturas = svc.recopilar_facturas([factura_manual], periodo=datos["fecha"][:7])

        assert len(facturas) == 1
        assert facturas[0].uuid == datos["folio_fiscal"]
        assert facturas[0].concepto == datos["descripcion"]
