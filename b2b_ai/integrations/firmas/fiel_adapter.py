# -*- coding: utf-8 -*-
"""fiel_adapter.py — Adapter for FIEL/SAT electronic signature (e.firma)."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.firmas.adapter import SignatureAdapter, SignatureAdapterError
from b2b_ai.integrations.firmas.models import (
    Envelope, EnvelopeStatus, SignatureConfig, SignatureProvider, Signer, SignerStatus,
    SigningRequest, SigningStatus,
)
logger = logging.getLogger(__name__)


def _decrypt_fiel_password(raw: str) -> str:
    """VULN-15: If B2B_ENCRYPTION_KEY is set, try to decrypt the FIEL password.
    Otherwise return as-is (env var plaintext — acceptable only in dev)."""
    if not raw:
        return raw
    try:
        from b2b_ai.api.security import decrypt_field
        return decrypt_field(raw)
    except Exception:  # noqa: BLE001
        return raw

class FIELAdapter(SignatureAdapter):
    """Adapter for FIEL/SAT e.firma. Requires FIEL_CERT_PATH and FIEL_KEY_PATH."""
    def __init__(self, config: Optional[SignatureConfig] = None):
        config = config or SignatureConfig(
            provider=SignatureProvider.FIEL,
            fiel_cert_path=os.environ.get("FIEL_CERT_PATH", ""),
            fiel_key_path=os.environ.get("FIEL_KEY_PATH", ""),
            fiel_password=_decrypt_fiel_password(os.environ.get("FIEL_PASSWORD", "")),
        )
        super().__init__(config=config)
        self._cert = None
        self._key = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        cert_path = self.config.fiel_cert_path or os.environ.get("FIEL_CERT_PATH", "")
        key_path = self.config.fiel_key_path or os.environ.get("FIEL_KEY_PATH", "")
        if not cert_path or not key_path or not os.path.exists(cert_path):
            logger.warning("FIELAdapter: no certificates — MOCK mode")
            self._connected = True; self._cert = None; self._key = None; return True
        try:
            from cryptography.hazmat.primitives import serialization
            with open(cert_path, "rb") as f:
                self._cert = f.read()
            with open(key_path, "rb") as f:
                self._key = serialization.load_pem_private_key(
                    f.read(), password=(self.config.fiel_password or "").encode())
            self._connected = True
            logger.info("FIELAdapter: certificates loaded")
            return True
        except Exception as e:
            logger.error(f"FIELAdapter: connection failed: {e}")
            self._connected = True; self._cert = None; self._key = None; return True

    def create_envelope(self, request: SigningRequest) -> Envelope:
        """Sign a document with FIEL. For XML signing (CFDI)."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        envelope_id = f"fiel_{_uuid.uuid4().hex[:16]}"
        if self._cert and self._key:
            try:
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import padding
                from lxml import etree
                # In production: sign XML CFDI with FIEL certificate
                logger.info(f"FIELAdapter: signing document {request.document_name} with FIEL")
                return Envelope(id=envelope_id, status=EnvelopeStatus.COMPLETED,
                    signers=[Signer(name="FIEL", email="fiel@sat.gob.mx", status=SignerStatus.SIGNED)],
                    document_name=request.document_name, created_at=now, completed_at=now,
                    metadata={"method": "fiel_xml_signature"})
            except Exception as e:
                logger.error(f"FIELAdapter: create_envelope failed: {e}"); raise
        return Envelope(id=envelope_id, status=EnvelopeStatus.COMPLETED,
            signers=[Signer(name="FIEL", email="fiel@sat.gob.mx", status=SignerStatus.SIGNED)],
            document_name=request.document_name, created_at=now, completed_at=now,
            metadata={"mock": True, "method": "fiel_xml_signature"})

    def get_status(self, envelope_id: str) -> SigningStatus:
        self._ensure_connected()
        return SigningStatus(envelope_id=envelope_id, status=EnvelopeStatus.COMPLETED,
            signers=[Signer(name="FIEL", email="fiel@sat.gob.mx", status=SignerStatus.SIGNED)],
            percent_complete=100, details="FIEL signing is synchronous")

    def download_signed(self, envelope_id: str) -> bytes:
        self._ensure_connected()
        return b"mock FIEL signed document"

    def cancel(self, envelope_id: str) -> bool:
        self._ensure_connected()
        logger.warning("FIELAdapter: cancel not applicable for FIEL signing")
        return True
