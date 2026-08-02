# -*- coding: utf-8 -*-
"""
reconciliacion_ingresos_egresos — Módulo de conciliación de ingresos y egresos
para despachos contables mexicanos.

Reconcilia depósitos bancarios con auxiliares contables para:
  1. Clasificar depósitos: ingreso, financiamiento, aportación de socio,
     garantía, otro no gravable
  2. Detectar discrepancias bancarias vs contables
  3. Calcular balance de IVA
  4. Generar papel de trabajo para revisión del auditor fiscal
"""
from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    ClasificacionDeposito,
    TipoDiscrepancia,
    Severidad,
    DepositoBancario,
    AuxiliarContable,
    MovimientoAuxiliar,
    ClasificacionDepositoResult,
    ConciliacionIngresosEgresos,
    DiscrepanciaFiscal,
    BalanceIVA,
    PapelTrabajoConciliacion,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.validators import (
    validate_deposito,
    validate_auxiliar_contable,
    validate_clasificacion,
    validate_balance_iva,
    validate_periodo,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.classification_rules import (
    Rule,
    ClassificationEngine,
    DEFAULT_RULES,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.routes import (
    build_reconciliacion_ingresos_egresos_router,
)

__all__ = [
    # Enums
    "ClasificacionDeposito",
    "TipoDiscrepancia",
    "Severidad",
    # Models
    "DepositoBancario",
    "AuxiliarContable",
    "MovimientoAuxiliar",
    "ClasificacionDepositoResult",
    "ConciliacionIngresosEgresos",
    "DiscrepanciaFiscal",
    "BalanceIVA",
    "PapelTrabajoConciliacion",
    # Service
    "ReconciliacionIngresosEgresosService",
    # Validators
    "validate_deposito",
    "validate_auxiliar_contable",
    "validate_clasificacion",
    "validate_balance_iva",
    "validate_periodo",
    # Classification rules
    "Rule",
    "ClassificationEngine",
    "DEFAULT_RULES",
    # Router
    "build_reconciliacion_ingresos_egresos_router",
]
