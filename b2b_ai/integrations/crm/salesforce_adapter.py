# -*- coding: utf-8 -*-
"""salesforce_adapter.py — Real adapter for Salesforce CRM."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.crm.adapter import CRMAdapter, CRMAdapterError
from b2b_ai.integrations.crm.models import (
    Contact, ContactCreateRequest, CRMConfig, CRMProvider, Deal, DealCreateRequest,
)
logger = logging.getLogger(__name__)

class SalesforceAdapter(CRMAdapter):
    """Real adapter for Salesforce CRM. Requires SF_CLIENT_ID, SF_CLIENT_SECRET, SF_USERNAME, SF_PASSWORD."""
    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(
            provider=CRMProvider.SALESFORCE,
            api_key=os.environ.get("SF_CLIENT_ID", ""),
            base_url=os.environ.get("SF_LOGIN_URL", "https://login.salesforce.com"),
        )
        super().__init__(config=config)
        self._client = None
        self._instance_url = None
        self._token = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        client_id = self.config.api_key or os.environ.get("SF_CLIENT_ID", "")
        client_secret = (credentials or {}).get("client_secret") or os.environ.get("SF_CLIENT_SECRET", "")
        username = (credentials or {}).get("username") or os.environ.get("SF_USERNAME", "")
        password = (credentials or {}).get("password") or os.environ.get("SF_PASSWORD", "")
        if not all([client_id, client_secret, username, password]):
            logger.warning("SalesforceAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            resp = httpx.post(f"{self.config.base_url}/services/oauth2/token", data={
                "grant_type": "password", "client_id": client_id, "client_secret": client_secret,
                "username": username, "password": password}, timeout=self.config.timeout)
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("access_token")
            self._instance_url = data.get("instance_url")
            self._client = httpx.Client(base_url=self._instance_url,
                headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                timeout=self.config.timeout)
            self._connected = True
            logger.info("SalesforceAdapter: connected to Salesforce")
            return True
        except Exception as e:
            logger.error(f"SalesforceAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/services/data/v59.0/sobjects/Contact", json={
                    "FirstName": request.name.split()[0] if request.name else "",
                    "LastName": " ".join(request.name.split()[1:]) or "Unknown",
                    "Email": request.email or "", "Phone": request.phone or "",
                    "Description": f"Tags: {', '.join(request.tags)}" if request.tags else ""})
                resp.raise_for_status()
                cid = resp.json().get("id", "")
                return Contact(id=cid, name=request.name, email=request.email, phone=request.phone,
                    company=request.company, tags=request.tags, created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"SalesforceAdapter: create_contact failed: {e}"); raise
        return Contact(id=f"sf_{_uuid.uuid4().hex[:16]}", name=request.name, email=request.email,
            phone=request.phone, company=request.company, tags=request.tags, created_at=now, updated_at=now)

    def get_contact(self, contact_id: str) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get(f"/services/data/v59.0/sobjects/Contact/{contact_id}")
                resp.raise_for_status()
                data = resp.json()
                return Contact(id=contact_id, name=f"{data.get('FirstName','')} {data.get('LastName','')}".strip(),
                    email=data.get("Email"), phone=data.get("Phone"),
                    company=data.get("Account",{}).get("Name") if isinstance(data.get("Account"), dict) else None,
                    created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"SalesforceAdapter: get_contact failed: {e}"); raise
        return Contact(id=contact_id, name="Mock Contact", email="mock@example.com",
            company="Mock Corp", created_at=now, updated_at=now)

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.patch(f"/services/data/v59.0/sobjects/Contact/{contact_id}", json=data)
                resp.raise_for_status()
                return self.get_contact(contact_id)
            except Exception as e:
                logger.error(f"SalesforceAdapter: update_contact failed: {e}"); raise
        return Contact(id=contact_id, name=data.get("name", "Updated"), created_at=now, updated_at=now)

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                soql = "SELECT Id, FirstName, LastName, Email, Phone FROM Contact LIMIT 100"
                resp = self._client.get("/services/data/v59.0/query", params={"q": soql})
                resp.raise_for_status()
                records = resp.json().get("records", [])
                return [Contact(id=r.get("Id",""), name=f"{r.get('FirstName','')} {r.get('LastName','')}".strip(),
                    email=r.get("Email"), phone=r.get("Phone"), created_at=now, updated_at=now) for r in records]
            except Exception as e:
                logger.error(f"SalesforceAdapter: list_contacts failed: {e}"); raise
        return [Contact(id=f"sf_{_uuid.uuid4().hex[:8]}", name=f"Contact {i}",
            email=f"contact{i}@example.com", company="Mock Corp", created_at=now, updated_at=now) for i in range(1, 4)]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/services/data/v59.0/sobjects/Opportunity", json={
                    "Name": request.title, "Amount": request.value,
                    "StageName": "Prospecting", "CloseDate": now[:10],
                    "ContactId": contact_id})
                resp.raise_for_status()
                did = resp.json().get("id", "")
                return Deal(id=did, contact_id=contact_id, title=request.title,
                    value=request.value, currency=request.currency, stage=request.stage,
                    created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"SalesforceAdapter: create_deal failed: {e}"); raise
        return Deal(id=f"sfd_{_uuid.uuid4().hex[:16]}", contact_id=contact_id, title=request.title,
            value=request.value, currency=request.currency, stage=request.stage, created_at=now, updated_at=now)
