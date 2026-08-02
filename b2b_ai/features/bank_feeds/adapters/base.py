# -*- coding: utf-8 -*-
"""
base.py — Clase base de los adapters bancarios.

Define la interfaz común (fetch_transactions) y helpers para convertir
movimientos raw (RawMovement) en dicts normalizados. Para el MVP el "origen"
puede ser un texto OFX/QFX/CNBV o un mock; el método ``fetch`` real se
implementa en las subclases cuando se conecta a la banca en línea.
"""
from __future__ import annotations

import abc
from typing import List, Optional

from b2b_ai.features.bank_feeds.models import BankProvider
from b2b_ai.features.bank_feeds.processors.ofx import RawMovement


class BaseBankAdapter(abc.ABC):
    """Interfaz común para conectar con un banco y extraer transacciones."""

    provider: BankProvider = None  # type: ignore[assignment]  # override en subclases

    def __init__(self, http_session=None, base_url: Optional[str] = None):
        self.http = http_session
        self.base_url = base_url

    @abc.abstractmethod
    def fetch_transactions(
        self,
        account: dict,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawMovement]:
        """Extrae movimientos de la cuenta.

        Parameters
        ----------
        account : dict
            Datos de la cuenta (clabe, credentials, etc.).
        from_date / to_date : str, optional
            Rango de fechas (YYYY-MM-DD).
        limit : int
            Máximo de movimientos a devolver.

        Returns
        -------
        List[RawMovement]
            Movimientos normalizados. Debe lanzar RuntimeError si no puede
            autenticar/leer el feed.
        """

    # ------------------------------------------------------------------
    # Helpers de mapeo
    # ------------------------------------------------------------------
    def map_movement(
        self,
        mv: RawMovement,
        account_id: str,
        provider: Optional[BankProvider] = None,
    ) -> dict:
        """Convierte un RawMovement en un dict listo para construir una
        Transaction (consistente con Transaction.to_dict)."""
        provider = provider or self.provider
        amount = _to_float(mv.amount) or 0.0
        # OFX: CREDIT es ingreso (positivo), DEBIT egreso (negativo).
        if mv.type_raw.upper() in ("DEBIT", "DEBITO", "CARGO"):
            if amount >= 0:
                amount = -amount
            txn_type = "EGRESO"
        else:
            if amount < 0:
                amount = abs(amount)
            txn_type = "INGRESO"
        return {
            "account_id": account_id,
            "provider": provider.value if provider else "",
            "external_id": mv.external_id,
            "date": mv.date,
            "description": mv.description or mv.memo,
            "reference": mv.extra.get("reference", "") if isinstance(mv.extra, dict) else "",
            "amount": amount,
            "type": txn_type,
            "counterparty": mv.extra.get("counterparty", "") if isinstance(mv.extra, dict) else "",
        }


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def slice_movements(movements: List[RawMovement], limit: int) -> List[RawMovement]:
    """Recorta una lista de movimientos al límite solicitado."""
    return movements[:limit] if limit and limit > 0 else movements
