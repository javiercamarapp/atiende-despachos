# -*- coding: utf-8 -*-
"""
csv_erp.py — Conector ERP por CSV (fallback universal).

Los despachos mexicanos usan mucho Excel/CSV como "ERP" (de `07-erps-
integracion.md`, prioridad 6 de alto uso real). Este conector registra cada
póliza como una fila en un CSV, sirviendo de fallback cuando no hay API real.
"""
from __future__ import annotations

import csv
import os
import uuid
from datetime import datetime

from b2b_ai.erp.base import ERPInterface


class CSVErp(ERPInterface):
    """Registra pólizas en un CSV. Fallback universal."""

    backend = "CSV"

    def __init__(self, path=None):
        if path is None:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            path = os.path.join(base, "erp_export.csv")
        self.path = path
        self._rows = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, newline="", encoding="utf-8") as f:
                self._rows = list(csv.DictReader(f))

    def _write(self):
        fieldnames = ["poliza", "folio_fiscal", "emisor", "total", "categoria",
                      "cuenta_cargo", "cuenta_abono", "fecha_registro"]
        exists = os.path.exists(self.path)
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not exists:
                writer.writeheader()
            writer.writerow(self._rows[-1])

    def register_invoice(self, invoice):
        folio = invoice.get("folio_fiscal") or invoice.get("archivo")
        if not folio:
            return {"ok": False, "poliza": None, "status": "error",
                    "message": "Sin folio fiscal para registrar."}
        poliza_id = "CSV-" + uuid.uuid4().hex[:8].upper()
        categoria = invoice.get("categoria", "desconocido")
        from b2b_ai.erp.contpaqi import _cuentas_para_categoria
        cargo, abono = _cuentas_para_categoria(categoria)
        row = {
            "poliza": poliza_id, "folio_fiscal": folio,
            "emisor": invoice.get("emisor_rfc", ""),
            "total": invoice.get("total", ""), "categoria": categoria,
            "cuenta_cargo": cargo, "cuenta_abono": abono,
            "fecha_registro": datetime.now().isoformat(timespec="seconds"),
        }
        self._rows.append(row)
        self._write()
        return {"ok": True, "poliza": poliza_id, "cuenta_cargo": cargo,
                "cuenta_abono": abono, "status": "registrada",
                "message": f"Póliza {poliza_id} exportada a CSV ({self.path})."}

    def get_invoice(self, folio_fiscal):
        for r in self._rows:
            if r.get("folio_fiscal") == folio_fiscal:
                return dict(r)
        return None

    def health(self):
        return {"ok": True, "backend": self.backend,
                "detail": f"CSV operativo ({self.path})."}
