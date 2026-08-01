# -*- coding: utf-8 -*-
"""
adjustment_policies.py — 13 automatic adjustment policy calculators.

Each function computes journal entries (pólizas de ajuste) for a given period
and returns an AdjustmentPolicy. Based on Mexican fiscal law:
  - LISR Art. 34-36 (depreciación)
  - LISR Art. 41 (amortización intangibles)
  - LFT Art. 76-78 (vacaciones, prima vacacional)
  - LFT Art. 87 (aguinaldo)
  - LISR Art. 9 (PTU)
  - LISR Art. 44-45 (ajuste por inflación)
  - Banxico TC oficial (diferencias cambiarias)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.close_management.models import (
    AdjustmentPolicy,
    AdjustmentType,
)


def _round2(v: float) -> float:
    """Round to 2 decimal places (MXN precision)."""
    return round(v, 2)


# ---------------------------------------------------------------------------
# 1. DEPRECIACIÓN — LISR Art. 34-36
# ---------------------------------------------------------------------------

# SAT maximum depreciation rates by asset type (annual %)
_DEPRECIATION_RATES = {
    "edificios": 0.05,
    "construcciones": 0.05,
    "maquinaria": 0.10,
    "equipo_transporte": 0.25,
    "equipo_computo": 0.30,
    "muebles_refacciones": 0.10,
    "herramientas": 0.25,
    "equipo_telefonico": 0.30,
    "equipo_de_oficina": 0.10,
}


def calculate_depreciacion(
    activos: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Calculate monthly depreciation for fixed assets.

    Args:
        activos: List of {cuenta_activo, cuenta_gasto, costo, tipo, vida_util_meses}
        periodo: YYYY-MM
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for activo in activos:
        costo = activo.get("costo", 0.0)
        tipo = activo.get("tipo", "maquinaria")
        # Use provided rate or look up SAT rate
        annual_rate = activo.get("tasa_anual", _DEPRECIATION_RATES.get(tipo, 0.10))
        monthly_depr = _round2(costo * annual_rate / 12)
        if monthly_depr <= 0:
            continue
        total += monthly_depr
        entries.append({
            "cuenta": activo.get("cuenta_gasto", "6120100"),
            "debe": monthly_depr,
            "haber": 0.0,
            "concepto": f"Depreciación mensual {tipo}",
        })
        entries.append({
            "cuenta": activo.get("cuenta_activo", "1500100"),
            "debe": 0.0,
            "haber": monthly_depr,
            "concepto": f"Depreciación acumulada {tipo}",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.DEPRECIACION,
        periodo=periodo,
        description=f"Depreciación mensual — {len(activos)} activos",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 2. AMORTIZACIÓN — LISR Art. 41 (max 10% anual)
# ---------------------------------------------------------------------------

def calculate_amortizacion(
    intangibles: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Calculate monthly amortization for intangible assets.

    Args:
        intangibles: List of {cuenta_gasto, cuenta_activo, costo, tasa_anual}
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for item in intangibles:
        costo = item.get("costo", 0.0)
        annual_rate = item.get("tasa_anual", 0.10)  # Max 10% per LISR Art. 41
        monthly = _round2(costo * annual_rate / 12)
        if monthly <= 0:
            continue
        total += monthly
        entries.append({
            "cuenta": item.get("cuenta_gasto", "6130100"),
            "debe": monthly,
            "haber": 0.0,
            "concepto": "Amortización de intangibles",
        })
        entries.append({
            "cuenta": item.get("cuenta_activo", "1550100"),
            "debe": 0.0,
            "haber": monthly,
            "concepto": "Amortización acumulada intangibles",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.AMORTIZACION,
        periodo=periodo,
        description=f"Amortización mensual — {len(intangibles)} intangibles",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 3. PROVISIÓN AGUINALDO — LFT Art. 87 (15 días / 12 meses)
# ---------------------------------------------------------------------------

def calculate_provision_aguinaldo(
    empleados: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Provision monthly aguinaldo accrual.

    Args:
        empleados: List of {salario_diario, cuenta_gasto, cuenta_provision}
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for emp in empleados:
        sd = emp.get("salario_diario", 0.0)
        monthly = _round2(sd * 15 / 12)  # 15 days / 12 months
        if monthly <= 0:
            continue
        total += monthly
        entries.append({
            "cuenta": emp.get("cuenta_gasto", "6110100"),
            "debe": monthly,
            "haber": 0.0,
            "concepto": "Provisión mensual aguinaldo",
        })
        entries.append({
            "cuenta": emp.get("cuenta_provision", "2110200"),
            "debe": 0.0,
            "haber": monthly,
            "concepto": "Provisión aguinaldo",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.PROVISION_AGUINALDO,
        periodo=periodo,
        description=f"Provisión aguinaldo — {len(empleados)} empleados",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 4. PROVISIÓN VACACIONES + PRIMA — LFT Art. 76-78
# ---------------------------------------------------------------------------

# Days of vacation by seniority (LFT Art. 76, 2023 reform)
_VACATION_DAYS = [
    (1, 12), (2, 14), (3, 16), (4, 18), (5, 20),
    (6, 22), (7, 24), (8, 26), (9, 28), (10, 30),
    (11, 32), (12, 34), (13, 36), (14, 38), (15, 40),
]


def _vacation_days_for_years(years: int) -> int:
    """Get vacation days based on years of seniority."""
    for threshold, days in _VACATION_DAYS:
        if years <= threshold:
            return days
    return 40  # Cap at 40 days for 15+ years


def calculate_provision_vacaciones(
    empleados: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Provision monthly vacation + prima vacacional accrual.

    Args:
        empleados: List of {salario_diario, antiguedad_anos, prima_pct,
                            cuenta_gasto, cuenta_provision}
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for emp in empleados:
        sd = emp.get("salario_diario", 0.0)
        years = emp.get("antiguedad_anos", 1)
        prima_pct = emp.get("prima_pct", 0.25)  # 25% legal minimum
        vac_days = _vacation_days_for_years(years)
        # Monthly accrual: (days * salary + prima) / 12
        monthly = _round2(vac_days * sd * (1 + prima_pct) / 12)
        if monthly <= 0:
            continue
        total += monthly
        entries.append({
            "cuenta": emp.get("cuenta_gasto", "6110200"),
            "debe": monthly,
            "haber": 0.0,
            "concepto": f"Provisión vacaciones + prima ({vac_days} días)",
        })
        entries.append({
            "cuenta": emp.get("cuenta_provision", "2110300"),
            "debe": 0.0,
            "haber": monthly,
            "concepto": "Provisión vacaciones y prima vacacional",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.PROVISION_VACACIONES,
        periodo=periodo,
        description=f"Provisión vacaciones — {len(empleados)} empleados",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 5. PROVISIÓN PTU — LISR Art. 9 (10% utilidad / 12)
# ---------------------------------------------------------------------------

def calculate_provision_ptu(
    utilidad_fiscal: float,
    periodo: str,
    cuenta_gasto: str = "6110400",
    cuenta_provision: str = "2110400",
) -> AdjustmentPolicy:
    """Provision monthly PTU (Participación de los Trabajadores).

    Only applies when there is positive fiscal utility.
    """
    if utilidad_fiscal <= 0:
        return AdjustmentPolicy(
            type=AdjustmentType.PROVISION_PTU,
            periodo=periodo,
            description="PTU no aplica — sin utilidad fiscal",
            entries=[],
            total_debe=0.0,
            total_haber=0.0,
            is_balanced=True,
        )

    monthly = _round2(utilidad_fiscal * 0.10 / 12)
    entries = [
        {"cuenta": cuenta_gasto, "debe": monthly, "haber": 0.0,
         "concepto": "Provisión mensual PTU"},
        {"cuenta": cuenta_provision, "debe": 0.0, "haber": monthly,
         "concepto": "Provisión PTU"},
    ]
    return AdjustmentPolicy(
        type=AdjustmentType.PROVISION_PTU,
        periodo=periodo,
        description=f"Provisión PTU — utilidad fiscal ${utilidad_fiscal:,.2f}",
        entries=entries,
        total_debe=monthly,
        total_haber=monthly,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 6. PROVISIÓN ISR — LISR Art. 14 (provisional monthly)
# ---------------------------------------------------------------------------

ISR_PM_RATE = 0.30


def calculate_provision_isr(
    utilidad_fiscal: float,
    periodo: str,
    tasa: float = ISR_PM_RATE,
    cuenta_gasto: str = "6200100",
    cuenta_provision: str = "2120100",
) -> AdjustmentPolicy:
    """Provision monthly ISR (Impuesto Sobre la Renta)."""
    base = max(0.0, utilidad_fiscal)
    isr = _round2(base * tasa)
    entries = [
        {"cuenta": cuenta_gasto, "debe": isr, "haber": 0.0,
         "concepto": "Provisión mensual ISR"},
        {"cuenta": cuenta_provision, "debe": 0.0, "haber": isr,
         "concepto": "Provisión ISR"},
    ]
    return AdjustmentPolicy(
        type=AdjustmentType.PROVISION_ISR,
        periodo=periodo,
        description=f"Provisión ISR {tasa*100:.0f}% — utilidad ${base:,.2f}",
        entries=entries,
        total_debe=isr,
        total_haber=isr,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 7. PROVISIÓN IMSS — employer social security contribution
# ---------------------------------------------------------------------------

# Approximate IMSS employer rates (2024-2026)
_IMSS_RATES = {
    "enfermedad_maternidad": 0.2040,
    "invalidez_vida": 0.0175,
    "cesantia_vejez": 0.0135,
    "riesgo_trabajo": 0.01,  # Variable by risk class
    "guarderias": 0.01,
    "infonavit": 0.05,
}


def calculate_provision_imss(
    empleados: List[Dict[str, Any]],
    periodo: str,
    rates: Optional[Dict[str, float]] = None,
) -> AdjustmentPolicy:
    """Provision monthly IMSS employer contributions.

    Args:
        empleados: List of {salario_diario_integrado, cuenta_gasto, cuenta_provision}
    """
    if rates is None:
        rates = _IMSS_RATES
    total_rate = sum(rates.values())

    entries: List[Dict[str, Any]] = []
    total = 0.0

    for emp in empleados:
        sdi = emp.get("salario_diario_integrado", 0.0)
        monthly = _round2(sdi * 30 * total_rate)
        if monthly <= 0:
            continue
        total += monthly
        entries.append({
            "cuenta": emp.get("cuenta_gasto", "6110500"),
            "debe": monthly,
            "haber": 0.0,
            "concepto": f"Provisión IMSS ({total_rate*100:.1f}%)",
        })
        entries.append({
            "cuenta": emp.get("cuenta_provision", "2110500"),
            "debe": 0.0,
            "haber": monthly,
            "concepto": "Provisión IMSS patronal",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.PROVISION_IMSS,
        periodo=periodo,
        description=f"Provisión IMSS patronal — {len(empleados)} empleados",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 8. AJUSTE POR INFLACIÓN — LISR Art. 44-45
# ---------------------------------------------------------------------------

def calculate_ajuste_inflacion(
    saldo_acumulado: float,
    factor_inpc: float,
    periodo: str,
    cuenta_gasto: str = "6300100",
    cuenta_ajuste: str = "1500200",
) -> AdjustmentPolicy:
    """Calculate inflation adjustment on cumulative balances.

    Args:
        saldo_acumulado: Previous balance to adjust
        factor_inpc: INPC factor for the period (e.g., 0.04 for 4%)
    """
    ajuste = _round2(saldo_acumulado * factor_inpc)
    if ajuste == 0:
        return AdjustmentPolicy(
            type=AdjustmentType.AJUSTE_INFLACION,
            periodo=periodo,
            description="Ajuste por inflación — sin efecto",
            entries=[],
            total_debe=0.0,
            total_haber=0.0,
            is_balanced=True,
        )
    if ajuste > 0:
        entries = [
            {"cuenta": cuenta_gasto, "debe": ajuste, "haber": 0.0,
             "concepto": "Ajuste por inflación (LISR Art. 44-45)"},
            {"cuenta": cuenta_ajuste, "debe": 0.0, "haber": ajuste,
             "concepto": "Ajuste por inflación acumulado"},
        ]
    else:
        # Deflation: reverse
        entries = [
            {"cuenta": cuenta_ajuste, "debe": abs(ajuste), "haber": 0.0,
             "concepto": "Ajuste por deflación acumulado"},
            {"cuenta": cuenta_gasto, "debe": 0.0, "haber": abs(ajuste),
             "concepto": "Ajuste por deflación (LISR Art. 44-45)"},
        ]

    abs_ajuste = abs(ajuste)
    return AdjustmentPolicy(
        type=AdjustmentType.AJUSTE_INFLACION,
        periodo=periodo,
        description=f"Ajuste por inflación — factor {factor_inpc*100:.2f}%",
        entries=entries,
        total_debe=abs_ajuste,
        total_haber=abs_ajuste,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 9. AJUSTE PREPAGOS — amortize prepaid expenses
# ---------------------------------------------------------------------------

def calculate_ajuste_prepagos(
    prepagos: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Amortize prepaid expenses for the period.

    Args:
        prepagos: List of {monto_total, meses_restantes, cuenta_gasto, cuenta_prepago}
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for prep in prepagos:
        monto = prep.get("monto_total", 0.0)
        months = max(1, prep.get("meses_restantes", 12))
        monthly = _round2(monto / months)
        if monthly <= 0:
            continue
        total += monthly
        entries.append({
            "cuenta": prep.get("cuenta_gasto", "6140100"),
            "debe": monthly,
            "haber": 0.0,
            "concepto": "Amortización prepagos",
        })
        entries.append({
            "cuenta": prep.get("cuenta_prepago", "1600100"),
            "debe": 0.0,
            "haber": monthly,
            "concepto": "Baja de prepagos amortizados",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.AJUSTE_PREPAGOS,
        periodo=periodo,
        description=f"Ajuste prepagos — {len(prepagos)} partidas",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 10. AJUSTE INVENTARIOS — PEPS/Promedio + NRV
# ---------------------------------------------------------------------------

def calculate_ajuste_inventarios(
    inventarios: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Adjust inventory valuation (write-down to NRV).

    Args:
        inventarios: List of {costo_original, valor_nrv, cuenta_costo, cuenta_inventario}
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for inv in inventarios:
        costo = inv.get("costo_original", 0.0)
        nrv = inv.get("valor_nrv", 0.0)
        diff = _round2(costo - nrv)
        if diff <= 0:
            continue  # NRV >= costo, no adjustment needed
        total += diff
        entries.append({
            "cuenta": inv.get("cuenta_costo", "6150100"),
            "debe": diff,
            "haber": 0.0,
            "concepto": "Ajuste inventario a NRV",
        })
        entries.append({
            "cuenta": inv.get("cuenta_inventario", "1150100"),
            "debe": 0.0,
            "haber": diff,
            "concepto": "Reducción de inventario a valor neto de realización",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.AJUSTE_INVENTARIOS,
        periodo=periodo,
        description=f"Ajuste inventarios — {len(inventarios)} artículos",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 11. DIFERENCIAS CAMBIARIAS — Banxico TC oficial
# ---------------------------------------------------------------------------

def calculate_diferencias_cambiarias(
    cuentas_fx: List[Dict[str, Any]],
    tc_oficial: float,
    periodo: str,
    cuenta_utilidad: str = "7200100",
    cuenta_perdida: str = "7200200",
) -> AdjustmentPolicy:
    """Calculate FX gains/losses on foreign currency balances.

    Args:
        cuentas_fx: List of {saldo_mn, saldo_fx, tc_registro, cuenta}
        tc_oficial: Official exchange rate from Banxico
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for cta in cuentas_fx:
        saldo_fx = cta.get("saldo_fx", 0.0)
        tc_reg = cta.get("tc_registro", tc_oficial)
        saldo_mn_original = _round2(saldo_fx * tc_reg)
        saldo_mn_actual = _round2(saldo_fx * tc_oficial)
        diff = _round2(saldo_mn_actual - saldo_mn_original)
        if diff == 0:
            continue
        total += abs(diff)
        if diff > 0:
            # Gain
            entries.append({
                "cuenta": cta.get("cuenta", "1100100"),
                "debe": diff,
                "haber": 0.0,
                "concepto": f"Utilidad cambiaria TC {tc_oficial}",
            })
            entries.append({
                "cuenta": cuenta_utilidad,
                "debe": 0.0,
                "haber": diff,
                "concepto": "Utilidad por diferencias cambiarias",
            })
        else:
            # Loss
            abs_diff = abs(diff)
            entries.append({
                "cuenta": cuenta_perdida,
                "debe": abs_diff,
                "haber": 0.0,
                "concepto": "Pérdida por diferencias cambiarias",
            })
            entries.append({
                "cuenta": cta.get("cuenta", "1100100"),
                "debe": 0.0,
                "haber": abs_diff,
                "concepto": f"Pérdida cambiaria TC {tc_oficial}",
            })

    total_debe = _round2(sum(e["debe"] for e in entries))
    total_haber = _round2(sum(e["haber"] for e in entries))
    return AdjustmentPolicy(
        type=AdjustmentType.DIFERENCIAS_CAMBIARIAS,
        periodo=periodo,
        description=f"Diferencias cambiarias — TC oficial {tc_oficial}",
        entries=entries,
        total_debe=total_debe,
        total_haber=total_haber,
        is_balanced=_round2(total_debe - total_haber) == 0.0,
    )


# ---------------------------------------------------------------------------
# 12. PROVISIÓN INCOBRABLES — Art. 46 LISR
# ---------------------------------------------------------------------------

# LISR Art. 46 aging buckets → max deductible %
_AGING_PCTS = {
    "0-30": 0.0,
    "31-60": 0.0,
    "61-90": 0.0,
    "91-120": 0.05,
    "121-180": 0.10,
    "181-240": 0.15,
    "241-360": 0.20,
    "360+": 0.25,
}


def calculate_provision_incobrables(
    cartera: List[Dict[str, Any]],
    periodo: str,
    aging_pcts: Optional[Dict[str, float]] = None,
) -> AdjustmentPolicy:
    """Provision for doubtful accounts based on aging.

    Args:
        cartera: List of {monto, dias_vencido, cuenta_gasto, cuenta_provision}
    """
    if aging_pcts is None:
        aging_pcts = _AGING_PCTS

    def _pct_for_days(dias: int) -> float:
        if dias <= 30:
            return aging_pcts.get("0-30", 0.0)
        elif dias <= 60:
            return aging_pcts.get("31-60", 0.0)
        elif dias <= 90:
            return aging_pcts.get("61-90", 0.0)
        elif dias <= 120:
            return aging_pcts.get("91-120", 0.05)
        elif dias <= 180:
            return aging_pcts.get("121-180", 0.10)
        elif dias <= 240:
            return aging_pcts.get("181-240", 0.15)
        elif dias <= 360:
            return aging_pcts.get("241-360", 0.20)
        else:
            return aging_pcts.get("360+", 0.25)

    entries: List[Dict[str, Any]] = []
    total = 0.0

    for item in cartera:
        dias = item.get("dias_vencido", 0)
        pct = _pct_for_days(dias)
        prov = _round2(item.get("monto", 0.0) * pct)
        if prov <= 0:
            continue
        total += prov
        entries.append({
            "cuenta": item.get("cuenta_gasto", "6160100"),
            "debe": prov,
            "haber": 0.0,
            "concepto": f"Provisión incobrables ({dias} días, {pct*100:.0f}%)",
        })
        entries.append({
            "cuenta": item.get("cuenta_provision", "1180100"),
            "debe": 0.0,
            "haber": prov,
            "concepto": "Provisión para cuentas incobrables",
        })

    total = _round2(total)
    return AdjustmentPolicy(
        type=AdjustmentType.PROVISION_INCOBRABLES,
        periodo=periodo,
        description=f"Provisión incobrables — {len(cartera)} partidas",
        entries=entries,
        total_debe=total,
        total_haber=total,
        is_balanced=True,
    )


# ---------------------------------------------------------------------------
# 13. VALUACIÓN INVERSIONES — semi-automatic, needs human review
# ---------------------------------------------------------------------------

def calculate_valuacion_inversiones(
    inversiones: List[Dict[str, Any]],
    periodo: str,
) -> AdjustmentPolicy:
    """Mark-to-market adjustment for investments (NIF C-9).

    NOTE: This is semi-automatic — the data is computed but the
    result should be flagged for human review before posting.

    Args:
        inversiones: List of {costo, valor_mercado, cuenta, cuenta_ajuste}
    """
    entries: List[Dict[str, Any]] = []
    total = 0.0

    for inv in inversiones:
        costo = inv.get("costo", 0.0)
        vm = inv.get("valor_mercado", 0.0)
        diff = _round2(vm - costo)
        if diff == 0:
            continue
        total += abs(diff)
        if diff > 0:
            entries.append({
                "cuenta": inv.get("cuenta", "1120100"),
                "debe": diff,
                "haber": 0.0,
                "concepto": "Ajuste alza inversiones",
            })
            entries.append({
                "cuenta": inv.get("cuenta_ajuste", "7100100"),
                "debe": 0.0,
                "haber": diff,
                "concepto": "Resultado por valuación inversiones",
            })
        else:
            abs_diff = abs(diff)
            entries.append({
                "cuenta": inv.get("cuenta_ajuste", "7100200"),
                "debe": abs_diff,
                "haber": 0.0,
                "concepto": "Resultado por valuación inversiones (baja)",
            })
            entries.append({
                "cuenta": inv.get("cuenta", "1120100"),
                "debe": 0.0,
                "haber": abs_diff,
                "concepto": "Ajuste baja inversiones",
            })

    total_debe = _round2(sum(e["debe"] for e in entries))
    total_haber = _round2(sum(e["haber"] for e in entries))
    return AdjustmentPolicy(
        type=AdjustmentType.VALUACION_INVERSIONES,
        periodo=periodo,
        description=f"Valuación inversiones — {len(inversiones)} posiciones (REVISAR)",
        entries=entries,
        total_debe=total_debe,
        total_haber=total_haber,
        is_balanced=_round2(total_debe - total_haber) == 0.0,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ADJUSTMENT_CALCULATORS = {
    AdjustmentType.DEPRECIACION: calculate_depreciacion,
    AdjustmentType.AMORTIZACION: calculate_amortizacion,
    AdjustmentType.PROVISION_AGUINALDO: calculate_provision_aguinaldo,
    AdjustmentType.PROVISION_VACACIONES: calculate_provision_vacaciones,
    AdjustmentType.PROVISION_PTU: calculate_provision_ptu,
    AdjustmentType.PROVISION_ISR: calculate_provision_isr,
    AdjustmentType.PROVISION_IMSS: calculate_provision_imss,
    AdjustmentType.AJUSTE_INFLACION: calculate_ajuste_inflacion,
    AdjustmentType.AJUSTE_PREPAGOS: calculate_ajuste_prepagos,
    AdjustmentType.AJUSTE_INVENTARIOS: calculate_ajuste_inventarios,
    AdjustmentType.DIFERENCIAS_CAMBIARIAS: calculate_diferencias_cambiarias,
    AdjustmentType.PROVISION_INCOBRABLES: calculate_provision_incobrables,
    AdjustmentType.VALUACION_INVERSIONES: calculate_valuacion_inversiones,
}
