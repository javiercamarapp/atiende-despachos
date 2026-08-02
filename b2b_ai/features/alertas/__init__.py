# -*- coding: utf-8 -*-
"""
Módulo Alertas Inteligentes: motor de reglas, store y API para notificaciones
de facturas vencidas, anomalías, discrepancias de conciliación y picos de volumen.

Expone:
  - Alert, AlertRule, AlertConfig, AlertHistory, NotificationPreference
  - AlertEngine — lógica de evaluación de reglas
  - AlertStore  — almacén en memoria con dedup, historial y acknowledge/dismiss
  - build_alertas_router() — FastAPI router (/api/v1/alerts/*)
"""
from b2b_ai.features.alertas.models import (
    Alert,
    AlertRule,
    AlertConfig,
    AlertHistory,
    NotificationPreference,
)
from b2b_ai.features.alertas.engine import AlertEngine
from b2b_ai.features.alertas.store import AlertStore
from b2b_ai.features.alertas.routes import build_alertas_router
from b2b_ai.features.alertas.deadline_engine import (
    DeadlineEngine,
    FiscalObligation,
    SAT_OBLIGATIONS_2026,
)
from b2b_ai.features.alertas.anomaly_detector import (
    AnomalyDetector,
    AnomalyThresholds,
)
from b2b_ai.features.alertas.notification_service import (
    AlertNotificationService,
    NotificationConfig,
)

__all__ = [
    "Alert",
    "AlertRule",
    "AlertConfig",
    "AlertHistory",
    "NotificationPreference",
    "AlertEngine",
    "AlertStore",
    "build_alertas_router",
    "DeadlineEngine",
    "FiscalObligation",
    "SAT_OBLIGATIONS_2026",
    "AnomalyDetector",
    "AnomalyThresholds",
    "AlertNotificationService",
    "NotificationConfig",
]
