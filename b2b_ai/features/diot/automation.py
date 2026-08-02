# -*- coding: utf-8 -*-
"""
automation.py — Motor de automatización de la DIOT.

Declaración Informativa de Operaciones con Terceros (CFF Art. 32-H).

Genera la DIOT automáticamente a partir de los CFDIs de un periodo:

  - Clasifica IVA acreditable vs deducible por proveedor (tercero).
  - Detecta proveedores que no emitieron CFDI en el periodo (posible omisión
    de la obligación de reportarlos).
  - Construye los registros DIOT agregados por RFC de tercero.
  - Genera el XML DIOT listo para enviar al SAT (esquema DIOT sat.gob.mx).

Expone:
  - DIOTAutomationError       : excepción de dominio.
  - ProviderClassification    : resumen IVA acreditable / deducible por proveedor.
  - MissingProvider           : proveedor registrado sin CFDI en el periodo.
  - DIOTAutomationResult      : resultado completo (declaración + clasificación
                                + proveedores omitidos + XML).
  - DIOTAutomation            : motor (auto_generate_diot / generate_diot_xml).
  - _reset_state()            : limpia el registro en memoria (para tests).
"""
from __future__ import annotations

import hashlib
import io
import uuid as _uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.diot.models import (
    DIOTDeclaration,
    DIOTPeriod,
    DIOTRecord,
    DIOTStatus,
    DIOTSummary,
    TipoIVA,
    TipoOperacion,
)
from b2b_ai.features.diot.validators import TIPOIVA_TO_TASA, coerce_record


class DIOTAutomationError(Exception):
    """Error de dominio en la automatización de la DIOT."""


@dataclass
class ProviderClassification:
    """Clasificación de IVA por proveedor (tercero)."""
    rfc_tercero: str
    nombre: str = ""
    tipo_operacion: str = "A"
    base_gravable: float = 0.0
    iva_acreditable: float = 0.0
    iva_deducible: float = 0.0
    num_cfdis: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rfc_tercero": self.rfc_tercero,
            "nombre": self.nombre,
            "tipo_operacion": self.tipo_operacion,
            "base_gravable": round(self.base_gravable, 2),
            "iva_acreditable": round(self.iva_acreditable, 2),
            "iva_deducible": round(self.iva_deducible, 2),
            "num_cfdis": self.num_cfdis,
        }


@dataclass
class MissingProvider:
    """Proveedor registrado para el tenant que no emitió CFDI en el periodo."""
    rfc_tercero: str
    nombre: str = ""
    motivo: str = "Sin CFDI recibido en el periodo."

    def to_dict(self) -> Dict[str, Any]:
        return {"rfc_tercero": self.rfc_tercero, "nombre": self.nombre, "motivo": self.motivo}


@dataclass
class DIOTAutomationResult:
    """Resultado de la generación automática de la DIOT."""
    declaration: DIOTDeclaration
    classification: List[ProviderClassification] = field(default_factory=list)
    missing_providers: List[MissingProvider] = field(default_factory=list)
    xml_bytes: Optional[bytes] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "declaration": self.declaration.to_dict(),
            "classification": [c.to_dict() for c in self.classification],
            "missing_providers": [m.to_dict() for m in self.missing_providers],
            "xml_generated": self.xml_bytes is not None,
        }


# ---------------------------------------------------------------------------
# Registro en memoria de CFDIs ingeridos por tenant (para el MVP autónomo).
# En producción esto se reemplaza por el repositorio de CFDIs de la DB.
# ---------------------------------------------------------------------------
_registry: Dict[str, List[Dict[str, Any]]] = {}
_known_providers: Dict[str, List[Dict[str, Any]]] = {}


def _reset_state() -> None:
    """Limpia el registro en memoria (útil para tests)."""
    _registry.clear()
    _known_providers.clear()


def _tenant_key(tenant_id: str) -> str:
    return str(tenant_id).strip().upper()


def ingest_cfdi(tenant_id: str, cfdi: Dict[str, Any]) -> None:
    """Registra un CFDI (dict parseado por b2b_ai.cfdi.parser) para un tenant."""
    key = _tenant_key(tenant_id)
    _registry.setdefault(key, []).append(dict(cfdi))


def register_provider(tenant_id: str, rfc_tercero: str, nombre: str = "") -> None:
    """Registra un proveedor (tercero) esperado para el tenant, para detección
    de omisiones."""
    key = _tenant_key(tenant_id)
    _known_providers.setdefault(key, [])
    _known_providers[key].append({"rfc_tercero": rfc_tercero.strip().upper(), "nombre": nombre})


def _cfdi_period(cfdi: Dict[str, Any], month: int, year: int) -> bool:
    """Devuelve True si el CFDI pertenece al (month, year) solicitado."""
    fecha = cfdi.get("fecha_dt") or cfdi.get("fecha") or ""
    if not fecha:
        return False
    try:
        dt = datetime.fromisoformat(str(fecha).replace("Z", ""))
    except (ValueError, TypeError):
        try:
            # tolera "2024-03-15"
            dt = datetime.strptime(str(fecha)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return False
    return dt.year == year and dt.month == month


def _cfdi_iva_tr_fileds(cfdi: Dict[str, Any]) -> tuple:
    """Extrae (base_gravable, iva_acreditable) de un CFDI ingreso.

    Se prioriza los totales de impuestos trasladados / retenidos del CFDI
    y el IVA agregado del parser; falla a 0.
    """
    base = float(cfdi.get("subtotal") or 0.0)
    iva = float(cfdi.get("iva") or 0.0)
    ret_iva = float(cfdi.get("retenciones_iva") or 0.0)
    iva_acreditable = max(0.0, iva - ret_iva)
    return base, iva_acreditable


class DIOTAutomation:
    """Motor de automatización de la DIOT."""

    def __init__(self, tenant_id: str):
        self.tenant_id = str(tenant_id).strip().upper()

    # -- helpers ----------------------------------------------------------
    def _period(self, month: int, year: int) -> DIOTPeriod:
        quarter = ((month - 1) // 3) + 1
        return DIOTPeriod(year=year, quarter=quarter, month=month)

    def _cfdis_for_period(self, month: int, year: int) -> List[Dict[str, Any]]:
        cfdis = _registry.get(self.tenant_id, [])
        return [c for c in cfdis if _cfdi_period(c, month, year)]

    # -- API pública ------------------------------------------------------
    def auto_generate_diot(
        self,
        month: int,
        year: int,
        tenant_id: Optional[str] = None,
    ) -> DIOTAutomationResult:
        """Genera la DIOT del periodo automáticamente desde los CFDIs.

        - Agrega operaciones por RFC de tercero (emisor del CFDI).
        - Clasifica IVA acreditable vs deducible por proveedor.
        - Detecta proveedores registrados sin CFDI en el periodo.
        - Devuelve declaración + clasificación + omitidos + XML listo para SAT.
        """
        if tenant_id is not None:
            self.tenant_id = str(tenant_id).strip().upper()
        if month < 1 or month > 12:
            raise DIOTAutomationError(f"Mes inválido: {month} (1-12).")
        if year < 2014 or year > 2099:
            raise DIOTAutomationError(f"Año inválido: {year}.")

        period = self._period(month, year)
        cfdis = self._cfdis_for_period(month, year)

        # Agregar por tercero (emisor del CFDI)
        by_provider: Dict[str, Dict[str, Any]] = {}
        for cfdi in cfdis:
            rfc = (cfdi.get("emisor_rfc") or "").strip().upper()
            if not rfc:
                continue
            base, iva_acred = _cfdi_iva_tr_fileds(cfdi)
            prov = by_provider.setdefault(rfc, {
                "rfc_tercero": rfc,
                "nombre": cfdi.get("emisor_nombre") or "",
                "regimen": cfdi.get("emisor", {}).get("regimen_fiscal") if isinstance(
                    cfdi.get("emisor"), dict) else None,
                "base_gravable": 0.0,
                "iva_acreditable": 0.0,
                "iva_deducible": 0.0,
                "num_cfdis": 0,
            })
            prov["base_gravable"] += base
            prov["iva_acreditable"] += iva_acred
            prov["iva_deducible"] += iva_acred  # MVP: acreditable == deducible salvo reglas
            prov["num_cfdis"] += 1

        # Construir registros DIOT
        records: List[DIOTRecord] = []
        classification: List[ProviderClassification] = []
        for rfc in sorted(by_provider):
            p = by_provider[rfc]
            tasa = TipoIVA.IVA_16
            records.append(DIOTRecord(
                rfc_tercero=rfc,
                nombre=p["nombre"],
                regimen_fiscal=p["regimen"],
                tipo_operacion=TipoOperacion.A,
                base_gravable=round(p["base_gravable"], 2),
                iva_trasladado=round(p["iva_acreditable"], 2),
                iva_acreditable=round(p["iva_acreditable"], 2),
                tasa_iva=tasa,
            ))
            classification.append(ProviderClassification(
                rfc_tercero=rfc,
                nombre=p["nombre"],
                tipo_operacion="A",
                base_gravable=round(p["base_gravable"], 2),
                iva_acreditable=round(p["iva_acreditable"], 2),
                iva_deducible=round(p["iva_deducible"], 2),
                num_cfdis=p["num_cfdis"],
            ))

        # Detectar proveedores omitidos
        missing: List[MissingProvider] = []
        for prov in _known_providers.get(self.tenant_id, []):
            rfc = prov.get("rfc_tercero", "")
            if rfc and rfc not in by_provider:
                missing.append(MissingProvider(
                    rfc_tercero=rfc, nombre=prov.get("nombre") or ""))

        # Construir declaración
        declaration = DIOTDeclaration(
            id=str(_uuid.uuid4()),
            client_rfc=self.tenant_id,
            period=period,
            records=records,
            status=DIOTStatus.GENERADA,
            created_at=datetime.utcnow(),
        )
        declaration.recompute_summary()

        xml_bytes = self.generate_diot_xml(declaration.to_dict())
        return DIOTAutomationResult(
            declaration=declaration,
            classification=classification,
            missing_providers=missing,
            xml_bytes=xml_bytes,
        )

    # -- XML --------------------------------------------------------------
    def generate_diot_xml(self, diot_data: Dict[str, Any]) -> bytes:
        """Genera el XML DIOT conforme al esquema sat.gob.mx listo para submit.

        Recibe el dict de la declaración (o el DIOTAutomationResult) y produce
        el XML con el encabezado del periodo y los registros por tercero.
        """
        # Normalizar entrada: acepta declaration.to_dict() o result
        if isinstance(diot_data, DIOTAutomationResult):
            decl = diot_data.declaration.to_dict()
        elif "declaration" in diot_data and isinstance(diot_data.get("declaration"), dict):
            decl = diot_data["declaration"]
        else:
            decl = diot_data

        records = decl.get("records") or []
        summary = decl.get("summary") or {}

        root = ET.Element(
            "DIOT",
            {
                "xmlns": "http://www.sat.gob.mx/diot",
                "version": "1.0",
                "periodo_anio": str(decl.get("year") or ""),
                "periodo_trimestre": str(decl.get("quarter") or ""),
                "rfc_contribuyente": decl.get("client_rfc") or "",
            },
        )
        encabezado = ET.SubElement(root, "Encabezado")
        ET.SubElement(encabezado, "TotalOperaciones").text = str(summary.get("total_operaciones", 0))
        ET.SubElement(encabezado, "TotalBaseGravable").text = (
            f"{float(summary.get('total_base_gravable', 0.0)):.2f}")
        ET.SubElement(encabezado, "TotalIVAAcreditable").text = (
            f"{float(summary.get('total_iva_acreditable', 0.0)):.2f}")

        detalle = ET.SubElement(root, "Detalle")
        for rec in records:
            tasa = TIPOIVA_TO_TASA.get(rec.get("tasa_iva"), 0.16)
            prov = ET.SubElement(detalle, "Tercero", {"rfc": rec.get("rfc_tercero", "")})
            ET.SubElement(prov, "Nombre").text = rec.get("nombre") or ""
            ET.SubElement(prov, "TipoOperacion").text = rec.get("tipo_operacion") or "A"
            ET.SubElement(prov, "BaseGravable").text = f"{float(rec.get('base_gravable', 0.0)):.2f}"
            ET.SubElement(prov, "IVATrasladado").text = f"{float(rec.get('iva_trasladado', 0.0)):.2f}"
            ET.SubElement(prov, "IVAAcreditable").text = f"{float(rec.get('iva_acreditable', 0.0)):.2f}"
            ET.SubElement(prov, "TasaIVA").text = f"{tasa:.2f}"

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        buf = io.BytesIO()
        tree.write(buf, encoding="UTF-8", xml_declaration=True)
        return buf.getvalue()

    def diot_xml_sha256(self, xml_bytes: bytes) -> str:
        """Hash SHA-256 del XML generado (para trazabilidad/integridad)."""
        return hashlib.sha256(xml_bytes).hexdigest()
