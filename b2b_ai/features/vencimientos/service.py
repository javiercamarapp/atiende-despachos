# -*- coding: utf-8 -*-
"""
service.py — Deadline Management service (Vencimientos).

Tracks upcoming fiscal deadlines, detects overdue items, handles
escalation notifications, and manages completion proofs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .models import (
    Deadline,
    DeadlineEstado,
    DeadlineTipo,
    DeadlineWithEscalations,
    Escalation,
    EscalationEstado,
    EscalationLevel,
    Prioridad,
    UpcomingSummary,
)


# ---------------------------------------------------------------------------
# In-memory store (replaced by DB in production)
# ---------------------------------------------------------------------------
_deadlines: Dict[str, Deadline] = {}
_escalations: Dict[str, List[Escalation]] = {}  # deadline_id → [Escalation]


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def calculate_deadlines(
    tenant_id: str,
    days_ahead: int = 30,
) -> List[Deadline]:
    """Get all upcoming deadlines within the next N days.

    Args:
        tenant_id: Company/tenant identifier.
        days_ahead: How many days to look ahead (default 30).

    Returns:
        List of deadlines sorted by fecha_limite ascending.
    """
    today = datetime.utcnow().date()
    cutoff = today + timedelta(days=days_ahead)

    upcoming = []
    for d in _deadlines.values():
        if d.tenant_id != tenant_id:
            continue
        try:
            fecha = datetime.strptime(d.fecha_limite, "%Y-%m-%d").date()
        except ValueError:
            continue
        if today <= fecha <= cutoff:
            upcoming.append(d)

    upcoming.sort(key=lambda x: x.fecha_limite)
    return upcoming


def check_overdue(tenant_id: str) -> List[Deadline]:
    """Find deadlines that have passed and are not completed.

    Returns:
        List of overdue deadlines sorted by fecha_limite.
    """
    today = datetime.utcnow().date()
    overdue = []

    for d in _deadlines.values():
        if d.tenant_id != tenant_id:
            continue
        if d.estado in (DeadlineEstado.COMPLETADO, DeadlineEstado.VENCIDO):
            continue
        try:
            fecha = datetime.strptime(d.fecha_limite, "%Y-%m-%d").date()
        except ValueError:
            continue
        if fecha < today:
            overdue.append(d)

    overdue.sort(key=lambda x: x.fecha_limite)
    return overdue


def escalate(deadline: Deadline) -> Escalation:
    """Escalate a deadline to the next notification level.

    Escalation progression: email → WhatsApp → phone call.
    If already at maximum level, stays at CALL.

    Returns:
        The new Escalation record created.
    """
    existing = _escalations.get(deadline.id, [])
    current_level = max(
        (e.level.value for e in existing),
        default=0,
    )

    # Determine next level
    next_level = min(current_level + 1, EscalationLevel.CALL.value)

    escalation = Escalation(
        id=str(uuid.uuid4()),
        deadline_id=deadline.id,
        level=EscalationLevel(next_level),
        sent_at=datetime.utcnow(),
        estado=EscalationEstado.ENVIADO,
    )

    if deadline.id not in _escalations:
        _escalations[deadline.id] = []
    _escalations[deadline.id].append(escalation)

    # Update deadline status
    deadline.estado = DeadlineEstado.ESCALADO

    return escalation


def mark_completed(
    deadline_id: str,
    proof: str = "",
) -> bool:
    """Mark a deadline as completed with optional proof.

    Args:
        deadline_id: ID of the deadline to complete.
        proof: URL or description of completion proof.

    Returns:
        True if successfully marked, False if not found.
    """
    deadline = _deadlines.get(deadline_id)
    if deadline is None:
        return False

    deadline.estado = DeadlineEstado.COMPLETADO
    deadline.proof_url = proof if proof else None
    return True


def create_deadline(
    tenant_id: str,
    tipo: DeadlineTipo,
    fecha_limite: str,
    prioridad: Prioridad = Prioridad.MEDIA,
    descripcion: str = "",
    responsable: str = "",
) -> Deadline:
    """Create and store a new deadline."""
    deadline = Deadline(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        tipo=tipo,
        fecha_limite=fecha_limite,
        prioridad=prioridad,
        estado=DeadlineEstado.PENDIENTE,
        descripcion=descripcion,
        responsable=responsable,
        created_at=datetime.utcnow(),
    )
    _deadlines[deadline.id] = deadline
    return deadline


def get_deadline(deadline_id: str) -> Optional[Deadline]:
    """Retrieve a deadline by ID."""
    return _deadlines.get(deadline_id)


def get_deadline_with_escalations(deadline_id: str) -> Optional[DeadlineWithEscalations]:
    """Retrieve a deadline with its escalation history."""
    deadline = _deadlines.get(deadline_id)
    if deadline is None:
        return None
    escalations = _escalations.get(deadline_id, [])
    return DeadlineWithEscalations(deadline=deadline, escalations=escalations)


def get_upcoming_summary(tenant_id: str, days_ahead: int = 30) -> UpcomingSummary:
    """Get a summary of upcoming deadlines by priority."""
    deadlines = calculate_deadlines(tenant_id, days_ahead)
    return UpcomingSummary(
        tenant_id=tenant_id,
        total=len(deadlines),
        criticas=sum(1 for d in deadlines if d.prioridad == Prioridad.CRITICA),
        altas=sum(1 for d in deadlines if d.prioridad == Prioridad.ALTA),
        medias=sum(1 for d in deadlines if d.prioridad == Prioridad.MEDIA),
        bajas=sum(1 for d in deadlines if d.prioridad == Prioridad.BAJA),
        deadlines=deadlines,
    )


def acknowledge_deadline(deadline_id: str, responsable: str = "") -> bool:
    """Acknowledge a deadline, moving it to en_proceso."""
    deadline = _deadlines.get(deadline_id)
    if deadline is None:
        return False
    deadline.estado = DeadlineEstado.EN_PROCESO
    if responsable:
        deadline.responsable = responsable
    return True
