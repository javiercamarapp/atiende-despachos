# -*- coding: utf-8 -*-
"""
service.py — ReconciliacionIngresosEgresosService: conciliación de ingresos
y egresos con auxiliares contables para despachos contables mexicanos.

This service:
  - Collects bank deposits and auxiliary accounting entries
  - Classifies deposits (income, financing, partner contributions, guarantees, other)
  - Matches deposits with auxiliary entries
  - Detects discrepancies between bank and accounting data
  - Calculates IVA balance
  - Generates working papers for tax auditor review
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    AuxiliarContable,
    BalanceIVA,
    ClasificacionDeposito,
    ClasificacionDepositoResult,
    ConciliacionIngresosEgresos,
    DepositoBancario,
    DiscrepanciaFiscal,
    MovimientoAuxiliar,
    PapelTrabajoConciliacion,
    SeccionResumen,
    Severidad,
    TipoDiscrepancia,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.classification_rules import (
    ClassificationEngine,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.validators import (
    validate_auxiliar_contable,
    validate_balance_iva,
    validate_deposito,
    validate_periodo,
)


class ReconciliacionIngresosEgresosService:
    """Core service for Income/Expense Reconciliation.

    Manages the complete reconciliation lifecycle:
      1. Data collection (deposits, auxiliaries)
      2. Classification (rule engine)
      3. Conciliation (matching)
      4. Discrepancy detection
      5. IVA balance calculation
      6. Working paper generation
    """

    def __init__(self, classification_engine: Optional[ClassificationEngine] = None):
        self._engine = classification_engine or ClassificationEngine()
        self._conciliaciones: Dict[str, ConciliacionIngresosEgresos] = {}
        self._papeles_trabajo: Dict[str, PapelTrabajoConciliacion] = {}

    # -------------------------------------------------------------------
    # Step 1: Collect data
    # -------------------------------------------------------------------

    def recopilar_depositos(
        self,
        periodo: str,
        tenant_id: Optional[str],
        depositos_data: List[dict],
    ) -> List[DepositoBancario]:
        """Collect and validate bank deposits for a period.

        Parameters
        ----------
        periodo : str
            Period (YYYY-MM).
        tenant_id : Optional[str]
            Tenant identifier.
        depositos_data : List[dict]
            Raw deposit data (id, fecha, monto, descripcion, referencia, banco, cuenta, es_credito).

        Returns
        -------
        List[DepositoBancario]
            Validated deposits.
        """
        depositos: List[DepositoBancario] = []
        for d in depositos_data:
            dep = DepositoBancario(
                id=d.get("id", ""),
                fecha=d.get("fecha", ""),
                monto=float(d.get("monto", 0.0)),
                descripcion=d.get("descripcion", ""),
                referencia=d.get("referencia", ""),
                banco=d.get("banco", ""),
                cuenta=d.get("cuenta", ""),
                es_credito=d.get("es_credito", True),
            )
            is_valid, err = validate_deposito(dep)
            if is_valid:
                depositos.append(dep)
        return depositos

    def recopilar_auxiliares(
        self,
        periodo: str,
        tenant_id: Optional[str],
        auxiliares_data: List[dict],
    ) -> List[AuxiliarContable]:
        """Collect and validate auxiliary accounting entries for a period.

        Parameters
        ----------
        periodo : str
            Period (YYYY-MM).
        tenant_id : Optional[str]
            Tenant identifier.
        auxiliares_data : List[dict]
            Raw auxiliary data (cuenta_id, cuenta_mayor, cuenta_auxiliar,
            descripcion, saldo_inicial, movimientos, saldo_final).

        Returns
        -------
        List[AuxiliarContable]
            Validated auxiliaries.
        """
        auxiliares: List[AuxiliarContable] = []
        for a in auxiliares_data:
            movimientos = []
            for m in a.get("movimientos", []):
                movimientos.append(MovimientoAuxiliar(
                    fecha=m.get("fecha", ""),
                    concepto=m.get("concepto", ""),
                    debe=float(m.get("debe", 0.0)),
                    haber=float(m.get("haber", 0.0)),
                    referencia=m.get("referencia", ""),
                    tipo=m.get("tipo", "ingreso"),
                ))
            aux = AuxiliarContable(
                cuenta_id=a.get("cuenta_id", ""),
                cuenta_mayor=a.get("cuenta_mayor", ""),
                cuenta_auxiliar=a.get("cuenta_auxiliar", ""),
                descripcion=a.get("descripcion", ""),
                saldo_inicial=float(a.get("saldo_inicial", 0.0)),
                movimientos=movimientos,
                saldo_final=float(a.get("saldo_final", 0.0)),
            )
            is_valid, err = validate_auxiliar_contable(aux)
            if is_valid:
                auxiliares.append(aux)
        return auxiliares

    # -------------------------------------------------------------------
    # Step 2: Classify deposits
    # -------------------------------------------------------------------

    def clasificar_deposito(
        self,
        deposito: DepositoBancario,
        auxiliares: List[AuxiliarContable],
    ) -> ClasificacionDepositoResult:
        """Classify a single deposit using the rule engine.

        Parameters
        ----------
        deposito : DepositoBancario
            The deposit to classify.
        auxiliares : List[AuxiliarContable]
            Available auxiliary entries for matching.

        Returns
        -------
        ClasificacionDepositoResult
        """
        classification, confidence, reason, articulo = self._engine.classify(
            deposito, auxiliares
        )

        requires_review = confidence < 0.7

        return ClasificacionDepositoResult(
            deposito_id=deposito.id,
            clasificacion=classification,
            confianza=confidence,
            razon=reason or "",
            articulo_cff=articulo,
            requires_human_review=requires_review,
        )

    def clasificar_todos(
        self,
        depositos: List[DepositoBancario],
        auxiliares: List[AuxiliarContable],
    ) -> List[ClasificacionDepositoResult]:
        """Classify all deposits using the rule engine.

        Parameters
        ----------
        depositos : List[DepositoBancario]
            Deposits to classify.
        auxiliares : List[AuxiliarContable]
            Available auxiliary entries.

        Returns
        -------
        List[ClasificacionDepositoResult]
        """
        return [
            self.clasificar_deposito(dep, auxiliares)
            for dep in depositos
        ]

    # -------------------------------------------------------------------
    # Step 3: Conciliate
    # -------------------------------------------------------------------

    def conciliar_depositos_auxiliares(
        self,
        depositos: List[DepositoBancario],
        auxiliares: List[AuxiliarContable],
    ) -> ConciliacionIngresosEgresos:
        """Match deposits with auxiliary accounting entries.

        Matching strategy:
          - Exact match by reference
          - Amount match within tolerance (±0.01)
          - Date proximity (±1 day)

        Parameters
        ----------
        depositos : List[DepositoBancario]
            Bank deposits.
        auxiliares : List[AuxiliarContable]
            Auxiliary entries.

        Returns
        -------
        ConciliacionIngresosEgresos
        """
        clasificaciones = self.clasificar_todos(depositos, auxiliares)
        discrepancias = self._detectar_discrepancias(depositos, auxiliares, clasificaciones)

        saldo_bancario = sum(d.monto for d in depositos if d.es_credito)
        saldo_contable = sum(a.saldo_final for a in auxiliares)

        return ConciliacionIngresosEgresos(
            periodo="",
            depositos=depositos,
            auxiliares=auxiliares,
            clasificaciones=clasificaciones,
            discrepancias=discrepancias,
            saldo_bancario=saldo_bancario,
            saldo_contable=saldo_contable,
            diferencia=saldo_bancario - saldo_contable,
        )

    def detectar_discrepancias(
        self,
        conciliacion: ConciliacionIngresosEgresos,
    ) -> List[DiscrepanciaFiscal]:
        """Find mismatches between bank deposits and auxiliary entries.

        Parameters
        ----------
        conciliacion : ConciliacionIngresosEgresos
            The reconciliation to analyze.

        Returns
        -------
        List[DiscrepanciaFiscal]
        """
        return conciliacion.discrepancias

    def _detectar_discrepancias(
        self,
        depositos: List[DepositoBancario],
        auxiliares: List[AuxiliarContable],
        clasificaciones: List[ClasificacionDepositoResult],
    ) -> List[DiscrepanciaFiscal]:
        """Internal: detect discrepancies between deposits and auxiliaries."""
        discrepancies: List[DiscrepanciaFiscal] = []

        # Build movement lookup by reference
        movimientos_by_ref: Dict[str, List[tuple]] = {}
        for aux in auxiliares:
            for mov in aux.movimientos:
                ref = mov.referencia.strip().upper()
                if ref:
                    movimientos_by_ref.setdefault(ref, []).append((aux, mov))

        # Check for deposits without matching auxiliary entries
        clas_map = {c.deposito_id: c for c in clasificaciones}
        for dep in depositos:
            ref = dep.referencia.strip().upper()
            if ref and ref not in movimientos_by_ref:
                clas = clas_map.get(dep.id)
                severity = Severidad.ALTA if clas and clas.clasificacion == ClasificacionDeposito.INGRESO else Severidad.MEDIA
                discrepancies.append(DiscrepanciaFiscal(
                    tipo=TipoDiscrepancia.FALTA_DOCUMENTACION,
                    deposito_id=dep.id,
                    monto_afectado=dep.monto,
                    descripcion=(
                        f"Depósito '{dep.id}' (monto: {dep.monto:.2f}, referencia: '{dep.referencia}') "
                        f"no tiene movimiento asociado en auxiliares contables."
                    ),
                    severidad=severity,
                ))

        # Check for amount mismatches on matched references
        for ref, mov_list in movimientos_by_ref.items():
            for dep in depositos:
                if dep.referencia.strip().upper() == ref:
                    for aux, mov in mov_list:
                        total_haber = mov.haber
                        if abs(dep.monto - total_haber) > 0.01:
                            discrepancies.append(DiscrepanciaFiscal(
                                tipo=TipoDiscrepancia.MONTO,
                                deposito_id=dep.id,
                                auxiliar_id=aux.cuenta_id,
                                monto_afectado=abs(dep.monto - total_haber),
                                descripcion=(
                                    f"Monto del depósito ({dep.monto:.2f}) difiere del "
                                    f"haber en auxiliar ({total_haber:.2f}) para referencia '{ref}'. "
                                    f"Diferencia: {abs(dep.monto - total_haber):.2f}."
                                ),
                                severidad=Severidad.MEDIA,
                            ))

        # Check for date mismatches
        for dep in depositos:
            ref = dep.referencia.strip().upper()
            if ref in movimientos_by_ref:
                for aux, mov in movimientos_by_ref[ref]:
                    if dep.fecha and mov.fecha and dep.fecha != mov.fecha:
                        discrepancies.append(DiscrepanciaFiscal(
                            tipo=TipoDiscrepancia.FECHA,
                            deposito_id=dep.id,
                            auxiliar_id=aux.cuenta_id,
                            monto_afectado=0.0,
                            descripcion=(
                                f"Fecha del depósito ({dep.fecha}) difiere de la fecha "
                                f"en auxiliar ({mov.fecha}) para referencia '{ref}'."
                            ),
                            severidad=Severidad.BAJA,
                        ))

        return discrepancies

    # -------------------------------------------------------------------
    # Step 3b: IVA balance
    # -------------------------------------------------------------------

    def calcular_balance_iva(
        self,
        declaraciones: List[dict],
        depositos_clasificados: List[ClasificacionDepositoResult],
        depositos: List[DepositoBancario],
    ) -> BalanceIVA:
        """Calculate IVA balance from declarations and classified deposits.

        Parameters
        ----------
        declaraciones : List[dict]
            Declaration data (iva_cobrado, iva_pagado, declarado).
        depositos_clasificados : List[ClasificacionDepositoResult]
            Classified deposits.
        depositos : List[DepositoBancario]
            Original deposits.

        Returns
        -------
        BalanceIVA
        """
        # Sum IVA from declarations
        iva_cobrado = sum(float(d.get("iva_cobrado", 0)) for d in declaraciones)
        iva_pagado = sum(float(d.get("iva_pagado", 0)) for d in declaraciones)
        declarado = sum(float(d.get("declarado", 0)) for d in declaraciones)

        # Calculate derived values
        iva_acreditable = max(0.0, iva_pagado - iva_cobrado)
        saldo_favor = max(0.0, iva_pagado - iva_cobrado)
        saldo_contra = max(0.0, iva_cobrado - iva_pagado)
        discrepancia = abs((iva_cobrado - iva_pagado) - declarado)

        return BalanceIVA(
            iva_cobrado=iva_cobrado,
            iva_pagado=iva_pagado,
            iva_acreditable=iva_acreditable,
            saldo_favor=saldo_favor,
            saldo_contra=saldo_contra,
            declarado=declarado,
            discrepancia=discrepancia,
        )

    # -------------------------------------------------------------------
    # Step 4: Generate working paper
    # -------------------------------------------------------------------

    def generar_papel_trabajo(
        self,
        conciliacion: ConciliacionIngresosEgresos,
        clasificaciones: List[ClasificacionDepositoResult],
        balance_iva: Optional[BalanceIVA] = None,
    ) -> PapelTrabajoConciliacion:
        """Generate a working paper for tax auditor review.

        Sections:
          1. Resumen (Summary)
          2. Clasificación de depósitos
          3. Conciliación bancaria vs contable
          4. Balance IVA
          5. Discrepancias
          6. Conclusiones

        Parameters
        ----------
        conciliacion : ConciliacionIngresosEgresos
            The reconciliation result.
        clasificaciones : List[ClasificacionDepositoResult]
            Classification results.
        balance_iva : Optional[BalanceIVA]
            IVA balance (optional).

        Returns
        -------
        PapelTrabajoConciliacion
        """
        # Build summary
        resumen = [
            SeccionResumen(
                titulo="Resumen de Conciliación",
                contenido=(
                    f"Período: {conciliacion.periodo or 'N/A'}. "
                    f"Total depósitos: {len(conciliacion.depositos)}. "
                    f"Total auxiliares: {len(conciliacion.auxiliares)}. "
                    f"Discrepancias: {len(conciliacion.discrepancias)}."
                ),
                total_depositos=len(conciliacion.depositos),
                total_auxiliares=len(conciliacion.auxiliares),
            ),
            SeccionResumen(
                titulo="Clasificación de Depósitos",
                contenido=self._resumen_clasificaciones(clasificaciones),
            ),
            SeccionResumen(
                titulo="Conciliación Bancaria vs Contable",
                contenido=(
                    f"Saldo bancario: ${conciliacion.saldo_bancario:,.2f}. "
                    f"Saldo contable: ${conciliacion.saldo_contable:,.2f}. "
                    f"Diferencia: ${conciliacion.diferencia:,.2f}."
                ),
            ),
        ]

        if balance_iva:
            resumen.append(SeccionResumen(
                titulo="Balance IVA",
                contenido=(
                    f"IVA cobrado: ${balance_iva.iva_cobrado:,.2f}. "
                    f"IVA pagado: ${balance_iva.iva_pagado:,.2f}. "
                    f"Saldo a favor: ${balance_iva.saldo_favor:,.2f}. "
                    f"Saldo en contra: ${balance_iva.saldo_contra:,.2f}. "
                    f"Declarado: ${balance_iva.declarado:,.2f}. "
                    f"Discrepancia: ${balance_iva.discrepancia:,.2f}."
                ),
            ))

        # Build conclusions
        conclusions: List[str] = []
        total_discrepancies = len(conciliacion.discrepancias)
        if total_discrepancies == 0:
            conclusions.append(
                "No se encontraron discrepancias. Los depósitos bancarios "
                "concilian con los auxiliares contables."
            )
        else:
            conclusions.append(
                f"Se encontraron {total_discrepancies} discrepancia(s) que "
                f"requieren revisión."
            )

        # Count by classification type
        by_type: Dict[str, int] = {}
        for c in clasificaciones:
            by_type[c.clasificacion.value] = by_type.get(c.clasificacion.value, 0) + 1
        for ctype, count in by_type.items():
            conclusions.append(f"Depósitos clasificados como '{ctype}': {count}.")

        if balance_iva and balance_iva.discrepancia > 0:
            conclusions.append(
                f"Existe discrepancia de ${balance_iva.discrepancia:,.2f} "
                f"en el balance de IVA declarado vs calculado."
            )

        requires_review = any(c.requires_human_review for c in clasificaciones) or total_discrepancies > 0

        papel = PapelTrabajoConciliacion(
            periodo=conciliacion.periodo,
            tenant_id=conciliacion.tenant_id,
            resumen=resumen,
            clasificaciones=clasificaciones,
            discrepancias=conciliacion.discrepancias,
            balanceiva=[balance_iva] if balance_iva else [],
            conclusiones=conclusions,
            requires_human_review=requires_review,
            created_at=datetime.now().isoformat(),
        )

        key = f"{conciliacion.periodo}_{conciliacion.tenant_id or 'default'}"
        self._papeles_trabajo[key] = papel

        return papel

    def get_papel_trabajo(self, periodo: str, tenant_id: Optional[str] = None) -> Optional[PapelTrabajoConciliacion]:
        """Retrieve a working paper by period and tenant."""
        key = f"{periodo}_{tenant_id or 'default'}"
        return self._papeles_trabajo.get(key)

    def get_conciliacion(self, periodo: str, tenant_id: Optional[str] = None) -> Optional[ConciliacionIngresosEgresos]:
        """Retrieve a reconciliation by period and tenant."""
        key = f"{periodo}_{tenant_id or 'default'}"
        return self._conciliaciones.get(key)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _resumen_clasificaciones(self, clasificaciones: List[ClasificacionDepositoResult]) -> str:
        """Build a human-readable summary of classifications."""
        if not clasificaciones:
            return "No hay clasificaciones registradas."

        by_type: Dict[str, int] = {}
        for c in clasificaciones:
            by_type[c.clasificacion.value] = by_type.get(c.clasificacion.value, 0) + 1

        parts = [f"{count} depósito(s) como '{ctype}'" for ctype, count in by_type.items()]
        return "Clasificación: " + "; ".join(parts) + "."
