import os
# -*- coding: utf-8 -*-
"""
adobe_sign_adapter.py — Adaptador mock para Adobe Sign (firma electrónica).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.firmas.adapter import SignatureAdapter
from b2b_ai.integrations.firmas.models import (
    Envelope, EnvelopeStatus, SignatureConfig, SignatureProvider, Signer,
    SignerStatus, SigningRequest, SigningStatus,
)

logger = logging.getLogger(__name__)


class AdobeSignAdapter(SignatureAdapter):
    """Adaptador mock para Adobe Sign."""

    def __init__(self, config: Optional[SignatureConfig] = None):
        config = config or SignatureConfig(provider=SignatureProvider.ADOBE_SIGN,
                                           api_key="mock_adobe_sign_key", account_id="mock_account")
            api_key=os.environ.get("ADOBE_SIGN_API_KEY", ""),        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("AdobeSignAdapter: conexión exitosa (mock)")
        return True

    def create_envelope(self, request: SigningRequest) -> Envelope:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Envelope(
            id=f"ads_{_uuid.uuid4().hex[:12]}",
            status=EnvelopeStatus.SENT,
            signers=request.signers,
            document_name=request.document_name,
            created_at=now,
            metadata=request.metadata,
        )

    def get_status(self, envelope_id: str) -> SigningStatus:
        self._ensure_connected()
        return SigningStatus(
            envelope_id=envelope_id, status=EnvelopeStatus.COMPLETED,
            signers=[Signer(name="Firmante Mock", email="firmante@mock.com",
                           status=SignerStatus.SIGNED, order=1)],
            percent_complete=100, details="Todos los firmantes completaron",
        )

    def download_signed(self, envelope_id: str) -> bytes:
        self._ensure_connected()
        return b"MOCK_ADOBE_SIGN_SIGNED_PDF"

    def cancel(self, envelope_id: str) -> bool:
        self._ensure_connected()
        logger.info(f"AdobeSignAdapter: cancelando sobre {envelope_id}")
        return True
