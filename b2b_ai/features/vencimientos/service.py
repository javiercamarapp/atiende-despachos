# -*- coding: utf-8 -*-
"""
service.py — VencimientosService: cálculo de plazos, detección de vencimientos
y escalamiento automático.

This service:
  - Calculates fiscal deadlines for a tenant
  - Detects overdue deadlines
  - Escalates pending deadlines based on urgency
  - Marks deadlines as completed with proof
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.vencimientos.models import (
    Deadline,
    Escalation,
    EstadoVencimiento,
    NivelEscalamiento,
    PrioridadVencimiento,
    VencimientoSummary,
)
from b2b_ai.features.vencimientos.validators import (
    validate_date,
    validate_date_range_venc,
    validate_priority,
)


class VencimientosService:
    """Core service for fiscal deadline management."""

    def __init__(self):
        self._deadlines: Dict[str, Deadline] = {}
        self._escalations: List[Escalation] = []

    # -------------------------------------------------------------------
    # Calculate deadlines
    # -------------------------------------------------------------------

    def calculate_deadlines(
        self,
        tenant_id: Optional[str] = None,
        month: Optional[int] = None,
        year: Optional[int] = None,
    ) -> List[Deadline]:
        """Calculate standard fiscal deadlines for a tenant/period.

        Standard Mexican fiscal deadlines:
          - ISR mensual: día 17 del mes siguiente
          - IVA mensual: día 17 del mes siguiente
          - DIOT mensual: día 17 del mes siguiente
          - Nómina: día 17 del mes siguiente
          - Declaración anual: día 17 de abril

        Parameters
        ----------
        tenant_id : Optional[str]
            Tenant identifier.
        month : Optional[int]
            Month to calculate deadlines for.
        year : Optional[int]
            Year.

        Returns
        -------
        List[Deadline]
        """
        now = datetime.now()
        target_month = month or now.month
        target_year = year or now.year

        # Calculate deadline dates (17th of next month)
        if target_month == 12:
            next_month = 1
            next_year = target_year + 1
        else:
            next_month = target_month + 1
            next_year = target_year

        deadline_date = f"{next_year}-{next_month:02d}-17"

        # Determine priority based on how close the deadline is
        days_until = self._days_until(deadline_date)
        priority = self._calculate_priority(days_until)

        deadlines: List[Deadline] = []

        # ISR
        deadlines.append(Deadline(
            id=f"VENC-ISR-{target_year}-{target_month:02d}-{str(_uuid.uuid4())[:8]}",
            tipo="ISR",
            fecha_limite=deadline_date,
            prioridad=priority,
            estado=EstadoVencimiento.PENDIENTE,
            descripcion=f"Declaración mensual de ISR - {target_month:02d}/{target_year}",
            periodo=f"{target_year}-{target_month:02d}",
            tenant_id=tenant_id,
        ))

        # IVA
        deadlines.append(Deadline(
            id=f"VENC-IVA-{target_year}-{target_month:02d}-{str(_uuid.uuid4())[:8]}",
            tipo="IVA",
            fecha_limite=deadline_date,
            prioridad=priority,
            estado=EstadoVencimiento.PENDIENTE,
            descripcion=f"Declaración mensual de IVA - {target_month:02d}/{target_year}",
            periodo=f"{target_year}-{target_month:02d}",
            tenant_id=tenant_id,
        ))

        # DIOT
        deadlines.append(Deadline(
            id=f"VENC-DIOT-{target_year}-{target_month:02d}-{str(_uuid.uuid4())[:8]}",
            tipo="DIOT",
            fecha_limite=deadline_date,
            prioridad=priority,
            estado=EstadoVencimiento.PENDIENTE,
            descripcion=f"DIOT mensual - {target_month:02d}/{target_year}",
            periodo=f"{target_year}-{target_month:02d}",
            tenant_id=tenant_id,
        ))

        # Nómina
        deadlines.append(Deadline(
            id=f"VENC-NOMINA-{target_year}-{target_month:02d}-{str(_uuid.uuid4())[:8]}",
            tipo="Nómina",
            fecha_limite=deadline_date,
            prioridad=priority,
            estado=EstadoVencimiento.PENDIENTE,
            descripcion=f"Declaración de nómina - {target_month:02d}/{target_year}",
            periodo=f"{target_year}-{target_month:02d}",
            tenant_id=tenant_id,
        ))

        # Store deadlines
        for d in deadlines:
            self._deadlines[d.id] = d

        return deadlines

    # -------------------------------------------------------------------
    # Check overdue
    # -------------------------------------------------------------------

    def check_overdue(
        self,
        tenant_id: Optional[str] = None,
    ) -> List[Deadline]:
        """Check for overdue deadlines.

        Returns deadlines that are past their fecha_limite and not completed.
        """
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        overdue: List[Deadline] = []

        for deadline in self._deadlines.values():
            # Filter by tenant
            if tenant_id and deadline.tenant_id != tenant_id:
                continue

            # Skip completed deadlines
            if deadline.estado in (EstadoVencimiento.COMPLETADO,):
                continue

            # Check if past due
            if deadline.fecha_limite < today:
                deadline.estado = EstadoVencimiento.VENCIDO
                overdue.append(deadline)

        return sorted(overdue, key=lambda d: d.fecha_limite)

    # -------------------------------------------------------------------
    # Escalate
    # -------------------------------------------------------------------

    def escalate(
        self,
        deadline: Deadline,
    ) -> Escalation:
        """Escalate a deadline to the next level.

        Escalation levels:
          - nivel_1: Internal reminder (day -3)
          - nivel_2: Supervisor notification (day -1)
          - nivel_3: Director alert (day 0 / today)
          - nivel_4: Executive escalation (overdue)
        """
        now = datetime.now()
        days_until = self._days_until(deadline.fecha_limite)

        # Determine escalation level
        if days_until < 0:
            level = NivelEscalamiento.NIVEL_4
        elif days_until == 0:
            level = NivelEscalamiento.NIVEL_3
        elif days_until <= 1:
            level = NivelEscalamiento.NIVEL_2
        else:
            level = NivelEscalamiento.NIVEL_1

        escalation = Escalation(
            id=f"ESC-{str(_uuid.uuid4())[:8]}",
            deadline_id=deadline.id,
            level=level,
            sent_at=now.isoformat(),
            notes=(
                f"Escalamiento automático para '{deadline.tipo}'. "
                f"Fecha límite: {deadline.fecha_limite}. "
                f"Días restantes: {days_until}."
            ),
        )

        self._escalations.append(escalation)
        deadline.estado = EstadoVencimiento.ESCALADO

        return escalation

    # -------------------------------------------------------------------
    # Mark completed
    # -------------------------------------------------------------------

    def mark_completed(
        self,
        deadline_id: str,
        proof: str = "",
    ) -> bool:
        """Mark a deadline as completed with optional proof.

        Parameters
        ----------
        deadline_id : str
            ID of the deadline to complete.
        proof : str
            URL or reference to proof of completion.

        Returns
        -------
        bool
            True if the deadline was found and marked completed.
        """
        deadline = self._deadlines.get(deadline_id)
        if not deadline:
            return False

        deadline.estado = EstadoVencimiento.COMPLETADO
        deadline.fecha_presentacion = datetime.now().strftime("%Y-%m-%d")
        if proof:
            deadline.comprobante_url = proof

        return True

    # -------------------------------------------------------------------
    # Get upcoming
    # -------------------------------------------------------------------

    def get_upcoming(
        self,
        tenant_id: Optional[str] = None,
        days_ahead: int = 30,
    ) -> List[Deadline]:
        """Get upcoming deadlines within N days.

        Parameters
        ----------
        tenant_id : Optional[str]
            Filter by tenant.
        days_ahead : int
            Number of days to look ahead (default 30).

        Returns
        -------
        List[Deadline]
        """
        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        today_str = now.strftime("%Y-%m-%d")

        upcoming: List[Deadline] = []

        for deadline in self._deadlines.values():
            if tenant_id and deadline.tenant_id != tenant_id:
                continue

            if deadline.estado == EstadoVencimiento.COMPLETADO:
                continue

            if deadline.fecha_limite >= today_str and deadline.fecha_limite <= cutoff_str:
                # Update priority based on proximity
                days_until = self._days_until(deadline.fecha_limite)
                deadline.prioridad = self._calculate_priority(days_until)
                upcoming.append(deadline)

        return sorted(upcoming, key=lambda d: d.fecha_limite)

    # -------------------------------------------------------------------
    # Get summary
    # -------------------------------------------------------------------

    def get_summary(
        self,
        tenant_id: Optional[str] = None,
    ) -> VencimientoSummary:
        """Get a summary of all deadlines."""
        deadlines = [
            d for d in self._deadlines.values()
            if not tenant_id or d.tenant_id == tenant_id
        ]

        now = datetime.now()
        seven_days = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")

        return VencimientoSummary(
            total=len(deadlines),
            pendientes=sum(1 for d in deadlines if d.estado == EstadoVencimiento.PENDIENTE),
            completados=sum(1 for d in deadlines if d.estado == EstadoVencimiento.COMPLETADO),
            vencidos=sum(1 for d in deadlines if d.estado == EstadoVencimiento.VENCIDO),
            escalados=sum(1 for d in deadlines if d.estado == EstadoVencimiento.ESCALADO),
            proximos_7_dias=sum(
                1 for d in deadlines
                if d.fecha_limite >= today
                and d.fecha_limite <= seven_days
                and d.estado != EstadoVencimiento.COMPLETADO
            ),
        )

    # -------------------------------------------------------------------
    # Get all deadlines
    # -------------------------------------------------------------------

    def get_all_deadlines(
        self,
        tenant_id: Optional[str] = None,
    ) -> List[Deadline]:
        """Get all deadlines, optionally filtered by tenant."""
        deadlines = list(self._deadlines.values())
        if tenant_id:
            deadlines = [d for d in deadlines if d.tenant_id == tenant_id]
        return sorted(deadlines, key=lambda d: d.fecha_limite)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _days_until(self, date_str: str) -> int:
        """Calculate days until a given date (negative if past)."""
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
            now = datetime.now()
            delta = target - now
            return delta.days
        except ValueError:
            return 0

    def _calculate_priority(self, days_until: int) -> PrioridadVencimiento:
        """Calculate priority based on days until deadline."""
        if days_until < 0:
            return PrioridadVencimiento.CRITICA
        elif days_until == 0:
            return PrioridadVencimiento.CRITICA
        elif days_until <= 3:
            return PrioridadVencimiento.ALTA
        elif days_until <= 7:
            return PrioridadVencimiento.MEDIA
        else:
            return PrioridadVencimiento.BAJA
