# -*- coding: utf-8 -*-
"""Tests de multi-tenant (FASE 4): onboarding, config por cliente,
aislamiento de datos y fábrica de ERP."""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.db.tenants import (TenantManager, TenantNotFoundError,
                               CONFIG_DEFAULTS)
from b2b_ai.erp.contpaqi import MockCONTPAQi
from b2b_ai.erp.csv_erp import CSVErp


@pytest.fixture
def tm(tmp_path):
    return TenantManager(Database(str(tmp_path / "tenants.db")))


def test_onboarding_crea_config_y_api_key(tm):
    out = tm.onboard_tenant("Cliente A", rfc="XAXX010101000",
                            erp_type="csv", webhook_url="https://x/h")
    assert out["id"] >= 1
    assert out["rfc"] == "XAXX010101000"
    assert out["api_key"]
    cfg = tm.get_config(out["id"])
    assert cfg["erp_type"] == "csv"
    assert cfg["plantilla_contable"] == "SAT"
    assert cfg["webhook_url"] == "https://x/h"
    assert cfg["policy_human_review"] == "hold"  # default
    assert len(tm.db.list_api_keys(out["id"])) == 1


def test_defaults_de_config(tm):
    out = tm.onboard_tenant("Cliente B")
    cfg = tm.get_config(out["id"])
    for k, v in CONFIG_DEFAULTS.items():
        assert cfg[k] == v


def test_set_config_upsert(tm):
    out = tm.onboard_tenant("Cliente C")
    tm.set_config(out["id"], plantilla_contable="Pymes")
    tm.set_config(out["id"], erp_type="contpaqi")
    cfg = tm.get_config(out["id"])
    assert cfg["plantilla_contable"] == "Pymes"
    assert cfg["erp_type"] == "contpaqi"


def test_tenant_no_existe_levanta(tm):
    with pytest.raises(TenantNotFoundError):
        tm.get_tenant(99999)
    with pytest.raises(TenantNotFoundError):
        tm.get_config(99999)


def test_erp_factory_segun_config(tm):
    a = tm.onboard_tenant("ERP CSV", erp_type="csv")
    b = tm.onboard_tenant("ERP CONTPAQi", erp_type="contpaqi")
    assert isinstance(tm.erp_factory(a["id"]), CSVErp)
    assert isinstance(tm.erp_factory(b["id"]), MockCONTPAQi)


def test_erp_factory_inyeccion(tm):
    out = tm.onboard_tenant("Cliente D")
    custom = MockCONTPAQi()
    assert tm.erp_factory(out["id"], erp=custom) is custom


def test_aislamiento_de_datos(tmp_path):
    db = Database(str(tmp_path / "iso.db"))
    tm = TenantManager(db)
    a = tm.onboard_tenant("Tenant A")
    b = tm.onboard_tenant("Tenant B")
    # insertar facturas en ambos (directo por db, con tenant_id)
    db.insert_invoice(a["id"], {"folio_fiscal": "AAA-1", "archivo": "a.xml",
                                "emisor_rfc": "A1", "total": "10"},
                      {"categoria": "gasto_operativo", "confianza": 0.9,
                       "razon": ""}, {"ok": True})
    db.insert_invoice(b["id"], {"folio_fiscal": "BBB-1", "archivo": "b.xml",
                                "emisor_rfc": "B1", "total": "20"},
                      {"categoria": "inversion", "confianza": 0.9,
                       "razon": ""}, {"ok": True})
    # cada tenant solo ve sus facturas
    assert len(tm.scoped_invoices(a["id"])) == 1
    assert len(tm.scoped_invoices(b["id"])) == 1
    inv_a = tm.scoped_invoices(a["id"])[0]
    assert inv_a["folio_fiscal"] == "AAA-1"
    assert tm.scoped_invoice(b["id"], inv_a["id"]) is None  # aislado


def test_onboard_funcional(tmp_db):
    from b2b_ai.db.tenants import onboard_tenant
    out = onboard_tenant(tmp_db, name="Cliente X", rfc="RFC")
    assert out["id"] >= 1
    assert tmp_db.list_tenants()[-1]["name"] == "Cliente X"
