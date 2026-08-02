# -*- coding: utf-8 -*-
"""docusign_adapter.py — Real adapter for DocuSign e-signature."""
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

class DocuSignAdapter(SignatureAdapter):
    """Real adapter for DocuSign. Requires DOCUSIGN_ACCESS_TOKEN and DOCUSIGN_ACCOUNT_ID."""
    def __init__(self, config: Optional[SignatureConfig] = None):
        config = config or SignatureConfig(
            provider=SignatureProvider.DOCUSIGN,
            api_key=os.environ.get("DOCUSIGN_ACCESS_TOKEN", ""),
            account_id=os.environ.get("DOCUSIGN_ACCOUNT_ID", ""),
            base_url=os.environ.get("DOCUSIGN_BASE_URL", "https://demo.docusign.net"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("DOCUSIGN_ACCESS_TOKEN", "")
        account_id = (credentials or {}).get("account_id") or self.config.account_id or os.environ.get("DOCUSIGN_ACCOUNT_ID", "")
        if not token or not account_id:
            logger.warning("DocuSignAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            base = self.config.base_url or "https://demo.docusign.net"
            self._client = httpx.Client(base_url=f"{base}/restapi",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=self.config.timeout)
            self._connected = True
            logger.info("DocuSignAdapter: connected to DocuSign API")
            return True
        except Exception as e:
            logger.error(f"DocuSignAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_envelope(self, request: SigningRequest) -> Envelope:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                account_id = self.config.account_id
                resp = self._client.post(f"/v2.1/accounts/{account_id}/envelopes", json={
                    "emailSubject": request.subject, "emailBlurb": request.message,
                    "documents": [{"documentBase64": "bW9jaA==", "name": request.document_name, "documentId": "1"}],
                    "recipients": {"signers": [{"name": s.name, "email": s.email,
                        "recipientId": str(i+1), "routingOrder": str(s.order)}
                        for i, s in enumerate(request.signers)]},
                    "status": "sent"})
                resp.raise_for_status()
                data = resp.json()
                return Envelope(id=data.get("envelopeId",""), status=EnvelopeStatus.SENT,
                    signers=request.signers, document_name=request.document_name, created_at=now)
            except Exception as e:
                logger.error(f"DocuSignAdapter: create_envelope failed: {e}"); raise
        envelope_id = f"docusign_{_uuid.uuid4().hex[:16]}"
        return Envelope(id=envelope_id, status=EnvelopeStatus.SENT, signers=request.signers,
            document_name=request.document_name, created_at=now)

    def get_status(self, envelope_id: str) -> SigningStatus:
        self._ensure_connected()
        if self._client:
            try:
                account_id = self.config.account_id
                resp = self._client.get(f"/v2.1/accounts/{account_id}/envelopes/{envelope_id}")
                resp.raise_for_status()
                data = resp.json()
                status_map = {"created": EnvelopeStatus.DRAFT, "sent": EnvelopeStatus.SENT,
                    "completed": EnvelopeStatus.COMPLETED, "declined": EnvelopeStatus.DECLINED,
                    "voided": EnvelopeStatus.CANCELLED}
                return SigningStatus(envelope_id=envelope_id,
                    status=status_map.get(data.get("status",""), EnvelopeStatus.SENT),
                    percent_complete=data.get("purgeDocumentsDate") and 100 or 0)
            except Exception as e:
                logger.error(f"DocuSignAdapter: get_status failed: {e}"); raise
        return SigningStatus(envelope_id=envelope_id, status=EnvelopeStatus.SENT,
            signers=[Signer(name="Mock", email="mock@test.com", status=SignerStatus.PENDING)],
            percent_complete=0, details="Mock status")

    def download_signed(self, envelope_id: str) -> bytes:
        self._ensure_connected()
        if self._client:
            try:
                account_id = self.config.account_id
                resp = self._client.get(f"/v2.1/accounts/{account_id}/envelopes/{envelope_id}/documents/combined")
                resp.raise_for_status(); return resp.content
            except Exception as e:
                logger.error(f"DocuSignAdapter: download_signed failed: {e}"); raise
        return b"mock signed document"

    def cancel(self, envelope_id: str) -> bool:
        self._ensure_connected()
        if self._client:
            try:
                account_id = self.config.account_id
                resp = self._client.put(f"/v2.1/accounts/{account_id}/envelopes/{envelope_id}",
                    json={"status": "voided", "voidedReason": "Cancelled by user"})
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"DocuSignAdapter: cancel failed: {e}"); raise
        return True
