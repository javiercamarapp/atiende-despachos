# -*- coding: utf-8 -*-
"""
service.py — ConciliationService: matching algorithm, discrepancy detection,
adjustment proposals, reports, and CSV export.

Matching strategy (priority order):
  1. EXACT — identical amount on the same date
  2. AMOUNT_DATE — same amount within a date tolerance (±N days)
  3. PARTIAL_REFERENCE — reference number contains a substring match
  4. AMOUNT_ONLY — same amount regardless of date (lowest confidence)

Confidence scores:
  - EXACT: 1.0
  - AMOUNT_DATE: 0.8 (decreases with date distance)
  - PARTIAL_REFERENCE: 0.6 (decreases with reference similarity)
  - AMOUNT_ONLY: 0.4 (decreases with date distance)

Discrepancy detection:
  - Flags any matched pair where |bank_amount - poliza_amount| > threshold.
  - Identifies missing entries (faltante/sobrante).
  - Detects duplicate transactions.

Adjustment proposals:
  - For monto discrepancies: proposes correction entries.
  - For faltante entries: proposes missing poliza creation.
  - For sobrante entries: proposes void or reclassification.
"""
from __future__ import annotations

import csv
import io
import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.conciliacion.models import (
    Adjustment,
    AdjustmentStatus,
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    Discrepancy,
    DiscrepancyType,
    MatchResult,
    MatchStatus,
    MatchType,
    PolizaContable,
    TransactionType,
)
from b2b_ai.features.compliance import (
    FiscalOutput, AuditTrail, sanitize_string, mask_rfc,
    verify_tenant_access, SafeError, SAFE_ERRORS, ManualProcessMixin,
)


class ConciliationService(ManualProcessMixin):
    """Core service for bank reconciliation."""

    def __init__(
        self,
        date_tolerance_days: int = 3,
        discrepancy_threshold: float = 0.02,
        amount_tolerance: float = 0.01,
    ):
        """
        Parameters
        ----------
        date_tolerance_days : int
            Maximum days of difference for AMOUNT_DATE matching (default 3).
        discrepancy_threshold : float
            Fractional variance threshold to flag a discrepancy (default 0.02 = 2%).
        amount_tolerance : float
            Fractional tolerance for amount-only matching (default 0.01 = 1%).
        """
        super().__init__()
        self.date_tolerance_days = date_tolerance_days
        self.discrepancy_threshold = discrepancy_threshold
        self.amount_tolerance = amount_tolerance

    # -------------------------------------------------------------------
    # Core reconciliation method
    # -------------------------------------------------------------------

    def reconcile_bank_statement(
        self,
        transactions: List[BankTransaction],
        polizas: Optional[List[PolizaContable]] = None,
        cfdi_list: Optional[List[CFDIReference]] = None,
        tolerance_days: int = 3,
    ) -> Dict[str, Any]:
        """
        Full bank reconciliation pipeline.

        Matches bank transactions against polizas contables and/or CFDI references,
        then identifies discrepancies and proposes adjustments.

        Parameters
        ----------
        transactions : List[BankTransaction]
            Bank statement transactions to reconcile.
        polizas : Optional[List[PolizaContable]]
            Accounting entries (polizas contables) to match against.
        cfdi_list : Optional[List[CFDIReference]]
            CFDI references to match against (legacy support).
        tolerance_days : int
            Date tolerance in days for matching.

        Returns
        -------
        dict with keys:
            - matches: List[MatchResult]
            - poliza_matches: List[MatchResult]
            - discrepancies: List[Discrepancy]
            - adjustments: List[Adjustment]
            - unmatched_bank: List[BankTransaction]
            - unmatched_polizas: List[PolizaContable]
        """
        self.date_tolerance_days = tolerance_days
        results: Dict[str, Any] = {
            "matches": [],
            "poliza_matches": [],
            "discrepancies": [],
            "adjustments": [],
            "unmatched_bank": [],
            "unmatched_polizas": [],
        }

        # Match against polizas contables
        if polizas:
            poliza_matches = self.match_transactions_to_polizas(transactions, polizas)
            results["poliza_matches"] = poliza_matches

            # Identify unmatched bank transactions (only those with no successful match)
            matched_ids = {
                m.bank_transaction_id for m in poliza_matches
                if m.status in (MatchStatus.MATCHED, MatchStatus.PARTIAL)
            }
            results["unmatched_bank"] = [
                t for t in transactions if t.id not in matched_ids
            ]

            # Identify unmatched polizas
            matched_poliza_ids = {m.poliza_id for m in poliza_matches if m.poliza_id}
            results["unmatched_polizas"] = [
                p for p in polizas if p.id not in matched_poliza_ids
            ]

            # Detect discrepancies
            discrepancies = self.identify_discrepancies(
                poliza_matches, transactions, polizas
            )
            results["discrepancies"] = discrepancies

            # Propose adjustments
            if discrepancies:
                results["adjustments"] = self.propose_adjustments(discrepancies)

        # Also match against CFDI references (legacy support)
        if cfdi_list:
            cfdi_matches = self.match_transactions(transactions, cfdi_list)
            results["matches"] = cfdi_matches

            # If no poliza matching was done, identify unmatched here
            if not polizas:
                matched_ids = {m.bank_transaction_id for m in cfdi_matches}
                results["unmatched_bank"] = [
                    t for t in transactions if t.id not in matched_ids
                ]

        return results

    # -------------------------------------------------------------------
    # Matching — Bank transactions vs Polizas Contables
    # -------------------------------------------------------------------

    def match_transactions_to_polizas(
        self,
        bank_txns: List[BankTransaction],
        polizas: List[PolizaContable],
    ) -> List[MatchResult]:
        """Match bank transactions against polizas contables.

        Each bank transaction is matched to at most one poliza. The algorithm
        tries exact match first, then amount+date, then amount-only.
        """
        results: List[MatchResult] = []
        used_polizas: set[str] = set()

        for txn in bank_txns:
            best_match: Optional[MatchResult] = None

            # --- Pass 1: EXACT match (same amount, same date) ---
            for pol in polizas:
                if pol.id in used_polizas:
                    continue
                if txn.amount == pol.monto and txn.date == pol.fecha:
                    best_match = MatchResult(
                        bank_transaction_id=txn.id,
                        poliza_id=pol.id,
                        match_type=MatchType.EXACT,
                        confidence_score=1.0,
                        status=MatchStatus.MATCHED,
                    )
                    used_polizas.add(pol.id)
                    break

            # --- Pass 2: AMOUNT_DATE match (same amount, dates within tolerance) ---
            if best_match is None:
                for pol in polizas:
                    if pol.id in used_polizas:
                        continue
                    if txn.amount == pol.monto:
                        date_diff = self._date_difference_days(txn.date, pol.fecha)
                        if date_diff is not None and date_diff <= self.date_tolerance_days:
                            confidence = max(0.8 - (date_diff * 0.05), 0.5)
                            best_match = MatchResult(
                                bank_transaction_id=txn.id,
                                poliza_id=pol.id,
                                match_type=MatchType.AMOUNT_DATE,
                                confidence_score=round(confidence, 2),
                                status=MatchStatus.MATCHED,
                            )
                            used_polizas.add(pol.id)
                            break

            # --- Pass 3: PARTIAL_REFERENCE match ---
            if best_match is None and txn.reference:
                for pol in polizas:
                    if pol.id in used_polizas:
                        continue
                    ref_lower = txn.reference.lower()
                    pol_ref_lower = pol.referencia.lower() if pol.referencia else ""
                    pol_desc_lower = pol.descripcion.lower()
                    pol_concepto_lower = pol.concepto.lower()

                    # Check if reference is contained in poliza reference or vice versa
                    if (len(ref_lower) >= 6 and pol_ref_lower and (
                        ref_lower in pol_ref_lower
                        or pol_ref_lower in ref_lower
                    )):
                        similarity = min(len(ref_lower), len(pol_ref_lower)) / max(
                            len(ref_lower), len(pol_ref_lower)
                        )
                        confidence = round(0.4 + (similarity * 0.2), 2)
                        best_match = MatchResult(
                            bank_transaction_id=txn.id,
                            poliza_id=pol.id,
                            match_type=MatchType.PARTIAL_REFERENCE,
                            confidence_score=min(confidence, 0.6),
                            status=MatchStatus.PARTIAL,
                        )
                        used_polizas.add(pol.id)
                        break
                    # Check description contains reference fragment
                    elif len(ref_lower) >= 6 and ref_lower in pol_desc_lower:
                        confidence = 0.5
                        best_match = MatchResult(
                            bank_transaction_id=txn.id,
                            poliza_id=pol.id,
                            match_type=MatchType.PARTIAL_REFERENCE,
                            confidence_score=confidence,
                            status=MatchStatus.PARTIAL,
                        )
                        used_polizas.add(pol.id)
                        break
                    elif len(ref_lower) >= 6 and ref_lower in pol_concepto_lower:
                        confidence = 0.45
                        best_match = MatchResult(
                            bank_transaction_id=txn.id,
                            poliza_id=pol.id,
                            match_type=MatchType.PARTIAL_REFERENCE,
                            confidence_score=confidence,
                            status=MatchStatus.PARTIAL,
                        )
                        used_polizas.add(pol.id)
                        break

            # --- Pass 4: AMOUNT_ONLY match (amount within tolerance, any date) ---
            if best_match is None:
                for pol in polizas:
                    if pol.id in used_polizas:
                        continue
                    if pol.monto != 0:
                        variance = abs(txn.amount - pol.monto) / abs(pol.monto)
                        if variance <= self.amount_tolerance:
                            date_diff = self._date_difference_days(txn.date, pol.fecha)
                            # Penalize large date differences
                            date_penalty = 0.0
                            if date_diff is not None and date_diff > 0:
                                date_penalty = min(date_diff * 0.03, 0.2)
                            confidence = round(max(0.4 - date_penalty, 0.15), 2)
                            best_match = MatchResult(
                                bank_transaction_id=txn.id,
                                poliza_id=pol.id,
                                match_type=MatchType.AMOUNT_ONLY,
                                confidence_score=confidence,
                                status=MatchStatus.PARTIAL,
                            )
                            used_polizas.add(pol.id)
                            break

            if best_match is not None:
                results.append(best_match)
            else:
                results.append(MatchResult(
                    bank_transaction_id=txn.id,
                    confidence_score=0.0,
                    status=MatchStatus.UNMATCHED,
                ))

        return results

    # -------------------------------------------------------------------
    # Matching — Bank transactions vs CFDI (legacy)
    # -------------------------------------------------------------------

    def match_transactions(
        self,
        bank_txns: List[BankTransaction],
        cfdi_list: List[CFDIReference],
    ) -> List[MatchResult]:
        """Match bank transactions against CFDI references.

        Each bank transaction is matched to at most one CFDI.  The algorithm
        tries exact match first, then amount+date, then partial reference.
        Unmatched transactions get status=UNMATCHED.
        """
        results: List[MatchResult] = []
        used_cfdi: set[str] = set()

        for txn in bank_txns:
            best_match: Optional[MatchResult] = None

            # --- Pass 1: EXACT match (same amount, same date) ---
            for cfdi in cfdi_list:
                if cfdi.uuid in used_cfdi:
                    continue
                if txn.amount == cfdi.total and txn.date == cfdi.fecha:
                    best_match = MatchResult(
                        bank_transaction_id=txn.id,
                        cfdi_uuid=cfdi.uuid,
                        match_type=MatchType.EXACT,
                        confidence_score=1.0,
                        status=MatchStatus.MATCHED,
                    )
                    used_cfdi.add(cfdi.uuid)
                    break

            # --- Pass 2: AMOUNT_DATE match (same amount, dates within tolerance) ---
            if best_match is None:
                for cfdi in cfdi_list:
                    if cfdi.uuid in used_cfdi:
                        continue
                    if txn.amount == cfdi.total:
                        date_diff = self._date_difference_days(txn.date, cfdi.fecha)
                        if date_diff is not None and date_diff <= self.date_tolerance_days:
                            confidence = max(0.8 - (date_diff * 0.05), 0.5)
                            best_match = MatchResult(
                                bank_transaction_id=txn.id,
                                cfdi_uuid=cfdi.uuid,
                                match_type=MatchType.AMOUNT_DATE,
                                confidence_score=round(confidence, 2),
                                status=MatchStatus.MATCHED,
                            )
                            used_cfdi.add(cfdi.uuid)
                            break

            # --- Pass 3: PARTIAL_REFERENCE match ---
            if best_match is None and txn.reference:
                for cfdi in cfdi_list:
                    if cfdi.uuid in used_cfdi:
                        continue
                    ref_lower = txn.reference.lower()
                    cfdi_uuid_lower = cfdi.uuid.lower()
                    desc_lower = txn.description.lower()
                    # Check if reference is contained in CFDI UUID or vice versa
                    if (len(ref_lower) >= 6 and (
                        ref_lower in cfdi_uuid_lower
                        or cfdi_uuid_lower in ref_lower
                    )):
                        similarity = min(len(ref_lower), len(cfdi_uuid_lower)) / max(len(ref_lower), len(cfdi_uuid_lower))
                        confidence = round(0.4 + (similarity * 0.2), 2)
                        best_match = MatchResult(
                            bank_transaction_id=txn.id,
                            cfdi_uuid=cfdi.uuid,
                            match_type=MatchType.PARTIAL_REFERENCE,
                            confidence_score=min(confidence, 0.6),
                            status=MatchStatus.PARTIAL,
                        )
                        used_cfdi.add(cfdi.uuid)
                        break
                    # Also check description contains UUID fragment
                    elif len(ref_lower) >= 6 and ref_lower in desc_lower and cfdi_uuid_lower[:8] in desc_lower:
                        confidence = 0.5
                        best_match = MatchResult(
                            bank_transaction_id=txn.id,
                            cfdi_uuid=cfdi.uuid,
                            match_type=MatchType.PARTIAL_REFERENCE,
                            confidence_score=confidence,
                            status=MatchStatus.PARTIAL,
                        )
                        used_cfdi.add(cfdi.uuid)
                        break

            if best_match is not None:
                results.append(best_match)
            else:
                results.append(MatchResult(
                    bank_transaction_id=txn.id,
                    cfdi_uuid=None,
                    match_type=MatchType.EXACT,
                    confidence_score=0.0,
                    status=MatchStatus.UNMATCHED,
                ))

        return results

    # -------------------------------------------------------------------
    # Discrepancy detection
    # -------------------------------------------------------------------

    def identify_discrepancies(
        self,
        matched: List[MatchResult],
        bank_txns: Optional[List[BankTransaction]] = None,
        polizas: Optional[List[PolizaContable]] = None,
        cfdi_list: Optional[List[CFDIReference]] = None,
    ) -> List[Discrepancy]:
        """Find discrepancies in matched pairs.

        Detects:
        - Amount discrepancies (monto) > threshold
        - Date discrepancies (fecha) > tolerance
        - Missing entries (faltante) — bank txns without matches
        - Excess entries (sobrante) — polizas without matches
        - Duplicate transactions
        """
        discrepancies: List[Discrepancy] = []

        # Build lookup maps
        txn_map: Dict[str, BankTransaction] = {}
        if bank_txns:
            txn_map = {t.id: t for t in bank_txns}

        poliza_map: Dict[str, PolizaContable] = {}
        if polizas:
            poliza_map = {p.id: p for p in polizas}

        cfdi_map: Dict[str, CFDIReference] = {}
        if cfdi_list:
            cfdi_map = {c.uuid: c for c in cfdi_list}

        # Detect duplicates in bank transactions
        if bank_txns:
            seen_amounts: Dict[float, List[str]] = {}
            for txn in bank_txns:
                key = (txn.amount, txn.date)
                if key not in seen_amounts:
                    seen_amounts[key] = []
                seen_amounts[key].append(txn.id)

            for (amount, date), ids in seen_amounts.items():
                if len(ids) > 1:
                    discrepancies.append(Discrepancy(
                        id=f"DISC-DUP-{ids[0]}",
                        type=DiscrepancyType.DUPLICADO,
                        bank_transaction_id=ids[0],
                        bank_amount=amount,
                        details=f"Transacciones duplicadas detectadas: {', '.join(ids)} (monto={amount}, fecha={date})",
                    ))

        # Check matched pairs for discrepancies
        for match in matched:
            if match.status not in (MatchStatus.MATCHED, MatchStatus.PARTIAL):
                continue

            txn = txn_map.get(match.bank_transaction_id)
            poliza = poliza_map.get(match.poliza_id) if match.poliza_id else None
            cfdi = cfdi_map.get(match.cfdi_uuid) if match.cfdi_uuid else None

            # Get the reference amount and date
            ref_amount = None
            ref_date = None
            ref_id = None

            if poliza:
                ref_amount = poliza.monto
                ref_date = poliza.fecha
                ref_id = poliza.id
            elif cfdi:
                ref_amount = cfdi.total
                ref_date = cfdi.fecha
                ref_id = cfdi.uuid

            if txn is None or ref_amount is None:
                continue

            # Amount discrepancy
            if ref_amount != 0:
                variance = abs(txn.amount - ref_amount) / abs(ref_amount)
                if variance > self.discrepancy_threshold:
                    disc_type = DiscrepancyType.MONTO
                    # Determine if it's a sobrante or faltante
                    if txn.amount > ref_amount:
                        disc_type = DiscrepancyType.SOBRANTE
                    else:
                        disc_type = DiscrepancyType.FALTANTE

                    discrepancies.append(Discrepancy(
                        id=f"DISC-{match.bank_transaction_id}-{ref_id or 'unknown'}",
                        type=disc_type,
                        bank_transaction_id=match.bank_transaction_id,
                        poliza_id=match.poliza_id,
                        cfdi_uuid=match.cfdi_uuid,
                        bank_amount=txn.amount,
                        poliza_amount=ref_amount,
                        expected_amount=ref_amount,
                        actual_amount=txn.amount,
                        variance=round(variance * 100, 2),
                        variance_amount=round(abs(txn.amount - ref_amount), 2),
                        details=(
                            f"Diferencia de monto: banco={txn.amount}, "
                            f"{'póliza' if poliza else 'CFDI'}={ref_amount}, "
                            f"varianza={round(variance * 100, 2)}%"
                        ),
                    ))

            # Date discrepancy (only for poliza matches)
            if poliza and ref_date:
                date_diff = self._date_difference_days(txn.date, ref_date)
                if date_diff is not None and date_diff > self.date_tolerance_days:
                    discrepancies.append(Discrepancy(
                        id=f"DISC-FECHA-{match.bank_transaction_id}-{poliza.id}",
                        type=DiscrepancyType.FECHA,
                        bank_transaction_id=match.bank_transaction_id,
                        poliza_id=match.poliza_id,
                        bank_amount=txn.amount,
                        poliza_amount=poliza.monto,
                        date_diff_days=date_diff,
                        details=(
                            f"Diferencia de fecha: banco={txn.date}, "
                            f"póliza={ref_date}, diferencia={date_diff} días"
                        ),
                    ))

        # Find unmatched bank transactions (faltante)
        if bank_txns:
            matched_ids = {m.bank_transaction_id for m in matched}
            for txn in bank_txns:
                if txn.id not in matched_ids:
                    discrepancies.append(Discrepancy(
                        id=f"DISC-FALTANTE-{txn.id}",
                        type=DiscrepancyType.FALTANTE,
                        bank_transaction_id=txn.id,
                        bank_amount=txn.amount,
                        details=f"Transacción bancaria sin conciliar: {txn.id} ({txn.amount})",
                    ))

        # Find unmatched polizas (sobrante)
        if polizas:
            matched_poliza_ids = {m.poliza_id for m in matched if m.poliza_id}
            for pol in polizas:
                if pol.id not in matched_poliza_ids:
                    discrepancies.append(Discrepancy(
                        id=f"DISC-SOBRANTE-{pol.id}",
                        type=DiscrepancyType.SOBRANTE,
                        poliza_id=pol.id,
                        poliza_amount=pol.monto,
                        details=f"Póliza contable sin conciliar: {pol.id} ({pol.monto})",
                    ))

        return discrepancies

    # -------------------------------------------------------------------
    # Adjustment proposals
    # -------------------------------------------------------------------

    def propose_adjustments(
        self,
        discrepancies: List[Discrepancy],
    ) -> List[Adjustment]:
        """Propose adjustments to resolve discrepancies.

        Returns a list of Adjustment objects with proposed journal entries
        where applicable.
        """
        adjustments: List[Adjustment] = []

        for disc in discrepancies:
            adjustment_id = f"ADJ-{disc.id}"

            if disc.type == DiscrepancyType.MONTO:
                # Amount mismatch — propose correction entry
                diff = 0.0
                if disc.bank_amount is not None and disc.poliza_amount is not None:
                    diff = disc.bank_amount - disc.poliza_amount

                proposal = (
                    f"Corregir póliza {disc.poliza_id}: diferencia de monto "
                    f"${abs(diff):.2f}. {'Sobrante en banco.' if diff > 0 else 'Faltante en banco.'}"
                )
                journal_entry = None
                if disc.poliza_id:
                    journal_entry = {
                        "tipo": "correccion",
                        "descripcion": f"Corrección por diferencia de conciliación bancaria",
                        "cuenta_debito": "101.01" if diff > 0 else "501.01",
                        "cuenta_credito": "501.01" if diff > 0 else "101.01",
                        "monto": abs(diff),
                        "referencia": disc.poliza_id,
                    }

                adjustments.append(Adjustment(
                    id=adjustment_id,
                    discrepancy_id=disc.id,
                    proposal=proposal,
                    adjustment_type="correction",
                    journal_entry=journal_entry,
                    reason=f"Diferencia de monto detectada en conciliación bancaria",
                    status=AdjustmentStatus.PROPOSED,
                ))

            elif disc.type == DiscrepancyType.SOBRANTE and disc.poliza_id is None:
                # Excess without poliza — propose creating a new poliza
                proposal = (
                    f"Crear póliza contable para transacción bancaria "
                    f"{disc.bank_transaction_id}: monto ${disc.bank_amount or 0:.2f}"
                )
                journal_entry = {
                    "tipo": "alta",
                    "descripcion": f"Póliza generada por conciliación bancaria - transacción {disc.bank_transaction_id}",
                    "cuenta_debito": "101.01",
                    "cuenta_credito": "401.01",
                    "monto": abs(disc.bank_amount or 0),
                    "referencia": disc.bank_transaction_id,
                }

                adjustments.append(Adjustment(
                    id=adjustment_id,
                    discrepancy_id=disc.id,
                    proposal=proposal,
                    adjustment_type="manual_entry",
                    journal_entry=journal_entry,
                    reason="Transacción bancaria sin póliza contable asociada",
                    status=AdjustmentStatus.PROPOSED,
                ))

            elif disc.type == DiscrepancyType.FALTANTE and disc.bank_transaction_id:
                # Missing bank transaction — propose void or investigation
                proposal = (
                    f"Investigar transacción bancaria {disc.bank_transaction_id}: "
                    f"monto ${disc.bank_amount or 0:.2f} sin póliza asociada"
                )

                adjustments.append(Adjustment(
                    id=adjustment_id,
                    discrepancy_id=disc.id,
                    proposal=proposal,
                    adjustment_type="investigation",
                    reason="Transacción bancaria sin conciliar requiere investigación",
                    status=AdjustmentStatus.PROPOSED,
                ))

            elif disc.type == DiscrepancyType.DUPLICADO:
                # Duplicate transaction — propose voiding one
                proposal = (
                    f"Verificar transacción duplicada {disc.bank_transaction_id}: "
                    f"posible cargo duplicado que requiere reversión"
                )
                journal_entry = {
                    "tipo": "reversion",
                    "descripcion": f"Reversión de cargo duplicado - {disc.bank_transaction_id}",
                    "cuenta_debito": "501.01",
                    "cuenta_credito": "101.01",
                    "monto": abs(disc.bank_amount or 0),
                    "referencia": disc.bank_transaction_id,
                }

                adjustments.append(Adjustment(
                    id=adjustment_id,
                    discrepancy_id=disc.id,
                    proposal=proposal,
                    adjustment_type="void",
                    journal_entry=journal_entry,
                    reason="Transacción duplicada detectada en estado de cuenta",
                    status=AdjustmentStatus.PROPOSED,
                ))

            elif disc.type == DiscrepancyType.FECHA:
                # Date mismatch — propose review
                proposal = (
                    f"Revisar fecha de póliza {disc.poliza_id}: "
                    f"diferencia de {disc.date_diff_days} días con transacción bancaria"
                )

                adjustments.append(Adjustment(
                    id=adjustment_id,
                    discrepancy_id=disc.id,
                    proposal=proposal,
                    adjustment_type="review",
                    reason=f"Diferencia de fecha excede tolerancia ({disc.date_diff_days} días)",
                    status=AdjustmentStatus.PROPOSED,
                ))

            elif disc.type == DiscrepancyType.SOBRANTE and disc.poliza_id:
                # Excess with poliza — propose reclassification
                diff = 0.0
                if disc.bank_amount is not None and disc.poliza_amount is not None:
                    diff = disc.bank_amount - disc.poliza_amount

                proposal = (
                    f"Reclasificar póliza {disc.poliza_id}: "
                    f"diferencia de ${abs(diff):.2f}"
                )
                journal_entry = None
                if disc.poliza_id:
                    journal_entry = {
                        "tipo": "reclasificacion",
                        "descripcion": f"Reclasificación por diferencia de conciliación",
                        "cuenta_debito": "101.01",
                        "cuenta_credito": "101.02",
                        "monto": abs(diff),
                        "referencia": disc.poliza_id,
                    }

                adjustments.append(Adjustment(
                    id=adjustment_id,
                    discrepancy_id=disc.id,
                    proposal=proposal,
                    adjustment_type="reclassify",
                    journal_entry=journal_entry,
                    reason="Sobrante requiere reclasificación contable",
                    status=AdjustmentStatus.PROPOSED,
                ))

        return adjustments

    # -------------------------------------------------------------------
    # Report generation
    # -------------------------------------------------------------------

    def generate_reconciliation_report(
        self,
        results: Dict[str, Any],
        period: str = "",
    ) -> ConciliationReport:
        """Generate a comprehensive ConciliationReport from reconciliation results.

        Parameters
        ----------
        results : Dict[str, Any]
            Output from reconcile_bank_statement().
        period : str
            Period string (YYYY-MM).
        """
        all_matches = results.get("matches", []) + results.get("poliza_matches", [])
        discrepancies = results.get("discrepancies", [])
        adjustments = results.get("adjustments", [])
        unmatched_bank = results.get("unmatched_bank", [])
        unmatched_polizas = results.get("unmatched_polizas", [])

        total = len(all_matches) + len(unmatched_bank)
        matched = sum(1 for m in all_matches if m.status == MatchStatus.MATCHED)
        partial = sum(1 for m in all_matches if m.status == MatchStatus.PARTIAL)
        unmatched = len(unmatched_bank)
        discrepancy_count = len([d for d in discrepancies if d.type in (
            DiscrepancyType.MONTO, DiscrepancyType.FALTANTE, DiscrepancyType.SOBRANTE
        )])

        match_rate = 0.0
        if total > 0:
            match_rate = round(((matched + partial) / total) * 100, 2)

        # Calculate total variance
        total_variance = 0.0
        for disc in discrepancies:
            if disc.variance_amount is not None:
                total_variance += abs(disc.variance_amount)

        return ConciliationReport(
            period=period,
            total_transactions=total,
            matched=matched + partial,
            unmatched=unmatched,
            discrepancies=discrepancy_count,
            match_rate=match_rate,
            total_polizas=len(results.get("poliza_matches", [])) + len(unmatched_polizas),
            polizas_matched=sum(
                1 for m in results.get("poliza_matches", [])
                if m.status in (MatchStatus.MATCHED, MatchStatus.PARTIAL)
            ),
            adjustments_proposed=len(adjustments),
            adjustments_applied=sum(
                1 for a in adjustments if a.status == AdjustmentStatus.APPLIED
            ),
            total_variance=round(total_variance, 2),
            details=[m.model_dump() for m in all_matches],
            discrepancy_details=[d.model_dump() for d in discrepancies],
            adjustment_details=[a.model_dump() for a in adjustments],
        )

    # Legacy report generation (kept for backward compatibility)
    def generate_report(
        self,
        matches: List[MatchResult],
        period: str = "",
    ) -> ConciliationReport:
        """Generate a ConciliationReport from a list of match results (legacy)."""
        total = len(matches)
        matched = sum(1 for m in matches if m.status == MatchStatus.MATCHED)
        partial = sum(1 for m in matches if m.status == MatchStatus.PARTIAL)
        unmatched = sum(1 for m in matches if m.status == MatchStatus.UNMATCHED)
        discrepancies = sum(1 for m in matches if m.status == MatchStatus.DISCREPANCY)

        match_rate = 0.0
        if total > 0:
            match_rate = round(((matched + partial) / total) * 100, 2)

        return ConciliationReport(
            period=period,
            total_transactions=total,
            matched=matched + partial,
            unmatched=unmatched,
            discrepancies=discrepancies,
            match_rate=match_rate,
            details=[m.model_dump() for m in matches],
        )

    # -------------------------------------------------------------------
    # Discrepancy detection (legacy)
    # -------------------------------------------------------------------

    def find_discrepancies(
        self,
        matches: List[MatchResult],
        bank_txns: Optional[List[BankTransaction]] = None,
        cfdi_list: Optional[List[CFDIReference]] = None,
    ) -> List[dict]:
        """Find matches with amount discrepancies > threshold (legacy method).

        For each MATCHED or PARTIAL result, compares the bank transaction
        amount against the CFDI total and flags if variance > threshold.
        """
        discrepancies: List[dict] = []
        if not bank_txns or not cfdi_list:
            return discrepancies

        txn_map = {t.id: t for t in bank_txns}
        cfdi_map = {c.uuid: c for c in cfdi_list}

        for match in matches:
            if match.status not in (MatchStatus.MATCHED, MatchStatus.PARTIAL):
                continue
            if match.cfdi_uuid is None:
                continue

            txn = txn_map.get(match.bank_transaction_id)
            cfdi = cfdi_map.get(match.cfdi_uuid)
            if txn is None or cfdi is None:
                continue

            if cfdi.total == 0:
                continue

            variance = abs(txn.amount - cfdi.total) / abs(cfdi.total)
            if variance > self.discrepancy_threshold:
                discrepancies.append({
                    "bank_transaction_id": txn.id,
                    "cfdi_uuid": cfdi.uuid,
                    "bank_amount": txn.amount,
                    "cfdi_total": cfdi.total,
                    "variance": round(variance * 100, 2),
                    "variance_amount": round(abs(txn.amount - cfdi.total), 2),
                    "match_type": match.match_type.value,
                    "confidence_score": match.confidence_score,
                })

        return discrepancies

    # -------------------------------------------------------------------
    # CSV export
    # -------------------------------------------------------------------

    def export_csv(
        self,
        report: ConciliationReport,
        discrepancies: Optional[List[dict]] = None,
    ) -> str:
        """Export reconciliation results to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "Periodo",
            "Total Transacciones",
            "Conciliadas",
            "Sin Conciliar",
            "Discrepancias",
            "Porcentaje Conciliación (%)",
        ])
        writer.writerow([
            report.period,
            report.total_transactions,
            report.matched,
            report.unmatched,
            report.discrepancies,
            report.match_rate,
        ])
        writer.writerow([])

        # Match details
        writer.writerow([
            "ID Transacción Bancaria",
            "UUID CFDI",
            "ID Póliza",
            "Tipo de Match",
            "Confianza",
            "Estado",
        ])
        for detail in report.details:
            writer.writerow([
                detail.get("bank_transaction_id", ""),
                detail.get("cfdi_uuid", ""),
                detail.get("poliza_id", ""),
                detail.get("match_type", ""),
                detail.get("confidence_score", ""),
                detail.get("status", ""),
            ])

        # Discrepancy details
        if discrepancies:
            writer.writerow([])
            writer.writerow([
                "ID Transacción",
                "UUID CFDI",
                "Monto Bancario",
                "Total CFDI",
                "Variance (%)",
                "Variance ($)",
            ])
            for d in discrepancies:
                writer.writerow([
                    d.get("bank_transaction_id", ""),
                    d.get("cfdi_uuid", ""),
                    d.get("bank_amount", ""),
                    d.get("cfdi_total", ""),
                    d.get("variance", ""),
                    d.get("variance_amount", ""),
                ])

        return output.getvalue()

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _date_difference_days(self, date1: str, date2: str) -> Optional[int]:
        """Calculate absolute difference in days between two YYYY-MM-DD dates."""
        try:
            d1 = datetime.strptime(date1, "%Y-%m-%d")
            d2 = datetime.strptime(date2, "%Y-%m-%d")
            return abs((d1 - d2).days)
        except (ValueError, TypeError):
            return None
