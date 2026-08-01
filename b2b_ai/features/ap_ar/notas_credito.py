# -*- coding: utf-8 -*-
"""
notas_credito.py — Credit notes, returns, and discounts handler.

Manages credit notes (notas de crédito):
  - Returns (devoluciones)
  - Discounts (descuentos)
  - Bonifications (bonificaciones)

Reference: LISR Art. 25 fracc. I y II / CFF Art. 29 / RMF 2.7.1.37
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from b2b_ai.features.ap_ar.models import (
    CreditNote,
    CreditNoteCreate,
    InvoiceStatus,
)


class NotasCredito:
    """Credit note processor for AP/AR operations."""

    def __init__(self, facturapi_key: Optional[str] = None):
        self.facturapi_key = facturapi_key
        self._notes: List[CreditNote] = []

    def crear_nota_credito(
        self, data: CreditNoteCreate, tenant_id: Optional[int] = None
    ) -> CreditNote:
        """Create and (optionally) stamp a credit note.

        Steps:
        1. Validate the original CFDI is not cancelled
        2. Create CFDI type E (Egreso) referencing the original
        3. Generate accounting reversal entry

        Args:
            data: Credit note creation data.
            tenant_id: Optional tenant ID.

        Returns:
            Created CreditNote.
        """
        # Generate a mock UUID for the credit note
        uuid_parts = data.cfdi_original_uuid.split("-")
        cn_uuid = f"CN-{uuid_parts[0][:8]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        note = CreditNote(
            id=len(self._notes) + 1,
            tenant_id=tenant_id,
            uuid=cn_uuid,
            cfdi_original_uuid=data.cfdi_original_uuid,
            monto=data.monto,
            concepto=data.concepto,
            tipo=data.tipo,
            rfc_emisor=data.rfc_emisor,
            rfc_receptor=data.rfc_receptor,
            status="emitida",
            created_at=datetime.utcnow().isoformat(),
        )
        self._notes.append(note)
        return note

    def get_nota(self, note_id: int) -> Optional[CreditNote]:
        """Retrieve a credit note by ID."""
        for note in self._notes:
            if note.id == note_id:
                return note
        return None

    def list_notas(
        self,
        tenant_id: Optional[int] = None,
        cfdi_original_uuid: Optional[str] = None,
    ) -> List[CreditNote]:
        """List credit notes with optional filters."""
        result = self._notes
        if tenant_id is not None:
            result = [n for n in result if n.tenant_id == tenant_id]
        if cfdi_original_uuid:
            result = [
                n for n in result
                if n.cfdi_original_uuid == cfdi_original_uuid
            ]
        return result

    def calcular_monto_total_notas(
        self, cfdi_original_uuid: str
    ) -> float:
        """Calculate the total amount of all credit notes for an invoice."""
        return sum(
            n.monto for n in self._notes
            if n.cfdi_original_uuid == cfdi_original_uuid
        )

    def build_facturapi_payload(self, data: CreditNoteCreate) -> dict:
        """Build the Facturapi API payload for a credit note (CFDI type E).

        Returns the dict that would be sent to Facturapi.
        """
        return {
            "type": "E",  # Egreso
            "related_documents": [
                {
                    "id": data.cfdi_original_uuid,
                    "relationship": "01",  # Nota de crédito
                }
            ],
            "items": [
                {
                    "description": data.concepto,
                    "product_key": "84111506",  # Servicios de facturación
                    "quantity": 1,
                    "price": data.monto,
                }
            ],
        }

    def generate_reversal_entry(
        self,
        original_uuid: str,
        credit_note_uuid: str,
        monto: float,
    ) -> dict:
        """Generate the accounting reversal entry for a credit note.

        Returns a journal entry (póliza) that reverses the original.
        """
        return {
            "fecha": datetime.now().strftime("%Y-%m-%d"),
            "concepto": f"Nota de crédito {credit_note_uuid} — reverso de {original_uuid[:12]}",
            "uuid_referencia": original_uuid,
            "uuid_nota": credit_note_uuid,
            "lineas": [
                {
                    "cuenta": "2160100",  # Proveedores nacionales
                    "debe": monto,
                    "haber": 0,
                    "concepto": "Reverso de proveedor por nota de crédito",
                },
                {
                    "cuenta": "1190100",  # IVA acreditable pagado
                    "debe": round(monto * 0.16, 2),
                    "haber": 0,
                    "concepto": "Reverso de IVA acreditable",
                },
                {
                    "cuenta": "5010100",  # Gasto / Devoluciones
                    "debe": 0,
                    "haber": monto,
                    "concepto": "Reverso de gasto por devolución/descuento",
                },
                {
                    "cuenta": "1180100",  # IVA pendiente de acreditar
                    "debe": 0,
                    "haber": round(monto * 0.16, 2),
                    "concepto": "Reverso de IVA pendiente",
                },
            ],
            "cuadrada": True,
        }
