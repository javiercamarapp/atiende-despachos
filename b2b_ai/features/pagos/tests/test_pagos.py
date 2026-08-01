# -*- coding: utf-8 -*-
"""Tests for the Complemento de Pagos 1.1 parser and validators."""
from __future__ import annotations
import io
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from b2b_ai.features.pagos.parser import (
    PagosData, PagoInfo, DoctoRelacionado, Retencion, Traslado, ImpuestosDR,
    parse_pagos_bytes,
)
from b2b_ai.features.pagos.validators import (
    validate_pagos, validate_monto_pago, validate_forma_pago, validate_moneda,
    validate_tipo_cambio, validate_rfc_emisor, validate_doctos_relacionados,
    validate_tipo_cadena_pago,
    FORMA_PAGO_CODES, MONEDAS_ISO_4217,
)


# Helper: build minimal CFDI with Pagos complement

def _pagos_xml(forma_pago="03", moneda="MXN", monto="5000",
               tipo_cambio=None, rfc_ordenante=None, cfdi_rfc="EABC123456789",
               con_docto=True, saldo_ant="10000", imp_pagado="5000", saldo_insoluto="5000"):
    tc_line = ""
    if tipo_cambio is not None:
        tc_line = f' TipoCambioP="{tipo_cambio}"'

    rfc_ord = rfc_ordenante or cfdi_rfc

    dr_block = ""
    if con_docto:
        dr_block = f'''
      <pagos:DoctoRelacionado IdDocumento="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        MonedaDR="MXN" MetodoDePagoDR="PUE"
        ImpSaldoAnt="{saldo_ant}" ImpPagado="{imp_pagado}" ImpSaldoInsoluto="{saldo_insoluto}"
        ObjetoImpDR="01"/>'''

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4">',
        f'  <cfdi:Emisor Rfc="{cfdi_rfc}"/>',
        '  <cfdi:Complemento>',
        '    <pagos:Pagos xmlns:pagos="http://www.sat.gob.mx/pagos" Version="1.1">',
        f'      <pagos:Pago FechaPago="2025-01-15" FormaPagoP="{forma_pago}"',
        f'        MonedaP="{moneda}" Monto="{monto}"{tc_line}',
        f'        RfcEmisorCtaOrd="{rfc_ord}"/>',
        dr_block,
        '    </pagos:Pagos>',
        '  </cfdi:Complemento>',
        '</cfdi:Comprobante>',
    ]
    return "\n".join(lines).encode()


# ── Parser Tests ──

class TestPagosParser:
    def test_parse_valid(self):
        data = parse_pagos_bytes(_pagos_xml())
        assert data is not None
        assert data.version == "1.1"
        assert len(data.pagos) == 1
        assert data.pagos[0].monto == Decimal("5000")
        assert data.cfdi_emisor_rfc == "EABC123456789"

    def test_parse_with_docto_relacionado(self):
        data = parse_pagos_bytes(_pagos_xml())
        pago = data.pagos[0]
        assert len(pago.documentos_relacionados) == 1
        doc = pago.documentos_relacionados[0]
        assert doc.imp_pagado == Decimal("5000")
        assert doc.imp_saldo_ant == Decimal("10000")

    def test_parse_no_pagos_complement(self):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"></cfdi:Comprobante>'
        data = parse_pagos_bytes(xml)
        assert data is None

    def test_parse_invalid_xml(self):
        with pytest.raises(Exception):
            parse_pagos_bytes(b"not xml")

    def test_to_dict(self):
        data = parse_pagos_bytes(_pagos_xml())
        d = data.to_dict()
        assert d["version"] == "1.1"
        assert len(d["pagos"]) == 1


# ── Validator Tests ──

class TestPagosValidators:
    def test_validate_valid(self):
        data = parse_pagos_bytes(_pagos_xml())
        errors = validate_pagos(data)
        assert errors == []

    def test_validate_none(self):
        errors = validate_pagos(None)
        assert len(errors) == 1

    def test_monto_zero(self):
        data = parse_pagos_bytes(_pagos_xml(monto="0"))
        errors = validate_monto_pago(data)
        assert len(errors) > 0

    def test_monto_negative(self):
        data = parse_pagos_bytes(_pagos_xml(monto="-100"))
        errors = validate_monto_pago(data)
        assert len(errors) > 0

    def test_forma_pago_valid(self):
        data = parse_pagos_bytes(_pagos_xml(forma_pago="03"))
        errors = validate_forma_pago(data)
        assert errors == []

    def test_forma_pago_invalid(self):
        data = parse_pagos_bytes(_pagos_xml(forma_pago="99"))
        errors = validate_forma_pago(data)
        assert len(errors) > 0

    def test_moneda_valid(self):
        data = parse_pagos_bytes(_pagos_xml(moneda="MXN"))
        errors = validate_moneda(data)
        assert errors == []

    def test_moneda_invalid(self):
        data = parse_pagos_bytes(_pagos_xml(moneda="XYZ"))
        errors = validate_moneda(data)
        assert len(errors) > 0

    def test_tipo_cambio_mxn_ok(self):
        data = parse_pagos_bytes(_pagos_xml(moneda="MXN", tipo_cambio="1"))
        errors = validate_tipo_cambio(data)
        assert errors == []

    def test_tipo_cambio_mxn_wrong(self):
        data = parse_pagos_bytes(_pagos_xml(moneda="MXN", tipo_cambio="20"))
        errors = validate_tipo_cambio(data)
        assert len(errors) > 0

    def test_tipo_cambio_usd_required(self):
        data = parse_pagos_bytes(_pagos_xml(moneda="USD"))
        errors = validate_tipo_cambio(data)
        assert len(errors) > 0

    def test_docto_relacionado_consistency(self):
        data = parse_pagos_bytes(_pagos_xml(
            saldo_ant="10000", imp_pagado="5000", saldo_insoluto="5000"))
        errors = validate_doctos_relacionados(data)
        assert errors == []

    def test_docto_relacionado_inconsistency(self):
        data = parse_pagos_bytes(_pagos_xml(
            saldo_ant="10000", imp_pagado="5000", saldo_insoluto="6000"))
        errors = validate_doctos_relacionados(data)
        assert len(errors) > 0

    def test_rfc_emisor_match(self):
        data = parse_pagos_bytes(_pagos_xml())
        errors = validate_rfc_emisor(data)
        assert errors == []

    def test_rfc_emisor_no_match(self):
        data = parse_pagos_bytes(_pagos_xml(rfc_ordenante="XXX999999999"))
        errors = validate_rfc_emisor(data)
        assert len(errors) > 0

    def test_tipo_cadena_pago_valid(self):
        data = parse_pagos_bytes(_pagos_xml())
        # Set tipo_cad_pago on the pago
        data.pagos[0].tipo_cad_pago = "01"
        errors = validate_tipo_cadena_pago(data)
        assert errors == []


# ── Route Tests ──

class TestPagosRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.pagos.routes import build_pagos_router
        from fastapi import FastAPI
        app = FastAPI()
        router = build_pagos_router()
        app.include_router(router)
        return TestClient(app)

    def test_parse_pagos(self, client):
        xml = _pagos_xml()
        resp = client.post("/pagos/parse",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["pagos"]["version"] == "1.1"

    def test_parse_empty(self, client):
        resp = client.post("/pagos/parse",
                           files={"file": ("test.xml", io.BytesIO(b""), "application/xml")})
        assert resp.status_code == 400

    def test_parse_no_pagos(self, client):
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"></cfdi:Comprobante>'
        resp = client.post("/pagos/parse",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 404

    def test_validate_pagos_route(self, client):
        xml = _pagos_xml()
        resp = client.post("/pagos/validate",
                           files={"file": ("test.xml", io.BytesIO(xml), "application/xml")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_catalog(self, client):
        resp = client.get("/pagos/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "forma_pago" in data
        assert "monedas_iso" in data
        assert "MXN" in data["monedas_iso"]
