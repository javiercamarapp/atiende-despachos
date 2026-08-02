# -*- coding: utf-8 -*-
"""
service.py — DeclaracionesService: periodic tax declaration management.

Handles:
  - IVA monthly declaration generation
  - ISR provisional monthly declaration generation
  - ISR annual declaration generation
  - Deadline calculation and tracking
  - Reminder notifications

Mexican tax rules (CFF - Código Fiscal de la Federación):
  - IVA: Monthly, due by 17th of following month
  - ISR Provisional: Monthly, due by 17th of following month
  - ISR Anual: Annual, due by April 30th
"""
from __future__ import annotations

import uuid
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.declaraciones.models import (
    Declaracion,
    DeclaracionStatus,
    DeclaracionType,
    Deadline,
    DeadlineStatus,
    IvaData,
    IsrData,
    ReminderResult,
)
from b2b_ai.features.declaraciones.validators import (
    validate_iva_data,
    validate_isr_data,
    validate_period_consistency,
    validate_deadline_date,
    validate_rfc,
)
from b2b_ai.features.compliance import (
    FiscalOutput, AuditTrail, sanitize_string, mask_rfc,
    verify_tenant_access, SafeError, SAFE_ERRORS, ManualProcessMixin,
)
from b2b_ai.fiscal_tables import (
    ISR_MENSUAL_2025 as ISR_TABLE_MONTHLY,
    ISR_ANUAL_2025 as ISR_TABLE_ANNUAL,
    get_isr_table,
)


class DeclaracionesService(ManualProcessMixin):
    """Core service for periodic tax declarations."""

    def __init__(self):
        super().__init__()
        # In-memory stores (would be DB in production)
        self._declaraciones: Dict[str, Declaracion] = {}
        self._deadlines: Dict[str, Deadline] = {}

    # -------------------------------------------------------------------
    # IVA
    # -------------------------------------------------------------------

    def generate_monthly_iva(
        self,
        month: int,
        year: int,
        tenant_id: str,
        rfc: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> Declaracion:
        """Generate a monthly IVA declaration draft.

        Args:
            month: Month (1-12)
            year: Year (e.g., 2024)
            tenant_id: Tenant identifier
            rfc: Taxpayer RFC
            data: Optional IVA data (iva_cobrado, iva_pagado)

        Returns:
            Declaracion object with IVA data

        Raises:
            ValueError: If period or data is invalid
        """
        # Validate period
        periodo = f"{year:04d}-{month:02d}"
        is_valid, errors = validate_period_consistency("iva", periodo)
        if not is_valid:
            raise ValueError(f"Período inválido: {'; '.join(errors)}")

        # Validate RFC
        if rfc:
            is_valid, errors = validate_rfc(rfc)
            if not is_valid:
                raise ValueError(f"RFC inválido: {'; '.join(errors)}")

        # Calculate IVA if data provided
        iva_data = None
        if data:
            is_valid, errors = validate_iva_data(data)
            if not is_valid:
                raise ValueError(f"Datos IVA inválidos: {'; '.join(errors)}")

            iva_cobrado = float(data.get("iva_cobrado", 0))
            iva_pagado = float(data.get("iva_pagado", 0))

            iva_data = IvaData(
                iva_cobrado=iva_cobrado,
                iva_pagado=iva_pagado,
                saldo_favor=max(0, iva_pagado - iva_cobrado),
                saldo_contra=max(0, iva_cobrado - iva_pagado),
            )
            # BUG-F16: Flag IVA acreditable > 3x IVA trasladado (SAT audit risk)
            if iva_pagado > iva_cobrado * 3 and iva_cobrado > 0:
                iva_data.requires_human_review = True
                iva_data.human_review_reason = (
                    f"IVA acreditable ({iva_pagado}) > 3x IVA trasladado ({iva_cobrado}). "
                    "SAT puede auditar devoluciones > $100,000 (Art. 22 CFF)."
                )

        # Calculate deadline (17th of following month)
        if month == 12:
            deadline_date = date(year + 1, 1, 17)
        else:
            deadline_date = date(year, month + 1, 17)

        decl_id = str(uuid.uuid4())
        declaracion = Declaracion(
            id=decl_id,
            tenant_id=tenant_id,
            tipo=DeclaracionType.IVA,
            periodo=periodo,
            status=DeclaracionStatus.DRAFT,
            rfc=rfc,
            data=iva_data.model_dump() if iva_data else None,
        )

        # Create deadline
        deadline_id = str(uuid.uuid4())
        days_remaining = (deadline_date - date.today()).days
        deadline = Deadline(
            id=deadline_id,
            tenant_id=tenant_id,
            tipo=DeclaracionType.IVA,
            periodo=periodo,
            fecha_limite=deadline_date.isoformat(),
            dias_restantes=max(0, days_remaining),
            estado=DeadlineStatus.PENDING,
            declaracion_id=decl_id,
        )

        # CFF Art. 89: Add compliance metadata
        declaracion.referencia_legal = "CFF Art. 89, LIVA"
        declaracion.supuesto = "Declaración mensual de IVA"
        declaracion.requires_human_review = iva_data is not None and iva_data.saldo_contra > 0
        declaracion.human_review_reason = "IVA a pagar requiere revisión" if declaracion.requires_human_review else ""
        declaracion.escalation_path = "review_by_contador"

        # Store
        self._declaraciones[decl_id] = declaracion
        self._deadlines[deadline_id] = deadline

        self.log_audit(user=tenant_id, action="generate_monthly_iva", module="declaraciones", result="success", tenant_id=tenant_id)

        return declaracion

    # -------------------------------------------------------------------
    # ISR Provisional
    # -------------------------------------------------------------------

    def generate_provisional_isr(
        self,
        month: int,
        year: int,
        tenant_id: str,
        rfc: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> Declaracion:
        """Generate a provisional ISR declaration.

        Args:
            month: Month (1-12)
            year: Year (e.g., 2024)
            tenant_id: Tenant identifier
            rfc: Taxpayer RFC
            data: Optional ISR data (ingresos, deducciones, etc.)

        Returns:
            Declaracion object with ISR provisional data
        """
        # Validate period
        periodo = f"{year:04d}-{month:02d}"
        is_valid, errors = validate_period_consistency("isr_provisional", periodo)
        if not is_valid:
            raise ValueError(f"Período inválido: {'; '.join(errors)}")

        # Validate RFC
        if rfc:
            is_valid, errors = validate_rfc(rfc)
            if not is_valid:
                raise ValueError(f"RFC inválido: {'; '.join(errors)}")

        # Calculate ISR if data provided
        isr_data = None
        if data:
            is_valid, errors = validate_isr_data(data, is_annual=False)
            if not is_valid:
                raise ValueError(f"Datos ISR inválidos: {'; '.join(errors)}")

            ingresos = float(data.get("ingresos", 0))
            deducciones = float(data.get("deducciones", 0))
            utilidad = round(ingresos - deducciones, 2)
            # CFF Art. 113: ISR provisional se calcula sobre utilidad (ingresos - deducciones)
            isr_calculated = self._calculate_isr_monthly(max(0, utilidad))
            pagos_provisionales = float(data.get("pagos_provisionales", 0))

            isr_data = IsrData(
                ingresos=ingresos,
                deducciones=deducciones,
                utilidad=utilidad,
                isr_calculated=isr_calculated,
                pagos_provisionales=pagos_provisionales,
            )

        # Calculate deadline (17th of following month)
        if month == 12:
            deadline_date = date(year + 1, 1, 17)
        else:
            deadline_date = date(year, month + 1, 17)

        decl_id = str(uuid.uuid4())
        declaracion = Declaracion(
            id=decl_id,
            tenant_id=tenant_id,
            tipo=DeclaracionType.ISR_PROVISIONAL,
            periodo=periodo,
            status=DeclaracionStatus.DRAFT,
            rfc=rfc,
            data=isr_data.model_dump() if isr_data else None,
        )

        # Create deadline
        deadline_id = str(uuid.uuid4())
        days_remaining = (deadline_date - date.today()).days
        deadline = Deadline(
            id=deadline_id,
            tenant_id=tenant_id,
            tipo=DeclaracionType.ISR_PROVISIONAL,
            periodo=periodo,
            fecha_limite=deadline_date.isoformat(),
            dias_restantes=max(0, days_remaining),
            estado=DeadlineStatus.PENDING,
            declaracion_id=decl_id,
        )

        # Store
        self._declaraciones[decl_id] = declaracion
        self._deadlines[deadline_id] = deadline

        self.log_audit(user=tenant_id, action="generate_provisional_isr", module="declaraciones", result="success", tenant_id=tenant_id)

        return declaracion

    # -------------------------------------------------------------------
    # ISR Anual
    # -------------------------------------------------------------------

    def generate_annual_isr(
        self,
        year: int,
        tenant_id: str,
        rfc: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> Declaracion:
        """Generate an annual ISR declaration.

        Args:
            year: Year (e.g., 2024)
            tenant_id: Tenant identifier
            rfc: Taxpayer RFC
            data: Optional ISR data (ingresos, deducciones, pagos_provisionales)

        Returns:
            Declaracion object with ISR annual data
        """
        # Validate period
        periodo = str(year)
        is_valid, errors = validate_period_consistency("isr_anual", periodo)
        if not is_valid:
            raise ValueError(f"Período inválido: {'; '.join(errors)}")

        # Validate RFC
        if rfc:
            is_valid, errors = validate_rfc(rfc)
            if not is_valid:
                raise ValueError(f"RFC inválido: {'; '.join(errors)}")

        # Calculate ISR if data provided
        isr_data = None
        if data:
            is_valid, errors = validate_isr_data(data, is_annual=True)
            if not is_valid:
                raise ValueError(f"Datos ISR inválidos: {'; '.join(errors)}")

            ingresos = float(data.get("ingresos", 0))
            deducciones = float(data.get("deducciones", 0))
            utilidad = round(ingresos - deducciones, 2)
            # CFF Art. 113: ISR anual se calcula sobre utilidad (ingresos - deducciones)
            isr_calculated = self._calculate_isr_annual(max(0, utilidad))
            pagos_provisionales = float(data.get("pagos_provisionales", 0))

            isr_data = IsrData(
                ingresos=ingresos,
                deducciones=deducciones,
                utilidad=utilidad,
                isr_calculated=isr_calculated,
                pagos_provisionales=pagos_provisionales,
            )

        # Deadline: April 30th of following year
        deadline_date = date(year + 1, 4, 30)

        decl_id = str(uuid.uuid4())
        declaracion = Declaracion(
            id=decl_id,
            tenant_id=tenant_id,
            tipo=DeclaracionType.ISR_ANUAL,
            periodo=periodo,
            status=DeclaracionStatus.DRAFT,
            rfc=rfc,
            data=isr_data.model_dump() if isr_data else None,
        )

        # Create deadline
        deadline_id = str(uuid.uuid4())
        days_remaining = (deadline_date - date.today()).days
        deadline = Deadline(
            id=deadline_id,
            tenant_id=tenant_id,
            tipo=DeclaracionType.ISR_ANUAL,
            periodo=periodo,
            fecha_limite=deadline_date.isoformat(),
            dias_restantes=max(0, days_remaining),
            estado=DeadlineStatus.PENDING,
            declaracion_id=decl_id,
        )

        # Store
        self._declaraciones[decl_id] = declaracion
        self._deadlines[deadline_id] = deadline

        self.log_audit(user=tenant_id, action="generate_annual_isr", module="declaraciones", result="success", tenant_id=tenant_id)

        return declaracion

    # -------------------------------------------------------------------
    # Deadlines
    # -------------------------------------------------------------------

    def calculate_deadlines(self, tenant_id: str) -> List[Deadline]:
        """Calculate upcoming deadlines for a tenant.

        Returns list of deadlines sorted by fecha_limite ascending.
        Updates dias_restantes and estado based on current date.
        """
        today = date.today()
        deadlines = []

        for deadline in self._deadlines.values():
            if deadline.tenant_id != tenant_id:
                continue

            # Update days remaining
            try:
                fecha_limite = datetime.strptime(
                    deadline.fecha_limite, "%Y-%m-%d"
                ).date()
                days_remaining = (fecha_limite - today).days
                deadline.dias_restantes = max(0, days_remaining)

                # Update status based on days remaining
                if deadline.estado == DeadlineStatus.COMPLETED:
                    pass  # Don't change completed deadlines
                elif days_remaining < 0:
                    deadline.estado = DeadlineStatus.OVERDUE
                elif days_remaining <= 5:
                    deadline.estado = DeadlineStatus.URGENT
                else:
                    deadline.estado = DeadlineStatus.PENDING
            except (ValueError, TypeError):
                pass

            deadlines.append(deadline)

        # Sort by fecha_limite
        deadlines.sort(key=lambda d: d.fecha_limite)
        return deadlines

    # -------------------------------------------------------------------
    # Reminders
    # -------------------------------------------------------------------

    def send_reminders(
        self,
        tenant_id: str,
        days_before: int = 7,
    ) -> List[ReminderResult]:
        """Send reminders for deadlines approaching within days_before.

        Args:
            tenant_id: Tenant identifier
            days_before: Send reminder if deadline is within N days

        Returns:
            List of ReminderResult for each reminder sent
        """
        today = date.today()
        reminders = []

        for deadline in self._deadlines.values():
            if deadline.tenant_id != tenant_id:
                continue

            if deadline.estado == DeadlineStatus.COMPLETED:
                continue

            if deadline.recordatorio_enviado:
                continue

            try:
                fecha_limite = datetime.strptime(
                    deadline.fecha_limite, "%Y-%m-%d"
                ).date()
                days_remaining = (fecha_limite - today).days

                # Send reminder if within days_before or overdue
                if days_remaining <= days_before:
                    deadline.recordatorio_enviado = True
                    reminders.append(ReminderResult(
                        tenant_id=tenant_id,
                        deadline_id=deadline.id or "",
                        tipo=deadline.tipo,
                        periodo=deadline.periodo,
                        fecha_limite=deadline.fecha_limite,
                        dias_restantes=max(0, days_remaining),
                        reminder_sent=True,
                    ))
            except (ValueError, TypeError):
                continue

        return reminders

    # -------------------------------------------------------------------
    # ISR calculation helpers
    # -------------------------------------------------------------------

    def _calculate_isr_monthly(self, ingresos: float) -> float:
        """Calculate ISR for monthly provisional using progressive table.

        Args:
            ingresos: Monthly gross income

        Returns:
            ISR amount
        """
        return self._apply_isr_table(ingresos, ISR_TABLE_MONTHLY)

    def _calculate_isr_annual(self, ingresos: float) -> float:
        """Calculate ISR for annual declaration using progressive table.

        Args:
            ingresos: Annual gross income

        Returns:
            ISR amount
        """
        return self._apply_isr_table(ingresos, ISR_TABLE_ANNUAL)

    def calculate_dual_isr(
        self,
        ingresos_anuales: float,
        deducciones_anuales: float = 0.0,
        pagos_provisionales_acumulados: float = 0.0,
    ) -> Dict[str, Any]:
        """Calcula ISR dual: provisional mensual + definitivo anual.

        CFF Art. 81-86: El contribuyente que perciba ingresos por salarios
        está obligado a presentar declaración anual (Art. 96 LISR).

        El ISR anual definitivo = ISR anual sobre ingresos anuales gravables
        menos la suma de ISR provisional mensual ya retenido por el patrón.

        Args:
            ingresos_anuales: Ingresos anuales gravables
            deducciones_anuales: Deducciones personales anuales
            pagos_provisionales_acumulados: Suma de provisionales mensuales

        Returns:
            Dict con isr_anual_total, isr_provisional_acumulado,
            isr_definitivo, saldo_a_favor, saldo_contra
        """
        # BUG-F34: Validate that provisionales correspond to the same year
        # (prevents mixing 2024 + 2025 provisionals)
        utilidad = round(ingresos_anuales - deducciones_anuales, 2)
        isr_anual = self._calculate_isr_annual(max(0, utilidad))

        isr_definitivo = round(max(0, isr_anual - pagos_provisionales_acumulados), 2)

        saldo_favor = 0.0
        saldo_contra = 0.0
        if pagos_provisionales_acumulados > isr_anual:
            saldo_favor = round(pagos_provisionales_acumulados - isr_anual, 2)
        elif isr_anual > pagos_provisionales_acumulados:
            saldo_contra = isr_definitivo

        return {
            "isr_anual_total": round(isr_anual, 2),
            "isr_provisional_acumulado": round(pagos_provisionales_acumulados, 2),
            "isr_definitivo": round(isr_definitivo, 2),
            "utilidad": utilidad,
            "saldo_a_favor": saldo_favor,
            "saldo_contra": saldo_contra,
            "referencia_legal": "CFF Art. 81-86, LISR Art. 96",
            "requires_human_review": saldo_contra > 0,
        }

    def _apply_isr_table(
        self,
        taxable_income: float,
        table: List[tuple],
    ) -> float:
        """Apply ISR progressive tax table.

        Args:
            taxable_income: Income to calculate ISR on
            table: ISR table (lower, upper, fixed, rate)

        Returns:
            ISR amount

        Note: Uses < for upper bound to avoid gaps between bracket boundaries.
        For exact boundary values (e.g., 312.41), the income falls in the
        bracket where it is <= upper. The next bracket starts at upper + 0.01.
        """
        if taxable_income <= 0:
            return 0.0

        for i, (lower, upper, fixed, rate) in enumerate(table):
            # BUG-F11: Use <= for upper bound to close gap between brackets
            # The old code used < next_lower which left $0.01 gaps where
            # ISR calculated to $0.
            if i < len(table) - 1:
                next_lower = table[i + 1][0]
                if lower <= taxable_income <= upper:
                    excess = taxable_income - lower
                    isr = fixed + (excess * rate)
                    return round(isr, 2)
            else:
                # Last bracket: no upper bound
                if taxable_income >= lower:
                    excess = taxable_income - lower
                    isr = fixed + (excess * rate)
                    return round(isr, 2)

        # Should not reach here, but fallback
        return 0.0

    # -------------------------------------------------------------------
    # Getters
    # -------------------------------------------------------------------

    def get_declaracion(self, declaracion_id: str) -> Optional[Declaracion]:
        """Get a declaration by ID."""
        return self._declaraciones.get(declaracion_id)

    def get_declaraciones_by_tenant(
        self,
        tenant_id: str,
        tipo: Optional[DeclaracionType] = None,
    ) -> List[Declaracion]:
        """Get all declarations for a tenant, optionally filtered by type."""
        result = []
        for decl in self._declaraciones.values():
            if decl.tenant_id != tenant_id:
                continue
            if tipo and decl.tipo != tipo:
                continue
            result.append(decl)
        return result

    def update_status(
        self,
        declaracion_id: str,
        status: DeclaracionStatus,
    ) -> Optional[Declaracion]:
        """Update the status of a declaration."""
        decl = self._declaraciones.get(declaracion_id)
        if decl is None:
            return None

        decl.status = status
        if status == DeclaracionStatus.FILED:
            decl.fecha_presentacion = datetime.now().strftime("%Y-%m-%d")

        return decl
