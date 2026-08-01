# -*- coding: utf-8 -*-
"""
templates.py — Plantillas de notificación por tipo de evento.

Principio (de `06-plan-tecnico.md` / `04-leyes-fiscales.md`): tono profesional,
NUNCA firmar como contador, SIEMPRE incluir referencia legal + flag de revisión
humana cuando aplique.
"""
from __future__ import annotations

TEMPLATES = {
    "invoice_processed": {
        "subject": "Factura {folio} procesada y registrada",
        "body": (
            "Hola {nombre},\n\n"
            "La factura {folio} del proveedor {emisor} por ${monto} fue "
            "procesada, validada y registrada en el ERP.\n"
            "  - Categoría: {categoria}\n"
            "  - Clasificación: {razon}\n"
            "  - Folio fiscal: {uuid}\n"
            "{revision}"
            "\nEl agente prepara y valida; el profesional determina y firma. "
            "Revise antes de cualquier uso con efecto fiscal."
        ),
    },
    "invoice_parse_failed": {
        "subject": "⚠ No se pudo leer la factura {archivo}",
        "body": (
            "Hola {nombre},\n\n"
            "El agente no pudo leer el CFDI {archivo}.\n"
            "Error: {error}\n\n"
            "Se requiere revisión humana para recuperar el documento."
        ),
    },
    "invoice_rejected": {
        "subject": "⚠ Factura rechazada por validación: {archivo}",
        "body": (
            "Hola {nombre},\n\n"
            "La factura {archivo} no pasó la validación fiscal:\n"
            "{detalle}\n\n"
            "No se registró en el ERP. Se requiere revisión humana."
        ),
    },
    "invoice_review": {
        "subject": "🔎 Factura {folio} requiere revisión humana",
        "body": (
            "Hola {nombre},\n\n"
            "La factura {folio} de {emisor} por ${monto} fue marcada para "
            "revisión humana.\n"
            "  - Categoría propuesta: {categoria} (confianza {confianza})\n"
            "  - Fuente de clasificación: {fuente}\n"
            "  - Anomalías: {anomalias}\n\n"
            "El agente propone; usted decide. La decisión fiscal es humana."
        ),
    },
    "exception": {
        "subject": "⚠ Excepción en factura {folio}",
        "body": (
            "Hola {nombre},\n\n"
            "Se detectó una excepción en la factura {folio} ({emisor}):\n"
            "{detalle}\n"
            "\nSe requiere revisión humana antes de continuar."
        ),
    },
    "requires_approval": {
        "subject": "Aprobación requerida: factura {folio} por ${monto}",
        "body": (
            "Hola {nombre},\n\n"
            "La factura {folio} de {emisor} por ${monto} supera el umbral de "
            "aprobación y requiere su autorización.\n"
            "Ref. fiscal: {ref}\n"
            "Esta decisión es de carácter humano y no la toma el agente."
        ),
    },
    "reconciliation_discrepancy": {
        "subject": "Discrepancia de conciliación: {cantidad} movimiento(s)",
        "body": (
            "Hola {nombre},\n\n"
            "Hay {cantidad} movimiento(s) bancario(s) sin conciliar para el "
            "periodo {periodo}. Revise la cola de excepciones."
        ),
    },
    "report_ready": {
        "subject": "Reporte {periodo} listo",
        "body": (
            "Hola {nombre},\n\n"
            "El reporte del periodo {periodo} está listo.\n"
            "  - Facturas: {facturas}\n"
            "  - Total: ${total}\n"
            "\nLos agregados son informativos; la presentación fiscal requiere "
            "revisión humana."
        ),
    },
    # Resumen diario de actividad (FASE notificaciones).
    "daily_summary": {
        "subject": "Resumen diario {fecha}",
        "body": (
            "Hola {nombre},\n\n"
            "Resumen del día {fecha}:\n"
            "  - Facturas procesadas: {facturas}\n"
            "  - Monto total: ${monto_total}\n"
            "  - Pendientes de aprobación: {pendientes}\n"
            "  - Anomalías detectadas: {anomalias}\n"
            "\nLos agregados son informativos; la determinación fiscal es humana."
        ),
    },
    # Alerta de anomalía (FASE notificaciones).
    "anomaly_alert": {
        "subject": "⚠ Alerta de anomalía: {tipo}",
        "body": (
            "Hola {nombre},\n\n"
            "Se detectó una anomalía en {documento}:\n"
            "  - Tipo: {tipo}\n"
            "  - Detalle: {detalle}\n"
            "\nRequiere revisión humana antes de cualquier uso fiscal."
        ),
    },
}


def render(event_type, context, extra_subject=""):
    """Renderiza subject/body de la plantilla. Devuelve (subject, body)."""
    tpl = TEMPLATES.get(event_type)
    if not tpl:
        raise KeyError(f"Plantilla desconocida: {event_type}")
    ctx = dict(context)
    try:
        subject = tpl["subject"].format(**ctx)
        body = tpl["body"].format(**ctx)
    except KeyError as e:
        raise ValueError(f"Falta contexto para la plantilla {event_type}: {e}")
    if extra_subject:
        subject = f"{extra_subject} {subject}"
    return subject, body


# --------------------------------------------------------------------------- #
# Plantillas HTML (email) — cargadas desde ficheros en este directorio.
#
# Los placeholders se escriben como `{{nombre}}` y se sustituyen con el
# contexto. Se usa sustitución por `{{key}}` (no str.format) para que el CSS
# de los templates pueda usar llaves reales sin escaparlas.
# --------------------------------------------------------------------------- #
import os
import re as _re

_HTML_SUBJECTS = {
    "welcome": "Bienvenido a {nombre} — tu agente contable está activo",
    "invoice_processed": "Factura {folio} procesada y registrada",
    "approval_required": "Aprobación requerida: factura {folio} por ${monto}",
    "daily_summary": "Resumen diario {fecha}",
    "weekly_report": "Reporte semanal {periodo}",
    "anomaly_detected": "⚠ Alerta de anomalía: {tipo}",
    "subscription_renewal": "Tu suscripción {plan} se renueva el {fecha}",
}

_HTML_PLACEHOLDER = _re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def _template_dir():
    return os.path.dirname(os.path.abspath(__file__))


def html_template_path(template_name):
    """Ruta absoluta del fichero HTML de la plantilla (o None)."""
    path = os.path.join(_template_dir(), f"{template_name}.html")
    return path if os.path.isfile(path) else None


def html_subject(template_name, context):
    """Asunto del email para una plantilla HTML. Usa placeholders {x}."""
    tpl = _HTML_SUBJECTS.get(template_name)
    if not tpl:
        raise KeyError(f"Plantilla HTML desconocida: {template_name}")
    try:
        return tpl.format(**dict(context))
    except KeyError as e:
        raise ValueError(f"Falta contexto para la plantilla {template_name}: {e}")


def _fill_placeholders(text, context):
    """Sustituye {{key}} por los valores del contexto. Los que falten
    quedan como {{key}} visible (no silencioso) para detectarlos en QA."""
    ctx = dict(context)

    def _sub(m):
        key = m.group(1)
        if key not in ctx:
            raise ValueError(
                f"Falta contexto para la plantilla HTML: {key}")
        val = ctx[key]
        if val is None:
            val = ""
        return str(val)

    return _HTML_PLACEHOLDER.sub(_sub, text)


def render_html(template_name, context):
    """Renderiza una plantilla HTML. Devuelve (subject, html_body)."""
    path = html_template_path(template_name)
    if path is None:
        raise KeyError(f"Plantilla HTML desconocida: {template_name}")
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    return html_subject(template_name, context), _fill_placeholders(raw, context)
