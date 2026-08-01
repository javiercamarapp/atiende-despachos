# -*- coding: utf-8 -*-
"""
__init__.py — Módulo de Integraciones del B2B AI Platform.

Integraciones para SAT, SAT Direct, ERPs, Bancos, Nómina, Pagos, Comunicación,
Almacenamiento, Firmas, CRM, Monitoreo, AI/ML, Documentos y Analytics.
Centraliza el registro y gestión de adaptadores a través del IntegrationHub.

Uso básico:
    from b2b_ai.integrations import IntegrationHub, StripeAdapter

    hub = IntegrationHub()
    hub.register_adapter("pago_stripe", StripeAdapter())
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

# SAT Direct
from b2b_ai.integrations.sat_direct import (
    SATDirectAdapter,
    SATDirectAdapterError,
    SATDirectConnection,
    SATDirectConfig,
)

# ERP
from b2b_ai.integrations.erp import (
    ERPAdapter,
    ERPAdapterError,
    CONTPAQiWebAdapter,
    CONTPAQiDesktopAdapter,
    CONTPAQiOneAdapter,
    AspelCloudAdapter,
    QuickBooksOnlineAdapter,
    QuickBooksDesktopAdapter,
    XeroAdapter,
    PeakAdapter,
    MultilegAdapter,
    EurowebAdapter,
    AbsisAdapter,
    FactorDAdapter,
    TaxkoAdapter,
    FacturaDirectaAdapter,
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
    HSBCAdapter,
    BanamexAdapter,
    ScotiabankAdapter,
    InbursaAdapter,
    AfirmeAdapter,
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

# Pagos
from b2b_ai.integrations.pagos import (
    PaymentAdapter,
    PaymentAdapterError,
    StripeAdapter,
    ConektaAdapter,
    PayPalAdapter,
    KushkiAdapter,
    MercadoPagoAdapter,
    PayPalMexicoAdapter,
    PaymentConfig,
    PaymentRequest,
    PaymentStatus,
    PaymentMethod,
    Currency,
    Refund,
    RefundRequest,
    Transaction,
)

# Comunicación
from b2b_ai.integrations.comunicacion import (
    CommunicationAdapter,
    CommunicationAdapterError,
    SendGridAdapter,
    TwilioAdapter,
    WhatsAppBusinessAdapter,
    MailgunAdapter,
    AWSSesAdapter,
    VonageAdapter,
    MessageBirdAdapter,
    CommunicationConfig,
    EmailRequest,
    SMSRequest,
    WhatsAppRequest,
    NotificationRequest,
    Message,
    MessageChannel,
    MessageStatus,
)

# Almacenamiento
from b2b_ai.integrations.storage import (
    StorageAdapter,
    StorageAdapterError,
    GoogleDriveAdapter,
    OneDriveAdapter,
    S3Adapter,
    DropboxAdapter,
    BoxAdapter,
    GCSAdapter,
    StorageConfig,
    FileMetadata,
    SharePermission,
    UploadResult,
)

# Firmas
from b2b_ai.integrations.firmas import (
    SignatureAdapter,
    SignatureAdapterError,
    DocuSignAdapter,
    FIELAdapter,
    AdobeSignAdapter,
    SignatureConfig,
    SigningRequest,
    Signer,
    Envelope,
    EnvelopeStatus,
)

# CRM
from b2b_ai.integrations.crm import (
    CRMAdapter,
    CRMAdapterError,
    HubSpotAdapter,
    PipedriveAdapter,
    SalesforceAdapter,
    ZohoCRMAdapter,
    CRMConfig,
    Contact,
    ContactCreateRequest,
    Deal,
    DealCreateRequest,
)

# Monitoreo
from b2b_ai.integrations.monitoreo import (
    MonitoringAdapter,
    MonitoringAdapterError,
    SentryAdapter,
    ConsoleAdapter,
    DatadogAdapter,
    NewRelicAdapter,
    LogRocketAdapter,
    MonitoringConfig,
    ErrorReport,
    Breadcrumb,
    ErrorLevel,
)

# AI/ML
from b2b_ai.integrations.ai import (
    AIAdapter,
    AIAdapterError,
    OpenAIAdapter,
    AnthropicAdapter,
    VertexAIAdapter,
    AIConfig,
    AIProvider,
    AIRequest,
    AIResponse,
)

# Documentos
from b2b_ai.integrations.documentos import (
    DocumentProcessor,
    DocumentProcessorError,
    ReportLabProcessor,
    LXMLProcessor,
    TesseractProcessor,
    OpenPyxlProcessor,
)

# Analytics
from b2b_ai.integrations.analytics import (
    AnalyticsAdapter,
    AnalyticsAdapterError,
    GoogleAnalyticsAdapter,
    MixpanelAdapter,
    AmplitudeAdapter,
    AnalyticsConfig,
    AnalyticsEvent,
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
    # SAT Direct
    "SATDirectAdapter",
    "SATDirectAdapterError",
    "SATDirectConnection",
    "SATDirectConfig",
    # ERP
    "ERPAdapter",
    "ERPAdapterError",
    "CONTPAQiWebAdapter",
    "CONTPAQiDesktopAdapter",
    "CONTPAQiOneAdapter",
    "AspelCloudAdapter",
    "QuickBooksOnlineAdapter",
    "QuickBooksDesktopAdapter",
    "XeroAdapter",
    "PeakAdapter",
    "MultilegAdapter",
    "EurowebAdapter",
    "AbsisAdapter",
    "FactorDAdapter",
    "TaxkoAdapter",
    "FacturaDirectaAdapter",
    "ERPConfig",
    "ERPType",
    # Bancos
    "BankAdapter",
    "BankAdapterError",
    "BBVAAdapter",
    "BanorteAdapter",
    "SantanderAdapter",
    "HSBCAdapter",
    "BanamexAdapter",
    "ScotiabankAdapter",
    "InbursaAdapter",
    "AfirmeAdapter",
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
    # Pagos
    "PaymentAdapter",
    "PaymentAdapterError",
    "StripeAdapter",
    "ConektaAdapter",
    "PayPalAdapter",
    "KushkiAdapter",
    "MercadoPagoAdapter",
    "PayPalMexicoAdapter",
    "PaymentConfig",
    "PaymentRequest",
    "PaymentStatus",
    "PaymentMethod",
    "Currency",
    "Refund",
    "RefundRequest",
    "Transaction",
    # Comunicación
    "CommunicationAdapter",
    "CommunicationAdapterError",
    "SendGridAdapter",
    "TwilioAdapter",
    "WhatsAppBusinessAdapter",
    "MailgunAdapter",
    "AWSSesAdapter",
    "VonageAdapter",
    "MessageBirdAdapter",
    "CommunicationConfig",
    "EmailRequest",
    "SMSRequest",
    "WhatsAppRequest",
    "NotificationRequest",
    "Message",
    "MessageChannel",
    "MessageStatus",
    # Almacenamiento
    "StorageAdapter",
    "StorageAdapterError",
    "GoogleDriveAdapter",
    "OneDriveAdapter",
    "S3Adapter",
    "DropboxAdapter",
    "BoxAdapter",
    "GCSAdapter",
    "StorageConfig",
    "FileMetadata",
    "SharePermission",
    "UploadResult",
    # Firmas
    "SignatureAdapter",
    "SignatureAdapterError",
    "DocuSignAdapter",
    "FIELAdapter",
    "AdobeSignAdapter",
    "SignatureConfig",
    "SigningRequest",
    "Signer",
    "Envelope",
    "EnvelopeStatus",
    # CRM
    "CRMAdapter",
    "CRMAdapterError",
    "HubSpotAdapter",
    "PipedriveAdapter",
    "SalesforceAdapter",
    "ZohoCRMAdapter",
    "CRMConfig",
    "Contact",
    "ContactCreateRequest",
    "Deal",
    "DealCreateRequest",
    # Monitoreo
    "MonitoringAdapter",
    "MonitoringAdapterError",
    "SentryAdapter",
    "ConsoleAdapter",
    "DatadogAdapter",
    "NewRelicAdapter",
    "LogRocketAdapter",
    "MonitoringConfig",
    "ErrorReport",
    "Breadcrumb",
    "ErrorLevel",
    # AI/ML
    "AIAdapter",
    "AIAdapterError",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "VertexAIAdapter",
    "AIConfig",
    "AIProvider",
    "AIRequest",
    "AIResponse",
    # Documentos
    "DocumentProcessor",
    "DocumentProcessorError",
    "ReportLabProcessor",
    "LXMLProcessor",
    "TesseractProcessor",
    "OpenPyxlProcessor",
    # Analytics
    "AnalyticsAdapter",
    "AnalyticsAdapterError",
    "GoogleAnalyticsAdapter",
    "MixpanelAdapter",
    "AmplitudeAdapter",
    "AnalyticsConfig",
    "AnalyticsEvent",
]
