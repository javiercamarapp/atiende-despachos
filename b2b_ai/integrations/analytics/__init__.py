# -*- coding: utf-8 -*-
"""Módulo de integración de Analytics — Google Analytics, Mixpanel, Amplitude."""

from b2b_ai.integrations.analytics.adapter import AnalyticsAdapter, AnalyticsAdapterError
from b2b_ai.integrations.analytics.google_analytics_adapter import GoogleAnalyticsAdapter
from b2b_ai.integrations.analytics.mixpanel_adapter import MixpanelAdapter
from b2b_ai.integrations.analytics.amplitude_adapter import AmplitudeAdapter
from b2b_ai.integrations.analytics.models import (
    AnalyticsConfig, AnalyticsEvent, AnalyticsEventResult, AnalyticsProvider,
    AnalyticsQuery, AnalyticsQueryResult, EventType,
)

__all__ = [
    "AnalyticsAdapter", "AnalyticsAdapterError",
    "GoogleAnalyticsAdapter", "MixpanelAdapter", "AmplitudeAdapter",
    "AnalyticsConfig", "AnalyticsEvent", "AnalyticsEventResult",
    "AnalyticsProvider", "AnalyticsQuery", "AnalyticsQueryResult", "EventType",
]
