# -*- coding: utf-8 -*-
"""Tests del módulo computer use (BrowserAutomation + MockBrowser)."""
import pytest

from b2b_ai.computer_use.browser import (
    BrowserAutomation,
    MockBrowser,
    navigate_to_erp,
    login_contpaqi,
    upload_cfdi,
    read_screen,
    run_capture_flow,
    set_default_browser,
    get_default_browser,
)


@pytest.fixture
def browser():
    return MockBrowser()


def test_es_una_interfaz_abstracta():
    assert BrowserAutomation.__abstractmethods__  # tiene métodos abstractos
    with pytest.raises(TypeError):
        BrowserAutomation()


def test_navigate(browser):
    r = browser.navigate_to_erp()
    assert r["ok"] is True
    assert r["page"] == "login"
    assert r["url"].startswith("https://")


def test_login_ok(browser):
    r = browser.login({"username": "contador1", "password": "x"})
    assert r["ok"] is True
    assert r["session"]["username"] == "contador1"
    assert browser.session is not None
    assert browser.read_screen()["logged_in"] is True


def test_login_sin_usuario(browser):
    r = browser.login({})
    assert r["ok"] is False
    assert r["session"] is None


def test_upload_requiere_login(browser, sample_papeleria):
    # archivo existe pero no hay sesión activa → debe rechazar
    r = browser.upload_cfdi(sample_papeleria)
    assert r["ok"] is False
    assert "login" in r["message"].lower()


def test_upload_archivo_no_existe(browser):
    browser.login({"username": "u"})
    r = browser.upload_cfdi("/no/existe.xml")
    assert r["ok"] is False
    assert "no encontrado" in r["message"].lower()


def test_upload_ok(browser, sample_papeleria):
    browser.login({"username": "u"})
    r = browser.upload_cfdi(sample_papeleria)
    assert r["ok"] is True
    assert r["upload_id"]
    assert browser.uploads[0]["archivo"].endswith(".xml")
    assert browser.read_screen()["uploads"] == 1


def test_read_screen(browser):
    s = browser.read_screen()
    assert "page" in s and "url" in s and "logged_in" in s


def test_health(browser):
    h = browser.health()
    assert h["ok"] is True
    assert "Mock" in h["backend"]


# ---- helpers a nivel de módulo (API pública simple) -----------------------

def test_helpers_de_modulo(browser):
    # swap del navegador por defecto para no depender del global compartido
    set_default_browser(browser)
    try:
        assert get_default_browser() is browser
        assert navigate_to_erp()["ok"] is True
        assert login_contpaqi({"username": "u"})["ok"] is True
        assert upload_cfdi("/tmp/x.xml")["ok"] is False  # ya subimos? no
        assert "page" in read_screen()
    finally:
        # reset global para no contaminar otros tests
        set_default_browser(None)


def test_run_capture_flow(browser, sample_papeleria):
    res = run_capture_flow(sample_papeleria, {"username": "contador"},
                           browser=browser)
    assert res["ok"] is True
    steps = res["steps"]
    assert steps["navigate"]["ok"] is True
    assert steps["login"]["ok"] is True
    assert steps["upload"]["ok"] is True
    assert steps["screen"]["logged_in"] is True
