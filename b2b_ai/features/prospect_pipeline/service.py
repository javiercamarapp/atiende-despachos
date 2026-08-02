# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo de Pipeline de Prospectos/Leads.

Clases:
  - PipelineManager    : alta, actualización, movimiento entre etapas, listado
                         con filtros y detalle de leads.
  - LeadScoring        : scoring automático 0-100 basado en tamaño de empresa,
                         presupuesto y plazo de compra.
  - ActivityTracker    : registro de actividades, timeline y próximas acciones.
  - ProposalManager    : creación, envío y aceptación/rechazo de propuestas.
  - PipelineAnalytics  : tasas de conversión, tiempo promedio en etapa y win rate.

Almacenamiento: en memoria (dict) con `_reset_state()` para tests, coherente
con el patrón de ap_ar / nomina / monthly_close. Todos los registros llevan
`tenant_id`; todas las operaciones filtran por tenant para garantizar el
aislamiento multi-tenant.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.prospect_pipeline.models import (
    Activity,
    ActivityCreate,
    Lead,
    LeadCreate,
    LeadSource,
    LeadStatus,
    PipelineStage,
    PipelineStageCreate,
    Proposal,
    ProposalCreate,
    ProposalStatus,
)


# ---------------------------------------------------------------------------
# Store en memoria (patrón ap_ar / nomina / monthly_close)
# ---------------------------------------------------------------------------

_leads: Dict[str, Lead] = {}
_stages: Dict[str, PipelineStage] = {}
_activities: Dict[str, Activity] = {}
_proposals: Dict[str, Proposal] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _leads.clear()
    _stages.clear()
    _activities.clear()
    _proposals.clear()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_date(value: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Etapas por defecto (se crean on-demand por tenant)
# ---------------------------------------------------------------------------

_DEFAULT_STAGES = [
    ("Nuevo", 0, "#64748b", False, False),
    ("Contactado", 1, "#3b82f6", False, False),
    ("Calificado", 2, "#8b5cf6", False, False),
    ("Propuesta", 3, "#f59e0b", False, False),
    ("Negociación", 4, "#ef4444", False, False),
    ("Ganado", 5, "#22c55e", True, False),
    ("Perdido", 6, "#6b7280", False, True),
]


# ---------------------------------------------------------------------------
# LeadScoring
# ---------------------------------------------------------------------------

class LeadScoring:
    """Scoring automático 0-100 de un lead según señales comerciales.

    Rúbrica:
      - Tamaño de empresa  : 0-35 pts (empresas más grandes → más valor).
      - Presupuesto        : 0-40 pts (>= 50k MXN es el techo).
      - Plazo de compra    : 0-25 pts (más corto → más valor).
    """

    COMPANY_SIZE_POINTS = {
        "1-10": 10,
        "11-50": 20,
        "51-200": 30,
        "201+": 35,
    }

    TIMELINE_POINTS = {
        "0-3 meses": 25,
        "3-6 meses": 18,
        "6-12 meses": 10,
        "12+ meses": 5,
    }

    def calculate_score(
        self,
        company_size: str = "",
        budget: Optional[float] = None,
        timeline: str = "",
    ) -> int:
        """Calcula el score 0-100 para un lead."""
        size_pts = self.COMPANY_SIZE_POINTS.get((company_size or "").strip(), 0)

        if budget is not None and budget > 0:
            budget_pts = min(40, int(budget / 1000))  # 1k MXN ≈ 1 pt, techo 40
        else:
            budget_pts = 0

        timeline_pts = self.TIMELINE_POINTS.get((timeline or "").strip(), 0)

        return max(0, min(100, size_pts + budget_pts + timeline_pts))


# ---------------------------------------------------------------------------
# PipelineManager
# ---------------------------------------------------------------------------

class PipelineManager:
    """Gestión del pipeline de leads (CRUD + movimiento entre etapas)."""

    def __init__(self, scoring: Optional[LeadScoring] = None, db: Any = None):
        self.db = db
        self.scoring = scoring or LeadScoring()

    # -- Etapas ----------------------------------------------------------
    def _ensure_stages(self, tenant_id: str) -> List[PipelineStage]:
        """Crea las etapas por defecto del tenant la primera vez."""
        existing = [s for s in _stages.values() if s.tenant_id == tenant_id]
        if existing:
            return sorted(existing, key=lambda s: s.order)
        created = []
        for name, order, color, is_won, is_lost in _DEFAULT_STAGES:
            stage = PipelineStage(
                tenant_id=tenant_id,
                name=name,
                order=order,
                color=color,
                is_won=is_won,
                is_lost=is_lost,
            )
            _stages[stage.id] = stage
            created.append(stage)
        return created

    def list_stages(self, tenant_id: str) -> List[PipelineStage]:
        return sorted(self._ensure_stages(tenant_id), key=lambda s: s.order)

    def add_stage(self, tenant_id: str, req: PipelineStageCreate) -> PipelineStage:
        if not (req.name or "").strip():
            raise ValueError("name no puede estar vacío")
        self._ensure_stages(tenant_id)
        stage = PipelineStage(
            tenant_id=tenant_id,
            name=req.name.strip(),
            order=req.order,
            color=req.color,
            is_won=req.is_won,
            is_lost=req.is_lost,
        )
        _stages[stage.id] = stage
        return stage

    # -- Leads -----------------------------------------------------------
    def create_lead(self, tenant_id: str, req: LeadCreate) -> Lead:
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        if not (req.company_name or "").strip():
            raise ValueError("company_name es obligatorio")
        self._ensure_stages(tenant_id)
        score = self.scoring.calculate_score(
            company_size=req.company_size,
            budget=req.budget,
            timeline=req.timeline,
        )
        lead = Lead(
            tenant_id=str(tenant_id),
            company_name=req.company_name.strip(),
            contact_name=req.contact_name,
            contact_email=req.contact_email,
            contact_phone=req.contact_phone,
            source=req.source,
            company_size=req.company_size,
            budget=req.budget,
            timeline=req.timeline,
            notes=req.notes,
            score=score,
        )
        _leads[lead.id] = lead
        return lead

    def _get(self, tenant_id: str, lead_id: str) -> Lead:
        lead = _leads.get(lead_id)
        if lead is None or str(lead.tenant_id) != str(tenant_id):
            raise KeyError(f"Lead {lead_id} no encontrado")
        return lead

    def get_lead(self, tenant_id: str, lead_id: str) -> Lead:
        return self._get(tenant_id, lead_id)

    def update_lead(
        self,
        tenant_id: str,
        lead_id: str,
        *,
        company_name: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        source: Optional[LeadSource] = None,
        company_size: Optional[str] = None,
        budget: Optional[float] = None,
        timeline: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Lead:
        lead = self._get(tenant_id, lead_id)
        if company_name is not None:
            if not str(company_name).strip():
                raise ValueError("company_name no puede estar vacío")
            lead.company_name = company_name.strip()
        if contact_name is not None:
            lead.contact_name = contact_name
        if contact_email is not None:
            lead.contact_email = contact_email
        if contact_phone is not None:
            lead.contact_phone = contact_phone
        if source is not None:
            lead.source = source
        if company_size is not None:
            lead.company_size = company_size
        if budget is not None:
            lead.budget = budget
        if timeline is not None:
            lead.timeline = timeline
        if notes is not None:
            lead.notes = notes
        # Recalcular score con las señales vigentes.
        lead.score = self.scoring.calculate_score(
            company_size=lead.company_size,
            budget=lead.budget,
            timeline=lead.timeline,
        )
        lead.updated_at = _utcnow()
        _leads[lead.id] = lead
        return lead

    def move_stage(self, tenant_id: str, lead_id: str, status: LeadStatus) -> Lead:
        """Mueve un lead a una etapa por su estado (LeadStatus)."""
        lead = self._get(tenant_id, lead_id)
        if not isinstance(status, LeadStatus):
            status = LeadStatus(status)
        lead.status = status
        lead.updated_at = _utcnow()
        _leads[lead.id] = lead
        return lead

    def move_to_stage(self, tenant_id: str, lead_id: str, stage_id: str) -> Lead:
        """Mueve un lead a una etapa por el id de la PipelineStage."""
        self._ensure_stages(tenant_id)
        stage = _stages.get(stage_id)
        if stage is None or str(stage.tenant_id) != str(tenant_id):
            raise KeyError(f"Stage {stage_id} no encontrado")
        mapping = {
            "Nuevo": LeadStatus.NEW,
            "Contactado": LeadStatus.CONTACTED,
            "Calificado": LeadStatus.QUALIFIED,
            "Propuesta": LeadStatus.PROPOSAL,
            "Negociación": LeadStatus.NEGOTIATION,
            "Ganado": LeadStatus.WON,
            "Perdido": LeadStatus.LOST,
        }
        status = mapping.get(stage.name, LeadStatus.NEW)
        return self.move_stage(tenant_id, lead_id, status)

    def list_leads(
        self,
        tenant_id: str,
        *,
        stage: Optional[LeadStatus] = None,
        score_min: Optional[int] = None,
        score_max: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        source: Optional[LeadSource] = None,
    ) -> List[Lead]:
        """Lista leads del tenant con filtros (etapa, score, rango de fecha)."""
        self._ensure_stages(tenant_id)
        from_d = _parse_date(date_from) if date_from else None
        to_d = _parse_date(date_to) if date_to else None

        result = []
        for lead in _leads.values():
            if str(lead.tenant_id) != str(tenant_id):
                continue
            if stage is not None and lead.status != stage:
                continue
            if source is not None and lead.source != source:
                continue
            if score_min is not None and lead.score < score_min:
                continue
            if score_max is not None and lead.score > score_max:
                continue
            if from_d is not None and lead.created_at.date() < from_d:
                continue
            if to_d is not None and lead.created_at.date() > to_d:
                continue
            result.append(lead)
        return sorted(result, key=lambda l: l.created_at, reverse=True)

    def get_lead_details(self, tenant_id: str, lead_id: str) -> Dict[str, Any]:
        """Detalle completo de un lead: lead + actividades + propuestas."""
        lead = self._get(tenant_id, lead_id)
        return {
            "lead": lead.to_dict(),
            "activities": [
                a.to_dict()
                for a in _activities.values()
                if a.lead_id == lead_id and str(a.tenant_id) == str(tenant_id)
            ],
            "proposals": [
                p.to_dict()
                for p in _proposals.values()
                if p.lead_id == lead_id and str(p.tenant_id) == str(tenant_id)
            ],
        }


# ---------------------------------------------------------------------------
# ActivityTracker
# ---------------------------------------------------------------------------

class ActivityTracker:
    """Registro de actividades, timeline y próximas acciones de un lead."""

    def log_activity(
        self,
        tenant_id: str,
        lead_id: str,
        req: ActivityCreate,
    ) -> Activity:
        # El lead debe pertenecer al tenant (aislamiento).
        lead = _leads.get(lead_id)
        if lead is None or str(lead.tenant_id) != str(tenant_id):
            raise KeyError(f"Lead {lead_id} no encontrado")
        activity = Activity(
            lead_id=lead_id,
            tenant_id=str(tenant_id),
            activity_type=req.activity_type,
            description=req.description,
            outcome=req.outcome,
            next_action=req.next_action,
            next_action_date=req.next_action_date,
            created_by=req.created_by,
        )
        _activities[activity.id] = activity
        return activity

    def get_timeline(self, tenant_id: str, lead_id: str) -> List[Activity]:
        """Timeline de actividades de un lead (más recientes primero)."""
        if lead_id not in _leads:
            raise KeyError(f"Lead {lead_id} no encontrado")
        result = [
            a for a in _activities.values()
            if a.lead_id == lead_id and str(a.tenant_id) == str(tenant_id)
        ]
        return sorted(result, key=lambda a: a.created_at, reverse=True)

    def get_next_actions(self, tenant_id: str) -> List[Activity]:
        """Actividades pendientes con próxima acción definida (todos los leads del tenant)."""
        today = date.today()
        result = []
        for a in _activities.values():
            if str(a.tenant_id) != str(tenant_id):
                continue
            if not a.next_action.strip():
                continue
            nd = _parse_date(a.next_action_date) if a.next_action_date else None
            if nd is not None and nd < today:
                continue  # vencida / sin fecha definida no es "próxima acción"
            result.append(a)
        return sorted(
            result,
            key=lambda a: (_parse_date(a.next_action_date) or date.max, a.created_at),
        )


# ---------------------------------------------------------------------------
# ProposalManager
# ---------------------------------------------------------------------------

class ProposalManager:
    """Creación, envío y aceptación/rechazo de propuestas."""

    def create_proposal(
        self,
        tenant_id: str,
        lead_id: str,
        req: ProposalCreate,
    ) -> Proposal:
        lead = _leads.get(lead_id)
        if lead is None or str(lead.tenant_id) != str(tenant_id):
            raise KeyError(f"Lead {lead_id} no encontrado")
        proposal = Proposal(
            lead_id=lead_id,
            tenant_id=str(tenant_id),
            amount=req.amount,
            currency=req.currency or "MXN",
            valid_until=req.valid_until,
            content=req.content,
        )
        _proposals[proposal.id] = proposal
        return proposal

    def _get(self, tenant_id: str, proposal_id: str) -> Proposal:
        prop = _proposals.get(proposal_id)
        if prop is None or str(prop.tenant_id) != str(tenant_id):
            raise KeyError(f"Proposal {proposal_id} no encontrado")
        return prop

    def get_proposal(self, tenant_id: str, proposal_id: str) -> Proposal:
        return self._get(tenant_id, proposal_id)

    def send_proposal(self, tenant_id: str, proposal_id: str) -> Proposal:
        prop = self._get(tenant_id, proposal_id)
        if prop.status != ProposalStatus.DRAFT:
            raise ValueError(f"Solo propuestas DRAFT pueden enviarse (estado: {prop.status.value})")
        prop.status = ProposalStatus.SENT
        _proposals[prop.id] = prop
        return prop

    def accept_proposal(self, tenant_id: str, proposal_id: str) -> Proposal:
        prop = self._get(tenant_id, proposal_id)
        if prop.status != ProposalStatus.SENT:
            raise ValueError(f"Solo propuestas SENT pueden aceptarse (estado: {prop.status.value})")
        prop.status = ProposalStatus.ACCEPTED
        _proposals[prop.id] = prop
        # Al aceptar, el lead pasa a NEGOTIATION/WON según corresponda.
        lead = _leads.get(prop.lead_id)
        if lead is not None and str(lead.tenant_id) == str(tenant_id):
            lead.status = LeadStatus.NEGOTIATION
            lead.updated_at = _utcnow()
            _leads[lead.id] = lead
        return prop

    def reject_proposal(self, tenant_id: str, proposal_id: str) -> Proposal:
        prop = self._get(tenant_id, proposal_id)
        if prop.status not in (ProposalStatus.SENT, ProposalStatus.DRAFT):
            raise ValueError(f"Propuesta en estado {prop.status.value} no puede rechazarse")
        prop.status = ProposalStatus.REJECTED
        _proposals[prop.id] = prop
        return prop


# ---------------------------------------------------------------------------
# PipelineAnalytics
# ---------------------------------------------------------------------------

class PipelineAnalytics:
    """Métricas del pipeline de un tenant."""

    def conversion_rates(self, tenant_id: str) -> Dict[str, float]:
        """Tasa de conversión por etapa (proporción de leads en cada etapa)."""
        leads = [l for l in _leads.values() if str(l.tenant_id) == str(tenant_id)]
        total = len(leads)
        if total == 0:
            return {}
        rates = {}
        for status in LeadStatus:
            n = sum(1 for l in leads if l.status == status)
            rates[status.value] = round(n / total, 4)
        return rates

    def average_time_in_stage(self, tenant_id: str) -> Dict[str, float]:
        """Días promedio en cada etapa (aproximación por antigüedad del lead)."""
        leads = [l for l in _leads.values() if str(l.tenant_id) == str(tenant_id)]
        buckets: Dict[str, List[float]] = {}
        for lead in leads:
            days = (datetime.utcnow() - lead.created_at).total_seconds() / 86400.0
            buckets.setdefault(lead.status.value, []).append(days)
        out = {}
        for status, days in buckets.items():
            out[status] = round(sum(days) / len(days), 2)
        return out

    def win_rate(self, tenant_id: str) -> Dict[str, Any]:
        """Tasa de cierre ganado sobre cierres totales (won + lost)."""
        leads = [l for l in _leads.values() if str(l.tenant_id) == str(tenant_id)]
        won = sum(1 for l in leads if l.status == LeadStatus.WON)
        lost = sum(1 for l in leads if l.status == LeadStatus.LOST)
        closed = won + lost
        return {
            "won": won,
            "lost": lost,
            "closed": closed,
            "win_rate": round(won / closed, 4) if closed else 0.0,
        }

    def pipeline_value(self, tenant_id: str) -> Dict[str, Any]:
        """Valor agregado del pipeline: monto de propuestas activas."""
        props = [
            p for p in _proposals.values()
            if str(p.tenant_id) == str(tenant_id)
            and p.status in (ProposalStatus.DRAFT, ProposalStatus.SENT)
        ]
        total = sum(p.amount for p in props)
        return {"active_proposals": len(props), "total_value": round(total, 2)}
