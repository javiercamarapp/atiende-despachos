# -*- coding: utf-8 -*-
"""test_sat_portal_rpa_driver.py — Pruebas de contrato para SATPortalRPADriver.

TODAS estas pruebas corren EXCLUSIVAMENTE contra el simulador local
`tests/fixtures/sat_portal_simulator.py`. Ninguna toca sat.gob.mx ni ningún
otro dominio *.gob.mx. Ver el docstring de
`b2b_ai/features/declaraciones/sat_portal_rpa_driver.py` para el porqué.

Las pruebas que abren Chromium real están marcadas `computer_use_e2e` (misma
convención que `tests/test_computer_use_e2e.py`) y requieren
`playwright install chromium`. Las pruebas que no necesitan navegador
(guardas de dominio, validación local, gate de confirmación) corren siempre.
"""
import os
import tempfile

import pytest

from b2b_ai.features.declaraciones.sat_portal_rpa_driver import (
    PortalStatus,
    SATPortalRealDomainBlocked,
    SATPortalRPADriver,
    VERIFICADO_CONTRA_SAT_REAL,
    _assert_host_is_not_real_sat,
)
from b2b_ai.features.declaraciones.diot_generator import DIOTGenerator
from b2b_ai.features.declaraciones.engine import DiotRecord, DiotResult

pytestmark_e2e = pytest.mark.computer_use_e2e

PORT = 18766
PORTAL_URL = f"http://127.0.0.1:{PORT}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def cer_key_files(tmp_path):
    """Archivos .cer/.key dummy: el simulador solo comprueba que existan."""
    cer = tmp_path / "fake.cer"
    key = tmp_path / "fake.key"
    cer.write_bytes(b"-----FAKE CERTIFICATE-----")
    key.write_bytes(b"-----FAKE PRIVATE KEY-----")
    return str(cer), str(key)


@pytest.fixture()
def diot_file(tmp_path):
    """DIOT real generado con DIOTGenerator (no reimplementado aquí)."""
    result = DiotResult(
        records=[
            DiotRecord(
                rfc_tercero="ABC010101AB1",
                nombre="Proveedor de Prueba SA de CV",
                tipo_operacion="03",
                monto_neto=10000.0,
                iva_trasladado_16=1600.0,
                fecha="2026-01-15",
            ),
        ],
        periodo="2026-01",
        rfc_contribuyente="XYZ010101AB2",
    )
    gen = DIOTGenerator()
    path = gen.export_txt(result, output_dir=str(tmp_path))
    assert gen.errors == []
    return path


@pytest.fixture(scope="module")
def sat_simulator():
    from tests.fixtures.sat_portal_simulator import SATPortalHandler, start_sat_portal_server
    SATPortalHandler.SESSIONS = {}
    SATPortalHandler.SUBMISSIONS = {}
    server = start_sat_portal_server(port=PORT)
    yield PORTAL_URL
    server.shutdown()


def _make_driver(cer_key_files, password="correct-password", rfc=None, portal_url=PORTAL_URL):
    cer, key = cer_key_files
    return SATPortalRPADriver(
        portal_url=portal_url, cer_path=cer, key_path=key,
        password=password, rfc=rfc, headless=True,
    )


# ---------------------------------------------------------------------------
# 1. Honestidad / guardas — sin navegador
# ---------------------------------------------------------------------------
def test_verificado_contra_sat_real_es_false():
    """La bandera de honestidad debe existir y ser False."""
    assert VERIFICADO_CONTRA_SAT_REAL is False


@pytest.mark.parametrize("url", [
    "https://sat.gob.mx/login",
    "https://declara.sat.gob.mx/algo",
    "https://www.sat.gob.mx/",
    "http://gob.mx",
    "https://cualquier.subdominio.gob.mx/x",
])
def test_bloquea_dominios_reales_gob_mx(url):
    with pytest.raises(SATPortalRealDomainBlocked):
        _assert_host_is_not_real_sat(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:18766",
    "http://localhost:9999",
])
def test_permite_hosts_de_prueba(url):
    _assert_host_is_not_real_sat(url)  # no debe lanzar


def test_constructor_rechaza_url_real_sat(cer_key_files):
    cer, key = cer_key_files
    with pytest.raises(SATPortalRealDomainBlocked):
        SATPortalRPADriver(
            portal_url="https://sat.gob.mx/declaraciones",
            cer_path=cer, key_path=key, password="x",
        )


def test_constructor_rechaza_certificado_inexistente(tmp_path):
    key = tmp_path / "k.key"
    key.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        SATPortalRPADriver(
            portal_url=PORTAL_URL, cer_path=str(tmp_path / "no-existe.cer"),
            key_path=str(key), password="x",
        )


def test_constructor_rechaza_llave_inexistente(tmp_path):
    cer = tmp_path / "c.cer"
    cer.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        SATPortalRPADriver(
            portal_url=PORTAL_URL, cer_path=str(cer),
            key_path=str(tmp_path / "no-existe.key"), password="x",
        )


def test_constructor_rechaza_password_vacio(cer_key_files):
    cer, key = cer_key_files
    with pytest.raises(ValueError):
        SATPortalRPADriver(portal_url=PORTAL_URL, cer_path=cer, key_path=key, password="")


def test_repr_nunca_expone_password(cer_key_files):
    driver = _make_driver(cer_key_files, password="super-secreta-123")
    assert "super-secreta-123" not in repr(driver)
    assert "<redacted>" in repr(driver)


# ---------------------------------------------------------------------------
# 2. Gate de confirmación / validación local — sin navegador
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_submit_diot_sin_confirm_no_toca_el_navegador(cer_key_files, diot_file):
    driver = _make_driver(cer_key_files)
    result = await driver.submit_diot(diot_file, periodo="2026-01", confirm=False)
    assert result.status == PortalStatus.CONFIRMATION_REQUIRED
    assert result.folio_acuse is None
    assert driver.desktop.health()["launched"] is False  # nunca se lanzó el navegador


@pytest.mark.asyncio
async def test_submit_diot_archivo_inexistente(cer_key_files):
    driver = _make_driver(cer_key_files)
    result = await driver.submit_diot("/no/existe/diot.txt", periodo="2026-01", confirm=True)
    assert result.status == PortalStatus.LOCAL_VALIDATION_ERROR
    assert driver.desktop.health()["launched"] is False


@pytest.mark.asyncio
async def test_submit_diot_archivo_vacio(cer_key_files, tmp_path):
    empty = tmp_path / "vacio.txt"
    empty.write_text("")
    driver = _make_driver(cer_key_files)
    result = await driver.submit_diot(str(empty), periodo="2026-01", confirm=True)
    assert result.status == PortalStatus.LOCAL_VALIDATION_ERROR
    assert driver.desktop.health()["launched"] is False


# ---------------------------------------------------------------------------
# 3. Flujo completo contra el simulador — requiere Chromium real
# ---------------------------------------------------------------------------
@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_flujo_completo_exitoso(sat_simulator, cer_key_files, diot_file):
    driver = _make_driver(cer_key_files, portal_url=sat_simulator)
    try:
        result = await driver.submit_diot(diot_file, periodo="2026-01", confirm=True)
        assert result.status == PortalStatus.CONFIRMED, result.mensaje
        assert result.is_final_success
        assert result.folio_acuse is not None
        assert result.folio_acuse.startswith("ACUSE-2026-01-")
        assert result.fecha_recepcion
        assert result.sello_acuse
        # Honestidad: incluso en éxito, jamás se marca como verificado contra el real.
        assert result.verificado_contra_sat_real is False
    finally:
        await driver.close()


@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_credenciales_invalidas_detiene_el_flujo(sat_simulator, cer_key_files, diot_file):
    driver = _make_driver(cer_key_files, password="wrong", portal_url=sat_simulator)
    try:
        result = await driver.submit_diot(diot_file, periodo="2026-01", confirm=True)
        assert result.status == PortalStatus.INVALID_CREDENTIALS
        assert result.folio_acuse is None
        assert not result.is_final_success
    finally:
        await driver.close()


@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_captcha_bloquea_el_flujo(sat_simulator, cer_key_files, diot_file):
    driver = _make_driver(cer_key_files, password="captcha-trigger", portal_url=sat_simulator)
    try:
        result = await driver.submit_diot(diot_file, periodo="2026-01", confirm=True)
        assert result.status == PortalStatus.CAPTCHA_BLOCKED
        assert result.folio_acuse is None
    finally:
        await driver.close()


@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_portal_caido_se_reporta_sin_reintentar_ciegamente(sat_simulator, cer_key_files, diot_file):
    driver = _make_driver(cer_key_files, rfc="PORTALCAIDO0000000", portal_url=sat_simulator)
    try:
        result = await driver.submit_diot(diot_file, periodo="2026-01", confirm=True)
        assert result.status == PortalStatus.PORTAL_UNAVAILABLE
        assert result.folio_acuse is None
    finally:
        await driver.close()


@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_archivo_diot_rechazado_por_el_portal(sat_simulator, cer_key_files, tmp_path):
    bad_file = tmp_path / "diot_malo.txt"
    bad_file.write_text("FORZAR_RECHAZO|contenido de prueba invalido")
    driver = _make_driver(cer_key_files, portal_url=sat_simulator)
    try:
        result = await driver.submit_diot(str(bad_file), periodo="2026-01", confirm=True)
        assert result.status == PortalStatus.UPLOAD_REJECTED
        assert result.folio_acuse is None
    finally:
        await driver.close()


@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_timeout_del_portal_al_cargar_no_se_reporta_como_exito(sat_simulator, cer_key_files, tmp_path):
    slow_file = tmp_path / "diot_timeout.txt"
    slow_file.write_text("FORZAR_TIMEOUT|contenido de prueba")
    driver = _make_driver(cer_key_files, portal_url=sat_simulator)
    try:
        result = await driver.submit_diot(str(slow_file), periodo="2026-01", confirm=True)
        assert result.status in (PortalStatus.PORTAL_UNAVAILABLE, PortalStatus.UNEXPECTED_STATE)
        assert not result.is_final_success
        assert result.folio_acuse is None
    finally:
        await driver.close()


@pytest.mark.computer_use_e2e
@pytest.mark.asyncio
async def test_confirmar_sin_haber_cargado_nada_es_estado_inesperado(sat_simulator, cer_key_files):
    """confirm_submission() llamado directo (sin upload previo) nunca produce éxito."""
    driver = _make_driver(cer_key_files, portal_url=sat_simulator)
    try:
        connect_res = await driver.connect()
        assert connect_res.ok
        auth_res = await driver.authenticate()
        assert auth_res.ok
        result = await driver.confirm_submission()
        assert result.status == PortalStatus.UNEXPECTED_STATE
        assert not result.is_final_success
    finally:
        await driver.close()
