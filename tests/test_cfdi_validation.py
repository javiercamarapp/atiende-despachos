# -*- coding: utf-8 -*-
"""Tests for POST /api/v1/cfdi/validate endpoint."""
import io
import pytest
from fastapi.testclient import TestClient


SAMPLE_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
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

# CFDI sin sello (debe dar INVÁLIDO)
INVALID_NO_SELLO = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Serie="X" Folio="999"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="500.00" Total="580.00">
    <cfdi:Emisor Rfc="PABD850101AB1" Nombre="EMPRESA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            Descripcion="Servicio" ValorUnitario="500.00" Importe="500.00"/>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="80.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="500.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="80.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
</cfdi:Comprobante>"""

# CFDI válido pero con RFC inválido → CON OBSERVACIONES
OBS_CFDI_RFC_BAD = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Serie="Y" Folio="200"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Total="1160.00"
    Sello="FAKESELLO1234" NoCertificado="00001000000000000000">
    <cfdi:Emisor Rfc="BAD_RFC" Nombre="EMPRESA" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            Descripcion="Servicio" ValorUnitario="1000.00" Importe="1000.00"/>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1"
            UUID="660e8400-e29b-41d4-a716-446655440001"
            FechaTimbrado="2026-07-03T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="XX" NoCertificado="00001000000000000000" SelloSAT="YY"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

# No es un CFDI (root wrong)
NOT_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<Root><Data>Not a CFDI</Data></Root>"""

# Malformed XML
MALFORMED = """not xml at all <>&"""


@pytest.fixture
def client():
    """FastAPI test client with API-key dependency overridden."""
    from b2b_ai.api.app import create_app
    from b2b_ai.api.routes.cfdi_validation import _require_api_key

    app = create_app()

    # Override the API-key dependency so tests can send "test-api-key"
    async def _no_op_key() -> str:
        return "test-api-key"

    app.dependency_overrides[_require_api_key] = _no_op_key
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestValidateEndpoint:
    """Tests for POST /api/v1/cfdi/validate."""

    # ---- Helpers ----

    def _api_key_headers(self):
        return {"X-API-Key": "test-api-key"}

    # ---- 200 OK — CFDI válido ----

    def test_valid_cfdi_text_plain(self, client):
        """CFDI 4.0 válido via text/plain → status VALIDO."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=SAMPLE_CFDI,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "VALIDO"
        assert data["comprobante"]["serie"] == "D"
        assert data["comprobante"]["folio"] == "100"
        assert data["comprobante"]["tipo"] == "I"
        assert data["emisor"]["rfc"] == "PAP850101JKL"
        assert data["emisor"]["nombre"] == "PAPELERIA TEST"
        assert data["receptor"]["rfc"] == "XAXX010101000"
        assert data["receptor"]["uso_cfdi"] == "G03"
        assert len(data["conceptos"]) == 1
        assert data["conceptos"][0]["descripcion"] == "Papeleria y articulos de oficina"
        assert data["impuestos"]["iva_trasladado"] == 160.0
        assert data["folio_fiscal"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["validacion"]["ok"] is True
        assert data["validacion"]["checks_fail"] == 0
        assert data["validacion"]["diot_reportable"] is True

    def test_valid_cfdi_json_body(self, client):
        """CFDI vía JSON body { xml_content } → VALIDO."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            json={"xml_content": SAMPLE_CFDI},
            headers=self._api_key_headers(),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "VALIDO"
        assert data["comprobante"]["version"] == "4.0"
        assert data["validacion"]["ok"] is True

    def test_valid_cfdi_multipart(self, client):
        """CFDI vía multipart file upload → VALIDO."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            files={"file": ("cfdi.xml", io.BytesIO(SAMPLE_CFDI.encode("utf-8")),
                           "application/xml")},
            headers=self._api_key_headers(),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "VALIDO"
        assert data["emisor"]["rfc"] == "PAP850101JKL"

    # ---- 400 — CFDI inválido / error de parsing ----

    def test_not_cfdi_root(self, client):
        """Root no-Comprobante → 400."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=NOT_CFDI,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 400

    def test_malformed_xml(self, client):
        """XML malformado → 400."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=MALFORMED,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 400

    def test_invalid_no_sello(self, client):
        """CFDI sin sello digital → status INVALIDO."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=INVALID_NO_SELLO,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "INVALIDO"
        assert data["validacion"]["ok"] is False
        assert data["validacion"]["checks_fail"] > 0
        # Sello faltante es el error principal
        assert any(e["code"] == "sello_faltante" for e in data["validacion"]["errores_sat"])

    # ---- 200 — CON OBSERVACIONES ----

    def test_con_observaciones_rfc_invalido(self, client):
        """CFDI con RFC inválido → CON OBSERVACIONES (parsea pero tiene warnings)."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=OBS_CFDI_RFC_BAD,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # RFC emisor inválido → no es VALIDO
        assert data["status"] in ("INVALIDO", "CON_OBSERVACIONES")
        assert data["validacion"]["ok"] is False
        assert any(e["code"] == "rfc_emisor_invalido"
                   for e in data["validacion"]["errores_sat"])

    # ---- 400 — Body vacío ----

    def test_empty_body_text_plain(self, client):
        """Body vacío con text/xml → 400."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content="",
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 400

    def test_empty_json(self, client):
        """JSON body sin xml_content → 400."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            json={},
            headers=self._api_key_headers(),
        )
        assert resp.status_code == 400

    def test_json_missing_xml_content(self, client):
        """JSON body con xml_content null → 400."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            json={"xml_content": None},
            headers=self._api_key_headers(),
        )
        assert resp.status_code == 400

    def test_json_non_string_xml_content(self, client):
        """JSON body con xml_content no-string → 422."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            json={"xml_content": 12345},
            headers=self._api_key_headers(),
        )
        assert resp.status_code == 422

    # ---- 401 — Sin API key ----

    def test_no_api_key(self, client):
        """Sin X-API-Key → 401 o 403."""
        # Remove the override temporarily for this test
        from b2b_ai.api.routes.cfdi_validation import _require_api_key
        from fastapi.testclient import TestClient as TC

        # The test client from the fixture has the override active.
        # We need a clean client without override for this test.
        from b2b_ai.api.app import create_app
        app = create_app()
        clean_client = TC(app)
        resp = clean_client.post(
            "/api/v1/cfdi/validate",
            content=SAMPLE_CFDI,
            headers={"Content-Type": "text/xml"},
        )
        assert resp.status_code in (401, 403)

    # ---- Conceptos e impuestos ----

    def test_conceptos_extraction(self, client):
        """Conceptos extraídos correctamente."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=SAMPLE_CFDI,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        conceptos = data["conceptos"]
        assert len(conceptos) == 1
        assert conceptos[0]["cantidad"] == 1.0
        assert conceptos[0]["valor_unitario"] == 1000.0
        assert conceptos[0]["importe"] == 1000.0
        assert "Papeleria" in conceptos[0]["descripcion"]

    def test_impuestos_extraction(self, client):
        """IVA traducido correctamente."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=SAMPLE_CFDI,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["impuestos"]["iva_trasladado"] == 160.0
        assert data["impuestos"]["isr_retenido"] is None
        assert data["impuestos"]["iva_retenido"] is None

    def test_folio_fiscal_and_timbre(self, client):
        """UUID del TimbreFiscalDigital extraído."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=SAMPLE_CFDI,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["folio_fiscal"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["fecha_timbrado"] == "2026-07-03T10:01:00"

    def test_validacion_checks_structure(self, client):
        """Estructura de validacion.* correcta."""
        resp = client.post(
            "/api/v1/cfdi/validate",
            content=SAMPLE_CFDI,
            headers={**self._api_key_headers(), "Content-Type": "text/xml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        v = data["validacion"]
        assert "ok" in v
        assert "checks_pass" in v
        assert "checks_fail" in v
        assert "errores_sat" in v
        assert "advertencias_sat" in v
        assert "requires_human_review" in v
        assert "diot_reportable" in v
