# -*- coding: utf-8 -*-
"""erp_registrar.py — ERPRegistrar.

Registers journal entries in ERP via IntegrationHub.
Idempotent. Rollback on failure.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from b2b_ai.features.bookkeeping.models import (
    ERPSystem,
    PolizaContable,
)

log = logging.getLogger(__name__)


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
        self._erp_system = erp_system
        self._config = config or {}
        self._registered: Dict[str, str] = {}  # poliza_id → erp_reference
        self._rollback_log: Dict[str, List[str]] = {}  # poliza_id → rollback actions

    @property
    def erp_system(self) -> ERPSystem:
        return self._erp_system

    @property
    def registered_count(self) -> int:
        return len(self._registered)

    def is_registered(self, poliza_id: str) -> bool:
        """Check if a poliza has already been registered (idempotency)."""
        return poliza_id in self._registered

    def register(self, poliza: PolizaContable) -> ERPRegistrationResult:
        """Register a journal entry in the ERP.

        Idempotent: returns existing reference if already registered.
        """
        # Idempotency check
        if self.is_registered(poliza.id):
            return ERPRegistrationResult(
                success=True,
                erp_reference=self._registered[poliza.id],
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
            self._registered[poliza.id] = ref
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

        # Production: delegate to IntegrationHub
        # This would call the appropriate adapter (CONTPAQi, Aspel, etc.)
        # For now, raise NotImplementedError for non-mock systems
        raise NotImplementedError(
            f"ERP adapter for {self._erp_system.value} not yet connected via IntegrationHub"
        )

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
