# -*- coding: utf-8 -*-
"""test_sat_validator_real.py — Pruebas de contrato para el SATValidator REAL
(FIS-024, cliente SOAP contra el WSDL público de Verificación de CFDI).

TODAS estas pruebas corren EXCLUSIVAMENTE contra el simulador local
`tests/fixtures/sat_consulta_cfdi_simulator.py`. Ninguna toca
`consultaqr.facturaelectronica.sat.gob.mx` ni ningún otro dominio real
(misma regla no negociable que `tests/test_facturapi_adapter.py` para
FacturAPI). Ver el docstring de `b2b_ai/sat/validator.py` para el contrato
real investigado contra el WSDL público y el PDF oficial del SAT.
"""
from __future__ import annotations

import httpx
import pytest

from b2b_ai.sat.validator import (
    SAT_VALIDATOR_VERIFICADO_CONTRA_REAL,
    SATValidator,
)
from tests.fixtures.sat_consulta_cfdi_simulator import (
    FOLIO_ESTADO_DESCONOCIDO_TEST,
    FOLIO_EXPRESION_INVALIDA_TEST,
    FOLIO_NO_ENCONTRADO_TEST,
    FOLIO_SOAP_FAULT_TEST,
    FOLIO_XML_INVALIDO_TEST,
    start_sat_consulta_cfdi_simulator,
)

PORT = 18781
SIMULATOR_URL = f"http://127.0.0.1:{PORT}"

RFC_EMISOR = "AAA010101AAA"
RFC_RECEPTOR = "XAXX010101000"
FOLIO_VIGENTE = "12345678-1234-1234-1234-123456789011"
FOLIO_CANCELADO = "12345678-1234-1234-1234-123456789010"  # termina en '0'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sat_simulator():
    server = start_sat_consulta_cfdi_simulator(port=PORT)
    yield SIMULATOR_URL
    server.shutdown()


@pytest.fixture()
def validator(sat_simulator) -> SATValidator:
    return SATValidator(base_url=sat_simulator)


# ---------------------------------------------------------------------------
# Honestidad: nunca "verificado contra real", siempre "simulado": False
# (no confundir con "no hace nada" — sí llama de verdad al simulador).
# ---------------------------------------------------------------------------
def test_verificado_contra_real_es_false():
    assert SAT_VALIDATOR_VERIFICADO_CONTRA_REAL is False


# ---------------------------------------------------------------------------
# Fail-closed: datos insuficientes -> nunca se intenta la llamada de red.
# ---------------------------------------------------------------------------
def test_check_status_folio_vacio_no_llama_red():
    class _Boom:
        def post(self, *a, **k):
            raise AssertionError("no debía llamarse")

    v = SATValidator(http_client=_Boom())
    res = v.check_status("")
    assert res["ok"] is False
    assert "folio_fiscal" in res["error"]


@pytest.mark.parametrize("kwargs,falta", [
    ({}, "rfc_emisor"),
    ({"rfc_emisor": RFC_EMISOR}, "rfc_receptor"),
    ({"rfc_emisor": RFC_EMISOR, "rfc_receptor": RFC_RECEPTOR}, "total"),
])
def test_check_status_datos_insuficientes_no_llama_red(kwargs, falta):
    class _Boom:
        def post(self, *a, **k):
            raise AssertionError("no debía llamarse")

    v = SATValidator(http_client=_Boom())
    res = v.check_status(FOLIO_VIGENTE, **kwargs)
    assert res["ok"] is False
    assert falta in res["error"]
    assert res["simulado"] is False


# ---------------------------------------------------------------------------
# Camino feliz real (contra el simulador)
# ---------------------------------------------------------------------------
def test_check_status_vigente(validator):
    res = validator.check_status(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is True
    assert res["estado"] == "vigente"
    assert res["simulado"] is False
    assert res["verificado_contra_real"] is False
    assert res["codigo_estatus"].startswith("S")
    assert res["es_cancelable"] == "Cancelable sin aceptación"


def test_check_status_cancelado(validator):
    res = validator.check_status(FOLIO_CANCELADO, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is True
    assert res["estado"] == "cancelado"
    assert res["estatus_cancelacion"] == "Cancelado sin aceptación"


def test_check_status_no_encontrado(validator):
    res = validator.check_status(FOLIO_NO_ENCONTRADO_TEST, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is True
    assert res["estado"] == "no_encontrado"
    assert "602" in res["codigo_estatus"]


def test_check_status_total_se_formatea_a_6_decimales(validator):
    # 1000 (int) y 1000.0 (float) deben producir la misma expresionImpresa
    # real (tt=1000.000000) — solo lo comprobamos indirectamente: ambos
    # deben resolver igual contra el simulador.
    res_int = validator.check_status(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000)
    res_float = validator.check_status(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res_int["estado"] == res_float["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Rechazos reales del SAT: nunca se traducen a un estatus de CFDI inventado.
# ---------------------------------------------------------------------------
def test_check_status_expresion_invalida_no_es_un_estatus_de_cfdi(validator):
    res = validator.check_status(FOLIO_EXPRESION_INVALIDA_TEST, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False
    assert "estado" not in res
    assert "601" in res["error"]


# ---------------------------------------------------------------------------
# Fail-closed ante respuestas reales anómalas: nunca se fabrica un veredicto.
# ---------------------------------------------------------------------------
def test_check_status_estado_desconocido_falla_cerrado(validator):
    res = validator.check_status(FOLIO_ESTADO_DESCONOCIDO_TEST, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False
    assert "estado" not in res
    assert "Suspendido" in res["error"]


def test_check_status_soap_fault_falla_cerrado(validator):
    res = validator.check_status(FOLIO_SOAP_FAULT_TEST, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False
    assert "Fault" in res["error"] or "500" in res["error"]


def test_check_status_xml_invalido_falla_cerrado(validator):
    res = validator.check_status(FOLIO_XML_INVALIDO_TEST, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False
    assert "XML" in res["error"]


def test_check_status_total_no_numerico_falla_cerrado(validator):
    res = validator.check_status(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, "no-es-un-numero")
    assert res["ok"] is False
    assert "total" in res["error"]


def test_check_status_error_de_red_falla_cerrado():
    # Puerto sin nada escuchando -> error de conexión real de httpx.
    v = SATValidator(base_url="http://127.0.0.1:1", timeout_seconds=2.0)
    res = v.check_status(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False
    assert res["simulado"] is False
    assert res["verificado_contra_real"] is False


def test_check_status_http_500_generico_falla_cerrado(validator):
    """Un cliente inyectado que devuelve 500 sin ser un SOAP Fault
    reconocible también debe fallar cerrado, no fabricar un estatus."""
    class _Cliente500:
        def post(self, *a, **k):
            return httpx.Response(500, text="Internal Server Error")

    v = SATValidator(http_client=_Cliente500())
    res = v.check_status(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False
    assert "500" in res["error"]


# ---------------------------------------------------------------------------
# verify_cfdi / verify_chain: honestidad de la "cadena de custodia".
# ---------------------------------------------------------------------------
def test_verify_cfdi_vigente(validator):
    res = validator.verify_cfdi(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is True
    assert res["valido"] is True
    assert res["estado"] == "vigente"
    assert res["cadena"]["ok"] is True
    assert len(res["cadena"]["cadena"]) == 1
    assert res["cadena"]["cadena"][0]["evento"] == "Consulta de estatus (SAT ConsultaCFDIService)"


def test_verify_chain_no_fabrica_eventos_si_faltan_datos():
    v = SATValidator(http_client=object())  # nunca debería usarse
    chain = v.verify_chain(FOLIO_VIGENTE)  # sin rfc/total
    assert chain["ok"] is False
    assert chain["cadena"] == []
    assert chain["estado"] is None


def test_verify_chain_incluye_acuse_de_timbrado_si_se_pasa(validator):
    acuse = {"fecha_timbrado": "2026-01-01T10:00:00", "cadena_timbre": "sello-pac-123"}
    res = validator.verify_cfdi(FOLIO_VIGENTE, RFC_EMISOR, RFC_RECEPTOR, 1000.0,
                                acuse_timbrado=acuse)
    eventos = res["cadena"]["cadena"]
    assert len(eventos) == 2
    assert eventos[0]["evento"] == "Timbrado"
    assert eventos[0]["autoridad"] == "PAC"
    assert eventos[0]["detalle"] == "sello-pac-123"
    assert eventos[1]["evento"] == "Consulta de estatus (SAT ConsultaCFDIService)"


def test_verify_chain_cancelado_ok_false(validator):
    res = validator.verify_chain(FOLIO_CANCELADO, RFC_EMISOR, RFC_RECEPTOR, 1000.0)
    assert res["ok"] is False  # solo "vigente" cuenta como cadena válida
    assert res["estado"] == "cancelado"
    assert res["sello_valido"] is False


# ---------------------------------------------------------------------------
# verify_rfc: solo formato, nunca existencia fabricada (sin cambios de FIS-024
# más allá del wording — se cubre aquí por completitud del módulo real).
# ---------------------------------------------------------------------------
def test_verify_rfc_formato_invalido():
    v = SATValidator()
    res = v.verify_rfc("no-es-rfc")
    assert res["valido"] is False


def test_verify_rfc_generico_no_registrado():
    v = SATValidator()
    res = v.verify_rfc("xaxx010101000")
    assert res["valido"] is True
    assert res["registrado"] is False


def test_verify_rfc_no_generico_existencia_desconocida():
    v = SATValidator()
    res = v.verify_rfc(RFC_EMISOR)
    assert res["valido"] is True
    assert res["registrado"] is None
    assert res["simulado"] is False
