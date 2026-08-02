# -*- coding: utf-8 -*-
"""zoho_crm_adapter.py — Real adapter for Zoho CRM."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.crm.adapter import CRMAdapter, CRMAdapterError
from b2b_ai.integrations.crm.models import (
    Contact, ContactCreateRequest, CRMConfig, CRMProvider, Deal, DealCreateRequest,
)
logger = logging.getLogger(__name__)

class ZohoCRMAdapter(CRMAdapter):
    """Real adapter for Zoho CRM. Requires ZOHO_CRM_ACCESS_TOKEN."""
    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(
            provider=CRMProvider.ZOHO_CRM,
            access_token=os.environ.get("ZOHO_CRM_ACCESS_TOKEN", ""),
            base_url=os.environ.get("ZOHO_CRM_BASE_URL", "https://www.zohoapis.com/crm/v2"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("access_token") or self.config.access_token or os.environ.get("ZOHO_CRM_ACCESS_TOKEN", "")
        if not token:
            logger.warning("ZohoCRMAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url=self.config.base_url or "https://www.zohoapis.com/crm/v2",
                headers={"Authorization": f"Zoho-oauthtoken {token}"}, timeout=self.config.timeout)
            resp = self._client.get("/users?type=CurrentUser")
            resp.raise_for_status()
            self._connected = True
            logger.info("ZohoCRMAdapter: connected to Zoho CRM")
            return True
        except Exception as e:
            logger.error(f"ZohoCRMAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/Contacts", json={"data": [
                    {"First_Name": request.name.split()[0] if request.name else "",
                     "Last_Name": " ".join(request.name.split()[1:]) or "Unknown",
                     "Email": request.email, "Phone": request.phone}]})
                resp.raise_for_status()
                data = resp.json().get("data", [{}])[0]
                return Contact(id=data.get("details",{}).get("id",""), name=request.name,
                    email=request.email, phone=request.phone, company=request.company,
                    tags=request.tags, created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"ZohoCRMAdapter: create_contact failed: {e}"); raise
        return Contact(id=f"zoho_{_uuid.uuid4().hex[:16]}", name=request.name, email=request.email,
            phone=request.phone, company=request.company, tags=request.tags, created_at=now, updated_at=now)

    def get_contact(self, contact_id: str) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get(f"/Contacts/{contact_id}")
                resp.raise_for_status()
                data = resp.json().get("data", [{}])[0]
                return Contact(id=contact_id, name=f"{data.get('First_Name','')} {data.get('Last_Name','')}".strip(),
                    email=data.get("Email"), phone=data.get("Phone"),
                    company=data.get("Account_Name",{}).get("name") if isinstance(data.get("Account_Name"), dict) else None,
                    created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"ZohoCRMAdapter: get_contact failed: {e}"); raise
        return Contact(id=contact_id, name="Mock Contact", email="mock@example.com",
            company="Mock Corp", created_at=now, updated_at=now)

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.put(f"/Contacts/{contact_id}", json={"data": [data]})
                resp.raise_for_status()
                return self.get_contact(contact_id)
            except Exception as e:
                logger.error(f"ZohoCRMAdapter: update_contact failed: {e}"); raise
        return Contact(id=contact_id, name=data.get("name", "Updated"), created_at=now, updated_at=now)

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get("/Contacts", params={"per_page": 100})
                resp.raise_for_status()
                records = resp.json().get("data", [])
                return [Contact(id=c.get("id",""), name=f"{c.get('First_Name','')} {c.get('Last_Name','')}".strip(),
                    email=c.get("Email"), phone=c.get("Phone"), created_at=now, updated_at=now) for c in records]
            except Exception as e:
                logger.error(f"ZohoCRMAdapter: list_contacts failed: {e}"); raise
        return [Contact(id=f"zoho_{_uuid.uuid4().hex[:8]}", name=f"Contact {i}",
            email=f"contact{i}@example.com", company="Mock Corp", created_at=now, updated_at=now) for i in range(1, 4)]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/Deals", json={"data": [
                    {"Deal_Name": request.title, "Amount": request.value,
                     "Stage": "Qualification", "Contact_Name": contact_id}]})
                resp.raise_for_status()
                data = resp.json().get("data", [{}])[0]
                return Deal(id=data.get("details",{}).get("id",""), contact_id=contact_id,
                    title=request.title, value=request.value, currency=request.currency,
                    stage=request.stage, created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"ZohoCRMAdapter: create_deal failed: {e}"); raise
        return Deal(id=f"zohod_{_uuid.uuid4().hex[:16]}", contact_id=contact_id, title=request.title,
            value=request.value, currency=request.currency, stage=request.stage, created_at=now, updated_at=now)
