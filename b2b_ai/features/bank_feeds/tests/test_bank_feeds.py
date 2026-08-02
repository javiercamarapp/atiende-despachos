# -*- coding: utf-8 -*-
"""Tests del módulo de Bank Feeds: parsers OFX/CNBV, adapters, servicio y
endpoints REST."""
from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from b2b_ai.features.bank_feeds.models import (
    BankAccount,
    BankProvider,
    Category,
    PaymentChannel,
    SyncStatus,
    TransactionStatus,
)
from b2b_ai.features.bank_feeds.processors.ofx import parse_ofx
from b2b_ai.features.bank_feeds.processors.cnbv import parse_cnbv
from b2b_ai.features.bank_feeds.service import BankFeedService, _reset_state
from b2b_ai.features.bank_feeds.adapters import (
    BBVAAdapter,
    BanorteAdapter,
    SantanderAdapter,
    HSBCAdapter,
    MockBankAdapter,
    get_adapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_OFX = """OFXHEADER:100
VERSION:102
<OFX>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <STMTRS>
        <BANKACCTFROM><BANKID>012</BANKID><ACCTID>000012345678901234</ACCTID></BANKACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>CREDIT</TRNTYPE>
            <DTPOSTED>20250115000000[0:GMT]</DTPOSTED>
            <TRNAMT>15000.00</TRNAMT>
            <FITID>SPEI-1001</FITID>
            <NAME>Transferencia SPEI</NAME>
            <MEMO>Cliente A</MEMO>
          </STMTTRN>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250116000000[0:GMT]</DTPOSTED>
            <TRNAMT>-5200.00</TRNAMT>
            <FITID>SPEI-1002</FITID>
            <NAME>Pago proveedor</NAME>
            <MEMO>Factura 0012</MEMO>
          </STMTTRN>
        </BANKTRANLIST>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""

SAMPLE_CNBV = """Fecha,Descripcion,Referencia,Cargo,Abono
2025-01-15,Transferencia SPEI recibida,SPEI-1001,,15000.00
2025-01-16,Pago proveedor,SPEI-1002,5200.00,
2025-01-17,Cobro CoDi,CODI-2001,,780.50
"""


def _fake_auth():
    async def dependency():
        return {"tenant_id": "tenant-1"}
    return dependency


def _make_service():
    _reset_state()
    return BankFeedService()


def _build_test_client():
    from b2b_ai.features.bank_feeds.routes import build_bank_feeds_router

    _reset_state()
    router = build_bank_feeds_router(db=None, require_api_key=_fake_auth())
    app = APIRouter()
    # No podemos montar un router en un router con TestClient directamente;
    # construimos una FastAPI mínima.
    from fastapi import FastAPI

    fastapp = FastAPI()
    fastapp.include_router(router)
    return TestClient(fastapp)


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_state()
    yield
    _reset_state()


# ---------------------------------------------------------------------------
# OFX parser
# ---------------------------------------------------------------------------


class TestOfxParser:
    def test_parses_stmttrn_blocks(self):
        moves = parse_ofx(SAMPLE_OFX)
        assert len(moves) == 2
        assert moves[0].external_id == "SPEI-1001"
        assert moves[0].date == "2025-01-15"
        assert moves[0].amount == "15000.00"
        assert moves[0].type_raw == "CREDIT"
        assert moves[1].external_id == "SPEI-1002"
        assert moves[1].type_raw == "DEBIT"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_ofx("")

    def test_no_stmttrn_raises(self):
        with pytest.raises(ValueError):
            parse_ofx("<OFX><x/></OFX>")


# ---------------------------------------------------------------------------
# CNBV parser
# ---------------------------------------------------------------------------


class TestCnbvParser:
    def test_parses_cargo_abono(self):
        moves = parse_cnbv(SAMPLE_CNBV)
        assert len(moves) == 3
        # Abono -> positivo
        assert float(moves[0].amount) == 15000.00
        assert moves[0].type_raw == "CREDIT"
        # Cargo -> negativo
        assert float(moves[1].amount) == -5200.00
        assert moves[1].type_raw == "DEBIT"
        assert moves[2].description == "Cobro CoDi"

    def test_date_formats(self):
        moves = parse_cnbv("Fecha;Importe\n15/01/2025;100.00\n")
        assert moves[0].date == "2025-01-15"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_cnbv("")


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class TestAdapters:
    def test_get_adapter_known(self):
        assert isinstance(get_adapter("BBVA"), BBVAAdapter)
        assert isinstance(get_adapter("BANORTE"), BanorteAdapter)
        assert isinstance(get_adapter("SANTANDER"), SantanderAdapter)
        assert isinstance(get_adapter("HSBC"), HSBCAdapter)

    def test_get_adapter_unknown(self):
        with pytest.raises(ValueError):
            get_adapter("XYZ")

    def test_bbva_parses_ofx_content(self):
        adapter = BBVAAdapter()
        moves = adapter.fetch_transactions({"ofx_content": SAMPLE_OFX})
        assert len(moves) == 2
        assert moves[0].external_id == "SPEI-1001"

    def test_bbva_falls_back_to_mock(self):
        adapter = BBVAAdapter()
        moves = adapter.fetch_transactions({})
        assert len(moves) >= 1
        assert all(m.external_id.startswith("BBVA:") for m in moves)

    def test_banorte_parses_cnbv(self):
        adapter = BanorteAdapter()
        moves = adapter.fetch_transactions({"statement_text": SAMPLE_CNBV})
        assert len(moves) == 3

    def test_mock_deterministic(self):
        a = MockBankAdapter(provider=BankProvider.HSBC).fetch_transactions({})
        b = MockBankAdapter(provider=BankProvider.HSBC).fetch_transactions({})
        assert [m.external_id for m in a] == [m.external_id for m in b]


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class TestBankFeedService:
    def test_register_and_list_accounts(self):
        svc = _make_service()
        acct = svc.register_account(
            provider=BankProvider.BBVA, clabe="012345678901234567",
            account_label="Operativa", tenant_id="t1",
        )
        assert acct.provider == BankProvider.BBVA
        assert len(svc.list_accounts(tenant_id="t1")) == 1
        assert len(svc.list_accounts(tenant_id="otra")) == 0

    def test_register_invalid_clabe(self):
        svc = _make_service()
        with pytest.raises(ValueError):
            svc.register_account(provider=BankProvider.BBVA, clabe="123")

    def test_sync_imports_mock_transactions(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        result = svc.sync_transactions(acct.id)
        assert result.sync.status == SyncStatus.COMPLETED
        assert result.sync.imported_count > 0
        assert result.sync.found_count == result.sync.imported_count
        assert result.transactions
        txn = result.transactions[0]
        assert txn.provider == BankProvider.BBVA
        assert txn.type.value in ("INGRESO", "EGRESO")
        assert txn.status == TransactionStatus.IMPORTED

    def test_sync_dedupes_on_second_run(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        first = svc.sync_transactions(acct.id)
        second = svc.sync_transactions(acct.id)
        assert second.sync.duplicate_count == first.sync.imported_count
        assert second.sync.imported_count == 0

    def test_sync_unknown_account_raises(self):
        svc = _make_service()
        with pytest.raises(KeyError):
            svc.sync_transactions("no-existe")

    def test_categorize_auto(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        svc.sync_transactions(acct.id)
        txn = svc.list_transactions(account_id=acct.id)[0]
        updated = svc.categorize_transaction(txn.id, auto=True)
        assert updated.category is not None
        assert updated.status == TransactionStatus.CATEGORIZED

    def test_categorize_manual(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        svc.sync_transactions(acct.id)
        txn = svc.list_transactions(account_id=acct.id)[0]
        updated = svc.categorize_transaction(txn.id, category=Category.IMPUESTOS)
        assert updated.category == Category.IMPUESTOS

    def test_categorize_unknown_raises(self):
        svc = _make_service()
        with pytest.raises(KeyError):
            svc.categorize_transaction("x", auto=True)

    def test_reconcile_no_transactions(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        result = svc.reconcile_with_cfdi(account_id=acct.id)
        assert result["reconciled"] == 0
        assert result["unmatched"] == 0

    def test_reconcile_with_cfdi_list(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        svc.sync_transactions(acct.id)
        result = svc.reconcile_with_cfdi(account_id=acct.id, cfdi_list=[])
        assert "report" in result
        assert result["total"] >= 1

    def test_get_syncs(self):
        svc = _make_service()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        svc.sync_transactions(acct.id)
        syncs = svc.get_syncs(account_id=acct.id)
        assert len(syncs) == 1


# ---------------------------------------------------------------------------
# Endpoints REST
# ---------------------------------------------------------------------------


class TestBankFeedRoutes:
    def test_connect_account(self):
        client = _build_test_client()
        r = client.post("/api/v1/bank-feeds/accounts", json={
            "provider": "BBVA",
            "clabe": "012345678901234567",
            "account_label": "Operativa",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["provider"] == "BBVA"

    def test_list_accounts(self):
        client = _build_test_client()
        client.post("/api/v1/bank-feeds/accounts", json={"provider": "HSBC"})
        r = client.get("/api/v1/bank-feeds/accounts")
        assert r.status_code == 200
        assert len(r.json()["data"]) >= 1

    def test_sync_account(self):
        client = _build_test_client()
        acct = client.post("/api/v1/bank-feeds/accounts", json={"provider": "BBVA"}).json()["data"]
        r = client.post(f"/api/v1/bank-feeds/accounts/{acct['id']}/sync")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["sync"]["status"] == "completed"
        assert data["sync"]["imported"] > 0

    def test_transactions_endpoint(self):
        client = _build_test_client()
        acct = client.post("/api/v1/bank-feeds/accounts", json={"provider": "BBVA"}).json()["data"]
        client.post(f"/api/v1/bank-feeds/accounts/{acct['id']}/sync")
        r = client.get(f"/api/v1/bank-feeds/accounts/{acct['id']}/transactions")
        assert r.status_code == 200
        assert len(r.json()["data"]) > 0

    def test_categorize_endpoint(self):
        client = _build_test_client()
        acct = client.post("/api/v1/bank-feeds/accounts", json={"provider": "BBVA"}).json()["data"]
        client.post(f"/api/v1/bank-feeds/accounts/{acct['id']}/sync")
        txns = client.get(f"/api/v1/bank-feeds/accounts/{acct['id']}/transactions").json()["data"]
        txn_id = txns[0]["id"]
        r = client.post(f"/api/v1/bank-feeds/transactions/{txn_id}/categorize", json={"auto": True})
        assert r.status_code == 200
        assert r.json()["data"]["category"] is not None

    def test_reconcile_endpoint(self):
        client = _build_test_client()
        acct = client.post("/api/v1/bank-feeds/accounts", json={"provider": "BBVA"}).json()["data"]
        client.post(f"/api/v1/bank-feeds/accounts/{acct['id']}/sync")
        r = client.post("/api/v1/bank-feeds/reconcile", json={"account_id": acct["id"], "cfdi_list": []})
        assert r.status_code == 200
        assert "report" in r.json()["data"]

    def test_unknown_account_404(self):
        client = _build_test_client()
        r = client.post("/api/v1/bank-feeds/accounts/no-such/sync")
        assert r.status_code == 404

    def test_router_requires_auth(self):
        with pytest.raises(ValueError):
            from b2b_ai.features.bank_feeds.routes import build_bank_feeds_router
            build_bank_feeds_router(db=None, require_api_key=None)
