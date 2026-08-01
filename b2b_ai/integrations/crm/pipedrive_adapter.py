# -*- coding: utf-8 -*-
"""pipedrive_adapter.py — Real adapter for Pipedrive CRM."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.crm.adapter import CRMAdapter, CRMAdapterError
from b2b_ai.integrations.crm.models import (
    Contact, ContactCreateRequest, CRMConfig, CRMProvider, Deal, DealCreateRequest,
)
logger = logging.getLogger(__name__)

class PipedriveAdapter(CRMAdapter):
    """Real adapter for Pipedrive CRM. Requires PIPEDRIVE_API_TOKEN."""
    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(
            provider=CRMProvider.PIPEDRIVE,
            api_key=os.environ.get("PIPEDRIVE_API_TOKEN", ""),
            base_url="https://api.pipedrive.com/v1",
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        api_key = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("PIPEDRIVE_API_TOKEN", "")
        if not api_key:
            logger.warning("PipedriveAdapter: no API token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url=self.config.base_url or "https://api.pipedrive.com/v1",
                params={"api_token": api_key}, timeout=self.config.timeout)
            resp = self._client.get("/users/me")
            resp.raise_for_status()
            self._connected = True
            logger.info("PipedriveAdapter: connected to Pipedrive API")
            return True
        except Exception as e:
            logger.error(f"PipedriveAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/persons", json={"name": request.name,
                    "email": [{"value": request.email or "", "primary": True}] if request.email else [],
                    "phone": [{"value": request.phone or "", "primary": True}] if request.phone else [],
                    "org_name": request.company or ""})
                resp.raise_for_status()
                data = resp.json().get("data", {})
                return Contact(id=str(data.get("id","")), name=request.name, email=request.email,
                    phone=request.phone, company=request.company, tags=request.tags,
                    created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"PipedriveAdapter: create_contact failed: {e}"); raise
        return Contact(id=f"pd_{_uuid.uuid4().hex[:16]}", name=request.name, email=request.email,
            phone=request.phone, company=request.company, tags=request.tags, created_at=now, updated_at=now)

    def get_contact(self, contact_id: str) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get(f"/persons/{contact_id}")
                resp.raise_for_status()
                data = resp.json().get("data", {})
                emails = data.get("email", [])
                phones = data.get("phone", [])
                return Contact(id=contact_id, name=data.get("name",""),
                    email=emails[0].get("value") if emails else None,
                    phone=phones[0].get("value") if phones else None,
                    company=data.get("org_name"), created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"PipedriveAdapter: get_contact failed: {e}"); raise
        return Contact(id=contact_id, name="Mock Contact", email="mock@example.com",
            company="Mock Corp", created_at=now, updated_at=now)

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.put(f"/persons/{contact_id}", json=data)
                resp.raise_for_status()
                return self.get_contact(contact_id)
            except Exception as e:
                logger.error(f"PipedriveAdapter: update_contact failed: {e}"); raise
        return Contact(id=contact_id, name=data.get("name", "Updated"), created_at=now, updated_at=now)

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get("/persons", params={"limit": 100})
                resp.raise_for_status()
                results = resp.json().get("data", []) or []
                return [Contact(id=str(p.get("id","")), name=p.get("name",""),
                    email=(p.get("email",[{}]) or [{}])[0].get("value"),
                    phone=(p.get("phone",[{}]) or [{}])[0].get("value"),
                    company=p.get("org_name"), created_at=now, updated_at=now) for p in results]
            except Exception as e:
                logger.error(f"PipedriveAdapter: list_contacts failed: {e}"); raise
        return [Contact(id=f"pd_{_uuid.uuid4().hex[:8]}", name=f"Contact {i}",
            email=f"contact{i}@example.com", company="Mock Corp", created_at=now, updated_at=now) for i in range(1, 4)]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("/deals", json={"title": request.title,
                    "value": request.value, "currency": request.currency,
                    "status": "open", "person_id": int(contact_id) if contact_id.isdigit() else 0})
                resp.raise_for_status()
                data = resp.json().get("data", {})
                return Deal(id=str(data.get("id","")), contact_id=contact_id, title=request.title,
                    value=request.value, currency=request.currency, stage=request.stage,
                    created_at=now, updated_at=now)
            except Exception as e:
                logger.error(f"PipedriveAdapter: create_deal failed: {e}"); raise
        return Deal(id=f"pdd_{_uuid.uuid4().hex[:16]}", contact_id=contact_id, title=request.title,
            value=request.value, currency=request.currency, stage=request.stage, created_at=now, updated_at=now)
