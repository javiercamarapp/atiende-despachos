# -*- coding: utf-8 -*-
"""Outreach API: campañas automatizadas de outbound email."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class LeadCreate(BaseModel):
    name: str
    email: str
    company: str
    title: Optional[str] = ""
    phone: Optional[str] = ""
    linkedin: Optional[str] = ""
    notes: Optional[str] = ""


class CampaignCreate(BaseModel):
    name: str
    sequence_id: int = 1
    lead_ids: List[int]


class EmailSend(BaseModel):
    lead_id: int
    template: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


def build_outreach_router(
    require_api_key: Callable[..., Dict],
) -> APIRouter:
    """Build the outreach router with injected auth dependency."""
    router = APIRouter(prefix="/api/v1/outreach", tags=["outreach"])

    @router.post("/leads")
    def create_lead(
        lead: LeadCreate,
        auth_info: dict = Depends(require_api_key),
    ):
        """Crear un lead para outreach."""
        from b2b_ai.db.db import Database

        db = Database()
        tenant_id = auth_info.get("tenant_id", 0)
        # Ensure a default campaign exists for standalone leads
        campaign_id = db._ensure_outreach_standalone_campaign(tenant_id)
        # Split name into first/last for the DB schema
        parts = (lead.name or "").split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
        lead_id = db.add_outreach_lead(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            email=lead.email,
            first_name=first_name,
            last_name=last_name,
            company=lead.company or "",
            role=lead.title or "",
        )
        return {"id": lead_id, "status": "created"}

    @router.get("/leads")
    def list_leads(
        campaign_id: Optional[int] = None,
        status: Optional[str] = None,
        auth_info: dict = Depends(require_api_key),
    ):
        """Listar leads de outreach."""
        from b2b_ai.db.db import Database

        db = Database()
        leads = db.list_outreach_leads(campaign_id=campaign_id, status=status)
        return {"leads": leads, "total": len(leads)}

    @router.post("/campaigns")
    def launch_campaign(
        campaign: CampaignCreate,
        auth_info: dict = Depends(require_api_key),
    ):
        """Lanzar campaña de outreach."""
        from b2b_ai.db.db import Database
        from b2b_ai.outreach.sequences import OutreachManager

        db = Database()
        manager = OutreachManager(db=db)

        leads = []
        for lid in campaign.lead_ids:
            lead = db.get_outreach_lead(lid)
            if lead:
                leads.append(lead)

        if not leads:
            raise HTTPException(status_code=404, detail="No leads found")

        result = manager.launch_campaign(leads, sequence_id=campaign.sequence_id)
        return result

    @router.post("/campaigns/{campaign_id}/pause")
    def pause_campaign(
        campaign_id: int,
        auth_info: dict = Depends(require_api_key),
    ):
        """Pausar campaña."""
        from b2b_ai.db.db import Database
        from b2b_ai.outreach.sequences import OutreachManager

        db = Database()
        manager = OutreachManager(db=db)
        return manager.pause_campaign(campaign_id)

    @router.post("/campaigns/{campaign_id}/resume")
    def resume_campaign(
        campaign_id: int,
        auth_info: dict = Depends(require_api_key),
    ):
        """Reanudar campaña."""
        from b2b_ai.db.db import Database
        from b2b_ai.outreach.sequences import OutreachManager

        db = Database()
        manager = OutreachManager(db=db)
        return manager.resume_campaign(campaign_id)

    @router.post("/send")
    def send_email(
        email: EmailSend,
        auth_info: dict = Depends(require_api_key),
    ):
        """Enviar email individual."""
        from b2b_ai.db.db import Database
        from b2b_ai.outreach.sequences import OutreachManager

        db = Database()
        manager = OutreachManager(db=db)
        result = manager.send_email(
            lead_id=email.lead_id,
            template=email.template,
            subject=email.subject,
            body=email.body,
        )
        return result

    @router.post("/track/open")
    def track_open(
        lead_id: int,
        email_id: int,
        auth_info: dict = Depends(require_api_key),
    ):
        """Trackear apertura de email."""
        from b2b_ai.db.db import Database
        from b2b_ai.outreach.sequences import OutreachManager

        db = Database()
        manager = OutreachManager(db=db)
        return manager.track_open(lead_id, email_id)

    @router.post("/track/click")
    def track_click(
        lead_id: int,
        email_id: int,
        link_id: str,
        auth_info: dict = Depends(require_api_key),
    ):
        """Trackear click en link."""
        from b2b_ai.db.db import Database
        from b2b_ai.outreach.sequences import OutreachManager

        db = Database()
        manager = OutreachManager(db=db)
        return manager.track_click(lead_id, email_id, link_id)

    @router.get("/stats/{campaign_id}")
    def campaign_stats(
        campaign_id: int,
        auth_info: dict = Depends(require_api_key),
    ):
        """Estadísticas de campaña."""
        from b2b_ai.outreach.analytics import campaign_stats

        return campaign_stats(campaign_id)

    @router.get("/lead-score/{lead_id}")
    def lead_score(
        lead_id: int,
        auth_info: dict = Depends(require_api_key),
    ):
        """Score de un lead."""
        from b2b_ai.outreach.analytics import lead_score

        return lead_score(lead_id)

    return router
