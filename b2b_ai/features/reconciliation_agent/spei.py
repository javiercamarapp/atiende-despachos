# -*- coding: utf-8 -*-
"""
spei.py — SPEI Payment Verification.

Verifies SPEI payments via:
  1. STP API (Sistema de Transferencias y Pagos)
  2. Banxico CEP (Comprobante Electrónico de Pago)
  3. Bank movement matching

Extends the SPEI verification described in the blueprint.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.reconciliation_agent.models import (
    BankMovement,
    SPEIVerificationResult,
)

logger = logging.getLogger(__name__)


class SPEIVerifier:
    """SPEI payment verification engine.

    Verifies SPEI payments through multiple methods:
      - STP API (requires API key)
      - Banxico CEP portal
      - Bank movement matching
    """

    def __init__(
        self,
        stp_api_key: Optional[str] = None,
        stp_base_url: str = "https://stp-api.i-banxico.gob.mx",
        banxico_token: Optional[str] = None,
        http_client: Any = None,
    ):
        self.stp_api_key = stp_api_key
        self.stp_base_url = stp_base_url
        self.banxico_token = banxico_token
        self._http = http_client

    async def verify_by_clave_rastreo(
        self,
        clave_rastreo: str,
        fecha: str,
        monto: Optional[float] = None,
    ) -> SPEIVerificationResult:
        """Verify a SPEI payment by tracking key (clave de rastreo).

        Args:
            clave_rastreo: SPEI tracking key (e.g., "BNET0123456789")
            fecha: Payment date (YYYY-MM-DD)
            monto: Expected amount (optional for verification)

        Returns:
            SPEIVerificationResult with verification status.
        """
        if not clave_rastreo:
            return SPEIVerificationResult(
                verified=False,
                error="Clave de rastreo requerida",
            )

        # Try STP API first
        if self.stp_api_key:
            result = await self._query_stp(clave_rastreo, fecha)
            if result.verified:
                return result

        # Try Banxico CEP
        if self.banxico_token:
            result = await self._query_banxico_cep(clave_rastreo, fecha, monto)
            if result.verified:
                return result

        # Fallback: check against bank movements
        return SPEIVerificationResult(
            verified=False,
            status="pending_verification",
            clave_rastreo=clave_rastreo,
            error="No se pudo verificar. Configure STP API key o Banxico token.",
        )

    async def verify_against_movements(
        self,
        clave_rastreo: str,
        monto: float,
        fecha: str,
        movements: List[BankMovement],
        date_tolerance_days: int = 3,
    ) -> SPEIVerificationResult:
        """Verify a SPEI payment against bank movements.

        Searches for a movement matching the tracking key and amount.
        """
        fecha_dt = self._parse_date(fecha)
        if fecha_dt is None:
            return SPEIVerificationResult(
                verified=False,
                error=f"Fecha inválida: {fecha}",
            )

        best_match = None
        best_score = 0

        for mov in movements:
            score = 0

            # Check reference match
            ref = (mov.referencia or "").strip().upper()
            clave = clave_rastreo.strip().upper()
            if clave in ref or ref in clave:
                score += 60
            elif clave[:8] in ref or ref[:8] in clave:
                score += 30

            # Check amount
            if abs(abs(mov.monto) - abs(monto)) < 0.01:
                score += 30
            elif abs(abs(mov.monto) - abs(monto)) / max(abs(monto), 1) < 0.05:
                score += 15

            # Check date
            mov_dt = self._parse_date(mov.fecha)
            if mov_dt and fecha_dt:
                diff = abs((mov_dt - fecha_dt).days)
                if diff == 0:
                    score += 10
                elif diff <= date_tolerance_days:
                    score += 5

            if score > best_score:
                best_score = score
                best_match = mov

        if best_match and best_score >= 60:
            return SPEIVerificationResult(
                clave_rastreo=clave_rastreo,
                verified=True,
                status="verified_via_movements",
                monto=best_match.monto,
                fecha=best_match.fecha,
                emisor=best_match.descripcion,
            )

        return SPEIVerificationResult(
            clave_rastreo=clave_rastreo,
            verified=False,
            status="not_found_in_movements",
            error="No se encontró movimiento bancario coincidente",
        )

    async def _query_stp(
        self, clave_rastreo: str, fecha: str
    ) -> SPEIVerificationResult:
        """Query STP API for payment status."""
        try:
            if self._http is None:
                import httpx
                self._http = httpx.AsyncClient(timeout=30)

            url = f"{self.stp_base_url}/spei/consulta"
            headers = {"Authorization": f"Bearer {self.stp_api_key}"}
            payload = {
                "claveRastreo": clave_rastreo,
                "fechaOperacion": fecha.replace("-", ""),
            }

            resp = await self._http.post(url, json=payload, headers=headers)

            if resp.status_code == 200:
                data = resp.json()
                return SPEIVerificationResult(
                    clave_rastreo=clave_rastreo,
                    verified=True,
                    status=data.get("estado", "verified"),
                    monto=float(data.get("monto", 0)),
                    fecha=fecha,
                    emisor=data.get("ordenanteNombre"),
                    receptor=data.get("beneficiarioNombre"),
                )
            else:
                return SPEIVerificationResult(
                    clave_rastreo=clave_rastreo,
                    verified=False,
                    status="stp_error",
                    error=f"STP API returned {resp.status_code}",
                )
        except Exception as e:
            logger.warning(f"STP API error: {e}")
            return SPEIVerificationResult(
                clave_rastreo=clave_rastreo,
                verified=False,
                status="stp_error",
                error=str(e),
            )

    async def _query_banxico_cep(
        self,
        clave_rastreo: str,
        fecha: str,
        monto: Optional[float] = None,
    ) -> SPEIVerificationResult:
        """Query Banxico CEP (Comprobante Electrónico de Pago)."""
        try:
            if self._http is None:
                import httpx
                self._http = httpx.AsyncClient(timeout=30)

            url = "https://www.banxico.org.mx/cep/descarga.do"
            payload = {
                "claveRastreo": clave_rastreo,
                "fecha": fecha,
                "tipoCuentaOrdenante": 40,  # CLABE
                "tipoCuentaBeneficiario": 40,
                "institucionOrdenante": "000",
                "institucionBeneficiario": "000",
                "monto": str(monto or 0),
            }

            resp = await self._http.post(url, data=payload)

            if resp.status_code == 200 and len(resp.content) > 1000:
                # CEP PDF was returned — payment exists
                return SPEIVerificationResult(
                    clave_rastreo=clave_rastreo,
                    verified=True,
                    status="verified_via_cep",
                    monto=monto,
                    fecha=fecha,
                    cep_url=url,
                )
            else:
                return SPEIVerificationResult(
                    clave_rastreo=clave_rastreo,
                    verified=False,
                    status="cep_not_found",
                    error="CEP no encontrado para esta clave de rastreo",
                )
        except Exception as e:
            logger.warning(f"Banxico CEP error: {e}")
            return SPEIVerificationResult(
                clave_rastreo=clave_rastreo,
                verified=False,
                status="cep_error",
                error=str(e),
            )

    def verify_pago_proveedor(
        self,
        proveedor_rfc: str,
        monto: float,
        fecha_aprox: str,
        movements: List[BankMovement],
        date_tolerance_days: int = 3,
    ) -> Optional[BankMovement]:
        """Find a bank movement that matches a supplier payment.

        Args:
            proveedor_rfc: Supplier RFC (tax ID)
            monto: Expected payment amount
            fecha_aprox: Approximate payment date
            movements: Bank movements to search

        Returns:
            Best matching BankMovement or None.
        """
        fecha_dt = self._parse_date(fecha_aprox)
        best = None
        best_score = 0

        for mov in movements:
            score = 0
            desc = (mov.descripcion or "").upper()
            rfc_upper = proveedor_rfc.upper()

            # RFC in description
            if rfc_upper in desc:
                score += 50
            elif rfc_upper[:6] in desc:
                score += 25

            # Amount match
            if abs(abs(mov.monto) - abs(monto)) < 0.01:
                score += 30
            elif abs(abs(mov.monto) - abs(monto)) / max(abs(monto), 1) < 0.05:
                score += 15

            # Date match
            mov_dt = self._parse_date(mov.fecha)
            if mov_dt and fecha_dt:
                diff = abs((mov_dt - fecha_dt).days)
                if diff == 0:
                    score += 20
                elif diff <= date_tolerance_days:
                    score += 10

            if score > best_score:
                best_score = score
                best = mov

        return best if best_score >= 50 else None

    @staticmethod
    def _parse_date(s: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None
