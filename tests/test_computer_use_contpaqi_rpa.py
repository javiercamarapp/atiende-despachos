# -*- coding: utf-8 -*-
"""
Pruebas de contrato para CONTPAQiRealDriver (RPA de escritorio).

HONESTIDAD OBLIGATORIA: estas pruebas ejercitan CONTPAQiRealDriver contra
ContpaqiSimulatorBackend -- un servidor HTTP local (stdlib) que imita el
flujo de "Captura de pólizas" de CONTPAQi Contabilidad tal como está
documentado públicamente, pero que NUNCA ha sido confirmado contra una
instalación real de CONTPAQi. Ninguna prueba de este archivo prueba nada
contra CONTPAQi real -- eso requiere una VM/servidor Windows con CONTPAQi
instalado, que no existe en este entorno.

Cubre:
    - issubclass(CONTPAQiRealDriver, ComputerUseDriver) -- la ABC completa.
    - Ciclo de vida completo: connect/login/verify_authenticated/
      navigate_menu/register_poliza (balanceada)/verify_poliza_registered/
      register_invoice/verify_invoice_registered/logout/close.
    - Manejo de errores: ventana no encontrada, timeout, diálogo de error de
      CONTPAQi (póliza no balanceada), credenciales inválidas, operar sin
      sesión.
    - El simulador es un servidor HTTP real (no solo llamadas en memoria).
    - recover_from_error() reconecta cuando el backend deja de responder.
"""
from __future__ import annotations

import urllib.request
import json

import pytest

from b2b_ai.computer_use.interface import ComputerUseDriver, DriverResultStatus
from b2b_ai.computer_use.contpaqi_real_driver import (
    CONTPAQiRealDriver,
    CONTPAQI_VERIFICADO_CONTRA_REAL,
)
from b2b_ai.computer_use.contpaqi_rpa_backend import (
    ContpaqiSimulatorBackend,
    PywinautoContpaqiBackend,
    select_contpaqi_backend,
)
from b2b_ai.computer_use.contpaqi_simulator_server import ContpaqiSimulatorServer


POLIZA_BALANCEADA = {
    "tipo": "Diario",
    "fecha": "2026-01-15",
    "conceptos": [
        {"cuenta": "1105-001", "concepto": "Ingreso a banco", "cargo": 1160.00, "abono": 0},
        {"cuenta": "2101-001", "concepto": "IVA trasladado", "cargo": 0, "abono": 160.00},
        {"cuenta": "4105-001", "concepto": "Venta de servicios", "cargo": 0, "abono": 1000.00},
    ],
}

POLIZA_DESBALANCEADA = {
    "tipo": "Diario",
    "fecha": "2026-01-15",
    "conceptos": [
        {"cuenta": "1105-001", "concepto": "Ingreso a banco", "cargo": 1000.00, "abono": 0},
        {"cuenta": "4105-001", "concepto": "Venta de servicios", "cargo": 0, "abono": 900.00},
    ],
}

FACTURA = {"folio_fiscal": "ABC-123-XYZ", "total": 1160.00, "emisor_rfc": "XAXX010101000",
           "concepto": "Servicios de consultoría"}


def make_driver(**kwargs) -> CONTPAQiRealDriver:
    """Driver forzado al backend simulador (nunca pywinauto en este entorno de CI)."""
    return CONTPAQiRealDriver(force_backend="simulator", **kwargs)


# =========================================================================
# Honestidad / ABC
# =========================================================================
class TestHonestidadYABC:
    def test_verificado_contra_real_es_false(self):
        """El flag de honestidad debe ser False: no hay CONTPAQi real disponible."""
        assert CONTPAQI_VERIFICADO_CONTRA_REAL is False

    def test_implementa_la_abc_completa(self):
        assert issubclass(CONTPAQiRealDriver, ComputerUseDriver)

    def test_no_se_puede_instanciar_la_abc_directamente(self):
        with pytest.raises(TypeError):
            ComputerUseDriver()

    def test_backend_info_reporta_no_verificado(self):
        d = make_driver()
        info = d.backend_info()
        assert info["verificado_contra_real"] is False
        assert info["backend_es_real"] is False  # simulador, no pywinauto real
        d.close()

    def test_health_incluye_flag_de_honestidad(self):
        d = make_driver()
        r = d.health()
        assert r.ok
        assert r.data["verificado_contra_real"] is False
        d.close()

    def test_pywinauto_backend_no_disponible_en_este_entorno_no_windows(self):
        """En macOS/Linux, is_available() debe ser False (no hay Windows)."""
        backend = PywinautoContpaqiBackend()
        assert backend.is_available() is False

    def test_seleccion_automatica_cae_a_simulador_sin_windows(self):
        backend = select_contpaqi_backend()
        assert backend.ES_REAL is False
        assert isinstance(backend, ContpaqiSimulatorBackend)


# =========================================================================
# Simulador: es un servidor HTTP real, no sólo llamadas en memoria
# =========================================================================
class TestSimuladorEsServidorHTTPReal:
    def test_servidor_responde_por_http_real(self):
        server = ContpaqiSimulatorServer()
        base_url = server.start()
        try:
            assert base_url.startswith("http://127.0.0.1:")
            with urllib.request.urlopen(base_url + "/salud", timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            assert payload["verificado_contra_real"] is False
        finally:
            server.stop()

    def test_lanzar_ventana_por_http_real(self):
        server = ContpaqiSimulatorServer()
        base_url = server.start()
        try:
            req = urllib.request.Request(
                base_url + "/ventana/lanzar", data=b"{}", method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            assert payload["ok"] is True
            assert "titulo_ventana" in payload
        finally:
            server.stop()


# =========================================================================
# Ciclo de vida completo (contrato ABC ComputerUseDriver)
# =========================================================================
class TestCicloDeVidaCompleto:
    def test_flujo_completo_poliza_y_factura(self):
        d = make_driver(tenant_id=99)
        try:
            r = d.connect()
            assert r.ok, r.message

            r = d.login({"usuario": "admin", "password": "s3cret", "empresa": "Demo SA de CV"})
            assert r.ok, r.message
            assert r.data["session"]["usuario"] == "admin"

            r = d.verify_authenticated()
            assert r.ok

            r = d.navigate_menu("polizas")
            assert r.ok
            assert r.data["module"] == "polizas"

            r = d.register_poliza(POLIZA_BALANCEADA)
            assert r.ok, r.message
            poliza_id = r.data["registro"]["poliza_id"]
            assert poliza_id

            r = d.verify_poliza_registered(poliza_id)
            assert r.ok
            assert r.data["poliza_id"] == poliza_id

            r = d.register_invoice(FACTURA)
            assert r.ok, r.message

            r = d.verify_invoice_registered(FACTURA["folio_fiscal"])
            assert r.ok

            r = d.extract_invoices()
            assert r.ok
            assert len(r.data["invoices"]) == 1

            r = d.capture_invoice_grid()
            assert r.ok

            r = d.health()
            assert r.ok
            assert r.data["registered_invoices"] == 1
            assert r.data["registered_polizas"] == 1

            r = d.logout()
            assert r.ok
        finally:
            d.close()

    def test_provider_y_mode(self):
        d = make_driver()
        assert d.provider == "contpaqi"
        assert d.mode == "playwright"  # vocabulario del factory; ver docstring
        d.close()


# =========================================================================
# Datos reales de una póliza (balance contable)
# =========================================================================
class TestPolizaBalanceada:
    def test_poliza_balanceada_se_registra(self):
        d = make_driver()
        try:
            d.connect()
            d.login({"usuario": "admin", "password": "pw"})
            d.navigate_menu("polizas")
            r = d.register_poliza(POLIZA_BALANCEADA)
            assert r.ok
            assert r.data["registro"]["cargo_total"] == 1160.00
            assert r.data["registro"]["abono_total"] == 1160.00
        finally:
            d.close()

    def test_poliza_desbalanceada_se_rechaza_localmente_sin_llamar_backend(self):
        """El driver valida el balance ANTES de llamar al backend (misma
        regla que aplicaría CONTPAQi real al intentar guardar)."""
        d = make_driver()
        try:
            d.connect()
            d.login({"usuario": "admin", "password": "pw"})
            d.navigate_menu("polizas")
            r = d.register_poliza(POLIZA_DESBALANCEADA)
            assert r.status == DriverResultStatus.FAILED
            assert "balanceada" in r.message.lower()
        finally:
            d.close()

    def test_poliza_sin_conceptos_falla(self):
        d = make_driver()
        try:
            d.connect()
            d.login({"usuario": "admin", "password": "pw"})
            r = d.register_poliza({"tipo": "Diario", "fecha": "2026-01-01"})
            assert r.status == DriverResultStatus.FAILED
        finally:
            d.close()


# =========================================================================
# Manejo de errores
# =========================================================================
class TestManejoDeErrores:
    def test_ventana_no_encontrada(self):
        # Lanzamos el simulador propio primero para poder inyectar la falla
        # antes de que el driver intente conectar.
        server = ContpaqiSimulatorServer()
        base_url = server.start()
        backend_con_url = ContpaqiSimulatorBackend(base_url=base_url)
        try:
            server.estado.inyectar_falla("ventana_no_encontrada", 1)
            d = CONTPAQiRealDriver(backend=backend_con_url)
            r = d.connect()
            assert r.status == DriverResultStatus.FAILED
            assert "ventana no encontrada" in r.message.lower()
        finally:
            server.stop()

    def test_timeout_al_conectar(self):
        server = ContpaqiSimulatorServer()
        base_url = server.start()
        backend_con_url = ContpaqiSimulatorBackend(base_url=base_url)
        try:
            server.estado.inyectar_falla("timeout", 1)
            d = CONTPAQiRealDriver(backend=backend_con_url)
            r = d.connect()
            assert r.status == DriverResultStatus.FAILED
            assert "timeout" in r.message.lower()
        finally:
            server.stop()

    def test_dialogo_de_error_de_contpaqi_al_guardar_poliza(self):
        server = ContpaqiSimulatorServer()
        base_url = server.start()
        backend_con_url = ContpaqiSimulatorBackend(base_url=base_url)
        try:
            d = CONTPAQiRealDriver(backend=backend_con_url)
            d.connect()
            d.login({"usuario": "admin", "password": "pw"})
            d.navigate_menu("polizas")
            server.estado.inyectar_falla("dialogo_error", 1)
            r = d.register_poliza(POLIZA_BALANCEADA)
            assert r.status == DriverResultStatus.NEEDS_HUMAN_REVIEW
        finally:
            server.stop()

    def test_credenciales_invalidas(self):
        d = make_driver()
        try:
            d.connect()
            r = d.login({"usuario": "usuario_invalido", "password": "cualquiera"})
            assert r.status == DriverResultStatus.FAILED
        finally:
            d.close()

    def test_login_sin_conectar_falla(self):
        d = make_driver()
        r = d.login({"usuario": "admin", "password": "pw"})
        assert r.status == DriverResultStatus.FAILED
        d.close()

    def test_operaciones_sin_sesion_dan_session_expired(self):
        d = make_driver()
        d.connect()
        assert d.verify_authenticated().status == DriverResultStatus.SESSION_EXPIRED
        assert d.navigate_menu("polizas").status == DriverResultStatus.SESSION_EXPIRED
        assert d.register_poliza(POLIZA_BALANCEADA).status == DriverResultStatus.SESSION_EXPIRED
        assert d.register_invoice(FACTURA).status == DriverResultStatus.SESSION_EXPIRED
        assert d.verify_invoice_registered("X").status == DriverResultStatus.SESSION_EXPIRED
        assert d.verify_poliza_registered("X").status == DriverResultStatus.SESSION_EXPIRED
        d.close()

    def test_navegar_modulo_desconocido_falla(self):
        d = make_driver()
        d.connect()
        d.login({"usuario": "admin", "password": "pw"})
        r = d.navigate_menu("modulo_inexistente")
        assert r.status == DriverResultStatus.FAILED
        d.close()

    def test_recover_from_error_reconecta(self):
        d = make_driver()
        d.connect()
        d.login({"usuario": "admin", "password": "pw"})
        # Forzamos que el backend deje de estar sano cerrándolo por debajo.
        d._backend.close()
        r = d.recover_from_error()
        assert r.ok
        assert r.data.get("needs_relogin") is True
        d.close()


# =========================================================================
# Factory: sigue creando CONTPAQiRealDriver correctamente (regresión)
# =========================================================================
class TestFactoryIntegracion:
    def test_factory_sigue_creando_contpaqi_real_driver(self, monkeypatch):
        from b2b_ai.computer_use.config import ComputerUseConfig
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory

        monkeypatch.setenv("B2B_ENV", "test")
        cfg = ComputerUseConfig(
            mode="playwright",
            contpaqi_url="https://real.contpaqi.com",
            contpaqi_username="admin",
            contpaqi_password="pass",
        )
        d = ComputerUseDriverFactory.create(provider="contpaqi", mode="playwright", config=cfg)
        try:
            assert isinstance(d, CONTPAQiRealDriver)
            assert issubclass(type(d), ComputerUseDriver)
            assert d.mode == "playwright"
            assert d.provider == "contpaqi"
        finally:
            d.close()
