# -*- coding: utf-8 -*-
"""rules_engine.py — AccountingRulesEngine.

Maps CFDI categories → SAT account codes → journal entry templates.
Based on SAT 6-digit catalog. Rules are configurable per despacho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from b2b_ai.features.bookkeeping.models import (
    CFDIClassification,
    LineaPoliza,
    PolizaContable,
    PolizaType,
)


# ===================================================================
# SAT CATALOGO DE CUENTAS (6 dígitos) — subset for bookkeeping
# ===================================================================

CATALOGO_CUENTAS_SAT: Dict[str, str] = {
    # ACTIVO (1)
    "1020000": "Bancos",
    "1020100": "Bancos nacionales",
    "1020200": "Bancos extranjeros",
    "1050000": "Clientes",
    "1050100": "Clientes nacionales",
    "1050200": "Clientes extranjeros",
    "1080000": "Deudores diversos",
    "1100000": "Anticipos de clientes",
    "1130000": "Mercancías",
    "1500000": "Terrenos",
    "1520000": "Edificios",
    "1540000": "Maquinaria y equipo",
    "1560000": "Mobiliario y equipo de oficina",
    "1580000": "Equipo de transporte",
    "1600000": "Equipo de cómputo",
    "1900000": "Activo diferido",
    # PASIVO (2)
    "2010000": "Proveedores nacionales",
    "2020000": "Proveedores extranjeros",
    "2050000": "Cuentas por pagar a partes relacionadas",
    "2080000": "Acreedores diversos",
    "2600000": "Impuestos y derechos por pagar",
    "2600100": "ISR por pagar",
    "2600200": "IVA por pagar",
    "2600300": "IVA acreditable",
    "2600400": "IVA trasladado",
    "2600500": "ISR por retener (nómina)",
    "2670000": "Acreedores por pago de nómina",
    # CAPITAL (3)
    "3010000": "Capital social",
    "3040000": "Resultado de ejercicios anteriores",
    "3050000": "Resultado del ejercicio",
    # INGRESOS (4)
    "4010000": "Ventas",
    "4020000": "Devoluciones sobre ventas",
    "4080000": "Ingresos por servicios",
    "4100000": "Ingresos por arrendamiento",
    # COSTOS (5)
    "5010000": "Costo de lo vendido",
    "5020000": "Compras",
    # GASTOS (6)
    "6010100": "Sueldos y salarios",
    "6010200": "Sueldos y salarios (asimilados)",
    "6010300": "Sueldos y salarios (IMSS)",
    "6010400": "Sueldos y salarios (INFONAVIT)",
    "6010500": "Sueldos y salarios (SAR)",
    "6010600": "Sueldos y salarios (vacaciones)",
    "6010700": "Sueldos y salarios (prima vacacional)",
    "6010800": "Sueldos y salarios (aguinaldo)",
    "6010900": "Sueldos y salarios (PTU)",
    "6020100": "Servicios profesionales",
    "6020200": "Servicios administrativos",
    "6020300": "Servicios de mantenimiento",
    "6020400": "Rentas de inmuebles",
    "6020500": "Publicidad y propaganda",
    "6020600": "Gastos legales y jurídicos",
    "6020700": "Gastos de viaje y representación",
    "6030100": "Intereses bancarios",
    "6030200": "Comisiones bancarias",
    "6040100": "Pérdida por crédito incobrable",
    "6050100": "Pérdida cambiaria",
    "6070100": "Gastos por inflación",
    "6080100": "Seguros",
    "6090100": "Teléfono e internet",
    "6100100": "Gastos de transporte",
    "6110100": "Equipo de cómputo (gasto)",
}


# ===================================================================
# DEFAULT MAPPING: (tipo_cfdi, category) → {cargo, abono, iva_cargo, iva_abono}
# ===================================================================

@dataclass
class AccountMapping:
    """Maps a CFDI category to journal entry accounts."""
    cargo: str           # Debit account (SAT code)
    abono: str           # Credit account (SAT code)
    iva_cargo: Optional[str] = None   # IVA debit account
    iva_abono: Optional[str] = None   # IVA credit account
    poliza_type: PolizaType = PolizaType.EGRESO


DEFAULT_MAPPINGS: Dict[Tuple[str, str], AccountMapping] = {
    # Ingreso CFDI (compras/gastos) — cargo=gasto, abono=proveedor
    ("I", "servicios_profesionales"): AccountMapping(
        cargo="6020100", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "renta_oficina"): AccountMapping(
        cargo="6020400", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "materia_prima"): AccountMapping(
        cargo="5010000", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "papeleria"): AccountMapping(
        cargo="6020200", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "publicidad"): AccountMapping(
        cargo="6020500", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "honorarios_legales"): AccountMapping(
        cargo="6020600", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "comision_bancaria"): AccountMapping(
        cargo="6030200", abono="1020000", iva_cargo="2600300",
    ),
    ("I", "intereses_bancarios"): AccountMapping(
        cargo="6030100", abono="1020000", iva_cargo=None,
    ),
    ("I", "nomina"): AccountMapping(
        cargo="6010100", abono="2670000", iva_cargo=None,
    ),
    ("I", "arrendamiento"): AccountMapping(
        cargo="6020400", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "seguros"): AccountMapping(
        cargo="6080100", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "telefonia"): AccountMapping(
        cargo="6090100", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "transporte"): AccountMapping(
        cargo="6100100", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "equipo_computo"): AccountMapping(
        cargo="1600000", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "mantenimiento"): AccountMapping(
        cargo="6020300", abono="2010000", iva_cargo="2600300",
    ),
    ("I", "otros"): AccountMapping(
        cargo="6020200", abono="2010000", iva_cargo="2600300",
    ),
    # Egreso CFDI (ventas/ingresos) — cargo=cliente, abono=ingreso
    ("E", "venta_servicios"): AccountMapping(
        cargo="1050000", abono="4080000", iva_abono="2600400",
        poliza_type=PolizaType.INGRESO,
    ),
    ("E", "venta_mercancia"): AccountMapping(
        cargo="1050000", abono="4010000", iva_abono="2600400",
        poliza_type=PolizaType.INGRESO,
    ),
}


class AccountingRulesEngine:
    """Maps CFDI categories to SAT accounts and generates journal entries.

    Rules are configurable per despacho (tenant). Custom rules override
    the defaults.
    """

    def __init__(self, custom_mappings: Optional[Dict[Tuple[str, str], AccountMapping]] = None):
        self._default_mappings = dict(DEFAULT_MAPPINGS)
        self._custom_mappings: Dict[str, Dict[Tuple[str, str], AccountMapping]] = {}
        if custom_mappings:
            self._custom_mappings["__global__"] = custom_mappings

    def add_tenant_mapping(
        self, tenant_id: str, tipo_cfdi: str, category: str, mapping: AccountMapping
    ) -> None:
        """Add a custom mapping for a specific tenant/despacho."""
        if tenant_id not in self._custom_mappings:
            self._custom_mappings[tenant_id] = {}
        self._custom_mappings[tenant_id][(tipo_cfdi, category)] = mapping

    def get_mapping(
        self, tipo_cfdi: str, category: str, tenant_id: str = ""
    ) -> Optional[AccountMapping]:
        """Look up the account mapping for a CFDI type + category.

        Priority: tenant-specific > global custom > default.
        """
        key = (tipo_cfdi, category)
        # 1. Tenant-specific
        if tenant_id and tenant_id in self._custom_mappings:
            if key in self._custom_mappings[tenant_id]:
                return self._custom_mappings[tenant_id][key]
        # 2. Global custom
        if "__global__" in self._custom_mappings:
            if key in self._custom_mappings["__global__"]:
                return self._custom_mappings["__global__"][key]
        # 3. Default
        return self._default_mappings.get(key)

    def get_account_name(self, code: str) -> str:
        """Look up the SAT account name for a code."""
        return CATALOGO_CUENTAS_SAT.get(code, f"Cuenta {code}")

    def validate_account(self, code: str) -> bool:
        """Check if an account code exists in the SAT catalog."""
        return code in CATALOGO_CUENTAS_SAT

    def generate_poliza(
        self,
        classification: CFDIClassification,
        tenant_id: str = "",
    ) -> Optional[PolizaContable]:
        """Generate a journal entry from a classified CFDI.

        Returns None if no mapping found.
        """
        mapping = self.get_mapping(classification.tipo_cfdi, classification.categoria, tenant_id)
        if not mapping:
            return None

        lineas: List[LineaPoliza] = []
        subtotal = classification.subtotal
        iva = classification.iva

        # Main entry: cargo (gasto/activo) + abono (proveedor/cliente)
        lineas.append(LineaPoliza(
            cuenta=mapping.cargo,
            concepto=f"{self.get_account_name(mapping.cargo)} - {classification.descripcion}",
            debe=subtotal,
            haber=0.0,
            tipo="cargo",
        ))
        lineas.append(LineaPoliza(
            cuenta=mapping.abono,
            concepto=f"{self.get_account_name(mapping.abono)}",
            debe=0.0,
            haber=subtotal,
            tipo="abono",
        ))

        # IVA entry (if applicable)
        if iva > 0:
            if mapping.iva_cargo:
                lineas.append(LineaPoliza(
                    cuenta=mapping.iva_cargo,
                    concepto=f"IVA acreditable - {self.get_account_name(mapping.iva_cargo)}",
                    debe=iva,
                    haber=0.0,
                    tipo="cargo",
                ))
                lineas.append(LineaPoliza(
                    cuenta=mapping.abono,
                    concepto=f"IVA trasladado - {self.get_account_name(mapping.abono)}",
                    debe=0.0,
                    haber=iva,
                    tipo="abono",
                ))
            elif mapping.iva_abono:
                lineas.append(LineaPoliza(
                    cuenta=mapping.cargo,
                    concepto=f"IVA trasladado cobrado",
                    debe=iva,
                    haber=0.0,
                    tipo="cargo",
                ))
                lineas.append(LineaPoliza(
                    cuenta=mapping.iva_abono,
                    concepto=f"IVA trasladado - {self.get_account_name(mapping.iva_abono)}",
                    debe=0.0,
                    haber=iva,
                    tipo="abono",
                ))

        total_debe = sum(l.debe for l in lineas)
        total_haber = sum(l.haber for l in lineas)

        return PolizaContable(
            tipo=mapping.poliza_type,
            fecha="",
            concepto=f"CFDI {classification.cfdi_uuid} - {classification.descripcion}",
            referencia=classification.cfdi_uuid,
            lineas=lineas,
            total_debe=round(total_debe, 2),
            total_haber=round(total_haber, 2),
            cuadrada=abs(total_debe - total_haber) < 0.01,
            tenant_id=tenant_id,
        )

    def get_all_categories(self) -> List[str]:
        """Return all known categories from default + custom mappings."""
        cats = set()
        for (_, cat) in self._default_mappings:
            cats.add(cat)
        for tenant_mappings in self._custom_mappings.values():
            for (_, cat) in tenant_mappings:
                cats.add(cat)
        return sorted(cats)

    def get_catalogo(self) -> Dict[str, str]:
        """Return the SAT account catalog."""
        return dict(CATALOGO_CUENTAS_SAT)
