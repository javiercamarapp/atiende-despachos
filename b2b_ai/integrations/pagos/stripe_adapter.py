# -*- coding: utf-8 -*-
"""
stripe_adapter.py — Adaptador mock para Stripe Mexico.

Implementa la interfaz PaymentAdapter con respuestas simuladas.
En producción, se conectaría a la Stripe API (https://stripe.com/docs/api).
"""
from __future__ import annotations

import os
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


class StripeAdapter(PaymentAdapter):
    """Adaptador mock para Stripe Mexico.

    En producción, se conectaría a la Stripe API REST
    (https://stripe.com/docs/api). Usa secret_key para autenticación.
    Soporta tarjetas, SPEI y transferencias bancarias.
    """

    def __init__(self, config: Optional[PaymentConfig] = None):
        config = config or PaymentConfig(
            provider="stripe",
            api_key=os.environ.get("STRIPE_SECRET_KEY", ""),
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Stripe.

        En producción:
        1. Validar API key con GET /v1/balance
        2. Verificar cuenta activa
        """
        logger.info("StripeAdapter: conectando a Stripe (mock)...")
        self._connected = True
        logger.info("StripeAdapter: conexión exitosa (mock)")
        return True

    def create_payment(self, request: PaymentRequest) -> Payment:
        """Crea un pago mock en Stripe.

        En producción: POST /v1/payment_intents
        """
        self._ensure_connected()
        logger.info(f"StripeAdapter: creando pago de {request.amount} {request.currency.value}")

        now = datetime.now().isoformat()
        return Payment(
            id=f"pi_{_uuid.uuid4().hex[:24]}",
            amount=request.amount,
            currency=request.currency,
            status=PaymentStatus.SUCCEEDED,
            method=request.method,
            customer_id=request.customer_id,
            description=request.description,
            metadata=request.metadata,
            created_at=now,
            updated_at=now,
        )

    def verify_payment(self, payment_id: str) -> Payment:
        """Verifica el estado de un pago mock.

        En producción: GET /v1/payment_intents/{id}
        """
        self._ensure_connected()
        logger.info(f"StripeAdapter: verificando pago {payment_id}")

        now = datetime.now().isoformat()
        return Payment(
            id=payment_id,
            amount=5000.00,
            currency=Currency.MXN,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.CARD,
            description="Pago verificado",
            created_at=now,
            updated_at=now,
        )

    def refund(self, request: RefundRequest) -> Refund:
        """Realiza un reembolso mock en Stripe.

        En producción: POST /v1/refunds
        """
        self._ensure_connected()
        logger.info(f"StripeAdapter: reembolsando pago {request.payment_id}")

        return Refund(
            id=f"re_{_uuid.uuid4().hex[:24]}",
            payment_id=request.payment_id,
            amount=request.amount or 5000.00,
            status="succeeded",
            reason=request.reason,
            created_at=datetime.now().isoformat(),
        )

    def get_transactions(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Transaction]:
        """Obtiene transacciones mock de Stripe.

        En producción: GET /v1/balance_transactions
        """
        self._ensure_connected()
        logger.info("StripeAdapter: obteniendo transacciones (mock)")

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return [
            Transaction(
                id=f"txn_{_uuid.uuid4().hex[:16]}",
                type="payment",
                amount=15000.00 + i * 2500,
                currency=Currency.MXN,
                status=PaymentStatus.SUCCEEDED,
                description=f"Pago cliente {i}",
                created_at=now,
            )
            for i in range(1, 4)
        ]
