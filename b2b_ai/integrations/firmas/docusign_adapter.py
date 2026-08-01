import os
# -*- coding: utf-8 -*-
"""
docusign_adapter.py — Adaptador mock para DocuSign.

Implementa la interfaz SignatureAdapter con respuestas simuladas.
En producción, se conectaría a la DocuSign eSignature API (https://developers.docusign.com/docs/esign-rest-api/).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.firmas.adapter import SignatureAdapter
from b2b_ai.integrations.firmas.models import (
    Envelope,
    EnvelopeStatus,
    SignatureConfig,
    SignatureProvider,
    Signer,
    SignerStatus,
    SigningRequest,
    SigningStatus,
)

logger = logging.getLogger(__name__)


class DocuSignAdapter(SignatureAdapter):
    """Adaptador mock para DocuSign eSignature.

    En producción, se conectaría a la DocuSign REST API v2.1
    (https://developers.docusign.com/docs/esign-rest-api/reference/).
    Usa OAuth 2.0 (JWT Grant o Authorization Code Grant).
    """

    def __init__(self, config: Optional[SignatureConfig] = None):
        config = config or SignatureConfig(
            provider=SignatureProvider.DOCUSIGN,
            api_key="MockDocuSignIntegrationKey",
            api_key=os.environ.get("DOCUSIGN_API_KEY", ""),            api_secret="MockDocuSignSecret",
            account_id="MockDocuSignAccount123",
            base_url="https://demo.docusign.net",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a DocuSign.

        En producción:
        1. Obtener access_token con JWT Grant
        2. Verificar cuenta con GET /restapi/v2.1/accounts/{accountId}
        """
        logger.info("DocuSignAdapter: conectando a DocuSign (mock)...")
        self._connected = True
        logger.info("DocuSignAdapter: conexión exitosa (mock)")
        return True

    def create_envelope(self, request: SigningRequest) -> Envelope:
        """Crea un sobre mock en DocuSign.

        En producción: POST /restapi/v2.1/accounts/{accountId}/envelopes
        """
        self._ensure_connected()
        now = datetime.now().isoformat()

        logger.info(f"DocuSignAdapter: creando sobre para '{request.document_name}'")

        return Envelope(
            id=f"env_{_uuid.uuid4().hex[:32]}",
            status=EnvelopeStatus.SENT,
            signers=[
                Signer(
                    name=s.name,
                    email=s.email,
                    role=s.role,
                    order=s.order,
                    status=SignerStatus.DELIVERED,
                )
                for s in request.signers
            ],
            document_name=request.document_name,
            created_at=now,
            metadata=request.metadata,
        )

    def get_status(self, envelope_id: str) -> SigningStatus:
        """Obtiene el estado mock de un sobre.

        En producción: GET /restapi/v2.1/accounts/{accountId}/envelopes/{envelopeId}
        """
        self._ensure_connected()
        logger.info(f"DocuSignAdapter: consultando estado de sobre {envelope_id}")

        return SigningStatus(
            envelope_id=envelope_id,
            status=EnvelopeStatus.SENT,
            signers=[
                Signer(name="Firmante 1", email="firmante1@example.com", status=SignerStatus.SIGNED),
                Signer(name="Firmante 2", email="firmante2@example.com", status=SignerStatus.PENDING),
            ],
            percent_complete=50,
            details="1 de 2 firmantes ha completado",
        )

    def download_signed(self, envelope_id: str) -> bytes:
        """Descarga el documento firmado mock.

        En producción: GET /restapi/v2.1/accounts/{accountId}/envelopes/{envelopeId}/documents/combined
        """
        self._ensure_connected()
        logger.info(f"DocuSignAdapter: descargando documento firmado {envelope_id}")
        return b"mock signed document from DocuSign PDF content"

    def cancel(self, envelope_id: str) -> bool:
        """Cancela un sobre mock en DocuSign.

        En producción: PUT /restapi/v2.1/accounts/{accountId}/envelopes/{envelopeId}
        con status=cancelled
        """
        self._ensure_connected()
        logger.info(f"DocuSignAdapter: cancelando sobre {envelope_id}")
        return True
