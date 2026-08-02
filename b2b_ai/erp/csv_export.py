# -*- coding: utf-8 -*-
"""
csv_export.py — Exportación CSV con templates por ERP (CONTPAQi / Aspel / SAT).

Los despachos mexicanos usan mucho Excel/CSV como puente hacia el ERP y hacia
el SAT. Este módulo exporta pólizas/facturas normalizadas a formatos CSV con la
estructura de columnas que cada destino espera para su importación:

  - **CONTPAQi**: póliza de contabilidad electrónica (folio, fecha, cuenta,
    cargo/abono, referencia). Campos típicos de la importación de pólizas.
  - **Aspel**: movimiento de póliza estilo COI/SAE (folio, fecha, cuenta,
    concepto, cargo, abono).
  - **SAT**: estructura plana tipo catálogo/balanza para revisión ante el SAT
    (RFC, ejercicio, mes, cuenta, concepto, cargo, abono).
  - **Custom**: templates definidos por el usuario (dict con `fieldnames` y
    `row_mapper`).

Diseño:
  - `ERP_FORMATS` : registro de templates por ERP. Cada template define
    `fieldnames` (columnas) y una función `row(voucher) -> dict` que rellena la
    fila. Añadir un ERP nuevo = añadir una entrada al registro.
  - `CSVExport`   : exporta una lista de vouchers a un archivo CSV con el
    template elegido. Devuelve {path, rows, template}.
  - Backward-compatible con el `CSVExporter` de `connector.py` (mismo contrato
    de salud y de escritura), pero multi-formato.

Ninguna exportación sustituye la presentación oficial ante el SAT.
"""
from __future__ import annotations

import csv
import os
import uuid
from datetime import datetime

from b2b_ai.erp.connector import cuentas_para_categoria


def _dec(v):
    if v is None:
        return "0.00"
    try:
        return f"{float(str(v).replace(',', '').replace('$', '').strip()):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _fecha(v):
    return str(v or "")[:10]


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _audit():
    return "EXP-" + uuid.uuid4().hex[:10].upper()


# ---------------------------------------------------------------------------
# Templates por ERP
# ---------------------------------------------------------------------------
def _base_cargo_abono(voucher):
    """Resuelve cuenta/importe de una póliza normalizada."""
    categoria = voucher.get("categoria", "desconocido")
    cargo_cuenta, abono_cuenta = cuentas_para_categoria(categoria)
    total = voucher.get("total")
    return {
        "categoria": categoria,
        "cargo_cuenta": voucher.get("cuenta_cargo", cargo_cuenta),
        "abono_cuenta": voucher.get("cuenta_abono", abono_cuenta),
        "monto": total,
    }


def _template_contpaqi():
    fieldnames = ["poliza", "folio_fiscal", "fecha", "concepto",
                  "cuenta_cargo", "cuenta_abono", "cargo", "abono",
                  "referencia", "audit_ref"]
    def row(v):
        b = _base_cargo_abono(v)
        return {
            "poliza": v.get("poliza") or "",
            "folio_fiscal": v.get("folio_fiscal") or v.get("concepto") or "",
            "fecha": _fecha(v.get("fecha")),
            "concepto": v.get("concepto", ""),
            "cuenta_cargo": b["cargo_cuenta"],
            "cuenta_abono": b["abono_cuenta"],
            "cargo": _dec(b["monto"]),
            "abono": _dec(b["monto"]),
            "referencia": v.get("referencia", v.get("folio_fiscal", "")),
            "audit_ref": v.get("audit_ref") or _audit(),
        }
    return {"name": "CONTPAQi", "fieldnames": fieldnames, "row": row}


def _template_aspel():
    fieldnames = ["poliza", "folio_fiscal", "fecha", "cuenta",
                  "concepto", "cargo", "abono", "tipo_movimiento", "audit_ref"]
    def row(v):
        b = _base_cargo_abono(v)
        return {
            "poliza": v.get("poliza") or "",
            "folio_fiscal": v.get("folio_fiscal") or v.get("concepto") or "",
            "fecha": _fecha(v.get("fecha")),
            "cuenta": b["cargo_cuenta"],
            "concepto": v.get("concepto", ""),
            "cargo": _dec(b["monto"]),
            "abono": _dec(b["monto"]),
            "tipo_movimiento": "cargo" if b["monto"] else "abono",
            "audit_ref": v.get("audit_ref") or _audit(),
        }
    return {"name": "Aspel", "fieldnames": fieldnames, "row": row}


def _template_sat():
    fieldnames = ["rfc", "razon_social", "ejercicio", "mes", "fecha",
                  "folio_fiscal", "cuenta", "concepto", "cargo", "abono",
                  "total", "audit_ref"]
    def row(v):
        b = _base_cargo_abono(v)
        fecha = _fecha(v.get("fecha"))
        return {
            "rfc": v.get("emisor_rfc", v.get("rfc", "")),
            "razon_social": v.get("emisor", v.get("razon_social", "")),
            "ejercicio": fecha[:4] if fecha else "",
            "mes": fecha[5:7] if fecha else "",
            "fecha": fecha,
            "folio_fiscal": v.get("folio_fiscal") or "",
            "cuenta": b["cargo_cuenta"],
            "concepto": v.get("concepto", ""),
            "cargo": _dec(b["monto"]),
            "abono": _dec(b["monto"]),
            "total": _dec(v.get("total")),
            "audit_ref": v.get("audit_ref") or _audit(),
        }
    return {"name": "SAT", "fieldnames": fieldnames, "row": row}


def _template_custom(fieldnames, row_mapper):
    return {"name": "Custom", "fieldnames": list(fieldnames), "row": row_mapper}


ERP_FORMATS = {
    "contpaqi": _template_contpaqi(),
    "aspel": _template_aspel(),
    "sat": _template_sat(),
}

# Aliases tolerantes a acentos/mayúsculas.
ERP_FORMAT_ALIASES = {
    "conpaqi": "contpaqi", "conpaq": "contpaqi", "contabilidad": "contpaqi",
    "aspel-sae": "aspel", "sae": "aspel", "coi": "aspel",
    "sat": "sat", "balanza": "sat",
}


def resolve_format(name):
    """Resuelve un nombre de formato a su key canónica."""
    if not name:
        return None
    key = str(name).lower().strip()
    if key in ERP_FORMATS:
        return key
    return ERP_FORMAT_ALIASES.get(key)


class CSVExport:
    """Exporta vouchers a CSV con un template por ERP (o custom)."""

    def __init__(self, fmt="contpaqi", path=None):
        key = resolve_format(fmt)
        if key is None:
            raise ValueError(f"Formato ERP desconocido: {fmt!r}. "
                             f"Usar: {sorted(ERP_FORMATS)} o custom.")
        self.template = ERP_FORMATS[key]
        self.format_key = key
        if path is None:
            base = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            path = os.path.join(base, f"export_{key}.csv")
        self.path = path

    @property
    def fieldnames(self):
        return self.template["fieldnames"]

    def row_for(self, voucher):
        return self.template["row"](voucher)

    def export(self, vouchers, overwrite=False):
        """Escribe `vouchers` al CSV del template. Devuelve {path, rows, template}."""
        mode = "w" if overwrite or not os.path.exists(self.path) else "a"
        write_header = mode == "w"
        rows = [self.row_for(v) for v in vouchers]
        with open(self.path, mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.fieldnames)
            if write_header:
                writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return {"path": self.path, "rows": rows, "template": self.template["name"]}

    def export_one(self, voucher):
        return self.export([voucher])

    def health(self):
        return {
            "ok": True, "backend": f"CSV export ({self.template['name']})",
            "path": self.path, "fieldnames": self.fieldnames,
        }


def export_to(fmt, vouchers, path=None, overwrite=True):
    """Conveniencia: exporta `vouchers` al formato `fmt`."""
    return CSVExport(fmt, path=path).export(vouchers, overwrite=overwrite)


def register_custom_format(name, fieldnames, row_mapper):
    """Registra un template ERP custom (retorna el nombre de formato)."""
    key = str(name).lower().strip().replace(" ", "_")
    ERP_FORMATS[key] = _template_custom(fieldnames, row_mapper)
    return key
