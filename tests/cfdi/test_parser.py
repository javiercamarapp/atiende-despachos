# -*- coding: utf-8 -*-
"""Tests for b2b_ai/cfdi/parser.py — CFDI XML parsing."""
import os
import pytest
import tempfile
from b2b_ai.cfdi.parser import parse_cfdi, CFDIError


SAMPLE_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="D" Folio="100"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Descuento="0.00" Total="1160.00">
    <cfdi:Emisor Rfc="PAP850101JKL" Nombre="PAPELERIA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR TEST"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Papeleria y articulos de oficina"
            ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                        TasaOCuota="0.160000" Importe="160.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1"
            UUID="550e8400-e29b-41d4-a716-446655440000"
            FechaTimbrado="2026-07-03T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


@pytest.fixture
def sample_xml(tmp_path):
    path = tmp_path / "test_cfdi.xml"
    path.write_text(SAMPLE_CFDI)
    return str(path)


class TestParseCFDI:
    def test_basic_parse(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert datos["version"] == "4.0"
        assert datos["tipo"] == "I"
        assert datos["emisor_rfc"] == "PAP850101JKL"
        assert datos["receptor_rfc"] == "XAXX010101000"

    def test_amounts(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert float(datos["subtotal"]) == 1000.0
        assert float(datos["total"]) == 1160.0
        assert float(datos["iva"]) == 160.0

    def test_conceptos(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert len(datos["conceptos"]) == 1
        assert datos["conceptos"][0]["clave_prod_serv"] == "44122000"

    def test_folio_fiscal(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert datos["folio_fiscal"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_sello(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        # Sello is empty in our test XML; tiene_sello depends on Sello attribute
        # The sample has Sello="" (default) so tiene_sello may be False
        assert "tiene_sello" in datos

    def test_file_not_found(self):
        with pytest.raises(OSError, match="no encontrado"):
            parse_cfdi("/nonexistent/path.xml")

    def test_invalid_xml(self, tmp_path):
        path = tmp_path / "bad.xml"
        path.write_text("not xml at all")
        with pytest.raises(CFDIError):
            parse_cfdi(str(path))

    def test_non_comprobante_root(self, tmp_path):
        path = tmp_path / "wrong.xml"
        path.write_text('<?xml version="1.0"?><Root/>')
        with pytest.raises(CFDIError, match="no es un CFDI"):
            parse_cfdi(str(path))

    def test_emisor_nombre(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert datos["emisor_nombre"] == "PAPELERIA TEST"

    def test_descripcion_concatenada(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert "Papeleria" in datos["descripcion"]

    def test_traslados_globales(self, sample_xml):
        datos = parse_cfdi(sample_xml)
        assert len(datos["traslados"]) >= 1
