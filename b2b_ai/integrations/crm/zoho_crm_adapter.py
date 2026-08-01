# -*- coding: utf-8 -*-
"""
zoho_crm_adapter.py — Adaptador mock para Zoho CRM (Pyme CRM).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.crm.adapter import CRMAdapter
from b2b_ai.integrations.crm.models import (
    Contact, ContactCreateRequest, CRMConfig, CRMProvider, Deal, DealCreateRequest,
)

logger = logging.getLogger(__name__)


class ZohoCRMAdapter(CRMAdapter):
    """Adaptador mock para Zoho CRM."""

    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(provider=CRMProvider.ZOHO_CRM, api_key="mock_zoho_key")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("ZohoCRMAdapter: conexión exitosa (mock)")
        return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Contact(id=f"zoho_{_uuid.uuid4().hex[:12]}", name=request.name,
                       email=request.email, phone=request.phone, company=request.company,
                       tags=request.tags, metadata=request.metadata, created_at=now, updated_at=now)

    def get_contact(self, contact_id: str) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Contact(id=contact_id, name="Contacto Zoho Mock",
                       email="zoho@mock.com", company="Zoho Mock Corp", created_at=now, updated_at=now)

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Contact(id=contact_id, name=data.get("name", "Contacto Zoho"),
                       email=data.get("email", "zoho@mock.com"), updated_at=now, created_at=now)

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return [Contact(id=f"zoho_{_uuid.uuid4().hex[:8]}", name=f"Contacto Zoho {i}",
                       email=f"contacto{i}@zhomock.com", company="Zoho Mock", created_at=now)
                for i in range(1, 4)]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Deal(id=f"deal_zoho_{_uuid.uuid4().hex[:8]}", contact_id=contact_id,
                   title=request.title, value=request.value, currency=request.currency,
                   stage=request.stage, created_at=now, updated_at=now)
