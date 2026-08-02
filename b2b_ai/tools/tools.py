# -*- coding: utf-8 -*-
"""
tools.py — Implementación de las tools del agente.

Cada tool se registra con `@tool` y queda disponible para el router y el
orquestador. Son la capa que el agente "llama": parse, validate, classify,
register_erp, notify, reconcile, report.
"""
from __future__ import annotations

from b2b_ai.tools.registry import tool
from b2b_ai.cfdi.parser import parse_cfdi as _parse
from b2b_ai.cfdi.validator import validate_cfdi as _validate
from b2b_ai.services.classify import classify_cfdi as _classify
from b2b_ai.erp.contpaqi import MockCONTPAQi
from b2b_ai.notifications import templates
from b2b_ai.notifications.sender import EmailSender
from b2b_ai.notifications.whatsapp import MockWhatsApp
from b2b_ai.services.reconcile import reconcile as _reconcile
from b2b_ai.services.reconcile import (parse_bank_statement_csv as _parse_csv,
                                       parse_bank_statement_pdf as _parse_pdf,
                                       build_reconciliation_report as _rep_recon)
from b2b_ai.services.payroll import calculate_payroll as _payroll
from b2b_ai.services.accounting import (get_catalogo as _catalogo,
                                        build_balance as _balance,
                                        send_balance_to_sat as _sat_send)
from b2b_ai.services.report import generate_report as _report
from b2b_ai.services.anomaly import detect_anomalies as _detect_anomalies
from b2b_ai.services.anomaly import summarize_anomalies as _summarize_anomalies
from b2b_ai.services.approval import ApprovalManager as _ApprovalManager
from b2b_ai.services.approval import DEFAULT_AUTO_THRESHOLD


@tool(name="parse_cfdi",
      description="Extrae todos los campos de un CFDI 4.0 XML.",
      category="parse",
      parameters=[{"name": "xml_path", "type": "string", "required": True}])
def parse_cfdi(xml_path):
    """Lee un CFDI XML y devuelve sus datos normalizados."""
    return _parse(xml_path)


@tool(name="validate_cfdi",
      description="Valida fiscalmente un CFDI (aritmética, catálogos SAT, "
                  "fechas, retenciones, DIOT).",
      category="validate",
      parameters=[{"name": "xml_path", "type": "string", "required": False},
                  {"name": "datos", "type": "object", "required": False}])
def validate_cfdi(xml_path=None, datos=None):
    """Valida un CFDI. Acepta la ruta al XML o el dict ya parseado."""
    if datos is None:
        datos = _parse(xml_path)
    return _validate(datos)


@tool(name="classify_expense",
      description="Clasifica contablemente un CFDI (gasto operativo, "
                  "inversión, activo fijo, nómina).",
      category="classify",
      parameters=[{"name": "xml_path", "type": "string", "required": False},
                  {"name": "datos", "type": "object", "required": False}])
def classify_expense(xml_path=None, datos=None):
    """Clasifica un CFDI. Acepta ruta XML o dict parseado."""
    if datos is None:
        datos = _parse(xml_path)
    return _classify(datos)


@tool(name="register_erp",
      description="Registra una póliza/factura en el ERP (CONTPAQi mock o CSV).",
      category="erp",
      parameters=[{"name": "invoice", "type": "object", "required": True}])
def register_erp(invoice, erp=None, tenant_id=None):
    """Registra la factura en el ERP. Acepta un ERPInterface inyectado."""
    if erp is None:
        erp = _get_default_erp(tenant_id=tenant_id)
    return erp.register_invoice(invoice)


_tool_erp = None


def _get_default_erp(tenant_id=None):
    global _tool_erp
    if _tool_erp is not None:
        return _tool_erp
    try:
        from b2b_ai.computer_use.factory import ComputerUseDriverFactory
        from b2b_ai.computer_use.config import ComputerUseConfig
        config = ComputerUseConfig.from_env()
        if config.mode != "disabled":
            _tool_erp = ComputerUseDriverFactory.create(
                provider=config.provider, mode=config.mode,
                tenant_id=tenant_id, config=config)
            return _tool_erp
    except Exception:
        pass
    _tool_erp = MockCONTPAQi()
    return _tool_erp


@tool(name="send_notification",
      description="Envía una notificación (email/WhatsApp) por tipo de evento.",
      category="notify",
      parameters=[{"name": "event_type", "type": "string", "required": True},
                  {"name": "to", "type": "string", "required": True},
                  {"name": "context", "type": "object", "required": True},
                  {"name": "channel", "type": "string", "required": False},
                  {"name": "email", "type": "object", "required": False},
                  {"name": "whatsapp", "type": "object", "required": False}])
def send_notification(event_type, to, context, channel="email",
                      email=None, whatsapp=None):
    """Renderiza la plantilla del evento y envía por el canal indicado."""
    subject, body = templates.render(event_type, context)
    if channel == "whatsapp":
        wa = whatsapp or MockWhatsApp()
        res = wa.send_message(to, body, template_name=event_type)
        res["subject"] = subject
        return res
    # canal email (default)
    sender = email or EmailSender()
    return sender.send(to, subject, body)


@tool(name="reconcile_bank",
      description="Concilia movimientos bancarios contra facturas.",
      category="reconcile",
      parameters=[{"name": "invoices", "type": "list", "required": True},
                  {"name": "bank_transactions", "type": "list", "required": True},
                  {"name": "date_tolerance_days", "type": "integer", "required": False}])
def reconcile_bank(invoices, bank_transactions, date_tolerance_days=3):
    """Cruce mecánico banco ↔ facturas."""
    return _reconcile(invoices, bank_transactions, date_tolerance_days)


@tool(name="generate_report",
      description="Genera un reporte de agregados (mensual, por categoría).",
      category="report",
      parameters=[{"name": "invoices", "type": "list", "required": True},
                  {"name": "period", "type": "string", "required": False},
                  {"name": "tenant_id", "type": "integer", "required": False}])
def generate_report(invoices, period=None, tenant_id=None):
    """Agrega facturas en un reporte."""
    return _report(invoices, period=period, tenant_id=tenant_id)


@tool(name="parse_bank_statement",
      description="Parsea un estado de cuenta bancario (CSV o PDF) a "
                  "movimientos normalizados.",
      category="reconcile",
      parameters=[{"name": "path", "type": "string", "required": True}])
def parse_bank_statement(path):
    """Parsea CSV o PDF de banco. Auto-detecta el formato por extensión."""
    if str(path).lower().endswith(".pdf"):
        return _parse_pdf(path)
    return _parse_csv(path)


@tool(name="reconciliation_report",
      description="Genera el reporte completo de una conciliación bancaria.",
      category="reconcile",
      parameters=[{"name": "invoices", "type": "list", "required": True},
                  {"name": "bank_transactions", "type": "list", "required": True},
                  {"name": "date_tolerance_days", "type": "integer",
                   "required": False}])
def reconciliation_report(invoices, bank_transactions, date_tolerance_days=3):
    """Reporte de conciliación (montos, pendientes, tasa)."""
    return _rep_recon(invoices, bank_transactions, date_tolerance_days)


@tool(name="calculate_payroll",
      description="Calcula una nómina: ISR, IMSS, INFONAVIT y prestaciones.",
      category="payroll",
      parameters=[{"name": "empleado", "type": "object", "required": True},
                  {"name": "sueldo_bruto", "type": "number", "required": True},
                  {"name": "dias_pagados", "type": "integer", "required": False}])
def calculate_payroll(empleado, sueldo_bruto, dias_pagados=None):
    """Desglose de percepciones/deducciones de una nómina."""
    return _payroll(empleado, sueldo_bruto, dias_pagados=dias_pagados)


@tool(name="build_balance",
      description="Construye la balanza de comprobación desde facturas.",
      category="accounting",
      parameters=[{"name": "invoices", "type": "list", "required": True},
                  {"name": "period", "type": "string", "required": False}])
def build_balance(invoices, period=None):
    """Balanza de comprobación agregada por cuenta contable."""
    return _balance(invoices, period=period)


@tool(name="send_balance_to_sat",
      description="Envía la balanza de comprobación al SAT (MOCK).",
      category="accounting",
      parameters=[{"name": "balanza", "type": "object", "required": True},
                  {"name": "ejercicio", "type": "integer", "required": True},
                  {"name": "mes", "type": "integer", "required": True},
                  {"name": "rfc", "type": "string", "required": False}])
def send_balance_to_sat(balanza, ejercicio, mes, rfc=""):
    """Acuse simulado de envío de balanza al SAT."""
    return _sat_send(balanza, ejercicio, mes, rfc=rfc)


@tool(name="detect_anomalies",
      description="Detecta anomalías en una factura contra su historial "
                  "(duplicados, montos atípicos, IVA inconsistente, proveedor "
                  "nuevo).",
      category="anomaly",
      parameters=[{"name": "invoice", "type": "object", "required": True},
                  {"name": "historical", "type": "list", "required": False}])
def detect_anomalies(invoice, historical=None):
    """Detecta anomalías de riesgo en una factura. Devuelve lista + resumen."""
    an = _detect_anomalies(invoice, historical or [])
    return {"anomalies": an, "summary": _summarize_anomalies(an)}


@tool(name="evaluate_approval",
      description="Evalúa si una factura se auto-aprueba o requiere aprobación "
                  "humana (gate por monto y e.firma para pagos).",
      category="approval",
      parameters=[{"name": "invoice", "type": "object", "required": True},
                  {"name": "auto_threshold", "type": "number", "required": False}])
def evaluate_approval(invoice, auto_threshold=DEFAULT_AUTO_THRESHOLD):
    """Evalúa el gate de aprobación de una factura (FASE 2)."""
    return _ApprovalManager(auto_threshold=auto_threshold).evaluate(invoice)
