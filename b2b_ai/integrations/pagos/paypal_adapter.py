# -*- coding: utf-8 -*-
"""
paypal_adapter.py — Adaptador mock para PayPal Mexico.

Implementa la interfaz PaymentAdapter con respuestas simuladas.
En producción, se conectaría a la PayPal API (https://developer.paypal.com/docs/api/overview/).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.pagos.adapter import PaymentAdapter, PaymentAdapterError
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

logger = logging.getLogger(__name__)


class PayPalAdapter(PaymentAdapter):
    """Adaptador mock para PayPal Mexico.

    En producción, se conectaría a la PayPal REST API v2
    (https://developer.paypal.com/docs/api/payments/v2/).
    Usa client_id + client_secret con OAuth 2.0.
    """

    def __init__(self, config: Optional[PaymentConfig] = None):
        config = config or PaymentConfig(
            provider="paypal",
            api_key="faker_paypal_client_id_DO_NOT_USE",
            api_secret="faker_paypal_secret_DO_NOT_USE",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a PayPal.

        En producción:
        1. Obtener OAuth 2.0 token con client_id/client_secret
        2. Usar token para todas las llamadas
        """
        logger.info("PayPalAdapter: conectando a PayPal (mock)...")
        self._connected = True
        logger.info("PayPalAdapter: conexión exitosa (mock)")
        return True

    def create_payment(self, request: PaymentRequest) -> Payment:
        """Crea un pago mock en PayPal.

        En producción: POST /v2/checkout/orders
        """
        self._ensure_connected()
        logger.info(f"PayPalAdapter: creando pago de {request.amount} {request.currency.value}")

        now = datetime.now().isoformat()
        return Payment(
            id=f"PAYID-{_uuid.uuid4().hex[:20].upper()}",
            amount=request.amount,
            currency=request.currency,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.PAYPAL,
            customer_id=request.customer_id,
            description=request.description,
            metadata=request.metadata,
            created_at=now,
            updated_at=now,
        )

    def verify_payment(self, payment_id: str) -> Payment:
        """Verifica el estado de un pago mock.

        En producción: GET /v2/checkout/orders/{id}
        """
        self._ensure_connected()
        logger.info(f"PayPalAdapter: verificando pago {payment_id}")

        now = datetime.now().isoformat()
        return Payment(
            id=payment_id,
            amount=750.00,
            currency=Currency.USD,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.PAYPAL,
            description="PayPal payment verified",
            created_at=now,
            updated_at=now,
        )

    def refund(self, request: RefundRequest) -> Refund:
        """Realiza un reembolso mock en PayPal.

        En producción: POST /v2/payments/captures/{id}/refund
        """
        self._ensure_connected()
        logger.info(f"PayPalAdapter: reembolsando pago {request.payment_id}")

        return Refund(
            id=f"REFUND-{_uuid.uuid4().hex[:16].upper()}",
            payment_id=request.payment_id,
            amount=request.amount or 750.00,
            status="succeeded",
            reason=request.reason,
            created_at=datetime.now().isoformat(),
        )

    def get_transactions(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Transaction]:
        """Obtiene transacciones mock de PayPal.

        En producción: GET /v1/reporting/transactions
        """
        self._ensure_connected()
        logger.info("PayPalAdapter: obteniendo transacciones (mock)")

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return [
            Transaction(
                id=f"TXN-{_uuid.uuid4().hex[:16].upper()}",
                type="payment",
                amount=250.00 + i * 100,
                currency=Currency.USD,
                status=PaymentStatus.SUCCEEDED,
                description=f"PayPal transaction {i}",
                created_at=now,
            )
            for i in range(1, 4)
        ]
