# -*- coding: utf-8 -*-
"""journal_generator.py — JournalEntryGenerator.

Generates journal entries (pólizas contables) compliant with NIF
and SAT catalog. Handles ingreso, egreso, and diario types.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from b2b_ai.features.bookkeeping.models import (
    CFDIClassification,
    LineaPoliza,
    PolizaContable,
    PolizaType,
)
from b2b_ai.features.bookkeeping.rules_engine import (
    AccountingRulesEngine,
    CATALOGO_CUENTAS_SAT,
)

log = logging.getLogger(__name__)


class JournalEntryGenerator:
    """Generates NIF-compliant journal entries from classified CFDIs.

    Supports:
    - Pólizas de Ingreso (sales revenue)
    - Pólizas de Egreso (purchases/expenses)
    - Pólizas de Diario (adjustments, depreciation, provisions)

    Each entry is balanced (debe == haber) per NIF C-4.
    """

    def __init__(self, rules_engine: Optional[AccountingRulesEngine] = None):
        self._rules = rules_engine or AccountingRulesEngine()

    def generate_from_classification(
        self,
        classification: CFDIClassification,
        fecha: Optional[str] = None,
        tenant_id: str = "",
    ) -> Optional[PolizaContable]:
        """Generate a journal entry from a CFDI classification.

        Returns None if no mapping exists for the category.
        """
        poliza = self._rules.generate_poliza(classification, tenant_id)
        if poliza is None:
            log.warning(
                "No mapping for (%s, %s)",
                classification.tipo_cfdi, classification.categoria,
            )
            return None

        poliza.fecha = fecha or date.today().isoformat()
        return poliza

    def generate_batch(
        self,
        classifications: List[CFDIClassification],
        fecha: Optional[str] = None,
        tenant_id: str = "",
    ) -> List[PolizaContable]:
        """Generate journal entries for a batch of classified CFDIs."""
        polizas: List[PolizaContable] = []
        for cls in classifications:
            poliza = self.generate_from_classification(cls, fecha, tenant_id)
            if poliza:
                polizas.append(poliza)
        return polizas

    def generate_adjustment(
        self,
        fecha: str,
        concepto: str,
        entries: List[Dict[str, Any]],
        tenant_id: str = "",
    ) -> PolizaContable:
        """Generate a manual adjustment journal entry (póliza de diario).

        entries: list of {"cuenta": str, "debe": float, "haber": float, "concepto": str}
        Validates that debe == haber (NIF balance requirement).
        """
        lineas: List[LineaPoliza] = []
        for entry in entries:
            cuenta = entry.get("cuenta", "")
            debe = float(entry.get("debe", 0))
            haber = float(entry.get("haber", 0))
            lineas.append(LineaPoliza(
                cuenta=cuenta,
                concepto=entry.get("concepto", ""),
                debe=debe,
                haber=haber,
                tipo="cargo" if debe > 0 else "abono",
            ))

        total_debe = round(sum(l.debe for l in lineas), 2)
        total_haber = round(sum(l.haber for l in lineas), 2)

        return PolizaContable(
            tipo=PolizaType.DIARIO,
            fecha=fecha,
            concepto=concepto,
            referencia="",
            lineas=lineas,
            total_debe=total_debe,
            total_haber=total_haber,
            cuadrada=abs(total_debe - total_haber) < 0.01,
            tenant_id=tenant_id,
        )

    def generate_depreciation_entry(
        self,
        fecha: str,
        activos: List[Dict[str, Any]],
        tenant_id: str = "",
    ) -> PolizaContable:
        """Generate depreciation journal entry.

        activos: [{"cuenta_activo": str, "cuenta_depreciacion": str,
                   "cuenta_gasto": str, "monto": float}]
        """
        entries: List[Dict[str, Any]] = []
        for activo in activos:
            # Cargo: Gasto depreciación
            entries.append({
                "cuenta": activo.get("cuenta_gasto", "6020300"),
                "debe": activo["monto"],
                "haber": 0,
                "concepto": f"Depreciación mensual - {CATALOGO_CUENTAS_SAT.get(activo.get('cuenta_activo', ''), '')}",
            })
            # Abono: Depreciación acumulada (convenio: cuenta activo + 100)
            entries.append({
                "cuenta": activo.get("cuenta_depreciacion", "1540100"),
                "debe": 0,
                "haber": activo["monto"],
                "concepto": "Depreciación acumulada",
            })

        return self.generate_adjustment(fecha, "Póliza de depreciación mensual", entries, tenant_id)

    def generate_provision_entry(
        self,
        fecha: str,
        tipo: str,
        monto: float,
        cuenta_gasto: str,
        cuenta_provision: str,
        tenant_id: str = "",
    ) -> PolizaContable:
        """Generate a provision journal entry (aguinaldo, vacaciones, PTU)."""
        entries = [
            {"cuenta": cuenta_gasto, "debe": monto, "haber": 0, "concepto": f"Provisión {tipo}"},
            {"cuenta": cuenta_provision, "debe": 0, "haber": monto, "concepto": f"Provisión {tipo}"},
        ]
        return self.generate_adjustment(fecha, f"Póliza de provisión — {tipo}", entries, tenant_id)

    def validate_poliza(self, poliza: PolizaContable) -> List[str]:
        """Validate a journal entry for NIF compliance.

        Returns list of errors (empty if valid).
        """
        errors: List[str] = []

        # 1. Must have at least 2 lines
        if len(poliza.lineas) < 2:
            errors.append("La póliza debe tener al menos 2 movimientos")

        # 2. Must balance (debe == haber)
        total_debe = round(sum(l.debe for l in poliza.lineas), 2)
        total_haber = round(sum(l.haber for l in poliza.lineas), 2)
        if abs(total_debe - total_haber) > 0.01:
            errors.append(f"Póliza desbalanceada: debe={total_debe}, haber={total_haber}")

        # 3. No negative amounts
        for linea in poliza.lineas:
            if linea.debe < 0 or linea.haber < 0:
                errors.append(f"Monto negativo en cuenta {linea.cuenta}")

        # 4. Each line must be either cargo or abono, not both
        for linea in poliza.lineas:
            if linea.debe > 0 and linea.haber > 0:
                errors.append(
                    f"Cuenta {linea.cuenta} tiene debe y haber simultáneos"
                )

        # 5. Accounts must exist in SAT catalog
        for linea in poliza.lineas:
            if linea.cuenta and linea.cuenta not in CATALOGO_CUENTAS_SAT:
                errors.append(f"Cuenta {linea.cuenta} no existe en catálogo SAT")

        # 6. Must have a date
        if not poliza.fecha:
            errors.append("La póliza requiere fecha")

        return errors
