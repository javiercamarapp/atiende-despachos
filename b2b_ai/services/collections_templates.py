# -*- coding: utf-8 -*-
"""
collections_templates.py — Plantillas en español (MX) para la cobranza.

Cada etapa de la secuencia de cobranza tiene una plantilla de correo (email)
y una de WhatsApp. El tono escala de amigable a formal-firme, terminando en
escalamiento a gerencia.

Etapas:
  - pre_vencimiento     : recordatorio amigable, 7 días antes del vencimiento.
  - vencimiento         : notificación de vencimiento, el día del vencimiento.
  - recordatorio_formal : primer recordatorio formal, 7 días después.
  - segundo_recordatorio: segundo recordatorio + aviso de escalamiento, 30 días.
  - escalamiento        : escalamiento a gerencia, 60 días después.

Variables disponibles en todas las plantillas:
  - {nombre_empresa}  : nombre del cliente deudor.
  - {monto}           : monto pendiente, ya formateado (p. ej. "$12,500.00 MXN").
  - {dias_vencido}    : días que lleva vencida la factura (entero).
  - {factura_id}      : identificador de la factura.
"""
from __future__ import annotations

from typing import Dict

# --------------------------------------------------------------------------- #
# Plantillas por etapa. Cada entrada define: label (etiqueta humana), tone
# (nivel de firmeza), email (subject + body) y whatsapp (texto).
# --------------------------------------------------------------------------- #
TEMPLATES: Dict[str, Dict] = {
    "pre_vencimiento": {
        "label": "Recordatorio amigable (7 días antes)",
        "tone": "amigable",
        "email": {
            "subject": "Recordatorio: factura {factura_id} vence en breve",
            "body": (
                "Hola {nombre_empresa},\n\n"
                "Solo queremos recordarte que la factura {factura_id} por "
                "{monto} tiene vencimiento próximamente. Si ya realizaste el "
                "pago, ignora este mensaje.\n\n"
                "Gracias por tu atención.\n"
                "Equipo de Administración"
            ),
        },
        "whatsapp": (
            "Hola {nombre_empresa}! 👋 Te recordamos amablemente que la factura "
            "{factura_id} por {monto} vence en breve. Si ya la pagaste, "
            "ignora este mensaje. ¡Gracias!"
        ),
    },
    "vencimiento": {
        "label": "Notificación de vencimiento (día 0)",
        "tone": "informativo",
        "email": {
            "subject": "La factura {factura_id} vence hoy",
            "body": (
                "Hola {nombre_empresa},\n\n"
                "Te informamos que la factura {factura_id} por {monto} vence "
                "el día de hoy. Te agradecemos realizar el pago a la brevedad "
                "para mantener tu cuenta al corriente.\n\n"
                "Quedamos a tu disposición para cualquier duda.\n"
                "Equipo de Administración"
            ),
        },
        "whatsapp": (
            "Hola {nombre_empresa}, la factura {factura_id} por {monto} vence "
            "hoy. Te pedimos amablemente realizar el pago a la brevedad. "
            "¡Gracias!"
        ),
    },
    "recordatorio_formal": {
        "label": "Primer recordatorio formal (7 días vencido)",
        "tone": "formal",
        "email": {
            "subject": "Recordatorio formal — factura {factura_id} vencida",
            "body": (
                "Estimado {nombre_empresa},\n\n"
                "La factura {factura_id} por {monto} presenta un atraso de "
                "{dias_vencido} días. Le solicitamos realizar el pago a la "
                "brevedad posible.\n\n"
                "Si ya fue cubierta, le pedimos compartirnos su comprobante de "
                "pago para actualizar su cuenta.\n\n"
                "Quedamos atentos.\n"
                "Departamento de Administración"
            ),
        },
        "whatsapp": (
            "Estimado {nombre_empresa}, le recordamos que la factura "
            "{factura_id} por {monto} presenta un atraso de {dias_vencido} "
            "días. Agradecemos su pago a la brevedad."
        ),
    },
    "segundo_recordatorio": {
        "label": "Segundo recordatorio + aviso de escalamiento (30 días)",
        "tone": "firme",
        "email": {
            "subject": "Aviso importante — factura {factura_id} con {dias_vencido} días de atraso",
            "body": (
                "Estimado {nombre_empresa},\n\n"
                "La factura {factura_id} por {monto} acumula {dias_vencido} días "
                "de atraso. Sin el pago o un acuerdo de liquidación a la "
                "brevedad, procederemos a escalar su cuenta a la gerencia y a "
                "nuestro departamento jurídico.\n\n"
                "Le invitamos a contactarnos para regularizar su situación "
                "antes de tomar esa medida.\n\n"
                "Departamento de Administración"
            ),
        },
        "whatsapp": (
            "Estimado {nombre_empresa}, la factura {factura_id} por {monto} "
            "acumula {dias_vencido} días de atraso. Sin pago o acuerdo, su "
            "cuenta será escalada a gerencia. Contáctenos para regularizarla."
        ),
    },
    "escalamiento": {
        "label": "Escalamiento a gerencia (60 días)",
        "tone": "formal-firme",
        "email": {
            "subject": "Escalamiento — factura {factura_id}, {dias_vencido} días vencidos",
            "body": (
                "Estimado {nombre_empresa},\n\n"
                "Debido a que la factura {factura_id} por {monto} lleva "
                "{dias_vencido} días sin liquidarse, su caso ha sido escalado "
                "a la gerencia. Esta es la última instancia administrativa "
                "antes de emprender acciones legales.\n\n"
                "Para evitar mayores consecuencias, le solicitamos ponerse en "
                "contacto inmediato con nuestra gerencia para acordar la "
                "liquidación.\n\n"
                "Gerencia de Cobranza"
            ),
        },
        "whatsapp": (
            "Estimado {nombre_empresa}, la factura {factura_id} por {monto} "
            "lleva {dias_vencido} días vencidos y su caso fue escalado a "
            "gerencia. Contáctenos de inmediato para acordar la liquidación "
            "antes de acciones legales."
        ),
    },
}

# Orden de la secuencia (para recorrer las etapas en el flujo de escalado).
SEQUENCE = ["pre_vencimiento", "vencimiento", "recordatorio_formal",
            "segundo_recordatorio", "escalamiento"]

# Offset en días respecto al vencimiento de cada etapa: negativo = antes del
# vencimiento, positivo = días de atraso.
STAGE_OFFSET_DAYS = {
    "pre_vencimiento": -7,
    "vencimiento": 0,
    "recordatorio_formal": 7,
    "segundo_recordatorio": 30,
    "escalamiento": 60,
}


def stages():
    """Devuelve la lista de etapas de la secuencia de cobranza."""
    return list(SEQUENCE)


def format_monto(monto) -> str:
    """Formatea un monto a '$12,500.00 MXN' para las plantillas."""
    try:
        v = float(monto)
    except (TypeError, ValueError):
        return str(monto)
    return "${:,.2f} MXN".format(v)


def render(stage: str, channel: str = "email", **variables) -> str:
    """Renderiza la plantilla de una etapa en el canal indicado.

    stage:     'pre_vencimiento' | 'vencimiento' | 'recordatorio_formal' |
               'segundo_recordatorio' | 'escalamiento'
    channel:   'email' o 'whatsapp'.
    variables: valores para {nombre_empresa}, {monto}, {dias_vencido},
               {factura_id}. Los que falten se sustituyen por '' (string vacío).

    Para email se devuelve el cuerpo del mensaje (usa `render_subject` para
    el asunto). Para WhatsApp se devuelve el texto directo.
    """
    tpl = TEMPLATES.get(stage)
    if tpl is None:
        raise KeyError(f"Etapa de cobranza desconocida: {stage!r}")

    if channel == "email":
        body = tpl["email"]["body"]
        return _fill(body, variables)
    if channel == "whatsapp":
        return _fill(tpl["whatsapp"], variables)
    raise ValueError(f"Canal desconocido: {channel!r} (usa 'email' o 'whatsapp')")


def render_subject(stage: str, **variables) -> str:
    """Renderiza el asunto de correo de una etapa (solo email)."""
    tpl = TEMPLATES.get(stage)
    if tpl is None:
        raise KeyError(f"Etapa de cobranza desconocida: {stage!r}")
    return _fill(tpl["email"]["subject"], variables)


def _fill(text: str, variables: dict) -> str:
    """Sustituye {vars} conocidas; las que falten quedan en blanco."""
    def _repl(m):
        key = m.group(1)
        val = variables.get(key, "")
        return str(val) if val is not None else ""
    import re
    return re.sub(r"\{([a-z_0-9]+)\}", _repl, text)
