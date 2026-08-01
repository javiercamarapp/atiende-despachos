# -*- coding: utf-8 -*-
"""
__init__.py — Módulo de Integraciones del B2B AI Platform.

Integraciones para SAT, ERPs, Bancos, Nómina, Google, Microsoft,
Gobierno, Social, Calendario, Compliance y más.
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
    SATAdapter, SATAdapterError,
    EcodexAdapter, FinkokAdapter, SATPortalAdapter,
)

# SAT PACs
from b2b_ai.integrations.sat.pacs import (
    CorefiAdapter, FacturapiAdapter, PAXFACTURASAdapter, MultifacturaAdapter,
)

# ERP
from b2b_ai.integrations.erp import (
    ERPAdapter, ERPAdapterError,
    CONTPAQiWebAdapter, CONTPAQiDesktopAdapter, AspelCloudAdapter,
    QuickBooksOnlineAdapter, XeroAdapter, PeakAdapter, MultilegAdapter,
    EurowebAdapter, AbsisAdapter, FactorDAdapter, TaxkoAdapter, FacturaDirectaAdapter,
    ERPConfig, ERPType,
)

# Bancos
from b2b_ai.integrations.bancos import (
    BankAdapter, BankAdapterError,
    BBVAAdapter, BanorteAdapter, SantanderAdapter,
    HSBCAdapter, BanamexAdapter, ScotiabankAdapter, InbursaAdapter, AfirmeAdapter,
    OFXParser, CSVParser, BankConfig, Banco,
)

# Nómina
from b2b_ai.integrations.nomina import (
    NominaAdapter, NominaAdapterError, NominaService,
    Empleado, CalculoImpuestos,
)

# Pagos
from b2b_ai.integrations.pagos import (
    PaymentAdapter, PaymentAdapterError,
    StripeAdapter, ConektaAdapter, KushkiAdapter, MercadoPagoAdapter,
    PayPalAdapter, OpenPayAdapter,
)

# Comunicación
from b2b_ai.integrations.comunicacion import (
    CommunicationAdapter, CommunicationAdapterError,
    SendGridAdapter, TwilioAdapter, MailgunAdapter, AWSSesAdapter,
    VonageAdapter, MessageBirdAdapter, WhatsAppBusinessAdapter,
)

# Almacenamiento
from b2b_ai.integrations.storage import (
    StorageAdapter, StorageAdapterError,
    GoogleDriveAdapter, OneDriveAdapter, S3Adapter,
    DropboxAdapter, BoxAdapter, GCSAdapter,
)

# CRM
from b2b_ai.integrations.crm import (
    CRMAdapter, CRMAdapterError,
    HubSpotAdapter, PipedriveAdapter, SalesforceAdapter, ZohoCRMAdapter,
)

# Firmas Electrónicas
from b2b_ai.integrations.firmas import (
    SignatureAdapter, SignatureAdapterError,
    DocuSignAdapter, FIELAdapter, AdobeSignAdapter,
)

# Google Services
from b2b_ai.integrations.google import (
    GoogleSheetsAdapter, GmailAdapter, GoogleCalendarAdapter,
)

# Microsoft Services
from b2b_ai.integrations.microsoft import (
    ExcelGraphAdapter, OutlookAdapter, Microsoft365Adapter,
)

# Portales Gubernamentales
from b2b_ai.integrations.gobierno import (
    IMSSAdapter, INFONAVITAdapter, SARAdapter, CONDUSEFAdapter,
)

# Redes Sociales
from b2b_ai.integrations.social import (
    LinkedInAdapter, FacebookAdapter, InstagramAdapter,
)

# Calendario
from b2b_ai.integrations.calendario import CalendlyAdapter

# Cumplimiento
from b2b_ai.integrations.compliance import (
    CFFCompliance, LISRCompliance, LIVACompliance,
    LFTCompliance, LFPDPPPCompliance, NOM151Compliance,
)

__all__ = [
    # Hub
    "IntegrationHub", "IntegrationHubError",
    # SAT
    "SATAdapter", "SATAdapterError", "EcodexAdapter", "FinkokAdapter", "SATPortalAdapter",
    # SAT PACs
    "CorefiAdapter", "FacturapiAdapter", "PAXFACTURASAdapter", "MultifacturaAdapter",
    # ERP
    "ERPAdapter", "ERPAdapterError",
    "CONTPAQiWebAdapter", "CONTPAQiDesktopAdapter", "AspelCloudAdapter",
    "QuickBooksOnlineAdapter", "XeroAdapter", "PeakAdapter", "MultilegAdapter",
    "EurowebAdapter", "AbsisAdapter", "FactorDAdapter", "TaxkoAdapter", "FacturaDirectaAdapter",
    "ERPConfig", "ERPType",
    # Bancos
    "BankAdapter", "BankAdapterError",
    "BBVAAdapter", "BanorteAdapter", "SantanderAdapter",
    "HSBCAdapter", "BanamexAdapter", "ScotiabankAdapter", "InbursaAdapter", "AfirmeAdapter",
    "OFXParser", "CSVParser", "BankConfig", "Banco",
    # Nómina
    "NominaAdapter", "NominaAdapterError", "NominaService", "Empleado", "CalculoImpuestos",
    # Pagos
    "PaymentAdapter", "PaymentAdapterError",
    "StripeAdapter", "ConektaAdapter", "KushkiAdapter", "MercadoPagoAdapter",
    "PayPalAdapter", "OpenPayAdapter",
    # Comunicación
    "CommunicationAdapter", "CommunicationAdapterError",
    "SendGridAdapter", "TwilioAdapter", "MailgunAdapter", "AWSSesAdapter",
    "VonageAdapter", "MessageBirdAdapter", "WhatsAppBusinessAdapter",
    # Almacenamiento
    "StorageAdapter", "StorageAdapterError",
    "GoogleDriveAdapter", "OneDriveAdapter", "S3Adapter",
    "DropboxAdapter", "BoxAdapter", "GCSAdapter",
    # CRM
    "CRMAdapter", "CRMAdapterError",
    "HubSpotAdapter", "PipedriveAdapter", "SalesforceAdapter", "ZohoCRMAdapter",
    # Firmas
    "SignatureAdapter", "SignatureAdapterError",
    "DocuSignAdapter", "FIELAdapter", "AdobeSignAdapter",
    # Google
    "GoogleSheetsAdapter", "GmailAdapter", "GoogleCalendarAdapter",
    # Microsoft
    "ExcelGraphAdapter", "OutlookAdapter", "Microsoft365Adapter",
    # Gobierno
    "IMSSAdapter", "INFONAVITAdapter", "SARAdapter", "CONDUSEFAdapter",
    # Social
    "LinkedInAdapter", "FacebookAdapter", "InstagramAdapter",
    # Calendario
    "CalendlyAdapter",
    # Compliance
    "CFFCompliance", "LISRCompliance", "LIVACompliance",
    "LFTCompliance", "LFPDPPPCompliance", "NOM151Compliance",
]
