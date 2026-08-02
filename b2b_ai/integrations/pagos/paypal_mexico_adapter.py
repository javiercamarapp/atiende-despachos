# -*- coding: utf-8 -*-
"""
paypal_mexico_adapter.py — Stub adapter for PayPal Mexico.

Provides PayPalMexicoAdapter with mock mode. Real implementation pending.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.pagos.adapter import PaymentAdapter, PaymentAdapterError
from b2b_ai.integrations.pagos.models import (
    Currency, Payment, PaymentConfig, PaymentMethod, PaymentRequest, PaymentStatus,
    Refund, RefundRequest, Transaction,
)

logger = logging.getLogger(__name__)


class PayPalMexicoAdapter(PaymentAdapter):
    """Stub adapter for PayPal Mexico. Falls back to mock mode."""

    def __init__(self, config: Optional[PaymentConfig] = None):
        config = config or PaymentConfig(
            provider="paypal_mexico",
            api_key=os.environ.get("PAYPAL_MX_CLIENT_ID", ""),
            currency=Currency.MXN,
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        return True

    def create_payment(self, request: PaymentRequest) -> Payment:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Payment(
            id=f"ppmx_{_uuid.uuid4().hex[:24]}", amount=request.amount,
            currency=request.currency, status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.PAYPAL, customer_id=request.customer_id,
            description=request.description, metadata=request.metadata,
            created_at=now, updated_at=now,
        )

    def verify_payment(self, payment_id: str) -> Payment:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Payment(
            id=payment_id, amount=1000.00, currency=Currency.MXN,
            status=PaymentStatus.SUCCEEDED, method=PaymentMethod.PAYPAL,
            description="Pago verificado", created_at=now, updated_at=now,
        )

    def refund(self, request: RefundRequest) -> Refund:
        self._ensure_connected()
        return Refund(
            id=f"ppmx_ref_{_uuid.uuid4().hex[:24]}", payment_id=request.payment_id,
            amount=request.amount or 1000.00, status="succeeded",
            reason=request.reason, created_at=datetime.now().isoformat(),
        )

    def get_transactions(self, date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[Transaction]:
        self._ensure_connected()
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return [
            Transaction(
                id=f"ppmx_txn_{_uuid.uuid4().hex[:16]}", type="payment",
                amount=5000.00, currency=Currency.MXN,
                status=PaymentStatus.SUCCEEDED,
                description="Pago PayPal Mexico", created_at=now,
            )
        ]
