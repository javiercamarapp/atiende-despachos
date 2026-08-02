# -*- coding: utf-8 -*-
"""
Módulo Bank Feeds: importación automática de transacciones bancarias desde
bancos mexicanos (BBVA, Banorte, Santander, HSBC) vía SPEI, CoDi y banca en
línea.

Expone:
  - BankProvider, TransactionType, PaymentChannel, SyncStatus,
    TransactionStatus, Category — enums
  - BankAccount, Transaction, FeedSync, FeedSyncResult — schemas
  - BankFeedService — sync_transactions, reconcile_with_cfdi, categorize...
  - adapters: BBVAAdapter, BanorteAdapter, SantanderAdapter, HSBCAdapter,
    MockBankAdapter, get_adapter
  - processors: parse_ofx, parse_cnbv, RawMovement
  - build_bank_feeds_router() — FastAPI router (/api/v1/bank-feeds/*)
"""
from __future__ import annotations

from b2b_ai.features.bank_feeds.models import (
    BankAccount,
    BankProvider,
    Category,
    FeedSync,
    FeedSyncResult,
    PaymentChannel,
    SyncStatus,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from b2b_ai.features.bank_feeds.service import BankFeedService
from b2b_ai.features.bank_feeds.routes import build_bank_feeds_router

__all__ = [
    # Enums
    "BankProvider",
    "TransactionType",
    "PaymentChannel",
    "SyncStatus",
    "TransactionStatus",
    "Category",
    # Schemas
    "BankAccount",
    "Transaction",
    "FeedSync",
    "FeedSyncResult",
    # Service
    "BankFeedService",
    # Router
    "build_bank_feeds_router",
]
