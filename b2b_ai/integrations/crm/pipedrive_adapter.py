import os
# -*- coding: utf-8 -*-
"""
pipedrive_adapter.py — Adaptador mock para Pipedrive CRM.

Implementa la interfaz CRMAdapter con respuestas simuladas.
En producción, se conectaría a la Pipedrive API (https://developers.pipedrive.com/docs/api/v1/).
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


class PipedriveAdapter(CRMAdapter):
    """Adaptador mock para Pipedrive CRM.

    En producción, se conectaría a la Pipedrive REST API v1
    (https://developers.pipedrive.com/docs/api/v1/).
    Usa API token para autenticación.
    """

    def __init__(self, config: Optional[CRMConfig] = None):
        config = config or CRMConfig(
            provider=CRMProvider.PIPEDRIVE,
            api_key="MockPipedriveToken1234567890",
            api_key=os.environ.get("PIPEDRIVE_API_KEY", ""),            base_url="https://api.pipedrive.com/v1",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Pipedrive.

        En producción:
        1. Validar token con GET /users/me
        2. Verificar cuenta activa
        """
        logger.info("PipedriveAdapter: conectando a Pipedrive (mock)...")
        self._connected = True
        logger.info("PipedriveAdapter: conexión exitosa (mock)")
        return True

    def create_contact(self, request: ContactCreateRequest) -> Contact:
        """Crea un contacto mock en Pipedrive.

        En producción: POST /v1/persons
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        contact_id = f"pd_{_uuid.uuid4().hex[:16]}"

        logger.info(f"PipedriveAdapter: creando contacto '{request.name}'")

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
        """Obtiene un contacto mock de Pipedrive.

        En producción: GET /v1/persons/{id}
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"PipedriveAdapter: obteniendo contacto {contact_id}")

        return Contact(
            id=contact_id,
            name="María López Hernández",
            email="maria.lopez@empresa.com",
            phone="+525598765432",
            company="Corporativo Demo S.A. DE C.V.",
            tags=["prospect", "mid-market"],
            created_at=now,
            updated_at=now,
        )

    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        """Actualiza un contacto mock en Pipedrive.

        En producción: PUT /v1/persons/{id}
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"PipedriveAdapter: actualizando contacto {contact_id}")

        return Contact(
            id=contact_id,
            name=data.get("name", "María López Hernández"),
            email=data.get("email", "maria.lopez@empresa.com"),
            phone=data.get("phone", "+525598765432"),
            company=data.get("company", "Corporativo Demo S.A. DE C.V."),
            tags=data.get("tags", ["prospect"]),
            updated_at=now,
            created_at=now,
        )

    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        """Lista contactos mock de Pipedrive.

        En producción: GET /v1/persons
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info("PipedriveAdapter: listando contactos (mock)")

        return [
            Contact(
                id=f"pd_person_{i:04d}",
                name=f"Prospecto {i}",
                email=f"prospecto{i}@empresa.com",
                phone=f"+52559876{54 + i:02d}",
                company=f"Corporativo {i} S.A.",
                tags=["prospect"],
                created_at=now,
                updated_at=now,
            )
            for i in range(1, 4)
        ]

    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        """Crea una oportunidad mock en Pipedrive.

        En producción: POST /v1/deals
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        deal_id = f"pd_deal_{_uuid.uuid4().hex[:16]}"

        logger.info(f"PipedriveAdapter: creando oportunidad '{request.title}' para contacto {contact_id}")

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
