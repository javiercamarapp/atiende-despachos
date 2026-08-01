# -*- coding: utf-8 -*-
"""
service.py — ConciliationService: matching algorithm, reports, and CSV export.

Matching strategy (priority order):
  1. EXACT — identical amount on the same date
  2. AMOUNT_DATE — same amount within a date tolerance (±N days)
  3. PARTIAL_REFERENCE — reference number contains a substring match

Confidence scores:
  - EXACT: 1.0
  - AMOUNT_DATE: 0.8 (decreases with date distance)
  - PARTIAL_REFERENCE: 0.6 (decreases with reference similarity)

Discrepancy detection:
  - Flags any matched pair where |bank_amount - cfdi_total| > 2% of cfdi_total.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import List, Optional

from b2b_ai.features.conciliacion.models import (
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    MatchResult,
    MatchStatus,
    MatchType,
    TransactionType,
)


class ConciliationService:
    """Core service for bank reconciliation."""

    def __init__(
        self,
        date_tolerance_days: int = 3,
        discrepancy_threshold: float = 0.02,
    ):
        """
        Parameters
        ----------
        date_tolerance_days : int
            Maximum days of difference for AMOUNT_DATE matching (default 3).
        discrepancy_threshold : float
            Fractional variance threshold to flag a discrepancy (default 0.02 = 2%).
        """
        self.date_tolerance_days = date_tolerance_days
        self.discrepancy_threshold = discrepancy_threshold

    # -------------------------------------------------------------------
    # Matching
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
    # Report generation
    # -------------------------------------------------------------------

    def generate_report(
        self,
        matches: List[MatchResult],
        period: str = "",
    ) -> ConciliationReport:
        """Generate a ConciliationReport from a list of match results."""
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
    # Discrepancy detection
    # -------------------------------------------------------------------

    def find_discrepancies(
        self,
        matches: List[MatchResult],
        bank_txns: Optional[List[BankTransaction]] = None,
        cfdi_list: Optional[List[CFDIReference]] = None,
    ) -> List[dict]:
        """Find matches with amount discrepancies > threshold.

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
            "Tipo de Match",
            "Confianza",
            "Estado",
        ])
        for detail in report.details:
            writer.writerow([
                detail.get("bank_transaction_id", ""),
                detail.get("cfdi_uuid", ""),
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
