# -*- coding: utf-8 -*-
"""
matching_engine.py — 4-level progressive matching engine.

Levels:
  1. Exact  — same amount (±0.01) + same date + reference match
  2. Fuzzy  — amount ±tolerance% + date ±tolerance days + description similarity (rapidfuzz)
  3. Multi-line — one bank payment covers multiple book records (subset sum)
  4. LLM    — AI reasoning for ambiguous cases (requires LLMService)

Extends the existing matching in b2b_ai.services.bank_reconciliation.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from b2b_ai.features.reconciliation_agent.models import (
    BankMovement,
    MatchLevel,
    ReconciliationMatch,
    ReconciliationResult,
)

logger = logging.getLogger(__name__)


def _dec(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace(" ", "")
    if s in ("", "-", "--", "N/A", "n/a"):
        return None
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def _norm_text(s: str) -> str:
    """Normalize text for comparison."""
    s = (s or "").lower()
    s = re.sub(r"[^0-9a-zñáéíóú ]+", " ", s)
    return " ".join(s.split())


def _token_set(s: str) -> set:
    return set(_norm_text(s).split())


def _token_overlap(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _fecha_to_dt(fecha: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(fecha, fmt)
        except ValueError:
            continue
    return None


def _fecha_diff(f1: str, f2: str) -> Optional[int]:
    d1, d2 = _fecha_to_dt(f1), _fecha_to_dt(f2)
    if d1 and d2:
        return abs((d1 - d2).days)
    return None


# ---------------------------------------------------------------------------
# Matching Engine
# ---------------------------------------------------------------------------

class MatchingEngine:
    """Progressive 4-level matching engine.

    Args:
        date_tolerance_days: Max days between dates for fuzzy matching.
        monto_tolerance_pct: Max % difference in amount for fuzzy matching.
        fuzzy_threshold: Minimum rapidfuzz ratio for fuzzy description matching.
        enable_llm: Whether to use LLM for level 4 matching.
        llm_service: Optional LLMService instance.
    """

    def __init__(
        self,
        date_tolerance_days: int = 3,
        monto_tolerance_pct: float = 5.0,
        fuzzy_threshold: int = 80,
        enable_llm: bool = False,
        llm_service: Any = None,
    ):
        self.date_tolerance_days = date_tolerance_days
        self.monto_tolerance_pct = monto_tolerance_pct
        self.fuzzy_threshold = fuzzy_threshold
        self.enable_llm = enable_llm
        self.llm_service = llm_service

    def match(
        self,
        movements: List[BankMovement],
        records: List[Dict[str, Any]],
    ) -> ReconciliationResult:
        """Execute progressive matching on bank movements vs book records.

        Args:
            movements: Parsed bank movements.
            records: Book records (invoices, pólizas) with at least
                     {fecha, monto, descripcion/referencia}.

        Returns:
            ReconciliationResult with matched, unmatched_bank, unmatched_books.
        """
        import time
        start = time.monotonic()

        # Work with indices for easy removal
        free_movs = list(range(len(movements)))
        free_recs = list(range(len(records)))
        matches: List[ReconciliationMatch] = []

        # Level 1: Exact matching
        l1 = self._match_exact(movements, records, free_movs, free_recs)
        matches.extend(l1["matches"])
        free_movs = l1["free_movs"]
        free_recs = l1["free_recs"]

        # Level 2: Fuzzy matching
        l2 = self._match_fuzzy(movements, records, free_movs, free_recs)
        matches.extend(l2["matches"])
        free_movs = l2["free_movs"]
        free_recs = l2["free_recs"]

        # Level 3: Multi-line matching
        l3 = self._match_multiline(movements, records, free_movs, free_recs)
        matches.extend(l3["matches"])
        free_movs = l3["free_movs"]
        free_recs = l3["free_recs"]

        # Level 4: LLM matching (optional)
        if self.enable_llm:
            l4 = self._match_llm(movements, records, free_movs, free_recs)
            matches.extend(l4["matches"])
            free_movs = l4["free_movs"]
            free_recs = l4["free_recs"]

        # Build result
        elapsed_ms = (time.monotonic() - start) * 1000
        return self._build_result(movements, records, matches, free_movs, free_recs, elapsed_ms)

    # ------------------------------------------------------------------
    # Level 1: Exact
    # ------------------------------------------------------------------

    def _match_exact(
        self,
        movements: List[BankMovement],
        records: List[Dict[str, Any]],
        free_movs: List[int],
        free_recs: List[int],
    ) -> Dict[str, Any]:
        matches = []
        used_mov = set()
        used_rec = set()

        for mi in free_movs:
            mov = movements[mi]
            monto_mov = mov.monto
            for ri in free_recs:
                if ri in used_rec:
                    continue
                rec = records[ri]
                monto_rec = _dec(rec.get("monto", rec.get("total")))
                if monto_rec is None:
                    continue

                # Amount must be identical (±0.01)
                if abs(abs(monto_mov) - abs(monto_rec)) > 0.01:
                    continue

                # Date must match exactly or within 1 day
                fecha_rec = str(rec.get("fecha", ""))[:10]
                diff = _fecha_diff(mov.fecha, fecha_rec)
                if diff is None or diff > 1:
                    continue

                # Reference check (if available)
                ref_match = self._check_ref(mov, rec)
                if ref_match or diff == 0:
                    matches.append(ReconciliationMatch(
                        movement_idx=mi,
                        registro_idx=ri,
                        level=MatchLevel.EXACT,
                        score=100 if diff == 0 else 97,
                        detail=f"Monto exacto ({monto_rec}) y fecha {'igual' if diff == 0 else f'a {diff}d'}",
                        monto_banco=monto_mov,
                        monto_registro=monto_rec,
                        fecha_banco=mov.fecha,
                        fecha_registro=fecha_rec,
                    ))
                    used_mov.add(mi)
                    used_rec.add(ri)
                    break

        free_movs = [m for m in free_movs if m not in used_mov]
        free_recs = [r for r in free_recs if r not in used_rec]
        return {"matches": matches, "free_movs": free_movs, "free_recs": free_recs}

    # ------------------------------------------------------------------
    # Level 2: Fuzzy
    # ------------------------------------------------------------------

    def _match_fuzzy(
        self,
        movements: List[BankMovement],
        records: List[Dict[str, Any]],
        free_movs: List[int],
        free_recs: List[int],
    ) -> Dict[str, Any]:
        matches = []
        used_mov = set()
        used_rec = set()

        for mi in free_movs:
            mov = movements[mi]
            monto_mov = mov.monto
            best_ri = None
            best_score = 0.0

            for ri in free_recs:
                if ri in used_rec:
                    continue
                rec = records[ri]
                monto_rec = _dec(rec.get("monto", rec.get("total")))
                if monto_rec is None:
                    continue

                # Amount tolerance
                abs_mov = abs(monto_mov)
                abs_rec = abs(monto_rec)
                if abs_rec == 0:
                    continue
                diff_pct = abs(abs_mov - abs_rec) / abs_rec * 100
                if diff_pct > self.monto_tolerance_pct:
                    continue

                # Date tolerance
                fecha_rec = str(rec.get("fecha", ""))[:10]
                day_diff = _fecha_diff(mov.fecha, fecha_rec)
                if day_diff is None or day_diff > self.date_tolerance_days:
                    continue

                # Description similarity
                desc_mov = f"{mov.descripcion} {mov.referencia or ''}".strip()
                desc_rec = str(rec.get("descripcion", rec.get("concepto", rec.get("referencia", "")))).strip()
                ratio = fuzz.partial_ratio(desc_mov.lower(), desc_rec.lower())

                if ratio >= self.fuzzy_threshold:
                    # Composite score: description (60%) + amount closeness (25%) + date closeness (15%)
                    amount_score = max(0, 100 - diff_pct * 10)
                    date_score = max(0, 100 - day_diff * 25)
                    score = ratio * 0.6 + amount_score * 0.25 + date_score * 0.15
                    score = min(95, max(50, score))  # Cap at 95 for fuzzy

                    if score > best_score:
                        best_score = score
                        best_ri = ri

            if best_ri is not None:
                rec = records[best_ri]
                monto_rec = _dec(rec.get("monto", rec.get("total")))
                fecha_rec = str(rec.get("fecha", ""))[:10]
                matches.append(ReconciliationMatch(
                    movement_idx=mi,
                    registro_idx=best_ri,
                    level=MatchLevel.FUZZY,
                    score=round(best_score, 1),
                    detail=f"Fuzzy match: descripción similar ({fuzz.partial_ratio(mov.descripcion, str(rec.get('descripcion', '')))}%)",
                    monto_banco=monto_mov,
                    monto_registro=monto_rec,
                    fecha_banco=mov.fecha,
                    fecha_registro=fecha_rec,
                ))
                used_mov.add(mi)
                used_rec.add(best_ri)

        free_movs = [m for m in free_movs if m not in used_mov]
        free_recs = [r for r in free_recs if r not in used_rec]
        return {"matches": matches, "free_movs": free_movs, "free_recs": free_recs}

    # ------------------------------------------------------------------
    # Level 3: Multi-line
    # ------------------------------------------------------------------

    def _match_multiline(
        self,
        movements: List[BankMovement],
        records: List[Dict[str, Any]],
        free_movs: List[int],
        free_recs: List[int],
    ) -> Dict[str, Any]:
        """One bank movement covers multiple book records (subset sum).

        Example: SPEI transfer of $5,000 covers 3 invoices ($2,000 + $1,500 + $1,500).
        """
        matches = []
        used_mov = set()
        used_recs = set()

        # Only try multi-line for movements > $100 (avoid noise)
        for mi in free_movs:
            mov = movements[mi]
            monto_mov = abs(mov.monto)
            if monto_mov < 100 or mi in used_mov:
                continue

            # Get candidate records within date tolerance
            candidates = []
            for ri in free_recs:
                if ri in used_recs:
                    continue
                rec = records[ri]
                monto_rec = abs(_dec(rec.get("monto", rec.get("total"))) or 0)
                fecha_rec = str(rec.get("fecha", ""))[:10]
                day_diff = _fecha_diff(mov.fecha, fecha_rec)
                if monto_rec > 0 and day_diff is not None and day_diff <= self.date_tolerance_days:
                    candidates.append((ri, monto_rec))

            if len(candidates) < 2:
                continue

            # Subset sum with tolerance
            combo = self._find_subset_sum(candidates, monto_mov, tolerance_pct=1.0)
            if combo and len(combo) >= 2:
                combo_indices = [c[0] for c in combo]
                combo_total = sum(c[1] for c in combo)
                diff_pct = abs(monto_mov - combo_total) / max(monto_mov, 1) * 100
                score = max(70, 95 - diff_pct * 10)

                matches.append(ReconciliationMatch(
                    movement_idx=mi,
                    registro_indices=combo_indices,
                    level=MatchLevel.MULTI_LINE,
                    score=round(min(score, 95), 1),
                    detail=f"Multi-línea: {len(combo)} registros suman ${combo_total:,.2f} ≈ ${monto_mov:,.2f}",
                    monto_banco=mov.monto,
                    monto_registro=combo_total,
                    fecha_banco=mov.fecha,
                    fecha_registro=str(records[combo_indices[0]].get("fecha", ""))[:10],
                ))
                used_mov.add(mi)
                used_recs.update(combo_indices)

        free_movs = [m for m in free_movs if m not in used_mov]
        free_recs = [r for r in free_recs if r not in used_recs]
        return {"matches": matches, "free_movs": free_movs, "free_recs": free_recs}

    @staticmethod
    def _find_subset_sum(
        candidates: List[Tuple[int, float]],
        target: float,
        tolerance_pct: float = 1.0,
        max_combo_size: int = 8,
    ) -> Optional[List[Tuple[int, float]]]:
        """Find a subset of candidates that sums to target ± tolerance."""
        tol = target * tolerance_pct / 100
        # Sort descending by amount for faster convergence
        sorted_cands = sorted(candidates, key=lambda c: -c[1])

        # Try small combinations first (most common: 2-4 items)
        for size in range(2, min(max_combo_size + 1, len(sorted_cands) + 1)):
            if size > 10:  # Safety limit
                break
            for combo in combinations(sorted_cands, size):
                total = sum(c[1] for c in combo)
                if abs(total - target) <= tol:
                    return list(combo)

        return None

    # ------------------------------------------------------------------
    # Level 4: LLM
    # ------------------------------------------------------------------

    def _match_llm(
        self,
        movements: List[BankMovement],
        records: List[Dict[str, Any]],
        free_movs: List[int],
        free_recs: List[int],
    ) -> Dict[str, Any]:
        """Use LLM for ambiguous matching."""
        matches = []
        used_mov = set()
        used_rec = set()

        if not self.llm_service:
            return {"matches": [], "free_movs": free_movs, "free_recs": free_recs}

        # Only try LLM for movements >= $1,000
        for mi in free_movs:
            mov = movements[mi]
            if abs(mov.monto) < 1000 or mi in used_mov:
                continue

            # Get top candidates by partial text overlap (pre-filter)
            desc_mov = f"{mov.descripcion} {mov.referencia or ''}".strip()
            scored = []
            for ri in free_recs:
                if ri in used_rec:
                    continue
                rec = records[ri]
                desc_rec = str(rec.get("descripcion", rec.get("concepto", ""))).strip()
                overlap = _token_overlap(desc_mov, desc_rec)
                if overlap >= 0.15:  # Pre-filter threshold
                    scored.append((ri, overlap))

            scored.sort(key=lambda x: -x[1])
            top_candidates = scored[:20]  # Max 20 for LLM

            if not top_candidates:
                continue

            try:
                result = self._call_llm(mov, records, top_candidates)
                if result and result.get("confidence", 0) >= 0.7:
                    ri = result["registro_idx"]
                    matches.append(ReconciliationMatch(
                        movement_idx=mi,
                        registro_idx=ri,
                        level=MatchLevel.LLM,
                        score=round(result["confidence"] * 100, 1),
                        detail=f"LLM: {result.get('razonamiento', '')}",
                        monto_banco=mov.monto,
                        monto_registro=_dec(records[ri].get("monto", records[ri].get("total"))) or 0,
                        fecha_banco=mov.fecha,
                        fecha_registro=str(records[ri].get("fecha", ""))[:10],
                    ))
                    used_mov.add(mi)
                    used_rec.add(ri)
            except Exception as e:
                logger.warning(f"LLM match failed: {e}")

        free_movs = [m for m in free_movs if m not in used_mov]
        free_recs = [r for r in free_recs if r not in used_rec]
        return {"matches": matches, "free_movs": free_movs, "free_recs": free_recs}

    def _call_llm(
        self, mov: BankMovement, records: List[Dict], candidates: List[Tuple[int, float]]
    ) -> Optional[Dict]:
        """Call LLM service for matching."""
        # Format candidates for prompt
        cand_text = ""
        for ri, _ in candidates[:20]:
            rec = records[ri]
            cand_text += (f"- ID:{ri} | fecha:{rec.get('fecha')} | "
                         f"monto:{rec.get('monto', rec.get('total'))} | "
                         f"desc:{str(rec.get('descripcion', ''))[:80]}\n")

        monto = mov.abono if mov.abono else (f"-{mov.cargo}" if mov.cargo else "0")
        prompt = (
            f"Eres un contador experto mexicano. Concilia este movimiento bancario:\n\n"
            f"Movimiento: fecha={mov.fecha}, monto=${monto}, "
            f"desc={mov.descripcion}, ref={mov.referencia or 'N/A'}\n\n"
            f"Registros pendientes:\n{cand_text}\n"
            f"¿Cuál registro corresponde? Responde JSON: "
            f'{{"registro_id": N, "confidence": 0.0-1.0, "razonamiento": "..."}}\n'
            f'Si no hay match: {{"registro_id": null, "confidence": 0}}'
        )

        try:
            res = self.llm_service.classify_invoice({"descripcion": prompt})
            import json
            if isinstance(res, dict) and "registro_id" in res:
                return res
            # Try parsing JSON from response
            text = str(res)
            json_match = re.search(r'\{.*?\}', text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if parsed.get("registro_id") is not None:
                    return parsed
        except Exception as e:
            logger.debug(f"LLM call failed: {e}")

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_ref(mov: BankMovement, rec: Dict) -> bool:
        """Check if movement reference matches record reference."""
        mov_ref = (mov.referencia or "").strip().lower()
        rec_ref = str(rec.get("referencia", rec.get("folio_fiscal", ""))).strip().lower()
        if not mov_ref or not rec_ref:
            return False
        return mov_ref in rec_ref or rec_ref in mov_ref

    def _build_result(
        self,
        movements: List[BankMovement],
        records: List[Dict],
        matches: List[ReconciliationMatch],
        free_movs: List[int],
        free_recs: List[int],
        elapsed_ms: float,
    ) -> ReconciliationResult:
        """Build the final ReconciliationResult."""
        unmatched_bank = [movements[i] for i in free_movs]
        unmatched_books = [records[i] for i in free_recs]

        monto_matched = sum(abs(m.monto_banco) for m in matches)
        monto_bank_total = sum(abs(m.monto) for m in movements)
        monto_books_total = sum(abs(_dec(r.get("monto", r.get("total"))) or 0) for r in records)

        total_movs = len(movements)
        total_recs = len(records)
        total_matched = len(matches)
        match_rate = (total_matched / max(total_movs, 1)) * 100

        # Overall confidence: weighted average of match scores
        if matches:
            confidence = sum(m.score * abs(m.monto_banco) for m in matches) / max(monto_bank_total, 1)
        else:
            confidence = 0.0

        return ReconciliationResult(
            matched=matches,
            unmatched_bank=unmatched_bank,
            unmatched_books=unmatched_books,
            confidence=round(confidence, 2),
            total_movements=total_movs,
            total_records=total_recs,
            total_matched=total_matched,
            match_rate=round(match_rate, 2),
            monto_matched=round(monto_matched, 2),
            monto_unmatched_bank=round(sum(abs(m.monto) for m in unmatched_bank), 2),
            monto_unmatched_books=round(
                sum(abs(_dec(r.get("monto", r.get("total"))) or 0) for r in unmatched_books), 2
            ),
            processing_time_ms=round(elapsed_ms, 2),
        )
