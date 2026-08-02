# -*- coding: utf-8 -*-
"""
diot_expansion.py — Expansión DIOT: generación batch desde CFDI y clasificación.

Convierte facturas CFDI 4.0 en el formato DIOT (Declaración Informativa de
Operaciones con Terceros, CFF Art. 85-A) para declaración mensual.

Funcionalidad:
  • generate_diot_from_cfdi_batch()  — Procesa N facturas → reporte DIOT
  • Clasificación automática: proveedor nacional vs extranjero
  • Cross-reference IVA acreditable vs no acreditable
  • Generar layout DIOT XML para upload al SAT
  • Validar completitud antes de generación

Dependencias:
  - b2b_ai.cfdi.parser: parse_cfdi() para leer facturas
  - b2b_ai.services.diot_validator: validación de layout generado
  - b2b_ai.services.diot_service: tipos DIOTOperation, DIOTReport

Referencia:
  - CFF art. 85-A (Declaración Informativa de Operaciones con Terceros)
  - Regla 3.10.7 RMF vigente (DIOT)
  - Anexo 20 CFDI 4.0
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from b2b_ai.cfdi.parser import parse_cfdi, CFDIError
from b2b_ai.cfdi.catalogs import (
    DIOT_TIPO_OPERACION,
    REGIMENES_FISCALES,
)
from b2b_ai.common.rfc import is_valid_rfc, normalize_rfc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# RFCs genéricos para proveedores extranjeros (CFF art. 29, Anexo 20)
RFC_EXTRANJEROS: Set[str] = {"XEXX010101000", "XAXX010101000", "XAXX010101001"}

# Tasas de IVA estándar en México
TASA_IVA_16 = Decimal("0.16")
TASA_IVA_8 = Decimal("0.08")
TASA_IVA_0 = Decimal("0.00")
TASAS_IVA_VALIDAS = {TASA_IVA_16, TASA_IVA_8, TASA_IVA_0}

# Porcentaje para determinar si un IVA es "acreditable"
# Regla general: IVA trasladado expresamente en CFDI es acreditable si es
# gasto estrictamente indispensable (LIVA art. 5).
# El IVA no acreditable ocurre en: gastos no deducibles (LISR art. 28),
# actividad exenta, o tasa 0%.
UMBRAL_ACREDITABLE = Decimal("0.01")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DIOTInvoiceCrossReference:
    """Referencia cruzada de una factura para declaración DIOT."""
    # Identificación
    folio_fiscal: str  # UUID
    emisor_rfc: str
    emisor_nombre: str
    receptor_rfc: str
    fecha: str
    total: float
    tipo_comprobante: str  # I, E, T, P, N

    # IVA desglosado
    iva_trasladado: float
    iva_acreditable: float
    iva_acreditable_calculado: float  # IVA que SÍ es acreditable (LIVA art. 5)
    iva_no_acreditable: float  # IVA que NO es acreditable (gastos no deducibles, etc.)

    # Clasificación
    es_extranjero: bool = False  # Proveedor extranjero (RFC genérico)
    tipo_operacion_diot: str = "85"  # Default "Otros"
    es_gasto_no_deducible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "folio_fiscal": self.folio_fiscal,
            "emisor_rfc": self.emisor_rfc,
            "emisor_nombre": self.emisor_nombre,
            "receptor_rfc": self.receptor_rfc,
            "fecha": self.fecha,
            "total": self.total,
            "tipo_comprobante": self.tipo_comprobante,
            "iva_trasladado": self.iva_trasladado,
            "iva_acreditable": self.iva_acreditable,
            "iva_acreditable_calculado": self.iva_acreditable_calculado,
            "iva_no_acreditable": self.iva_no_acreditable,
            "es_extranjero": self.es_extranjero,
            "tipo_operacion_diot": self.tipo_operacion_diot,
            "es_gasto_no_deducible": self.es_gasto_no_deducible,
        }


@dataclass
class DIOTBatchSummary:
    """Resumen de todo un batch de facturas para DIOT."""
    total_facturas: int = 0
    total_iva_trasladado: float = 0.0
    total_iva_acreditable: float = 0.0
    total_iva_no_acreditable: float = 0.0
    total_monto: float = 0.0
    proveedores_unicos: int = 0
    proveedores_extranjeros: int = 0
    facturas_con_iva_no_acreditable: int = 0
    facturas_extranjeras: int = 0
    por_rfc: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_facturas": self.total_facturas,
            "total_iva_trasladado": round(self.total_iva_trasladado, 2),
            "total_iva_acreditable": round(self.total_iva_acreditable, 2),
            "total_iva_no_acreditable": round(self.total_iva_no_acreditable, 2),
            "total_monto": round(self.total_monto, 2),
            "proveedores_unicos": self.proveedores_unicos,
            "proveedores_extranjeros": self.proveedores_extranjeros,
            "facturas_con_iva_no_acreditable": self.facturas_con_iva_no_acreditable,
            "facturas_extranjeras": self.facturas_extranjeras,
            "por_rfc": self.por_rfc,
        }


@dataclass
class DIOTBatchResult:
    """Resultado completo del procesamiento batch."""
    invoices: List[DIOTInvoiceCrossReference] = field(default_factory=list)
    summary: Optional[DIOTBatchSummary] = None
    errores: List[str] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoices": [inv.to_dict() for inv in self.invoices],
            "summary": self.summary.to_dict() if self.summary else None,
            "errores": self.errores,
            "advertencias": self.advertencias,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Convierte a Decimal de forma segura."""
    if value is None:
        return default
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convierte a float de forma segura."""
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


def _round2_float(v: float) -> float:
    """Redondea un float a 2 decimales."""
    return round(v, 2)


def _es_proveedor_extranjero(rfc: str) -> bool:
    """Determina si un RFC corresponde a un proveedor extranjero.

    Los RFCs genéricos XAXX010101000 (persona moral extranjera sin RFC
    específico) y XEXX010101000 (persona física) se usan cuando el
    proveedor no tiene RFC mexicano (CFF art. 29, Anexo 20).
    """
    return normalize_rfc(rfc) in RFC_EXTRANJEROS


def _clasificar_tipo_operacion_diot(
    cfdi_data: Dict[str, Any],
) -> str:
    """Clasifica un CFDI en el tipo de operación DIOT correcto.

    Catálogo DIOT (Regla 3.10.7 RMF):
      03 — Prestación de servicios profesionales
      06 — Arrendamiento de inmuebles
      85 — Otros (default)

    La clasificación se basa en:
    - ClaveProdServ del concepto
    - Tipo de comprobante
    - Régimen fiscal del emisor
    """
    # Si es nómina, no va a DIOT (no aplica)
    if cfdi_data.get("tipo") == "N":
        return "85"

    conceptos = cfdi_data.get("conceptos", [])
    if not conceptos:
        return "85"

    claves = [c.get("clave_prod_serv", "") for c in conceptos if c.get("clave_prod_serv")]
    if not claves:
        return "85"

    # Arrendamiento de inmuebles (servicios de arrendamiento)
    # ClaveProdServ 78111200 y variantes = alquiler de inmuebles
    claves_arrendamiento = {"78111200", "78111201", "78111202", "78111203",
                            "78111204", "78111205", "78111206", "78111207",
                            "81111500", "81111501"}
    if any(c.startswith("781112") or c in claves_arrendamiento for c in claves):
        return "06"

    # Servicios profesionales
    # ClaveProdServ 80100000-80101900 = servicios contables, legales, consultoría
    claves_profesionales = {"80101500", "80101501", "80101502", "80101503",
                            "80101600", "80101601", "80111600",
                            "80111700", "80111800", "80111900",
                            "80112000", "80112100", "80112200",
                            "80112300", "80112400", "80112500",
                            "80121500", "80131500", "80141500",
                            "80141600", "80141700", "80141800",
                            "80151500", "80151600", "80151700",
                            "80151800", "80151900"}
    if any(c in claves_profesionales for c in claves):
        return "03"

    # Servicios profesionales por régimen fiscal
    regimen = cfdi_data.get("emisor", {}).get("regimen_fiscal", "")
    if regimen in ("605", "612", "621", "626"):
        # Sueldos, Personas Físicas con actividad profesional, RESICO, Incorporación
        if any(c.startswith("84") or c.startswith("80") for c in claves):
            return "03"

    return "85"


def _determinar_iva_acreditable(
    cfdi_data: Dict[str, Any],
) -> Tuple[float, float, bool]:
    """Determina el IVA acreditable vs no acreditable de un CFDI.

    Returns:
        (iva_acreditable, iva_no_acreditable, es_gasto_no_deducible)

    Reglas (LIVA art. 5, LISR art. 28):
    - IVA es acreditable cuando el gasto es estrictamente indispensable
    - NO es acreditable en: gastos de transporte, comidas no deducibles,
      cortesías, actividades exentas, etc.
    - Si el IVA total es 0, no hay nada que acreditar.
    """
    tipo = cfdi_data.get("tipo", "")

    # Verificar tipos de comprobante que NO permiten acreditamiento
    # IMPORTANTE: esta verificación va ANTES del IVA <= 0 para casos donde
    # el IVA es 0 pero el tipo sigue siendo no acreditable
    if tipo == "N":
        # Nómina: el IVA no es acreditable
        return (0.0, _safe_float(cfdi_data.get("iva", 0)), True)

    if tipo == "E":
        # Egresos: CFDI de egreso, no aplica IVA acreditable
        return (0.0, _safe_float(cfdi_data.get("iva", 0)), True)

    iva_total = _safe_dec(cfdi_data.get("iva", 0))
    impuestos = cfdi_data.get("traslados", [])

    if iva_total <= Decimal("0"):
        return (0.0, 0.0, False)

    # Determinar el IVA acreditable basado en las tasas
    iva_16 = Decimal("0")
    iva_8 = Decimal("0")
    iva_0 = Decimal("0")

    for t in impuestos:
        if t.get("impuesto") == "002":  # IVA
            tasa = _safe_dec(t.get("tasa_cuota"))
            importe = _safe_dec(t.get("importe"))
            if tasa == TASA_IVA_16:
                iva_16 += importe
            elif tasa == TASA_IVA_8:
                iva_8 += importe
            else:
                iva_0 += importe

    # Por defecto, el IVA trasladado es acreditable
    # Solo se marca como no acreditable si es un gasto no deducible
    iva_acreditable = _safe_dec(iva_total)
    es_no_deducible = False

    # Verificar conceptos para gastos no deducibles
    conceptos = cfdi_data.get("conceptos", [])
    claves_no_deducibles = {
        "90111500",  # Regalos corporativos / cortesías
        "90111800",  # Comidas y bebidas no deducibles
        "90111900",  # Transporte personal
        "90112000",  # Hospedaje personal
    }
    for c in conceptos:
        clave = c.get("clave_prod_serv", "")
        if clave in claves_no_deducibles:
            es_no_deducible = True
            break

    if es_no_deducible:
        return (0.0, _safe_float(iva_total), True)

    return (_safe_float(iva_acreditable), 0.0, False)


# ---------------------------------------------------------------------------
# DIOTExpander
# ---------------------------------------------------------------------------


class DIOTExpanderError(Exception):
    """Error base del expander DIOT."""


class DIOTExpander:
    """
    Expansor DIOT: genera declaraciones informativas desde facturas CFDI.

    Flujo de uso:
        1. process_cfdi_batch(invoices_or_paths) → DIOTBatchResult
        2. generate_diot_xml(result) → str (XML para upload SAT)
        3. validate_before_generation(result) → dict
    """

    def __init__(
        self,
        rfc_declarante: str = "",
        ejercicio: Optional[int] = None,
        mes: Optional[int] = None,
    ):
        """
        Args:
            rfc_declarante: RFC del contribuyente que declara.
            ejercicio: Año fiscal (default: año actual).
            mes: Mes de la declaración (1-12; default: mes anterior).
        """
        from datetime import date as _date
        today = _date.today()
        self.rfc_declarante = rfc_declarante
        self.ejercicio = ejercicio or today.year
        self.mes = mes or (today.month - 1 if today.month > 1 else 12)

    # ------------------------------------------------------------------
    # Procesamiento batch
    # ------------------------------------------------------------------

    def process_cfdi_batch(
        self,
        invoice_paths: Optional[List[str]] = None,
        cfdi_data_list: Optional[List[Dict[str, Any]]] = None,
        rfc_receptor: Optional[str] = None,
    ) -> DIOTBatchResult:
        """Procesa un lote de facturas CFDI para generar reporte DIOT.

        Args:
            invoice_paths: Lista de rutas a archivos XML de CFDI.
            cfdi_data_list: Lista de dicts ya parseados (alternativa).
            rfc_receptor: RFC del receptor para filtrar (opcional).

        Returns:
            DIOTBatchResult con invoices, summary, errores y advertencias.
        """
        result = DIOTBatchResult()

        # --- Parsear facturas ---
        cfdi_list: List[Dict[str, Any]] = []

        if invoice_paths:
            for path in invoice_paths:
                if not os.path.exists(path):
                    result.errores.append(f"Archivo no encontrado: {path}")
                    continue
                try:
                    cfdi_data = parse_cfdi(path)
                    cfdi_list.append(cfdi_data)
                except (CFDIError, OSError, ValueError) as e:
                    result.errores.append(f"Error al parsear {path}: {e}")

        if cfdi_data_list:
            cfdi_list.extend(cfdi_data_list)

        if not cfdi_list:
            result.errores.append("No se proporcionaron facturas para procesar")
            return result

        # --- Filtrar por receptor ---
        if rfc_receptor:
            rfc_norm = normalize_rfc(rfc_receptor)
            cfdi_list = [
                c for c in cfdi_list
                if normalize_rfc(c.get("receptor_rfc", "")) == rfc_norm
            ]
            if not cfdi_list:
                result.errores.append(
                    f"No se encontraron facturas para el RFC {rfc_receptor}"
                )
                return result

        # --- Procesar cada factura ---
        totales_rfc: Dict[str, float] = defaultdict(float)
        iva_trasladado_total = 0.0
        iva_acreditable_total = 0.0
        iva_no_acreditable_total = 0.0
        monto_total = 0.0
        proveedores: Set[str] = set()
        extranjeros: Set[str] = set()
        facturas_no_acreditable = 0
        facturas_extranjeras = 0

        for cfdi_data in cfdi_list:
            emisor_rfc = normalize_rfc(
                cfdi_data.get("emisor_rfc", "") or
                cfdi_data.get("emisor", {}).get("rfc", "")
            )
            emisor_nombre = (
                cfdi_data.get("emisor_nombre", "") or
                cfdi_data.get("emisor", {}).get("nombre", "")
            )
            receptor_rfc = normalize_rfc(
                cfdi_data.get("receptor_rfc", "") or
                cfdi_data.get("receptor", {}).get("rfc", "")
            )

            iva_trasladado = _safe_float(cfdi_data.get("iva", 0))
            iva_acreditable_val, iva_no_acreditable_val, es_no_deducible = (
                _determinar_iva_acreditable(cfdi_data)
            )
            es_extranjero = _es_proveedor_extranjero(emisor_rfc)
            tipo_op = _clasificar_tipo_operacion_diot(cfdi_data)

            monto = _safe_float(cfdi_data.get("total", 0))
            folio_fiscal = cfdi_data.get("folio_fiscal", "")
            fecha = cfdi_data.get("fecha", "")
            tipo = cfdi_data.get("tipo", "")

            # Acumular
            iva_trasladado_total += iva_trasladado
            iva_acreditable_total += iva_acreditable_val
            iva_no_acreditable_total += iva_no_acreditable_val
            monto_total += monto
            proveedores.add(emisor_rfc)
            totales_rfc[emisor_rfc] += monto

            if es_extranjero:
                extranjeros.add(emisor_rfc)
                facturas_extranjeras += 1

            if iva_no_acreditable_val > UMBRAL_ACREDITABLE:
                facturas_no_acreditable += 1

            # Advertencia si no es una operación típica de DIOT
            if tipo == "N":
                result.advertencias.append(
                    f"CFDI tipo nómina ({folio_fiscal}): no se incluye en DIOT"
                )

            inv_ref = DIOTInvoiceCrossReference(
                folio_fiscal=folio_fiscal,
                emisor_rfc=emisor_rfc,
                emisor_nombre=emisor_nombre,
                receptor_rfc=receptor_rfc,
                fecha=fecha,
                total=_round2_float(monto),
                tipo_comprobante=tipo,
                iva_trasladado=_round2_float(iva_trasladado),
                iva_acreditable=_round2_float(iva_acreditable_val),
                iva_acreditable_calculado=_round2_float(iva_acreditable_val),
                iva_no_acreditable=_round2_float(iva_no_acreditable_val),
                es_extranjero=es_extranjero,
                tipo_operacion_diot=tipo_op,
                es_gasto_no_deducible=es_no_deducible,
            )
            result.invoices.append(inv_ref)

        summary = DIOTBatchSummary(
            total_facturas=len(result.invoices),
            total_iva_trasladado=_round2_float(iva_trasladado_total),
            total_iva_acreditable=_round2_float(iva_acreditable_total),
            total_iva_no_acreditable=_round2_float(iva_no_acreditable_total),
            total_monto=_round2_float(monto_total),
            proveedores_unicos=len(proveedores),
            proveedores_extranjeros=len(extranjeros),
            facturas_con_iva_no_acreditable=facturas_no_acreditable,
            facturas_extranjeras=facturas_extranjeras,
            por_rfc={rfc: _round2_float(totales_rfc[rfc]) for rfc in sorted(totales_rfc)},
        )
        result.summary = summary

        return result

    # ------------------------------------------------------------------
    # Validación antes de generación
    # ------------------------------------------------------------------

    def validate_before_generation(
        self, result: DIOTBatchResult
    ) -> Dict[str, Any]:
        """Valida que el batch esté completo antes de generar XML DIOT.

        Verifica:
        - Que haya facturas procesadas
        - Que el RFC declarante esté configurado
        - Que no haya errores críticos de parseo
        - Que los totales sean consistentes

        Returns:
            {'valid': bool, 'errors': [...], 'warnings': [...]}
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not result.invoices:
            errors.append("No hay facturas procesadas para generar DIOT")

        if not self.rfc_declarante or not is_valid_rfc(self.rfc_declarante):
            errors.append(
                "RFC declarante no configurado o inválido. "
                "Configure DIOTExpander(rfc_declarante='...')"
            )

        if result.errores:
            errors.extend(
                f"Error de procesamiento: {e}" for e in result.errores
            )

        if result.summary:
            s = result.summary
            # Verificar que el IVA acreditable no exceda el trasladado
            if s.total_iva_acreditable > s.total_iva_trasladado + 1.0:
                warnings.append(
                    f"IVA acreditable ({s.total_iva_acreditable:.2f}) excede "
                    f"IVA trasladado ({s.total_iva_trasladado:.2f}). "
                    "Revise los cálculos de acreditamiento."
                )

            # Verificar que hay IVA acreditable total
            if s.total_iva_trasladado > 0 and s.total_iva_acreditable <= 0:
                warnings.append(
                    f"Hay IVA trasladado ({s.total_iva_trasladado:.2f}) pero "
                    "no hay IVA acreditable. Verifique que los gastos "
                    "sean deducibles."
                )

        if not (1 <= self.mes <= 12):
            errors.append(f"Mes inválido: {self.mes}. Debe ser 1-12.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": result.advertencias + warnings,
        }

    # ------------------------------------------------------------------
    # Generación de XML DIOT para upload SAT
    # ------------------------------------------------------------------

    def generate_diot_xml(self, result: DIOTBatchResult) -> str:
        """Genera el XML DIOT listo para declarar ante el SAT.

        El formato sigue la especificación del SAT para la declaración
        informativa de operaciones con terceros (DIOT), con estructura:

          <DIOT>
            <Declaracion>
              <RFC>...</RFC>
              <Ejercicio>...</Ejercicio>
              <Mes>...</Mes>
            </Declaracion>
            <Operacion>...</Operacion>
            ...
          </DIOT>

        Returns:
            String XML listo para upload al SAT.

        Raises:
            DIOTExpanderError: Si la validación previa falla.
        """
        validation = self.validate_before_generation(result)
        if not validation["valid"]:
            raise DIOTExpanderError(
                "No se puede generar DIOT:\n  - "
                + "\n  - ".join(validation["errors"])
            )

        # Construir XML
        root = ET.Element("DIOT")

        # Cabecera
        decl = ET.SubElement(root, "Declaracion")
        ET.SubElement(decl, "RFC").text = self.rfc_declarante
        ET.SubElement(decl, "Ejercicio").text = str(self.ejercicio)
        ET.SubElement(decl, "Mes").text = f"{self.mes:02d}"

        # Totales declarados
        s = result.summary
        if s:
            ET.SubElement(decl, "TotalMonto").text = f"{s.total_monto:.2f}"
            ET.SubElement(decl, "TotalIVATrasladado").text = f"{s.total_iva_trasladado:.2f}"
            ET.SubElement(decl, "TotalIVAAcreditable").text = f"{s.total_iva_acreditable:.2f}"
            ET.SubElement(decl, "TotalIVANoAcreditable").text = f"{s.total_iva_no_acreditable:.2f}"

        # Operaciones (una por factura)
        for inv in result.invoices:
            # Saltar nóminas y no incluir operaciones sin IVA si son nómina
            if inv.tipo_comprobante == "N":
                continue

            op = ET.SubElement(root, "Operacion")
            ET.SubElement(op, "RFC").text = inv.emisor_rfc
            ET.SubElement(op, "RazonSocial").text = inv.emisor_nombre
            ET.SubElement(op, "TipoOperacion").text = inv.tipo_operacion_diot
            ET.SubElement(op, "Monto").text = f"{inv.total:.2f}"
            ET.SubElement(op, "IVATrasladado").text = f"{inv.iva_trasladado:.2f}"
            ET.SubElement(op, "IVAAcreditable").text = f"{inv.iva_acreditable_calculado:.2f}"
            ET.SubElement(op, "IVANoAcreditable").text = f"{inv.iva_no_acreditable:.2f}"
            ET.SubElement(op, "FolioFiscal").text = inv.folio_fiscal
            ET.SubElement(op, "FechaFactura").text = inv.fecha
            ET.SubElement(op, "EsExtranjero").text = "Sí" if inv.es_extranjero else "No"

        # Serializar
        # Indent manual (ET.indent disponible en Python 3.9+)
        try:
            ET.indent(root, space="  ")
        except AttributeError:
            pass  # Python anterior a 3.9

        xml_bytes = ET.tostring(
            root, xml_declaration=True, encoding="UTF-8"
        )
        return xml_bytes.decode("UTF-8")

    # ------------------------------------------------------------------
    # Generar resumen contable desde batch
    # ------------------------------------------------------------------

    def generate_accounting_summary(self, result: DIOTBatchResult) -> Dict[str, Any]:
        """Genera un resumen contable del batch.

        Incluye:
        - IVA acreditable vs no acreditable (desglose)
        - Proporción de gastos deducibles
        - Clasificación por tipo de operación
        - Proveedores extranjeros vs nacionales
        """
        if not result.summary:
            return {"error": "No hay datos de resumen disponibles"}

        s = result.summary

        # Proporción de IVA acreditable
        pct_acreditable = 0.0
        if s.total_iva_trasladado > 0:
            pct_acreditable = round(
                s.total_iva_acreditable / s.total_iva_trasladado * 100, 1
            )

        # Desglose por tipo de operación DIOT
        tipo_op_counts: Dict[str, int] = defaultdict(int)
        tipo_op_montos: Dict[str, float] = defaultdict(float)
        for inv in result.invoices:
            tipo_op_counts[inv.tipo_operacion_diot] += 1
            tipo_op_montos[inv.tipo_operacion_diot] += inv.total

        # Desglose por RFC
        top_proveedores = sorted(
            s.por_rfc.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return {
            "total_facturas": s.total_facturas,
            "iva_trasladado_total": s.total_iva_trasladado,
            "iva_acreditable_total": s.total_iva_acreditable,
            "iva_no_acreditable_total": s.total_iva_no_acreditable,
            "proporcion_acreditable_pct": pct_acreditable,
            "proveedores_unicos": s.proveedores_unicos,
            "proveedores_extranjeros": s.proveedores_extranjeros,
            "facturas_extranjeras": s.facturas_extranjeras,
            "tipo_operacion_counts": dict(tipo_op_counts),
            "tipo_operacion_montos": {
                k: _round2_float(v) for k, v in tipo_op_montos.items()
            },
            "top_10_proveedores": [
                {"rfc": rfc, "monto": monto}
                for rfc, monto in top_proveedores
            ],
            "mes": self.mes,
            "ejercicio": self.ejercicio,
        }

    # ------------------------------------------------------------------
    # Conveniencia: generar reporte completo (batch + summary + XML)
    # ------------------------------------------------------------------

    def process_and_generate(
        self,
        invoice_paths: Optional[List[str]] = None,
        cfdi_data_list: Optional[List[Dict[str, Any]]] = None,
        rfc_receptor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pipeline completo: procesar batch + generar XML + accounting.

        Returns:
            Dict con:
            - batch_result: DIOTBatchResult.to_dict()
            - diot_xml: str (XML)
            - accounting_summary: dict
            - validation: dict
        """
        batch = self.process_cfdi_batch(
            invoice_paths=invoice_paths,
            cfdi_data_list=cfdi_data_list,
            rfc_receptor=rfc_receptor,
        )

        validation = self.validate_before_generation(batch)

        diot_xml = None
        if validation["valid"]:
            try:
                diot_xml = self.generate_diot_xml(batch)
            except DIOTExpanderError as e:
                validation["errors"].append(str(e))
                validation["valid"] = False

        accounting = self.generate_accounting_summary(batch)

        return {
            "batch_result": batch.to_dict(),
            "diot_xml": diot_xml,
            "accounting_summary": accounting,
            "validation": validation,
        }