# -*- coding: utf-8 -*-
"""
collections — Módulo de cobranza automatizada (FASE 3).

Gestiona cuentas por cobrar de despachos contables mexicanos:
  - Análisis de cartera por antigüedad (buckets 0-30/31-60/61-90/90+)
  - Score de cobrabilidad por factura (0..1)
  - Secuencia de recordatorios automatizados (email/WhatsApp)
  - Scheduler de recordatorios con persistencia
  - Webhooks para confirmación de pagos
  - Reportes PDF de aging y proyección de cobro

Componentes:
  - CollectionsManager (services/collections.py): core de análisis y scoring
  - collections_report.py: reportes de aging, proyección y resumen
  - collections_templates.py: plantillas en español (MX)
  - collections/scheduler.py: programación automática de recordatorios
  - collections/webhooks.py: procesamiento de webhooks de pago
  - collections/api.py: endpoints REST /api/v1/collections/*
  - collections/models.py: modelos Pydantic
  - collections/pdf_report.py: generación de reportes PDF

Uso típico:
    from b2b_ai.collections import CollectionsManager, build_collections_router
"""
from b2b_ai.collections.api import build_collections_router
from b2b_ai.collections.models import (
    AgingReportResponse,
    CollectionEventResponse,
    CollectionsAnalyzeRequest,
    CollectionsSendReminderRequest,
    CollectionsScheduleRequest,
    CollectionsSummaryResponse,
    CollectionWebhookPayload,
    OutstandingInvoiceResponse,
    ProjectionResponse,
)
from b2b_ai.collections.scheduler import CollectionsScheduler
from b2b_ai.collections.webhooks import CollectionsWebhookHandler
from b2b_ai.services.collections import CollectionsManager

__all__ = [
    "build_collections_router",
    "CollectionsManager",
    "CollectionsScheduler",
    "CollectionsWebhookHandler",
    "CollectionsAnalyzeRequest",
    "CollectionsSendReminderRequest",
    "CollectionsScheduleRequest",
    "AgingReportResponse",
    "CollectionEventResponse",
    "CollectionsSummaryResponse",
    "CollectionWebhookPayload",
    "OutstandingInvoiceResponse",
    "ProjectionResponse",
]
