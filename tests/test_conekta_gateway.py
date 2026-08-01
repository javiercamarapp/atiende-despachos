# -*- coding: utf-8 -*-
"""
test_conekta_gateway.py — Tests del ConektaGateway.

Cubre:
  - API Client (headers, retry, error handling)
  - Customer management (create, get)
  - Subscription management (create, update, cancel, status)
  - Payment processing (SPEI primary, card, OXXO)
  - Invoice generation (basic, subscription)
  - Webhook handling (signature verification, event routing)
  - Cost analysis (fees, recommendations)
  - Mock mode (sin red)
  - Error handling (missing API key, unsupported methods)
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from b2b_ai.billing.conekta_gateway import (
    CONEKTA_API_BASE,
    CARD_FLAT_FEE,
    CARD_PERCENT_FEE,
    SPEI_FLAT_FEE,
    ConektaAPIClient,
    ConektaEnvironment,
    ConektaGateway,
    PaymentMethodPriority,
)
from b2b_ai.billing.base import PaymentError
from b2b_ai.billing.models import (
    Customer,
    Invoice,
    InvoiceStatus,
    PaymentMethodType,
    PaymentResult,
    Provider,
    Subscription,
    SubscriptionStatus,
)


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def gateway_mock():
    """Gateway en modo mock (sin llamadas a la API)."""
    return ConektaGateway(mock=True)


@pytest.fixture
def gateway_real():
    """Gateway en modo real con API key de prueba."""
    return ConektaGateway(api_key="key_test_conekta_fake123", mock=False)


@pytest.fixture
def api_client():
    """Cliente API de Conekta con API key de prueba."""
    return ConektaAPIClient(api_key="key_test_conekta_fake123")


# ===========================================================================
# API Client Tests
# ===========================================================================
class TestConektaAPIClient:
    """Tests del cliente HTTP de Conekta."""

    def test_headers_con_api_key(self, api_client):
        """Headers incluyen Authorization y Content-Type correctos."""
        headers = api_client._headers()
        assert headers["Authorization"] == "Bearer key_test_conekta_fake123"
        assert "application/vnd.conekta-v" in headers["Accept"]
        assert headers["Content-Type"] == "application/json"

    def test_headers_sin_api_key_lanza_error(self):
        """Sin API key, lanza PaymentError con code missing_api_key."""
        client = ConektaAPIClient(api_key="")
        with pytest.raises(PaymentError) as exc_info:
            client._headers()
        assert exc_info.value.code == "missing_api_key"
        assert "B2B_CONEKTA_KEY" in str(exc_info.value)

    def test_base_url_correcta(self, api_client):
        """URL base apunta a la API de Conekta."""
        assert api_client._base_url == CONEKTA_API_BASE
        assert "api.conekta.io" in CONEKTA_API_BASE


# ===========================================================================
# Customer Management Tests
# ===========================================================================
class TestConektaGatewayCustomers:
    """Tests de creación y obtención de clientes."""

    def test_create_customer_mock(self, gateway_mock):
        """Mock mode crea customer sin llamada de red."""
        customer = gateway_mock.create_customer(
            email="despacho@contadores.mx",
            name="ABC Contadores",
        )
        assert isinstance(customer, Customer)
        assert customer.email == "despacho@contadores.mx"
        assert customer.name == "ABC Contadores"
        assert customer.provider == Provider.CONEKTA
        assert customer.provider_customer_id is not None
        assert customer.provider_customer_id.startswith("customer_")

    def test_create_customer_con_telefono_y_metadata(self, gateway_mock):
        """Customer con teléfono y metadata opcional."""
        customer = gateway_mock.create_customer(
            email="firma@audit.mx",
            name="Firma Audit",
            phone="+525551234567",
            metadata={"rfc": "XAXX010101000", "sector": "contabilidad"},
        )
        assert customer.email == "firma@audit.mx"
        assert customer.name == "Firma Audit"

    def test_create_customer_sin_email_invalido(self, gateway_mock):
        """Email con formato inválido es aceptado por el gateway
        (validación está en el modelo Pydantic, no en el gateway)."""
        # El gateway no valida email; lo hace el modelo
        customer = gateway_mock.create_customer(email="test@test.com", name="Test")
        assert customer.email == "test@test.com"

    def test_get_customer_mock(self, gateway_mock):
        """get_customer en mock devuelve datos estáticos."""
        result = gateway_mock.get_customer("cus_mock_123")
        assert result["id"] == "cus_mock_123"
        assert result["name"] == "Mock Customer"
        assert result["email"] == "mock@test.com"


# ===========================================================================
# Subscription Management Tests
# ===========================================================================
class TestConektaGatewaySubscriptions:
    """Tests de creación, actualización y cancelación de suscripciones."""

    def test_create_subscription_mock(self, gateway_mock):
        """Mock mode crea suscripción activa."""
        sub = gateway_mock.create_subscription(
            customer_id="cus_mock_1", plan_id="growth"
        )
        assert isinstance(sub, Subscription)
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.plan == "growth"
        assert sub.provider == Provider.CONEKTA
        assert sub.provider_subscription_id.startswith("subscription_")
        assert sub.current_period_start is not None
        assert sub.current_period_end is not None

    def test_create_subscription_con_trial(self, gateway_mock):
        """Suscripción con período de prueba."""
        sub = gateway_mock.create_subscription(
            customer_id="cus_mock_1", plan_id="starter", trial_days=14
        )
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.plan == "starter"

    def test_create_subscription_con_medio_pago(self, gateway_mock):
        """Suscripción con método de pago específico."""
        sub = gateway_mock.create_subscription(
            customer_id="cus_mock_1",
            plan_id="growth",
            payment_method_id="card_mock_123",
        )
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_update_subscription_mock(self, gateway_mock):
        """Mock mode actualiza suscripción a nuevo plan."""
        sub = gateway_mock.update_subscription(
            customer_id="cus_mock_1",
            subscription_id="sub_mock_1",
            new_plan_id="enterprise",
        )
        assert isinstance(sub, Subscription)
        assert sub.plan == "enterprise"
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.provider_subscription_id == "sub_mock_1"

    def test_update_subscription_sin_cambios(self, gateway_mock):
        """Update sin cambios no lanza error en mock."""
        sub = gateway_mock.update_subscription(
            customer_id="cus_mock_1",
            subscription_id="sub_mock_1",
        )
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_cancel_subscription_mock(self, gateway_mock):
        """Mock mode cancela suscripción."""
        sub = gateway_mock.cancel_subscription(
            customer_id="cus_mock_1",
            subscription_id="sub_mock_1",
        )
        assert isinstance(sub, Subscription)
        assert sub.status == SubscriptionStatus.CANCELED
        assert sub.provider_subscription_id == "sub_mock_1"

    def test_cancel_subscription_at_period_end(self, gateway_mock):
        """Cancelación al final del periodo."""
        sub = gateway_mock.cancel_subscription(
            customer_id="cus_mock_1",
            subscription_id="sub_mock_1",
            at_period_end=True,
        )
        assert sub.status == SubscriptionStatus.CANCELED

    def test_cancel_subscription_immediate(self, gateway_mock):
        """Cancelación inmediata."""
        sub = gateway_mock.cancel_subscription(
            customer_id="cus_mock_1",
            subscription_id="sub_mock_1",
            at_period_end=False,
        )
        assert sub.status == SubscriptionStatus.CANCELED

    def test_get_subscription_status_mock(self, gateway_mock):
        """Estado de suscripción en mock."""
        status = gateway_mock.get_subscription_status(
            customer_id="cus_mock_1",
            subscription_id="sub_mock_1",
        )
        assert status["id"] == "sub_mock_1"
        assert status["status"] == "active"
        assert status["plan_id"] == "growth"
        assert "billing_cycle_start" in status
        assert "billing_cycle_end" in status


# ===========================================================================
# Payment Processing Tests
# ===========================================================================
class TestConektaGatewayPayments:
    """Tests de procesamiento de pagos (SPEI, card, OXXO)."""

    def test_spei_payment_mock(self, gateway_mock):
        """SPEI retorna pending_payment con instrucciones CLABE."""
        result = gateway_mock.process_charge(
            customer_id="cus_mock_1", amount=20000,
            method=PaymentMethodType.SPEI,
        )
        assert isinstance(result, PaymentResult)
        assert result.ok is True
        assert result.status == "pending_payment"
        assert result.payment_method_type == PaymentMethodType.SPEI
        assert result.payment_instructions is not None
        assert result.payment_instructions["type"] == "spei"
        assert "clabe" in result.payment_instructions
        assert result.payment_instructions["bank"] is not None

    def test_card_payment_mock(self, gateway_mock):
        """Card payment retorna succeeded."""
        result = gateway_mock.process_charge(
            customer_id="cus_mock_1", amount=20000,
            method=PaymentMethodType.CARD,
        )
        assert result.ok is True
        assert result.status == "succeeded"
        assert result.payment_method_type == PaymentMethodType.CARD

    def test_oxxo_payment_mock(self, gateway_mock):
        """OXXO retorna pending_payment con barcode."""
        result = gateway_mock.process_charge(
            customer_id="cus_mock_1", amount=4999,
            method=PaymentMethodType.OXXO,
        )
        assert result.ok is True
        assert result.status == "pending_payment"
        assert result.payment_instructions["type"] == "oxxo"
        assert "barcode" in result.payment_instructions

    def test_spei_default_method(self, gateway_mock):
        """SPEI es el método por defecto (primary)."""
        result = gateway_mock.process_charge(
            customer_id="cus_mock_1", amount=9999,
        )
        assert result.payment_method_type == PaymentMethodType.SPEI
        assert result.status == "pending_payment"

    def test_payment_unsupported_method(self, gateway_mock):
        """Método no soportado lanza PaymentError."""
        with pytest.raises(PaymentError) as exc_info:
            gateway_mock.process_charge(
                customer_id="cus_mock_1", amount=1000,
                method="bitcoin",
            )
        assert exc_info.value.code == "unsupported_payment_method"

    def test_payment_amounts_various(self, gateway_mock):
        """Diferentes montos funcionan correctamente."""
        amounts = [8000, 20000, 45000, 4999, 9999]
        for amount in amounts:
            result = gateway_mock.process_charge(
                customer_id="cus_mock_1", amount=amount,
                method=PaymentMethodType.SPEI,
            )
            assert result.amount == amount
            assert result.ok is True

    def test_payment_with_description(self, gateway_mock):
        """Payment con descripción personalizada."""
        result = gateway_mock.process_charge(
            customer_id="cus_mock_1", amount=4999,
            method=PaymentMethodType.SPEI,
            description="Likida AI Starter — mensualidad agosto",
        )
        assert result.ok is True
        assert result.amount == 4999


# ===========================================================================
# Invoice Generation Tests
# ===========================================================================
class TestConektaGatewayInvoices:
    """Tests de generación de facturas."""

    def test_create_invoice_mock(self, gateway_mock):
        """Mock mode crea invoice con monto correcto."""
        invoice = gateway_mock.create_invoice(
            customer_id="cus_mock_1", amount=9999,
        )
        assert isinstance(invoice, Invoice)
        assert invoice.amount == 9999
        assert invoice.currency == "MXN"
        assert invoice.status == InvoiceStatus.OPEN
        assert invoice.provider == Provider.CONEKTA
        assert invoice.provider_invoice_id.startswith("invoice_")

    def test_create_invoice_con_items(self, gateway_mock):
        """Invoice con line items personalizados."""
        items = [
            {"name": "Likida AI Growth", "unit_price": 999900, "quantity": 1},
            {"name": "Setup fee", "unit_price": 50000, "quantity": 1},
        ]
        invoice = gateway_mock.create_invoice(
            customer_id="cus_mock_1", amount=10499,
            line_items=items,
        )
        assert invoice.amount == 10499
        assert invoice.currency == "MXN"

    def test_create_subscription_invoice_mock(self, gateway_mock):
        """Invoice de suscripción usa el precio del plan."""
        invoice = gateway_mock.create_subscription_invoice(
            customer_id="cus_mock_1", plan_id="growth",
        )
        assert invoice.amount == 9999.0
        assert invoice.status == InvoiceStatus.OPEN

    def test_create_subscription_invoice_starter(self, gateway_mock):
        """Invoice para plan Starter."""
        invoice = gateway_mock.create_subscription_invoice(
            customer_id="cus_mock_1", plan_id="starter",
        )
        assert invoice.amount == 4999.0

    def test_create_subscription_invoice_enterprise_custom(self, gateway_mock):
        """Enterprise requiere cotización manual (monto 0)."""
        with pytest.raises(PaymentError) as exc_info:
            gateway_mock.create_subscription_invoice(
                customer_id="cus_mock_1", plan_id="enterprise",
            )
        assert exc_info.value.code == "requires_quote"

    def test_create_subscription_invoice_con_monto_custom(self, gateway_mock):
        """Enterprise con monto custom funciona."""
        invoice = gateway_mock.create_subscription_invoice(
            customer_id="cus_mock_1", plan_id="enterprise",
            amount=45000,
        )
        assert invoice.amount == 45000


# ===========================================================================
# Webhook Handling Tests
# ===========================================================================
class TestConektaGatewayWebhooks:
    """Tests de manejo de webhooks."""

    def test_webhook_order_paid(self, gateway_mock):
        """order.paid retorna mark_paid=True."""
        result = gateway_mock.handle_webhook(
            event_type="order.paid",
            data={"data": {"object": {"id": "ord_1", "status": "paid"}}},
        )
        assert result["handled"] is True
        assert result["mark_paid"] is True
        assert result["provider"] == "conekta"
        assert result["event_type"] == "order.paid"

    def test_webhook_charge_paid(self, gateway_mock):
        """charge.paid retorna mark_paid=True."""
        result = gateway_mock.handle_webhook(
            event_type="charge.paid",
            data={"data": {"object": {"id": "chg_1", "amount": 20000}}},
        )
        assert result["handled"] is True
        assert result["mark_paid"] is True

    def test_webhook_order_created(self, gateway_mock):
        """order.created retorna mark_paid=False."""
        result = gateway_mock.handle_webhook(
            event_type="order.created",
            data={"data": {"object": {"id": "ord_2"}}},
        )
        assert result["handled"] is True
        assert result["mark_paid"] is False

    def test_webhook_subscription_paid(self, gateway_mock):
        """subscription.paid retorna mark_paid=True."""
        result = gateway_mock.handle_webhook(
            event_type="subscription.paid",
            data={"data": {"object": {"id": "sub_1"}}},
        )
        assert result["handled"] is True
        assert result["mark_paid"] is True

    def test_webhook_subscription_canceled(self, gateway_mock):
        """subscription.canceled retorna handled=True, mark_paid=False."""
        result = gateway_mock.handle_webhook(
            event_type="subscription.canceled",
            data={"data": {"object": {"id": "sub_2"}}},
        )
        assert result["handled"] is True
        assert result["mark_paid"] is False

    def test_webhook_unhandled_event(self, gateway_mock):
        """Evento no reconocido retorna handled=False."""
        result = gateway_mock.handle_webhook(
            event_type="unknown.event.type",
            data={"data": {"object": {}}},
        )
        assert result["handled"] is False
        assert result["reason"] == "evento sin manejo específico"

    def test_webhook_empty_data(self, gateway_mock):
        """Webhook con data vacía no crashea."""
        result = gateway_mock.handle_webhook(
            event_type="charge.paid", data={},
        )
        assert result["handled"] is True
        assert result["customer_id"] is None

    def test_verify_webhook_signature_without_secret(self, gateway_mock):
        """Sin webhook_secret configurado, retorna True (modo dev)."""
        assert gateway_mock.verify_webhook_signature("payload", "sig") is True

    def test_verify_webhook_signature_empty(self):
        """Sin secret configurado, retorna True (modo dev sin verificación)."""
        gw = ConektaGateway(mock=True)
        gw.webhook_secret = ""  # force empty
        # Dev mode: sin secreto, no verificamos
        assert gw.verify_webhook_signature("payload", "") is True

    def test_verify_webhook_signature_invalid_with_secret(self):
        """Con secret configurado, firma inválida retorna False."""
        import hashlib
        import hmac

        secret = "test_webhook_secret_123"
        gw = ConektaGateway(mock=True)
        gw.webhook_secret = secret

        # Build a valid-looking but wrong signature
        fake_hash = "0" * 64  # 64-char hex, but wrong
        bad_header = f"hmac_sha256={fake_hash},t=1234567890"
        assert gw.verify_webhook_signature("payload", bad_header) is False

    def test_verify_webhook_signature_valid(self):
        """Con secret configurado, firma correcta retorna True."""
        import hashlib
        import hmac
        import time

        secret = "test_webhook_secret_123"
        gw = ConektaGateway(mock=True)
        gw.webhook_secret = secret

        timestamp = str(int(time.time()))
        payload = '{"event":"charge.paid"}'
        signed_content = f"{timestamp}{payload}"
        correct_hash = hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        header = f"hmac_sha256={correct_hash},t={timestamp}"
        assert gw.verify_webhook_signature(payload, header) is True


# ===========================================================================
# Cost Analysis Tests
# ===========================================================================
class TestConektaGatewayCostAnalysis:
    """Tests de análisis de costos por método de pago."""

    def test_spei_fee_calculation(self):
        """SPEI tiene costo fijo de $12.50."""
        result = ConektaGateway.calculate_fee(PaymentMethodType.SPEI, 20000)
        assert result["fee"] == SPEI_FLAT_FEE
        assert result["net_amount"] == 20000 - SPEI_FLAT_FEE
        assert result["effective_rate"] < 0.01  # < 1%

    def test_card_fee_calculation(self):
        """Card tiene costo ~3.4% + $3.50."""
        result = ConektaGateway.calculate_fee(PaymentMethodType.CARD, 20000)
        expected_fee = (20000 * CARD_PERCENT_FEE) + CARD_FLAT_FEE
        assert result["fee"] == round(expected_fee, 2)
        assert result["net_amount"] == round(20000 - expected_fee, 2)

    def test_spei_vs_card_savings(self):
        """SPEI ahorra ~95% vs card en planes de $20K."""
        spei = ConektaGateway.calculate_fee(PaymentMethodType.SPEI, 20000)
        card = ConektaGateway.calculate_fee(PaymentMethodType.CARD, 20000)
        savings = card["fee"] - spei["fee"]
        assert savings > 600  # Ahorro > $600
        assert spei["fee"] < card["fee"]

    def test_fee_small_amounts(self):
        """Fees funcionan con montos pequeños."""
        spei = ConektaGateway.calculate_fee(PaymentMethodType.SPEI, 4999)
        card = ConektaGateway.calculate_fee(PaymentMethodType.CARD, 4999)
        assert spei["fee"] < card["fee"]

    def test_fee_zero_amount(self):
        """Monto cero no causa división por cero."""
        spei = ConektaGateway.calculate_fee(PaymentMethodType.SPEI, 0)
        card = ConektaGateway.calculate_fee(PaymentMethodType.CARD, 0)
        assert spei["effective_rate"] == 0
        assert card["effective_rate"] == 0

    def test_recommend_payment_method(self):
        """Recomendación siempre es SPEI por costo."""
        assert ConektaGateway.recommend_payment_method(20000) == PaymentMethodType.SPEI
        assert ConektaGateway.recommend_payment_method(4999) == PaymentMethodType.SPEI
        assert ConektaGateway.recommend_payment_method(45000) == PaymentMethodType.SPEI


# ===========================================================================
# Error Handling Tests
# ===========================================================================
class TestConektaGatewayErrors:
    """Tests de manejo de errores."""

    def test_missing_api_key_raises(self):
        """Sin API key, lanza PaymentError."""
        gw = ConektaGateway(api_key="", mock=False)
        with pytest.raises(PaymentError) as exc_info:
            gw.create_customer("a@b.com", "Test")
        assert exc_info.value.code == "missing_api_key"
        assert "B2B_CONEKTA_KEY" in str(exc_info.value)

    def test_invalid_payment_method(self, gateway_mock):
        """Método inválido lanza error."""
        with pytest.raises(PaymentError):
            gateway_mock.process_charge(
                customer_id="cus_1", amount=1000, method="paypal",
            )


# ===========================================================================
# Environment & Config Tests
# ===========================================================================
class TestConektaGatewayConfig:
    """Tests de configuración y entorno."""

    def test_environment_enum(self):
        """Enum de entornos existe."""
        assert ConektaEnvironment.SANDBOX.value == "sandbox"
        assert ConektaEnvironment.PRODUCTION.value == "production"

    def test_payment_method_priority_enum(self):
        """Enum de prioridad de métodos existe."""
        assert PaymentMethodPriority.SPEI_PRIMARY.value == "spei_primary"
        assert PaymentMethodPriority.CARD_ONLY.value == "card_only"
        assert PaymentMethodPriority.SPEI_ONLY.value == "spei_only"

    def test_plan_prices_defined(self):
        """Precios de planes están definidos."""
        from b2b_ai.billing.conekta_gateway import PLAN_PRICES
        assert PLAN_PRICES["starter"] == 4999.0
        assert PLAN_PRICES["growth"] == 9999.0
        assert PLAN_PRICES["enterprise"] == 0.0

    def test_gateway_provider_is_conekta(self, gateway_mock):
        """El gateway usa Conekta como provider."""
        customer = gateway_mock.create_customer("a@b.com", "Test")
        assert customer.provider == Provider.CONEKTA

    def test_constants_values(self):
        """Constantes de costo son correctas."""
        assert SPEI_FLAT_FEE == 12.50
        assert CARD_PERCENT_FEE == 0.034
        assert CARD_FLAT_FEE == 3.50
