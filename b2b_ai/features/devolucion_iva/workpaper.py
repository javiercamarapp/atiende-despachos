# -*- coding: utf-8 -*-
"""
workpaper.py — Working paper (papel de trabajo) generator.

Generates the conciliation working paper for IVA refund requests.
The working paper is the key document auditors review — it traces
the full chain: CFDI invoices → DIOT → Declarations → Balance.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from .models import (
    ClasificacionIVA,
    ConciliacionDIOTDeclaracion,
    ConciliacionFacturasDIOT,
    DeclaracionMensual,
    DIOTEntry,
    EstatusConciliacion,
    FacturaCFDI,
)
from .service import (
    clasificar_iva,
    conciliar_diot_declaracion,
    conciliar_facturas_diot,
    conciliar_declaracion_saldo,
    calcular_saldo_favor,
    calcular_monto_devolucion,
)


class WorkpaperGenerator:
    """Generate structured working paper (papel de trabajo) for IVA refund.

    The working paper has 6 sections:
      1. Summary of period
      2. DIOT by supplier
      3. Conciliation CFDI vs DIOT
      4. Conciliation DIOT vs Declarations
      5. Balance calculation
      6. Supporting documents list
    """

    def generate(
        self,
        periodo: str,
        facturas: List[FacturaCFDI],
        diot_entries: List[DIOTEntry],
        declaraciones: List[DeclaracionMensual],
        tenant_id: Optional[str] = None,
        documentos_soporte: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a complete working paper.

        Returns a structured dict ready for PDF/Excel export.
        """
        # Section 1: Summary
        section1 = self._section_summary(periodo, facturas, diot_entries, declaraciones)

        # Section 2: DIOT by supplier
        section2 = self._section_diot_by_supplier(diot_entries)

        # Section 3: CFDI vs DIOT conciliation
        section3 = self._section_conciliation_cfdi_diot(facturas, diot_entries)

        # Section 4: DIOT vs Declaration conciliation
        section4 = self._section_conciliation_diot_declaracion(diot_entries, declaraciones)

        # Section 5: Balance calculation
        section5 = self._section_balance(declaraciones, diot_entries)

        # Section 6: Supporting documents
        section6 = self._section_documentos(documentos_soporte or [])

        return {
            "periodo": periodo,
            "tenant_id": tenant_id,
            "secciones": {
                "1_resumen_periodo": section1,
                "2_diot_por_proveedor": section2,
                "3_conciliacion_cfdi_diot": section3,
                "4_conciliacion_diot_declaracion": section4,
                "5_calculo_saldo": section5,
                "6_documentos_soporte": section6,
            },
            "metadata": {
                "generado_por": "B2B AI Enterprise - Devolución de IVA Agent",
                "version": "1.0",
                "total_facturas": len(facturas),
                "total_diot_entries": len(diot_entries),
                "total_declaraciones": len(declaraciones),
            },
        }

    def _section_summary(
        self,
        periodo: str,
        facturas: List[FacturaCFDI],
        diot_entries: List[DIOTEntry],
        declaraciones: List[DeclaracionMensual],
    ) -> Dict[str, Any]:
        """Section 1: Summary of the period."""
        clasif = clasificar_iva(facturas)

        total_subtotal = sum(f.subtotal for f in facturas)
        total_iva = sum(f.iva for f in facturas)
        total_total = sum(f.total for f in facturas)
        total_diot_iva = sum(e.iva_trasladado for e in diot_entries)
        total_diot_acreditable = sum(e.iva_acreditable for e in diot_entries)
        total_saldo_favor = sum(d.saldo_favor for d in declaraciones)

        return {
            "periodo": periodo,
            "resumen_facturas": {
                "total_facturas": len(facturas),
                "acreditable_100_count": len(clasif.get("acreditable_100", [])),
                "acreditable_proporcional_count": len(clasif.get("acreditable_proporcional", [])),
                "no_acreditable_count": len(clasif.get("no_acreditable", [])),
                "total_subtotal": round(total_subtotal, 2),
                "total_iva_trasladado": round(total_iva, 2),
                "total_gravado": round(total_total, 2),
            },
            "resumen_diot": {
                "total_entradas": len(diot_entries),
                "total_iva_trasladado": round(total_diot_iva, 2),
                "total_iva_acreditable": round(total_diot_acreditable, 2),
            },
            "resumen_declaraciones": {
                "total_declaraciones": len(declaraciones),
                "total_iva_cobrado": round(sum(d.iva_cobrado for d in declaraciones), 2),
                "total_iva_pagado": round(sum(d.iva_pagado for d in declaraciones), 2),
                "total_saldo_favor": round(total_saldo_favor, 2),
                "total_saldo_contra": round(sum(d.saldo_contra for d in declaraciones), 2),
            },
        }

    def _section_diot_by_supplier(
        self,
        diot_entries: List[DIOTEntry],
    ) -> Dict[str, Any]:
        """Section 2: DIOT entries grouped by supplier."""
        suppliers = []
        for e in diot_entries:
            suppliers.append({
                "rfc": e.rfc_tercero,
                "nombre": e.nombre,
                "tipo_operacion": e.tipo_operacion,
                "monto_neto": e.monto_neto,
                "iva_trasladado": e.iva_trasladado,
                "iva_acreditable": e.iva_acreditable,
                "num_facturas": len(e.folios_fiscales),
                "folios_fiscales": e.folios_fiscales,
            })

        return {
            "proveedores": suppliers,
            "total_proveedores": len(suppliers),
            "total_monto_neto": round(sum(s["monto_neto"] for s in suppliers), 2),
            "total_iva_trasladado": round(sum(s["iva_trasladado"] for s in suppliers), 2),
            "total_iva_acreditable": round(sum(s["iva_acreditable"] for s in suppliers), 2),
        }

    def _section_conciliation_cfdi_diot(
        self,
        facturas: List[FacturaCFDI],
        diot_entries: List[DIOTEntry],
    ) -> Dict[str, Any]:
        """Section 3: Conciliation CFDI vs DIOT."""
        results = conciliar_facturas_diot(facturas, diot_entries)

        matches = [r for r in results if r.status == EstatusConciliacion.MATCH]
        mismatches = [r for r in results if r.status == EstatusConciliacion.MISMATCH]
        missing = [r for r in results if r.status == EstatusConciliacion.MISSING]

        return {
            "total_facturas": len(results),
            "matches": len(matches),
            "mismatches": len(mismatches),
            "missing": len(missing),
            "tasa_conciliacion": round(
                len(matches) / len(results) * 100, 1
            ) if results else 0.0,
            "detalle_mismatches": [
                {
                    "factura_uuid": r.factura_uuid,
                    "detalles": r.detalles,
                }
                for r in mismatches
            ],
            "detalle_missing": [
                {
                    "factura_uuid": r.factura_uuid,
                    "detalles": r.detalles,
                }
                for r in missing
            ],
        }

    def _section_conciliation_diot_declaracion(
        self,
        diot_entries: List[DIOTEntry],
        declaraciones: List[DeclaracionMensual],
    ) -> Dict[str, Any]:
        """Section 4: Conciliation DIOT vs Declarations."""
        results = conciliar_diot_declaracion(diot_entries, declaraciones)

        matches = [r for r in results if r.status == EstatusConciliacion.MATCH]
        mismatches = [r for r in results if r.status == EstatusConciliacion.MISMATCH]

        return {
            "total_declaraciones": len(results),
            "matches": len(matches),
            "mismatches": len(mismatches),
            "tasa_conciliacion": round(
                len(matches) / len(results) * 100, 1
            ) if results else 0.0,
            "detalle": [
                {
                    "diot_iva_total": r.diot_iva_total,
                    "declaracion_iva_acreditable": r.declaracion_iva_acreditable,
                    "diferencia": r.diferencia,
                    "status": r.status.value,
                }
                for r in results
            ],
        }

    def _section_balance(
        self,
        declaraciones: List[DeclaracionMensual],
        diot_entries: List[DIOTEntry],
    ) -> Dict[str, Any]:
        """Section 5: Balance calculation."""
        saldo_favor = calcular_saldo_favor(declaraciones)
        monto_calc = calcular_monto_devolucion(saldo_favor, declaraciones)

        # Cross-check
        verificacion = conciliar_declaracion_saldo(declaraciones, saldo_favor)

        return {
            "saldo_a_favor": round(saldo_favor, 2),
            "monto_devolucion": monto_calc,
            "verificacion": verificacion,
        }

    def _section_documentos(
        self,
        documentos: List[str],
    ) -> Dict[str, Any]:
        """Section 6: Supporting documents list."""
        return {
            "documentos": documentos,
            "total_documentos": len(documentos),
            "checklist": {
                "cfdi_compra": any("cfdi" in d.lower() or "factura" in d.lower() for d in documentos),
                "diot": any("diot" in d.lower() for d in documentos),
                "declaraciones": any("declaracion" in d.lower() for d in documentos),
                "estados_cuenta": any("banco" in d.lower() or "estado" in d.lower() for d in documentos),
                "balanza": any("balanza" in d.lower() for d in documentos),
            },
        }
