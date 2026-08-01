# -*- coding: utf-8 -*-
"""
Comprehensive test coverage for b2b_ai/cfdi/ module.
Covers: parser.py, validator.py, catalogs.py, cancellation.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from decimal import Decimal

import pytest

# ── catalogs.py ───────────────────────────────────────────────────────────────

from b2b_ai.cfdi.catalogs import (
    IMPUESTOS, TIPOS_FACTOR, TIPOS_COMPROBANTE, METODOS_PAGO,
    FORMAS_PAGO, USOS_CFDI, REGIMENES_FISCALES, CP_CATEGORIAS,
    is_valid_uso_cfdi, is_valid_forma_pago, is_valid_metodo_pago,
    is_valid_tipo_comprobante, is_valid_regimen, is_valid_impuesto,
    describe_impuesto,
)


class TestCatalogs:
    def test_is_valid_uso_cfdi(self):
        assert is_valid_uso_cfdi("G01") is True
        assert is_valid_uso_cfdi("ZZ") is False
        assert is_valid_uso_cfdi("CN01") is True

    def test_is_valid_forma_pago(self):
        assert is_valid_forma_pago("01") is True
        assert is_valid_forma_pago("99") is True
        assert is_valid_forma_pago("ZZ") is False

    def test_is_valid_metodo_pago(self):
        assert is_valid_metodo_pago("PUE") is True
        assert is_valid_metodo_pago("PPD") is True
        assert is_valid_metodo_pago("XYZ") is False

    def test_is_valid_tipo_comprobante(self):
        assert is_valid_tipo_comprobante("I") is True
        assert is_valid_tipo_comprobante("E") is True
        assert is_valid_tipo_comprobante("T") is True
        assert is_valid_tipo_comprobante("P") is True
        assert is_valid_tipo_comprobante("N") is True
        assert is_valid_tipo_comprobante("Z") is False

    def test_is_valid_regimen(self):
        assert is_valid_regimen("601") is True
        assert is_valid_regimen("612") is True
        assert is_valid_regimen("999") is False

    def test_is_valid_impuesto(self):
        assert is_valid_impuesto("001") is True
        assert is_valid_impuesto("002") is True
        assert is_valid_impuesto("003") is True
        assert is_valid_impuesto("999") is False

    def test_describe_impuesto(self):
        assert describe_impuesto("001") == "ISR"
        assert describe_impuesto("002") == "IVA"
        assert describe_impuesto("999") == "999"

    def test_cp_categorias(self):
        assert "activo_fijo" in CP_CATEGORIAS
        assert "gasto_operativo" in CP_CATEGORIAS
        assert "inversion" in CP_CATEGORIAS

    def test_tipos_factor(self):
        assert "Tasa" in TIPOS_FACTOR
        assert "Exento" in TIPOS_FACTOR


# ── parser.py ─────────────────────────────────────────────────────────────────

from b2b_ai.cfdi.parser import parse_cfdi, CFDIError


class TestParser:
    def _write_xml(self, content, suffix=".xml"):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_parse_basic_invoice(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="D" Folio="1" Fecha="2026-07-01T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Total="1160.00"
    Sello="ABC123DEF456" NoCertificado="30001000000500003418" Certificado="MIIFuz...">
  <cfdi:Emisor Rfc="ABC850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" Nombre="Cliente SA" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="80121600" Cantidad="1" ClaveUnidad="E48" Unidad="Servicio"
        Descripcion="Servicio profesional" ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02">
      <cfdi:Impuestos>
        <cfdi:Traslados>
          <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
      </cfdi:Impuestos>
    </cfdi:Concepto>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
    <cfdi:Traslados>
      <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="160.00"/>
    </cfdi:Traslados>
  </cfdi:Impuestos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440000"
        FechaTimbrado="2026-07-01T10:01:00" RfcProvCertif="SAT970701NN3"
        SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["version"] == "4.0"
            assert r["tipo"] == "I"
            assert r["emisor_rfc"] == "ABC850101AB1"
            assert r["emisor_nombre"] == "Empresa SA"
            assert r["receptor_rfc"] == "XYZ010101AAA"
            assert r["total"] == Decimal("1160.00")
            assert r["iva"] == Decimal("160.00")
            assert r["folio_fiscal"] == "550e8400-e29b-41d4-a716-446655440000"
            assert len(r["conceptos"]) == 1
            assert len(r["traslados"]) == 1
            assert r["tiene_sello"] is True
        finally:
            os.unlink(path)

    def test_parse_not_found(self):
        with pytest.raises(OSError, match="no encontrado"):
            parse_cfdi("/nonexistent/file.xml")

    def test_parse_invalid_xml(self):
        path = self._write_xml("<invalid")
        try:
            with pytest.raises(CFDIError, match="mal formado"):
                parse_cfdi(path)
        finally:
            os.unlink(path)

    def test_parse_not_cfdi(self):
        path = self._write_xml("<root></root>")
        try:
            with pytest.raises(CFDIError, match="no es un CFDI"):
                parse_cfdi(path)
        finally:
            os.unlink(path)

    def test_parse_nota_credito(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="E" Folio="1" Fecha="2026-07-01T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="E" Exportacion="01"
    LugarExpedicion="06600" SubTotal="500.00" Total="0.00">
  <cfdi:Emisor Rfc="ABC850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" Nombre="Cliente SA" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="D08"/>
  <cfdi:CfdiRelacionados TipoRelacion="04">
    <cfdi:CfdiRelacionado UUID="550e8400-e29b-41d4-a716-446655440001"/>
  </cfdi:CfdiRelacionados>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="80121600" Cantidad="1" ClaveUnidad="E48" Unidad="Servicio"
        Descripcion="Descuento" ValorUnitario="500.00" Importe="500.00" ObjetoImp="02"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440002"
        FechaTimbrado="2026-07-01T10:01:00" RfcProvCertif="SAT970701NN3"
        SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["tipo"] == "E"
            assert len(r["cfdi_relacionados"]) == 1
        finally:
            os.unlink(path)

    def test_parse_with_retenciones(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="H" Folio="1" Fecha="2026-07-01T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="10000.00" Total="10000.00">
  <cfdi:Emisor Rfc="ABC850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" Nombre="Cliente SA" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="80121600" Cantidad="1" ClaveUnidad="E48" Unidad="Servicio"
        Descripcion="Honorarios" ValorUnitario="10000.00" Importe="10000.00" ObjetoImp="02"/>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosRetenidos="1100.00">
    <cfdi:Retenciones>
      <cfdi:Retencion Base="10000.00" Impuesto="001" TipoFactor="Tasa" TasaOCuota="0.100000" Importe="1000.00"/>
      <cfdi:Retencion Base="1000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="160.00"/>
    </cfdi:Retenciones>
  </cfdi:Impuestos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440003"
        FechaTimbrado="2026-07-01T10:01:00" RfcProvCertif="SAT970701NN3"
        SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["retenciones_isr"] == Decimal("1000.00")
            assert r["retenciones_iva"] == Decimal("160.00")
            assert len(r["retenciones"]) == 2
        finally:
            os.unlink(path)

    def test_parse_nomina(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="N" Folio="1" Fecha="2026-07-15T08:00:00"
    FormaPago="99" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="N" Exportacion="01"
    LugarExpedicion="06600" SubTotal="15000.00" Total="15000.00">
  <cfdi:Emisor Rfc="ABC850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101HDF" Nombre="Empleado" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="605" UsoCFDI="CN01"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="84111505" Cantidad="1" ClaveUnidad="ACT"
        Descripcion="Pago de nómina" ValorUnitario="15000.00" Importe="15000.00" ObjetoImp="01"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <nomina12:Nomina Version="1.2" TipoNomina="O" FechaPago="2026-07-15"
        FechaInicialPago="2026-07-01" FechaFinalPago="2026-07-15" NumDiasPagados="15"
        TotalPercepciones="18000.00" TotalDeducciones="3000.00">
      <nomina12:Receptor Curp="AABB010101HDFRRL01" NumEmpleado="001"/>
    </nomina12:Nomina>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440004"
        FechaTimbrado="2026-07-15T08:01:00" RfcProvCertif="SAT970701NN3"
        SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["nomina"] is not None
            assert r["nomina"]["tipo_nomina"] == "O"
            assert r["nomina"]["curp"] == "AABB010101HDFRRL01"
            assert r["nomina"]["num_empleado"] == "001"
        finally:
            os.unlink(path)

    def test_parse_pago(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pago20="http://www.sat.gob.mx/Pagos20"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="P" Folio="1" Fecha="2026-07-01T10:00:00"
    FormaPago="03" MetodoPago="PPD" Moneda="MXN"
    TipoDeComprobante="P" Exportacion="01"
    LugarExpedicion="06600" SubTotal="0.00" Total="0.00">
  <cfdi:Emisor Rfc="ABC850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" Nombre="Cliente SA" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="CP01"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT"
        Descripcion="Pago" ValorUnitario="0.00" Importe="0.00" ObjetoImp="01"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <pago20:Pagos Version="2.0">
      <pago20:Pago FechaPago="2026-07-01" FormaDePagoP="03" MonedaP="MXN" Monto="5000.00">
        <pago20:DoctoRelacionado IdDocumento="550e8400-e29b-41d4-a716-446655440000" MonedaDR="MXN"
            MetodoDePagoDR="PPD" NumParcialidad="1" ImpSaldoAnt="5000.00" ImpPagado="5000.00" ImpSaldoInsoluto="0.00"/>
      </pago20:Pago>
    </pago20:Pagos>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440005"
        FechaTimbrado="2026-07-01T10:01:00" RfcProvCertif="SAT970701NN3"
        SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["tipo"] == "P"
            assert len(r["pagos"]) == 1
            assert r["pagos"][0]["monto"] == Decimal("5000.00")
        finally:
            os.unlink(path)

    def test_parse_descuento(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="D" Folio="1" Fecha="2026-07-01T10:00:00"
    FormaPago="01" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Descuento="100.00" Total="1044.00">
  <cfdi:Emisor Rfc="ABC850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" Nombre="Cliente SA" DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="80121600" Cantidad="1" ClaveUnidad="E48" Unidad="Servicio"
        Descripcion="Servicio con descuento" ValorUnitario="1000.00" Importe="1000.00" Descuento="100.00" ObjetoImp="02"/>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="144.00">
    <cfdi:Traslados>
      <cfdi:Traslado Base="900.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="144.00"/>
    </cfdi:Traslados>
  </cfdi:Impuestos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440006"
        FechaTimbrado="2026-07-01T10:01:00" RfcProvCertif="SAT970701NN3"
        SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["descuento"] == Decimal("100.00")
            assert r["total"] == Decimal("1044.00")
        finally:
            os.unlink(path)

    def test_parse_dates(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Fecha="2026-07-01T10:00:00"
    TipoDeComprobante="I" LugarExpedicion="06600" Total="0.00">
  <cfdi:Emisor Rfc="ABC850101AB1" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" RegimenFiscalReceptor="603"/>
  <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="80121600" Cantidad="1" ClaveUnidad="E48" Descripcion="X" ValorUnitario="0" Importe="0" ObjetoImp="01"/></cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="550e8400-e29b-41d4-a716-446655440007"
        FechaTimbrado="2026-07-01T10:05:00" RfcProvCertif="SAT970701NN3" SelloCFD="" NoCertificado="" SelloSAT=""/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["fecha"] == "2026-07-01T10:00:00"
            assert r["fecha_dt"] is not None
            assert r["fecha_timbrado_dt"] is not None
            assert r["fechas_coherentes"] is True
        finally:
            os.unlink(path)

    def test_parse_no_sello(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Fecha="2026-07-01T10:00:00"
    TipoDeComprobante="I" LugarExpedicion="06600" Total="0.00">
  <cfdi:Emisor Rfc="ABC850101AB1" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XYZ010101AAA" RegimenFiscalReceptor="603"/>
  <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="80121600" Cantidad="1" ClaveUnidad="E48" Descripcion="X" ValorUnitario="0" Importe="0" ObjetoImp="01"/></cfdi:Conceptos>
</cfdi:Comprobante>"""
        path = self._write_xml(xml)
        try:
            r = parse_cfdi(path)
            assert r["tiene_sello"] is False
        finally:
            os.unlink(path)


# ── validator.py ──────────────────────────────────────────────────────────────

from b2b_ai.cfdi.validator import validate_cfdi, ValidationResult


class TestValidator:
    def _valid_datos(self):
        return {
            "subtotal": "1000.00", "total": "1160.00", "descuento": "0",
            "iva": "160.00", "tipo": "I", "uso_cfdi": "G03",
            "forma_pago": "03", "metodo_pago": "PUE",
            "emisor_rfc": "ABC850101AB1", "emisor_nombre": "Empresa SA",
            "emisor": {"regimen_fiscal": "601"},
            "receptor_rfc": "XYZ010101AAA", "receptor_nombre": "Cliente SA",
            "fecha": "2026-07-01T10:00:00", "fecha_timbrado": "2026-07-01T10:01:00",
            "conceptos": [{
                "cantidad": "1", "valor_unitario": "1000.00", "importe": "1000.00",
                "traslados": [{"impuesto": "002", "tipo_factor": "Tasa",
                              "base": "1000.00", "tasa_cuota": "0.160000", "importe": "160.00"}]
            }],
            "traslados": [{"impuesto": "002", "tipo_factor": "Tasa",
                           "base": "1000.00", "tasa_cuota": "0.160000", "importe": "160.00"}],
            "retenciones": [],
        }

    def test_valid_invoice(self):
        r = validate_cfdi(self._valid_datos())
        assert r["ok"] is True
        assert r["checks"]["fail"] == 0

    def test_aritmetica_incorrecta(self):
        d = self._valid_datos()
        d["conceptos"][0]["importe"] = "9999.00"  # wrong
        r = validate_cfdi(d)
        assert r["ok"] is False
        assert any(i["code"] == "importe_concepto_incoherente" for i in r["issues"])

    def test_subtotal_descuadra(self):
        d = self._valid_datos()
        d["subtotal"] = "500.00"  # doesn't match concepto importe
        r = validate_cfdi(d)
        assert any(i["code"] == "subtotal_descuadra_conceptos" for i in r["issues"])

    def test_total_incoherente(self):
        d = self._valid_datos()
        d["total"] = "9999.00"
        r = validate_cfdi(d)
        assert any(i["code"] == "total_incoherente" for i in r["issues"])

    def test_rfc_emisor_invalido(self):
        d = self._valid_datos()
        d["emisor_rfc"] = "invalid"
        r = validate_cfdi(d)
        assert any(i["code"] == "rfc_emisor_invalido" for i in r["issues"])

    def test_rfc_receptor_invalido(self):
        d = self._valid_datos()
        d["receptor_rfc"] = "invalid"
        r = validate_cfdi(d)
        assert any(i["code"] == "rfc_receptor_invalido" for i in r["issues"])

    def test_uso_cfdi_invalido(self):
        d = self._valid_datos()
        d["uso_cfdi"] = "ZZ"
        r = validate_cfdi(d)
        assert any(i["code"] == "uso_cfdi_invalido" for i in r["issues"])

    def test_forma_pago_invalida(self):
        d = self._valid_datos()
        d["forma_pago"] = "ZZ"
        r = validate_cfdi(d)
        assert any(i["code"] == "forma_pago_invalida" for i in r["issues"])

    def test_metodo_pago_invalido(self):
        d = self._valid_datos()
        d["metodo_pago"] = "XYZ"
        r = validate_cfdi(d)
        assert any(i["code"] == "metodo_pago_invalido" for i in r["issues"])

    def test_tipo_invalido(self):
        d = self._valid_datos()
        d["tipo"] = "Z"
        r = validate_cfdi(d)
        assert any(i["code"] == "tipo_comprobante_invalido" for i in r["issues"])

    def test_regimen_invalido(self):
        d = self._valid_datos()
        d["emisor"]["regimen_fiscal"] = "999"
        r = validate_cfdi(d)
        assert any(i["code"] == "regimen_fiscal_invalido" for i in r["issues"])

    def test_fecha_invalida(self):
        d = self._valid_datos()
        d["fecha"] = "bad-date"
        r = validate_cfdi(d)
        assert any(i["code"] == "fecha_invalida" for i in r["issues"])

    def test_fecha_timbrado_anterior(self):
        d = self._valid_datos()
        d["fecha_timbrado"] = "2020-01-01T00:00:00"
        r = validate_cfdi(d)
        assert any(i["code"] == "fecha_timbrado_anterior" for i in r["issues"])

    def test_sin_timbre_warning(self):
        d = self._valid_datos()
        d["fecha_timbrado"] = ""
        r = validate_cfdi(d)
        assert any("Sin TimbreFiscalDigital" in w for w in r["warnings"])

    def test_diot_reportable(self):
        d = self._valid_datos()
        d["iva"] = "160.00"
        r = validate_cfdi(d)
        assert r["diot"]["reportable"] is True
        assert len(r["diot"]["proveedores_reportables"]) == 1

    def test_nomina_requires_pue(self):
        d = self._valid_datos()
        d["tipo"] = "I"
        d["nomina"] = {"total_percepciones": "1000"}
        d["metodo_pago"] = "PPD"
        r = validate_cfdi(d)
        assert any(i["code"] == "nomina_metodo_pago" for i in r["issues"])

    def test_nomina_sin_percepciones_warning(self):
        d = self._valid_datos()
        d["nomina"] = {"tipo_nomina": "O"}  # non-empty but no total_percepciones
        r = validate_cfdi(d)
        assert any("TotalPercepciones" in w for w in r["warnings"])

    def test_pago_monto_invalido(self):
        d = self._valid_datos()
        d["tipo"] = "P"
        d["pagos"] = [{"monto": -100}]
        r = validate_cfdi(d)
        assert any(i["code"] == "pago_monto_invalido" for i in r["issues"])

    def test_iva_global_mismatch(self):
        d = self._valid_datos()
        d["iva"] = "100.00"  # 16% of 1000 = 160
        r = validate_cfdi(d)
        assert any("IVA global" in w for w in r["warnings"])

    def test_iva_global_anchored_to_16pct(self):
        """[37] Verify the expected IVA is anchored to 16% (not 8% or other).

        IVA=160 on SubTotal=1000 → no warning (exact 16%).
        IVA=80 on SubTotal=1000 → warning (80 != 160).
        """
        from decimal import Decimal
        from b2b_ai.cfdi.validator import IVA_TASA_GENERAL
        # The constant must be 16%
        assert IVA_TASA_GENERAL == Decimal("0.16"), (
            f"IVA_TASA_GENERAL should be 0.16, got {IVA_TASA_GENERAL}")
        # IVA=160 on SubTotal=1000 → exact match → no warning
        d = self._valid_datos()
        d["iva"] = "160.00"
        r = validate_cfdi(d)
        assert not any("IVA global" in w for w in r["warnings"]), (
            "IVA=160 on SubTotal=1000 should match 16% — no warning expected")
        # IVA=80 on SubTotal=1000 → mismatch → warning with expected 160
        d["iva"] = "80.00"
        r = validate_cfdi(d)
        matching = [w for w in r["warnings"] if "IVA global" in w]
        assert len(matching) == 1
        assert "160" in matching[0], (
            f"Warning should mention expected 160, got: {matching[0]}")

    def test_retencion_isr_warning(self):
        d = self._valid_datos()
        d["retenciones_isr"] = "9999.00"
        r = validate_cfdi(d)
        assert any("Retención ISR" in w for w in r["warnings"])

    def test_retencion_iva_warning(self):
        d = self._valid_datos()
        d["retenciones_iva"] = "9999.00"
        r = validate_cfdi(d)
        assert any("Retención IVA" in w for w in r["warnings"])

    def test_iva_concepto_incoherente(self):
        d = self._valid_datos()
        d["conceptos"][0]["traslados"][0]["importe"] = "999.00"
        r = validate_cfdi(d)
        assert any(i["code"] == "iva_concepto_incoherente" for i in r["issues"])

    def test_validation_result_as_attr(self):
        r = validate_cfdi(self._valid_datos())
        assert r.ok is True
        with pytest.raises(AttributeError):
            _ = r.nonexistent


# ── cancellation.py ───────────────────────────────────────────────────────────

from b2b_ai.cfdi.cancellation import evaluate_cancellation, prepare_cancellation_request


class TestCancellation:
    def test_egreso(self):
        r = evaluate_cancellation({"tipo": "E", "total": "1000"})
        assert r["decision"] == "no_cancelar_usar_egreso"

    def test_nomina(self):
        r = evaluate_cancellation({"tipo": "N"})
        assert r["decision"] == "revisar_especial"

    def test_ingreso_small(self):
        r = evaluate_cancellation({"tipo": "I", "total": "100"})
        assert r["decision"] == "cancelacion_directa"
        assert r["requiere_aceptacion_receptor"] is False

    def test_ingreso_large(self):
        r = evaluate_cancellation({"tipo": "I", "total": "10000"})
        assert r["decision"] == "requiere_aceptacion_receptor"
        assert r["requiere_aceptacion_receptor"] is True

    def test_ingreso_no_total(self):
        r = evaluate_cancellation({"tipo": "I"})
        assert r["decision"] == "requiere_revision"

    def test_pago(self):
        r = evaluate_cancellation({"tipo": "P"})
        assert r["decision"] == "no_cancelar_complemento"

    def test_unknown_type(self):
        r = evaluate_cancellation({"tipo": ""})
        assert r["decision"] == "no_aplica"

    def test_relacionados(self):
        r = evaluate_cancellation({"tipo": "I", "total": "100", "cfdi_relacionados": ["uuid1"]})
        assert any("relacionado" in s for s in r["sugerencias"])

    def test_always_human_review(self):
        r = evaluate_cancellation({"tipo": "I", "total": "100"})
        assert r["requires_human_review"] is True

    def test_prepare_request_no_confirmation(self):
        payload, errors = prepare_cancellation_request(
            {"folio_fiscal": "UUID1", "emisor_rfc": "ABC", "tipo": "I", "total": "100"},
            motivo="test"
        )
        assert payload["dry_run"] is True
        assert any("confirmación" in e for e in errors)

    def test_prepare_request_no_uuid(self):
        payload, errors = prepare_cancellation_request(
            {"tipo": "I", "total": "100"},
            confirmacion_humana=True
        )
        assert any("folio fiscal" in e for e in errors)

    def test_prepare_request_complete(self):
        payload, errors = prepare_cancellation_request(
            {"folio_fiscal": "UUID1", "emisor_rfc": "ABC", "tipo": "I", "total": "100"},
            confirmacion_humana=True
        )
        assert len(errors) == 0
        assert payload["uuid"] == "UUID1"


# ── __init__.py exports ───────────────────────────────────────────────────────

class TestCFDIExports:
    def test_imports(self):
        from b2b_ai.cfdi import parse_cfdi, CFDIError, validate_cfdi, evaluate_cancellation
        assert callable(parse_cfdi)
        assert callable(validate_cfdi)
        assert callable(evaluate_cancellation)
