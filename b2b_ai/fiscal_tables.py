# -*- coding: utf-8 -*-
"""
fiscal_tables.py — Tablas fiscales centralizadas y versionadas.

Centraliza las tablas ISR, subsidio al empleo y UMA que se duplicaban en:
  - features/declaraciones/service.py (ISR_TABLE_MONTHLY, ISR_TABLE_ANNUAL)
  - services/payroll.py (TARIFA_ISR_2024_MENSUAL, TARIFA_ISR_2024_QUINCENAL)
  - features/compliance.py (ISR_TABLE_2024_MONTHLY, ISR_TABLE_2024_ANNUAL)

Cada tabla lleva el año fiscal al que corresponde. Los consumidores deben
importar de aquí en vez de definir sus propias copias.

Fuentes oficiales:
  - ISR: LISR Art. 96, Resolución Miscelánea Fiscal (RMF) Anexo 3
  - Subsidio: Tabla del subsidio para el empleo publicada por el SAT (DOF)
  - UMA: INEGI — publicado en DOF cada febrero

Última actualización: 2026 (DOF diciembre 2025).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Año fiscal vigente
# ---------------------------------------------------------------------------
FISCAL_YEAR = 2026

# ---------------------------------------------------------------------------
# Tarifa mensual ISR — LISR art. 96 (ejercicio fiscal 2025).
# Formato: (limite_inferior, limite_superior, cuota_fija, porcentaje_excedente)
# Fuente: RMF 2025, Anexo 3.
# ---------------------------------------------------------------------------
ISR_MENSUAL_2025: List[Tuple[float, float, float, float]] = [
    (0.00, 416.34, 0.00, 0.0192),
    (416.35, 3508.42, 7.99, 0.0640),
    (3508.43, 6145.58, 205.29, 0.1088),
    (6145.59, 7185.25, 492.98, 0.1600),
    (7185.26, 8564.67, 659.32, 0.2136),
    (8564.68, 17128.42, 952.82, 0.2352),
    (17128.43, 34256.83, 2963.16, 0.3000),
    (34256.84, 45675.74, 8099.64, 0.3200),
    (45675.75, 91351.48, 11753.69, 0.3400),
    (91351.49, float("inf"), 27285.41, 0.3500),
]

# ---------------------------------------------------------------------------
# Tarifa anual ISR — LISR art. 96 (ejercicio fiscal 2025).
# (limite_inferior, limite_superior, cuota_fija, porcentaje_excedente)
# ---------------------------------------------------------------------------
ISR_ANUAL_2025: List[Tuple[float, float, float, float]] = [
    (0.00, 4996.07, 0.00, 0.0192),
    (4996.08, 42101.07, 95.93, 0.0640),
    (42101.08, 73747.05, 2464.95, 0.1088),
    (73747.06, 86222.93, 5921.82, 0.1600),
    (86222.94, 102775.97, 7918.14, 0.2136),
    (102775.98, 205540.72, 11454.29, 0.2352),
    (205540.73, 411081.46, 35594.91, 0.3000),
    (411081.47, 548108.74, 97257.13, 0.3200),
    (548108.75, 1096217.44, 141065.88, 0.3400),
    (1096217.45, float("inf"), 327422.79, 0.3500),
]

# ---------------------------------------------------------------------------
# Tarifa quincenal ISR — tabla 2025 derivada de la mensual.
# Se calcula el ISR mensual equivalente y se divide entre 2 (LISR art. 96).
# ---------------------------------------------------------------------------
ISR_QUINCENAL_2025: List[Tuple[float, float, float, float]] = [
    (0.00, 208.17, 0.00, 0.0192),
    (208.18, 1754.21, 4.00, 0.0640),
    (1754.22, 3072.79, 102.65, 0.1088),
    (3072.80, 3592.63, 246.49, 0.1600),
    (3592.64, 4282.34, 329.66, 0.2136),
    (4282.35, 8564.21, 476.41, 0.2352),
    (8564.22, 17128.42, 1481.58, 0.3000),
    (17128.43, 22837.87, 4049.82, 0.3200),
    (22837.88, 45675.74, 5876.85, 0.3400),
    (45675.75, float("inf"), 13642.71, 0.3500),
]

# ---------------------------------------------------------------------------
# Subsidio para el empleo — LISR art. 174, Decreto DOF (2025).
# Formato: (ingreso_gravado_desde, ingreso_gravado_hasta, subsidio_mensual)
# Fuente: Tabla del subsidio para el empleo publicada por el SAT (DOF 2025).
# ---------------------------------------------------------------------------
SUBSIDIO_EMPLEO_MENSUAL_2025: List[Tuple[str, str, str]] = [
    ("0.01", "2169.53", "407.02"),
    ("2169.54", "3502.78", "406.83"),
    ("3502.79", "3861.48", "406.62"),
    ("3861.49", "4607.32", "392.77"),
    ("4607.33", "5090.80", "382.46"),
    ("5090.81", "6355.12", "354.24"),
    ("6355.13", "7470.57", "294.17"),
    ("7470.58", "8455.60", "253.54"),
    ("8455.61", "9912.54", "217.61"),
    ("9912.55", "11492.66", "209.13"),
    ("11492.67", "13493.97", "0.00"),
]
# NOTA: Los montos de subsidio por rango requieren verificación contra el
# decreto oficial del subsidio para el empleo 2026 (DOF). El ingreso
# máximo se actualizó a $11,492.66 según Anexo 8 RMF 2026.

# ---------------------------------------------------------------------------
# Subsidio quincenal 2025 — mitad del mensual.
# ---------------------------------------------------------------------------
SUBSIDIO_EMPLEO_QUINCENAL_2025: List[Tuple[str, str, str]] = [
    ("0.01", "1084.77", "203.51"),
    ("1084.78", "1751.39", "203.42"),
    ("1751.39", "1930.74", "203.31"),
    ("1930.75", "2303.66", "196.39"),
    ("2303.67", "2545.40", "191.23"),
    ("2545.41", "3177.56", "177.12"),
    ("3177.57", "3735.29", "147.09"),
    ("3735.30", "4227.80", "126.77"),
    ("4227.81", "4956.27", "108.81"),
    ("4956.28", "5820.88", "104.57"),
    ("5820.89", "6746.99", "0.00"),
]

# ---------------------------------------------------------------------------
# UMA (Unidad de Medida y Actualización) 2025
# Fuente: INEGI, publicado en DOF febrero 2025.
# ---------------------------------------------------------------------------
UMA_DIARIO_2025 = "113.15"
UMA_MENSUAL_2025 = "3439.54"
UMA_ANUAL_2025 = "41274.48"

# ---------------------------------------------------------------------------
# UMA (Unidad de Medida y Actualización) 2026
# Fuente: INEGI, publicado en DOF febrero 2026.
# ---------------------------------------------------------------------------
UMA_DIARIO_2026 = "117.31"
UMA_MENSUAL_2026 = "3566.22"
UMA_ANUAL_2026 = "42794.64"


# ---------------------------------------------------------------------------
# Tarifa mensual ISR — LISR art. 96 (ejercicio fiscal 2026).
# Fuente: Anexo 8 RMF 2026, Resolución Miscelánea Fiscal para 2026.
# ---------------------------------------------------------------------------
ISR_MENSUAL_2026: List[Tuple[float, float, float, float]] = [
    (0.01, 844.59, 0.00, 0.0192),
    (844.60, 7168.51, 16.22, 0.0640),
    (7168.52, 13074.34, 420.95, 0.1088),
    (13074.35, 16217.55, 1073.89, 0.1600),
    (16217.56, 22089.52, 1576.78, 0.2136),
    (22089.53, 36113.04, 2830.39, 0.2352),
    (36113.05, 66356.44, 6128.72, 0.3000),
    (66356.45, 96006.05, 15201.73, 0.3200),
    (96006.06, 133596.27, 24729.61, 0.3400),
    (133596.28, float("inf"), 37530.25, 0.3500),
]

# ---------------------------------------------------------------------------
# Tarifa anual ISR — LISR art. 96 (ejercicio fiscal 2026).
# Derivada de la tabla mensual ×12 (con redondeo).
# ---------------------------------------------------------------------------
ISR_ANUAL_2026: List[Tuple[float, float, float, float]] = [
    (0.01, 10135.08, 0.00, 0.0192),
    (10135.09, 86022.12, 194.64, 0.0640),
    (86022.13, 156892.08, 5051.40, 0.1088),
    (156892.09, 194610.60, 12886.68, 0.1600),
    (194610.61, 265074.24, 18921.36, 0.2136),
    (265074.25, 433356.48, 33964.68, 0.2352),
    (433356.49, 796277.28, 73544.64, 0.3000),
    (796277.29, 1152072.60, 182420.76, 0.3200),
    (1152072.61, 1603155.24, 296755.32, 0.3400),
    (1603155.25, float("inf"), 450363.00, 0.3500),
]

# ---------------------------------------------------------------------------
# Tarifa quincenal ISR — tabla 2026 derivada de la mensual.
# ---------------------------------------------------------------------------
ISR_QUINCENAL_2026: List[Tuple[float, float, float, float]] = [
    (0.01, 416.70, 0.00, 0.0192),
    (416.71, 3584.26, 8.11, 0.0640),
    (3584.27, 6537.17, 210.48, 0.1088),
    (6537.18, 8108.78, 536.95, 0.1600),
    (8108.79, 11044.76, 788.39, 0.2136),
    (11044.77, 18056.52, 1415.20, 0.2352),
    (18056.53, 33178.22, 3064.36, 0.3000),
    (33178.23, 48003.03, 7600.87, 0.3200),
    (48003.04, 66798.14, 12364.81, 0.3400),
    (66798.15, float("inf"), 18765.13, 0.3500),
]

# ---------------------------------------------------------------------------
# Subsidio para el empleo — LISR art. 174, Decreto DOF (2026).
# Los montos son los mismos que 2025 (el SAT no ha publicado nuevos).
# TODO: Actualizar si el DOF publica tabla nueva para 2026.
# ---------------------------------------------------------------------------
SUBSIDIO_EMPLEO_MENSUAL_2026: List[Tuple[str, str, str]] = [
    ("0.01", "2169.53", "407.02"),
    ("2169.54", "3502.78", "406.83"),
    ("3502.79", "3861.48", "406.62"),
    ("3861.49", "4607.32", "392.77"),
    ("4607.33", "5090.80", "382.46"),
    ("5090.81", "6355.12", "354.24"),
    ("6355.13", "7470.57", "294.17"),
    ("7470.58", "8455.60", "253.54"),
    ("8455.61", "9912.54", "217.61"),
    ("9912.55", "11492.66", "209.13"),
    ("11492.67", "13493.97", "0.00"),
]
# NOTA: Los montos de subsidio por rango requieren verificación contra el
# decreto oficial del subsidio para el empleo 2026 (DOF). El ingreso
# máximo se actualizó a $11,492.66 según Anexo 8 RMF 2026.

# ---------------------------------------------------------------------------
# Subsidio quincenal 2026 — mitad del mensual.
# ---------------------------------------------------------------------------
SUBSIDIO_EMPLEO_QUINCENAL_2026: List[Tuple[str, str, str]] = [
    ("0.01", "1084.77", "203.51"),
    ("1084.78", "1751.39", "203.42"),
    ("1751.39", "1930.74", "203.31"),
    ("1930.75", "2303.66", "196.39"),
    ("2303.67", "2545.40", "191.23"),
    ("2545.41", "3177.56", "177.12"),
    ("3177.57", "3735.29", "147.09"),
    ("3735.30", "4227.80", "126.77"),
    ("4227.81", "4956.27", "108.81"),
    ("4956.28", "5820.88", "104.57"),
    ("5820.89", "6746.99", "0.00"),
]

# ---------------------------------------------------------------------------
# Tablas legacy (2024) — mantener para cálculos de ejercicios anteriores.
# ---------------------------------------------------------------------------
ISR_MENSUAL_2024: List[Tuple[float, float, float, float]] = [
    (0.00, 312.41, 0.00, 0.0192),
    (312.42, 2636.28, 5.99, 0.0640),
    (2636.29, 4623.01, 154.29, 0.1088),
    (4623.02, 5409.82, 370.32, 0.1600),
    (5409.83, 6447.11, 496.04, 0.2136),
    (6447.12, 12904.06, 717.37, 0.2352),
    (12904.07, 25808.11, 2235.28, 0.3000),
    (25808.12, 34410.81, 6106.49, 0.3200),
    (34410.82, 68821.62, 8857.35, 0.3400),
    (68821.63, float("inf"), 20557.10, 0.3500),
]

ISR_ANUAL_2024: List[Tuple[float, float, float, float]] = [
    (0.00, 3748.57, 0.00, 0.0192),
    (3748.58, 31635.36, 71.92, 0.0640),
    (31635.37, 55476.12, 1851.62, 0.1088),
    (55476.13, 64917.85, 4443.84, 0.1600),
    (64917.86, 77365.32, 5952.52, 0.2136),
    (77365.33, 154854.73, 8608.45, 0.2352),
    (154854.74, 309709.48, 26823.35, 0.3000),
    (309709.49, 412946.06, 73267.78, 0.3200),
    (412946.07, 825892.12, 106293.69, 0.3400),
    (825892.13, float("inf"), 246695.13, 0.3500),
]


def get_isr_table(year: Optional[int] = None, period: str = "monthly"):
    """Get the ISR table for a given year and period.

    Args:
        year: Fiscal year (default: current FISCAL_YEAR).
        period: 'monthly', 'annual', or 'quincenal'.

    Returns:
        List of (limite_inferior, limite_superior, cuota_fija, porcentaje) tuples.
    """
    year = year or FISCAL_YEAR
    tables = {
        (2026, "monthly"): ISR_MENSUAL_2026,
        (2026, "annual"): ISR_ANUAL_2026,
        (2026, "quincenal"): ISR_QUINCENAL_2026,
        (2025, "monthly"): ISR_MENSUAL_2025,
        (2025, "annual"): ISR_ANUAL_2025,
        (2025, "quincenal"): ISR_QUINCENAL_2025,
        (2024, "monthly"): ISR_MENSUAL_2024,
        (2024, "annual"): ISR_ANUAL_2024,
    }
    key = (year, period)
    if key not in tables:
        raise ValueError(
            f"No hay tabla ISR para año={year}, periodo={period}. "
            f"Años disponibles: 2024, 2025, 2026"
        )
    return tables[key]


def get_subsidio_table(year: Optional[int] = None, period: str = "monthly"):
    """Get the subsidio al empleo table for a given year and period."""
    year = year or FISCAL_YEAR
    tables = {
        (2026, "monthly"): SUBSIDIO_EMPLEO_MENSUAL_2026,
        (2026, "quincenal"): SUBSIDIO_EMPLEO_QUINCENAL_2026,
        (2025, "monthly"): SUBSIDIO_EMPLEO_MENSUAL_2025,
        (2025, "quincenal"): SUBSIDIO_EMPLEO_QUINCENAL_2025,
    }
    key = (year, period)
    if key not in tables:
        raise ValueError(
            f"No hay tabla de subsidio para año={year}, periodo={period}."
        )
    return tables[key]
