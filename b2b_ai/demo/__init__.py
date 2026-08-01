# -*- coding: utf-8 -*-
"""Demo mode — mock API for prospect demos without a real backend.

Activated by ``DEMO_MODE=true`` in the environment. When active the API
returns realistic mock data for all major endpoints so prospects can try
the product without needing real CFDI data, ERP connections, or API keys.

Usage in app startup::

    if os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        from b2b_ai.demo.routes import mount_demo_routes
        mount_demo_routes(app)
"""
from b2b_ai.demo.mock_data import (
    DEMO_CFDI_SAMPLES,
    DEMO_STATS,
    DEMO_ANALYTICS,
    DEMO_INVOICES,
    DEMO_DASHBOARD_SUMMARY,
)
from b2b_ai.demo.routes import mount_demo_routes, is_demo_mode

__all__ = [
    "mount_demo_routes",
    "is_demo_mode",
    "DEMO_CFDI_SAMPLES",
    "DEMO_STATS",
    "DEMO_ANALYTICS",
    "DEMO_INVOICES",
    "DEMO_DASHBOARD_SUMMARY",
]
