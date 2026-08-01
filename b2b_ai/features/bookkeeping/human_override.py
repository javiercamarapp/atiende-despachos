# -*- coding: utf-8 -*-
"""human_override.py — HumanOverride.

Endpoint logic for accountants to correct agent classifications.
The agent learns from feedback to improve future predictions.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.bookkeeping.models import (
    CFDIClassification,
    OverrideAction,
    OverrideRecord,
)

log = logging.getLogger(__name__)


class HumanOverrideManager:
    """Manages human corrections to agent classifications.

    Features:
    - Stores override history for audit trail
    - Aggregates feedback by RFC (learn from repeated corrections)
    - Provides statistics on override rate
    - Exposes feedback signal for classifier retraining
    """

    def __init__(self):
        self._overrides: List[OverrideRecord] = []
        # Aggregated: rfc_emisor → {categoria → count}
        self._rfc_category_map: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # UUID-indexed for quick lookup
        self._by_uuid: Dict[str, OverrideRecord] = {}

    def submit_override(
        self,
        cfdi_uuid: str,
        action: OverrideAction,
        new_categoria: str = "",
        new_cuenta_cargo: str = "",
        new_cuenta_abono: str = "",
        original_categoria: str = "",
        reason: str = "",
        corrected_by: str = "",
        rfc_emisor: str = "",
        tenant_id: str = "",
    ) -> OverrideRecord:
        """Submit a human override for a CFDI classification."""
        record = OverrideRecord(
            cfdi_uuid=cfdi_uuid,
            action=action,
            original_categoria=original_categoria,
            new_categoria=new_categoria,
            new_cuenta_cargo=new_cuenta_cargo,
            new_cuenta_abono=new_cuenta_abono,
            reason=reason,
            corrected_by=corrected_by,
            tenant_id=tenant_id,
        )

        self._overrides.append(record)
        self._by_uuid[cfdi_uuid] = record

        # Aggregate by RFC for learning
        if rfc_emisor and new_categoria:
            self._rfc_category_map[rfc_emisor][new_categoria] += 1

        log.info(
            "Override submitted: UUID=%s action=%s new_cat=%s by=%s",
            cfdi_uuid, action.value, new_categoria, corrected_by,
        )
        return record

    def get_override(self, cfdi_uuid: str) -> Optional[OverrideRecord]:
        """Get the override record for a specific CFDI UUID."""
        return self._by_uuid.get(cfdi_uuid)

    def get_overrides(
        self,
        tenant_id: str = "",
        limit: int = 100,
    ) -> List[OverrideRecord]:
        """Get override history, optionally filtered by tenant."""
        records = self._overrides
        if tenant_id:
            records = [r for r in records if r.tenant_id == tenant_id]
        return records[-limit:]

    def get_rfc_category_feedback(self, rfc: str) -> Optional[str]:
        """Get the most common corrected category for an RFC.

        Returns the category with the most overrides, or None if
        no feedback exists.
        """
        if rfc not in self._rfc_category_map:
            return None
        cats = self._rfc_category_map[rfc]
        if not cats:
            return None
        return max(cats, key=cats.get)

    def get_all_rfc_feedback(self) -> Dict[str, str]:
        """Get all RFC → preferred category mappings."""
        result = {}
        for rfc, cats in self._rfc_category_map.items():
            if cats:
                result[rfc] = max(cats, key=cats.get)
        return result

    def get_statistics(self, tenant_id: str = "") -> Dict[str, Any]:
        """Get override statistics."""
        overrides = self._overrides
        if tenant_id:
            overrides = [r for r in overrides if r.tenant_id == tenant_id]

        total = len(overrides)
        by_action = defaultdict(int)
        by_corrector = defaultdict(int)
        by_categoria = defaultdict(int)

        for o in overrides:
            by_action[o.action.value] += 1
            if o.corrected_by:
                by_corrector[o.corrected_by] += 1
            if o.new_categoria:
                by_categoria[o.new_categoria] += 1

        return {
            "total_overrides": total,
            "by_action": dict(by_action),
            "by_corrector": dict(by_corrector),
            "by_categoria": dict(by_categoria),
            "rfc_with_feedback": len(self._rfc_category_map),
        }

    def get_suggestions_for_retraining(self) -> List[Dict[str, Any]]:
        """Get override data formatted for classifier retraining.

        Returns list of {rfc, categoria, count} for RFCs with
        consistent corrections.
        """
        suggestions = []
        for rfc, cats in self._rfc_category_map.items():
            if not cats:
                continue
            total = sum(cats.values())
            top_cat = max(cats, key=cats.get)
            top_count = cats[top_cat]
            # Only suggest if there's a strong signal (>50% of overrides agree)
            if total >= 2 and top_count / total > 0.5:
                suggestions.append({
                    "rfc": rfc,
                    "suggested_categoria": top_cat,
                    "override_count": top_count,
                    "total_corrections": total,
                    "confidence": round(top_count / total, 2),
                })
        return suggestions
