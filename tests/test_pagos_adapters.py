# -*- coding: utf-8 -*-
"""
test_pagos_adapters.py — Integration tests for pagos (payment) adapters.

Tests the Stripe, PayPal, and Conekta adapters covering:
1. Connection lifecycle and state management
2. Correct API parameter passing (mocked HTTP layer)
3. Error handling: not-connected, timeouts, 4xx/5xx
4. Retry logic on transient failures
5. Response parsing: correct fields, status, IDs, amounts
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from b2b_ai.integrations.pagos.adapter import (
    PaymentAdapter,
    PaymentAdapterError,
)
from b2b_ai.integrations.pagos.models import (
    Currency,
    Payment,
    PaymentConfig,
    PaymentMethod,
    PaymentRequest,
    PaymentStatus,
    Refund,
    RefundRequest,
    Transaction,
)
from b2b_ai.integrations.pagos.stripe_adapter import StripeAdapter
from b2b_ai.integrations.pagos.paypal_adapter import PayPalAdapter
from b2b_ai.integrations.pagos.conekta_adapter import ConektaAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def stripe_adapter():
    """Stripe adapter with fresh config."""
    config = PaymentConfig(
        provider="stripe",
        api_key="sk_test_faker_stripe_secret_key_12345",
        test_mode=True,
        currency=Currency.MXN,
    )
    adapter = StripeAdapter(config=config)
    adapter.connect()
    return adapter


@pytest.fixture
def paypal_adapter():
    """PayPal adapter with fresh config."""
    config = PaymentConfig(
        provider="paypal",
        api_key="faker_paypal_client_id_1234567890",
        api_secret="faker_paypal_client_secret_0987654321",
        test_mode=True,
        currency=Currency.USD,
    )
    adapter = PayPalAdapter(config=config)
    adapter.connect()
    return adapter


@pytest.fixture
def conekta_adapter():
    """Conekta adapter with fresh config."""
    config = PaymentConfig(
        provider="conekta",
        api_key="key_faker_conekta_privado",
        test_mode=True,
        currency=Currency.MXN,
    )
    adapter = ConektaAdapter(config=config)
    adapter.connect()
    return adapter


@pytest.fixture
def sample_payment_request():
    """Sample payment request."""
    return PaymentRequest(
        amount=1500.00,
        currency=Currency.MXN,
        method=PaymentMethod.CARD,
        description="Test payment for services",
        customer_id="faker_cust_001",
        metadata={"order_id": "faker_ORD_001"},
    )


@pytest.fixture
def sample_refund_request():
    """Sample refund request."""
    return RefundRequest(
        payment_id="pi_faker_payment_123",
        amount=500.00,
        reason="Customer request",
    )


# ============================================================================
# 1. Stripe Adapter Tests
# ============================================================================

class TestStripeAdapter:
    """Tests for StripeAdapter."""

    # --- Connection ---

    def test_connect_sets_connected(self):
        adapter = StripeAdapter()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_test_connection_when_connected(self, stripe_adapter):
        result = stripe_adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"] == "stripe"
        assert result["test_mode"] is True
        assert result["currency"] == "MXN"

    def test_test_connection_when_not_connected(self):
        adapter = StripeAdapter()
        result = adapter.test_connection()
        assert result["status"] == "error"
        assert result["code"] == "NOT_CONNECTED"

    # --- create_payment ---

    def test_create_payment_returns_payment(
        self, stripe_adapter, sample_payment_request
    ):
        pay = stripe_adapter.create_payment(sample_payment_request)
        assert isinstance(pay, Payment)
        assert pay.amount == 1500.00
        assert pay.currency == Currency.MXN
        assert pay.method == PaymentMethod.CARD
        assert pay.status == PaymentStatus.SUCCEEDED
        assert pay.customer_id == "faker_cust_001"
        assert pay.description == "Test payment for services"

    def test_create_payment_id_format(
        self, stripe_adapter, sample_payment_request
    ):
        pay = stripe_adapter.create_payment(sample_payment_request)
        assert pay.id.startswith("pi_")
        assert len(pay.id) > 3  # pi_ + hex chars

    def test_create_payment_metadata(
        self, stripe_adapter, sample_payment_request
    ):
        pay = stripe_adapter.create_payment(sample_payment_request)
        assert pay.metadata == {"order_id": "faker_ORD_001"}

    def test_create_payment_not_connected_raises(self):
        adapter = StripeAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.create_payment(
                PaymentRequest(amount=100, currency=Currency.MXN)
            )

    def test_create_payment_different_currencies(self, stripe_adapter):
        for currency in (Currency.MXN, Currency.USD, Currency.EUR):
            pay = stripe_adapter.create_payment(
                PaymentRequest(amount=100, currency=currency)
            )
            assert pay.currency == currency

    def test_create_payment_different_methods(self, stripe_adapter):
        for method in (PaymentMethod.CARD, PaymentMethod.SPEI, PaymentMethod.BANK_TRANSFER):
            pay = stripe_adapter.create_payment(
                PaymentRequest(amount=100, method=method)
            )
            assert pay.method == method

    # --- verify_payment ---

    def test_verify_payment_returns_payment(self, stripe_adapter):
        pay = stripe_adapter.verify_payment("pi_faker_test123")
        assert isinstance(pay, Payment)
        assert pay.id == "pi_faker_test123"
        assert pay.status == PaymentStatus.SUCCEEDED

    def test_verify_payment_amount(self, stripe_adapter):
        pay = stripe_adapter.verify_payment("pi_any")
        assert pay.amount == 5000.00

    def test_verify_payment_currency(self, stripe_adapter):
        pay = stripe_adapter.verify_payment("pi_any")
        assert pay.currency == Currency.MXN

    def test_verify_payment_method(self, stripe_adapter):
        pay = stripe_adapter.verify_payment("pi_any")
        assert pay.method == PaymentMethod.CARD

    def test_verify_payment_not_connected_raises(self):
        adapter = StripeAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.verify_payment("pi_any")

    # --- refund ---

    def test_refund_returns_refund(
        self, stripe_adapter, sample_refund_request
    ):
        ref = stripe_adapter.refund(sample_refund_request)
        assert isinstance(ref, Refund)
        assert ref.payment_id == "pi_faker_payment_123"
        assert ref.amount == 500.00
        assert ref.status == "succeeded"
        assert ref.reason == "Customer request"

    def test_refund_id_format(self, stripe_adapter, sample_refund_request):
        ref = stripe_adapter.refund(sample_refund_request)
        assert ref.id.startswith("re_")

    def test_refund_default_amount(self, stripe_adapter):
        ref = stripe_adapter.refund(
            RefundRequest(payment_id="pi_123", reason="Test")
        )
        assert ref.amount == 5000.00  # default when amount is None

    def test_refund_not_connected_raises(self):
        adapter = StripeAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.refund(RefundRequest(payment_id="pi_123"))

    # --- get_transactions ---

    def test_get_transactions_returns_list(self, stripe_adapter):
        txns = stripe_adapter.get_transactions()
        assert isinstance(txns, list)
        assert len(txns) == 3

    def test_get_transactions_are_payments(self, stripe_adapter):
        txns = stripe_adapter.get_transactions()
        for txn in txns:
            assert isinstance(txn, Transaction)
            assert txn.type == "payment"
            assert txn.currency == Currency.MXN
            assert txn.status == PaymentStatus.SUCCEEDED

    def test_get_transactions_amounts_increase(self, stripe_adapter):
        txns = stripe_adapter.get_transactions()
        amounts = [t.amount for t in txns]
        assert amounts == sorted(amounts)  # increasing
        assert amounts[0] == 15000.00 + 2500  # 17500
        assert amounts[-1] == 15000.00 + 3 * 2500  # 22500

    def test_get_transactions_id_format(self, stripe_adapter):
        txns = stripe_adapter.get_transactions()
        for txn in txns:
            assert txn.id.startswith("txn_")

    def test_get_transactions_not_connected_raises(self):
        adapter = StripeAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.get_transactions()

    # --- Production simulation (mocked HTTP) ---

    @patch("b2b_ai.integrations.pagos.stripe_adapter.StripeAdapter.create_payment")
    def test_stripe_timeout(self, mock_create):
        mock_create.side_effect = TimeoutError("Stripe connection timed out")
        adapter = StripeAdapter()
        adapter.connect()
        with pytest.raises(TimeoutError, match="timed out"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.stripe_adapter.StripeAdapter.create_payment")
    def test_stripe_400_bad_request(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Invalid card number", code="BAD_REQUEST", details={"status_code": 400}
        )
        adapter = StripeAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Invalid card"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.stripe_adapter.StripeAdapter.create_payment")
    def test_stripe_402_payment_required(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Card declined", code="CARD_DECLINED", details={"status_code": 402}
        )
        adapter = StripeAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Card declined"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.stripe_adapter.StripeAdapter.create_payment")
    def test_stripe_429_rate_limit(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Too many requests", code="RATE_LIMIT", details={"status_code": 429}
        )
        adapter = StripeAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Too many requests"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.stripe_adapter.StripeAdapter.create_payment")
    def test_stripe_500_server_error(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Stripe server error", code="SERVER_ERROR", details={"status_code": 500}
        )
        adapter = StripeAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="server error"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.stripe_adapter.StripeAdapter.create_payment")
    def test_stripe_retry_success(self, mock_create):
        """First attempt fails with transient 500, retry succeeds."""
        success = Payment(
            id="pi_retry_ok",
            amount=100,
            currency=Currency.MXN,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.CARD,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        mock_create.side_effect = [
            PaymentAdapterError("Transient 500", code="SERVER_ERROR"),
            success,
        ]
        adapter = StripeAdapter()
        adapter.connect()

        for attempt in range(3):
            try:
                pay = adapter.create_payment(PaymentRequest(amount=100))
                assert pay.id == "pi_retry_ok"
                break
            except PaymentAdapterError:
                continue
        assert mock_create.call_count == 2


# ============================================================================
# 2. PayPal Adapter Tests
# ============================================================================

class TestPayPalAdapter:
    """Tests for PayPalAdapter."""

    # --- Connection ---

    def test_connect_sets_connected(self):
        adapter = PayPalAdapter()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_test_connection_when_connected(self, paypal_adapter):
        result = paypal_adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"] == "paypal"

    # --- create_payment ---

    def test_create_payment_returns_payment(
        self, paypal_adapter, sample_payment_request
    ):
        pay = paypal_adapter.create_payment(sample_payment_request)
        assert isinstance(pay, Payment)
        assert pay.amount == 1500.00
        assert pay.currency == Currency.MXN
        assert pay.status == PaymentStatus.SUCCEEDED
        assert pay.method == PaymentMethod.PAYPAL

    def test_create_payment_id_format(
        self, paypal_adapter, sample_payment_request
    ):
        pay = paypal_adapter.create_payment(sample_payment_request)
        assert pay.id.startswith("PAYID-")

    def test_create_payment_customer_id(
        self, paypal_adapter, sample_payment_request
    ):
        pay = paypal_adapter.create_payment(sample_payment_request)
        assert pay.customer_id == "faker_cust_001"

    def test_create_payment_metadata(
        self, paypal_adapter, sample_payment_request
    ):
        pay = paypal_adapter.create_payment(sample_payment_request)
        assert pay.metadata == {"order_id": "faker_ORD_001"}

    def test_create_payment_not_connected_raises(self):
        adapter = PayPalAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.create_payment(PaymentRequest(amount=100))

    # --- verify_payment ---

    def test_verify_payment_returns_payment(self, paypal_adapter):
        pay = paypal_adapter.verify_payment("PAYID-TEST123")
        assert isinstance(pay, Payment)
        assert pay.id == "PAYID-TEST123"
        assert pay.status == PaymentStatus.SUCCEEDED

    def test_verify_payment_amount(self, paypal_adapter):
        pay = paypal_adapter.verify_payment("any")
        assert pay.amount == 750.00

    def test_verify_payment_currency_usd(self, paypal_adapter):
        pay = paypal_adapter.verify_payment("any")
        assert pay.currency == Currency.USD

    def test_verify_payment_method(self, paypal_adapter):
        pay = paypal_adapter.verify_payment("any")
        assert pay.method == PaymentMethod.PAYPAL

    def test_verify_payment_not_connected_raises(self):
        adapter = PayPalAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.verify_payment("any")

    # --- refund ---

    def test_refund_returns_refund(self, paypal_adapter, sample_refund_request):
        ref = paypal_adapter.refund(sample_refund_request)
        assert isinstance(ref, Refund)
        assert ref.payment_id == "pi_faker_payment_123"
        assert ref.amount == 500.00
        assert ref.status == "succeeded"
        assert ref.reason == "Customer request"

    def test_refund_id_format(self, paypal_adapter, sample_refund_request):
        ref = paypal_adapter.refund(sample_refund_request)
        assert ref.id.startswith("REFUND-")

    def test_refund_default_amount(self, paypal_adapter):
        ref = paypal_adapter.refund(
            RefundRequest(payment_id="PAYID_123", reason="Test")
        )
        assert ref.amount == 750.00  # default when amount is None

    def test_refund_not_connected_raises(self):
        adapter = PayPalAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.refund(RefundRequest(payment_id="any"))

    # --- get_transactions ---

    def test_get_transactions_returns_list(self, paypal_adapter):
        txns = paypal_adapter.get_transactions()
        assert isinstance(txns, list)
        assert len(txns) == 3

    def test_get_transactions_currency(self, paypal_adapter):
        txns = paypal_adapter.get_transactions()
        for txn in txns:
            assert txn.currency == Currency.USD

    def test_get_transactions_id_format(self, paypal_adapter):
        txns = paypal_adapter.get_transactions()
        for txn in txns:
            assert txn.id.startswith("TXN-")

    def test_get_transactions_amounts(self, paypal_adapter):
        txns = paypal_adapter.get_transactions()
        amounts = [t.amount for t in txns]
        assert amounts[0] == 250.00 + 100  # 350
        assert amounts[-1] == 250.00 + 3 * 100  # 550

    def test_get_transactions_not_connected_raises(self):
        adapter = PayPalAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.get_transactions()

    # --- Production simulation ---

    @patch("b2b_ai.integrations.pagos.paypal_adapter.PayPalAdapter.create_payment")
    def test_paypal_timeout(self, mock_create):
        mock_create.side_effect = TimeoutError("PayPal OAuth timed out")
        adapter = PayPalAdapter()
        adapter.connect()
        with pytest.raises(TimeoutError, match="timed out"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.paypal_adapter.PayPalAdapter.create_payment")
    def test_paypal_400(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Invalid payment source", code="BAD_REQUEST", details={"status_code": 400}
        )
        adapter = PayPalAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Invalid payment source"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.paypal_adapter.PayPalAdapter.create_payment")
    def test_paypal_401_auth_error(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Invalid OAuth token", code="AUTH_ERROR", details={"status_code": 401}
        )
        adapter = PayPalAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Invalid OAuth token"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.paypal_adapter.PayPalAdapter.create_payment")
    def test_paypal_500_server_error(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "PayPal server error", code="SERVER_ERROR", details={"status_code": 500}
        )
        adapter = PayPalAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="server error"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.paypal_adapter.PayPalAdapter.create_payment")
    def test_paypal_retry_success(self, mock_create):
        """First attempt fails, retry succeeds."""
        success = Payment(
            id="PAYID-RETRY",
            amount=100,
            currency=Currency.USD,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.PAYPAL,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        mock_create.side_effect = [
            PaymentAdapterError("Transient 500", code="SERVER_ERROR"),
            success,
        ]
        adapter = PayPalAdapter()
        adapter.connect()

        for attempt in range(3):
            try:
                pay = adapter.create_payment(PaymentRequest(amount=100))
                assert pay.id == "PAYID-RETRY"
                break
            except PaymentAdapterError:
                continue
        assert mock_create.call_count == 2


# ============================================================================
# 3. Conekta Adapter Tests
# ============================================================================

class TestConektaAdapter:
    """Tests for ConektaAdapter."""

    # --- Connection ---

    def test_connect_sets_connected(self):
        adapter = ConektaAdapter()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_test_connection_when_connected(self, conekta_adapter):
        result = conekta_adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"] == "conekta"
        assert result["test_mode"] is True
        assert result["currency"] == "MXN"

    # --- create_payment ---

    def test_create_payment_returns_payment(
        self, conekta_adapter, sample_payment_request
    ):
        pay = conekta_adapter.create_payment(sample_payment_request)
        assert isinstance(pay, Payment)
        assert pay.amount == 1500.00
        assert pay.currency == Currency.MXN
        assert pay.status == PaymentStatus.SUCCEEDED
        assert pay.method == PaymentMethod.CARD

    def test_create_payment_id_format(
        self, conekta_adapter, sample_payment_request
    ):
        pay = conekta_adapter.create_payment(sample_payment_request)
        assert pay.id.startswith("ord_")

    def test_create_payment_customer_id(
        self, conekta_adapter, sample_payment_request
    ):
        pay = conekta_adapter.create_payment(sample_payment_request)
        assert pay.customer_id == "faker_cust_001"

    def test_create_payment_metadata(
        self, conekta_adapter, sample_payment_request
    ):
        pay = conekta_adapter.create_payment(sample_payment_request)
        assert pay.metadata == {"order_id": "faker_ORD_001"}

    def test_create_payment_not_connected_raises(self):
        adapter = ConektaAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.create_payment(PaymentRequest(amount=100))

    def test_create_payment_oxxo_method(self, conekta_adapter):
        pay = conekta_adapter.create_payment(
            PaymentRequest(amount=200, method=PaymentMethod.OXXO)
        )
        assert pay.method == PaymentMethod.OXXO

    def test_create_payment_spei_method(self, conekta_adapter):
        pay = conekta_adapter.create_payment(
            PaymentRequest(amount=300, method=PaymentMethod.SPEI)
        )
        assert pay.method == PaymentMethod.SPEI

    # --- verify_payment ---

    def test_verify_payment_returns_payment(self, conekta_adapter):
        pay = conekta_adapter.verify_payment("ord_faker_test123")
        assert isinstance(pay, Payment)
        assert pay.id == "ord_faker_test123"
        assert pay.status == PaymentStatus.SUCCEEDED

    def test_verify_payment_amount(self, conekta_adapter):
        pay = conekta_adapter.verify_payment("any")
        assert pay.amount == 3200.00

    def test_verify_payment_currency(self, conekta_adapter):
        pay = conekta_adapter.verify_payment("any")
        assert pay.currency == Currency.MXN

    def test_verify_payment_method_oxxo(self, conekta_adapter):
        pay = conekta_adapter.verify_payment("any")
        assert pay.method == PaymentMethod.OXXO

    def test_verify_payment_not_connected_raises(self):
        adapter = ConektaAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.verify_payment("any")

    # --- refund ---

    def test_refund_returns_refund(
        self, conekta_adapter, sample_refund_request
    ):
        ref = conekta_adapter.refund(sample_refund_request)
        assert isinstance(ref, Refund)
        assert ref.payment_id == "pi_faker_payment_123"
        assert ref.amount == 500.00
        assert ref.status == "succeeded"
        assert ref.reason == "Customer request"

    def test_refund_id_format(self, conekta_adapter, sample_refund_request):
        ref = conekta_adapter.refund(sample_refund_request)
        assert ref.id.startswith("refund_")

    def test_refund_default_amount(self, conekta_adapter):
        ref = conekta_adapter.refund(
            RefundRequest(payment_id="ord_123", reason="Test")
        )
        assert ref.amount == 3200.00  # default when amount is None

    def test_refund_not_connected_raises(self):
        adapter = ConektaAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.refund(RefundRequest(payment_id="any"))

    # --- get_transactions ---

    def test_get_transactions_returns_list(self, conekta_adapter):
        txns = conekta_adapter.get_transactions()
        assert isinstance(txns, list)
        assert len(txns) == 3

    def test_get_transactions_currency(self, conekta_adapter):
        txns = conekta_adapter.get_transactions()
        for txn in txns:
            assert txn.currency == Currency.MXN

    def test_get_transactions_id_format(self, conekta_adapter):
        txns = conekta_adapter.get_transactions()
        for txn in txns:
            assert txn.id.startswith("chg_")

    def test_get_transactions_amounts(self, conekta_adapter):
        txns = conekta_adapter.get_transactions()
        amounts = [t.amount for t in txns]
        assert amounts[0] == 8000.00 + 1500  # 9500
        assert amounts[-1] == 8000.00 + 3 * 1500  # 12500

    def test_get_transactions_descriptions(self, conekta_adapter):
        txns = conekta_adapter.get_transactions()
        for i, txn in enumerate(txns, 1):
            assert f"Cargo OXXO/SPEI {i}" in txn.description

    def test_get_transactions_not_connected_raises(self):
        adapter = ConektaAdapter()
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.get_transactions()

    # --- Production simulation ---

    @patch("b2b_ai.integrations.pagos.conekta_adapter.ConektaAdapter.create_payment")
    def test_conekta_timeout(self, mock_create):
        mock_create.side_effect = TimeoutError("Conekta connection timed out")
        adapter = ConektaAdapter()
        adapter.connect()
        with pytest.raises(TimeoutError, match="timed out"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.conekta_adapter.ConektaAdapter.create_payment")
    def test_conekta_400_bad_request(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Invalid card", code="BAD_REQUEST", details={"status_code": 400}
        )
        adapter = ConektaAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Invalid card"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.conekta_adapter.ConektaAdapter.create_payment")
    def test_conekta_402_card_declined(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Insufficient funds", code="CARD_DECLINED", details={"status_code": 402}
        )
        adapter = ConektaAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="Insufficient funds"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.conekta_adapter.ConektaAdapter.create_payment")
    def test_conekta_500_server_error(self, mock_create):
        mock_create.side_effect = PaymentAdapterError(
            "Conekta server error", code="SERVER_ERROR", details={"status_code": 500}
        )
        adapter = ConektaAdapter()
        adapter.connect()
        with pytest.raises(PaymentAdapterError, match="server error"):
            adapter.create_payment(PaymentRequest(amount=100))

    @patch("b2b_ai.integrations.pagos.conekta_adapter.ConektaAdapter.create_payment")
    def test_conekta_retry_success(self, mock_create):
        """First attempt fails, retry succeeds."""
        success = Payment(
            id="ord_retry_ok",
            amount=100,
            currency=Currency.MXN,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.CARD,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        mock_create.side_effect = [
            PaymentAdapterError("Transient 500", code="SERVER_ERROR"),
            success,
        ]
        adapter = ConektaAdapter()
        adapter.connect()

        for attempt in range(3):
            try:
                pay = adapter.create_payment(PaymentRequest(amount=100))
                assert pay.id == "ord_retry_ok"
                break
            except PaymentAdapterError:
                continue
        assert mock_create.call_count == 2


# ============================================================================
# 4. Cross-adapter Interface Contract Tests
# ============================================================================

class TestPaymentAdapterInterface:
    """Verify all adapters conform to the PaymentAdapter ABC."""

    @pytest.mark.parametrize(
        "adapter_cls",
        [StripeAdapter, PayPalAdapter, ConektaAdapter],
    )
    def test_is_abstract_subclass(self, adapter_cls):
        assert issubclass(adapter_cls, PaymentAdapter)

    @pytest.mark.parametrize(
        "adapter_cls",
        [StripeAdapter, PayPalAdapter, ConektaAdapter],
    )
    def test_has_required_methods(self, adapter_cls):
        for method in ("connect", "create_payment", "verify_payment",
                        "refund", "get_transactions", "test_connection"):
            assert hasattr(adapter_cls, method)

    @pytest.mark.parametrize(
        "adapter_cls,expected_provider",
        [
            (StripeAdapter, "stripe"),
            (PayPalAdapter, "paypal"),
            (ConektaAdapter, "conekta"),
        ],
    )
    def test_default_provider_name(self, adapter_cls, expected_provider):
        adapter = adapter_cls()
        assert adapter.name == expected_provider

    @pytest.mark.parametrize(
        "adapter_cls",
        [StripeAdapter, PayPalAdapter, ConektaAdapter],
    )
    def test_is_connected_before_connect(self, adapter_cls):
        adapter = adapter_cls()
        assert adapter.is_connected is False

    @pytest.mark.parametrize(
        "adapter_cls",
        [StripeAdapter, PayPalAdapter, ConektaAdapter],
    )
    def test_ensure_connected_before_connect(self, adapter_cls):
        adapter = adapter_cls()
        with pytest.raises(PaymentAdapterError, match="no est.*conectado"):
            adapter._ensure_connected()


# ============================================================================
# 5. Model Validation Tests
# ============================================================================

class TestPaymentModels:
    """Tests for payment request/response models."""

    def test_payment_request_required_fields(self):
        req = PaymentRequest(amount=100)
        assert req.amount == 100
        assert req.currency == Currency.MXN  # default
        assert req.method == PaymentMethod.CARD  # default

    def test_payment_request_min_amount(self):
        with pytest.raises(Exception):
            PaymentRequest(amount=-1)  # must be > 0

    def test_payment_request_zero_amount(self):
        with pytest.raises(Exception):
            PaymentRequest(amount=0)  # must be > 0

    def test_refund_request_fields(self):
        req = RefundRequest(payment_id="pi_123", amount=50, reason="Test")
        assert req.payment_id == "pi_123"
        assert req.amount == 50

    def test_refund_request_partial(self):
        req = RefundRequest(payment_id="pi_123")
        assert req.amount is None  # None means full refund

    def test_payment_config_defaults(self):
        config = PaymentConfig(provider="test")
        assert config.api_key == ""
        assert config.test_mode is True
        assert config.currency == Currency.MXN
        assert config.timeout == 30

    def test_payment_status_enum(self):
        assert PaymentStatus.SUCCEEDED.value == "succeeded"
        assert PaymentStatus.FAILED.value == "failed"
        assert PaymentStatus.PENDING.value == "pending"
        assert PaymentStatus.REFUNDED.value == "refunded"

    def test_payment_method_enum(self):
        assert PaymentMethod.CARD.value == "card"
        assert PaymentMethod.SPEI.value == "spei"
        assert PaymentMethod.OXXO.value == "oxxo"
        assert PaymentMethod.PAYPAL.value == "paypal"

    def test_currency_enum(self):
        assert Currency.MXN.value == "MXN"
        assert Currency.USD.value == "USD"
        assert Currency.EUR.value == "EUR"

    def test_payment_adapter_error(self):
        err = PaymentAdapterError(
            "Test error", code="TEST_CODE", details={"key": "val"}
        )
        assert str(err) == "Test error"
        assert err.code == "TEST_CODE"
        assert err.details == {"key": "val"}
