# -*- coding: utf-8 -*-
"""Tests del parser CFDI completo."""
import pytest

from b2b_ai.cfdi.parser import parse_cfdi, CFDIError
from decimal import Decimal


def test_parse_consultoria(parsed_consultoria):
    d = parsed_consultoria
    assert d["version"] == "4.0"
    assert d["tipo"] == "I"
    assert d["metodo_pago"] == "PPD"
    assert d["moneda"] == "MXN"
    assert d["emisor_rfc"] == "CON950820K12"
    assert d["receptor_rfc"] == "JCCP840101HDA"
    assert d["uso_cfdi"] == "G03"
    assert d["subtotal"] == Decimal("5000.00")
    assert d["iva"] == Decimal("800.00")
    assert d["total"] == Decimal("5800.00")
    assert d["folio_fiscal"] == "4a54e553-84f3-4a3a-b495-846bad779691"
    assert d["exportacion"] == "01"
    assert len(d["conceptos"]) == 1
    assert d["conceptos"][0]["cantidad"] == Decimal("1")
    assert d["conceptos"][0]["importe"] == Decimal("5000.00")


def test_parse_nomina(sample_nomina):
    d = parse_cfdi(sample_nomina)
    assert d["tipo"] == "N"
    assert d["nomina"] is not None
    assert d["nomina"]["tipo_nomina"] == "O"
    assert d["nomina"]["total_percepciones"] == Decimal("15000.00")
    assert d["metodo_pago"] == "PUE"


def test_parse_honorarios_retenciones(sample_honorarios):
    d = parse_cfdi(sample_honorarios)
    assert d["retenciones_isr"] == Decimal("2000.00")
    assert d["retenciones_iva"] == Decimal("2133.34")
    assert d["iva"] == Decimal("3200.00")
    assert len(d["retenciones"]) == 2


def test_parse_pago_complemento(sample_pago):
    d = parse_cfdi(sample_pago)
    assert d["tipo"] == "P"
    assert d["metodo_pago"] == "PPD"
    assert len(d["pagos"]) == 1
    assert d["pagos"][0]["monto"] == Decimal("2000.00")
    assert len(d["pagos"][0]["doctos_relacionados"]) == 1
    assert d["pagos"][0]["doctos_relacionados"][0]["imp_pagado"] == Decimal("2000.00")


def test_parse_archivo_inexistente():
    with pytest.raises(OSError):
        parse_cfdi("/no/existe/factura.xml")


def test_parse_no_cfdi(tmp_path):
    f = tmp_path / "no.xml"
    f.write_text("<root><x/></root>")
    with pytest.raises(CFDIError):
        parse_cfdi(str(f))


def test_parse_xml_malformado(tmp_path):
    f = tmp_path / "malo.xml"
    f.write_text("<cfdi:Comprobante")
    with pytest.raises(CFDIError):
        parse_cfdi(str(f))


def test_descripcion_concatenada(parsed_consultoria):
    assert "consultoria" in parsed_consultoria["descripcion"].lower()


def test_parse_fecha_malformada_no_crashea(tmp_path):
    """Regresión: Fecha inválida + FechaTimbrado válida no debe crashear."""
    xml = (
        '<?xml version="1.0"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        'Serie="A" Folio="1" Fecha="NO-ES-FECHA" FormaPago="01" MetodoPago="PUE" '
        'Moneda="MXN" SubTotal="100.00" Total="116.00" TipoDeComprobante="I" '
        'LugarExpedicion="65000" Exportacion="01">'
        '<cfdi:Emisor Rfc="AAA010101AAA" Nombre="EMPRESA SA" RegimenFiscal="601"/>'
        '<cfdi:Receptor Rfc="BBB020202BBB" Nombre="CLIENTE SA" '
        'DomicilioFiscalReceptor="65000" RegimenFiscalReceptor="601" UsoCFDI="G03"/>'
        '<cfdi:Conceptos><cfdi:Concepto ClaveProdServ="01010101" Cantidad="1" '
        'ClaveUnidad="ACT" Descripcion="Papel" ValorUnitario="100.00" Importe="100.00" '
        'ObjetoImp="02"><cfdi:Impuestos><cfdi:Traslados>'
        '<cfdi:Traslado Base="100.00" Impuesto="002" TipoFactor="Tasa" '
        'TasaOCuota="0.160000" Importe="16.00"/></cfdi:Traslados></cfdi:Impuestos>'
        '</cfdi:Concepto></cfdi:Conceptos>'
        '<cfdi:Impuestos TotalImpuestosTrasladados="16.00"><cfdi:Traslados>'
        '<cfdi:Traslado Base="100.00" Impuesto="002" TipoFactor="Tasa" '
        'TasaOCuota="0.160000" Importe="16.00"/></cfdi:Traslados></cfdi:Impuestos>'
        '<tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
        'Version="1.1" UUID="11111111-1111-1111-1111-111111111111" '
        'FechaTimbrado="2026-07-01T12:00:00"/>'
        '</cfdi:Comprobante>'
    )
    f = tmp_path / "fecha_mala.xml"
    f.write_text(xml)
    d = parse_cfdi(str(f))
    assert d["fechas_coherentes"] is False
    assert d["fecha_dt"] is None
