# -*- coding: utf-8 -*-
"""
contpaqi.py — Mock de CONTPAQi (contaDIGITAL API) para el MVP.

Implementa ERPInterface en memoria (registro de pólizas). Está diseñado para
que, cuando existan credenciales reales, se sustituya el método de registro
por una llamada REST a la API de CONTPAQi/contaDIGITAL sin tocar los servicios
que lo consumen (ver `base.ERPInterface`).

Modo real (futuro, requiere credenciales):
    POST https://api.contpaqi.com/.../polizas   con Bearer token
No se toca credenciales aquí; el mock solo sirve para testear el flujo.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from b2b_ai.erp.base import ERPInterface


class MockCONTPAQi(ERPInterface):
    """Implementación simulada de la API de CONTPAQi en memoria."""

    backend = "CONTPAQi (mock)"

    def __init__(self):
        self._polizas = {}

    def register_invoice(self, invoice):
        folio = invoice.get("folio_fiscal") or invoice.get("archivo")
        if not folio:
            return {"ok": False, "poliza": None, "status": "error",
                    "message": "Sin folio fiscal para registrar."}

        poliza_id = "POL-" + uuid.uuid4().hex[:10].upper()
        categoria = invoice.get("categoria", "desconocido")
        cuenta_cargo, cuenta_abono = _cuentas_para_categoria(categoria)

        self._polizas[folio] = {
            "poliza": poliza_id,
            "folio_fiscal": folio,
            "emisor": invoice.get("emisor_rfc", ""),
            "total": invoice.get("total"),
            "categoria": categoria,
            "cuenta_cargo": cuenta_cargo,
            "cuenta_abono": cuenta_abono,
            "fecha_registro": datetime.now().isoformat(timespec="seconds"),
            "status": "registrada",
        }
        return {
            "ok": True,
            "poliza": poliza_id,
            "cuenta_cargo": cuenta_cargo,
            "cuenta_abono": cuenta_abono,
            "status": "registrada",
            "message": f"Póliza {poliza_id} registrada en CONTPAQi (mock).",
        }

    def get_invoice(self, folio_fiscal):
        p = self._polizas.get(folio_fiscal)
        return dict(p) if p else None

    def health(self):
        return {"ok": True, "backend": self.backend,
                "detail": "Mock CONTPAQi operativo (sin conexión real)."}


# Mapa de cuentas contables sugeridas por categoría (catálogo simplificado).
_CUENTAS = {
    "gasto_operativo": ("6131 Gastos generales", "1130 Bancos"),
    "inversion": ("1115 Gastos de instalacion", "1130 Bancos"),
    "activo_fijo": ("1210 Mobiliario y equipo", "1130 Bancos"),
    "nomina": ("6110 Sueldos y salarios", "1130 Bancos"),
    "desconocido": ("6100 Gastos por clasificar", "1130 Bancos"),
}


def _cuentas_para_categoria(categoria):
    return _CUENTAS.get(categoria, _CUENTAS["desconocido"])
