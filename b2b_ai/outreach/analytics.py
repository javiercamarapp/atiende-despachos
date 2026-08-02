# -*- coding: utf-8 -*-
"""
analytics.py — Métricas y análisis de campañas de outbound email.

Funciones de lectura sobre los datos que registra `sequences.OutreachManager`
(campañas, leads, correos y eventos de tracking) para responder preguntas de
negocio: ¿qué tan bien está rindiendo esta campaña?, ¿qué lead está más
caliente?, ¿a qué hora es mejor enviar?, ¿qué asunto abre más?

Todas las funciones aceptan un objeto `Database`; si es `None` devuelven
estructuras vacías/por defecto (modo lógico).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from b2b_ai.db.db import Database

# Peso de cada señal de engagement para el lead_score (suman 100).
_SCORE_WEIGHTS = {"open": 20, "click": 40, "reply": 40}

# Rango razonable de la ventana de análisis de mejor horario (días).
_DEFAULT_LOOKBACK_DAYS = 30


def campaign_stats(campaign_id: int, db: Optional[Database] = None) -> dict:
    """Métricas agregadas de una campaña.

    Devuelve total de leads, correos enviados, opens únicos y totales,
    open rate (correos abiertos / enviados), clicks únicos y totales,
    click-through rate, replies, unsubscribes y tasa de conversión a reply.
    """
    empty = {"campaign_id": campaign_id, "leads": 0, "emails_sent": 0,
             "opens": 0, "unique_opens": 0, "open_rate": 0.0,
             "clicks": 0, "unique_clickers": 0, "click_rate": 0.0,
             "replies": 0, "unsubscribes": 0, "reply_rate": 0.0}
    if db is None:
        return empty

    leads = db.list_outreach_leads(campaign_id=campaign_id)
    emails = db.list_outreach_emails(campaign_id=campaign_id)
    events = db.list_outreach_events(email_id=None)
    events = [e for e in events if e.get("email_id") in {em["id"] for em in emails}]

    unique_opens = {e["email_id"] for e in events
                    if e.get("event_type") == "open"}
    clickers = {e["lead_id"] for e in events
                if e.get("event_type") == "click"}
    opens_total = sum(1 for e in events if e.get("event_type") == "open")
    clicks_total = sum(1 for e in events if e.get("event_type") == "click")

    statuses = [l.get("status") for l in leads]
    replies = statuses.count("replied")
    unsubscribes = statuses.count("unsubscribed")

    sent = len(emails)
    return {
        "campaign_id": campaign_id,
        "leads": len(leads),
        "emails_sent": sent,
        "opens": opens_total,
        "unique_opens": len(unique_opens),
        "open_rate": round((len(unique_opens) / sent), 4) if sent else 0.0,
        "clicks": clicks_total,
        "unique_clickers": len(clickers),
        "click_rate": round((len(clickers) / sent), 4) if sent else 0.0,
        "replies": replies,
        "unsubscribes": unsubscribes,
        "reply_rate": round((replies / sent), 4) if sent else 0.0,
    }


def lead_score(lead_id: int, db: Optional[Database] = None) -> dict:
    """Puntaje de engagement (0-100) de un lead en función de sus eventos de
    tracking. Devuelve el score global y el desglose de señales."""
    base = {"lead_id": lead_id, "score": 0, "breakdown": {"open": 0,
            "click": 0, "reply": 0}}
    if db is None:
        return base

    emails = db.list_outreach_emails(lead_id=lead_id)
    events = db.list_outreach_events(lead_id=lead_id)
    lead = db.get_outreach_lead(lead_id)

    score = 0.0
    breakdown = {"open": 0, "click": 0, "reply": 0}
    if any(e.get("event_type") == "open" for e in events):
        breakdown["open"] = _SCORE_WEIGHTS["open"]
    if any(e.get("event_type") == "click" for e in events):
        breakdown["click"] = _SCORE_WEIGHTS["click"]
    if lead and lead.get("status") == "replied":
        breakdown["reply"] = _SCORE_WEIGHTS["reply"]
    score = sum(breakdown.values())

    return {"lead_id": lead_id, "score": score,
            "breakdown": breakdown, "emails_sent": len(emails)}


def best_send_time(tenant_id: int, db: Optional[Database] = None,
                   lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> dict:
    """Mejor horario de envío para un tenant según la hora del día en que se
    registran opens. Sin datos históricos devuelve una recomendación por
    defecto (mañana laboral)."""
    default = {"tenant_id": tenant_id, "best_hour": 9, "recommendation":
               "Enviar entre 08:00 y 10:00 (mañana laboral)",
               "basis": "default", "hourly": {}}
    if db is None:
        return default

    since = (datetime.utcnow() - timedelta(days=lookback_days))
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    campaigns = db.list_outreach_campaigns(tenant_id=tenant_id)
    campaign_ids = {c["id"] for c in campaigns}
    emails = []
    for cid in campaign_ids:
        emails.extend(db.list_outreach_emails(campaign_id=cid))
    email_ids = {e["id"] for e in emails}

    hourly: Dict[int, int] = {}
    for e in emails:
        sent_at = str(e.get("sent_at") or "")[:19]
        if sent_at < since_str or not sent_at:
            continue
        try:
            hour = datetime.strptime(sent_at, "%Y-%m-%d %H:%M:%S").hour
        except ValueError:
            continue
        # Solo contar horas de correos que tuvieron al menos un open.
        opened = any(ev.get("email_id") == e["id"]
                     for ev in db.list_outreach_events(
                         email_id=e["id"]) if ev.get("event_type") == "open")
        if opened:
            hourly[hour] = hourly.get(hour, 0) + 1

    if not hourly:
        return default
    best_hour = max(hourly.items(), key=lambda kv: kv[1])[0]
    return {"tenant_id": tenant_id, "best_hour": best_hour,
            "recommendation": f"Enviar alrededor de las {best_hour:02d}:00 "
                              "(hora con más opens)",
            "basis": "observed", "hourly": dict(sorted(hourly.items()))}


def subject_line_ab_test(campaign_id: int, db: Optional[Database] = None) -> dict:
    """Compara el rendimiento (open rate) por asunto dentro de una campaña,
    como si fuera un A/B test. Devuelve por asunto: enviados, opens únicos y
    open rate, y el asunto ganador. Si solo hay un asunto distinto, lo señala
    (sin A/B real no hay comparación válida)."""
    base = {"campaign_id": campaign_id, "winner": None, "subjects": {},
            "note": "sin datos"}
    if db is None:
        return base

    emails = db.list_outreach_emails(campaign_id=campaign_id)
    if not emails:
        return base

    groups: Dict[str, dict] = {}
    for em in emails:
        subj = em.get("subject") or "(sin asunto)"
        g = groups.setdefault(subj, {"sent": 0, "opened": set()})
        g["sent"] += 1
        events = db.list_outreach_events(email_id=em["id"])
        if any(ev.get("event_type") == "open" for ev in events):
            g["opened"].add(em["id"])

    subjects = {}
    for subj, g in groups.items():
        subjects[subj] = {
            "sent": g["sent"],
            "unique_opens": len(g["opened"]),
            "open_rate": round((len(g["opened"]) / g["sent"]), 4)
            if g["sent"] else 0.0,
        }

    if len(subjects) < 2:
        return {"campaign_id": campaign_id, "winner": None,
                "subjects": subjects,
                "note": "solo un asunto: sin A/B real para comparar"}

    winner = max(subjects.items(), key=lambda kv: kv[1]["open_rate"])[0]
    return {"campaign_id": campaign_id, "winner": winner,
            "subjects": subjects, "note": "ok"}
