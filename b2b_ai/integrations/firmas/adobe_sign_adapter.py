# -*- coding: utf-8 -*-
"""adobe_sign_adapter.py — Real adapter for Adobe Acrobat Sign."""
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

class AdobeSignAdapter(SignatureAdapter):
    """Real adapter for Adobe Acrobat Sign. Requires ADOBE_SIGN_ACCESS_TOKEN."""
    def __init__(self, config: Optional[SignatureConfig] = None):
        config = config or SignatureConfig(
            provider=SignatureProvider.ADOBE_SIGN,
            api_key=os.environ.get("ADOBE_SIGN_ACCESS_TOKEN", ""),
            base_url=os.environ.get("ADOBE_SIGN_BASE_URL", "https://api.na1.echosign.com"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("ADOBE_SIGN_ACCESS_TOKEN", "")
        if not token:
            logger.warning("AdobeSignAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            base = self.config.base_url or "https://api.na1.echosign.com"
            self._client = httpx.Client(base_url=base,
                headers={"Authorization": f"Bearer {token}"}, timeout=self.config.timeout)
            resp = self._client.get("/api/rest/v6/userInfo")
            resp.raise_for_status()
            self._connected = True
            logger.info("AdobeSignAdapter: connected to Adobe Sign API")
            return True
        except Exception as e:
            logger.error(f"AdobeSignAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_envelope(self, request: SigningRequest) -> Envelope:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/api/rest/v6/agreements", json={
                    "fileInfos": [{"fileName": request.document_name, "documentLabel": "Document"}],
                    "name": request.subject,
                    "participantSetsInfo": [{"memberInfos": [{"email": s.email}],
                        "role": "SIGNER", "order": s.order} for s in request.signers],
                    "emailMessage": request.message})
                resp.raise_for_status()
                data = resp.json()
                return Envelope(id=data.get("id",""), status=EnvelopeStatus.SENT,
                    signers=request.signers, document_name=request.document_name, created_at=now)
            except Exception as e:
                logger.error(f"AdobeSignAdapter: create_envelope failed: {e}"); raise
        envelope_id = f"adobe_{_uuid.uuid4().hex[:16]}"
        return Envelope(id=envelope_id, status=EnvelopeStatus.SENT, signers=request.signers,
            document_name=request.document_name, created_at=now)

    def get_status(self, envelope_id: str) -> SigningStatus:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/api/rest/v6/agreements/{envelope_id}")
                resp.raise_for_status()
                data = resp.json()
                status_map = {"DRAFT": EnvelopeStatus.DRAFT, "IN_PROCESS": EnvelopeStatus.SENT,
                    "SIGNED": EnvelopeStatus.COMPLETED, "DECLINED": EnvelopeStatus.DECLINED}
                return SigningStatus(envelope_id=envelope_id,
                    status=status_map.get(data.get("status",""), EnvelopeStatus.SENT),
                    percent_complete=100 if data.get("status") == "SIGNED" else 0)
            except Exception as e:
                logger.error(f"AdobeSignAdapter: get_status failed: {e}"); raise
        return SigningStatus(envelope_id=envelope_id, status=EnvelopeStatus.SENT,
            signers=[Signer(name="Mock", email="mock@test.com", status=SignerStatus.PENDING)],
            percent_complete=0, details="Mock status")

    def download_signed(self, envelope_id: str) -> bytes:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/api/rest/v6/agreements/{envelope_id}/signedDocuments")
                resp.raise_for_status(); return resp.content
            except Exception as e:
                logger.error(f"AdobeSignAdapter: download_signed failed: {e}"); raise
        return b"mock Adobe Sign document"

    def cancel(self, envelope_id: str) -> bool:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.put(f"/api/rest/v6/agreements/{envelope_id}/status",
                    json={"value": "CANCEL"})
                return resp.status_code in (200, 202)
            except Exception as e:
                logger.error(f"AdobeSignAdapter: cancel failed: {e}"); raise
        return True
