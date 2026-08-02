# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo de Bank Feeds.

BankFeedService:
  - register_account      : da de alta una cuenta bancaria
  - list_accounts         : lista cuentas del tenant
  - get_account           : consulta una cuenta
  - sync_transactions     : extrae movimientos del feed y los importa (dedupe)
  - list_transactions     : lista transacciones de una cuenta
  - categorize_transaction: asigna categoría (automática por heurística o manual)
  - reconcile_with_cfdi   : cruza transacciones importadas contra CFDI/pólizas
                            usando el motor de conciliación existente
  - get_syncs             : historial de sincronizaciones de una cuenta

Almacenamiento: en memoria (dict) con reset_state() para tests, coherente con
el patrón del módulo batch y webhooks. La interfaz permite inyectar una capa
de persistencia (db) sin cambiar la firma.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.bank_feeds.adapters import get_adapter
from b2b_ai.features.bank_feeds.categorizer import TransactionCategorizer
from b2b_ai.features.bank_feeds.models import (
    BankAccount,
    BankProvider,
    Category,
    FeedSync,
    FeedSyncResult,
    SyncStatus,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from b2b_ai.features.bank_feeds.processors.ofx import RawMovement

logger = logging.getLogger("b2b_ai.bank_feeds")

# ---------------------------------------------------------------------------
# Store en memoria (patrón batch/webhooks)
# ---------------------------------------------------------------------------
_accounts: Dict[str, BankAccount] = {}
_transactions: Dict[str, Transaction] = {}
_syncs: Dict[str, FeedSync] = {}
# external_id -> transaction id (dedupe por cuenta)
_external_index: Dict[str, str] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _accounts.clear()
    _transactions.clear()
    _syncs.clear()
    _external_index.clear()


# ---------------------------------------------------------------------------
# Motor de categorización (nuevo)
# ---------------------------------------------------------------------------

# Instancia por defecto reutilizada por el servicio. Se puede reconfigurar en
# caliente (add_rfc_rule / add_keyword_rule) o sustituir con un motor custom.
_categorizer = TransactionCategorizer()


def set_categorizer(categorizer: TransactionCategorizer) -> None:
    """Reemplaza el motor de categorización usado por el servicio (tests/custom)."""
    global _categorizer
    _categorizer = categorizer


def get_categorizer() -> TransactionCategorizer:
    """Devuelve el motor de categorización activo."""
    return _categorizer


def _categorize_text(description: str) -> Category:
    """Categoriza por heurística de palabras clave sobre la descripción."""
    value = _categorizer.categorize_transaction(
        {"description": description or "", "channel": "OTRO"}
    )
    try:
        return Category(str(value))
    except ValueError:
        return Category.OTROS


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class BankFeedService:
    """Servicio principal de bank feeds."""

    def __init__(self, db: Any = None):
        self.db = db

    # ------------------------------------------------------------------
    # Cuentas
    # ------------------------------------------------------------------
    def register_account(
        self,
        provider: BankProvider,
        clabe: str = "",
        account_label: str = "",
        tenant_id: str = "",
        **extra: Any,
    ) -> BankAccount:
        """Da de alta una cuenta bancaria y la guarda."""
        account = BankAccount(
            provider=provider,
            clabe=clabe,
            account_label=account_label,
            tenant_id=tenant_id,
            metadata=extra,
        )
        _accounts[account.id] = account
        logger.info("bank account registered id=%s provider=%s", account.id, provider.value)
        return account

    def list_accounts(self, tenant_id: str = "") -> List[BankAccount]:
        return [a for a in _accounts.values()
                if (not tenant_id or a.tenant_id == tenant_id)]

    def get_account(self, account_id: str) -> Optional[BankAccount]:
        return _accounts.get(account_id)

    # ------------------------------------------------------------------
    # Sincronización
    # ------------------------------------------------------------------
    def sync_transactions(
        self,
        account_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 200,
    ) -> FeedSyncResult:
        """Extrae movimientos del feed del banco y los importa.

        Dedupe por ``external_id`` por cuenta: los movimientos ya vistos se
        cuentan como duplicados y no se re-importan.

        Raises:
            KeyError: si la cuenta no existe.
            RuntimeError: si el feed falla (red / credenciales).
        """
        account = _accounts.get(account_id)
        if account is None:
            raise KeyError(f"Cuenta bancaria no encontrada: {account_id}")

        sync = FeedSync(account_id=account_id, provider=account.provider,
                        status=SyncStatus.RUNNING)
        _syncs[sync.id] = sync

        try:
            adapter = get_adapter(account.provider)
            raw_movements = adapter.fetch_transactions(
                account.to_dict(), from_date, to_date, limit
            )
        except Exception as exc:  # noqa: BLE001 — fallo de feed
            sync.status = SyncStatus.FAILED
            sync.completed_at = datetime.utcnow()
            sync.error = f"{type(exc).__name__}: {exc}"
            logger.warning("bank feed sync failed account=%s err=%s", account_id, sync.error)
            raise RuntimeError(sync.error) from exc

        sync.found_count = len(raw_movements)
        imported: List[Transaction] = []

        for mv in raw_movements:
            key = _external_key(account_id, mv.external_id)
            if key in _external_index:
                sync.duplicate_count += 1
                continue
            txn = self._build_transaction(account, mv)
            _transactions[txn.id] = txn
            _external_index[key] = txn.id
            imported.append(txn)
            sync.imported_count += 1

        sync.status = SyncStatus.COMPLETED
        sync.completed_at = datetime.utcnow()
        logger.info(
            "bank feed sync done account=%s found=%d imported=%d dup=%d",
            account_id, sync.found_count, sync.imported_count, sync.duplicate_count,
        )
        return FeedSyncResult(sync=sync, transactions=imported)

    def _build_transaction(self, account: BankAccount, mv: RawMovement) -> Transaction:
        """Convierte un RawMovement en Transaction aplicando canal y categoría."""
        mapped = self._adapter_for(account).map_movement(mv, account_id=account.id)
        channel = (mv.extra or {}).get("channel", "OTRO") if isinstance(mv.extra, dict) else "OTRO"
        desc = mapped.get("description") or ""
        txn_type = TransactionType(mapped["type"]) if mapped.get("type") else TransactionType.INGRESO
        return Transaction(
            account_id=account.id,
            provider=account.provider,
            external_id=mapped["external_id"],
            date=mapped["date"],
            description=desc,
            reference=mapped.get("reference") or "",
            amount=float(mapped["amount"]),
            type=txn_type,
            channel=_to_channel(channel),
            counterparty=mapped.get("counterparty") or "",
            category=self._categorizer_category(
                desc, channel=channel, amount=float(mapped["amount"])
            ),
        )

    @staticmethod
    def _categorizer_category(
        description: str,
        channel: str = "OTRO",
        amount: float = 0.0,
        counterparty: str = "",
    ) -> Optional[Category]:
        """Categoriza una transacción con el motor de categorización activo."""
        value = _categorizer.categorize_transaction({
            "description": description or "",
            "channel": channel or "OTRO",
            "amount": amount,
            "counterparty": counterparty or "",
        })
        try:
            return Category(str(value))
        except ValueError:
            return None

    @staticmethod
    def _adapter_for(account: BankAccount):
        return get_adapter(account.provider)

    # ------------------------------------------------------------------
    # Transacciones
    # ------------------------------------------------------------------
    def list_transactions(
        self,
        account_id: Optional[str] = None,
        status: Optional[TransactionStatus] = None,
        category: Optional[Category] = None,
        limit: int = 200,
    ) -> List[Transaction]:
        items = list(_transactions.values())
        if account_id:
            items = [t for t in items if t.account_id == account_id]
        if status:
            items = [t for t in items if t.status == status]
        if category:
            items = [t for t in items if t.category == category]
        # Más recientes primero.
        items.sort(key=lambda t: (t.date, t.id), reverse=True)
        return items[:limit] if limit and limit > 0 else items

    def get_transaction(self, txn_id: str) -> Optional[Transaction]:
        return _transactions.get(txn_id)

    # ------------------------------------------------------------------
    # Categorización
    # ------------------------------------------------------------------
    def categorize_transaction(
        self,
        txn_id: str,
        category: Optional[Category] = None,
        auto: bool = False,
    ) -> Transaction:
        """Asigna categoría a una transacción.

        - Si ``category`` se pasa, se asigna explícitamente.
        - Si ``auto`` es True, se infiere con el motor de categorización
          (TransactionCategorizer) sobre la transacción completa.
        """
        txn = _transactions.get(txn_id)
        if txn is None:
            raise KeyError(f"Transacción no encontrada: {txn_id}")
        if category is not None:
            txn.category = category
        elif auto:
            txn.category = self._categorizer_category(
                txn.description,
                channel=(txn.channel.value if hasattr(txn, "channel") else "OTRO"),
                amount=txn.amount,
                counterparty=txn.counterparty,
            )
        if txn.category is not None and txn.status == TransactionStatus.IMPORTED:
            txn.status = TransactionStatus.CATEGORIZED
        return txn

    # ------------------------------------------------------------------
    # Conciliación con CFDI / pólizas
    # ------------------------------------------------------------------
    def reconcile_with_cfdi(
        self,
        account_id: Optional[str] = None,
        cfdi_list: Optional[List[Dict[str, Any]]] = None,
        tolerance_days: int = 3,
    ) -> Dict[str, Any]:
        """Cruza transacciones importadas contra CFDIs/pólizas.

        Usa ConciliationService (módulo conciliacion existente) para ejecutar
        el matching. Devuelve un reporte con coincidencias y discrepancias.

        Parameters
        ----------
        account_id : str, optional
            Si se da, solo concilia transacciones de esa cuenta.
        cfdi_list : List[dict], optional
            CFDIs en forma CFDIReference (uuid, fecha, total, rfc_emisor...).
        tolerance_days : int
            Tolerancia de fechas para AMOUNT_DATE matching.

        Returns
        -------
        dict con: reconciled (int), unmatched (int), matches (list),
                  discrepancies (list), report (dict del motor).
        """
        transactions = self.list_transactions(account_id=account_id)
        if not transactions:
            return {"reconciled": 0, "unmatched": 0, "matches": [], "discrepancies": [], "report": None}

        try:
            from b2b_ai.features.conciliacion.models import (
                BankTransaction,
                CFDIReference,
                TransactionType as ConciliacionTransactionType,
            )
            from b2b_ai.features.conciliacion.service import ConciliationService
        except Exception as exc:  # noqa: BLE001
            logger.warning("conciliacion module unavailable: %s", exc)
            return {"reconciled": 0, "unmatched": len(transactions), "matches": [],
                    "discrepancies": [], "report": None}

        bank_txns = [
            BankTransaction(
                id=t.external_id,
                date=t.date,
                description=t.description,
                amount=t.amount,
                type=ConciliacionTransactionType.INGRESO if t.amount >= 0
                else ConciliacionTransactionType.EGRESO,
                reference=t.reference or t.external_id,
                bank_account=t.account_id,
            )
            for t in transactions
        ]

        cfdi_refs = None
        if cfdi_list:
            cfdi_refs = [
                CFDIReference(**c) if isinstance(c, dict) else c
                for c in cfdi_list
            ]

        svc = ConciliationService()
        report = svc.reconcile_bank_statement(
            transactions=bank_txns,
            polizas=None,
            cfdi_list=cfdi_refs,
            tolerance_days=tolerance_days,
        )

        return self._summarize_reconciliation(bank_txns, report)

    @staticmethod
    def _summarize_reconciliation(
        bank_txns: List[Any], report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normaliza el reporte del motor de conciliación a un resumen simple."""
        matches = report.get("matches") or report.get("matched") or []
        discrepancies = report.get("discrepancies") or report.get("discrepancies_list") or []
        if isinstance(matches, dict):
            matches = matches.get("items") or list(matches.values())
        reconciled = len(matches) if isinstance(matches, list) else 0
        unmatched = max(0, len(bank_txns) - reconciled)
        return {
            "reconciled": reconciled,
            "unmatched": unmatched,
            "total": len(bank_txns),
            "matches": matches,
            "discrepancies": discrepancies,
            "report": report,
        }

    # ------------------------------------------------------------------
    # Sincronizaciones
    # ------------------------------------------------------------------
    def get_syncs(self, account_id: Optional[str] = None) -> List[FeedSync]:
        items = list(_syncs.values())
        if account_id:
            items = [s for s in items if s.account_id == account_id]
        items.sort(key=lambda s: s.started_at, reverse=True)
        return items


def _external_key(account_id: str, external_id: str) -> str:
    return f"{account_id}::{external_id}"


def _to_channel(value: str):
    from b2b_ai.features.bank_feeds.models import PaymentChannel
    try:
        return PaymentChannel(value.upper().replace(" ", "_"))
    except ValueError:
        return PaymentChannel.OTRO
