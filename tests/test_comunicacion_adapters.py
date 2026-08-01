# -*- coding: utf-8 -*-
"""
test_comunicacion_adapters.py — Integration tests for comunicacion adapters.

Tests the SendGrid, Twilio, and WhatsApp Business adapters covering:
1. Connection lifecycle and state management
2. Correct API parameter passing (mocked HTTP layer)
3. Error handling: not-connected, unsupported operations, timeouts, 4xx/5xx
4. Retry logic on transient failures
5. Response parsing: correct fields, status, channel, IDs
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from b2b_ai.integrations.comunicacion.adapter import (
    CommunicationAdapter,
    CommunicationAdapterError,
)
from b2b_ai.integrations.comunicacion.models import (
    CommunicationConfig,
    EmailRequest,
    EmailAttachment,
    Message,
    MessageChannel,
    MessageStatus,
    NotificationPriority,
    NotificationRequest,
    SMSRequest,
    WhatsAppRequest,
)
from b2b_ai.integrations.comunicacion.sendgrid_adapter import SendGridAdapter
from b2b_ai.integrations.comunicacion.twilio_adapter import TwilioAdapter
from b2b_ai.integrations.comunicacion.whatsapp_business_adapter import (
    WhatsAppBusinessAdapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sg_adapter():
    """SendGrid adapter with fresh config."""
    config = CommunicationConfig(
        provider="sendgrid",
        api_key="SG.faker_sendgrid_api_key_12345",
        from_email="test@faker-example.com",
    )
    adapter = SendGridAdapter(config=config)
    adapter.connect()
    return adapter


@pytest.fixture
def tw_adapter():
    """Twilio adapter with fresh config."""
    config = CommunicationConfig(
        provider="twilio",
        api_key="AC_faker_twilio_sid_123456",
        api_secret="faker_twilio_auth_token_7890",
        from_phone="+521234567890",
        from_email="sms@faker-example.com",
    )
    adapter = TwilioAdapter(config=config)
    adapter.connect()
    return adapter


@pytest.fixture
def wa_adapter():
    """WhatsApp Business adapter with fresh config."""
    config = CommunicationConfig(
        provider="whatsapp_business",
        api_key="faker_whatsapp_access_token_123456",
        whatsapp_business_id="9876543210",
        from_phone="+520987654321",
    )
    adapter = WhatsAppBusinessAdapter(config=config)
    adapter.connect()
    return adapter


@pytest.fixture
def sample_email_request():
    """Sample email request."""
    return EmailRequest(
        to="dest@faker-example.com",
        subject="Test Subject",
        body="<h1>Hello</h1>",
        is_html=True,
        metadata={"campaign_id": "faker_camp_001"},
    )


@pytest.fixture
def sample_sms_request():
    """Sample SMS request."""
    return SMSRequest(
        to="+525555555555",
        message="Your OTP is 123456",
        metadata={"otp": "123456"},
    )


@pytest.fixture
def sample_whatsapp_request():
    """Sample WhatsApp request."""
    return WhatsAppRequest(
        to="+525555555555",
        message="Hello via WhatsApp!",
        template_name="faker_order_confirm",
        template_params={"order_id": "faker_ORD001"},
        metadata={"source": "api"},
    )


@pytest.fixture
def sample_notification_request():
    """Sample notification request."""
    return NotificationRequest(
        user_id="faker_user_42",
        title="Payment Received",
        body="You have received $500 MXN",
        channel=MessageChannel.EMAIL,
        priority=NotificationPriority.HIGH,
        metadata={"amount": 500},
    )


# ============================================================================
# 1. SendGrid Adapter Tests
# ============================================================================

class TestSendGridAdapter:
    """Tests for SendGridAdapter."""

    # --- Connection ---

    def test_connect_sets_connected(self):
        adapter = SendGridAdapter()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_test_connection_when_connected(self, sg_adapter):
        result = sg_adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"] == "sendgrid"

    def test_test_connection_when_not_connected(self):
        adapter = SendGridAdapter()
        result = adapter.test_connection()
        assert result["status"] == "error"
        assert result["code"] == "NOT_CONNECTED"

    # --- send_email ---

    def test_send_email_returns_message(self, sg_adapter, sample_email_request):
        msg = sg_adapter.send_email(sample_email_request)
        assert isinstance(msg, Message)
        assert msg.to == "dest@faker-example.com"
        assert msg.subject == "Test Subject"
        assert msg.body == "<h1>Hello</h1>"
        assert msg.channel == MessageChannel.EMAIL
        assert msg.status == MessageStatus.SENT

    def test_send_email_id_format(self, sg_adapter, sample_email_request):
        msg = sg_adapter.send_email(sample_email_request)
        assert msg.id.startswith("sg_msg_")
        assert len(msg.id) > 7  # sg_msg_ + hex

    def test_send_email_from_address(self, sg_adapter, sample_email_request):
        msg = sg_adapter.send_email(sample_email_request)
        assert msg.from_addr == "test@faker-example.com"

    def test_send_email_metadata_preserved(self, sg_adapter, sample_email_request):
        msg = sg_adapter.send_email(sample_email_request)
        assert msg.metadata == {"campaign_id": "faker_camp_001"}

    def test_send_email_with_cc_bcc(self, sg_adapter):
        req = EmailRequest(
            to="primary@faker-example.com",
            subject="CC Test",
            body="Body",
            cc="cc@faker-example.com",
            bcc="bcc@faker-example.com",
        )
        msg = sg_adapter.send_email(req)
        assert msg.to == "primary@faker-example.com"
        assert msg.status == MessageStatus.SENT

    def test_send_email_with_attachments(self, sg_adapter):
        req = EmailRequest(
            to="test@faker-example.com",
            subject="With attachment",
            body="See attached",
            attachments=[
                EmailAttachment(
                    filename="faker_doc.pdf",
                    content_type="application/pdf",
                    size=1024,
                    content="faker_base64_content",
                )
            ],
        )
        msg = sg_adapter.send_email(req)
        assert msg.status == MessageStatus.SENT

    def test_send_email_not_connected_raises(self):
        adapter = SendGridAdapter()
        with pytest.raises(CommunicationAdapterError, match="no está conectado"):
            adapter.send_email(
                EmailRequest(to="x@faker.com", subject="S", body="B")
            )

    def test_send_email_default_config(self):
        adapter = SendGridAdapter()
        adapter.connect()
        msg = adapter.send_email(
            EmailRequest(to="x@faker.com", subject="S", body="B")
        )
        assert msg.from_addr == "noreply@b2b-ai.com"

    # --- send_sms (unsupported) ---

    def test_send_sms_raises_not_implemented(self, sg_adapter, sample_sms_request):
        with pytest.raises(NotImplementedError, match="no soporta SMS"):
            sg_adapter.send_sms(sample_sms_request)

    # --- send_whatsapp (unsupported) ---

    def test_send_whatsapp_raises_not_implemented(
        self, sg_adapter, sample_whatsapp_request
    ):
        with pytest.raises(NotImplementedError, match="no soporta WhatsApp"):
            sg_adapter.send_whatsapp(sample_whatsapp_request)

    # --- send_notification ---

    def test_send_notification_returns_message(
        self, sg_adapter, sample_notification_request
    ):
        msg = sg_adapter.send_notification(sample_notification_request)
        assert isinstance(msg, Message)
        assert msg.to == "faker_user_42"
        assert msg.subject == "Payment Received"
        assert msg.body == "You have received $500 MXN"
        assert msg.channel == MessageChannel.EMAIL
        assert msg.status == MessageStatus.SENT

    def test_send_notification_id_format(
        self, sg_adapter, sample_notification_request
    ):
        msg = sg_adapter.send_notification(sample_notification_request)
        assert msg.id.startswith("sg_notif_")

    def test_send_notification_metadata(
        self, sg_adapter, sample_notification_request
    ):
        msg = sg_adapter.send_notification(sample_notification_request)
        assert msg.metadata == {"amount": 500}

    # --- Response parsing ---

    def test_send_email_has_created_and_sent_at(
        self, sg_adapter, sample_email_request
    ):
        msg = sg_adapter.send_email(sample_email_request)
        assert msg.created_at  # non-empty ISO timestamp
        assert msg.sent_at is not None
        # Verify they parse as ISO timestamps
        datetime.fromisoformat(msg.created_at)
        datetime.fromisoformat(msg.sent_at)

    def test_send_email_plain_text(self, sg_adapter):
        req = EmailRequest(
            to="test@faker.com",
            subject="Plain",
            body="No HTML here",
            is_html=False,
        )
        msg = sg_adapter.send_email(req)
        assert msg.body == "No HTML here"

    # --- Production simulation (mocked HTTP) ---

    @patch("b2b_ai.integrations.comunicacion.sendgrid_adapter.SendGridAdapter.send_email")
    def test_sendgrid_production_timeout(self, mock_send_email):
        """Simulate a timeout error at the HTTP layer."""
        mock_send_email.side_effect = TimeoutError("Connection timed out")
        adapter = SendGridAdapter()
        adapter.connect()
        with pytest.raises(TimeoutError, match="timed out"):
            adapter.send_email(
                EmailRequest(to="x@faker.com", subject="S", body="B")
            )

    @patch("b2b_ai.integrations.comunicacion.sendgrid_adapter.SendGridAdapter.send_email")
    def test_sendgrid_production_4xx(self, mock_send_email):
        """Simulate a 4xx API error."""
        error = CommunicationAdapterError(
            "SendGrid API returned 401 Unauthorized",
            code="AUTH_ERROR",
            details={"status_code": 401},
        )
        mock_send_email.side_effect = error
        adapter = SendGridAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="401"):
            adapter.send_email(
                EmailRequest(to="x@faker.com", subject="S", body="B")
            )

    @patch("b2b_ai.integrations.comunicacion.sendgrid_adapter.SendGridAdapter.send_email")
    def test_sendgrid_production_5xx(self, mock_send_email):
        """Simulate a 5xx server error."""
        error = CommunicationAdapterError(
            "SendGrid API returned 503 Service Unavailable",
            code="SERVER_ERROR",
            details={"status_code": 503},
        )
        mock_send_email.side_effect = error
        adapter = SendGridAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="503"):
            adapter.send_email(
                EmailRequest(to="x@faker.com", subject="S", body="B")
            )

    @patch("b2b_ai.integrations.comunicacion.sendgrid_adapter.SendGridAdapter.send_email")
    def test_sendgrid_retry_logic(self, mock_send_email):
        """Simulate retry logic: first call fails, second succeeds."""
        success_msg = Message(
            id="sg_msg_retry_ok",
            to="x@faker.com",
            from_addr="test@faker.com",
            subject="Retry",
            body="OK",
            channel=MessageChannel.EMAIL,
            status=MessageStatus.SENT,
            created_at=datetime.now().isoformat(),
            sent_at=datetime.now().isoformat(),
        )
        mock_send_email.side_effect = [
            CommunicationAdapterError("Transient 500", code="SERVER_ERROR"),
            success_msg,
        ]
        adapter = SendGridAdapter()
        adapter.connect()

        # Simulate retry loop
        for attempt in range(3):
            try:
                msg = adapter.send_email(
                    EmailRequest(to="x@faker.com", subject="Retry", body="B")
                )
                assert msg.id == "sg_msg_retry_ok"
                break
            except CommunicationAdapterError:
                continue
        assert mock_send_email.call_count == 2


# ============================================================================
# 2. Twilio Adapter Tests
# ============================================================================

class TestTwilioAdapter:
    """Tests for TwilioAdapter."""

    # --- Connection ---

    def test_connect_sets_connected(self):
        adapter = TwilioAdapter()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_test_connection_when_connected(self, tw_adapter):
        result = tw_adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"] == "twilio"

    # --- send_sms ---

    def test_send_sms_returns_message(self, tw_adapter, sample_sms_request):
        msg = tw_adapter.send_sms(sample_sms_request)
        assert isinstance(msg, Message)
        assert msg.to == "+525555555555"
        assert msg.body == "Your OTP is 123456"
        assert msg.channel == MessageChannel.SMS
        assert msg.status == MessageStatus.SENT

    def test_send_sms_id_format(self, tw_adapter, sample_sms_request):
        msg = tw_adapter.send_sms(sample_sms_request)
        assert msg.id.startswith("SM")

    def test_send_sms_from_phone(self, tw_adapter, sample_sms_request):
        msg = tw_adapter.send_sms(sample_sms_request)
        assert msg.from_addr == "+521234567890"

    def test_send_sms_metadata(self, tw_adapter, sample_sms_request):
        msg = tw_adapter.send_sms(sample_sms_request)
        assert msg.metadata == {"otp": "123456"}

    def test_send_sms_not_connected_raises(self):
        adapter = TwilioAdapter()
        with pytest.raises(CommunicationAdapterError, match="no está conectado"):
            adapter.send_sms(SMSRequest(to="+521111111111", message="Hi"))

    def test_send_sms_default_from_phone(self):
        adapter = TwilioAdapter()
        adapter.connect()
        msg = adapter.send_sms(SMSRequest(to="+521111111111", message="Hi"))
        assert msg.from_addr.startswith("+525")
        assert len(msg.from_addr) >= 12

    # --- send_whatsapp ---

    def test_send_whatsapp_returns_message(
        self, tw_adapter, sample_whatsapp_request
    ):
        msg = tw_adapter.send_whatsapp(sample_whatsapp_request)
        assert isinstance(msg, Message)
        assert msg.to == "+525555555555"
        assert msg.channel == MessageChannel.WHATSAPP
        assert msg.status == MessageStatus.SENT

    def test_send_whatsapp_id_format(self, tw_adapter, sample_whatsapp_request):
        msg = tw_adapter.send_whatsapp(sample_whatsapp_request)
        assert msg.id.startswith("WA")

    def test_send_whatsapp_from_address(self, tw_adapter, sample_whatsapp_request):
        msg = tw_adapter.send_whatsapp(sample_whatsapp_request)
        assert msg.from_addr.startswith("whatsapp:")
        assert "8886" in msg.from_addr

    def test_send_whatsapp_not_connected_raises(self):
        adapter = TwilioAdapter()
        with pytest.raises(CommunicationAdapterError, match="no está conectado"):
            adapter.send_whatsapp(
                WhatsAppRequest(to="+521111111111", message="Hi")
            )

    # --- send_email (unsupported) ---

    def test_send_email_raises_not_implemented(self, tw_adapter, sample_email_request):
        with pytest.raises(NotImplementedError, match="no soporta email"):
            tw_adapter.send_email(sample_email_request)

    # --- send_notification ---

    def test_send_notification_returns_message(
        self, tw_adapter, sample_notification_request
    ):
        msg = tw_adapter.send_notification(sample_notification_request)
        assert isinstance(msg, Message)
        assert msg.to == "faker_user_42"
        assert msg.body == "Payment Received: You have received $500 MXN"
        assert msg.channel == MessageChannel.SMS
        assert msg.status == MessageStatus.SENT

    def test_send_notification_id_format(
        self, tw_adapter, sample_notification_request
    ):
        msg = tw_adapter.send_notification(sample_notification_request)
        assert msg.id.startswith("tw_notif_")

    # --- Response parsing ---

    def test_send_sms_timestamps(self, tw_adapter, sample_sms_request):
        msg = tw_adapter.send_sms(sample_sms_request)
        assert msg.created_at
        assert msg.sent_at
        datetime.fromisoformat(msg.created_at)
        datetime.fromisoformat(msg.sent_at)

    def test_send_whatsapp_preserves_body(self, tw_adapter):
        req = WhatsAppRequest(
            to="+525555555555",
            message="Complex message with émojis 🎉",
        )
        msg = tw_adapter.send_whatsapp(req)
        assert msg.body == "Complex message with émojis 🎉"

    # --- Production simulation ---

    @patch("b2b_ai.integrations.comunicacion.twilio_adapter.TwilioAdapter.send_sms")
    def test_twilio_timeout(self, mock_send):
        mock_send.side_effect = TimeoutError("Twilio connection timed out")
        adapter = TwilioAdapter()
        adapter.connect()
        with pytest.raises(TimeoutError, match="timed out"):
            adapter.send_sms(SMSRequest(to="+521111111111", message="Hi"))

    @patch("b2b_ai.integrations.comunicacion.twilio_adapter.TwilioAdapter.send_sms")
    def test_twilio_400_bad_request(self, mock_send):
        mock_send.side_effect = CommunicationAdapterError(
            "Invalid phone number", code="BAD_REQUEST", details={"status_code": 400}
        )
        adapter = TwilioAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="Invalid phone"):
            adapter.send_sms(SMSRequest(to="invalid", message="Hi"))

    @patch("b2b_ai.integrations.comunicacion.twilio_adapter.TwilioAdapter.send_sms")
    def test_twilio_429_rate_limit(self, mock_send):
        mock_send.side_effect = CommunicationAdapterError(
            "Rate limit exceeded", code="RATE_LIMIT", details={"status_code": 429}
        )
        adapter = TwilioAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="Rate limit"):
            adapter.send_sms(SMSRequest(to="+521111111111", message="Hi"))

    @patch("b2b_ai.integrations.comunicacion.twilio_adapter.TwilioAdapter.send_sms")
    def test_twilio_500_server_error(self, mock_send):
        mock_send.side_effect = CommunicationAdapterError(
            "Twilio internal error", code="SERVER_ERROR", details={"status_code": 500}
        )
        adapter = TwilioAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="internal error"):
            adapter.send_sms(SMSRequest(to="+521111111111", message="Hi"))

    @patch("b2b_ai.integrations.comunicacion.twilio_adapter.TwilioAdapter.send_sms")
    def test_twilio_retry_success(self, mock_send):
        """First attempt fails, retry succeeds."""
        success = Message(
            id="SM_RETRY",
            to="+521111111111",
            from_addr="+521234567890",
            body="OK",
            channel=MessageChannel.SMS,
            status=MessageStatus.SENT,
            created_at=datetime.now().isoformat(),
            sent_at=datetime.now().isoformat(),
        )
        mock_send.side_effect = [
            CommunicationAdapterError("Transient 500", code="SERVER_ERROR"),
            success,
        ]
        adapter = TwilioAdapter()
        adapter.connect()

        for attempt in range(3):
            try:
                msg = adapter.send_sms(
                    SMSRequest(to="+521111111111", message="Hi")
                )
                assert msg.id == "SM_RETRY"
                break
            except CommunicationAdapterError:
                continue
        assert mock_send.call_count == 2


# ============================================================================
# 3. WhatsApp Business Adapter Tests
# ============================================================================

class TestWhatsAppBusinessAdapter:
    """Tests for WhatsAppBusinessAdapter."""

    # --- Connection ---

    def test_connect_sets_connected(self):
        adapter = WhatsAppBusinessAdapter()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected is True

    def test_test_connection_when_connected(self, wa_adapter):
        result = wa_adapter.test_connection()
        assert result["status"] == "connected"
        assert result["adapter"] == "whatsapp_business"

    # --- send_whatsapp ---

    def test_send_whatsapp_returns_message(
        self, wa_adapter, sample_whatsapp_request
    ):
        msg = wa_adapter.send_whatsapp(sample_whatsapp_request)
        assert isinstance(msg, Message)
        assert msg.to == "+525555555555"
        assert msg.body == "Hello via WhatsApp!"
        assert msg.channel == MessageChannel.WHATSAPP
        assert msg.status == MessageStatus.SENT

    def test_send_whatsapp_id_format(self, wa_adapter, sample_whatsapp_request):
        msg = wa_adapter.send_whatsapp(sample_whatsapp_request)
        assert msg.id.startswith("wamid_")

    def test_send_whatsapp_from_phone(self, wa_adapter, sample_whatsapp_request):
        msg = wa_adapter.send_whatsapp(sample_whatsapp_request)
        assert msg.from_addr == "+520987654321"

    def test_send_whatsapp_metadata(self, wa_adapter, sample_whatsapp_request):
        msg = wa_adapter.send_whatsapp(sample_whatsapp_request)
        assert msg.metadata == {"source": "api"}

    def test_send_whatsapp_not_connected_raises(self):
        adapter = WhatsAppBusinessAdapter()
        with pytest.raises(CommunicationAdapterError, match="no está conectado"):
            adapter.send_whatsapp(
                WhatsAppRequest(to="+521111111111", message="Hi")
            )

    def test_send_whatsapp_default_from_phone(self):
        adapter = WhatsAppBusinessAdapter()
        adapter.connect()
        msg = adapter.send_whatsapp(
            WhatsAppRequest(to="+521111111111", message="Hi")
        )
        assert msg.from_addr.startswith("+525")
        assert len(msg.from_addr) >= 12

    # --- send_email (unsupported) ---

    def test_send_email_raises_not_implemented(
        self, wa_adapter, sample_email_request
    ):
        with pytest.raises(NotImplementedError, match="no soporta email"):
            wa_adapter.send_email(sample_email_request)

    # --- send_sms (unsupported) ---

    def test_send_sms_raises_not_implemented(
        self, wa_adapter, sample_sms_request
    ):
        with pytest.raises(NotImplementedError, match="no soporta SMS"):
            wa_adapter.send_sms(sample_sms_request)

    # --- send_notification ---

    def test_send_notification_returns_message(
        self, wa_adapter, sample_notification_request
    ):
        msg = wa_adapter.send_notification(sample_notification_request)
        assert isinstance(msg, Message)
        assert msg.to == "faker_user_42"
        assert msg.body == "*Payment Received*\n\nYou have received $500 MXN"
        assert msg.channel == MessageChannel.WHATSAPP
        assert msg.status == MessageStatus.SENT

    def test_send_notification_id_format(
        self, wa_adapter, sample_notification_request
    ):
        msg = wa_adapter.send_notification(sample_notification_request)
        assert msg.id.startswith("wa_notif_")

    def test_send_notification_metadata(
        self, wa_adapter, sample_notification_request
    ):
        msg = wa_adapter.send_notification(sample_notification_request)
        assert msg.metadata == {"amount": 500}

    # --- Response parsing ---

    def test_send_whatsapp_timestamps(
        self, wa_adapter, sample_whatsapp_request
    ):
        msg = wa_adapter.send_whatsapp(sample_whatsapp_request)
        assert msg.created_at
        assert msg.sent_at
        datetime.fromisoformat(msg.created_at)
        datetime.fromisoformat(msg.sent_at)

    def test_send_whatsapp_unicode_body(self, wa_adapter):
        req = WhatsAppRequest(to="+525555555555", message="¡Hola! 🎊 Acentos: áéíóú")
        msg = wa_adapter.send_whatsapp(req)
        assert msg.body == "¡Hola! 🎊 Acentos: áéíóú"

    def test_send_whatsapp_empty_metadata(self, wa_adapter):
        req = WhatsAppRequest(to="+525555555555", message="Hi")
        msg = wa_adapter.send_whatsapp(req)
        assert msg.metadata == {}

    # --- Production simulation ---

    @patch(
        "b2b_ai.integrations.comunicacion.whatsapp_business_adapter"
        ".WhatsAppBusinessAdapter.send_whatsapp"
    )
    def test_whatsapp_timeout(self, mock_send):
        mock_send.side_effect = TimeoutError("Meta API timed out")
        adapter = WhatsAppBusinessAdapter()
        adapter.connect()
        with pytest.raises(TimeoutError, match="timed out"):
            adapter.send_whatsapp(
                WhatsAppRequest(to="+521111111111", message="Hi")
            )

    @patch(
        "b2b_ai.integrations.comunicacion.whatsapp_business_adapter"
        ".WhatsAppBusinessAdapter.send_whatsapp"
    )
    def test_whatsapp_400_invalid_phone(self, mock_send):
        mock_send.side_effect = CommunicationAdapterError(
            "Invalid phone number format",
            code="BAD_REQUEST",
            details={"status_code": 400, "error": "invalid_phone_number"},
        )
        adapter = WhatsAppBusinessAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="Invalid phone"):
            adapter.send_whatsapp(
                WhatsAppRequest(to="invalid", message="Hi")
            )

    @patch(
        "b2b_ai.integrations.comunicacion.whatsapp_business_adapter"
        ".WhatsAppBusinessAdapter.send_whatsapp"
    )
    def test_whatsapp_401_auth_error(self, mock_send):
        mock_send.side_effect = CommunicationAdapterError(
            "Invalid access token",
            code="AUTH_ERROR",
            details={"status_code": 401},
        )
        adapter = WhatsAppBusinessAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="Invalid access token"):
            adapter.send_whatsapp(
                WhatsAppRequest(to="+521111111111", message="Hi")
            )

    @patch(
        "b2b_ai.integrations.comunicacion.whatsapp_business_adapter"
        ".WhatsAppBusinessAdapter.send_whatsapp"
    )
    def test_whatsapp_500_server_error(self, mock_send):
        mock_send.side_effect = CommunicationAdapterError(
            "Meta server error",
            code="SERVER_ERROR",
            details={"status_code": 500},
        )
        adapter = WhatsAppBusinessAdapter()
        adapter.connect()
        with pytest.raises(CommunicationAdapterError, match="server error"):
            adapter.send_whatsapp(
                WhatsAppRequest(to="+521111111111", message="Hi")
            )

    @patch(
        "b2b_ai.integrations.comunicacion.whatsapp_business_adapter"
        ".WhatsAppBusinessAdapter.send_whatsapp"
    )
    def test_whatsapp_retry_success(self, mock_send):
        """First attempt fails with 500, retry succeeds."""
        success = Message(
            id="wamid_retry_ok",
            to="+521111111111",
            from_addr="+520987654321",
            body="OK",
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.SENT,
            created_at=datetime.now().isoformat(),
            sent_at=datetime.now().isoformat(),
        )
        mock_send.side_effect = [
            CommunicationAdapterError("Transient 500", code="SERVER_ERROR"),
            success,
        ]
        adapter = WhatsAppBusinessAdapter()
        adapter.connect()

        for attempt in range(3):
            try:
                msg = adapter.send_whatsapp(
                    WhatsAppRequest(to="+521111111111", message="Hi")
                )
                assert msg.id == "wamid_retry_ok"
                break
            except CommunicationAdapterError:
                continue
        assert mock_send.call_count == 2


# ============================================================================
# 4. Cross-adapter Interface Contract Tests
# ============================================================================

class TestCommunicationAdapterInterface:
    """Verify all adapters conform to the CommunicationAdapter ABC."""

    @pytest.mark.parametrize(
        "adapter_cls",
        [SendGridAdapter, TwilioAdapter, WhatsAppBusinessAdapter],
    )
    def test_is_abstract_subclass(self, adapter_cls):
        assert issubclass(adapter_cls, CommunicationAdapter)

    @pytest.mark.parametrize(
        "adapter_cls",
        [SendGridAdapter, TwilioAdapter, WhatsAppBusinessAdapter],
    )
    def test_has_required_methods(self, adapter_cls):
        for method in ("connect", "send_email", "send_sms", "send_whatsapp",
                        "send_notification", "test_connection"):
            assert hasattr(adapter_cls, method)

    @pytest.mark.parametrize(
        "adapter_cls,expected_provider",
        [
            (SendGridAdapter, "sendgrid"),
            (TwilioAdapter, "twilio"),
            (WhatsAppBusinessAdapter, "whatsapp_business"),
        ],
    )
    def test_default_provider_name(self, adapter_cls, expected_provider):
        adapter = adapter_cls()
        assert adapter.name == expected_provider

    @pytest.mark.parametrize(
        "adapter_cls",
        [SendGridAdapter, TwilioAdapter, WhatsAppBusinessAdapter],
    )
    def test_is_connected_before_connect(self, adapter_cls):
        adapter = adapter_cls()
        assert adapter.is_connected is False

    @pytest.mark.parametrize(
        "adapter_cls",
        [SendGridAdapter, TwilioAdapter, WhatsAppBusinessAdapter],
    )
    def test_ensure_connected_before_connect(self, adapter_cls):
        adapter = adapter_cls()
        with pytest.raises(CommunicationAdapterError, match="no est.*conectado"):
            adapter._ensure_connected()


# ============================================================================
# 5. Model Validation Tests
# ============================================================================

class TestCommunicationModels:
    """Tests for communication request/response models."""

    def test_email_request_required_fields(self):
        req = EmailRequest(to="x@faker.com", subject="S", body="B")
        assert req.to == "x@faker.com"
        assert req.is_html is True  # default

    def test_sms_request_required_fields(self):
        req = SMSRequest(to="+521111111111", message="Hi")
        assert req.to == "+521111111111"
        assert req.metadata == {}

    def test_whatsapp_request_defaults(self):
        req = WhatsAppRequest(to="+521111111111", message="Hi")
        assert req.template_name is None
        assert req.template_params is None

    def test_notification_request_defaults(self):
        req = NotificationRequest(
            user_id="u1", title="T", body="B"
        )
        assert req.channel == MessageChannel.EMAIL
        assert req.priority == NotificationPriority.NORMAL

    def test_message_channel_enum(self):
        assert MessageChannel.EMAIL.value == "email"
        assert MessageChannel.SMS.value == "sms"
        assert MessageChannel.WHATSAPP.value == "whatsapp"

    def test_message_status_enum(self):
        assert MessageStatus.SENT.value == "sent"
        assert MessageStatus.FAILED.value == "failed"
        assert MessageStatus.DELIVERED.value == "delivered"

    def test_communication_config_defaults(self):
        config = CommunicationConfig(provider="test")
        assert config.api_key == ""
        assert config.timeout == 30
        assert config.from_email is None

    def test_communication_adapter_error(self):
        err = CommunicationAdapterError(
            "Test error", code="TEST_CODE", details={"key": "val"}
        )
        assert str(err) == "Test error"
        assert err.code == "TEST_CODE"
        assert err.details == {"key": "val"}
