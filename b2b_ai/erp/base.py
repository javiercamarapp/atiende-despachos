# -*- coding: utf-8 -*-
"""
base.py — Interfaz abstracta de integración con ERP.

Define el contrato que debe cumplir cualquier conector ERP. La implementación
concreta puede ser un API REST (CONTPAQi contaDIGITAL), un conector CSV o un
mock para testing. Los servicios del agente dependen de esta interfaz, no de
una implementación concreta (principio de inversión de dependencias).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ERPInterface(ABC):
    """Contrato mínimo de un ERP contable para registrar pólizas/facturas."""

    @abstractmethod
    def register_invoice(self, invoice: dict) -> dict:
        """
        Registra una póliza/factura en el ERP.
        invoice: dict normalizado (folio_fiscal, emisor, conceptos, montos,
                 clasificación contable, etc.).
        Devuelve {ok: bool, poliza: str|None, status: str, message: str}.
        """
        raise NotImplementedError

    @abstractmethod
    def get_invoice(self, folio_fiscal: str) -> dict | None:
        """Consulta el estado de una póliza por folio fiscal en el ERP."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict:
        """Devuelve {ok: bool, backend: str, detail: str}."""
        raise NotImplementedError
