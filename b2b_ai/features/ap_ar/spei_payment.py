# -*- coding: utf-8 -*-
"""
spei_payment.py — SPEI payment integration via STP (Banxico).

Sends interbank transfers programmatically via STP API.
Reference: SPEI (Sistema de Pagos Electrónicos Interbancarios).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Optional

from b2b_ai.features.ap_ar.models import PaymentOrder


class SPEIPayment:
    """Integration with STP (Banxico) for SPEI payment execution."""

    STP_BASE = "https://services.stpmex.com"

    def __init__(
        self,
        stp_token: Optional[str] = None,
        empresa: str = "",
        clabe_ordenante: str = "",
        nombre_ordenante: str = "",
        rfc_ordenante: str = "",
        institucion_ordenante: int = 90646,  # STP default
    ):
        self.stp_token = stp_token or os.environ.get("STP_TOKEN", "")
        self.empresa = empresa
        self.clabe_ordenante = clabe_ordenante
        self.nombre_ordenante = nombre_ordenante
        self.rfc_ordenante = rfc_ordenante
        self.institucion_ordenante = institucion_ordenante

    def build_payload(self, order: PaymentOrder) -> dict:
        """Build the STP API payload from a PaymentOrder.

        Does not send — just builds the dict for testing/inspection.
        """
        return {
            "claveRastreo": order.clave_rastreo,
            "conceptoPago": order.concepto_pago[:40],  # STP max 40 chars
            "cuentaBeneficiario": order.cuenta_beneficiario,
            "cuentaOrdenante": order.cuenta_ordenante or self.clabe_ordenante,
            "empresa": order.empresa or self.empresa,
            "institucionContraparte": order.institucion_beneficiario,
            "institucionOperante": order.institucion_ordenante or self.institucion_ordenante,
            "monto": order.monto,
            "nombreBeneficiario": order.nombre_beneficiario[:60],
            "nombreOrdenante": order.nombre_ordenante or self.nombre_ordenante,
            "rfcCurpBeneficiario": order.rfc_beneficiario,
            "rfcCurpOrdenante": order.rfc_ordenante or self.rfc_ordenante,
            "tipoCuentaBeneficiario": 40,  # CLABE
            "tipoCuentaOrdenante": 40,
            "tipoPago": 1,
        }

    async def enviar_pago(self, order: PaymentOrder) -> dict:
        """Send SPEI payment via STP.

        Returns a dict with 'stp_id', 'status', and 'error' (if any).
        In sandbox/test mode, simulates a successful response.
        """
        payload = self.build_payload(order)

        if not self.stp_token or self.stp_token.startswith("test"):
            # Sandbox mode: simulate success
            stp_id = hashlib.md5(
                f"{order.clave_rastreo}{order.monto}{datetime.utcnow().isoformat()}"
                .encode()
            ).hexdigest()[:16]
            return {
                "stp_id": stp_id,
                "status": "LIQUIDACION",
                "clave_rastreo": order.clave_rastreo,
                "error": None,
            }

        # Real STP API call (httpx async)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.STP_BASE}/ordenPago",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.stp_token}"},
                )
                data = resp.json()
                return {
                    "stp_id": data.get("id"),
                    "status": data.get("estado", "PENDIENTE"),
                    "clave_rastreo": order.clave_rastreo,
                    "error": data.get("mensajeError"),
                }
        except Exception as e:
            return {
                "stp_id": None,
                "status": "ERROR",
                "clave_rastreo": order.clave_rastreo,
                "error": str(e),
            }

    async def consultar_estado(self, clave_rastreo: str) -> dict:
        """Check the status of a SPEI transfer by tracking key."""
        if not self.stp_token or self.stp_token.startswith("test"):
            return {
                "clave_rastreo": clave_rastreo,
                "status": "LIQUIDACION",
                "error": None,
            }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.STP_BASE}/ordenPago/{clave_rastreo}",
                    headers={"Authorization": f"Bearer {self.stp_token}"},
                )
                return resp.json()
        except Exception as e:
            return {
                "clave_rastreo": clave_rastreo,
                "status": "ERROR",
                "error": str(e),
            }

    def validate_clabe(self, clabe: str) -> bool:
        """Validate a CLABE interbancaria (18 digits with check digit).

        Algorithm: weighted modulo 10 check digit.
        """
        clabe = clabe.strip().replace(" ", "").replace("-", "")
        if len(clabe) != 18 or not clabe.isdigit():
            return False

        weights = [3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7]
        total = sum(int(clabe[i]) * weights[i] for i in range(17))
        check_digit = (10 - (total % 10)) % 10
        return int(clabe[17]) == check_digit
