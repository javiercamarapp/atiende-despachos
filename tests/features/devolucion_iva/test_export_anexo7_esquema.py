# -*- coding: utf-8 -*-
"""
test_export_anexo7_esquema.py — REQ-IVA-014.

El FED (Formato Electrónico de Devoluciones) exportable debe incluir, por
cada línea de proveedor, los 9 campos mínimos del anexo 7/7-A: RFC,
nombre/razón social, folio fiscal, folio de factura, fecha de factura,
fecha de pago, forma de pago, banco de pago, IVA trasladado/acreditable —
más `concepto` (10º campo), agregado a petición explícita del dueño del
despacho para que el concepto de la factura viaje siempre junto con esos
otros datos en el desglose de proveedores/FED exportado. `concepto` NO es
parte de los 9 mínimos oficiales del SAT; es una extensión de este módulo.

Prueba de esquema: el JSON/CSV exportado debe tener exactamente esas 10
claves no nulas por fila.

Sin mocks: se instancian los modelos reales (pydantic v2) y se llama al
`WorkpaperGenerator` real.
"""
from __future__ import annotations

import csv
import io

import pytest

from b2b_ai.features.devolucion_iva.models import (
    ClasificacionIVA,
    FacturaCFDI,
    TipoFactura,
)
from b2b_ai.features.devolucion_iva.workpaper import (
    CAMPOS_FED_ANEXO7,
    WorkpaperGenerator,
)


CAMPOS_ESPERADOS = {
    "rfc",
    "nombre_razon_social",
    "folio_fiscal",
    "folio_factura",
    "concepto",
    "fecha_factura",
    "fecha_pago",
    "forma_pago",
    "banco_pago",
    "iva_trasladado_acreditable",
}


def _factura_completa_anexo7(**overrides) -> FacturaCFDI:
    """Una factura con los 10 datos requeridos para el anexo 7/7-A exportado."""
    defaults = dict(
        uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        rfc_emisor="EMP850101AB1",
        nombre_emisor="Proveedor Ejemplo S.A. de C.V.",
        rfc_receptor="REC850101CD2",
        fecha="2025-01-15",
        subtotal=10000.0,
        iva=1600.0,
        total=11600.0,
        tipo=TipoFactura.INGRESO,
        categoria=ClasificacionIVA.CREDITABLE_100,
        banco_pago="BBVA",
        fecha_pago="2025-01-20",
        folio_factura="A-1042",
        concepto="Servicios de consultoría administrativa",
        forma_pago="03",
    )
    defaults.update(overrides)
    return FacturaCFDI(**defaults)


class TestEsquemaExactoDeLasDiezClaves:
    def test_json_tiene_exactamente_las_10_claves_por_fila(self):
        gen = WorkpaperGenerator()
        filas = gen.exportar_fed_anexo7([_factura_completa_anexo7()])

        assert len(filas) == 1
        assert set(filas[0].keys()) == CAMPOS_ESPERADOS
        assert len(filas[0]) == 10

    def test_ninguna_clave_es_nula_en_el_json(self):
        gen = WorkpaperGenerator()
        filas = gen.exportar_fed_anexo7([_factura_completa_anexo7()])

        for clave, valor in filas[0].items():
            assert valor is not None, f"'{clave}' no debe ser nulo"
            if isinstance(valor, str):
                assert valor.strip() != "", f"'{clave}' no debe ser cadena vacía"

    def test_una_fila_por_factura(self):
        gen = WorkpaperGenerator()
        facturas = [
            _factura_completa_anexo7(uuid="uuid-1", folio_factura="A-1"),
            _factura_completa_anexo7(uuid="uuid-2", folio_factura="A-2", rfc_emisor="OTR850101XY9"),
        ]
        filas = gen.exportar_fed_anexo7(facturas)

        assert len(filas) == 2
        for fila in filas:
            assert set(fila.keys()) == CAMPOS_ESPERADOS

    def test_valores_provienen_de_los_campos_correctos_de_la_factura(self):
        gen = WorkpaperGenerator()
        f = _factura_completa_anexo7()
        fila = gen.exportar_fed_anexo7([f])[0]

        assert fila["rfc"] == f.rfc_emisor
        assert fila["nombre_razon_social"] == f.nombre_emisor
        assert fila["folio_fiscal"] == f.uuid
        assert fila["folio_factura"] == f.folio_factura
        assert fila["concepto"] == f.concepto
        assert fila["fecha_factura"] == f.fecha
        assert fila["fecha_pago"] == f.fecha_pago
        assert fila["forma_pago"] == f.forma_pago
        assert fila["banco_pago"] == f.banco_pago
        assert fila["iva_trasladado_acreditable"] == round(f.iva * f.proporcionalidad, 2)


class TestCsvTieneExactamenteLasDiezColumnas:
    def test_csv_header_tiene_exactamente_las_10_columnas(self):
        gen = WorkpaperGenerator()
        csv_text = gen.exportar_fed_anexo7_csv([_factura_completa_anexo7()])

        reader = csv.DictReader(io.StringIO(csv_text))
        assert set(reader.fieldnames) == CAMPOS_ESPERADOS
        assert len(reader.fieldnames) == 10

    def test_csv_filas_no_tienen_valores_vacios(self):
        gen = WorkpaperGenerator()
        csv_text = gen.exportar_fed_anexo7_csv([_factura_completa_anexo7()])

        reader = csv.DictReader(io.StringIO(csv_text))
        filas = list(reader)
        assert len(filas) == 1
        for clave, valor in filas[0].items():
            assert valor is not None
            assert valor.strip() != "", f"'{clave}' no debe venir vacío en el CSV"

    def test_campos_fed_anexo7_constante_coincide_con_el_esquema(self):
        assert set(CAMPOS_FED_ANEXO7) == CAMPOS_ESPERADOS
        assert len(CAMPOS_FED_ANEXO7) == 10


class TestRechazaExportacionConDatosFaltantes:
    """Nunca se exporta una fila con un campo nulo/vacío inventado."""

    @pytest.mark.parametrize("campo_a_quitar,override", [
        ("nombre_emisor", {"nombre_emisor": ""}),
        ("folio_factura", {"folio_factura": None}),
        ("concepto", {"concepto": None}),
        ("fecha_pago", {"fecha_pago": None}),
        ("forma_pago", {"forma_pago": None}),
        ("banco_pago", {"banco_pago": None}),
    ])
    def test_factura_incompleta_rechaza_toda_la_exportacion(self, campo_a_quitar, override):
        gen = WorkpaperGenerator()
        factura_incompleta = _factura_completa_anexo7(**override)

        with pytest.raises(ValueError, match="faltan campos"):
            gen.exportar_fed_anexo7([factura_incompleta])

    def test_mensaje_de_error_identifica_la_factura_y_el_campo_faltante(self):
        gen = WorkpaperGenerator()
        factura_incompleta = _factura_completa_anexo7(banco_pago=None)

        with pytest.raises(ValueError) as exc_info:
            gen.exportar_fed_anexo7([factura_incompleta])

        msg = str(exc_info.value)
        assert factura_incompleta.uuid in msg
        assert "banco_pago" in msg

    def test_una_factura_incompleta_entre_varias_rechaza_el_lote_completo(self):
        """No se exportan las filas buenas dejando fuera la mala en silencio."""
        gen = WorkpaperGenerator()
        facturas = [
            _factura_completa_anexo7(uuid="uuid-ok", folio_factura="A-1"),
            _factura_completa_anexo7(uuid="uuid-malo", folio_factura="A-2", banco_pago=None),
        ]

        with pytest.raises(ValueError):
            gen.exportar_fed_anexo7(facturas)


class TestIvaTrasladadoAcreditableNuncaEsNulo:
    def test_iva_cero_no_es_nulo_y_pasa_el_esquema(self):
        """0.0 es un valor legítimo (no un dato faltante): la fila igual exporta."""
        gen = WorkpaperGenerator()
        f = _factura_completa_anexo7(iva=0.0)
        fila = gen.exportar_fed_anexo7([f])[0]

        assert fila["iva_trasladado_acreditable"] == 0.0
        assert fila["iva_trasladado_acreditable"] is not None

    def test_proporcionalidad_parcial_se_refleja_en_el_monto(self):
        gen = WorkpaperGenerator()
        f = _factura_completa_anexo7(iva=1600.0, proporcionalidad=0.5)
        fila = gen.exportar_fed_anexo7([f])[0]

        assert fila["iva_trasladado_acreditable"] == 800.0
