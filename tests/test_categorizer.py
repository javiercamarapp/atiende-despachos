# -*- coding: utf-8 -*-
"""
test_categorizer.py — Tests del motor de auto-categorización de transacciones.

Cubre:
  - TransactionCategorizer.categorize_transaction : clasificación por
    palabras clave (nómina, impuestos/SAT, servicios, transferencias,
    depósitos, retiros, comisiones), por RFC y por monto.
  - Reglas configurables (add_rfc_rule / add_keyword_rule / add_amount_rule).
  - Pistas por canal de pago.
  - Soporte de llm_router (futuro): solo se invoca cuando no hay regla.
  - Integración con BankFeedService.sync_transactions / categorize_transaction.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.bank_feeds.categorizer import (
    TransactionCategorizer,
    categorize_transaction,
)
from b2b_ai.features.bank_feeds.models import (
    BankProvider,
    Category,
    PaymentChannel,
    TransactionStatus,
)
from b2b_ai.features.bank_feeds.service import (
    BankFeedService,
    get_categorizer,
    set_categorizer,
    _reset_state,
)


def txn(**over):
    base = {
        "external_id": "T-1",
        "date": "2026-07-03",
        "description": "",
        "reference": "",
        "amount": 100.0,
        "channel": "OTRO",
        "counterparty": "",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Clasificación por palabras clave
# ---------------------------------------------------------------------------


class TestKeywordClassification:
    def test_nomina(self):
        assert categorize_transaction(txn(description="Pago de nomina quincenal")) == "NOMINA"

    def test_sueldo_salario(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Sueldo mensual empleado")) == "NOMINA"

    def test_impuestos_sat(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Pago al SAT ISR")) == "IMPUESTOS"
        assert cat.categorize_transaction(txn(description="Retención de IVA")) == "IMPUESTOS"

    def test_comision_bancaria(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Comisión por manejo de cuenta")) == "FINANCIEROS"

    def test_proveedor(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Pago a proveedor mercancía")) == "COMPRAS"

    def test_servicios(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Renta de oficina")) == "SERVICIOS"
        assert cat.categorize_transaction(txn(description="Internet y teléfono")) == "SERVICIOS"

    def test_transferencia_spei(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Transferencia SPEI a cuenta")) == "TRANSFERENCIAS"

    def test_deposito_venta(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Depósito de cliente")) == "VENTAS"
        assert cat.categorize_transaction(txn(description="Cobro CoDi")) == "VENTAS"

    def test_retiro_default(self):
        # Un retiro sin pista textual cae en OTROS (no clasificable).
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Retiro en cajero")) == "OTROS"


# ---------------------------------------------------------------------------
# Clasificación por RFC y monto (configuración)
# ---------------------------------------------------------------------------


class TestConfigurableRules:
    def test_rfc_rule_overrides_keyword(self):
        cat = TransactionCategorizer()
        cat.add_rfc_rule("PAP850101JKL", Category.COMPRAS)
        # Mismo texto que en servicios, pero el RFC gana.
        result = cat.categorize_transaction(txn(
            description="Pago a proveedor mercancía",
            counterparty="PAP850101JKL",
        ))
        assert result == "COMPRAS"

    def test_rfc_rule_matches_normalized(self):
        cat = TransactionCategorizer()
        cat.add_rfc_rule("pap850101jkl", Category.COMPRAS)  # minúsculas
        assert cat.categorize_transaction(txn(counterparty="PAP850101JKL")) == "COMPRAS"

    def test_amount_rule(self):
        cat = TransactionCategorizer()
        cat.add_amount_rule(Category.NOMINA, min_amount=10000.0)
        assert cat.categorize_transaction(txn(description="Pago", amount=15000.0)) == "NOMINA"
        # Bajo el umbral no aplica la regla de monto.
        assert cat.categorize_transaction(txn(description="Pago", amount=500.0)) == "OTROS"

    def test_channel_hint(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="Movimiento", channel="SPEI")) == "TRANSFERENCIAS"

    def test_invalid_rfc_raises(self):
        cat = TransactionCategorizer()
        with pytest.raises(ValueError):
            cat.add_rfc_rule("", Category.OTROS)


# ---------------------------------------------------------------------------
# LLM router (futuro)
# ---------------------------------------------------------------------------


class TestLlmRouter:
    def test_llm_used_when_no_rule_matches(self):
        called = {"n": 0}

        def router(transaction):
            called["n"] += 1
            return Category.SERVICIOS

        cat = TransactionCategorizer(llm_router=router)
        assert cat.categorize_transaction(txn(description="Concepto misterioso")) == "SERVICIOS"
        assert called["n"] == 1

    def test_llm_not_called_when_rule_matches(self):
        called = {"n": 0}

        def router(transaction):
            called["n"] += 1
            return Category.SERVICIOS

        cat = TransactionCategorizer(llm_router=router)
        assert cat.categorize_transaction(txn(description="Pago de nomina")) == "NOMINA"
        assert called["n"] == 0

    def test_llm_invalid_output_falls_back_to_default(self):
        def router(transaction):
            return "NO_EXISTE"

        cat = TransactionCategorizer(llm_router=router)
        assert cat.categorize_transaction(txn(description="x")) == "OTROS"


# ---------------------------------------------------------------------------
# Integración con el servicio
# ---------------------------------------------------------------------------


class TestServiceIntegration:
    @pytest.fixture(autouse=True)
    def _clean(self):
        _reset_state()
        set_categorizer(TransactionCategorizer())  # motor limpio
        yield
        _reset_state()

    def test_sync_assigns_category(self):
        svc = BankFeedService()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        result = svc.sync_transactions(acct.id)
        assert result.sync.status == "completed"
        assert all(t.category is not None for t in result.transactions)

    def test_auto_categorize_sets_status(self):
        svc = BankFeedService()
        acct = svc.register_account(provider=BankProvider.BBVA, tenant_id="t1")
        svc.sync_transactions(acct.id)
        txn = svc.list_transactions(account_id=acct.id)[0]
        updated = svc.categorize_transaction(txn.id, auto=True)
        assert updated.category is not None
        assert updated.status == TransactionStatus.CATEGORIZED

    def test_set_categorizer_custom(self):
        custom = TransactionCategorizer()
        custom.add_rfc_rule("PAP850101JKL", Category.COMPRAS)
        set_categorizer(custom)
        assert get_categorizer() is custom


# ---------------------------------------------------------------------------
# Slot LLM futuro
# ---------------------------------------------------------------------------


class TestFutureLlmSlot:
    def test_classify_with_llm_raises_not_implemented(self):
        cat = TransactionCategorizer()
        with pytest.raises(NotImplementedError) as excinfo:
            cat.classify_with_llm(txn(description="algo"))
        assert "Future LLM integration" in str(excinfo.value)

    def test_classify_with_llm_is_method_slot(self):
        # El método existe y es llamable, solo aún no implementado.
        assert callable(TransactionCategorizer.classify_with_llm)


# ---------------------------------------------------------------------------
# Orden de prioridad: RFC > keyword > amount > default
# ---------------------------------------------------------------------------


class TestPriorityOrder:
    def test_keyword_before_amount(self):
        # Configurar keyword (SERVICIOS para "renta") y amount (NOMINA >= 10000).
        cat = TransactionCategorizer()
        cat.add_keyword_rule(r"renta", Category.SERVICIOS)
        cat.add_amount_rule(Category.NOMINA, min_amount=10000.0)
        # Ambos aplicarían, pero la keyword gana por prioridad (spec).
        result = cat.categorize_transaction(txn(description="Renta mensual", amount=15000.0))
        assert result == "SERVICIOS"

    def test_rfc_beats_keyword_and_amount(self):
        cat = TransactionCategorizer()
        cat.add_rfc_rule("PAP850101JKL", Category.COMPRAS)
        cat.add_keyword_rule(r"renta", Category.SERVICIOS)
        cat.add_amount_rule(Category.NOMINA, min_amount=10000.0)
        result = cat.categorize_transaction(txn(
            description="Renta oficina",
            counterparty="PAP850101JKL",
            amount=15000.0,
        ))
        assert result == "COMPRAS"

    def test_default_when_no_rule(self):
        cat = TransactionCategorizer()
        assert cat.categorize_transaction(txn(description="concepto desconocido")) == "OTROS"


# ---------------------------------------------------------------------------
# Observabilidad: logging de la regla que hizo match
# ---------------------------------------------------------------------------


class TestObservability:
    def test_logs_matched_rule(self, caplog):
        import logging
        cat = TransactionCategorizer()
        with caplog.at_level(logging.INFO, logger="b2b_ai.bank_feeds"):
            cat.categorize_transaction(txn(description="Pago de nomina quincenal"))
        records = [r.getMessage() for r in caplog.records]
        assert any("matched keyword rule" in m and "NOMINA" in m for m in records)

    def test_logs_rfc_rule(self, caplog):
        import logging
        cat = TransactionCategorizer()
        cat.add_rfc_rule("PAP850101JKL", Category.COMPRAS)
        with caplog.at_level(logging.INFO, logger="b2b_ai.bank_feeds"):
            cat.categorize_transaction(txn(counterparty="PAP850101JKL"))
        records = [r.getMessage() for r in caplog.records]
        assert any("matched RFC rule" in m and "COMPRAS" in m for m in records)
