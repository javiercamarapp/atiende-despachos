import os
# -*- coding: utf-8 -*-
"""
salesforce_adapter.py — Adaptador mock para Salesforce (Enterprise CRM).
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


class SalesforceAdapter(CRMAdapter):
    """Adaptador mock para Salesforce."""

    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(provider=CRMProvider.SALESFORCE, api_key="mock_sf_key")
            api_key=os.environ.get("SALESFORCE_CLIENT_ID", ""),        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("SalesforceAdapter: conexión exitosa (mock)")
        return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Contact(id=f"sf_{_uuid.uuid4().hex[:12]}", name=request.name,
                       email=request.email, phone=request.phone, company=request.company,
                       tags=request.tags, metadata=request.metadata, created_at=now, updated_at=now)

    def get_contact(self, contact_id: str) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Contact(id=contact_id, name="Contacto Salesforce Mock",
                       email="sf@mock.com", company="SF Mock Corp", created_at=now, updated_at=now)

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Contact(id=contact_id, name=data.get("name", "Contacto Actualizado"),
                       email=data.get("email", "sf@mock.com"), updated_at=now, created_at=now)

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return [Contact(id=f"sf_{_uuid.uuid4().hex[:8]}", name=f"Contacto SF {i}",
                       email=f"contacto{i}@sfmock.com", company="SF Mock", created_at=now)
                for i in range(1, 4)]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Deal(id=f"deal_sf_{_uuid.uuid4().hex[:8]}", contact_id=contact_id,
                   title=request.title, value=request.value, currency=request.currency,
                   stage=request.stage, created_at=now, updated_at=now)
