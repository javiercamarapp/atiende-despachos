import os
# -*- coding: utf-8 -*-
"""
hubspot_adapter.py — Adaptador mock para HubSpot CRM.

Implementa la interfaz CRMAdapter con respuestas simuladas.
En producción, se conectaría a la HubSpot API (https://developers.hubspot.com/api-reference/).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.crm.adapter import CRMAdapter
from b2b_ai.integrations.crm.models import (
    CRMConfig,
    CRMProvider,
    Contact,
    ContactCreateRequest,
    Deal,
    DealCreateRequest,
    DealStage,
    DealStatus,
)

logger = logging.getLogger(__name__)


class HubSpotAdapter(CRMAdapter):
    """Adaptador mock para HubSpot CRM.

    En producción, se conectaría a la HubSpot CRM API v3
    (https://developers.hubspot.com/api-reference/crm).
    Usa private app access token o OAuth 2.0.
    """

    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(
            provider=CRMProvider.HUBSPOT,
            api_key="MockHubSpotToken1234567890",
            api_key=os.environ.get("HUBSPOT_API_KEY", ""),            base_url="https://api.hubapi.com",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a HubSpot.

        En producción:
        1. Validar token con GET /crm/v3/objects/contacts (limit=1)
        2. Verificar permisos del token
        """
        logger.info("HubSpotAdapter: conectando a HubSpot (mock)...")
        self._connected = True
        logger.info("HubSpotAdapter: conexión exitosa (mock)")
        return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        """Crea un contacto mock en HubSpot.

        En producción: POST /crm/v3/objects/contacts
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        contact_id = f"hs_{_uuid.uuid4().hex[:16]}"

        logger.info(f"HubSpotAdapter: creando contacto '{request.name}'")

        return Contact(
            id=contact_id,
            name=request.name,
            email=request.email,
            phone=request.phone,
            company=request.company,
            tags=request.tags,
            created_at=now,
            updated_at=now,
            metadata=request.metadata,
        )

    def get_contact(self, contact_id: str) -> Contact:
        """Obtiene un contacto mock de HubSpot.

        En producción: GET /crm/v3/objects/contacts/{contactId}
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"HubSpotAdapter: obteniendo contacto {contact_id}")

        return Contact(
            id=contact_id,
            name="Juan Pérez García",
            email="juan.perez@empresa.com",
            phone="+525512345678",
            company="Empresa Ejemplo S.A. DE C.V.",
            tags=["lead", "enterprise"],
            created_at=now,
            updated_at=now,
        )

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        """Actualiza un contacto mock en HubSpot.

        En producción: PATCH /crm/v3/objects/contacts/{contactId}
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"HubSpotAdapter: actualizando contacto {contact_id}")

        return Contact(
            id=contact_id,
            name=data.get("name", "Juan Pérez García"),
            email=data.get("email", "juan.perez@empresa.com"),
            phone=data.get("phone", "+525512345678"),
            company=data.get("company", "Empresa Ejemplo S.A. DE C.V."),
            tags=data.get("tags", ["lead"]),
            updated_at=now,
            created_at=now,
        )

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        """Lista contactos mock de HubSpot.

        En producción: POST /crm/v3/objects/contacts/search
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info("HubSpotAdapter: listando contactos (mock)")

        return [
            Contact(
                id=f"hs_contact_{i:04d}",
                name=f"Contacto {i}",
                email=f"contacto{i}@empresa.com",
                phone=f"+5255123456{78 + i}",
                company=f"Empresa {i} S.A.",
                tags=["lead"],
                created_at=now,
                updated_at=now,
            )
            for i in range(1, 4)
        ]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        """Crea una oportunidad mock en HubSpot.

        En producción: POST /crm/v3/objects/deals
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        deal_id = f"hs_deal_{_uuid.uuid4().hex[:16]}"

        logger.info(f"HubSpotAdapter: creando oportunidad '{request.title}' para contacto {contact_id}")

        return Deal(
            id=deal_id,
            contact_id=contact_id,
            title=request.title,
            value=request.value,
            currency=request.currency,
            stage=request.stage,
            status=DealStatus.OPEN,
            created_at=now,
            updated_at=now,
            metadata=request.metadata,
        )
