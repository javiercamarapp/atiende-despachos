# -*- coding: utf-8 -*-
"""
test_concepto_desglose_proveedores.py

Gap de auditoría (2026-09): el módulo de devolución de IVA no capturaba el
campo "concepto" de la factura en ningún lado del modelo/exportación. El
dueño del despacho pidió explícitamente que el desglose de proveedores DIOT
incluya el concepto de la factura junto con folio fiscal/folio
factura/fecha de pago/banco.

Esta prueba confirma, de punta a punta y sin mocks, que `concepto` viaja
intacto:
  FacturaCFDI (entrada) → generar_diot() → DIOTEntry.facturas_detalle
      → WorkpaperGenerator.generate() sección 2 (desglose de proveedores)
      → WorkpaperGenerator.exportar_fed_anexo7() (anexo FED 7/7-A exportado)
"""
from __future__ import annotations

from b2b_ai.features.devolucion_iva.models import (
    ClasificacionIVA,
    DIOTFacturaDetalle,
    FacturaCFDI,
    TipoFactura,
)
from b2b_ai.features.devolucion_iva.service import generar_diot
from b2b_ai.features.devolucion_iva.workpaper import WorkpaperGenerator


CONCEPTO_A = "Servicios de consultoría en materia fiscal — junio 2026"
CONCEPTO_B = "Arrendamiento de oficinas — junio 2026"


def _factura(**overrides) -> FacturaCFDI:
    defaults = dict(
        uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        rfc_emisor="EMP850101AB1",
        nombre_emisor="Proveedor Uno S.A. de C.V.",
        rfc_receptor="REC850101CD2",
        fecha="2026-06-15",
        subtotal=10000.0,
        iva=1600.0,
        total=11600.0,
        tipo=TipoFactura.INGRESO,
        categoria=ClasificacionIVA.CREDITABLE_100,
        concepto=CONCEPTO_A,
        folio_factura="A-1042",
        fecha_pago="2026-06-20",
        banco_pago="BBVA",
        forma_pago="03",
    )
    defaults.update(overrides)
    return FacturaCFDI(**defaults)


class TestConceptoEnFacturaCFDI:
    def test_concepto_es_opcional_y_por_defecto_none(self):
        f = FacturaCFDI(
            uuid="u1", rfc_emisor="EMP850101AB1", rfc_receptor="REC850101CD2",
            fecha="2026-06-01", subtotal=100.0, iva=16.0, total=116.0,
        )
        assert f.concepto is None

    def test_concepto_se_guarda_tal_cual(self):
        f = _factura(concepto=CONCEPTO_A)
        assert f.concepto == CONCEPTO_A

    def test_concepto_cadena_vacia_es_rechazado(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _factura(concepto="   ")


class TestConceptoViajaHastaDIOTEntry:
    def test_generar_diot_propaga_concepto_en_facturas_detalle(self):
        entries = generar_diot([_factura()])

        assert len(entries) == 1
        detalle = entries[0].facturas_detalle
        assert len(detalle) == 1
        assert isinstance(detalle[0], DIOTFacturaDetalle)
        assert detalle[0].concepto == CONCEPTO_A
        assert detalle[0].folio_fiscal == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert detalle[0].folio_factura == "A-1042"
        assert detalle[0].fecha_pago == "2026-06-20"
        assert detalle[0].banco_pago == "BBVA"

    def test_dos_proveedores_conservan_cada_quien_su_concepto(self):
        facturas = [
            _factura(uuid="uuid-1", rfc_emisor="AAA850101AB1", concepto=CONCEPTO_A),
            _factura(uuid="uuid-2", rfc_emisor="BBB850101CD2", concepto=CONCEPTO_B,
                     folio_factura="B-2001"),
        ]
        entries = generar_diot(facturas)

        assert len(entries) == 2
        conceptos_por_rfc = {
            e.rfc_tercero: e.facturas_detalle[0].concepto for e in entries
        }
        assert conceptos_por_rfc["AAA850101AB1"] == CONCEPTO_A
        assert conceptos_por_rfc["BBB850101CD2"] == CONCEPTO_B


class TestConceptoEnDesgloseDeProveedoresDelPapelDeTrabajo:
    def test_seccion_2_incluye_concepto_por_factura(self):
        gen = WorkpaperGenerator()
        entries = generar_diot([_factura()])

        wp = gen.generate(
            periodo="2026-06",
            facturas=[_factura()],
            diot_entries=entries,
            declaraciones=[],
        )

        proveedores = wp["secciones"]["2_diot_por_proveedor"]["proveedores"]
        assert len(proveedores) == 1
        detalle = proveedores[0]["facturas_detalle"]
        assert len(detalle) == 1
        assert detalle[0]["concepto"] == CONCEPTO_A
        assert detalle[0]["folio_fiscal"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert detalle[0]["folio_factura"] == "A-1042"
        assert detalle[0]["fecha_pago"] == "2026-06-20"
        assert detalle[0]["banco_pago"] == "BBVA"


class TestConceptoEnExportacionFEDAnexo7:
    def test_concepto_viaja_intacto_de_entrada_a_salida_exportada(self):
        """REQ (auditoría): concepto de FacturaCFDI == concepto exportado."""
        gen = WorkpaperGenerator()
        f = _factura(concepto=CONCEPTO_A)

        filas = gen.exportar_fed_anexo7([f])

        assert len(filas) == 1
        assert filas[0]["concepto"] == f.concepto == CONCEPTO_A

    def test_concepto_viaja_intacto_al_csv_exportado(self):
        import csv
        import io

        gen = WorkpaperGenerator()
        f = _factura(concepto=CONCEPTO_A)

        csv_text = gen.exportar_fed_anexo7_csv([f])
        filas = list(csv.DictReader(io.StringIO(csv_text)))

        assert filas[0]["concepto"] == CONCEPTO_A

    def test_facturas_sin_concepto_rechazan_la_exportacion(self):
        import pytest

        gen = WorkpaperGenerator()
        f = _factura(concepto=None)

        with pytest.raises(ValueError, match="concepto"):
            gen.exportar_fed_anexo7([f])
