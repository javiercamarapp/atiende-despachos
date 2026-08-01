# -*- coding: utf-8 -*-
"""
conekta_adapter.py — Adaptador mock para Conekta Mexico.

Implementa la interfaz PaymentAdapter con respuestas simuladas.
En producción, se conectaría a la Conekta API (https://developers.conekta.com/).
Soporta tarjetas, OXXO y SPEI.
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


class ConektaAdapter(PaymentAdapter):
    """Adaptador mock para Conekta Mexico.

    En producción, se conectaría a la Conekta API REST v2
    (https://developers.conekta.com/reference). Usa privado_key para auth.
    Soporta tarjetas, OXXO (dispersiones) y SPEI.
    """

    def __init__(self, config: Optional[PaymentConfig] = None):
        config = config or PaymentConfig(
            provider="conekta",
            api_key="key_faker_conekta_DO_NOT_USE",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Conekta.

        En producción:
        1. Validar API key con GET /company
        2. Verificar empresa activa
        """
        logger.info("ConektaAdapter: conectando a Conekta (mock)...")
        self._connected = True
        logger.info("ConektaAdapter: conexión exitosa (mock)")
        return True

    def create_payment(self, request: PaymentRequest) -> Payment:
        """Crea un pago mock en Conekta.

        En producción: POST /orders
        """
        self._ensure_connected()
        logger.info(f"ConektaAdapter: creando pago de {request.amount} {request.currency.value}")

        now = datetime.now().isoformat()
        return Payment(
            id=f"ord_{_uuid.uuid4().hex[:20]}",
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

        En producción: GET /orders/{id}
        """
        self._ensure_connected()
        logger.info(f"ConektaAdapter: verificando pago {payment_id}")

        now = datetime.now().isoformat()
        return Payment(
            id=payment_id,
            amount=3200.00,
            currency=Currency.MXN,
            status=PaymentStatus.SUCCEEDED,
            method=PaymentMethod.OXXO,
            description="Pago OXXO verificado",
            created_at=now,
            updated_at=now,
        )

    def refund(self, request: RefundRequest) -> Refund:
        """Realiza un reembolso mock en Conekta.

        En producción: POST /orders/{id}/refund
        """
        self._ensure_connected()
        logger.info(f"ConektaAdapter: reembolsando pago {request.payment_id}")

        return Refund(
            id=f"refund_{_uuid.uuid4().hex[:16]}",
            payment_id=request.payment_id,
            amount=request.amount or 3200.00,
            status="succeeded",
            reason=request.reason,
            created_at=datetime.now().isoformat(),
        )

    def get_transactions(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Transaction]:
        """Obtiene transacciones mock de Conekta.

        En producción: GET /charges con filtros de fecha
        """
        self._ensure_connected()
        logger.info("ConektaAdapter: obteniendo transacciones (mock)")

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return [
            Transaction(
                id=f"chg_{_uuid.uuid4().hex[:16]}",
                type="payment",
                amount=8000.00 + i * 1500,
                currency=Currency.MXN,
                status=PaymentStatus.SUCCEEDED,
                description=f"Cargo OXXO/SPEI {i}",
                created_at=now,
            )
            for i in range(1, 4)
        ]
