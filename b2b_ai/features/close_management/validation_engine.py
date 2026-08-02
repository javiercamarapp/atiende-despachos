# -*- coding: utf-8 -*-
"""
validation_engine.py — ValidationEngine for close management.

Verifies the integrity of the monthly close:
  - Balanza cuadrada (total_debe == total_haber)
  - IVA conciliado (trasladado - acreditable matches provision)
  - ISR provisionado (ISR provision > 0 if there's utility)
  - Nómina cuadrada (all payrolls balanced)
  - Bancos conciliados (reconciliation match rate >= threshold)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from b2b_ai.features.close_management.models import (
    ValidationResult,
    ValidationType,
)


class ValidationEngine:
    """Runs close validations and returns pass/fail results.

    Each validation can be called independently for testing,
    or all at once via ``run_all()``.
    """

    def __init__(
        self,
        tolerance_balance: float = 1.0,
        min_reconciliation_rate: float = 0.80,
    ):
        self.tolerance_balance = tolerance_balance
        self.min_reconciliation_rate = min_reconciliation_rate

    # ------------------------------------------------------------------
    # Individual validations
    # ------------------------------------------------------------------

    def validate_balance_cuadrada(
        self,
        total_debe: float,
        total_haber: float,
    ) -> ValidationResult:
        """Check that trial balance totals match."""
        diff = round(abs(total_debe - total_haber), 2)
        passed = diff <= self.tolerance_balance
        return ValidationResult(
            type=ValidationType.BALANCE_CUADRADA,
            passed=passed,
            message=(
                "Balanza cuadrada"
                if passed
                else f"Balanza NO cuadrada — diferencia ${diff:,.2f}"
            ),
            details={
                "total_debe": total_debe,
                "total_haber": total_haber,
                "diferencia": diff,
                "tolerancia": self.tolerance_balance,
            },
        )

    def validate_iva_conciliado(
        self,
        iva_trasladado: float,
        iva_acreditable: float,
        iva_provisionado: float,
        tolerance: float = 100.0,
    ) -> ValidationResult:
        """Check IVA calculation: trasladado - acreditable ≈ provision."""
        expected = round(iva_trasladado - iva_acreditable, 2)
        diff = round(abs(expected - iva_provisionado), 2)
        passed = diff <= tolerance
        return ValidationResult(
            type=ValidationType.IVA_CONCILIADO,
            passed=passed,
            message=(
                "IVA conciliado correctamente"
                if passed
                else f"IVA NO conciliado — diferencia ${diff:,.2f}"
            ),
            details={
                "iva_trasladado": iva_trasladado,
                "iva_acreditable": iva_acreditable,
                "expected": expected,
                "iva_provisionado": iva_provisionado,
                "diferencia": diff,
            },
        )

    def validate_isr_provisionado(
        self,
        isr_provision: float,
        utilidad_fiscal: float,
        isr_rate: float = 0.30,
    ) -> ValidationResult:
        """Check ISR provisioned if there's fiscal utility."""
        if utilidad_fiscal <= 0:
            return ValidationResult(
                type=ValidationType.ISR_PROVISIONADO,
                passed=True,
                message="ISR no aplica — sin utilidad fiscal",
                details={
                    "utilidad_fiscal": utilidad_fiscal,
                    "isr_provision": isr_provision,
                },
            )
        expected = round(utilidad_fiscal * isr_rate, 2)
        diff = round(abs(expected - isr_provision), 2)
        tolerance = max(expected * 0.01, 100.0)  # 1% or $100
        passed = diff <= tolerance
        return ValidationResult(
            type=ValidationType.ISR_PROVISIONADO,
            passed=passed,
            message=(
                "ISR provisionado correctamente"
                if passed
                else f"ISR provision insuficiente — esperado ${expected:,.2f}, "
                     f"actual ${isr_provision:,.2f}, diferencia ${diff:,.2f}"
            ),
            details={
                "utilidad_fiscal": utilidad_fiscal,
                "expected": expected,
                "isr_provision": isr_provision,
                "diferencia": diff,
                "tasa": isr_rate,
            },
        )

    def validate_nomina_cuadrada(
        self,
        nominas: List[Dict[str, Any]],
    ) -> ValidationResult:
        """Check all payroll records are balanced (neto + deducciones = bruto)."""
        errors: List[str] = []
        for i, nom in enumerate(nominas):
            bruto = nom.get("sueldo_bruto", 0.0)
            deducciones = nom.get("total_deducciones", 0.0)
            neto = nom.get("sueldo_neto", 0.0)
            expected_neto = round(bruto - deducciones, 2)
            if abs(expected_neto - neto) > 0.01:
                errors.append(
                    f"Nómina #{i+1}: bruto ${bruto} - deducciones "
                    f"${deducciones} = ${expected_neto}, neto reportado ${neto}"
                )
        passed = len(errors) == 0
        return ValidationResult(
            type=ValidationType.NOMINA_CUADRADA,
            passed=passed,
            message=(
                f"{len(nominas)} nóminas cuadradas"
                if passed
                else f"{len(errors)} nóminas con desfase"
            ),
            details={
                "total_nominas": len(nominas),
                "errors": errors,
            },
            warnings=errors,
        )

    def validate_bancos_conciliados(
        self,
        match_rate: float,
        total_movements: int = 0,
        matched: int = 0,
    ) -> ValidationResult:
        """Check bank reconciliation match rate meets threshold."""
        rate_pct = round(match_rate * 100, 1) if match_rate <= 1 else round(match_rate, 1)
        passed = match_rate >= self.min_reconciliation_rate
        return ValidationResult(
            type=ValidationType.BANCOS_CONCILIADOS,
            passed=passed,
            message=(
                f"Bancos conciliados al {rate_pct}%"
                if passed
                else f"Bancos insuficientemente conciliados: {rate_pct}% "
                     f"(mínimo {self.min_reconciliation_rate*100:.0f}%)"
            ),
            details={
                "match_rate": match_rate,
                "total_movements": total_movements,
                "matched": matched,
                "threshold": self.min_reconciliation_rate,
            },
        )

    def validate_polizas_cuadradas(
        self,
        polizas: List[Dict[str, Any]],
    ) -> ValidationResult:
        """Check all journal entries balance (debe == haber)."""
        errors: List[str] = []
        for pol in polizas:
            debe = round(pol.get("total_debe", 0.0), 2)
            haber = round(pol.get("total_haber", 0.0), 2)
            if abs(debe - haber) > 0.01:
                errors.append(
                    f"Póliza {pol.get('id', '?')}: debe ${debe} ≠ haber ${haber}"
                )
        passed = len(errors) == 0
        return ValidationResult(
            type=ValidationType.POLIZAS_CUADRADAS,
            passed=passed,
            message=(
                f"{len(polizas)} pólizas cuadradas"
                if passed
                else f"{len(errors)} pólizas con desfase"
            ),
            details={
                "total_polizas": len(polizas),
                "errors": errors,
            },
            warnings=errors,
        )

    # ------------------------------------------------------------------
    # Run all
    # ------------------------------------------------------------------

    def run_all(
        self,
        balance_data: Optional[Dict[str, float]] = None,
        iva_data: Optional[Dict[str, float]] = None,
        isr_data: Optional[Dict[str, float]] = None,
        nominas: Optional[List[Dict[str, Any]]] = None,
        reconciliation_data: Optional[Dict[str, Any]] = None,
        polizas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ValidationResult]:
        """Run all available validations and return results."""
        results: List[ValidationResult] = []

        if balance_data:
            results.append(self.validate_balance_cuadrada(
                total_debe=balance_data.get("total_debe", 0.0),
                total_haber=balance_data.get("total_haber", 0.0),
            ))

        if iva_data:
            results.append(self.validate_iva_conciliado(
                iva_trasladado=iva_data.get("iva_trasladado", 0.0),
                iva_acreditable=iva_data.get("iva_acreditable", 0.0),
                iva_provisionado=iva_data.get("iva_provisionado", 0.0),
            ))

        if isr_data:
            results.append(self.validate_isr_provisionado(
                isr_provision=isr_data.get("isr_provision", 0.0),
                utilidad_fiscal=isr_data.get("utilidad_fiscal", 0.0),
            ))

        if nominas is not None:
            results.append(self.validate_nomina_cuadrada(nominas))

        if reconciliation_data:
            results.append(self.validate_bancos_conciliados(
                match_rate=reconciliation_data.get("match_rate", 0.0),
                total_movements=reconciliation_data.get("total_movements", 0),
                matched=reconciliation_data.get("matched", 0),
            ))

        if polizas is not None:
            results.append(self.validate_polizas_cuadradas(polizas))

        return results
