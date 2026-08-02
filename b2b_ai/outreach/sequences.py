# -*- coding: utf-8 -*-
"""
sequences.py — Orquestador de campañas de outbound emails (adquisición).

Gestiona el ciclo de vida de una campaña de correos en frío: crea la campaña,
carga los leads, envía el paso de la secuencia que toca (5 plantillas de
cold outreach), registra opens/clicks para tracking y avanza el followup
automático cuando es momento.

Sigue la convención del proyecto (ver services.collections): **NO envía
mensajes reales** — renderiza el contenido a partir de la plantilla HTML,
lo persiste en `outreach_emails` y devuelve el cuerpo + asunto listos para
que el canal de envío (SMTP / proveedor de email) los despache. El tracking
se resuelve con URLs de píxel y redirect que el despliegue debe exponer.

Forma de uso:

    from b2b_ai.outreach.sequences import OutreachManager

    mgr = OutreachManager(db=db, tenant_id=1,
                          sender_email="ventas@b2b-ai.example",
                          sender_first_name="Ana", sender_company="Likida AI Enterprise")
    camp = mgr.launch_campaign(leads=[{"email": "a@firm.com",
                                       "first_name": "Luis", "company": "Firma X"}],
                               sequence_id=1, name="Cold Q3")
    email = mgr.send_email(camp["leads"][0]["id"])       # paso 1
    mgr.track_open(email["lead_id"], email["id"])         # píxel de open
    mgr.track_click(email["lead_id"], "cta_1")            # redirect de click
    email2 = mgr.auto_followup(email["lead_id"])          # siguiente paso
    mgr.pause_campaign(camp["id"])                        # pausar todo
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from b2b_ai.db.db import Database

# --------------------------------------------------------------------------- #
# Definición de la secuencia de cold outreach
# --------------------------------------------------------------------------- #
# Paso de la secuencia -> plantilla HTML (b2b_ai/outreach/templates/).
SEQUENCE_TEMPLATES: Dict[int, str] = {
    1: "cold_outreach_1.html",   # introducción
    2: "cold_outreach_2.html",   # value prop
    3: "cold_outreach_3.html",   # case study
    4: "cold_outreach_4.html",   # demo offer
    5: "cold_outreach_5.html",   # last chance
}
SEQUENCE_LENGTH = len(SEQUENCE_TEMPLATES)

# Asuntos por paso (acepta los mismos placeholders que el cuerpo).
SEQUENCE_SUBJECTS: Dict[int, str] = {
    1: "Likida AI Enterprise — automatización contable para {company}",
    2: "Re: cómo ahorrar horas en captura de facturas",
    3: "Caso real: {industry} automatizó su contabilidad",
    4: "Demo de 20 minutos, sin compromiso",
    5: "Último mensaje: la puerta queda abierta",
}

# Días que deben pasar desde el envío anterior antes de avanzar de paso.
FOLLOWUP_DAY_OFFSETS: Dict[int, int] = {1: 0, 2: 2, 3: 4, 4: 6, 5: 10}

# Placeholders que se sustituyen en cuerpo y asunto. NO se usa str.format
# porque el HTML de las plantillas contiene llaves de CSS ({...}) que
# romperían el render; se hace reemplazo secuencial por clave.
_PLACEHOLDERS = (
    "first_name", "last_name", "company", "role", "industry",
    "sender_email", "sender_company", "sender_first_name",
    "email_id", "tracking_open_url", "tracking_click_base",
)

# Estados de lead que detienen el envío de más pasos.
_TERMINAL_STATUSES = {"replied", "unsubscribed", "bounced", "completed"}


def default_tracking_base() -> str:
    """Base URL del endpoint de tracking (env B2B_TRACKING_BASE)."""
    return (os.environ.get("B2B_TRACKING_BASE")
            or "https://track.b2b-ai.example")


def render_template(html: str, context: Dict[str, object]) -> str:
    """Sustituye {placeholders} en `html` usando `context`. Reemplazo
    secuencial (a prueba de llaves de CSS) y tolerante a claves ausentes
    (las deja tal cual para que no reviente el render)."""
    out = html
    for key in _PLACEHOLDERS:
        val = context.get(key)
        if val is None:
            continue
        out = out.replace("{%s}" % key, str(val))
    return out


def render_subject(template: str, context: Dict[str, object]) -> str:
    """Igual que render_template pero para asuntos (texto plano)."""
    out = template
    for key in _PLACEHOLDERS:
        val = context.get(key)
        if val is None:
            continue
        out = out.replace("{%s}" % key, str(val))
    return out


class OutreachManager:
    """Orquesta campañas de outbound email. `db` es opcional; sin él las
    llamadas de persistencia son no-op (modo lógico). `tenant_id` obligatorio
    para operar sobre datos multi-tenant."""

    def __init__(self, db: Optional[Database] = None, tenant_id: Optional[int] = None,
                 sender_email: str = "", sender_first_name: str = "",
                 sender_company: str = "Likida AI Enterprise", reply_to: Optional[str] = None,
                 tracking_base: Optional[str] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.sender_email = sender_email
        self.sender_first_name = sender_first_name
        self.sender_company = sender_company
        self.reply_to = reply_to
        self.tracking_base = tracking_base or default_tracking_base()

    # ---- Soporte de plantillas ----------------------------------------
    @staticmethod
    def _template_path(template: str) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates", template)

    def _read_template_file(self, filename: str) -> str:
        with open(self._template_path(filename), "r", encoding="utf-8") as fh:
            return fh.read()

    def _read_template(self, stage: int) -> str:
        tpl = SEQUENCE_TEMPLATES.get(stage)
        if not tpl:
            raise ValueError(f"secuencia inválida: no hay plantilla para el paso {stage}")
        return self._read_template_file(tpl)

    def _context(self, lead: dict, email_id: int) -> Dict[str, object]:
        return {
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company": lead.get("company", ""),
            "role": lead.get("role", ""),
            "industry": lead.get("industry", ""),
            "sender_email": self.sender_email,
            "sender_company": self.sender_company,
            "sender_first_name": self.sender_first_name,
            "email_id": email_id,
            "tracking_open_url": f"{self.tracking_base}/track/open?email_id={email_id}",
            "tracking_click_base": f"{self.tracking_base}/track/click",
        }

    # ---- Ciclo de vida de campaña -------------------------------------
    def launch_campaign(self, leads: List[dict], sequence_id: int = 1,
                        name: str = None) -> dict:
        """Crea una campaña y carga sus leads. `leads` es una lista de dicts
        con `email` (obligatorio) y `first_name`, `last_name`, `company`,
        `role`, `industry` (opcionales). Devuelve el dict de la campaña con
        la lista de leads asociados."""
        if self.tenant_id is None:
            raise ValueError("tenant_id es obligatorio para lanzar campañas")
        if not leads:
            raise ValueError("la campaña necesita al menos un lead")
        for i, lead in enumerate(leads):
            if not lead.get("email"):
                raise ValueError(f"lead #{i} sin email")

        name = name or f"Cold outreach #{sequence_id} {datetime.utcnow():%Y-%m-%d}"
        if self.db is not None:
            campaign_id = self.db.create_outreach_campaign(
                self.tenant_id, name, sequence_id=sequence_id,
                sender_email=self.sender_email, reply_to=self.reply_to)
            lead_ids = []
            for lead in leads:
                lid = self.db.add_outreach_lead(
                    campaign_id, self.tenant_id, lead["email"],
                    first_name=lead.get("first_name", ""),
                    last_name=lead.get("last_name", ""),
                    company=lead.get("company", ""),
                    role=lead.get("role", ""),
                    industry=lead.get("industry", ""))
                lead_ids.append(lid)
        else:
            campaign_id = None
            lead_ids = list(range(len(leads)))

        return {
            "id": campaign_id,
            "tenant_id": self.tenant_id,
            "name": name,
            "sequence_id": sequence_id,
            "status": "active",
            "leads": [{"id": lid, **leads[i]} for i, lid in enumerate(lead_ids)],
        }

    def pause_campaign(self, campaign_id: int) -> dict:
        """Pausa una campaña: detiene el envío de pasos nuevos (send_email
        y auto_followup se niegan). Devuelve la campaña actualizada."""
        if self.db is not None:
            self.db.set_outreach_campaign_status(campaign_id, "paused", paused=True)
            campaign = self.db.get_outreach_campaign(campaign_id)
        else:
            campaign = {"id": campaign_id, "status": "paused"}
        return campaign

    def resume_campaign(self, campaign_id: int) -> dict:
        """Reanuda una campaña pausada. Devuelve la campaña actualizada."""
        if self.db is not None:
            self.db.set_outreach_campaign_status(campaign_id, "active", paused=False)
            campaign = self.db.get_outreach_campaign(campaign_id)
        else:
            campaign = {"id": campaign_id, "status": "active"}
        return campaign

    def _campaign_active(self, campaign_id: int) -> bool:
        if self.db is None:
            return True
        camp = self.db.get_outreach_campaign(campaign_id)
        return bool(camp and camp.get("status") == "active")

    # ---- Envío ---------------------------------------------------------
    def send_email(self, lead_id: int, template: Optional[str] = None,
                   subject: Optional[str] = None, stage: Optional[int] = None,
                   campaign_id: Optional[int] = None) -> dict:
        """Renderiza y registra el envío del paso de la secuencia para un lead.

        - `stage`/`template` opcionales: por defecto usa el paso actual del
          lead (lead['stage']). Si se pasa `template` (nombre de archivo) se
          usa esa plantilla.
        - No envía si la campaña está pausada, si el lead llegó a un estado
          terminal (replied/unsubscribed/bounced/completed) o si ya alcanzó
          el paso 5.
        Devuelve el dict del correo con `body`, `subject`, `id`, `lead_id`,
        `campaign_id`, `stage`.
        """
        lead = self._get_lead(lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} no existe")

        if lead.get("status") in _TERMINAL_STATUSES:
            return {"skipped": True, "reason": f"status={lead['status']}"}

        current_stage = lead.get("stage") or 1
        if current_stage > SEQUENCE_LENGTH:
            return {"skipped": True, "reason": "secuencia completada"}

        cid = campaign_id or lead.get("campaign_id")
        if cid and not self._campaign_active(cid):
            return {"skipped": True, "reason": "campaña pausada"}

        use_stage = stage or current_stage
        if template is None:
            tpl_name = SEQUENCE_TEMPLATES[use_stage]
        else:
            tpl_name = template
            use_stage = stage or _template_stage_for(template)
        html = self._read_template_file(tpl_name)

        # Registramos el correo para tener un email_id (necesario para el
        # tracking), luego renderizamos con ese id.
        subj_tpl = subject or SEQUENCE_SUBJECTS.get(use_stage, "")

        if self.db is not None:
            email_id = self.db.add_outreach_email(
                cid, lead_id, self.tenant_id or lead.get("tenant_id"),
                tpl_name, subj_tpl, html)
            rendered = render_template(html, self._context(lead, email_id))
            rendered_subject = render_subject(subj_tpl, self._context(lead, email_id))
            self.db.update_outreach_lead(
                lead_id, emails_sent=(lead.get("emails_sent") or 0) + 1,
                status="active")
        else:
            email_id = None
            rendered = render_template(html, self._context(lead, 0))
            rendered_subject = render_subject(subj_tpl, self._context(lead, 0))

        return {
            "id": email_id,
            "lead_id": lead_id,
            "campaign_id": cid,
            "template": tpl_name,
            "stage": use_stage,
            "subject": rendered_subject,
            "body": rendered,
        }

    # ---- Tracking ------------------------------------------------------
    def track_open(self, lead_id: int, email_id: int) -> dict:
        """Registra un open (píxel). Actualiza contadores del correo y guarda
        el evento. Devuelve el correo actualizado."""
        if self.db is not None:
            self.db.mark_outreach_email_opened(email_id)
            self.db.add_outreach_event(self.tenant_id, email_id, lead_id, "open")
            return self.db.get_outreach_email(email_id) or {}
        return {"email_id": email_id, "lead_id": lead_id, "opened_count": 1}

    def track_click(self, lead_id: int, link_id: str,
                    email_id: Optional[int] = None) -> dict:
        """Registra un click (redirect). Si `link_id == 'unsubscribe'`, marca
        el lead como `unsubscribed` (detiene envíos futuros). Devuelve el
        evento registrado."""
        if email_id is None and self.db is not None:
            emails = self.db.list_outreach_emails(lead_id=lead_id, limit=1)
            email_id = emails[-1]["id"] if emails else None

        if self.db is not None:
            event_id = self.db.add_outreach_event(
                self.tenant_id, email_id, lead_id, "click", link_id=link_id)
            if email_id is not None:
                self.db.mark_outreach_email_clicked(email_id)
            if link_id == "unsubscribe":
                self.db.update_outreach_lead(lead_id, status="unsubscribed")
        else:
            event_id = None
            if link_id == "unsubscribe":
                pass  # sin db no hay estado que actualizar

        return {"event_id": event_id, "lead_id": lead_id, "link_id": link_id,
                "email_id": email_id, "event_type": "click"}

    # ---- Followup automático -------------------------------------------
    def auto_followup(self, lead_id: int) -> dict:
        """Avanza el lead al siguiente paso de la secuencia SI han pasado los
        días configurados desde el último envío y el lead sigue activo.
        Devuelve el dict de send_email, o un dict `skipped` si aún no toca o
        ya no puede avanzar."""
        lead = self._get_lead(lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} no existe")
        if lead.get("status") in _TERMINAL_STATUSES:
            return {"skipped": True, "reason": f"status={lead['status']}"}
        if lead.get("campaign_id") and not self._campaign_active(lead["campaign_id"]):
            return {"skipped": True, "reason": "campaña pausada"}

        stage = lead.get("stage") or 1
        if stage >= SEQUENCE_LENGTH:
            if self.db is not None:
                self.db.update_outreach_lead(lead_id, status="completed")
            return {"skipped": True, "reason": "secuencia completada"}

        emails = (self.db.list_outreach_emails(lead_id=lead_id, limit=1)
                  if self.db is not None else [])
        last_sent = emails[-1].get("sent_at") if emails else None
        if last_sent is None:
            # Nunca se envió el primer paso: hay que enviarlo.
            return self.send_email(lead_id)

        # Comparar fechas de SQLite (TEXT 'YYYY-MM-DD HH:MM:SS').
        try:
            last_dt = datetime.strptime(str(last_sent)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return {"skipped": True, "reason": "fecha de envío ilegible"}

        days_needed = FOLLOWUP_DAY_OFFSETS.get(stage + 1, 2)
        next_due = last_dt + timedelta(days=days_needed)
        if datetime.utcnow() < next_due:
            return {"skipped": True, "reason": "aún no toca el siguiente paso",
                    "next_due": next_due.isoformat()}

        next_stage = stage + 1
        if self.db is not None:
            self.db.update_outreach_lead(lead_id, stage=next_stage)
        return self.send_email(lead_id)

    # ---- Utilidades -----------------------------------------------------
    def _get_lead(self, lead_id: int) -> Optional[dict]:
        if self.db is None:
            return {"id": lead_id, "stage": 1, "status": "active",
                    "campaign_id": None, "tenant_id": self.tenant_id}
        return self.db.get_outreach_lead(lead_id)

    def leads_in_campaign(self, campaign_id: int) -> list:
        """Leads de una campaña (para auditoría / dashboards)."""
        if self.db is None:
            return []
        return self.db.list_outreach_leads(campaign_id=campaign_id)


def _template_stage_for(template: str) -> int:
    """Devuelve el paso de la secuencia al que pertenece un nombre de
    plantilla (cold_outreach_N.html -> N)."""
    for stage, name in SEQUENCE_TEMPLATES.items():
        if name == template:
            return stage
    return 1
