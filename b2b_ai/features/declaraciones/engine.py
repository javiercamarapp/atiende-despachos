# -*- coding: utf-8 -*-
"""engine.py — DeclarationEngine: unified tax calculation engine.

Single source of truth for all ISR tables (unifies the 3 copies that existed
in compliance.py, declaraciones/service.py, and nominas).  Calculates:
  - ISR provisional (PM 30% flat rate, PF progressive table Art. 96 LISR)
  - IVA monthly (trasladado – acreditable)
  - IEPS (per-product tasa/tarifa)
  - DIOT aggregation (grouped by RFC + TipoOperacion)

CFF/LISR/LIVA/IEPS references embedded in each method.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ===================================================================
# UNIFIED ISR TABLES — LISR Art. 96 (2025)
# This is THE canonical copy.  compliance.py re-exports from here.
# FIS-07/FIS-023: Migrated from hardcoded 2024 to centralized 2025 tables.
# Legacy 2024 tables available in fiscal_tables.py for prior-year calculations.
# ===================================================================
from b2b_ai.fiscal_tables import (
    ISR_MENSUAL_2025, ISR_ANUAL_2025,
    get_isr_table as _get_isr_table,
)

# Monthly progressive table (LISR Art. 96, 2025)
ISR_TABLE_MONTHLY: List[Tuple[float, float, float, float]] = ISR_MENSUAL_2025

# Annual progressive table (LISR Art. 96, 2025)
ISR_TABLE_ANNUAL: List[Tuple[float, float, float, float]] = ISR_ANUAL_2025

# ISR PM flat rate (LISR Art. 9, personas morales)
ISR_PM_RATE = 0.30

# ISR PM mensual — RESICO / régimen simplificado de confianza (LISR Art. 206, 209).
# Tasa progresiva mensual aplicable a personas morales del régimen simplificado
# de confianza (RESICO). Formato: (limite_inferior, limite_superior, cuota_fija, tasa)
ISR_PM_MENSUAL_RESICO: List[Tuple[float, float, float, float]] = [
    (0.00,       25000.00,     0.0000, 0.010),
    (25000.01,   50000.00,   250.0000, 0.011),
    (50000.01,   83333.33,   525.0000, 0.015),
    (83333.34,   208333.33,  1025.0000, 0.020),
    (208333.34,  3500000.00, 3525.0000, 0.025),
    (3500000.01, float("inf"), 86799.1675, 0.030),
]

# IVA rates (LIVA Art. 1, 2, 2-A)
IVA_TASA_GENERAL = 0.16
IVA_TASA_FRONTERA = 0.08
IVA_TASA_CERO = 0.0

# IEPS tasa/tarifa por producto (Ley IEPS Art. 2)
IEPS_RATES: Dict[str, float] = {
    "cerveza": 0.265,
    "bebidas_alcoholosas": 0.265,
    "tabaco": 0.160,
    "cigarros": 0.160,
    "combustibles_fosiles": 0.300,  # variable; simplified
    "juegos_con_apuestas": 0.300,
    "bebidas_energizantes": 0.265,
    "bebidas_saborizadas": 0.08,
    "alimentos_altos_calorias": 0.08,
    "plaguicidas": 0.08,
}

# Generic RFCs that must NOT appear in DIOT (RMF 3.10.7)
GENERIC_RFCS = {
    "XAXX010101000",  # público en general PF
    "XEXX010101000",  # público en general extranjero
    "XAXX010101001",  # variant
}


# ===================================================================
# Data classes
# ===================================================================

@dataclass
class IsrResult:
    """Resultado del cálculo de ISR."""
    base_gravable: float
    isr_bruto: float
    tasa_efectiva: float
    tipo_contribuyente: str   # "PM" o "PF"
    tabla_aplicada: str       # "monthly" / "annual" / "pm_30%"
    isr_neto: float = 0.0     # después de pagos provisionales
    pagos_provisionales: float = 0.0
    referencia_legal: str = "LISR Art. 9 (PM) / Art. 96 (PF)"


@dataclass
class IvaResult:
    """Resultado del cálculo de IVA mensual."""
    iva_trasladado: float
    iva_acreditable: float
    iva_neto: float              # trasladado – acreditable
    saldo_favor: float = 0.0
    saldo_contra: float = 0.0
    proporcion_acreditable: float = 1.0
    referencia_legal: str = "LIVA Art. 5"


@dataclass
class IepsEntry:
    """Una línea IEPS por producto."""
    concepto: str
    producto_tipo: str
    base_gravable: float
    tasa: float
    ieps: float


@dataclass
class IepsResult:
    """Resultado del cálculo de IEPS."""
    entries: List[IepsEntry] = field(default_factory=list)
    total_ieps: float = 0.0
    referencia_legal: str = "Ley IEPS Art. 2"


@dataclass
class DiotRecord:
    """Un registro DIOT (agrupado por RFC + TipoOperacion)."""
    rfc_tercero: str
    nombre: str
    tipo_operacion: str      # "03", "06", etc. per RMF 3.10.7
    tipo_tercero: str = "05"  # 05=nacional
    tipo_documento: str = "01"  # 01=CFDI
    moneda: str = "MXN"
    tipo_cambio: float = 1.0
    num_reg_id_trib: str = ""
    fecha: str = ""
    monto_neto: float = 0.0
    iva_trasladado_16: float = 0.0
    iva_trasladado_0: float = 0.0
    iva_acreditable_16: float = 0.0
    iva_acreditable_0: float = 0.0
    iva_exento: float = 0.0
    iva_retenido: float = 0.0
    count: int = 0


@dataclass
class DiotResult:
    """Resultado de la generación DIOT."""
    records: List[DiotRecord] = field(default_factory=list)
    total_records: int = 0
    total_monto_neto: float = 0.0
    total_iva_trasladado: float = 0.0
    total_iva_acreditable: float = 0.0
    periodo: str = ""
    rfc_contribuyente: str = ""
    referencia_legal: str = "RMF 3.10.7 / CFF Art. 85"


# ===================================================================
# ISR Calculation
# ===================================================================

def _apply_isr_table(
    taxable_income: float,
    table: List[Tuple[float, float, float, float]],
) -> float:
    """Apply ISR progressive tax table.

    Uses bracket look-up: find the row where limite_inferior <= income
    and income < next_limite_inferior (or inf for last row).
    """
    if taxable_income <= 0:
        return 0.0

    for i, (lower, upper, fixed, rate) in enumerate(table):
        if i < len(table) - 1:
            next_lower = table[i + 1][0]
            if lower <= taxable_income < next_lower:
                excess = taxable_income - lower
                return round(fixed + excess * rate, 2)
        else:
            if taxable_income >= lower:
                excess = taxable_income - lower
                return round(fixed + excess * rate, 2)
    return 0.0


def calculate_isr_pf(
    base_gravable: float,
    annual: bool = False,
    pagos_provisionales: float = 0.0,
) -> IsrResult:
    """Calculate ISR for Persona Física using progressive table.

    LISR Art. 96 / Art. 152.
    """
    table = ISR_TABLE_ANNUAL if annual else ISR_TABLE_MONTHLY
    isr_bruto = _apply_isr_table(max(0, base_gravable), table)
    isr_neto = round(max(0, isr_bruto - pagos_provisionales), 2)
    tasa_efectiva = round(isr_bruto / base_gravable, 4) if base_gravable > 0 else 0.0

    return IsrResult(
        base_gravable=base_gravable,
        isr_bruto=isr_bruto,
        tasa_efectiva=tasa_efectiva,
        tipo_contribuyente="PF",
        tabla_aplicada="annual" if annual else "monthly",
        isr_neto=isr_neto,
        pagos_provisionales=pagos_provisionales,
    )


def calculate_isr_pm(
    utilidad_fiscal: float,
    pagos_provisionales: float = 0.0,
) -> IsrResult:
    """Calculate ISR for Persona Moral (flat 30%).

    LISR Art. 9: ISR PM = utilidad_fiscal × 30%.
    """
    utilidad = max(0, utilidad_fiscal)
    isr_bruto = round(utilidad * ISR_PM_RATE, 2)
    isr_neto = round(max(0, isr_bruto - pagos_provisionales), 2)

    return IsrResult(
        base_gravable=utilidad,
        isr_bruto=isr_bruto,
        tasa_efectiva=ISR_PM_RATE if utilidad > 0 else 0.0,
        tipo_contribuyente="PM",
        tabla_aplicada="pm_30%",
        isr_neto=isr_neto,
        pagos_provisionales=pagos_provisionales,
    )



def calculate_isr_pm_resico(
    ingreso_mensual: float,
    pagos_provisionales: float = 0.0,
) -> IsrResult:
    """Calculate ISR for Persona Moral bajo RESICO (tabla mensual progresiva).

    LISR Art. 206 y 209: régimen simplificado de confianza para personas
    morales — ISR mensual sobre ingreso acumulable con tasa progresiva.
    """
    ingreso = max(0, ingreso_mensual)
    isr_bruto = _apply_isr_table(ingreso, ISR_PM_MENSUAL_RESICO)
    isr_neto = round(max(0, isr_bruto - pagos_provisionales), 2)
    tasa_efectiva = round(isr_bruto / ingreso, 4) if ingreso > 0 else 0.0
    return IsrResult(
        base_gravable=ingreso,
        isr_bruto=isr_bruto,
        tasa_efectiva=tasa_efectiva,
        tipo_contribuyente="PM",
        tabla_aplicada="pm_resico",
        isr_neto=isr_neto,
        pagos_provisionales=pagos_provisionales,
        referencia_legal="LISR Art. 206, 209 (RESICO PM)",
    )


# ===================================================================
# IVA Calculation
# ===================================================================

def calculate_iva(
    iva_trasladado: float,
    iva_acreditable: float,
    ingresos_gravados: float = 0.0,
    ingresos_totales: float = 0.0,
) -> IvaResult:
    """Calculate monthly IVA.

    LIVA Art. 5:
      - IVA a pagar = trasladado – acreditable × proporcion
      - proporcion = ingresos_gravados / ingresos_totales
    """
    proporcion = 1.0
    if ingresos_totales > 0 and ingresos_gravados >= 0:
        proporcion = min(1.0, ingresos_gravados / ingresos_totales)

    iva_acred_ajustado = round(iva_acreditable * proporcion, 2)
    iva_neto = round(iva_trasladado - iva_acred_ajustado, 2)

    saldo_favor = max(0, -iva_neto)
    saldo_contra = max(0, iva_neto)

    return IvaResult(
        iva_trasladado=round(iva_trasladado, 2),
        iva_acreditable=round(iva_acred_ajustado, 2),
        iva_neto=iva_neto,
        saldo_favor=saldo_favor,
        saldo_contra=saldo_contra,
        proporcion_acreditable=round(proporcion, 4),
    )


# ===================================================================
# IEPS Calculation
# ===================================================================

def calculate_ieps(
    items: List[Dict[str, Any]],
) -> IepsResult:
    """Calculate IEPS for a list of products.

    Each item: {"concepto": str, "producto_tipo": str, "base_gravable": float}
    Uses IEPS_RATES lookup (Ley IEPS Art. 2).
    """
    entries: List[IepsEntry] = []
    total = 0.0

    for item in items:
        tipo = item.get("producto_tipo", "")
        base = float(item.get("base_gravable", 0))
        tasa = IEPS_RATES.get(tipo, 0.0)
        ieps = round(base * tasa, 2)
        total += ieps
        entries.append(IepsEntry(
            concepto=item.get("concepto", ""),
            producto_tipo=tipo,
            base_gravable=base,
            tasa=tasa,
            ieps=ieps,
        ))

    return IepsResult(entries=entries, total_ieps=round(total, 2))


# ===================================================================
# DIOT Aggregation
# ===================================================================

def is_generic_rfc(rfc: str) -> bool:
    """Check if RFC is a generic (público en general) RFC.

    RMF 3.10.7: generic RFCs must NOT be included in DIOT.
    """
    return rfc.strip().upper() in GENERIC_RFCS


def _map_iva_tipo(tasa_iva: float) -> str:
    """Map IVA rate to DIOT TipoOperacion (RMF 3.10.7).

    Valid TipoOperacion per SAT catalog (catalogs.py DIOT_TIPO_OPERACION):
      "03" — Actos gravados a tasa general 16%
      "06" — Actos gravados a tasa 0%
      "85" — Otros (exentos, no objeto, tasa 8% frontera)
    """
    if abs(tasa_iva - 0.16) < 0.001:
        return "03"  # Actos gravados a tasa general 16%
    elif abs(tasa_iva - 0.08) < 0.001:
        return "85"  # Frontera: "Otros" per SAT catalog (FIS-012)
    elif abs(tasa_iva) < 0.001:
        return "06"  # Actos gravados a tasa 0%
    return "85"  # Exempt/other → "Otros" (FIS-011 fix)


def aggregate_diot(
    invoices: List[Dict[str, Any]],
    rfc_contribuyente: str,
    periodo: str,
) -> DiotResult:
    """Aggregate invoices into DIOT records.

    Groups by (rfc_emisor, tipo_operacion) per RMF 3.10.7.
    Filters out generic RFCs (XAXX010101000 etc.).
    """
    groups: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {
        "nombre": "",
        "monto_neto": 0.0,
        "iva_trasladado_16": 0.0,
        "iva_trasladado_0": 0.0,
        "iva_acreditable_16": 0.0,
        "iva_acreditable_0": 0.0,
        "iva_exento": 0.0,
        "iva_retenido": 0.0,
        "count": 0,
        "moneda": "MXN",
        "tipo_cambio": 1.0,
        "fecha": "",
    })

    for inv in invoices:
        rfc = str(inv.get("rfc_emisor", "")).strip().upper()

        # RMF 3.10.7: skip generic RFCs
        if is_generic_rfc(rfc):
            continue

        subtotal = float(inv.get("subtotal", 0))
        iva_t = float(inv.get("iva_trasladado", 0))
        iva_a = float(inv.get("iva_acreditable", 0))
        tasa_iva = float(inv.get("tasa_iva", 0.16))
        tc = float(inv.get("tipo_cambio", 1.0))
        moneda = inv.get("moneda", "MXN")

        # Normalize to MXN
        neto_mxn = round(subtotal * tc, 2)
        iva_t_mxn = round(iva_t * tc, 2)
        iva_a_mxn = round(iva_a * tc, 2)

        tipo_op = _map_iva_tipo(tasa_iva)
        key = (rfc, tipo_op)

        g = groups[key]
        g["nombre"] = inv.get("nombre_emisor", g["nombre"])
        g["monto_neto"] += neto_mxn
        g["count"] += 1
        g["moneda"] = moneda
        g["tipo_cambio"] = tc
        g["fecha"] = inv.get("fecha", g["fecha"])

        if abs(tasa_iva - 0.16) < 0.001:
            g["iva_trasladado_16"] += iva_t_mxn
            g["iva_acreditable_16"] += iva_a_mxn
        elif abs(tasa_iva) < 0.001:
            g["iva_trasladado_0"] += iva_t_mxn
            g["iva_acreditable_0"] += iva_a_mxn
        else:
            # Exempt or other
            g["iva_exento"] += iva_t_mxn

    records: List[DiotRecord] = []
    for (rfc, tipo_op), g in sorted(groups.items()):
        records.append(DiotRecord(
            rfc_tercero=rfc,
            nombre=g["nombre"],
            tipo_operacion=tipo_op,
            moneda=g["moneda"],
            tipo_cambio=g["tipo_cambio"],
            fecha=g["fecha"],
            monto_neto=round(g["monto_neto"], 2),
            iva_trasladado_16=round(g["iva_trasladado_16"], 2),
            iva_trasladado_0=round(g["iva_trasladado_0"], 2),
            iva_acreditable_16=round(g["iva_acreditable_16"], 2),
            iva_acreditable_0=round(g["iva_acreditable_0"], 2),
            iva_exento=round(g["iva_exento"], 2),
            iva_retenido=round(g["iva_retenido"], 2),
            count=g["count"],
        ))

    return DiotResult(
        records=records,
        total_records=len(records),
        total_monto_neto=round(sum(r.monto_neto for r in records), 2),
        total_iva_trasladado=round(
            sum(r.iva_trasladado_16 + r.iva_trasladado_0 for r in records), 2
        ),
        total_iva_acreditable=round(
            sum(r.iva_acreditable_16 + r.iva_acreditable_0 for r in records), 2
        ),
        periodo=periodo,
        rfc_contribuyente=rfc_contribuyente,
    )


# ===================================================================
# DeclarationEngine — unified facade for all tax calculations
# ===================================================================

class DeclarationEngine:
    """Unified facade for the declaration engine.

    Wraps all module-level calculation functions into a single object
    for use by the API layer.

    Usage:
        engine = DeclarationEngine()
        isr = engine.calculate_isr_pm(utilidad_fiscal=100000)
        iva = engine.calculate_iva(iva_trasladado=16000, iva_acreditable=8000)
        diot = engine.aggregate_diot(invoices=[...], rfc_contribuyente="ABC", periodo="2024-07")
    """

    def calculate_isr_pm(
        self,
        utilidad_fiscal: float,
        pagos_provisionales: float = 0.0,
    ) -> IsrResult:
        return calculate_isr_pm(utilidad_fiscal, pagos_provisionales)

    def calculate_isr_pm_resico(
        self,
        ingreso_mensual: float,
        pagos_provisionales: float = 0.0,
    ) -> IsrResult:
        return calculate_isr_pm_resico(ingreso_mensual, pagos_provisionales)

    def calculate_isr_pf(
        self,
        base_gravable: float,
        annual: bool = False,
        pagos_provisionales: float = 0.0,
    ) -> IsrResult:
        return calculate_isr_pf(base_gravable, annual, pagos_provisionales)

    def calculate_iva(
        self,
        iva_trasladado: float,
        iva_acreditable: float,
        ingresos_gravados: float = 0.0,
        ingresos_totales: float = 0.0,
    ) -> IvaResult:
        return calculate_iva(
            iva_trasladado, iva_acreditable,
            ingresos_gravados, ingresos_totales,
        )

    def calculate_ieps(
        self,
        items: List[Dict[str, Any]],
    ) -> IepsResult:
        return calculate_ieps(items)

    def aggregate_diot(
        self,
        invoices: List[Dict[str, Any]],
        rfc_contribuyente: str,
        periodo: str,
    ) -> DiotResult:
        return aggregate_diot(invoices, rfc_contribuyente, periodo)

    @staticmethod
    def get_isr_table(annual: bool = False) -> List[Tuple[float, float, float, float]]:
        return ISR_TABLE_ANNUAL if annual else ISR_TABLE_MONTHLY

    @staticmethod
    def get_ieps_rates() -> Dict[str, float]:
        return dict(IEPS_RATES)


# ===================================================================
# Legacy compatibility: re-export tables with original names
# ===================================================================

# For backwards compat with code importing from compliance.py
ISR_TABLE_2024_MONTHLY = ISR_TABLE_MONTHLY
ISR_TABLE_2024_ANNUAL = ISR_TABLE_ANNUAL
