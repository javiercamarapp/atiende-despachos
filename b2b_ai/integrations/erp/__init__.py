# -*- coding: utf-8 -*-
"""Modulo de integracion ERP — CONTPAQi, Aspel, QuickBooks, Xero, Peak, Multileg, Euroweb, Absis, Factor D, Taxko, FacturaDirecta."""

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.http_client import (
    ERPAPIError, ERPAuthError, ERPConnectionError, make_request,
)
from b2b_ai.integrations.erp.contpaqi_web import CONTPAQiWebAdapter
from b2b_ai.integrations.erp.contpaqi_desktop import CONTPAQiDesktopAdapter
from b2b_ai.integrations.erp.aspel_cloud import AspelCloudAdapter
from b2b_ai.integrations.erp.quickbooks import QuickBooksOnlineAdapter
from b2b_ai.integrations.erp.xero import XeroAdapter
from b2b_ai.integrations.erp.peak import PeakAdapter
from b2b_ai.integrations.erp.multileg import MultilegAdapter
from b2b_ai.integrations.erp.euroweb import EurowebAdapter
from b2b_ai.integrations.erp.absis import AbsisAdapter
from b2b_ai.integrations.erp.factor_d import FactorDAdapter
from b2b_ai.integrations.erp.taxko import TaxkoAdapter
from b2b_ai.integrations.erp.facturadirecta import FacturaDirectaAdapter
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
    "ERPAPIError",
    "ERPAuthError",
    "ERPConnectionError",
    "make_request",
    "CONTPAQiWebAdapter",
    "CONTPAQiDesktopAdapter",
    "AspelCloudAdapter",
    "QuickBooksOnlineAdapter",
    "XeroAdapter",
    "PeakAdapter",
    "MultilegAdapter",
    "EurowebAdapter",
    "AbsisAdapter",
    "FactorDAdapter",
    "TaxkoAdapter",
    "FacturaDirectaAdapter",
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
