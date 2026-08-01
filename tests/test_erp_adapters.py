# -*- coding: utf-8 -*-
"""
test_erp_adapters.py — Tests for the 7 new ERP adapters (Peak, Multileg,
Euroweb, Absis, Factor D, Taxko, FacturaDirecta).

Each adapter has both mock and real driver stubs. Tests exercise the mock
implementations to verify the ERPAdapter contract and data models.
"""
from __future__ import annotations

import pytest
from datetime import datetime

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion,
    ChartOfAccounts,
    CuentaPoliza,
    ERPConfig,
    ERPType,
    Invoice,
    Poliza,
    StatusPoliza,
)
from b2b_ai.integrations.erp.peak import PeakAdapter
from b2b_ai.integrations.erp.multileg import MultilegAdapter
from b2b_ai.integrations.erp.euroweb import EurowebAdapter
from b2b_ai.integrations.erp.absis import AbsisAdapter
from b2b_ai.integrations.erp.factor_d import FactorDAdapter
from b2b_ai.integrations.erp.taxko import TaxkoAdapter
from b2b_ai.integrations.erp.facturadirecta import FacturaDirectaAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _all_desktop_adapters():
    return [PeakAdapter(), MultilegAdapter(), EurowebAdapter(), AbsisAdapter()]


def _all_cloud_adapters():
    return [FactorDAdapter(), TaxkoAdapter(), FacturaDirectaAdapter()]


def _all_new_adapters():
    return _all_desktop_adapters() + _all_cloud_adapters()


def _connected_adapter(adapter: ERPAdapter) -> ERPAdapter:
    adapter.connect()
    return adapter


# ===================================================================
# 1. ERPAdapter contract — all new adapters inherit correctly
# ===================================================================
class TestERPAdapterContract:
    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_is_erp_adapter(self, adapter):
        assert isinstance(adapter, ERPAdapter)

    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_initial_not_connected(self, adapter):
        assert adapter.is_connected is False

    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_ensure_connected_raises_when_not_connected(self, adapter):
        with pytest.raises(ERPAdapterError, match="no está conectado"):
            adapter.get_invoices()

    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_connect_returns_true(self, adapter):
        assert adapter.connect() is True
        assert adapter.is_connected is True

    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_disconnect(self, adapter):
        adapter.connect()
        adapter.disconnect()
        assert adapter.is_connected is False

    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_test_connection_when_connected(self, adapter):
        adapter.connect()
        result = adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"]

    @pytest.mark.parametrize("adapter", _all_new_adapters(), ids=lambda a: type(a).__name__)
    def test_test_connection_when_not_connected(self, adapter):
        result = adapter.test_connection()
        assert result["status"] == "error"


# ===================================================================
# 2. Peak adapter
# ===================================================================
class TestPeakAdapter:
    def test_erp_type(self):
        assert PeakAdapter().config.type == ERPType.PEAK

    def test_connect_mock(self):
        a = PeakAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "PK010101AAA"

    def test_get_invoices(self):
        a = _connected_adapter(PeakAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert all(isinstance(inv, Invoice) for inv in invs)
        assert invs[0].id.startswith("PK-INV-")

    def test_get_polizas(self):
        a = _connected_adapter(PeakAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert all(isinstance(p, Poliza) for p in pols)
        assert pols[0].id.startswith("PK-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(PeakAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True
        assert result["id_erp"].startswith("PK-POL-")

    def test_upload_poliza_unbalanced(self):
        a = _connected_adapter(PeakAdapter())
        pol = Poliza(
            cuentas=[CuentaPoliza(cuenta="1101", debe=1000, haber=0)],
        )
        result = a.upload_poliza(pol)
        assert result["exito"] is False

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(PeakAdapter())
        coa = a.get_chart_of_accounts()
        assert isinstance(coa, ChartOfAccounts)
        assert len(coa.cuentas) >= 5
        assert coa.ejercicio == 2026

    def test_get_balanza(self):
        a = _connected_adapter(PeakAdapter())
        bal = a.get_balanza(2026, 1)
        assert isinstance(bal, BalanzaComprobacion)
        assert bal.ejercicio == 2026
        assert bal.mes == 1
        assert bal.total_deudor > 0


# ===================================================================
# 3. Multileg adapter
# ===================================================================
class TestMultilegAdapter:
    def test_erp_type(self):
        assert MultilegAdapter().config.type == ERPType.MULTILEG

    def test_connect_mock(self):
        a = MultilegAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "MLG010101AAA"

    def test_get_invoices(self):
        a = _connected_adapter(MultilegAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert invs[0].id.startswith("MLG-INV-")

    def test_get_polizas(self):
        a = _connected_adapter(MultilegAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert pols[0].id.startswith("MLG-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(MultilegAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True
        assert result["id_erp"].startswith("MLG-POL-")

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(MultilegAdapter())
        coa = a.get_chart_of_accounts()
        assert len(coa.cuentas) >= 5

    def test_get_balanza(self):
        a = _connected_adapter(MultilegAdapter())
        bal = a.get_balanza(2026, 6)
        assert bal.mes == 6


# ===================================================================
# 4. Euroweb adapter
# ===================================================================
class TestEurowebAdapter:
    def test_erp_type(self):
        assert EurowebAdapter().config.type == ERPType.EUROWEB

    def test_connect_mock(self):
        a = EurowebAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "EWB010101AAA"

    def test_get_invoices(self):
        a = _connected_adapter(EurowebAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert invs[0].id.startswith("EWB-INV-")

    def test_get_polizas(self):
        a = _connected_adapter(EurowebAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert pols[0].id.startswith("EWB-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(EurowebAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(EurowebAdapter())
        coa = a.get_chart_of_accounts()
        assert len(coa.cuentas) >= 5

    def test_get_balanza(self):
        a = _connected_adapter(EurowebAdapter())
        bal = a.get_balanza(2026, 3)
        assert bal.mes == 3


# ===================================================================
# 5. Absis adapter
# ===================================================================
class TestAbsisAdapter:
    def test_erp_type(self):
        assert AbsisAdapter().config.type == ERPType.ABSIS

    def test_connect_mock(self):
        a = AbsisAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "ABS010101AAA"

    def test_get_invoices(self):
        a = _connected_adapter(AbsisAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert invs[0].id.startswith("ABS-INV-")

    def test_get_polizas(self):
        a = _connected_adapter(AbsisAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert pols[0].id.startswith("ABS-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(AbsisAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(AbsisAdapter())
        coa = a.get_chart_of_accounts()
        assert len(coa.cuentas) >= 5

    def test_get_balanza(self):
        a = _connected_adapter(AbsisAdapter())
        bal = a.get_balanza(2026, 12)
        assert bal.mes == 12


# ===================================================================
# 6. Factor D adapter (Cloud, OAuth)
# ===================================================================
class TestFactorDAdapter:
    def test_erp_type(self):
        assert FactorDAdapter().config.type == ERPType.FACTOR_D

    def test_connect_mock(self):
        a = FactorDAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "FD010101AAA"

    def test_connect_with_credentials(self):
        a = FactorDAdapter()
        a.connect(credentials={"client_id": "real-id", "client_secret": "secret"})
        assert a.is_connected is True

    def test_get_invoices(self):
        a = _connected_adapter(FactorDAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert invs[0].id.startswith("FD-INV-")
        assert invs[0].forma_pago == "03"

    def test_get_polizas(self):
        a = _connected_adapter(FactorDAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert pols[0].id.startswith("FD-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(FactorDAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True
        assert result["id_erp"].startswith("FD-POL-")

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(FactorDAdapter())
        coa = a.get_chart_of_accounts()
        assert len(coa.cuentas) >= 5

    def test_get_balanza(self):
        a = _connected_adapter(FactorDAdapter())
        bal = a.get_balanza(2026, 7)
        assert bal.mes == 7
        assert bal.total_deudor > 0


# ===================================================================
# 7. Taxko adapter (Cloud, API Key)
# ===================================================================
class TestTaxkoAdapter:
    def test_erp_type(self):
        assert TaxkoAdapter().config.type == ERPType.TAXKO

    def test_connect_mock(self):
        a = TaxkoAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "TK010101AAA"

    def test_connect_with_api_key(self):
        a = TaxkoAdapter()
        a.connect(credentials={"api_key": "real-taxko-key"})
        assert a.is_connected is True

    def test_get_invoices(self):
        a = _connected_adapter(TaxkoAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert invs[0].id.startswith("TK-INV-")

    def test_get_polizas(self):
        a = _connected_adapter(TaxkoAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert pols[0].id.startswith("TK-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(TaxkoAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(TaxkoAdapter())
        coa = a.get_chart_of_accounts()
        assert len(coa.cuentas) >= 5

    def test_get_balanza(self):
        a = _connected_adapter(TaxkoAdapter())
        bal = a.get_balanza(2026, 2)
        assert bal.mes == 2


# ===================================================================
# 8. FacturaDirecta adapter (Cloud, API Key)
# ===================================================================
class TestFacturaDirectaAdapter:
    def test_erp_type(self):
        assert FacturaDirectaAdapter().config.type == ERPType.FACTURADIRECTA

    def test_connect_mock(self):
        a = FacturaDirectaAdapter()
        a.connect()
        assert a._empresa_info["rfc"] == "FDX010101AAA"

    def test_connect_with_credentials(self):
        a = FacturaDirectaAdapter()
        a.connect(credentials={"api_key": "real-fd-key", "token": "token123"})
        assert a.is_connected is True

    def test_get_invoices(self):
        a = _connected_adapter(FacturaDirectaAdapter())
        invs = a.get_invoices()
        assert len(invs) == 3
        assert invs[0].id.startswith("FDX-INV-")

    def test_get_polizas(self):
        a = _connected_adapter(FacturaDirectaAdapter())
        pols = a.get_polizas()
        assert len(pols) == 2
        assert pols[0].id.startswith("FDX-POL-")

    def test_upload_poliza(self):
        a = _connected_adapter(FacturaDirectaAdapter())
        pol = a.get_polizas()[0]
        result = a.upload_poliza(pol)
        assert result["exito"] is True
        assert result["id_erp"].startswith("FDX-POL-")

    def test_upload_poliza_unbalanced(self):
        a = _connected_adapter(FacturaDirectaAdapter())
        pol = Poliza(cuentas=[CuentaPoliza(cuenta="1101", debe=500, haber=0)])
        result = a.upload_poliza(pol)
        assert result["exito"] is False

    def test_get_chart_of_accounts(self):
        a = _connected_adapter(FacturaDirectaAdapter())
        coa = a.get_chart_of_accounts()
        assert len(coa.cuentas) >= 5
        assert coa.fecha_exportacion is not None

    def test_get_balanza(self):
        a = _connected_adapter(FacturaDirectaAdapter())
        bal = a.get_balanza(2026, 4)
        assert bal.mes == 4
        assert bal.total_acreedor > 0


# ===================================================================
# 9. Cross-adapter consistency
# ===================================================================
class TestCrossAdapterConsistency:
    def test_all_adapters_produce_invoices(self):
        for adapter in _all_new_adapters():
            a = _connected_adapter(adapter)
            invs = a.get_invoices()
            assert len(invs) >= 1, f"{type(a).__name__} produced no invoices"

    def test_all_adapters_produce_polizas(self):
        for adapter in _all_new_adapters():
            a = _connected_adapter(adapter)
            pols = a.get_polizas()
            assert len(pols) >= 1, f"{type(a).__name__} produced no polizas"

    def test_all_polizas_are_balanced(self):
        for adapter in _all_new_adapters():
            a = _connected_adapter(adapter)
            for pol in a.get_polizas():
                assert pol.esta_cuadrada(), f"{type(a).__name__} poliza {pol.id} not balanced"

    def test_all_chart_of_accounts_have_cuentas(self):
        for adapter in _all_new_adapters():
            a = _connected_adapter(adapter)
            coa = a.get_chart_of_accounts()
            assert len(coa.cuentas) >= 3

    def test_all_balanzas_have_totals(self):
        for adapter in _all_new_adapters():
            a = _connected_adapter(adapter)
            bal = a.get_balanza(2026, 1)
            assert bal.total_deudor > 0 or bal.total_acreedor > 0
