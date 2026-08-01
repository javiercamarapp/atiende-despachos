# -*- coding: utf-8 -*-
"""
alerts.py — Aging alerts for unreconciled items.

Implements the alert rules from the blueprint:
  - Deposits without CFDI (possible undeclared income)
  - Withdrawals without CFDI (deductibility check)
  - Inter-account transfers (auto-excluded)
  - Bank fees (classified as expense 6030200)
  - Deposits > declared income × 1.15 (Art. 91 LISR)
  - Duplicate payments
  - Unidentified movements > $50,000
  - Aging buckets: 0-7, 8-15, 16-30, 31-60, 60+ days
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.reconciliation_agent.models import (
    AgingAlert,
    AlertSeverity,
    BankMovement,
    ReconciliationResult,
)

logger = logging.getLogger(__name__)


# Aging thresholds (days)
AGING_BUCKETS = [
    (0, 7, AlertSeverity.INFO),
    (8, 15, AlertSeverity.INFO),
    (16, 30, AlertSeverity.WARNING),
    (31, 60, AlertSeverity.WARNING),
    (61, 999, AlertSeverity.CRITICAL),
]

# Bank fee patterns
BANK_FEE_PATTERNS = [
    "comision", "comisión", "cargo por", "iva comision",
    "iva por comision", "cuota manejo", "tarifa",
    "cargo servicio", "mantenimiento cuenta",
]

# Transfer patterns (inter-account)
TRANSFER_PATTERNS = [
    "transferencia entre cuentas", "traspaso",
    "transferencia propia", "mismo titular",
]


class AlertEngine:
    """Generates alerts for unreconciled bank movements.

    Rules from the blueprint (section 4.5):
      - Deposits without CFDI → warning
      - Withdrawals without CFDI → warning
      - Bank fees → info (auto-classify)
      - Large movements > $50K → critical
      - Duplicate payments → warning
      - Income discrepancy → critical (Art. 91 LISR)
      - Aging escalation
    """

    def __init__(
        self,
        large_movement_threshold: float = 50_000.0,
        income_discrepancy_ratio: float = 1.15,
    ):
        self.large_movement_threshold = large_movement_threshold
        self.income_discrepancy_ratio = income_discrepancy_ratio

    def generate_alerts(
        self,
        result: ReconciliationResult,
        reference_date: Optional[str] = None,
    ) -> List[AgingAlert]:
        """Generate alerts for all unreconciled movements.

        Args:
            result: ReconciliationResult with unmatched items.
            reference_date: Reference date for aging (default: today).

        Returns:
            List of AgingAlerts.
        """
        alerts: List[AgingAlert] = []
        ref_date = self._parse_date(reference_date) or datetime.utcnow()

        # Alerts for unreconciled bank movements
        for mov in result.unmatched_bank:
            alerts.extend(self._check_movement(mov, ref_date))

        # Duplicate detection
        alerts.extend(self._check_duplicates(result.unmatched_bank, ref_date))

        return alerts

    def _check_movement(
        self, mov: BankMovement, ref_date: datetime
    ) -> List[AgingAlert]:
        """Check a single movement against all rules."""
        alerts: List[AgingAlert] = []
        days = self._days_since(mov.fecha, ref_date)
        severity = self._aging_severity(days)

        desc_lower = (mov.descripcion or "").lower()
        monto = abs(mov.monto)

        # Rule 1: Bank fees
        if self._is_bank_fee(desc_lower):
            alerts.append(AgingAlert(
                item_type="bank",
                fecha=mov.fecha,
                monto=mov.monto,
                descripcion=mov.descripcion,
                days_unreconciled=days,
                severity=AlertSeverity.INFO,
                message=f"Comisión bancaria de ${monto:,.2f} — gasto deducible (cuenta 6030200)",
                rule="bank_fee",
            ))
            return alerts  # Don't generate other alerts for bank fees

        # Rule 2: Inter-account transfers
        if self._is_transfer(desc_lower):
            alerts.append(AgingAlert(
                item_type="bank",
                fecha=mov.fecha,
                monto=mov.monto,
                descripcion=mov.descripcion,
                days_unreconciled=days,
                severity=AlertSeverity.INFO,
                message=f"Transferencia entre cuentas propias — excluida de conciliación fiscal",
                rule="inter_account_transfer",
            ))
            return alerts

        # Rule 3: Large unidentified movement
        if monto >= self.large_movement_threshold:
            alerts.append(AgingAlert(
                item_type="bank",
                fecha=mov.fecha,
                monto=mov.monto,
                descripcion=mov.descripcion,
                days_unreconciled=days,
                severity=AlertSeverity.CRITICAL,
                message=(
                    f"🔴 Movimiento no identificado por ${monto:,.2f} — "
                    f"requiere revisión urgente (umbral ${self.large_movement_threshold:,.0f})"
                ),
                rule="large_unidentified",
            ))

        # Rule 4: Deposit without CFDI
        if mov.monto > 0:
            alerts.append(AgingAlert(
                item_type="bank",
                fecha=mov.fecha,
                monto=mov.monto,
                descripcion=mov.descripcion,
                days_unreconciled=days,
                severity=severity if severity == AlertSeverity.CRITICAL else AlertSeverity.WARNING,
                message=(
                    f"⚠️ Depósito de ${monto:,.2f} el {mov.fecha} sin factura asociada — "
                    f"posible ingreso no declarado ({days} días sin conciliar)"
                ),
                rule="deposit_no_cfdi",
            ))

        # Rule 5: Withdrawal without CFDI
        elif mov.monto < 0:
            alerts.append(AgingAlert(
                item_type="bank",
                fecha=mov.fecha,
                monto=mov.monto,
                descripcion=mov.descripcion,
                days_unreconciled=days,
                severity=severity if severity == AlertSeverity.CRITICAL else AlertSeverity.WARNING,
                message=(
                    f"⚠️ Retiro de ${monto:,.2f} sin factura — "
                    f"verificar deducibilidad ({days} días sin conciliar)"
                ),
                rule="withdrawal_no_cfdi",
            ))

        # Aging escalation
        if days > 30:
            alerts.append(AgingAlert(
                item_type="bank",
                fecha=mov.fecha,
                monto=mov.monto,
                descripcion=mov.descripcion,
                days_unreconciled=days,
                severity=AlertSeverity.CRITICAL,
                message=(
                    f"🔴 Partida sin conciliar por {days} días — "
                    f"monto ${monto:,.2f} requiere atención inmediata"
                ),
                rule="aging_escalation",
            ))

        return alerts

    def _check_duplicates(
        self, movements: List[BankMovement], ref_date: datetime
    ) -> List[AgingAlert]:
        """Detect potential duplicate payments (same amount to same recipient within 24h)."""
        alerts: List[AgingAlert] = []
        seen: Dict[str, List[BankMovement]] = {}

        for mov in movements:
            # Group by (abs_amount, normalized_description_prefix)
            key = f"{abs(mov.monto):.2f}_{(mov.descripcion or '')[:30].lower().strip()}"
            seen.setdefault(key, []).append(mov)

        for key, group in seen.items():
            if len(group) < 2:
                continue
            # Check if within 24 hours
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    d1 = self._parse_date(group[i].fecha)
                    d2 = self._parse_date(group[j].fecha)
                    if d1 and d2 and abs((d1 - d2).days) <= 1:
                        alerts.append(AgingAlert(
                            item_type="bank",
                            fecha=group[i].fecha,
                            monto=group[i].monto,
                            descripcion=group[i].descripcion,
                            days_unreconciled=self._days_since(group[i].fecha, ref_date),
                            severity=AlertSeverity.WARNING,
                            message=(
                                f"⚠️ Posible pago duplicado: mismo monto "
                                f"(${abs(group[i].monto):,.2f}) y proveedor "
                                f"en 24 horas ({group[i].fecha} / {group[j].fecha})"
                            ),
                            rule="duplicate_payment",
                        ))

        return alerts

    def check_income_discrepancy(
        self,
        total_deposits: float,
        declared_income: float,
    ) -> Optional[AgingAlert]:
        """Check if deposits exceed declared income × threshold (Art. 91 LISR).

        Returns an alert if discrepancy detected.
        """
        if declared_income <= 0:
            return None

        ratio = total_deposits / declared_income
        if ratio > self.income_discrepancy_ratio:
            return AgingAlert(
                item_type="bank",
                fecha=datetime.utcnow().strftime("%Y-%m-%d"),
                monto=total_deposits - declared_income,
                descripcion="",
                days_unreconciled=0,
                severity=AlertSeverity.CRITICAL,
                message=(
                    f"🔴 ALERTA: Depósitos (${total_deposits:,.2f}) superan "
                    f"ingresos declarados (${declared_income:,.2f}) × {self.income_discrepancy_ratio} — "
                    f"riesgo de discrepancia fiscal (Art. 91 LISR)"
                ),
                rule="income_discrepancy_art91",
            )
        return None

    @staticmethod
    def _is_bank_fee(desc: str) -> bool:
        return any(p in desc for p in BANK_FEE_PATTERNS)

    @staticmethod
    def _is_transfer(desc: str) -> bool:
        return any(p in desc for p in TRANSFER_PATTERNS)

    @staticmethod
    def _days_since(fecha_str: str, ref_date: datetime) -> int:
        d = AlertEngine._parse_date(fecha_str)
        if d:
            return max(0, (ref_date - d).days)
        return 0

    @staticmethod
    def _parse_date(s: str) -> Optional[datetime]:
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _aging_severity(days: int) -> AlertSeverity:
        for low, high, sev in AGING_BUCKETS:
            if low <= days <= high:
                return sev
        return AlertSeverity.CRITICAL
