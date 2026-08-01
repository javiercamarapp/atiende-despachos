# -*- coding: utf-8 -*-
"""
test_nomina.py — Tests del módulo de nómina (parser + validator + routes).

Cobertura:
  - Parse: XML válido (2 demo files), XML sin complemento, XML inválido,
           complemento incompleto, namespace alternativo, whitespace en attrs.
  - Validators: RFC match, fecha range, numDiasPagados, periodicidad,
                tipoNomina, casos vacíos/None, data completa válida.
  - Routes: /parse, /validate, /catalog, archivo vacío, XML inválido.
  - Edge cases: campos vacíos, decimal con espacios, fecha fuera de rango.
"""
from __future__ import annotations

import os
import io
from decimal import Decimal

import pytest
from lxml import etree

from b2b_ai.features.nomina.parser import (
    parse_nomina, parse_nomina_bytes, NominaData,
    NOMINA_NS_URIS, _find_nomina_node,
)
from b2b_ai.features.nomina.validators import (
    validate_nomina, validate_rfc_patron, validate_fechas,
    validate_num_dias_pagados, validate_periodicidad_pago,
    validate_tipo_nomina, PERIODICIDAD_PAGO_CODES, TIPO_NOMINA_CODES,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEMO_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "b2b_ai", "demo-data",
)
DEMO_XML_1 = os.path.join(DEMO_DATA_DIR, "nomina_empleado1.xml")
DEMO_XML_2 = os.path.join(DEMO_DATA_DIR, "nomina_empleado2.xml")


@pytest.fixture
def valid_nomina_data() -> NominaData:
    """NominaData completo y válido para pruebas de validador."""
    return NominaData(
        tipo_nomina="O",
        version="1.2",
        fecha_pago="2026-07-15",
        fecha_inicial_pago="2026-06-15",
        fecha_final_pago="2026-07-14",
        num_dias_pagados=Decimal("30"),
        total_percepciones=Decimal("28000.00"),
        total_deducciones=Decimal("2500.00"),
        registro_patronal="Z-1234567-01",
        rfc_patron_origen="JCCP840101HDA",
        curp="LOHG900101MMCPR01",
        num_empleado="001",
        tipo_jornada="01",
        riesgo_puesto="2",
        periodicidad_pago="04",
        cfdi_emisor_rfc="JCCP840101HDA",
    )


@pytest.fixture
def incomplete_nomina_xml(tmp_path) -> str:
    """Genera XML con complemento Nomina incompleto (sin Emisor/Receptor)."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="N">
    <cfdi:Emisor Rfc="TEST010101AAA" Nombre="Test"/>
    <cfdi:Receptor Rfc="TEST020202BBB" Nombre="Test2"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento>
        <nomina12:Nomina Version="1.2"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
    path = tmp_path / "incomplete.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def no_nomina_xml(tmp_path) -> str:
    """Genera XML CFDI sin complemento de nómina."""
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
    path = tmp_path / "no_nomina.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def alt_ns_nomina_xml(tmp_path) -> str:
    """Genera XML con namespace URI alternativo de nómina."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nom="http://www.sat.gob.mx/nomina"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="N">
    <cfdi:Emisor Rfc="JCCP840101HDA" Nombre="Test"/>
    <cfdi:Receptor Rfc="LOHG900101MNC" Nombre="Test2"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento>
        <nom:Nomina Version="1.2" TipoNomina="O"
            FechaPago="2026-07-15"
            FechaInicialPago="2026-06-15"
            FechaFinalPago="2026-07-14"
            NumDiasPagados="30">
            <nom:Emisor RegistroPatronal="Z-9999999-01"
                RfcPatronOrigen="JCCP840101HDA"/>
            <nom:Receptor Curp="TEST990101ABC" NumEmpleado="999"
                TipoJornada="01" RiesgoPuesto="2"
                PeriodicidadPago="03"/>
        </nom:Nomina>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
    path = tmp_path / "alt_ns.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


@pytest.fixture
def whitespace_nomina_xml(tmp_path) -> str:
    """Genera XML con espacios extra en atributos numéricos."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="N">
    <cfdi:Emisor Rfc="JCCP840101HDA" Nombre="Test"/>
    <cfdi:Receptor Rfc="LOHG900101MNC" Nombre="Test2"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento>
        <nomina12:Nomina Version="1.2" TipoNomina="O"
            FechaPago="2026-07-15"
            FechaInicialPago="2026-06-15"
            FechaFinalPago="2026-07-14"
            NumDiasPagados="  30  "
            TotalPercepciones="  15000.00  ">
            <nomina12:Emisor RegistroPatronal="Z-1234567-01"
                RfcPatronOrigen="JCCP840101HDA"/>
            <nomina12:Receptor Curp="LOHG900101MMCPR01"
                NumEmpleado="001" TipoJornada="01"
                RiesgoPuesto="2" PeriodicidadPago="04"/>
        </nomina12:Nomina>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
    path = tmp_path / "whitespace.xml"
    path.write_text(xml, encoding="utf-8")
    return str(path)


# ===========================================================================
# PARSE TESTS
# ===========================================================================

class TestParseNomina:
    """Tests de parse_nomina() y parse_nomina_bytes()."""

    def test_parse_demo_xml_1(self):
        """Parse completo del primer XML demo (empleado 1)."""
        data = parse_nomina(DEMO_XML_1)
        assert data is not None
        assert data.tipo_nomina == "O"
        assert data.fecha_pago == "2026-07-15"
        assert data.fecha_inicial_pago == "2026-06-15"
        assert data.fecha_final_pago == "2026-07-14"
        assert data.num_dias_pagados == Decimal("30")
        assert data.total_percepciones == Decimal("28000.00")
        assert data.total_deducciones == Decimal("2500.00")
        assert data.registro_patronal == "Z-1234567-01"
        assert data.rfc_patron_origen == "JCCP840101HDA"
        assert data.curp == "LOHG900101MMCPR01"
        assert data.num_empleado == "001"
        assert data.tipo_jornada == "01"
        assert data.riesgo_puesto == "2"
        assert data.periodicidad_pago == "04"
        assert data.cfdi_emisor_rfc == "JCCP840101HDA"

    def test_parse_demo_xml_2(self):
        """Parse completo del segundo XML demo (empleado 2)."""
        data = parse_nomina(DEMO_XML_2)
        assert data is not None
        assert data.num_empleado == "002"
        assert data.total_percepciones == Decimal("20000.00")
        assert data.total_deducciones == Decimal("1500.00")
        assert data.cfdi_emisor_rfc == "JCCP840101HDA"

    def test_parse_returns_none_no_complement(self, no_nomina_xml):
        """Sin complemento de nómina -> None."""
        data = parse_nomina(no_nomina_xml)
        assert data is None

    def test_parse_incomplete_complement(self, incomplete_nomina_xml):
        """Complemento vacío (sin Emisor/Receptor) -> data parcial."""
        data = parse_nomina(incomplete_nomina_xml)
        assert data is not None
        assert data.version == "1.2"
        assert data.tipo_nomina is None
        assert data.rfc_patron_origen is None
        assert data.curp is None

    def test_parse_file_not_found(self):
        """Archivo inexistente -> OSError."""
        with pytest.raises(OSError):
            parse_nomina("/nonexistent/file.xml")

    def test_parse_invalid_xml(self, tmp_path):
        """XML mal formado -> etree.XMLSyntaxError."""
        path = tmp_path / "bad.xml"
        path.write_text("<broken>", encoding="utf-8")
        with pytest.raises(etree.XMLSyntaxError):
            parse_nomina(str(path))

    def test_parse_alt_namespace(self, alt_ns_nomina_xml):
        """Namespace URI alternativo (http://www.sat.gob.mx/nomina) se parsea."""
        data = parse_nomina(alt_ns_nomina_xml)
        assert data is not None
        assert data.tipo_nomina == "O"
        assert data.rfc_patron_origen == "JCCP840101HDA"
        assert data.num_empleado == "999"
        assert data.periodicidad_pago == "03"

    def test_parse_whitespace_in_attrs(self, whitespace_nomina_xml):
        """Espacios extra en atributos numéricos se limpian."""
        data = parse_nomina(whitespace_nomina_xml)
        assert data is not None
        assert data.num_dias_pagados == Decimal("30")
        assert data.total_percepciones == Decimal("15000.00")

    def test_parse_bytes_valid(self):
        """parse_nomina_bytes() funciona con bytes del demo XML 1."""
        with open(DEMO_XML_1, "rb") as f:
            content = f.read()
        data = parse_nomina_bytes(content)
        assert data is not None
        assert data.tipo_nomina == "O"
        assert data.num_empleado == "001"

    def test_parse_bytes_no_nomina(self):
        """parse_nomina_bytes() retorna None si no hay nómina."""
        xml = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"/>'
        data = parse_nomina_bytes(xml)
        assert data is None

    def test_parse_version_extracted(self):
        """La versión del complemento Nomina 1.2 se extrae."""
        data = parse_nomina(DEMO_XML_1)
        assert data.version == "1.2"

    def test_to_dict_serializable(self):
        """NominaData.to_dict() produce dict JSON-serializable."""
        data = parse_nomina(DEMO_XML_1)
        d = data.to_dict()
        # Decimals serializados como str
        assert isinstance(d["num_dias_pagados"], str)
        assert isinstance(d["total_percepciones"], str)
        # Strings plain
        assert isinstance(d["tipo_nomina"], str)
        assert isinstance(d["curp"], str)


# ===========================================================================
# VALIDATOR TESTS
# ===========================================================================

class TestValidateRfcPatron:
    """Tests de validate_rfc_patron()."""

    def test_rfc_match(self, valid_nomina_data):
        """RFC patrón coincide con Emisor CFDI -> sin errores."""
        errors = validate_rfc_patron(valid_nomina_data)
        assert errors == []

    def test_rfc_mismatch(self, valid_nomina_data):
        """RFC patrón NO coincide -> error."""
        valid_nomina_data.rfc_patron_origen = "DIFFERENT0101AAA"
        errors = validate_rfc_patron(valid_nomina_data)
        assert len(errors) == 1
        assert "no coincide" in errors[0]

    def test_rfc_patron_empty(self, valid_nomina_data):
        """RFC patrón vacío -> error."""
        valid_nomina_data.rfc_patron_origen = None
        errors = validate_rfc_patron(valid_nomina_data)
        assert len(errors) == 1
        assert "vacío" in errors[0]

    def test_cfdi_emisor_rfc_missing(self, valid_nomina_data):
        """Sin RFC del emisor CFDI -> sin error (solo advertencia implícita)."""
        valid_nomina_data.cfdi_emisor_rfc = None
        errors = validate_rfc_patron(valid_nomina_data)
        assert errors == []


class TestValidateFechas:
    """Tests de validate_fechas()."""

    def test_dates_valid(self, valid_nomina_data):
        """Fechas correctas dentro del rango -> sin errores."""
        errors = validate_fechas(valid_nomina_data)
        assert errors == []

    def test_pago_before_inicial(self, valid_nomina_data):
        """FechaPago anterior a FechaInicialPago -> error."""
        valid_nomina_data.fecha_pago = "2026-06-10"
        errors = validate_fechas(valid_nomina_data)
        assert any("fuera del rango" in e for e in errors)

    def test_pago_after_final(self, valid_nomina_data):
        """FechaPago posterior a FechaFinalPago -> error."""
        valid_nomina_data.fecha_pago = "2026-07-20"
        errors = validate_fechas(valid_nomina_data)
        assert any("fuera del rango" in e for e in errors)

    def test_pago_on_initial(self, valid_nomina_data):
        """FechaPago igual a FechaInicialPago -> válido."""
        valid_nomina_data.fecha_pago = "2026-06-15"
        errors = validate_fechas(valid_nomina_data)
        assert errors == []

    def test_pago_on_final(self, valid_nomina_data):
        """FechaPago igual a FechaFinalPago -> válido."""
        valid_nomina_data.fecha_pago = "2026-07-14"
        errors = validate_fechas(valid_nomina_data)
        assert errors == []

    def test_inicial_after_final(self, valid_nomina_data):
        """FechaInicialPago posterior a FechaFinalPago -> error."""
        valid_nomina_data.fecha_inicial_pago = "2026-08-01"
        errors = validate_fechas(valid_nomina_data)
        assert any("posterior" in e for e in errors)

    def test_missing_fecha_pago(self, valid_nomina_data):
        """FechaPago ausente -> error."""
        valid_nomina_data.fecha_pago = None
        errors = validate_fechas(valid_nomina_data)
        assert any("FechaPago" in e for e in errors)

    def test_missing_all_dates(self):
        """Todas las fechas None -> errores de ausencia."""
        data = NominaData()
        errors = validate_fechas(data)
        assert len(errors) >= 2  # Al menos Pago e Inicial


class TestValidateNumDiasPagados:
    """Tests de validate_num_dias_pagados()."""

    def test_dias_valid(self, valid_nomina_data):
        """30 días en periodo de 30 días naturales -> válido."""
        errors = validate_num_dias_pagados(valid_nomina_data)
        assert errors == []

    def test_dias_zero(self, valid_nomina_data):
        """NumDiasPagados = 0 -> error."""
        valid_nomina_data.num_dias_pagados = Decimal("0")
        errors = validate_num_dias_pagados(valid_nomina_data)
        assert any("mayor a 0" in e for e in errors)

    def test_dias_negative(self, valid_nomina_data):
        """NumDiasPagados negativo -> error."""
        valid_nomina_data.num_dias_pagados = Decimal("-5")
        errors = validate_num_dias_pagados(valid_nomina_data)
        assert any("mayor a 0" in e for e in errors)

    def test_dias_exceeds_period(self, valid_nomina_data):
        """NumDiasPagados excede días naturales del periodo -> error."""
        valid_nomina_data.num_dias_pagados = Decimal("45")
        errors = validate_num_dias_pagados(valid_nomina_data)
        assert any("excede" in e for e in errors)

    def test_dias_none(self, valid_nomina_data):
        """NumDiasPagados None -> error de ausencia."""
        valid_nomina_data.num_dias_pagados = None
        errors = validate_num_dias_pagados(valid_nomina_data)
        assert any("ausente" in e for e in errors)

    def test_dias_one_day_period(self, valid_nomina_data):
        """1 día pagado en periodo de 1 día -> válido."""
        valid_nomina_data.fecha_inicial_pago = "2026-07-15"
        valid_nomina_data.fecha_final_pago = "2026-07-15"
        valid_nomina_data.num_dias_pagados = Decimal("1")
        errors = validate_num_dias_pagados(valid_nomina_data)
        assert errors == []


class TestValidatePeriodicidad:
    """Tests de validate_periodicidad_pago()."""

    def test_valid_codes(self):
        """Todos los códigos SAT válidos pasan validación."""
        for code in PERIODICIDAD_PAGO_CODES:
            data = NominaData(periodicidad_pago=code)
            errors = validate_periodicidad_pago(data)
            assert errors == [], f"Code {code} should be valid"

    def test_invalid_code(self):
        """Código inexistente -> error."""
        data = NominaData(periodicidad_pago="99")
        errors = validate_periodicidad_pago(data)
        assert len(errors) == 1
        assert "válido" in errors[0]

    def test_empty_code(self):
        """Periodicidad vacía -> error."""
        data = NominaData(periodicidad_pago="")
        errors = validate_periodicidad_pago(data)
        assert any("ausente" in e for e in errors)

    def test_none_code(self):
        """Periodicidad None -> error."""
        data = NominaData(periodicidad_pago=None)
        errors = validate_periodicidad_pago(data)
        assert any("ausente" in e for e in errors)


class TestValidateTipoNomina:
    """Tests de validate_tipo_nomina()."""

    def test_ordinaria(self, valid_nomina_data):
        """TipoNomina 'O' -> válido."""
        errors = validate_tipo_nomina(valid_nomina_data)
        assert errors == []

    def test_extraordinaria(self, valid_nomina_data):
        """TipoNomina 'E' -> válido."""
        valid_nomina_data.tipo_nomina = "E"
        errors = validate_tipo_nomina(valid_nomina_data)
        assert errors == []

    def test_invalid_tipo(self, valid_nomina_data):
        """TipoNomina inválido -> error."""
        valid_nomina_data.tipo_nomina = "X"
        errors = validate_tipo_nomina(valid_nomina_data)
        assert len(errors) == 1
        assert "no es válido" in errors[0]

    def test_none_tipo(self, valid_nomina_data):
        """TipoNomina None -> error."""
        valid_nomina_data.tipo_nomina = None
        errors = validate_tipo_nomina(valid_nomina_data)
        assert any("ausente" in e for e in errors)


class TestValidateNominaFull:
    """Tests del validador maestro validate_nomina()."""

    def test_valid_data(self, valid_nomina_data):
        """Data completa y válida -> lista de errores vacía."""
        errors = validate_nomina(valid_nomina_data)
        assert errors == []

    def test_none_data(self):
        """Data None -> error de ausencia."""
        errors = validate_nomina(None)
        assert len(errors) == 1
        assert "No se encontró" in errors[0]

    def test_multiple_errors(self, valid_nomina_data):
        """Múltiples errores se acumulan."""
        valid_nomina_data.rfc_patron_origen = "WRONG"
        valid_nomina_data.periodicidad_pago = "99"
        valid_nomina_data.tipo_nomina = "Z"
        errors = validate_nomina(valid_nomina_data)
        assert len(errors) >= 3


# ===========================================================================
# ROUTE TESTS
# ===========================================================================

class TestNominaRoutes:
    """Tests de los endpoints FastAPI /nomina/*."""

    @pytest.fixture
    def client(self):
        """TestClient FastAPI con el router de nómina registrado."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from b2b_ai.features.nomina.routes import build_nomina_router

        app = FastAPI()
        app.include_router(build_nomina_router())
        return TestClient(app)

    def test_catalog_endpoint(self, client):
        """GET /nomina/catalog retorna catálogos SAT."""
        r = client.get("/nomina/catalog")
        assert r.status_code == 200
        body = r.json()
        assert "periodicidad_pago" in body
        assert "03" in body["periodicidad_pago"]
        assert body["periodicidad_pago"]["03"] == "Mensual"
        assert "tipo_nomina" in body
        assert body["tipo_nomina"]["O"] == "Ordinaria"
        assert "tipo_jornada" in body
        assert "riesgo_puesto" in body

    def test_parse_valid_xml(self, client):
        """POST /nomina/parse con XML válido retorna datos."""
        with open(DEMO_XML_1, "rb") as f:
            r = client.post("/nomina/parse", files={"file": ("nomina.xml", f, "application/xml")})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["nomina"]["tipo_nomina"] == "O"
        assert body["nomina"]["num_empleado"] == "001"

    def test_parse_no_nomina(self, client, no_nomina_xml):
        """POST /nomina/parse sin complemento -> 404."""
        with open(no_nomina_xml, "rb") as f:
            r = client.post("/nomina/parse", files={"file": ("cfdi.xml", f, "application/xml")})
        assert r.status_code == 404
        assert "Nómina 1.2" in r.json()["detail"]

    def test_parse_empty_file(self, client):
        """POST /nomina/parse con archivo vacío -> 400."""
        r = client.post("/nomina/parse", files={"file": ("empty.xml", b"", "application/xml")})
        assert r.status_code == 400
        assert "vacío" in r.json()["detail"]

    def test_parse_invalid_xml(self, client):
        """POST /nomina/parse con XML mal formado -> 422."""
        r = client.post("/nomina/parse", files={"file": ("bad.xml", b"<broken>", "application/xml")})
        assert r.status_code == 422
        assert "parsear" in r.json()["detail"]

    def test_validate_valid_xml(self, client):
        """POST /nomina/validate con XML válido -> ok=True, errors vacío."""
        with open(DEMO_XML_1, "rb") as f:
            r = client.post("/nomina/validate", files={"file": ("nomina.xml", f, "application/xml")})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["errors"] == []

    def test_validate_empty_file(self, client):
        """POST /nomina/validate con archivo vacío -> 400."""
        r = client.post("/nomina/validate", files={"file": ("empty.xml", b"", "application/xml")})
        assert r.status_code == 400

    def test_validate_invalid_xml(self, client):
        """POST /nomina/validate con XML mal formado -> 422."""
        r = client.post("/nomina/validate", files={"file": ("bad.xml", b"<x", "application/xml")})
        assert r.status_code == 422

    def test_parse_demo_xml_2(self, client):
        """POST /nomina/parse con segundo demo XML."""
        with open(DEMO_XML_2, "rb") as f:
            r = client.post("/nomina/parse", files={"file": ("nomina2.xml", f, "application/xml")})
        assert r.status_code == 200
        body = r.json()
        assert body["nomina"]["num_empleado"] == "002"
        assert body["nomina"]["total_percepciones"] == "20000.00"

    def test_validate_incomplete_complement(self, client, incomplete_nomina_xml):
        """POST /nomina/validate con complemento incompleto -> múltiples errores."""
        with open(incomplete_nomina_xml, "rb") as f:
            r = client.post("/nomina/validate", files={"file": ("inc.xml", f, "application/xml")})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert len(body["errors"]) > 0

    def test_catalog_has_all_sections(self, client):
        """GET /nomina/catalog tiene las 4 secciones del catálogo."""
        r = client.get("/nomina/catalog")
        body = r.json()
        assert len(body) == 4
        assert len(body["periodicidad_pago"]) == 8
        assert len(body["tipo_nomina"]) == 2


# ===========================================================================
# EDGE CASE TESTS
# ===========================================================================

class TestEdgeCases:
    """Tests de casos extremos y valores límite."""

    def test_empty_cfdi_emisor_rfc_in_xml(self, tmp_path):
        """CFDI con Emisor sin RFC -> cfdi_emisor_rfc None."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="N">
    <cfdi:Emisor Nombre="Test"/>
    <cfdi:Receptor Rfc="X" Nombre="Test2"/>
    <cfdi:Concepts/>
    <cfdi:Complemento>
        <nomina12:Nomina Version="1.2" TipoNomina="O"
            FechaPago="2026-07-15"
            FechaInicialPago="2026-06-15"
            FechaFinalPago="2026-07-14"
            NumDiasPagados="1">
            <nomina12:Emisor RegistroPatronal="Z-123"/>
            <nomina12:Receptor Curp="X" NumEmpleado="1"/>
        </nomina12:Nomina>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = tmp_path / "no_rfc.xml"
        path.write_text(xml, encoding="utf-8")
        data = parse_nomina(str(path))
        assert data is not None
        assert data.cfdi_emisor_rfc is None

    def test_single_day_period(self):
        """Periodo de 1 día, 1 día pagado -> válido."""
        data = NominaData(
            fecha_pago="2026-07-15",
            fecha_inicial_pago="2026-07-15",
            fecha_final_pago="2026-07-15",
            num_dias_pagados=Decimal("1"),
            rfc_patron_origen="TEST",
            cfdi_emisor_rfc="TEST",
            tipo_nomina="O",
            periodicidad_pago="03",
        )
        errors = validate_nomina(data)
        assert errors == []

    def test_periodo_bimestral(self):
        """Periodicidad bimestral (04) -> válido."""
        data = NominaData(
            tipo_nomina="O",
            fecha_pago="2026-07-15",
            fecha_inicial_pago="2026-06-15",
            fecha_final_pago="2026-07-14",
            num_dias_pagados=Decimal("30"),
            rfc_patron_origen="TEST",
            cfdi_emisor_rfc="TEST",
            periodicidad_pago="04",
        )
        errors = validate_nomina(data)
        assert errors == []

    def test_extraordinaria_type(self):
        """TipoNomina E (Extraordinaria) -> válido."""
        data = NominaData(
            tipo_nomina="E",
            fecha_pago="2026-12-20",
            fecha_inicial_pago="2026-12-20",
            fecha_final_pago="2026-12-20",
            num_dias_pagados=Decimal("1"),
            rfc_patron_origen="TEST",
            cfdi_emisor_rfc="TEST",
            periodicidad_pago="08",
        )
        errors = validate_nomina(data)
        assert errors == []

    def test_whitespace_in_rfc(self, valid_nomina_data):
        """RFC con espacios -> match exacto requiere strip."""
        valid_nomina_data.rfc_patron_origen = "  JCCP840101HDA  "
        # The parser strips, but if set manually it doesn't match
        errors = validate_rfc_patron(valid_nomina_data)
        assert len(errors) == 1  # No match because of spaces

    def test_total_percepciones_zero(self, tmp_path):
        """TotalPercepciones = 0 en XML -> parsea sin error."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    Version="4.0" Fecha="2026-07-15T08:00:00"
    TipoDeComprobante="N">
    <cfdi:Emisor Rfc="T" Nombre="T"/>
    <cfdi:Receptor Rfc="R" Nombre="R"/>
    <cfdi:Conceptos/>
    <cfdi:Complemento>
        <nomina12:Nomina Version="1.2" TipoNomina="O"
            FechaPago="2026-07-15"
            FechaInicialPago="2026-07-01"
            FechaFinalPago="2026-07-15"
            NumDiasPagados="15"
            TotalPercepciones="0.00"
            TotalDeducciones="0.00">
            <nomina12:Emisor RegistroPatronal="Z-1"/>
            <nomina12:Receptor Curp="X" NumEmpleado="1"/>
        </nomina12:Nomina>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        path = tmp_path / "zero_totals.xml"
        path.write_text(xml, encoding="utf-8")
        data = parse_nomina(str(path))
        assert data.total_percepciones == Decimal("0.00")
        assert data.total_deducciones == Decimal("0.00")

    def test_riesgo_puesto_values(self):
        """Todos los códigos de riesgo (1-5) son válidos en el catálogo."""
        from b2b_ai.features.nomina.validators import RIESGO_PUESTO_CODES
        for code in RIESGO_PUESTO_CODES:
            assert code in {"1", "2", "3", "4", "5"}

    def test_tipo_jornada_values(self):
        """Catálogo de tipo jornada tiene códigos SAT esperados."""
        from b2b_ai.features.nomina.validators import TIPO_JORNADA_CODES
        assert "01" in TIPO_JORNADA_CODES
        assert "03" in TIPO_JORNADA_CODES
        assert len(TIPO_JORNADA_CODES) >= 10
