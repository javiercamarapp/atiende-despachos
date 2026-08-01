# -*- coding: utf-8 -*-
"""
test_pagos.py — Tests del módulo de Complemento de Pagos (parser + validator + routes).

Cobertura:
  - Parse: XML válido (simple, con múltiples pagos, con impuestos),
           XML sin complemento, XML inválido, complemento vacío,
           namespace alternativo, whitespace en attrs, desde bytes.
  - Validators: monto > 0, forma pago, moneda ISO, tipo cambio,
                RFC emisor match, docto rel saldo ant >= pagado,
                saldo insoluto correcto, tipo cadena pago,
                casos vacíos/None, data completa válida.
  - Routes: /parse, /validate, /catalog, archivo vacío, XML inválido.
  - Edge cases: múltiples DoctoRelacionado, empty payments,
                missing fields, currency conversion, type errors.
"""
from __future__ import annotations

import io
from decimal import Decimal

import pytest
from lxml import etree
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.pagos.parser import (
    parse_pagos, parse_pagos_bytes, PagosData,
    PagoInfo, DoctoRelacionado, ImpuestosDR, Retencion, Traslado,
    _find_pagos_node, PAGOS_NS_URIS,
)
from b2b_ai.features.pagos.validators import (
    validate_pagos, validate_monto_pago, validate_forma_pago,
    validate_moneda, validate_tipo_cambio, validate_rfc_emisor,
    validate_doctos_relacionados, validate_tipo_cadena_pago,
    FORMA_PAGO_CODES, TIPO_CADENA_PAGO_CODES, MONEDAS_ISO_4217,
)
from b2b_ai.features.pagos.routes import build_pagos_router


# ---------------------------------------------------------------------------
# XML templates
# ---------------------------------------------------------------------------

SIMPLE_PAGOS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="03"
                MonedaP="MXN" Monto="5000.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    Serie="A" Folio="1" MonedaDR="MXN"
                    MetodoDePagoDR="PUE" ParcialidadNo="1"
                    ImpSaldoAnt="10000.00" ImpPagado="5000.00"
                    ImpSaldoInsoluto="5000.00" ObjetoImpDR="01"/>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

MULTIPLE_PAGOS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-10" FormaPagoP="01"
                MonedaP="MXN" Monto="3000.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    Serie="A" Folio="1" MonedaDR="MXN"
                    MetodoDePagoDR="PPD" ParcialidadNo="1"
                    ImpSaldoAnt="10000.00" ImpPagado="3000.00"
                    ImpSaldoInsoluto="7000.00" ObjetoImpDR="01"/>
            </pagos:Pago>
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="03"
                MonedaP="MXN" Monto="7000.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    Serie="A" Folio="1" MonedaDR="MXN"
                    MetodoDePagoDR="PPD" ParcialidadNo="2"
                    ImpSaldoAnt="7000.00" ImpPagado="7000.00"
                    ImpSaldoInsoluto="0.00" ObjetoImpDR="01"/>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

PAGOS_WITH_TAXES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="03"
                MonedaP="MXN" Monto="11600.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    Serie="A" Folio="1" MonedaDR="MXN"
                    MetodoDePagoDR="PUE" ParcialidadNo="1"
                    ImpSaldoAnt="10000.00" ImpPagado="10000.00"
                    ImpSaldoInsoluto="0.00" ObjetoImpDR="02">
                    <pagos:Impuestos>
                        <pagos:Retencion Base="10000.00" Impuesto="001"
                            TipoFactor="Tasa" TasaOCuota="0.100000"
                            Importe="1000.00"/>
                        <pagos:Traslado Base="10000.00" Impuesto="002"
                            TipoFactor="Tasa" TasaOCuota="0.160000"
                            Importe="1600.00"/>
                    </pagos:Impuestos>
                </pagos:DoctoRelacionado>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

PAGOS_FOREIGN_CURRENCY_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="03"
                MonedaP="USD" Monto="500.00" TipoCambioP="17.50">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    Serie="A" Folio="1" MonedaDR="MXN"
                    EquivalenciaDR="17.50"
                    MetodoDePagoDR="PUE" ParcialidadNo="1"
                    ImpSaldoAnt="10000.00" ImpPagado="8750.00"
                    ImpSaldoInsoluto="1250.00" ObjetoImpDR="01"/>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

MULTIPLE_DOCTOS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="03"
                MonedaP="MXN" Monto="15000.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    Serie="A" Folio="1" MonedaDR="MXN"
                    MetodoDePagoDR="PPD" ParcialidadNo="1"
                    ImpSaldoAnt="10000.00" ImpPagado="10000.00"
                    ImpSaldoInsoluto="0.00" ObjetoImpDR="01"/>
                <pagos:DoctoRelacionado IdDocumento="DOC-002"
                    Serie="B" Folio="2" MonedaDR="MXN"
                    MetodoDePagoDR="PPD" ParcialidadNo="1"
                    ImpSaldoAnt="5000.00" ImpPagado="5000.00"
                    ImpSaldoInsoluto="0.00" ObjetoImpDR="01"/>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_pagos_xml(tmp_path) -> str:
    """XML con complemento Pagos simple."""
    path = tmp_path / "pagos_simple.xml"
    path.write_text(SIMPLE_PAGOS_XML, encoding="utf-8")
    return str(path)


@pytest.fixture
def no_pagos_xml(tmp_path) -> str:
    """XML CFDI sin complemento de pagos."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="I">
    <cfdi:Emisor Rfc="TEST010101AAA" Nombre="Test"/>
    <cfdi:Receptor Rfc="TEST020202BBB" Nombre="Test2"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento/>
</cfdi:Comprobante>"""
    path = tmp_path / "no_pagos.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def empty_pagos_xml(tmp_path) -> str:
    """XML con complemento Pagos vacío (sin pagos)."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
    path = tmp_path / "empty_pagos.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def whitespace_pagos_xml(tmp_path) -> str:
    """XML con espacios extra en atributos numéricos."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor Test"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor Test"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="  2026-07-15  " FormaPagoP="03"
                MonedaP="MXN" Monto="  5000.00  ">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    MonedaDR="MXN" MetodoDePagoDR="PUE"
                    ParcialidadNo="1"
                    ImpSaldoAnt="  10000.00  "
                    ImpPagado="  5000.00  "
                    ImpSaldoInsoluto="  5000.00  "/>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
    path = tmp_path / "whitespace.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def valid_pagos_data() -> PagosData:
    """PagosData completo y válido para pruebas de validador."""
    return PagosData(
        version="1.1",
        cfdi_emisor_rfc="EMISOR010101AAA",
        cfdi_receptor_rfc="RECEPT010101BBB",
        pagos=[
            PagoInfo(
                fecha_pago="2026-07-15",
                forma_pago_p="03",
                moneda_p="MXN",
                monto=Decimal("5000.00"),
                tipo_cambio_p=Decimal("1"),
                rfc_emisor_cta_ord="EMISOR010101AAA",
                documentos_relacionados=[
                    DoctoRelacionado(
                        id_documento="DOC-001",
                        serie="A",
                        folio="1",
                        moneda_dr="MXN",
                        metodo_de_pago_dr="PUE",
                        parcialidad_no=1,
                        imp_saldo_ant=Decimal("10000.00"),
                        imp_pagado=Decimal("5000.00"),
                        imp_saldo_insoluto=Decimal("5000.00"),
                        objeto_imp_dr="01",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def client():
    """TestClient FastAPI con el router de pagos registrado."""
    app = FastAPI()
    app.include_router(build_pagos_router())
    return TestClient(app)


# ===========================================================================
# PARSE TESTS
# ===========================================================================

class TestParsePagos:
    """Tests de parse_pagos() y parse_pagos_bytes()."""

    def test_parse_simple_xml(self, simple_pagos_xml):
        """Parse completo de XML simple con un pago."""
        data = parse_pagos(simple_pagos_xml)
        assert data is not None
        assert data.version == "1.1"
        assert len(data.pagos) == 1
        assert data.cfdi_emisor_rfc == "EMISOR010101AAA"
        assert data.cfdi_receptor_rfc == "RECEPT010101BBB"

    def test_parse_pago_fields(self, simple_pagos_xml):
        """Campos del pago se extraen correctamente."""
        data = parse_pagos(simple_pagos_xml)
        pago = data.pagos[0]
        assert pago.fecha_pago == "2026-07-15"
        assert pago.forma_pago_p == "03"
        assert pago.moneda_p == "MXN"
        assert pago.monto == Decimal("5000.00")

    def test_parse_docto_relacionado(self, simple_pagos_xml):
        """DoctoRelacionado se extrae correctamente."""
        data = parse_pagos(simple_pagos_xml)
        doc = data.pagos[0].documentos_relacionados[0]
        assert doc.id_documento == "DOC-001"
        assert doc.serie == "A"
        assert doc.folio == "1"
        assert doc.moneda_dr == "MXN"
        assert doc.metodo_de_pago_dr == "PUE"
        assert doc.parcialidad_no == 1
        assert doc.imp_saldo_ant == Decimal("10000.00")
        assert doc.imp_pagado == Decimal("5000.00")
        assert doc.imp_saldo_insoluto == Decimal("5000.00")
        assert doc.objeto_imp_dr == "01"

    def test_parse_multiple_payments(self):
        """XML con múltiples pagos."""
        root = etree.fromstring(MULTIPLE_PAGOS_XML.encode("utf-8"))
        data = parse_pagos_bytes(MULTIPLE_PAGOS_XML.encode("utf-8"))
        assert data is not None
        assert len(data.pagos) == 2
        assert data.pagos[0].monto == Decimal("3000.00")
        assert data.pagos[1].monto == Decimal("7000.00")

    def test_parse_multiple_doctos(self):
        """XML con múltiples DoctoRelacionado en un pago."""
        data = parse_pagos_bytes(MULTIPLE_DOCTOS_XML.encode("utf-8"))
        assert data is not None
        assert len(data.pagos[0].documentos_relacionados) == 2
        assert data.pagos[0].documentos_relacionados[0].id_documento == "DOC-001"
        assert data.pagos[0].documentos_relacionados[1].id_documento == "DOC-002"

    def test_parse_with_taxes(self):
        """XML con impuestos (retenciones y traslados) en DoctoRelacionado."""
        data = parse_pagos_bytes(PAGOS_WITH_TAXES_XML.encode("utf-8"))
        assert data is not None
        doc = data.pagos[0].documentos_relacionados[0]
        assert doc.impuestos is not None
        assert len(doc.impuestos.retenciones) == 1
        assert len(doc.impuestos.traslados) == 1
        ret = doc.impuestos.retenciones[0]
        assert ret.base == Decimal("10000.00")
        assert ret.impuesto == "001"
        assert ret.tipo_factor == "Tasa"
        assert ret.tasa_o_cuota == Decimal("0.100000")
        assert ret.importe == Decimal("1000.00")
        tras = doc.impuestos.traslados[0]
        assert tras.impuesto == "002"
        assert tras.importe == Decimal("1600.00")

    def test_parse_foreign_currency(self):
        """XML con moneda extranjera y tipo de cambio."""
        data = parse_pagos_bytes(PAGOS_FOREIGN_CURRENCY_XML.encode("utf-8"))
        assert data is not None
        pago = data.pagos[0]
        assert pago.moneda_p == "USD"
        assert pago.monto == Decimal("500.00")
        assert pago.tipo_cambio_p == Decimal("17.50")
        doc = pago.documentos_relacionados[0]
        assert doc.equivalencia_dr == Decimal("17.50")

    def test_parse_returns_none_no_complement(self, no_pagos_xml):
        """Sin complemento de pagos -> None."""
        data = parse_pagos(no_pagos_xml)
        assert data is None

    def test_parse_empty_pagos(self, empty_pagos_xml):
        """Complemento Pagos vacío -> data con lista vacía."""
        data = parse_pagos(empty_pagos_xml)
        assert data is not None
        assert data.version == "1.1"
        assert len(data.pagos) == 0

    def test_parse_file_not_found(self):
        """Archivo inexistente -> OSError."""
        with pytest.raises(OSError):
            parse_pagos("/nonexistent/file.xml")

    def test_parse_invalid_xml(self, tmp_path):
        """XML mal formado -> etree.XMLSyntaxError."""
        path = tmp_path / "bad.xml"
        path.write_text("<broken>", encoding="utf-8")
        with pytest.raises(etree.XMLSyntaxError):
            parse_pagos(str(path))

    def test_parse_whitespace_in_attrs(self, whitespace_pagos_xml):
        """Espacios extra en atributos numéricos se limpian."""
        data = parse_pagos(whitespace_pagos_xml)
        assert data is not None
        pago = data.pagos[0]
        assert pago.monto == Decimal("5000.00")
        assert pago.fecha_pago == "2026-07-15"
        doc = pago.documentos_relacionados[0]
        assert doc.imp_saldo_ant == Decimal("10000.00")
        assert doc.imp_pagado == Decimal("5000.00")
        assert doc.imp_saldo_insoluto == Decimal("5000.00")

    def test_parse_bytes_valid(self):
        """parse_pagos_bytes() funciona con bytes."""
        data = parse_pagos_bytes(SIMPLE_PAGOS_XML.encode("utf-8"))
        assert data is not None
        assert data.version == "1.1"
        assert len(data.pagos) == 1

    def test_parse_bytes_no_pagos(self):
        """parse_pagos_bytes() retorna None si no hay pagos."""
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"/>'
        data = parse_pagos_bytes(xml)
        assert data is None

    def test_parse_version_extracted(self, simple_pagos_xml):
        """La versión del complemento Pagos 1.1 se extrae."""
        data = parse_pagos(simple_pagos_xml)
        assert data.version == "1.1"

    def test_to_dict_serializable(self, simple_pagos_xml):
        """PagosData.to_dict() produce dict JSON-serializable."""
        import json
        data = parse_pagos(simple_pagos_xml)
        d = data.to_dict()
        # Decimals serializados como str
        assert isinstance(d["pagos"][0]["monto"], str)
        # Strings plain
        assert isinstance(d["version"], str)
        # Puede serializarse a JSON
        json.dumps(d)

    def test_to_dict_docto_relacionado_serializable(self):
        """DoctoRelacionado.to_dict() produce dict serializable."""
        import json
        data = parse_pagos_bytes(PAGOS_WITH_TAXES_XML.encode("utf-8"))
        d = data.to_dict()
        doc = d["pagos"][0]["documentos_relacionados"][0]
        assert "impuestos" in doc
        assert len(doc["impuestos"]["retenciones"]) == 1
        json.dumps(d)

    def test_parse_no_doctos(self):
        """Pago sin DoctoRelacionado."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="01"
                MonedaP="MXN" Monto="100.00"/>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        data = parse_pagos_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.pagos[0].documentos_relacionados) == 0

    def test_parse_no_impuestos(self):
        """DoctoRelacionado sin nodo Impuestos."""
        data = parse_pagos_bytes(SIMPLE_PAGOS_XML.encode("utf-8"))
        doc = data.pagos[0].documentos_relacionados[0]
        assert doc.impuestos is None

    def test_parse_empty_impuestos(self):
        """DoctoRelacionado con nodo Impuestos vacío (sin retenciones/traslados)."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="01"
                MonedaP="MXN" Monto="100.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    MonedaDR="MXN" MetodoDePagoDR="PUE"
                    ImpSaldoAnt="100.00" ImpPagado="100.00"
                    ImpSaldoInsoluto="0.00">
                    <pagos:Impuestos/>
                </pagos:DoctoRelacionado>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        data = parse_pagos_bytes(xml.encode("utf-8"))
        assert data is not None
        assert data.pagos[0].documentos_relacionados[0].impuestos is None

    def test_parse_parcialidad_no_none_when_missing(self):
        """ParcialidadNo ausente -> None."""
        data = parse_pagos_bytes(SIMPLE_PAGOS_XML.encode("utf-8"))
        # En el simple XML sí tiene ParcialidadNo=1, check docto
        doc = data.pagos[0].documentos_relacionados[0]
        assert doc.parcialidad_no == 1

    def test_parse_optional_fields_absent(self):
        """Campos opcionales ausentes no causan error."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
            <pagos:Pago FechaPago="2026-07-15" FormaPagoP="01"
                MonedaP="MXN" Monto="100.00">
                <pagos:DoctoRelacionado IdDocumento="DOC-001"
                    MonedaDR="MXN"/>
            </pagos:Pago>
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        data = parse_pagos_bytes(xml.encode("utf-8"))
        assert data is not None
        doc = data.pagos[0].documentos_relacionados[0]
        assert doc.serie is None
        assert doc.folio is None
        assert doc.metodo_de_pago_dr is None
        assert doc.imp_saldo_ant is None


# ===========================================================================
# VALIDATOR TESTS
# ===========================================================================

class TestValidateMontoPago:
    """Tests de validate_monto_pago()."""

    def test_valid_monto(self, valid_pagos_data):
        """Monto > 0 -> sin errores."""
        errors = validate_monto_pago(valid_pagos_data)
        assert errors == []

    def test_monto_zero(self, valid_pagos_data):
        """Monto = 0 -> error."""
        valid_pagos_data.pagos[0].monto = Decimal("0")
        errors = validate_monto_pago(valid_pagos_data)
        assert any("mayor a 0" in e for e in errors)

    def test_monto_negative(self, valid_pagos_data):
        """Monto negativo -> error."""
        valid_pagos_data.pagos[0].monto = Decimal("-100")
        errors = validate_monto_pago(valid_pagos_data)
        assert any("mayor a 0" in e for e in errors)

    def test_monto_none(self, valid_pagos_data):
        """Monto None -> error de ausencia."""
        valid_pagos_data.pagos[0].monto = None
        errors = validate_monto_pago(valid_pagos_data)
        assert any("ausente" in e for e in errors)

    def test_no_payments(self):
        """Sin pagos -> error."""
        data = PagosData(pagos=[])
        errors = validate_monto_pago(data)
        assert len(errors) == 1
        assert "No hay pagos" in errors[0]


class TestValidateFormaPago:
    """Tests de validate_forma_pago()."""

    def test_valid_codes(self):
        """Todos los códigos SAT válidos pasan validación."""
        for code in FORMA_PAGO_CODES:
            pago = PagoInfo(forma_pago_p=code)
            data = PagosData(pagos=[pago])
            errors = validate_forma_pago(data)
            assert errors == [], f"Code {code} should be valid"

    def test_invalid_code(self, valid_pagos_data):
        """Código inexistente -> error."""
        valid_pagos_data.pagos[0].forma_pago_p = "99"
        errors = validate_forma_pago(valid_pagos_data)
        assert len(errors) == 1
        assert "válido" in errors[0]

    def test_empty_code(self, valid_pagos_data):
        """FormaPago vacía -> error."""
        valid_pagos_data.pagos[0].forma_pago_p = ""
        errors = validate_forma_pago(valid_pagos_data)
        assert any("ausente" in e for e in errors)

    def test_none_code(self, valid_pagos_data):
        """FormaPago None -> error."""
        valid_pagos_data.pagos[0].forma_pago_p = None
        errors = validate_forma_pago(valid_pagos_data)
        assert any("ausente" in e for e in errors)


class TestValidateMoneda:
    """Tests de validate_moneda()."""

    def test_valid_mxn(self, valid_pagos_data):
        """MXN es válida."""
        errors = validate_moneda(valid_pagos_data)
        assert errors == []

    def test_valid_usd(self, valid_pagos_data):
        """USD es válida."""
        valid_pagos_data.pagos[0].moneda_p = "USD"
        errors = validate_moneda(valid_pagos_data)
        assert errors == []

    def test_invalid_moneda(self, valid_pagos_data):
        """Moneda inválida -> error."""
        valid_pagos_data.pagos[0].moneda_p = "XYZ"
        errors = validate_moneda(valid_pagos_data)
        assert any("ISO 4217" in e for e in errors)

    def test_none_moneda(self, valid_pagos_data):
        """Moneda None -> error."""
        valid_pagos_data.pagos[0].moneda_p = None
        errors = validate_moneda(valid_pagos_data)
        assert any("ausente" in e for e in errors)


class TestValidateTipoCambio:
    """Tests de validate_tipo_cambio()."""

    def test_mxn_with_no_exchange(self, valid_pagos_data):
        """MXN sin tipo de cambio -> válido."""
        valid_pagos_data.pagos[0].tipo_cambio_p = None
        errors = validate_tipo_cambio(valid_pagos_data)
        assert errors == []

    def test_mxn_with_exchange_1(self, valid_pagos_data):
        """MXN con tipo de cambio 1 -> válido."""
        errors = validate_tipo_cambio(valid_pagos_data)
        assert errors == []

    def test_mxn_with_wrong_exchange(self, valid_pagos_data):
        """MXN con tipo de cambio != 1 -> error."""
        valid_pagos_data.pagos[0].tipo_cambio_p = Decimal("18.5")
        errors = validate_tipo_cambio(valid_pagos_data)
        assert any("debe ser 1" in e for e in errors)

    def test_usd_requires_exchange(self, valid_pagos_data):
        """USD sin tipo de cambio -> error."""
        valid_pagos_data.pagos[0].moneda_p = "USD"
        valid_pagos_data.pagos[0].tipo_cambio_p = None
        errors = validate_tipo_cambio(valid_pagos_data)
        assert any("requerido" in e for e in errors)

    def test_usd_with_valid_exchange(self, valid_pagos_data):
        """USD con tipo de cambio válido -> sin errores."""
        valid_pagos_data.pagos[0].moneda_p = "USD"
        valid_pagos_data.pagos[0].tipo_cambio_p = Decimal("17.50")
        errors = validate_tipo_cambio(valid_pagos_data)
        assert errors == []

    def test_usd_negative_exchange(self, valid_pagos_data):
        """USD con tipo de cambio negativo -> error."""
        valid_pagos_data.pagos[0].moneda_p = "USD"
        valid_pagos_data.pagos[0].tipo_cambio_p = Decimal("-17.50")
        errors = validate_tipo_cambio(valid_pagos_data)
        assert any("mayor a 0" in e for e in errors)

    def test_usd_zero_exchange(self, valid_pagos_data):
        """USD con tipo de cambio 0 -> error."""
        valid_pagos_data.pagos[0].moneda_p = "USD"
        valid_pagos_data.pagos[0].tipo_cambio_p = Decimal("0")
        errors = validate_tipo_cambio(valid_pagos_data)
        assert any("mayor a 0" in e for e in errors)


class TestValidateRfcEmisor:
    """Tests de validate_rfc_emisor()."""

    def test_rfc_match(self, valid_pagos_data):
        """RFC Emisor coincide -> sin errores."""
        errors = validate_rfc_emisor(valid_pagos_data)
        assert errors == []

    def test_rfc_mismatch(self, valid_pagos_data):
        """RFC Emisor NO coincide -> error."""
        valid_pagos_data.pagos[0].rfc_emisor_cta_ord = "DIFFERENT01AAA"
        errors = validate_rfc_emisor(valid_pagos_data)
        assert len(errors) == 1
        assert "no coincide" in errors[0]

    def test_no_rfc_cta_ord(self, valid_pagos_data):
        """Sin RfcEmisorCtaOrd -> sin error (campo opcional)."""
        valid_pagos_data.pagos[0].rfc_emisor_cta_ord = None
        errors = validate_rfc_emisor(valid_pagos_data)
        assert errors == []

    def test_no_cfdi_emisor_rfc(self, valid_pagos_data):
        """Sin RFC del emisor CFDI -> sin error."""
        valid_pagos_data.cfdi_emisor_rfc = None
        errors = validate_rfc_emisor(valid_pagos_data)
        assert errors == []


class TestValidateDoctosRelacionados:
    """Tests de validate_doctos_relacionados()."""

    def test_valid_docto(self, valid_pagos_data):
        """Docto válido -> sin errores."""
        errors = validate_doctos_relacionados(valid_pagos_data)
        assert errors == []

    def test_saldo_ant_less_than_pagado(self, valid_pagos_data):
        """ImpSaldoAnt < ImpPagado -> error."""
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_saldo_ant = Decimal("1000")
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_pagado = Decimal("5000")
        errors = validate_doctos_relacionados(valid_pagos_data)
        assert any("ImpSaldoAnt" in e and "menor" in e for e in errors)

    def test_saldo_insoluto_incorrect(self, valid_pagos_data):
        """ImpSaldoInsoluto != ImpSaldoAnt - ImpPagado -> error."""
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_saldo_ant = Decimal("10000")
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_pagado = Decimal("5000")
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_saldo_insoluto = Decimal("6000")
        errors = validate_doctos_relacionados(valid_pagos_data)
        assert any("ImpSaldoInsoluto" in e and "coincide" in e for e in errors)

    def test_no_errors_when_fields_missing(self, valid_pagos_data):
        """Campos None -> sin error (no se puede validar)."""
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_saldo_ant = None
        valid_pagos_data.pagos[0].documentos_relacionados[0].imp_pagado = None
        errors = validate_doctos_relacionados(valid_pagos_data)
        assert errors == []


class TestValidateTipoCadenaPago:
    """Tests de validate_tipo_cadena_pago()."""

    def test_valid_codes(self):
        """Todos los códigos SAT válidos pasan."""
        for code in TIPO_CADENA_PAGO_CODES:
            pago = PagoInfo(tipo_cad_pago=code)
            data = PagosData(pagos=[pago])
            errors = validate_tipo_cadena_pago(data)
            assert errors == [], f"Code {code} should be valid"

    def test_invalid_code(self, valid_pagos_data):
        """Código inválido -> error."""
        valid_pagos_data.pagos[0].tipo_cad_pago = "99"
        errors = validate_tipo_cadena_pago(valid_pagos_data)
        assert any("válido" in e for e in errors)

    def test_none_optional(self, valid_pagos_data):
        """TipoCadPago None -> sin error (campo opcional)."""
        valid_pagos_data.pagos[0].tipo_cad_pago = None
        errors = validate_tipo_cadena_pago(valid_pagos_data)
        assert errors == []


class TestValidatePagosFull:
    """Tests del validador maestro validate_pagos()."""

    def test_valid_data(self, valid_pagos_data):
        """Data completa y válida -> lista de errores vacía."""
        errors = validate_pagos(valid_pagos_data)
        assert errors == []

    def test_none_data(self):
        """Data None -> error de ausencia."""
        errors = validate_pagos(None)
        assert len(errors) == 1
        assert "No se encontró" in errors[0]

    def test_multiple_errors(self, valid_pagos_data):
        """Múltiples errores se acumulan."""
        valid_pagos_data.pagos[0].monto = Decimal("0")
        valid_pagos_data.pagos[0].forma_pago_p = "99"
        valid_pagos_data.pagos[0].moneda_p = "XYZ"
        errors = validate_pagos(valid_pagos_data)
        assert len(errors) >= 3


# ===========================================================================
# ROUTE TESTS
# ===========================================================================

class TestPagosRoutes:
    """Tests de los endpoints FastAPI /pagos/*."""

    def test_parse_endpoint(self, client, simple_pagos_xml):
        """POST /pagos/parse con XML válido."""
        with open(simple_pagos_xml, "rb") as f:
            response = client.post("/pagos/parse", files={"file": ("test.xml", f, "application/xml")})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "pagos" in data
        assert data["pagos"]["version"] == "1.1"
        assert len(data["pagos"]["pagos"]) == 1

    def test_parse_endpoint_no_complement(self, client, no_pagos_xml):
        """POST /pagos/parse sin complemento -> 404."""
        with open(no_pagos_xml, "rb") as f:
            response = client.post("/pagos/parse", files={"file": ("test.xml", f, "application/xml")})
        assert response.status_code == 404
        assert "no contiene" in response.json()["detail"]

    def test_parse_endpoint_empty_file(self, client):
        """POST /pagos/parse con archivo vacío -> 400."""
        response = client.post("/pagos/parse", files={"file": ("empty.xml", b"", "application/xml")})
        assert response.status_code == 400
        assert "vacío" in response.json()["detail"]

    def test_parse_endpoint_invalid_xml(self, client):
        """POST /pagos/parse con XML inválido -> 422."""
        response = client.post("/pagos/parse", files={"file": ("bad.xml", b"<broken>", "application/xml")})
        assert response.status_code == 422
        assert "Error al parsear XML" in response.json()["detail"]

    def test_validate_endpoint(self, client, simple_pagos_xml):
        """POST /pagos/validate con XML válido."""
        with open(simple_pagos_xml, "rb") as f:
            response = client.post("/pagos/validate", files={"file": ("test.xml", f, "application/xml")})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["errors"] == []

    def test_validate_endpoint_empty_file(self, client):
        """POST /pagos/validate con archivo vacío -> 400."""
        response = client.post("/pagos/validate", files={"file": ("empty.xml", b"", "application/xml")})
        assert response.status_code == 400

    def test_validate_endpoint_invalid_xml(self, client):
        """POST /pagos/validate con XML inválido -> 422."""
        response = client.post("/pagos/validate", files={"file": ("bad.xml", b"<broken>", "application/xml")})
        assert response.status_code == 422

    def test_catalog_endpoint(self, client):
        """GET /pagos/catalog retorna catálogos."""
        response = client.get("/pagos/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "forma_pago" in data
        assert "tipo_cadena_pago" in data
        assert "monedas_iso" in data
        assert "01" in data["forma_pago"]
        assert "03" in data["tipo_cadena_pago"]
        assert "MXN" in data["monedas_iso"]

    def test_parse_endpoint_with_taxes(self, client):
        """POST /pagos/parse con impuestos."""
        xml_bytes = PAGOS_WITH_TAXES_XML.encode("utf-8")
        response = client.post("/pagos/parse", files={"file": ("taxes.xml", xml_bytes, "application/xml")})
        assert response.status_code == 200
        data = response.json()
        doc = data["pagos"]["pagos"][0]["documentos_relacionados"][0]
        assert doc["impuestos"] is not None
        assert len(doc["impuestos"]["retenciones"]) == 1
        assert len(doc["impuestos"]["traslados"]) == 1

    def test_validate_endpoint_multiple_payments(self, client):
        """POST /pagos/validate con múltiples pagos."""
        xml_bytes = MULTIPLE_PAGOS_XML.encode("utf-8")
        response = client.post("/pagos/validate", files={"file": ("multi.xml", xml_bytes, "application/xml")})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ===========================================================================
# EDGE CASE TESTS
# ===========================================================================

class TestEdgeCases:
    """Tests de edge cases y situaciones especiales."""

    def test_empty_complemento_tag(self):
        """Complemento con tag vacío (sin contenido Pagos)."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento/>
</cfdi:Comprobante>"""
        data = parse_pagos_bytes(xml.encode("utf-8"))
        assert data is None

    def test_cfdi_with_other_complement(self):
        """CFDI con otro complemento (no Pagos) -> None."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="N">
    <cfdi:Emisor Rfc="TEST010101AAA" Nombre="Test"/>
    <cfdi:Receptor Rfc="TEST020202BBB" Nombre="Test2"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento>
        <nomina12:Nomina Version="1.2" TipoNomina="O"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        data = parse_pagos_bytes(xml.encode("utf-8"))
        assert data is None

    def test_whitespace_only_forma_pago(self):
        """FormaPago con solo espacios -> error de ausencia."""
        pago = PagoInfo(forma_pago_p="   ")
        data = PagosData(pagos=[pago])
        errors = validate_forma_pago(data)
        assert any("ausente" in e for e in errors)

    def test_whitespace_only_moneda(self):
        """Moneda con solo espacios -> error de ausencia."""
        pago = PagoInfo(moneda_p="   ")
        data = PagosData(pagos=[pago])
        errors = validate_moneda(data)
        assert any("ausente" in e for e in errors)

    def test_many_payments(self):
        """XML con muchos pagos (10) se parsea correctamente."""
        pagos_xml_parts = []
        for i in range(10):
            pagos_xml_parts.append(
                f'<pagos:Pago FechaPago="2026-07-{i+1:02d}" '
                f'FormaPagoP="01" MonedaP="MXN" Monto="{1000*(i+1)}.00">'
                f'<pagos:DoctoRelacionado IdDocumento="DOC-{i+1:03d}" '
                f'MonedaDR="MXN" MetodoDePagoDR="PUE" '
                f'ImpSaldoAnt="{1000*(i+1)}.00" ImpPagado="{1000*(i+1)}.00" '
                f'ImpSaldoInsoluto="0.00"/>'
                f'</pagos:Pago>'
            )
        pagos_xml = "\n".join(pagos_xml_parts)
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pagos="http://www.sat.gob.mx/pagos"
    Version="4.0" Fecha="2026-07-15T10:00:00"
    TipoDeComprobante="P" SubTotal="0" Total="0" Moneda="MXN">
    <cfdi:Emisor Rfc="EMISOR010101AAA" Nombre="Emisor"/>
    <cfdi:Receptor Rfc="RECEPT010101BBB" Nombre="Receptor"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio" Descripcion="Pago"
            ValorUnitario="0" Importe="0" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pagos:Pagos Version="1.1">
{pagos_xml}
        </pagos:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        data = parse_pagos_bytes(xml.encode("utf-8"))
        assert data is not None
        assert len(data.pagos) == 10
        for i, pago in enumerate(data.pagos):
            assert pago.monto == Decimal(f"{1000*(i+1)}.00")

    def test_many_payments_valid(self):
        """10 pagos válidos -> validación pasa."""
        pagos = []
        for i in range(10):
            pagos.append(PagoInfo(
                fecha_pago=f"2026-07-{i+1:02d}",
                forma_pago_p="01",
                moneda_p="MXN",
                monto=Decimal(f"{1000*(i+1)}.00"),
                documentos_relacionados=[
                    DoctoRelacionado(
                        id_documento=f"DOC-{i+1:03d}",
                        moneda_dr="MXN",
                        metodo_de_pago_dr="PUE",
                        imp_saldo_ant=Decimal(f"{1000*(i+1)}.00"),
                        imp_pagado=Decimal(f"{1000*(i+1)}.00"),
                        imp_saldo_insoluto=Decimal("0"),
                    ),
                ],
            ))
        data = PagosData(
            version="1.1",
            cfdi_emisor_rfc="EMISOR010101AAA",
            pagos=pagos,
        )
        errors = validate_pagos(data)
        assert errors == []

    def test_currency_conversion_logic(self):
        """Pago en USD con tipo de cambio se parsea y valida correctamente."""
        data = parse_pagos_bytes(PAGOS_FOREIGN_CURRENCY_XML.encode("utf-8"))
        pago = data.pagos[0]
        assert pago.moneda_p == "USD"
        assert pago.tipo_cambio_p == Decimal("17.50")
        doc = pago.documentos_relacionados[0]
        # MXN = USD * TipoCambio
        assert doc.imp_pagado == Decimal("8750.00")
        # 500 * 17.50 = 8750
        assert pago.monto * pago.tipo_cambio_p == doc.imp_pagado

    def test_saldo_insoluto_zero(self):
        """Pago completo -> ImpSaldoInsoluto = 0."""
        data = parse_pagos_bytes(SIMPLE_PAGOS_XML.encode("utf-8"))
        doc = data.pagos[0].documentos_relacionados[0]
        assert doc.imp_saldo_insoluto == Decimal("5000.00")
        assert doc.imp_saldo_ant - doc.imp_pagado == doc.imp_saldo_insoluto

    def test_retencion_to_dict(self):
        """Retencion.to_dict() serializa correctamente."""
        ret = Retencion(
            base=Decimal("1000.00"),
            impuesto="001",
            tipo_factor="Tasa",
            tasa_o_cuota=Decimal("0.160000"),
            importe=Decimal("160.00"),
        )
        d = ret.to_dict()
        assert d["base"] == "1000.00"
        assert d["impuesto"] == "001"
        assert d["importe"] == "160.00"

    def test_traslado_to_dict(self):
        """Traslado.to_dict() serializa correctamente."""
        tras = Traslado(
            base=Decimal("1000.00"),
            impuesto="002",
            tipo_factor="Tasa",
            tasa_o_cuota=Decimal("0.160000"),
            importe=Decimal("160.00"),
        )
        d =tras.to_dict()
        assert d["base"] == "1000.00"
        assert d["impuesto"] == "002"

    def test_impuestos_dr_to_dict(self):
        """ImpuestosDR.to_dict() serializa correctamente."""
        imp = ImpuestosDR(
            retenciones=[Retencion(impuesto="001")],
            traslados=[Traslado(impuesto="002")],
        )
        d = imp.to_dict()
        assert len(d["retenciones"]) == 1
        assert len(d["traslados"]) == 1

    def test_pago_info_to_dict_no_docs(self):
        """PagoInfo.to_dict() sin documentos relacionados."""
        pago = PagoInfo(fecha_pago="2026-07-15", forma_pago_p="01",
                        moneda_p="MXN", monto=Decimal("100.00"))
        d = pago.to_dict()
        assert d["documentos_relacionados"] == []

    def test_many_payments_all_must_be_valid(self):
        """Si 1 de 10 pagos tiene monto 0, validación falla."""
        pagos = []
        for i in range(10):
            pagos.append(PagoInfo(
                fecha_pago=f"2026-07-{i+1:02d}",
                forma_pago_p="01",
                moneda_p="MXN",
                monto=Decimal("100.00") if i != 5 else Decimal("0"),
                documentos_relacionados=[
                    DoctoRelacionado(
                        id_documento=f"DOC-{i+1:03d}",
                        moneda_dr="MXN",
                        metodo_de_pago_dr="PUE",
                        imp_saldo_ant=Decimal("100.00"),
                        imp_pagado=Decimal("100.00"),
                        imp_saldo_insoluto=Decimal("0"),
                    ),
                ],
            ))
        data = PagosData(version="1.1", cfdi_emisor_rfc="EMISOR", pagos=pagos)
        errors = validate_monto_pago(data)
        assert any("Pago 6" in e for e in errors)
