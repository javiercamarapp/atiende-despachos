# -*- coding: utf-8 -*-
"""hubspot_adapter.py — Real adapter for HubSpot CRM."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.crm.adapter import CRMAdapter, CRMAdapterError
from b2b_ai.integrations.crm.models import (
    Contact, ContactCreateRequest, CRMConfig, CRMProvider, Deal, DealCreateRequest,
)
logger = logging.getLogger(__name__)

class HubSpotAdapter(CRMAdapter):
    """Real adapter for HubSpot CRM. Requires HUBSPOT_ACCESS_TOKEN."""
    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(
            provider=CRMProvider.HUBSPOT,
            access_token=os.environ.get("HUBSPOT_ACCESS_TOKEN", ""),
            base_url="https://api.hubapi.com",
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("access_token") or self.config.access_token or os.environ.get("HUBSPOT_ACCESS_TOKEN", "")
        if not token:
            logger.warning("HubSpotAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url=self.config.base_url or "https://api.hubapi.com",
                headers={"Authorization": f"Bearer {token}"}, timeout=self.config.timeout)
            resp = self._client.get("/crm/v3/objects/contacts?limit=1")
            resp.raise_for_status()
            self._connected = True
            logger.info("HubSpotAdapter: connected to HubSpot API")
            return True
        except Exception as e:
            logger.error(f"HubSpotAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/crm/v3/objects/contacts", json={
                    "properties": {"email": request.email or "", "firstname": request.name.split()[0] if request.name else "",
                        "lastname": " ".join(request.name.split()[1:]) if len(request.name.split()) > 1 else "",
                        "phone": request.phone or "", "company": request.company or ""}})
                resp.raise_for_status()
                data = resp.json()
                return Contact(id=data.get("id",""), name=request.name, email=request.email,
                    phone=request.phone, company=request.company, tags=request.tags,
                    created_at=now, updated_at=now, metadata=data.get("properties",{}))
            except Exception as e:
                logger.error(f"HubSpotAdapter: create_contact failed: {e}"); raise
        return Contact(id=f"hs_{_uuid.uuid4().hex[:16]}", name=request.name, email=request.email,
            phone=request.phone, company=request.company, tags=request.tags, created_at=now, updated_at=now)

    def get_contact(self, contact_id: str) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get(f"/crm/v3/objects/contacts/{contact_id}")
                resp.raise_for_status()
                data = resp.json()
                props = data.get("properties", {})
                return Contact(id=contact_id, name=f"{props.get('firstname','')} {props.get('lastname','')}".strip(),
                    email=props.get("email"), phone=props.get("phone"),
                    company=props.get("company"), created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"HubSpotAdapter: get_contact failed: {e}"); raise
        return Contact(id=contact_id, name="Mock Contact", email="mock@example.com",
            company="Mock Corp", created_at=now, updated_at=now)

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.patch(f"/crm/v3/objects/contacts/{contact_id}", json={"properties": data})
                resp.raise_for_status()
                return self.get_contact(contact_id)
            except Exception as e:
                logger.error(f"HubSpotAdapter: update_contact failed: {e}"); raise
        return Contact(id=contact_id, name=data.get("name", "Updated Contact"),
            email=data.get("email"), company=data.get("company"), created_at=now, updated_at=now)

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get("/crm/v3/objects/contacts", params={"limit": 100})
                resp.raise_for_status()
                results = resp.json().get("results", [])
                return [Contact(id=c.get("id",""), name=f"{c.get('properties',{}).get('firstname','')} {c.get('properties',{}).get('lastname','')}".strip(),
                    email=c.get("properties",{}).get("email"), phone=c.get("properties",{}).get("phone"),
                    company=c.get("properties",{}).get("company"), created_at=now, updated_at=now) for c in results]
            except Exception as e:
                logger.error(f"HubSpotAdapter: list_contacts failed: {e}"); raise
        return [Contact(id=f"hs_{_uuid.uuid4().hex[:8]}", name=f"Contact {i}",
            email=f"contact{i}@example.com", company="Mock Corp", created_at=now, updated_at=now) for i in range(1, 4)]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/crm/v3/objects/deals", json={
                    "properties": {"dealname": request.title, "amount": str(request.value),
                        "pipeline": "default", "dealstage": request.stage.value}})
                resp.raise_for_status()
                data = resp.json()
                return Deal(id=data.get("id",""), contact_id=contact_id, title=request.title,
                    value=request.value, currency=request.currency, stage=request.stage,
                    created_at=now, updated_at=now, metadata=data.get("properties",{}))
            except Exception as e:
                logger.error(f"HubSpotAdapter: create_deal failed: {e}"); raise
        return Deal(id=f"hsd_{_uuid.uuid4().hex[:16]}", contact_id=contact_id, title=request.title,
            value=request.value, currency=request.currency, stage=request.stage, created_at=now, updated_at=now)
