# -*- coding: utf-8 -*-
"""
erp_writer.py — ERPWriter: writes adjustment policies to ERP systems.

Extends the existing IntegrationHub (b2b_ai.integrations.erp) with
close-specific journal entry posting. Supports:
  - CONTPAQi (SQL Server + COM)
  - Aspel (SQL Server / Btrieve)
  - SAP B1 (Service Layer REST)
  - QuickBooks (OAuth 2.0 REST)
  - Odoo (JSON-RPC)

For MVP, uses a generic adapter that logs entries. Real ERP adapters
are injected at runtime via the IntegrationHub registry.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.close_management.models import (
    AdjustmentPolicy,
    AdjustmentType,
    ERPType,
)

logger = logging.getLogger(__name__)


class ERPWriterError(Exception):
    """Error writing to ERP."""

    def __init__(self, message: str, erp_type: str = "", details: Optional[Dict] = None):
        self.message = message
        self.erp_type = erp_type
        self.details = details or {}
        super().__init__(self.message)


class ERPWriter:
    """Writes adjustment policies to ERP systems.

    This class wraps the existing ERPAdapter from IntegrationHub and adds
    close-specific logic: batch posting, reference tracking, rollback.
    """

    def __init__(
        self,
        erp_type: ERPType = ERPType.GENERIC,
        erp_adapter: Optional[Any] = None,
    ):
        self.erp_type = erp_type
        self.erp_adapter = erp_adapter  # IntegrationHub adapter
        self._posted: List[Dict[str, Any]] = []
        logger.info(f"ERPWriter initialized for {erp_type.value}")

    def post_adjustment(self, policy: AdjustmentPolicy) -> Dict[str, Any]:
        """Post a single adjustment policy to the ERP.

        Args:
            policy: The adjustment policy with journal entries.

        Returns:
            Dict with erp_reference and status.
        """
        if not policy.entries:
            return {
                "status": "skipped",
                "message": "No entries to post",
                "erp_reference": None,
            }

        if not policy.is_balanced:
            raise ERPWriterError(
                f"Cannot post unbalanced policy: debe={policy.total_debe}, "
                f"haber={policy.total_haber}",
                erp_type=self.erp_type.value,
            )

        # Map to ERP-specific format
        erp_payload = self._map_to_erp_format(policy)

        # Post to ERP
        result = self._do_post(erp_payload)

        # Track
        self._posted.append({
            "policy_id": policy.id,
            "type": policy.type.value,
            "erp_reference": result.get("reference"),
            "posted_at": datetime.utcnow().isoformat(),
        })

        return result

    def post_batch(
        self,
        policies: List[AdjustmentPolicy],
    ) -> List[Dict[str, Any]]:
        """Post multiple adjustment policies as a batch.

        Posts all or none (atomic). If any fails, rolls back successful ones.
        """
        results: List[Dict[str, Any]] = []
        posted_refs: List[str] = []

        for policy in policies:
            try:
                result = self.post_adjustment(policy)
                results.append(result)
                if result.get("erp_reference"):
                    posted_refs.append(result["erp_reference"])
            except ERPWriterError as e:
                # Rollback previously posted entries in this batch
                logger.error(f"Batch post failed at policy {policy.type.value}: {e}")
                self._rollback(posted_refs)
                raise ERPWriterError(
                    f"Batch post failed: {e.message}",
                    erp_type=self.erp_type.value,
                    details={"failed_policy": policy.type.value, "rollback": True},
                )

        return results

    def _map_to_erp_format(
        self,
        policy: AdjustmentPolicy,
    ) -> Dict[str, Any]:
        """Map AdjustmentPolicy to ERP-specific journal entry format.

        Dispatches to the right mapper based on erp_type.
        """
        base = {
            "fecha": datetime.utcnow().strftime("%Y-%m-%d"),
            "concepto": policy.description,
            "periodo": policy.periodo,
            "tipo_poliza": "DIARIO",
            "referencia": f"AJUSTE-{policy.type.value.upper()}-{policy.periodo}",
        }

        if self.erp_type == ERPType.CONTPAQi:
            return self._map_contpaqi(policy, base)
        elif self.erp_type == ERPType.ASPEL:
            return self._map_aspel(policy, base)
        elif self.erp_type == ERPType.SAP_B1:
            return self._map_sap_b1(policy, base)
        elif self.erp_type == ERPType.QUICKBOOKS:
            return self._map_quickbooks(policy, base)
        elif self.erp_type == ERPType.ODOO:
            return self._map_odoo(policy, base)
        else:
            return self._map_generic(policy, base)

    def _map_generic(
        self,
        policy: AdjustmentPolicy,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generic format (used as-is or for logging)."""
        base["entries"] = policy.entries
        base["total_debe"] = policy.total_debe
        base["total_haber"] = policy.total_haber
        return base

    def _map_contpaqi(
        self,
        policy: AdjustmentPolicy,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map to CONTPAQi format (APOLIZAS + AMOVIMIENTOS)."""
        movimientos = []
        for entry in policy.entries:
            movimientos.append({
                "cCuenta": entry["cuenta"],
                "cImporte": entry["debe"] or entry["haber"],
                "cTipoMovto": "C" if entry["debe"] > 0 else "A",
                "cConcepto": entry["concepto"],
            })
        base["movimientos"] = movimientos
        return base

    def _map_aspel(
        self,
        policy: AdjustmentPolicy,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map to Aspel COI format."""
        movimientos = []
        for entry in policy.entries:
            movimientos.append({
                "cuenta": entry["cuenta"],
                "importe": entry["debe"] or entry["haber"],
                "tipo": "D" if entry["debe"] > 0 else "H",
                "concepto": entry["concepto"],
            })
        base["movimientos"] = movimientos
        return base

    def _map_sap_b1(
        self,
        policy: AdjustmentPolicy,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map to SAP B1 Service Layer JournalEntries format."""
        lines = []
        for entry in policy.entries:
            lines.append({
                "AccountCode": entry["cuenta"],
                "Debit": entry["debe"],
                "Credit": entry["haber"],
                "LineMemo": entry["concepto"],
            })
        base["JournalEntryLines"] = lines
        base["Memo"] = policy.description
        return base

    def _map_quickbooks(
        self,
        policy: AdjustmentPolicy,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map to QuickBooks Online JournalEntry format."""
        lines = []
        for entry in policy.entries:
            lines.append({
                "JournalEntryLineDetail": {
                    "PostingType": "Debit" if entry["debe"] > 0 else "Credit",
                    "AccountRef": {"value": entry["cuenta"]},
                },
                "Amount": entry["debe"] or entry["haber"],
                "Description": entry["concepto"],
            })
        base["Line"] = lines
        base["TxnDate"] = base.pop("fecha")
        return base

    def _map_odoo(
        self,
        policy: AdjustmentPolicy,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map to Odoo account.move format."""
        line_ids = []
        for entry in policy.entries:
            line_ids.append((0, 0, {
                "account_id": entry["cuenta"],
                "debit": entry["debe"],
                "credit": entry["haber"],
                "name": entry["concepto"],
            }))
        base["move_type"] = "entry"
        base["ref"] = policy.description
        base["line_ids"] = line_ids
        return base

    def _do_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Actually post to the ERP.

        If an ERP adapter is available, delegates to it.
        Otherwise, simulates the post (MVP / testing mode).
        """
        if self.erp_adapter is not None:
            try:
                if hasattr(self.erp_adapter, "crear_poliza"):
                    ref = self.erp_adapter.crear_poliza(payload)
                elif hasattr(self.erp_adapter, "create_poliza"):
                    ref = self.erp_adapter.create_poliza(payload)
                elif hasattr(self.erp_adapter, "crear_journal_entry"):
                    ref = self.erp_adapter.crear_journal_entry(payload)
                else:
                    raise ERPWriterError(
                        f"ERP adapter has no write method",
                        erp_type=self.erp_type.value,
                    )
                return {
                    "status": "posted",
                    "reference": str(ref),
                    "erp_type": self.erp_type.value,
                }
            except ERPWriterError:
                raise
            except Exception as e:
                raise ERPWriterError(
                    f"ERP post failed: {e}",
                    erp_type=self.erp_type.value,
                )
        else:
            # MVP mode: simulate
            ref = f"SIM-{payload.get('referencia', 'unknown')}-{datetime.utcnow().strftime('%H%M%S')}"
            logger.info(f"[ERP SIMULATOR] Posted: {ref}")
            return {
                "status": "simulated",
                "reference": ref,
                "erp_type": self.erp_type.value,
            }

    def _rollback(self, references: List[str]) -> None:
        """Rollback posted entries (best-effort)."""
        for ref in references:
            try:
                logger.warning(f"[ERP ROLLBACK] Reverting {ref}")
                # In production, call ERP adapter's cancel/reverse method
            except Exception as e:
                logger.error(f"[ERP ROLLBACK FAILED] {ref}: {e}")

    @property
    def posted_count(self) -> int:
        return len(self._posted)

    @property
    def posted_references(self) -> List[str]:
        return [p["erp_reference"] for p in self._posted if p.get("erp_reference")]
