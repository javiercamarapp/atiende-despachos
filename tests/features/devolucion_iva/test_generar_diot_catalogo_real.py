# -*- coding: utf-8 -*-
"""
test_generar_diot_catalogo_real.py — Regression test for REQ-IVA-004.

`devolucion_iva/service.py::generar_diot()` used to hardcode
`tipo_operacion="01"`, a code that does not exist in the real DIOT
catalog. It must instead consume the shared `TipoOperacion` enum from
`b2b_ai/features/diot/models.py`.
"""
from __future__ import annotations

from b2b_ai.features.devolucion_iva.models import (
    ClasificacionIVA,
    FacturaCFDI,
    TipoFactura,
)
from b2b_ai.features.devolucion_iva.service import generar_diot
from b2b_ai.features.diot.models import TipoOperacion


def _factura_iva_16(**overrides) -> FacturaCFDI:
    """An invoice taxed at the standard 16% VAT rate."""
    defaults = {
        "uuid": "11111111-1111-1111-1111-111111111111",
        "rfc_emisor": "EMP850101AB1",
        "rfc_receptor": "REC850101CD2",
        "fecha": "2025-01-15",
        "subtotal": 10000.0,
        "iva": 1600.0,  # 16% of subtotal
        "total": 11600.0,
        "tipo": TipoFactura.INGRESO,
        "categoria": ClasificacionIVA.CREDITABLE_100,
    }
    defaults.update(overrides)
    return FacturaCFDI(**defaults)


class TestGenerarDiotCatalogoReal:
    def test_iva_16_produce_tipo_operacion_03(self):
        """A 16%-IVA invoice must yield tipo_operacion == '03', never '01'."""
        entries = generar_diot([_factura_iva_16()])

        assert len(entries) == 1
        assert entries[0].tipo_operacion == "03"
        assert entries[0].tipo_operacion != "01"

    def test_tipo_operacion_es_codigo_real_del_catalogo_diot(self):
        """The emitted code must be a real member of the shared DIOT enum."""
        entries = generar_diot([_factura_iva_16()])

        codigos_validos = {op.value for op in TipoOperacion}
        assert entries[0].tipo_operacion in codigos_validos

    def test_tipo_operacion_coincide_con_enum_gastos_general(self):
        """The value must trace back to TipoOperacion.GASTOS_GENERAL."""
        entries = generar_diot([_factura_iva_16()])

        assert entries[0].tipo_operacion == TipoOperacion.GASTOS_GENERAL.value

    def test_codigo_01_ya_no_se_hardcodea(self):
        """Regression guard: '01' must never be the emitted code again."""
        facturas = [
            _factura_iva_16(uuid="f1", rfc_emisor="AAA850101AB1"),
            _factura_iva_16(uuid="f2", rfc_emisor="BBB850101CD2", iva=2560.0, subtotal=16000.0),
        ]
        entries = generar_diot(facturas)

        assert len(entries) == 2
        for entry in entries:
            assert entry.tipo_operacion != "01"
            assert entry.tipo_operacion == "03"
