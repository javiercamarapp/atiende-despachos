# -*- coding: utf-8 -*-
"""Tests de los drivers de escritorio (computer use) para CONTPAQi y Aspel."""
import pytest

from b2b_ai.computer_use.contpaqi_driver import (
    DesktopAutomation,
    MockDesktop,
    ContpaqiDriver,
    set_default_contpaqi,
    get_default_contpaqi,
    contpaqi_login,
    contpaqi_register,
)
from b2b_ai.computer_use.aspel_driver import (
    AspelDriver,
    set_default_aspel,
    get_default_aspel,
    aspel_login,
    aspel_register,
)


# ---- capa de escritorio ----------------------------------------------------
def test_desktop_es_abstracta():
    assert DesktopAutomation.__abstractmethods__
    with pytest.raises(TypeError):
        DesktopAutomation()


def test_mock_desktop_operativo():
    d = MockDesktop()
    assert d.screenshot()["ok"] is True
    assert d.read_window_title() == MockDesktop.DEFAULT_TITLE
    assert d.click(10, 20)["ok"] is True
    assert d.type_text("hola")["chars"] == 4
    assert d.press_key("Enter")["key"] == "Enter"
    assert d.health()["ok"] is True


# ---- CONTPAQi ---------------------------------------------------------------
@pytest.fixture
def contpaqi():
    return ContpaqiDriver()


def test_contpaqi_open_app(contpaqi):
    r = contpaqi.open_app()
    assert r["ok"] is True
    assert r["app"] == "CONTPAQi"


def test_contpaqi_login_ok(contpaqi):
    r = contpaqi.login({"usuario": "c1", "password": "x", "empresa": "D1"})
    assert r["ok"] is True
    assert contpaqi.session["empresa"] == "D1"
    # el login tecleó usuario y password
    assert contpaqi.desktop.typed[0] == "c1"


def test_contpaqi_login_sin_usuario(contpaqi):
    r = contpaqi.login({})
    assert r["ok"] is False
    assert contpaqi.session is None


def test_contpaqi_requiere_login_para_captura(contpaqi):
    r = contpaqi.capture_invoice_grid()
    assert r["ok"] is False


def test_contpaqi_registro_pendiente_revision(contpaqi):
    contpaqi.login({"usuario": "c1"})
    r = contpaqi.register_invoice({"folio_fiscal": "ABC-1", "total": 1000.0,
                                   "emisor_rfc": "XAXX010101000"})
    assert r["ok"] is True
    assert r["registro"]["status"] == "pendiente_revision"
    assert len(contpaqi._registered) == 1


def test_contpaqi_registro_sin_folio(contpaqi):
    contpaqi.login({"usuario": "c1"})
    r = contpaqi.register_invoice({})
    assert r["ok"] is False


def test_contpaqi_health(contpaqi):
    h = contpaqi.health()
    assert h["ok"] is True
    assert "CONTPAQi" in h["backend"]


def test_contpaqi_helpers_de_modulo():
    set_default_contpaqi(ContpaqiDriver())
    try:
        assert get_default_contpaqi() is not None
        assert contpaqi_login({"usuario": "u"})["ok"] is True
        assert contpaqi_register({"folio_fiscal": "F-1"})["ok"] is True
    finally:
        set_default_contpaqi(None)


# ---- Aspel -----------------------------------------------------------------
@pytest.fixture
def aspel():
    return AspelDriver()


def test_aspel_open_app(aspel):
    r = aspel.open_app()
    assert r["ok"] is True
    assert r["app"] == "Aspel"


def test_aspel_login_ok(aspel):
    r = aspel.login({"usuario": "a1", "password": "x", "empresa": "D2"})
    assert r["ok"] is True
    assert aspel.session["empresa"] == "D2"


def test_aspel_ventana_propia():
    # Aspel abre por defecto su propia ventana, distinta de CONTPAQi
    a = AspelDriver(desktop=MockDesktop(title="Aspel SAE 8.0"))
    assert a.open_app()["window"] == "Aspel SAE 8.0"


def test_aspel_captura_con_sesion(aspel):
    aspel.login({"usuario": "a1"})
    r = aspel.capture_invoice_grid()
    assert r["ok"] is True
    assert "grid" in r


def test_aspel_registro_pendiente(aspel):
    aspel.login({"usuario": "a1"})
    r = aspel.register_invoice({"folio_fiscal": "ASP-1", "total": 500.0})
    assert r["ok"] is True
    assert r["registro"]["status"] == "pendiente_revision"


def test_aspel_requiere_login(aspel):
    assert aspel.open_invoices()["ok"] is False


def test_aspel_health(aspel):
    h = aspel.health()
    assert h["ok"] is True
    assert "Aspel" in h["backend"]


def test_aspel_helpers_de_modulo():
    set_default_aspel(AspelDriver())
    try:
        assert get_default_aspel() is not None
        assert aspel_login({"usuario": "u"})["ok"] is True
        assert aspel_register({"folio_fiscal": "G-1"})["ok"] is True
    finally:
        set_default_aspel(None)


# ---- integración: un mismo escritorio para ambos ----------------------------
def test_mismo_desktop_para_ambos_drivers():
    desktop = MockDesktop()
    c = ContpaqiDriver(desktop)
    a = AspelDriver(desktop)
    c.login({"usuario": "c1"})
    a.login({"usuario": "a1"})
    # comparten el "escritorio" real (los tecleos van al mismo backend)
    assert desktop.typed[0] == "c1"
    assert desktop.typed[2] == "a1"
