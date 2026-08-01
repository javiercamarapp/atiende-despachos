# -*- coding: utf-8 -*-
"""Módulo de integración ERP — CONTPAQi, Aspel, QuickBooks, Xero."""

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.contpaqi_web import CONTPAQiWebAdapter
from b2b_ai.integrations.erp.contpaqi_desktop import CONTPAQiDesktopAdapter
from b2b_ai.integrations.erp.aspel_cloud import AspelCloudAdapter
from b2b_ai.integrations.erp.quickbooks import QuickBooksOnlineAdapter
from b2b_ai.integrations.erp.xero import XeroAdapter
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion,
    ChartOfAccounts,
    CuentaContable,
    CuentaPoliza,
    ERPConfig,
    ERPType,
    Invoice,
    Poliza,
    StatusPoliza,
    TipoCuenta,
)

__all__ = [
    "ERPAdapter",
    "ERPAdapterError",
    "CONTPAQiWebAdapter",
    "CONTPAQiDesktopAdapter",
    "AspelCloudAdapter",
    "QuickBooksOnlineAdapter",
    "XeroAdapter",
    "BalanzaComprobacion",
    "ChartOfAccounts",
    "CuentaContable",
    "CuentaPoliza",
    "ERPConfig",
    "ERPType",
    "Invoice",
    "Poliza",
    "StatusPoliza",
    "TipoCuenta",
]
