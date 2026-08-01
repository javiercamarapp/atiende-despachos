"""Módulo de integración Microsoft Services — Excel, Outlook, M365."""
from b2b_ai.integrations.microsoft.excel_adapter import ExcelGraphAdapter
from b2b_ai.integrations.microsoft.outlook_adapter import OutlookAdapter
from b2b_ai.integrations.microsoft.m365_adapter import Microsoft365Adapter

__all__ = ["ExcelGraphAdapter", "OutlookAdapter", "Microsoft365Adapter"]
