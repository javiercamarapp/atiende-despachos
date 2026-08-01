# -*- coding: utf-8 -*-
"""
__init__.py — Módulo de Integraciones del B2B AI Platform.

Integraciones para SAT, ERPs, Bancos y Nómina.
Centraliza el registro y gestión de adaptadores a través del IntegrationHub.

Uso básico:
    from b2b_ai.integrations import IntegrationHub, EcodexAdapter

    hub = IntegrationHub()
    hub.register_adapter("sat_ecodex", EcodexAdapter())
    hub.connect_all()
    status = hub.get_status()
"""
from b2b_ai.integrations.hub import IntegrationHub, IntegrationHubError

# SAT
from b2b_ai.integrations.sat import (
    SATAdapter,
    SATAdapterError,
    EcodexAdapter,
    FinkokAdapter,
    SATPortalAdapter,
)

# ERP
from b2b_ai.integrations.erp import (
    ERPAdapter,
    ERPAdapterError,
    CONTPAQiWebAdapter,
    CONTPAQiDesktopAdapter,
    AspelCloudAdapter,
    QuickBooksOnlineAdapter,
    XeroAdapter,
    ERPConfig,
    ERPType,
)

# Bancos
from b2b_ai.integrations.bancos import (
    BankAdapter,
    BankAdapterError,
    BBVAAdapter,
    BanorteAdapter,
    SantanderAdapter,
    OFXParser,
    CSVParser,
    BankConfig,
    Banco,
)

# Nómina
from b2b_ai.integrations.nomina import (
    NominaAdapter,
    NominaAdapterError,
    NominaService,
    Empleado,
    CalculoImpuestos,
)

__all__ = [
    # Hub
    "IntegrationHub",
    "IntegrationHubError",
    # SAT
    "SATAdapter",
    "SATAdapterError",
    "EcodexAdapter",
    "FinkokAdapter",
    "SATPortalAdapter",
    # ERP
    "ERPAdapter",
    "ERPAdapterError",
    "CONTPAQiWebAdapter",
    "CONTPAQiDesktopAdapter",
    "AspelCloudAdapter",
    "QuickBooksOnlineAdapter",
    "XeroAdapter",
    "ERPConfig",
    "ERPType",
    # Bancos
    "BankAdapter",
    "BankAdapterError",
    "BBVAAdapter",
    "BanorteAdapter",
    "SantanderAdapter",
    "OFXParser",
    "CSVParser",
    "BankConfig",
    "Banco",
    # Nómina
    "NominaAdapter",
    "NominaAdapterError",
    "NominaService",
    "Empleado",
    "CalculoImpuestos",
]
