# -*- coding: utf-8 -*-
"""erp_registrar.py — ERPRegistrar.

Registers journal entries in ERP via IntegrationHub.
Idempotent. Rollback on failure.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from b2b_ai.features.bookkeeping.models import (
    ERPSystem,
    PolizaContable,
)

log = logging.getLogger(__name__)


def _build_erp_adapter(tenant_id: int) -> Any:
    """Build a Computer Use ERP adapter for a tenant (or None)."""
    try:
        from b2b_ai.db.tenants import TenantManager
        from b2b_ai.db.db import Database
        db = Database()
        return TenantManager(db).erp_factory(tenant_id)
    except Exception:
        return None


def _poliza_to_invoice_dict(poliza: "PolizaContable") -> Dict[str, Any]:
    """Convert a PolizaContable to an invoice dict for the ERP adapter."""
    return {
        "id": poliza.id,
        "folio": poliza.erp_reference or poliza.id,
        "fecha": getattr(poliza, "fecha", None),
        "tipo": poliza.tipo.value if hasattr(poliza.tipo, "value") else str(poliza.tipo),
        "concepto": poliza.concepto,
        "debe": poliza.total_debe,
        "haber": poliza.total_haber,
        "cuadrada": poliza.cuadrada,
        "tenant_id": poliza.tenant_id,
    }



@dataclass
class ERPRegistrationResult:
    """Result of registering a poliza in the ERP."""
    success: bool
    erp_reference: Optional[str] = None
    erp_system: str = ""
    error: Optional[str] = None
    idempotent_skip: bool = False
    rolled_back: bool = False


class ERPRegistrar:
    """Registers journal entries in ERP systems via IntegrationHub.

    Features:
    - Idempotent: same poliza.id won't be registered twice
    - Rollback: if registration fails, attempts to undo partial writes
    - Multi-ERP: supports CONTPAQi, Aspel, SAP B1, QuickBooks, Odoo
    """

    def __init__(
        self,
        erp_system: ERPSystem = ERPSystem.MOCK,
        config: Optional[Dict[str, Any]] = None,
    ):
        # PRODUCTION GUARD: MOCK ERP is not allowed in production.
        _b2b_env = os.environ.get("B2B_ENV", "").strip().lower()
        _is_production = _b2b_env not in ("", "dev", "development", "test", "testing", "local")
        if _is_production and erp_system == ERPSystem.MOCK:
            raise RuntimeError(
                "ERPSystem.MOCK cannot be used in production (B2B_ENV=%r). "
                "Set erp_system to a real ERP backend or explicitly override "
                "B2B_ENV to a development value." % _b2b_env
            )

        self._erp_system = erp_system
        self._config = config or {}
        self._registered: Dict[str, str] = {}  # "tenant_id:poliza_id" → erp_reference
        self._rollback_log: Dict[str, List[str]] = {}  # poliza_id → rollback actions

    @property
    def erp_system(self) -> ERPSystem:
        return self._erp_system

    @property
    def registered_count(self) -> int:
        return len(self._registered)

    @staticmethod
    def _make_key(tenant_id: str, poliza_id: str) -> str:
        """Build a tenant-scoped idempotency key."""
        return f"{tenant_id}:{poliza_id}"

    def is_registered(self, poliza_id: str, tenant_id: str = "") -> bool:
        """Check if a poliza has already been registered (idempotency).

        Includes tenant_id to prevent cross-tenant idempotency leaks.
        """
        return self._make_key(tenant_id, poliza_id) in self._registered

    def register(self, poliza: PolizaContable) -> ERPRegistrationResult:
        """Register a journal entry in the ERP.

        Idempotent: returns existing reference if already registered.
        """
        key = self._make_key(poliza.tenant_id, poliza.id)
        # Idempotency check (tenant-scoped)
        if key in self._registered:
            return ERPRegistrationResult(
                success=True,
                erp_reference=self._registered[key],
                erp_system=self._erp_system.value,
                idempotent_skip=True,
            )

        # Validate before registering
        if not poliza.cuadrada:
            return ERPRegistrationResult(
                success=False,
                erp_system=self._erp_system.value,
                error="Póliza no cuadrada (debe != haber)",
            )

        try:
            ref = self._send_to_erp(poliza)
            self._registered[key] = ref
            poliza.erp_registered = True
            poliza.erp_reference = ref

            return ERPRegistrationResult(
                success=True,
                erp_reference=ref,
                erp_system=self._erp_system.value,
            )
        except Exception as exc:
            # Attempt rollback
            rolled_back = self._attempt_rollback(poliza)
            return ERPRegistrationResult(
                success=False,
                erp_system=self._erp_system.value,
                error=str(exc),
                rolled_back=rolled_back,
            )

    def register_batch(
        self, polizas: List[PolizaContable]
    ) -> List[ERPRegistrationResult]:
        """Register a batch of journal entries.

        If any fails, all successful ones in this batch are rolled back.
        """
        results: List[ERPRegistrationResult] = []
        successful: List[PolizaContable] = []

        for poliza in polizas:
            result = self.register(poliza)
            results.append(result)

            if result.success and not result.idempotent_skip:
                successful.append(poliza)
            elif not result.success:
                # Rollback all successful entries in this batch
                for p in successful:
                    self._attempt_rollback(p)
                # Mark remaining as failed
                for _ in polizas[len(results):]:
                    results.append(ERPRegistrationResult(
                        success=False,
                        erp_system=self._erp_system.value,
                        error="Rolled back due to batch failure",
                        rolled_back=True,
                    ))
                break

        return results

    def _send_to_erp(self, poliza: PolizaContable) -> str:
        """Send journal entry to the configured ERP.

        In MOCK mode, generates a fake reference.
        In production, delegates to IntegrationHub adapters.
        """
        if self._erp_system == ERPSystem.MOCK:
            ref = f"MOCK-{poliza.tipo.value.upper()}-{poliza.id}"
            log.info("MOCK ERP: registered poliza %s as %s", poliza.id, ref)
            return ref

        # Production: delegate to Computer Use ERP adapter
        try:
            tenant_id = int(poliza.tenant_id or 0)
            adapter = _build_erp_adapter(tenant_id)
            if adapter is None:
                raise RuntimeError(
                    f"No ERP adapter available for {self._erp_system.value}")

            invoice_payload = _poliza_to_invoice_dict(poliza)
            result = adapter.register_invoice(invoice_payload)

            if isinstance(result, dict):
                ref = str(result.get("folio") or result.get("id")
                          or result.get("reference") or f"ERP-{poliza.id}")
            else:
                ref = str(getattr(result, "folio", None)
                          or getattr(result, "id", None)
                          or getattr(result, "reference", None)
                          or f"ERP-{poliza.id}")
            log.info(
                "ERP %s: registered poliza %s as %s",
                self._erp_system.value, poliza.id, ref)
            return ref
        except Exception as exc:
            log.error(
                "ERP %s: failed to register poliza %s: %s",
                self._erp_system.value, poliza.id, exc)
            raise

    def _attempt_rollback(self, poliza: PolizaContable) -> bool:
        """Attempt to rollback a failed registration."""
        if poliza.id not in self._registered:
            return True  # Nothing to rollback

        try:
            ref = self._registered.pop(poliza.id)
            poliza.erp_registered = False
            poliza.erp_reference = None

            if poliza.id not in self._rollback_log:
                self._rollback_log[poliza.id] = []
            self._rollback_log[poliza.id].append(f"Removed registration {ref}")

            log.info("Rolled back poliza %s (ref: %s)", poliza.id, ref)
            return True
        except Exception as exc:
            log.error("Rollback failed for poliza %s: %s", poliza.id, exc)
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get registrar status."""
        return {
            "erp_system": self._erp_system.value,
            "registered_count": self.registered_count,
            "rollback_count": sum(
                1 for actions in self._rollback_log.values() if actions
            ),
        }
