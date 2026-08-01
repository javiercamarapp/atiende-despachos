# -*- coding: utf-8 -*-
"""
mercadopago_adapter.py — Adaptador mock para MercadoPago (LATAM).
Soporta tarjetas, efectivo (rapipago, pagofácil), transferencias.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.pagos.adapter import PaymentAdapter
from b2b_ai.integrations.pagos.models import (
    Currency, Payment, PaymentConfig, PaymentMethod, PaymentRequest, PaymentStatus,
    Refund, RefundRequest, Transaction,
)

logger = logging.getLogger(__name__)


class MercadoPagoAdapter(PaymentAdapter):
    """Adaptador mock para MercadoPago (pagos LATAM)."""

    def __init__(self, config: Optional[PaymentConfig] = None):
        config = config or PaymentConfig(provider="mercadopago", api_key="mock_mp_key")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("MercadoPagoAdapter: conexión exitosa (mock)")
        return True

    def create_payment(self, request: PaymentRequest) -> Payment:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Payment(
            id=f"mp_{_uuid.uuid4().hex[:16]}", amount=request.amount,
            currency=request.currency, status=PaymentStatus.SUCCEEDED,
            method=request.method, customer_id=request.customer_id,
            description=request.description, metadata=request.metadata,
            created_at=now, updated_at=now,
        )

    def verify_payment(self, payment_id: str) -> Payment:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Payment(id=payment_id, amount=8000.0, currency=Currency.MXN,
                       status=PaymentStatus.SUCCEEDED, created_at=now, updated_at=now)

    def refund(self, request: RefundRequest) -> Refund:
        self._ensure_connected()
        return Refund(id=f"ref_mp_{_uuid.uuid4().hex[:12]}", payment_id=request.payment_id,
                      amount=request.amount or 8000.0, status="succeeded",
                      reason=request.reason, created_at=datetime.now().isoformat())

    def get_transactions(self, date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[Transaction]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return [Transaction(id=f"chg_mp_{_uuid.uuid4().hex[:12]}", type="payment",
                           amount=4000.0 + i * 700, currency=Currency.MXN,
                           status=PaymentStatus.SUCCEEDED, description=f"Cargo MP {i}",
                           created_at=now) for i in range(1, 4)]
