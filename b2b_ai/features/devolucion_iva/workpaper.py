# -*- coding: utf-8 -*-
"""
workpaper.py — Working paper (papel de trabajo) generator.

Generates the conciliation working paper for IVA refund requests.
The working paper is the key document auditors review — it traces
the full chain: CFDI invoices → DIOT → Declarations → Balance.
"""
from __future__ import annotations

import csv
import io
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
from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    PapelTrabajoConciliacion,
)


# ---------------------------------------------------------------------------
# REQ-IVA-009 — Sección 7, "no discrepancia fiscal — depósitos bancarios"
# ---------------------------------------------------------------------------
#
# ADR-4 / REQ-IVA-011: el Art. 59 fracción III CFF NUNCA se aplica por
# cuenta propia. Un depósito clasificado por el motor de reglas
# (financiamiento/aportación de socio/garantía, u "otro no gravable") es
# siempre una SUGERENCIA automática de primera pasada, nunca una
# determinación fiscal firme — reclasificar un depósito a ingreso gravado
# exige evidencia documental real (contrato de mutuo, acta de asamblea,
# contrato de garantía) y revisión/aprobación humana explícita. Esta
# advertencia se repite literalmente en cada fila y en el nivel de sección
# para que nunca se pierda al exportar/imprimir el papel de trabajo.
ADVERTENCIA_ART_59_FRACC_III = (
    "Ninguna clasificación de depósito de esta sección es una determinación "
    "fiscal firme. La presunción de ingreso gravado del Art. 59 fracción III "
    "CFF exige facultades de comprobación previas (PRODECON 1/2026) y "
    "evidencia documental real (contrato de mutuo, acta de asamblea, "
    "contrato de garantía); toda clasificación automática de primera pasada "
    "es una sugerencia sujeta a revisión y aprobación humana explícita "
    "(ADR-4)."
)


# ---------------------------------------------------------------------------
# REQ-IVA-014 — FED (Formato Electrónico de Devoluciones), anexo 7/7-A
# ---------------------------------------------------------------------------
#
# Los 9 campos mínimos por línea de proveedor exigidos por el anexo 7/7-A.
# El orden es también el orden de columnas del CSV exportado.
CAMPOS_FED_ANEXO7 = (
    "rfc",
    "nombre_razon_social",
    "folio_fiscal",
    "folio_factura",
    "fecha_factura",
    "fecha_pago",
    "forma_pago",
    "banco_pago",
    "iva_trasladado_acreditable",
)


class WorkpaperGenerator:
    """Generate structured working paper (papel de trabajo) for IVA refund.

    The working paper has 7 sections:
      1. Summary of period
      2. DIOT by supplier
      3. Conciliation CFDI vs DIOT
      4. Conciliation DIOT vs Declarations
      5. Balance calculation
      6. Supporting documents list
      7. No discrepancia fiscal — depósitos bancarios (REQ-IVA-009)
    """

    def generate(
        self,
        periodo: str,
        facturas: List[FacturaCFDI],
        diot_entries: List[DIOTEntry],
        declaraciones: List[DeclaracionMensual],
        tenant_id: Optional[str] = None,
        documentos_soporte: Optional[List[str]] = None,
        papel_conciliacion_depositos: Optional[PapelTrabajoConciliacion] = None,
    ) -> Dict[str, Any]:
        """Generate a complete working paper.

        Parameters
        ----------
        papel_conciliacion_depositos : Optional[PapelTrabajoConciliacion]
            REQ-IVA-009 — el `PapelTrabajoConciliacion` producido por
            `reconciliacion_ingresos_egresos` (clasificaciones de depósito
            bancario + `articulo_cff`) para el mismo `periodo`/tenant. Es
            opcional: sin él, la sección 7 se genera igual pero marcada
            como "sin datos" — el papel de trabajo siempre tiene 7
            secciones, nunca 6, independientemente de si hay o no
            conciliación de depósitos disponible para este período.

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

        # Section 7 (REQ-IVA-009): no discrepancia fiscal — depósitos bancarios
        section7 = self._section_no_discrepancia_fiscal_depositos(
            papel_conciliacion_depositos
        )

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
                "7_no_discrepancia_fiscal_depositos": section7,
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

    def _section_no_discrepancia_fiscal_depositos(
        self,
        papel_conciliacion_depositos: Optional[PapelTrabajoConciliacion],
    ) -> Dict[str, Any]:
        """Section 7 (REQ-IVA-009): "no discrepancia fiscal — depósitos bancarios".

        Incorpora el `PapelTrabajoConciliacion` de
        `reconciliacion_ingresos_egresos`: las clasificaciones de depósito
        bancario (con su `articulo_cff`, poblado por REQ-IVA-001 para
        financiamiento/aportación de socio/garantía) y las discrepancias
        bancarias detectadas por esa conciliación, para que el expediente
        final de devolución de IVA quede conectado con el análisis de
        depósitos bancarios del periodo.

        REGLA DURA (ADR-4, Art. 59 fracc. III CFF): esta sección nunca
        presenta una clasificación de depósito como determinación fiscal
        firme — cada fila y la sección completa llevan la advertencia
        explícita de que se trata de una sugerencia automática de primera
        pasada sujeta a revisión humana (ver `ADVERTENCIA_ART_59_FRACC_III`).
        """
        if papel_conciliacion_depositos is None:
            return {
                "disponible": False,
                "mensaje": (
                    "No se proporcionó papel de conciliación de "
                    "ingresos/egresos (depósitos bancarios) para este "
                    "período; sección informativa sin datos."
                ),
                "total_depositos_clasificados": 0,
                "clasificaciones_depositos": [],
                "resumen_por_clasificacion": {},
                "total_discrepancias_bancarias": 0,
                "requiere_revision_humana": False,
                "conclusiones_conciliacion_depositos": [],
                "advertencia_fiscal": ADVERTENCIA_ART_59_FRACC_III,
            }

        clasificaciones = papel_conciliacion_depositos.clasificaciones

        resumen_por_clasificacion: Dict[str, int] = {}
        for c in clasificaciones:
            resumen_por_clasificacion[c.clasificacion.value] = (
                resumen_por_clasificacion.get(c.clasificacion.value, 0) + 1
            )

        detalle_clasificaciones = [
            {
                "deposito_id": c.deposito_id,
                "clasificacion": c.clasificacion.value,
                "articulo_cff": c.articulo_cff,
                "confianza": c.confianza,
                "razon": c.razon,
                "requires_human_review": c.requires_human_review,
                "es_sugerencia_no_determinacion_firme": True,
            }
            for c in clasificaciones
        ]

        requiere_revision_humana = bool(
            papel_conciliacion_depositos.requires_human_review
        ) or any(c.requires_human_review for c in clasificaciones)

        return {
            "disponible": True,
            "periodo": papel_conciliacion_depositos.periodo,
            "total_depositos_clasificados": len(clasificaciones),
            "clasificaciones_depositos": detalle_clasificaciones,
            "resumen_por_clasificacion": resumen_por_clasificacion,
            "total_discrepancias_bancarias": len(
                papel_conciliacion_depositos.discrepancias
            ),
            "requiere_revision_humana": requiere_revision_humana,
            "conclusiones_conciliacion_depositos": list(
                papel_conciliacion_depositos.conclusiones
            ),
            "advertencia_fiscal": ADVERTENCIA_ART_59_FRACC_III,
        }

    # -----------------------------------------------------------------
    # REQ-IVA-014 — FED (Formato Electrónico de Devoluciones), anexo 7/7-A
    # -----------------------------------------------------------------

    def _campos_faltantes_fed_anexo7(self, factura: FacturaCFDI) -> List[str]:
        """Campos obligatorios del anexo 7/7-A ausentes/vacíos en `factura`.

        `iva_trasladado_acreditable` nunca falta: es un cálculo derivado
        (`iva * proporcionalidad`) que siempre produce un número, aunque
        sea 0.0 — 0.0 no es un valor nulo.
        """
        faltantes: List[str] = []
        if not factura.rfc_emisor or not factura.rfc_emisor.strip():
            faltantes.append("rfc")
        if not factura.nombre_emisor or not factura.nombre_emisor.strip():
            faltantes.append("nombre_razon_social")
        if not factura.uuid or not factura.uuid.strip():
            faltantes.append("folio_fiscal")
        if not factura.folio_factura or not str(factura.folio_factura).strip():
            faltantes.append("folio_factura")
        if not factura.fecha or not factura.fecha.strip():
            faltantes.append("fecha_factura")
        if not factura.fecha_pago or not factura.fecha_pago.strip():
            faltantes.append("fecha_pago")
        if not factura.forma_pago or not factura.forma_pago.strip():
            faltantes.append("forma_pago")
        if not factura.banco_pago or not factura.banco_pago.strip():
            faltantes.append("banco_pago")
        return faltantes

    def exportar_fed_anexo7(self, facturas: List[FacturaCFDI]) -> List[Dict[str, Any]]:
        """REQ-IVA-014 — FED exportable, anexo 7/7-A, uno por proveedor/factura.

        Cada fila tiene exactamente los 9 campos mínimos del anexo 7/7-A
        definidos en `CAMPOS_FED_ANEXO7`, ninguno nulo/vacío:
          RFC, nombre/razón social, folio fiscal, folio de factura,
          fecha de factura, fecha de pago, forma de pago, banco de pago
          e IVA trasladado/acreditable.

        Si a alguna factura le falta un dato obligatorio para el anexo
        (p.ej. no se capturó `banco_pago` o `fecha_pago`), la exportación
        completa se rechaza con `ValueError` listando facturas y campos
        faltantes — nunca se emite una fila con un campo nulo o inventado.
        """
        filas: List[Dict[str, Any]] = []
        errores: List[str] = []

        for factura in facturas:
            faltantes = self._campos_faltantes_fed_anexo7(factura)
            if faltantes:
                errores.append(f"factura {factura.uuid}: faltan {faltantes}")
                continue
            filas.append({
                "rfc": factura.rfc_emisor,
                "nombre_razon_social": factura.nombre_emisor,
                "folio_fiscal": factura.uuid,
                "folio_factura": factura.folio_factura,
                "fecha_factura": factura.fecha,
                "fecha_pago": factura.fecha_pago,
                "forma_pago": factura.forma_pago,
                "banco_pago": factura.banco_pago,
                "iva_trasladado_acreditable": round(factura.iva * factura.proporcionalidad, 2),
            })

        if errores:
            raise ValueError(
                "No se puede generar el FED anexo 7/7-A: faltan campos "
                f"obligatorios en {len(errores)} factura(s): " + "; ".join(errores)
            )

        return filas

    def exportar_fed_anexo7_csv(self, facturas: List[FacturaCFDI]) -> str:
        """REQ-IVA-014 — Igual que `exportar_fed_anexo7` pero como texto CSV.

        Las columnas siguen exactamente el orden de `CAMPOS_FED_ANEXO7`.
        """
        filas = self.exportar_fed_anexo7(facturas)

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(CAMPOS_FED_ANEXO7))
        writer.writeheader()
        for fila in filas:
            writer.writerow(fila)
        return buffer.getvalue()
