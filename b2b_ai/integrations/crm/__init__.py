# -*- coding: utf-8 -*-
"""Módulo de integración de CRM — HubSpot, Pipedrive."""

from b2b_ai.integrations.crm.adapter import CRMAdapter, CRMAdapterError
from b2b_ai.integrations.crm.hubspot_adapter import HubSpotAdapter
from b2b_ai.integrations.crm.pipedrive_adapter import PipedriveAdapter
from b2b_ai.integrations.crm.models import (
    Contact,
    ContactCreateRequest,
    CRMConfig,
    CRMProvider,
    Deal,
    DealCreateRequest,
    DealStage,
    DealStatus,
)

__all__ = [
    "CRMAdapter",
    "CRMAdapterError",
    "HubSpotAdapter",
    "PipedriveAdapter",
    "Contact",
    "ContactCreateRequest",
    "CRMConfig",
    "CRMProvider",
    "Deal",
    "DealCreateRequest",
    "DealStage",
    "DealStatus",
]
