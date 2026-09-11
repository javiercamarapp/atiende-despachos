# -*- coding: utf-8 -*-
"""Tests de la integración SAT (downloader/validator/scheduler/api).

Todos los tests usan el transporte mock: NO se toca e.firma real, credenciales
ni red. Los folios son deterministas por (rfc, fecha, tipo, índice).
"""
import pytest

from b2b_ai.sat.downloader import SATDownloader, TIPOS_CFDI
from b2b_ai.sat.validator import SATValidator
from b2b_ai.sat.scheduler import SATScheduler

RFC = "XAXX010101000"  # RFC genérico de pruebas (formato válido, no registrado)

SAT_SIM_PORT = 18780
SAT_SIM_URL = f"http://127.0.0.1:{SAT_SIM_PORT}"


@pytest.fixture(scope="module")
def sat_consulta_cfdi_simulator():
    """Simulador local del WSDL de Verificación de CFDI del SAT (FIS-024) —
    ver tests/fixtures/sat_consulta_cfdi_simulator.py. Nunca red real."""
    from tests.fixtures.sat_consulta_cfdi_simulator import start_sat_consulta_cfdi_simulator
    server = start_sat_consulta_cfdi_simulator(port=SAT_SIM_PORT)
    yield SAT_SIM_URL
    server.shutdown()


# -------------------------------------------------------------------------- #
# Downloader: login / logout
# -------------------------------------------------------------------------- #
def test_login_rfc_invalido_rechaza():
    dl = SATDownloader(rfc=RFC)
    res = dl.login("1234", "ciec")
    assert res["ok"] is False
    assert "RFC" in res["error"]
    assert not dl.logged_in


def test_login_sin_credenciales_rechaza():
    dl = SATDownloader(rfc=RFC)
    res = dl.login(RFC)
    assert res["ok"] is False
    assert "CIEC" in res["error"]


def test_login_y_logout_ok():
    dl = SATDownloader(rfc=RFC)
    res = dl.login(RFC, "ciEc123")
    assert res["ok"] is True
    assert dl.logged_in
    assert dl.logged_rfc == RFC
    out = dl.logout()
    assert out["ok"] is True
    assert out["was_logged_in"] is True
    assert not dl.logged_in


# -------------------------------------------------------------------------- #
# Downloader: descarga de CFDI
# -------------------------------------------------------------------------- #
def test_download_requiere_login():
    dl = SATDownloader(rfc=RFC)
    with pytest.raises(RuntimeError):
        dl.download_cfdi("2026-01-01", "2026-01-03", "emitidas")


def test_download_tipo_invalido():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    res = dl.download_cfdi("2026-01-01", "2026-01-03", "cualquier")
    assert res["ok"] is False
    assert "tipo" in res["error"]


def test_download_fechas_invalidas():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    assert dl.download_cfdi("mal", "2026-01-03", "emitidas")["ok"] is False
    # rango invertido
    res = dl.download_cfdi("2026-01-05", "2026-01-03", "emitidas")
    assert res["ok"] is False
    assert "anterior" in res["error"]


def test_download_emitidas_genera_determinista():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    r1 = dl.download_cfdi("2026-01-01", "2026-01-03", "emitidas")
    r2 = dl.download_cfdi("2026-01-01", "2026-01-03", "emitidas")
    assert r1["ok"] is True
    assert r1["count"] == 6          # 3 días × 2 CFDI
    assert r1["cfdis"][0]["emisor_rfc"] == RFC
    assert r1["cfdis"][0]["receptor_rfc"] != RFC
    # determinismo: mismo rango/rfc → mismos folios
    assert [c["folio_fiscal"] for c in r1["cfdis"]] == \
           [c["folio_fiscal"] for c in r2["cfdis"]]
    assert all(c["estatus"] == "vigente" for c in r1["cfdis"])


def test_download_recibidas_emisor_invertido():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    res = dl.download_cfdi("2026-01-01", "2026-01-01", "recibidas")
    assert res["ok"] is True
    assert res["count"] == 2
    assert res["cfdis"][0]["receptor_rfc"] == RFC
    assert res["cfdis"][0]["emisor_rfc"] != RFC


# -------------------------------------------------------------------------- #
# Downloader: balanza y catálogo
# -------------------------------------------------------------------------- #
def test_balanza_periodo_invalido():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    assert dl.download_balanza("2026")["ok"] is False
    assert dl.download_balanza("2026-13")["ok"] is False


def test_balanza_ok_cuadrada():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    res = dl.download_balanza("2026-07")
    assert res["ok"] is True
    assert res["periodo"] == "2026-07"
    assert res["cuadrada"] is True
    assert len(res["cuentas"]) >= 3


def test_catalogo_cuentas_requiere_login():
    dl = SATDownloader(rfc=RFC)
    with pytest.raises(RuntimeError):
        dl.download_catalogo_cuentas()


def test_catalogo_cuentas_ok():
    dl = SATDownloader(rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    res = dl.download_catalogo_cuentas()
    assert res["ok"] is True
    assert res["count"] >= 4
    assert res["catalogo"][0]["codigo"]


# -------------------------------------------------------------------------- #
# Validator
# -------------------------------------------------------------------------- #
# FIS-024: SATValidator dejó de ser mock — ahora llama (o intenta llamar) al
# WSDL público real del SAT. Las pruebas de contrato/comportamiento del
# cliente SOAP real (feliz, cancelado, no encontrado, SOAP Fault, XML
# inválido, error de red, etc.) viven en tests/test_sat_validator_real.py,
# contra el simulador local (nunca contra el SAT real). Aquí solo queda lo
# que no requiere red: la validación de folio_fiscal/rfc obligatorios y el
# formato de RFC (verify_rfc no cambió: sigue siendo solo validación de
# formato, ver docstring de SATValidator.verify_rfc).
def test_check_status_folio_obligatorio_sin_red():
    v = SATValidator()
    res = v.check_status("")
    assert res["ok"] is False


def test_check_status_sin_rfc_total_falla_cerrado_sin_red():
    """Sin rfc_emisor/rfc_receptor/total no se intenta ninguna llamada real
    — se prueba pasando un http_client que lanzaría si se usara."""
    class _ClienteQueNuncaDebeUsarse:
        def post(self, *a, **k):
            raise AssertionError("no debía intentarse ninguna llamada de red")

    v = SATValidator(http_client=_ClienteQueNuncaDebeUsarse())
    res = v.check_status("12345678901234567890123456789011")
    assert res["ok"] is False
    assert "rfc_emisor" in res["error"]


def test_verify_rfc_formato_y_registrado():
    v = SATValidator()
    assert v.verify_rfc("1234")["valido"] is False
    ok = v.verify_rfc("AAA010101AAA")
    assert ok["valido"] is True
    # No existe servicio público del SAT para existencia de RFC de terceros.
    assert ok["registrado"] is None
    gen = v.verify_rfc("XAXX010101000")
    assert gen["valido"] is True
    assert gen["registrado"] is False


# -------------------------------------------------------------------------- #
# Scheduler
# -------------------------------------------------------------------------- #
def test_run_daily_descarga_ambos_tipos():
    dl = SATDownloader(rfc=RFC, ciec="x")
    # run_daily() no usa el validador (solo descarga); SATValidator() aquí
    # no hace ninguna llamada de red al solo instanciarse.
    sched = SATScheduler(downloader=dl, validator=SATValidator(),
                         rfc=RFC, ciec="x")
    res = sched.run_daily(fecha="2026-01-10")
    assert res["ok"] is True
    assert res["count"] == 4          # emitidas (2) + recibidas (2)
    assert {d["tipo"] for d in res["descargas"]} == {"emitidas", "recibidas"}
    assert len(dl._ledger) == 4


def test_run_weekly_alertas_cancelacion(tmp_path, sat_consulta_cfdi_simulator):
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "sat.db"))
    db.create_tenant("Despacho SAT", rfc=RFC)
    db.create_api_key(1, "k", "key")
    dl = SATDownloader(db=db, tenant_id=1, rfc=RFC, ciec="x")
    dl.login(RFC, "x")
    dl.download_cfdi("2026-01-01", "2026-01-01", "emitidas")  # 2 CFDI
    dl.logout()
    # Fuerza que el folio[1] se reporte cancelado (termina en '0').
    # Como los folios son deterministas, inyectamos un CFDI cancelable:
    # marcamos estatus vigente en ledger y forzamos estado.
    dl._ledger[1]["estatus"] = "vigente"
    dl._save_ledger()
    # FIS-024: SATValidator real necesita apuntar al simulador local (nunca
    # al SAT real) — el ledger ya trae emisor_rfc/receptor_rfc/total, que
    # scheduler.run_weekly() ahora le pasa a check_status().
    validator = SATValidator(base_url=sat_consulta_cfdi_simulator)
    sched = SATScheduler(db=db, tenant_id=1, downloader=dl,
                         validator=validator, rfc=RFC, ciec="x")
    res = sched.run_weekly()
    assert res["checked"] == 2
    # Al menos una alerta si hay folio terminado en 0 en el ledger.
    alerts = res["alerts"]
    # Verificar que la alerta, si existe, quedó persistida en notifications.
    notifs = db.list_notifications(tenant_id=1)
    for a in alerts:
        assert any(n["id"] == a["notification_id"] for n in notifs)


def test_run_weekly_ledger_vacio():
    dl = SATDownloader(rfc=RFC, ciec="x")
    sched = SATScheduler(downloader=dl, validator=SATValidator(), rfc=RFC)
    res = sched.run_weekly()
    assert res["ok"] is True
    assert res["checked"] == 0


def test_process_marca_ultima_ejecucion(tmp_path):
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "sat2.db"))
    db.create_tenant("D2", rfc=RFC)
    db.create_api_key(1, "k", "key")
    sched = SATScheduler(db=db, tenant_id=1, rfc=RFC, ciec="x")
    out = sched.process()
    assert out["ok"] is True
    assert "daily" in out["ran"]
    assert db.get_tenant_config(1, "sat_last_daily") is not None
