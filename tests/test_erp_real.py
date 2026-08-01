# -*- coding: utf-8 -*-
"""Tests de la integración ERP real (CONTPAQi + Aspel) por computer use.

Se prueban sobre MockDesktop (en memoria) con inyección de fallas, según el
límite del task: "Mock tests para desarrollo". No hay instalación real de
CONTPAQi/Aspel en esta máquina, así que el controlador de escritorio real no
se puede ejercitar aquí (ver bloque de cierre).
"""
import os
import pytest

from b2b_ai.computer_use.contpaqi_driver import (
    ContpaqiDriver, MockDesktop,
)
from b2b_ai.computer_use.aspel_driver import AspelDriver
from b2b_ai.erp.erp_automation import DesktopERPBase
from b2b_ai.erp.contpaqi_real import RealCONTPAQi, capture_and_register as cq_capture
from b2b_ai.erp.aspel_real import RealAspel, capture_and_register as asl_capture

CREDS = {"usuario": "contador1", "password": "x", "empresa": "Despacho Demo"}
CFDI = {"folio_fiscal": "FAC-2026-0001", "total": 5800.00,
        "emisor_rfc": "CON950820K12", "categoria": "inversion"}


@pytest.fixture
def audit_dir(tmp_path):
    d = tmp_path / "audit"
    d.mkdir()
    return str(d)


# ---- RealCONTPAQi ----------------------------------------------------------
def test_contpaqi_real_health_ok(audit_dir):
    c = RealCONTPAQi(audit_dir=audit_dir)
    h = c.health(CREDS)
    assert h["ok"] is True
    assert h["checks"] == {"abierto": True, "navegable": True, "guardable": True}
    assert os.path.exists(c.audit_log_path)


def test_contpaqi_real_full_flow_registra(audit_dir):
    c = RealCONTPAQi(audit_dir=audit_dir)
    res = c.full_flow(CREDS, invoices=[CFDI])
    assert res["ok"] is True
    assert len(res["registered"]) == 1
    assert res["registered"][0]["folio_fiscal"] == "FAC-2026-0001"
    # audit log con entradas por paso
    assert os.path.exists(res["audit_log_path"])
    with open(res["audit_log_path"], encoding="utf-8") as fh:
        lines = fh.read().strip().splitlines()
    assert lines  # no vacío
    # abrir -> login -> captura -> register quedan registrados
    assert any('"step": "open_app"' in l for l in lines)
    assert any('"step": "login"' in l for l in lines)
    assert any('"step": "register"' in l for l in lines)


def test_contpaqi_real_error_recovery_reintenta(audit_dir):
    desktop = MockDesktop()
    driver = ContpaqiDriver(desktop=desktop)
    c = RealCONTPAQi(driver=driver, audit_dir=audit_dir, retries=3)
    # open_app lee el título (levanta excepción); fallan 2 de 3 intentos,
    # la recuperación ocurre al tercero.
    desktop.fail_next("read_window_title", times=2)
    res = c.open_app()
    assert res["ok"] is True
    assert res["retries"] == 3  # se recuperó al tercer intento
    # cada intento dejó entrada en el audit log
    with open(c.audit_log_path, encoding="utf-8") as fh:
        content = fh.read()
    assert content.count('"step": "open_app"') >= 3


def test_contpaqi_real_falla_sin_usuario(audit_dir):
    c = RealCONTPAQi(audit_dir=audit_dir, retries=2)
    res = c.login({})
    assert res["ok"] is False
    assert res["retries"] == 2


def test_contpaqi_real_screenshot_guardado_real(audit_dir, tmp_path):
    # si el backend devuelve una ruta real de screenshot, el audit log la refleja
    shot_file = tmp_path / "captura.png"
    shot_file.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    desktop = MockDesktop()
    desktop.screenshot_path = str(shot_file)
    driver = ContpaqiDriver(desktop=desktop)
    c = RealCONTPAQi(driver=driver, audit_dir=audit_dir)
    c.open_app()
    with open(c.audit_log_path, encoding="utf-8") as fh:
        content = fh.read()
    assert str(shot_file) in content
    # el archivo realmente existe en disco
    assert os.path.exists(str(shot_file))


def test_contpaqi_real_capture_and_register_helper(audit_dir):
    res = cq_capture(CREDS, invoices=[CFDI], audit_dir=audit_dir)
    assert res["ok"] is True
    assert len(res["registered"]) == 1


# ---- RealAspel -------------------------------------------------------------
def test_aspel_real_health_ok(audit_dir):
    a = RealAspel(audit_dir=audit_dir)
    h = a.health(CREDS)
    assert h["ok"] is True
    assert all(h["checks"].values())


def test_aspel_real_full_flow(audit_dir):
    a = RealAspel(audit_dir=audit_dir)
    res = a.full_flow(CREDS, invoices=[CFDI])
    assert res["ok"] is True
    assert len(res["registered"]) == 1
    # Aspel abre su módulo de facturas
    assert res["steps"]["open_invoices"]["ok"] is True


def test_aspel_real_error_recovery(audit_dir):
    desktop = MockDesktop()
    driver = AspelDriver(desktop=desktop)
    a = RealAspel(driver=driver, audit_dir=audit_dir, retries=3)
    # open_app lee el título y levanta excepción en 2 de 3 intentos.
    desktop.fail_next("read_window_title", times=2)
    res = a.open_app()
    assert res["ok"] is True
    assert res["retries"] == 3


def test_aspel_real_navigate_sae_screens(audit_dir):
    a = RealAspel(audit_dir=audit_dir)
    a.login(CREDS)
    res = a.navigate_sae_screens(["facturas", "captura", "guardar"])
    assert res["ok"] is True
    assert len(res["visited"]) == 3


def test_aspel_real_capture_and_register_helper(audit_dir):
    res = asl_capture(CREDS, invoices=[CFDI], audit_dir=audit_dir)
    assert res["ok"] is True
    assert len(res["registered"]) == 1


# ---- DesktopERPBase --------------------------------------------------------
def test_base_retry_agota_intentos(audit_dir):
    c = RealCONTPAQi(audit_dir=audit_dir, retries=2)
    # login sin usuario devuelve ok=False SIEMPRE -> se agotan los 2 intentos
    res = c.login({})
    assert res["ok"] is False
    assert res["retries"] == 2
    assert res["recovered"] is False
    # el audit log registra el fallo final
    with open(c.audit_log_path, encoding="utf-8") as fh:
        content = fh.read()
    assert '"status": "failed"' in content


def test_audit_log_json_por_linea(audit_dir):
    c = RealCONTPAQi(audit_dir=audit_dir)
    c.open_app()
    import json
    with open(c.audit_log_path, encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            assert "step" in obj and "status" in obj and "at" in obj
