#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera docs/openapi.json desde la app FastAPI real + enriquecimiento.

Uso (desde la raíz del proyecto):
    .venv/bin/python scripts/generate_openapi.py

Genera el OpenAPI contract (todas las rutas y schemas) directamente de
create_app() — nunca a mano, para que nunca se desincronice del código — y le
añade servers, securitySchemes y ejemplos reales.

Determinista: hace model_rebuild() sobre todos los módulos que definen modelos
Pydantic (billing, auth, onboarding, sat, notifications, portal) antes de pedir
el schema, para evitar el error 'not fully defined' de forward refs.
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# --- 1) Rebuild de modelos con forward refs (pydantic v2) ------------------
_REBUILD_MODULES = [
    "b2b_ai.billing.models",
    "b2b_ai.auth.api",
    "b2b_ai.auth.middleware",
    "b2b_ai.auth.users",
    "b2b_ai.auth.roles",
    "b2b_ai.onboarding.wizard",
    "b2b_ai.onboarding.checklist",
    "b2b_ai.sat.api",
    "b2b_ai.notifications.api",
    "b2b_ai.api.portal",
    "b2b_ai.api.webhooks",
    "b2b_ai.api.v2",
]
for _mod in _REBUILD_MODULES:
    try:
        _m = importlib.import_module(_mod)
    except Exception:
        continue
    for _name in dir(_m):
        _obj = getattr(_m, _name)
        if isinstance(_obj, type) and hasattr(_obj, "model_rebuild"):
            try:
                _obj.model_rebuild()
            except Exception:
                pass

# --- 2) Dump del OpenAPI real ----------------------------------------------
from b2b_ai.api.app import create_app  # noqa: E402

app = create_app()
spec = app.openapi()

# --- 3) Enriquecimiento ----------------------------------------------------
spec["servers"] = [
    {"url": "https://api.b2b-ai.local", "description": "Producción"},
    {"url": "http://localhost:8000", "description": "Local (uvicorn)"},
]
components = spec.setdefault("components", {})
components["securitySchemes"] = {
    "ApiKeyAuth": {
        "type": "apiKey", "in": "header", "name": "X-API-Key",
        "description": ("API key del tenant (tabla api_keys) o la key de "
                        "servicio (env B2B_API_KEY). Header X-API-Key."),
    },
    "BearerAuth": {
        "type": "http", "scheme": "bearer", "bearerFormat": "opaque",
        "description": "Token del Portal del cliente (POST /portal/auth/login).",
    },
    "JWTAuth": {
        "type": "http", "scheme": "bearer",
        "description": ("JWT access token de auth enterprise "
                        "(POST /api/v1/auth/login)."),
    },
}
APIKEY_PREFIXES = ("/api/v1/", "/api/v2/")
APIKEY_EXACT = ("/tools", "/invoices", "/stats", "/process")
BEARER_PREFIX = "/portal/"
JWT_PREFIXES = ("/api/v1/auth/", "/api/v1/tenants/")
NO_AUTH_PATHS = {
    "/api/v1/auth/login", "/api/v1/auth/register",
    "/portal/auth/login", "/portal/auth/magic-link", "/portal/auth/confirm",
}
for path, item in spec["paths"].items():
    for method, op in item.items():
        if not isinstance(op, dict):
            continue
        if path in NO_AUTH_PATHS:
            op["security"] = []
        elif path.startswith(BEARER_PREFIX):
            op["security"] = [{"BearerAuth": []}]
        elif path.startswith(JWT_PREFIXES) and not path.startswith("/api/v1/tenants"):
            op["security"] = [{"JWTAuth": []}]
        elif path.startswith(APIKEY_PREFIXES) or path in APIKEY_EXACT:
            op["security"] = [{"ApiKeyAuth": []}]
        else:
            op["security"] = []

EXAMPLES = {
    "/api/v1/invoices/process": {
        "multipart": {"summary": "Subida multipart (archivo XML)",
                      "value": {"xml_file": "<archivo CFDI .xml>", "tenant_id": 1}},
        "json": {"summary": "JSON con xml_path (servidor)",
                 "value": {"xml_path": "/data/cfdi/factura_20260731.xml",
                           "tenant_id": 1}},
    },
    "/api/v1/leads": {"json": {"value": {"nombre": "María González",
        "email": "maria@despacho.com", "despacho": "Despacho Contable XYZ",
        "facturas": "400/mes", "mensaje": "Quiero automatizar mi contabilidad"}}},
    "/api/v1/reconcile/run": {"json": {"value": {
        "invoices": [{"folio_fiscal": "A1B2C3", "fecha": "2026-07-30",
                      "total": 12000.0, "emisor": "XAXX010101000"}],
        "bank_transactions": [{"fecha": "2026-07-30", "monto": 12000.0,
                               "descripcion": "Transferencia", "ref": "A1B2C3"}],
        "date_tolerance_days": 3}}},
    "/api/v1/payroll/calculate": {"json": {"value": {
        "empleado": {"nombre": "Juan Pérez", "rfc": "PEJA850101XXX"},
        "emisor": {"rfc": "DESP820101AB1", "nombre": "Despacho Contable B&B",
                   "regimen_fiscal": "601"},
        "periodo": {"sueldo_bruto": 25000.0, "dias_pagados": 30},
        "generar_cfdi": False}}},
    "/api/v1/collections/analyze": {"json": {"value": {
        "invoices": [{"factura_id": "F-1001", "monto": 8500.0,
                      "fecha_vencimiento": "2026-06-15"}], "sync": True}}},
    "/api/v1/collections/send-reminder": {"json": {"value": {
        "invoice": {"factura_id": "F-1001", "monto": 8500.0,
                    "cliente": "Comercial Ruiz", "fecha_vencimiento": "2026-06-15"},
        "stage": "cortesia", "channel": "email", "record": True}}},
    "/api/v1/contabilidad/catalogo": {"json": {"value": {
        "rfc": "XAXX010101000",
        "cuentas": [{"codigo": "1000", "descripcion": "Caja",
                     "nivel": 1, "naturaleza": "deudora"}]}}},
    "/api/v1/contabilidad/asientos": {"json": {"value": {
        "fecha": "2026-07-31", "cuenta_debito": "1000", "cuenta_credito": "2000",
        "monto": "15000.00", "descripcion": "Registro de factura",
        "factura_id": ""}}},
    "/api/v1/tenants": {"json": {"value": {
        "name": "Despacho Demo S.C.", "rfc": "DESP820101AB1", "erp_type": "contpaqi",
        "plantilla_contable": "SAT", "notif_channel": "email",
        "webhook_url": "https://cliente.example.com/hooks/b2b",
        "user_name": "María", "user_email": "maria@despacho.com"}}},
    "/api/v1/webhooks/email": {"json": {"value": {
        "from": "proveedor@x.com", "subject": "Factura CFDI", "text": "Adjunto factura",
        "attachments": [{"filename": "factura.xml",
                         "content_base64": "<base64 del XML>"}]}}},
    "/api/v1/webhooks/notify": {"json": {"value": {
        "event": "invoice_processed", "invoice_id": 42}}},
    "/api/v1/webhooks/subscriptions": {"json": {"value": {
        "url": "https://cliente.example.com/hooks/b2b"}}},
    "/api/v1/notifications/send": {"json": {"value": {
        "recipient": "+5215512345678", "message": "Tu factura F-1001 está por vencer.",
        "template": None, "type": "whatsapp", "schedule_at": None}}},
    "/api/v1/billing/checkout": {"json": {"value": {
        "plan": "starter", "email": "cliente@despacho.com", "name": "Cliente",
        "payment_method_id": "pm_xxx", "payment_method_type": "card",
        "currency": "MXN"}}},
    "/api/v2/batch": {"json": {"value": {
        "paths": ["/data/cfdi/1.xml", "/data/cfdi/2.xml"], "folder": "",
        "async": False, "webhook": True}}},
    "/api/v2/webhooks": {"json": {"value": {
        "url": "https://cliente.example.com/hooks/b2b",
        "events": ["invoice_processed", "batch_completed"]}}},
    "/api/v2/export": {"json": {"value": {
        "format": "csv", "scope": "invoices", "title": "Export", "periodo": None,
        "desde": None, "hasta": None, "limit": 1000}}},
    "/api/v2/tenants": {"json": {"value": {
        "config": {"erp_type": "aspel", "plantilla_contable": "SAT",
                   "notif_channel": "whatsapp", "policy_human_review": True}}}},
    "/api/v1/auth/login": {"json": {"value": {
        "email": "admin@despacho.com", "password": "secret", "tenant_id": 1}}},
    "/portal/auth/login": {"json": {"value": {
        "email": "cliente@despacho.com", "password": "secret", "tenant_id": None}}},
    "/portal/invoices/upload": {"multipart": {"summary": "Subida multipart (XML/PDF)",
        "value": {"file": "<archivo CFDI .xml o .pdf>"}}},
}
for path, op_examples in EXAMPLES.items():
    ops = spec["paths"].get(path)
    if not ops:
        continue
    for method in ("post", "get", "patch", "delete"):
        op = ops.get(method)
        if op:
            rb = op.get("requestBody") or {}
            content = rb.get("content", {})
            if content:
                for ctype in content:
                    content[ctype]["examples"] = op_examples
            break

SCHEMA_DOCS = {
    "ProcessRequest": "Cuerpo JSON para POST /api/v1/invoices/process (alternativa a multipart).",
    "LeadRequest": "Lead de la landing (público, sin API key).",
    "ReconcileRequest": "Datos para conciliación bancaria.",
    "PayrollRequest": "Datos para cálculo de nómina.",
    "BatchRequest": "Lote de CFDI para procesamiento masivo (≤1000).",
    "ExportRequest": "Parámetros de exportación CSV/XLSX/PDF.",
    "WebhookRegister": "Registro de suscripción de webhook por evento.",
    "EmailInbound": "Payload de email entrante (mock Mailgun/SendGrid).",
    "RegisterBody": "Alta de usuario (bootstrap del 1er admin o admin del tenant).",
    "LoginBody": "Login email+password.",
    "RefreshBody": "Refresh de tokens.",
}
schemas = components.setdefault("schemas", {})
for name, doc in SCHEMA_DOCS.items():
    if name in schemas:
        schemas[name]["description"] = doc

out = os.path.join(HERE, "..", "docs", "openapi.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(spec, f, indent=2, ensure_ascii=False)
json.load(open(out, encoding="utf-8"))  # validar
print(f"OK. {len(spec['paths'])} paths, {len(schemas)} schemas -> "
      f"{os.path.normpath(out)}")
