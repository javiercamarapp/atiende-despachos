# -*- coding: utf-8 -*-
"""test_facturapi_adapter.py — Pruebas de contrato para FacturapiAdapter.

TODAS estas pruebas corren EXCLUSIVAMENTE contra el simulador local
`tests/fixtures/facturapi_simulator.py`. Ninguna toca facturapi.io ni ningún
otro dominio real (misma regla no negociable que
`tests/test_sat_portal_rpa_driver.py` para el SAT). Ver el docstring de
`b2b_ai/integrations/sat/pacs/facturapi_adapter.py` para el contrato real
investigado contra la documentación pública de FacturAPI.
"""
from __future__ import annotations

import pytest

from b2b_ai.integrations.sat.adapter import SATAdapterError
from b2b_ai.integrations.sat.models import (
    CancelacionRequest,
    CFDIRequest,
    CFDIStatus,
    ContabilidadElectronica,
    TipoCancelacion,
)
from b2b_ai.integrations.sat.pacs.facturapi_adapter import FacturapiAdapter

PORT = 18777
SIMULATOR_URL = f"http://127.0.0.1:{PORT}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def facturapi_simulator():
    from tests.fixtures.facturapi_simulator import (
        FacturapiSimulatorHandler,
        start_facturapi_simulator,
    )
    FacturapiSimulatorHandler.INVOICES = {}
    server = start_facturapi_simulator(port=PORT)
    yield SIMULATOR_URL
    server.shutdown()


@pytest.fixture()
def cfdi_request() -> CFDIRequest:
    return CFDIRequest(
        rfc_emisor="AAA010101AAA",
        rfc_receptor="XAXX010101000",
        subtotal=1000.0,
        iva=160.0,
        total=1160.0,
        conceptos=[{
            "descripcion": "Servicio de consultoría",
            "clave_prod_serv": "80101500",
            "cantidad": 1,
            "valor_unitario": 1000.0,
        }],
    )


def _adapter_configurado(simulator_url: str) -> FacturapiAdapter:
    from tests.fixtures.facturapi_simulator import VALID_API_KEY
    adapter = FacturapiAdapter(
        config={"api_key": VALID_API_KEY, "pac_name": "facturapi"},
        base_url=simulator_url,
    )
    assert adapter.connect() is True
    return adapter


# ---------------------------------------------------------------------------
# Fail-closed: sin API key configurada
# ---------------------------------------------------------------------------
def test_no_configurado_es_fail_closed():
    adapter = FacturapiAdapter(config={"api_key": "", "pac_name": "facturapi"})

    assert adapter.is_configured is False
    assert adapter.connect() is False

    with pytest.raises(SATAdapterError) as exc_info:
        adapter.timbrar_cfdi(CFDIRequest(
            rfc_emisor="AAA010101AAA",
            rfc_receptor="XAXX010101000",
            subtotal=100.0,
            total=116.0,
        ))
    assert exc_info.value.code == "NO_CONFIGURADO"


def test_no_configurado_bloquea_cancelar_y_consultar():
    adapter = FacturapiAdapter(config={"api_key": "", "pac_name": "facturapi"})

    with pytest.raises(SATAdapterError) as exc_cancelar:
        adapter.cancelar_cfdi(CancelacionRequest(
            uuid="fake-uuid", motivo=TipoCancelacion.FACTURA_ERRORES, rfc="AAA010101AAA",
        ))
    assert exc_cancelar.value.code == "NO_CONFIGURADO"

    with pytest.raises(SATAdapterError) as exc_consultar:
        adapter.consultar_cfdi("fake-uuid")
    assert exc_consultar.value.code == "NO_CONFIGURADO"


# ---------------------------------------------------------------------------
# Timbrado real (contra el simulador)
# ---------------------------------------------------------------------------
def test_timbrar_cfdi_exitoso(facturapi_simulator, cfdi_request):
    adapter = _adapter_configurado(facturapi_simulator)

    respuesta = adapter.timbrar_cfdi(cfdi_request)

    assert respuesta.exito is True
    assert respuesta.uuid  # UUID fiscal real regresado por el simulador
    assert respuesta.codigo_response == "200"
    assert respuesta.cadena_timbre is not None
    assert respuesta.no_certificado_sat == "00001000000500003416"


def test_timbrar_cfdi_rfc_receptor_invalido_no_finge_exito(facturapi_simulator):
    from tests.fixtures.facturapi_simulator import RFC_TRIGGER_INVALIDO
    adapter = _adapter_configurado(facturapi_simulator)

    solicitud = CFDIRequest(
        rfc_emisor="AAA010101AAA",
        rfc_receptor=RFC_TRIGGER_INVALIDO,
        subtotal=500.0,
        total=580.0,
    )
    respuesta = adapter.timbrar_cfdi(solicitud)

    # El error real del PAC se propaga honestamente: NUNCA se finge éxito.
    assert respuesta.exito is False
    assert respuesta.uuid == ""
    assert respuesta.codigo_response == "400"
    assert "no es válido" in respuesta.mensaje


def test_timbrar_cfdi_api_key_invalida_da_401(facturapi_simulator, cfdi_request):
    adapter = FacturapiAdapter(
        config={"api_key": "sk_test_llave_incorrecta", "pac_name": "facturapi"},
        base_url=facturapi_simulator,
    )
    assert adapter.connect() is True  # connect() no valida la key (ver TODO del módulo)

    respuesta = adapter.timbrar_cfdi(cfdi_request)

    assert respuesta.exito is False
    assert respuesta.codigo_response == "401"


# ---------------------------------------------------------------------------
# Cancelación real (contra el simulador)
# ---------------------------------------------------------------------------
def test_cancelar_cfdi_exitoso(facturapi_simulator, cfdi_request):
    adapter = _adapter_configurado(facturapi_simulator)
    timbrado = adapter.timbrar_cfdi(cfdi_request)
    assert timbrado.exito is True

    resultado = adapter.cancelar_cfdi(CancelacionRequest(
        uuid=timbrado.uuid,
        motivo=TipoCancelacion.FACTURA_CANCELACION,
        rfc="AAA010101AAA",
    ))

    assert resultado["exito"] is True
    assert resultado["cancellation_status"] == "accepted"


def test_cancelar_cfdi_inexistente_da_404(facturapi_simulator):
    adapter = _adapter_configurado(facturapi_simulator)

    resultado = adapter.cancelar_cfdi(CancelacionRequest(
        uuid="00000000-0000-0000-0000-000000000000",
        motivo=TipoCancelacion.FACTURA_CANCELACION,
        rfc="AAA010101AAA",
    ))

    assert resultado["exito"] is False
    assert resultado["codigo_response"] == "404"


def test_cancelar_cfdi_motivo_no_soportado_no_llama_al_pac(facturapi_simulator):
    """motivo '05' existe en TipoCancelacion (otros PACs) pero FacturAPI no
    lo documenta: el adaptador debe rechazarlo localmente sin red."""
    adapter = _adapter_configurado(facturapi_simulator)

    resultado = adapter.cancelar_cfdi(CancelacionRequest(
        uuid="cualquier-uuid",
        motivo=TipoCancelacion.EMISOR_DEFINITIVO,  # "05"
        rfc="AAA010101AAA",
    ))

    assert resultado["exito"] is False
    assert resultado["codigo_response"] == "400"
    assert "no es válido para FacturAPI" in resultado["mensaje"]


# ---------------------------------------------------------------------------
# Consulta real (contra el simulador)
# ---------------------------------------------------------------------------
def test_consultar_cfdi_existente(facturapi_simulator, cfdi_request):
    adapter = _adapter_configurado(facturapi_simulator)
    timbrado = adapter.timbrar_cfdi(cfdi_request)

    cfdi = adapter.consultar_cfdi(timbrado.uuid)

    assert cfdi.uuid == timbrado.uuid
    assert cfdi.status == CFDIStatus.TIMBRADO
    assert cfdi.total == pytest.approx(1000.0)


def test_consultar_cfdi_inexistente_propaga_error(facturapi_simulator):
    adapter = _adapter_configurado(facturapi_simulator)

    with pytest.raises(SATAdapterError) as exc_info:
        adapter.consultar_cfdi("00000000-0000-0000-0000-000000000000")
    assert exc_info.value.code == "invoice_not_found"


# ---------------------------------------------------------------------------
# Capacidades que FacturAPI no ofrece: nunca se simulan.
# ---------------------------------------------------------------------------
def test_consultar_rfc_no_implementado(facturapi_simulator):
    adapter = _adapter_configurado(facturapi_simulator)

    with pytest.raises(NotImplementedError):
        adapter.consultar_rfc("AAA010101AAA")


def test_contabilidad_electronica_no_implementado(facturapi_simulator):
    adapter = _adapter_configurado(facturapi_simulator)

    with pytest.raises(NotImplementedError):
        adapter.contabilidad_electronica(ContabilidadElectronica(
            ejercicio=2026, mes=1, rfc="AAA010101AAA",
        ))
