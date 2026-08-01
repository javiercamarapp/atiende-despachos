# -*- coding: utf-8 -*-
"""
factories.py — Test Data Factories for enterprise testing.

Provides builder-pattern factories for:
  - CFDIs (Factura, Nómina, Honorarios, Pago)
  - Bank transactions
  - Tenants, Users, API Keys
  - Invoices with realistic Mexican fiscal data

Usage:
    from tests.factories import CFDIFactory, TenantFactory
    invoice = CFDIFactory.gasto_operativo(total=15000.00)
    tenant = TenantFactory.create(name="Mi Despacho", rfc="MDE220101AB1")
"""
from __future__ import annotations

import random
import secrets
import string
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Mexican fiscal data constants
# ---------------------------------------------------------------------------
_REGIMENES_FISCALES = [
    "601", "603", "605", "606", "607", "608", "610", "611", "612",
    "614", "615", "616", "620", "621", "622", "623", "624", "625",
]

_USOS_CFDI = [
    "G01", "G02", "G03", "I01", "I02", "I03", "I04", "I05", "I06",
    "I07", "I08", "D01", "D02", "D03", "D04", "D05", "D06", "D07",
    "D08", "D09", "D10", "P01", "S01", "CP01", "CN01",
]

_METODOS_PAGO = ["PUE", "PPD"]

_FORMAS_PAGO = [
    "01", "02", "03", "04", "05", "06", "08", "12", "13", "14",
    "15", "17", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "99",
]

_CLAVES_PROD_SERVICIO = [
    "43232300", "43232314", "80121500", "81112100", "82101500",
    "84111506", "78101800", "43231500", "80101600",
]

_CLAVES_UNIDAD = ["ACT", "E48", "H87", "HUR", "KGM", "LTR", "MTR", "NIU", "PZA", "SET"]


def _random_rfc(tipo: str = "fisica") -> str:
    """Generate a random valid-format RFC."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ&Ñ"
    digits = "0123456789"
    if tipo == "fisica":
        # 4 letters + 6 digits (date) + 3 alphanumeric (homoclave)
        prefix = "".join(random.choices(letters, k=4))
    else:
        # 3 letters + 6 digits (date) + 3 alphanumeric
        prefix = "".join(random.choices(letters, k=3))
    date_part = f"{random.randint(70, 99):02d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
    homo = "".join(random.choices(digits + letters, k=2)) + random.choice(digits)
    return prefix + date_part + homo


def _random_curp() -> str:
    """Generate a random valid-format CURP."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "0123456789"
    first4 = "".join(random.choices(letters, k=4))
    date6 = f"{random.randint(70, 99):02d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
    sex = random.choice(["H", "M"])
    entity = random.choice(["AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF",
                             "DG", "GT", "GR", "HG", "JC", "MC", "MN", "MS", "NT",
                             "NL", "OC", "PL", "QT", "QR", "SP", "SL", "SR", "TC",
                             "TS", "TL", "VZ", "YN", "ZS"])
    consonants = "".join(random.choices(letters, k=3))
    disambiguator = random.choice(digits + letters)
    check = random.choice(digits)
    return first4 + date6 + sex + entity + consonants + disambiguator + check


def _random_nss() -> str:
    """Generate a random valid-format NSS."""
    subdelegation = f"{random.randint(1, 99):02d}"
    affiliation = f"{random.randint(70, 99):02d}{random.randint(1, 2):01d}"
    consecutive = f"{random.randint(1, 99):02d}"
    body = subdelegation + affiliation + consecutive
    # Compute check digit (IMSS algorithm)
    total = 0
    for i, d in enumerate(body):
        factor = 1 if i % 2 == 0 else 2
        product = int(d) * factor
        total += (product // 10) + (product % 10)
    check = (10 - (total % 10)) % 10
    return body + str(check)


def _random_clabe() -> str:
    """Generate a random valid-format CLABE."""
    bank = random.choice(["012", "014", "021", "030", "036", "072"])
    branch = f"{random.randint(1, 999):03d}"
    account = f"{random.randint(1, 99999999999):011d}"
    body = bank + branch + account
    # Compute check digit (CLABE algorithm)
    factors = [3, 7, 1] * 6
    total = 0
    for i in range(17):
        total += (int(body[i]) * factors[i]) % 10
    check = (10 - (total % 10)) % 10
    return body + str(check)


# ---------------------------------------------------------------------------
# CFDI Factory
# ---------------------------------------------------------------------------
class CFDIFactory:
    """Factory for generating CFDI test data."""

    @staticmethod
    def gasto_operativo(
        total: float = 5000.00,
        emisor_rfc: Optional[str] = None,
        receptor_rfc: Optional[str] = None,
        fecha: Optional[str] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Generate a gasto operativo CFDI (office supplies, services)."""
        emisor_rfc = emisor_rfc or _random_rfc("moral")
        receptor_rfc = receptor_rfc or _random_rfc("moral")
        fecha = fecha or date.today().isoformat()
        iva = round(total * 0.16, 2)
        base = {
            "version": "4.0",
            "serie": "A",
            "folio": str(random.randint(1000, 9999)),
            "fecha": fecha,
            "forma_pago": "01",
            "no_certificado": "30001000000500003416",
            "subtotal": total,
            "descuento": 0.0,
            "moneda": "MXN",
            "total": round(total + iva, 2),
            "tipo_de_comprobante": "I",
            "metodo_pago": "PUE",
            "lugar_expedicion": "06300",
            "emisor": {
                "rfc": emisor_rfc,
                "nombre": f"Empresa {emisor_rfc[:4]} SA de CV",
                "regimen_fiscal": random.choice(_REGIMENES_FISCALES),
            },
            "receptor": {
                "rfc": receptor_rfc,
                "nombre": f"Despacho {receptor_rfc[:4]}",
                "regimen_fiscal": "601",
                "uso_cfdi": "G03",
                "domicilio_fiscal_receptor": "06300",
            },
            "conceptos": [{
                "clave_prod_serv": random.choice(_CLAVES_PROD_SERVICIO),
                "cantidad": 1,
                "clave_unidad": random.choice(_CLAVES_UNIDAD),
                "descripcion": "Material de oficina y papelería",
                "valor_unitario": total,
                "importe": total,
                "descuento": 0,
                "traslados": [{
                    "base": total,
                    "impuesto": "002",
                    "tipo_factor": "Tasa",
                    "tasa_o_cuota": "0.160000",
                    "importe": iva,
                }],
            }],
            "impuestos": {
                "total_impuestos_trasladados": iva,
                "traslados": [{
                    "base": total,
                    "impuesto": "002",
                    "tipo_factor": "Tasa",
                    "tasa_o_cuota": "0.160000",
                    "importe": iva,
                }],
            },
            "uuid": str(secrets.token_hex(8)).upper(),
        }
        base.update(overrides)
        return base

    @staticmethod
    def nomina(
        sueldo_bruto: float = 15000.00,
        empleado_rfc: Optional[str] = None,
        emisor_rfc: Optional[str] = None,
        dias_pagados: int = 15,
        **overrides,
    ) -> Dict[str, Any]:
        """Generate a nómina CFDI test object."""
        empleado_rfc = empleado_rfc or _random_rfc("fisica")
        emisor_rfc = emisor_rfc or _random_rfc("moral")
        isr = round(sueldo_bruto * 0.10, 2)
        imss = round(sueldo_bruto * 0.025, 2)
        neto = sueldo_bruto - isr - imss
        return {
            "version": "4.0",
            "serie": "N",
            "folio": str(random.randint(1000, 9999)),
            "fecha": date.today().isoformat(),
            "forma_pago": "99",
            "subtotal": sueldo_bruto,
            "moneda": "MXN",
            "total": neto,
            "tipo_de_comprobante": "N",
            "metodo_pago": "PUE",
            "emisor": {
                "rfc": emisor_rfc,
                "nombre": f"Empresa {emisor_rfc[:4]} SA de CV",
                "regimen_fiscal": "601",
            },
            "receptor": {
                "rfc": empleado_rfc,
                "nombre": f"Empleado {empleado_rfc[:4]}",
                "regimen_fiscal": "605",
                "uso_cfdi": "CN01",
            },
            "nomina": {
                "version": "1.2",
                "tipo_nomina": "O",
                "fecha_pago": date.today().isoformat(),
                "fecha_inicial_pago": (date.today() - timedelta(days=15)).isoformat(),
                "fecha_final_pago": date.today().isoformat(),
                "num_dias_pagados": dias_pagados,
                "empleado": {
                    "curp": _random_curp(),
                    "tipo_contrato": "01",
                    "tipo_regimen": "02",
                    "num_seguridad_social": _random_nss(),
                    "clave_ent federativa": "09",
                    "salario_diario_integrado": round(sueldo_bruto / dias_pagados, 2),
                },
                "percepciones": {
                    "total_sueldos": sueldo_bruto,
                    "percepciones": [{
                        "tipo_percepcion": "001",
                        "clave": "001",
                        "concepto": "Sueldos, Salarios Rayas y Jornales",
                        "importe_gravado": sueldo_bruto,
                        "importe_exento": 0,
                    }],
                },
                "deducciones": {
                    "total_impuestos_retenidos": isr,
                    "total_otras_deducciones": imss,
                    "deducciones": [
                        {
                            "tipo_deduccion": "002",
                            "clave": "002",
                            "concepto": "ISR",
                            "importe": isr,
                        },
                        {
                            "tipo_deduccion": "004",
                            "clave": "004",
                            "concepto": "Seguridad social",
                            "importe": imss,
                        },
                    ],
                },
            },
            **overrides,
        }

    @staticmethod
    def honorarios(
        total: float = 25000.00,
        emisor_rfc: Optional[str] = None,
        receptor_rfc: Optional[str] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Generate a honorarios (professional services) CFDI."""
        emisor_rfc = emisor_rfc or _random_rfc("fisica")
        receptor_rfc = receptor_rfc or _random_rfc("moral")
        ret_isr = round(total * 0.10, 2)
        iva = round(total * 0.16, 2)
        return {
            "version": "4.0",
            "serie": "H",
            "folio": str(random.randint(1000, 9999)),
            "fecha": date.today().isoformat(),
            "subtotal": total,
            "moneda": "MXN",
            "total": round(total + iva - ret_isr, 2),
            "tipo_de_comprobante": "I",
            "metodo_pago": "PUE",
            "emisor": {
                "rfc": emisor_rfc,
                "nombre": f"Profesional {emisor_rfc[:4]}",
                "regimen_fiscal": "612",
            },
            "receptor": {
                "rfc": receptor_rfc,
                "nombre": f"Empresa {receptor_rfc[:4]}",
                "regimen_fiscal": "601",
                "uso_cfdi": "G03",
            },
            "impuestos": {
                "total_impuestos_trasladados": iva,
                "total_impuestos_retenidos": ret_isr,
            },
            **overrides,
        }

    @staticmethod
    def xml_content(
        emisor_rfc: str = "DEMO220101AB1",
        receptor_rfc: str = "TEST220101CD2",
        total: float = 1000.00,
        uuid: Optional[str] = None,
    ) -> str:
        """Generate a minimal valid CFDI 4.0 XML string."""
        uuid = uuid or str(secrets.token_hex(8)).upper()
        iva = round(total * 0.16, 2)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante
    xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0"
    Serie="A"
    Folio="1234"
    Fecha="2026-01-15T10:30:00"
    FormaPago="01"
    NoCertificado="30001000000500003416"
    Certificado="MIIFuzCCA6OgAwIBAgIUMzAwMDEwMDAwMDA1MDAwMDM0MTYwDQYJKoZIhvcNAQELBQA..."
    Subtotal="{total:.2f}"
    Moneda="MXN"
    Total="{total + iva:.2f}"
    TipoDeComprobante="I"
    MetodoPago="PUE"
    LugarExpedicion="06300">
    <cfdi:Emisor Rfc="{emisor_rfc}" Nombre="Empresa Demo SA de CV" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="{receptor_rfc}" Nombre="Test Despacho" RegimenFiscal="601" UsoCfdi="G03" DomicilioFiscalReceptor="06300"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="43232300" Cantidad="1" ClaveUnidad="ACT" Descripcion="Servicio de consultoría" ValorUnitario="{total:.2f}" Importe="{total:.2f}" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="{total:.2f}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="{iva:.2f}"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="{iva:.2f}">
        <cfdi:Traslados>
            <cfdi:Traslado Base="{total:.2f}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="{iva:.2f}"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}" FechaTimbrado="2026-01-15T10:30:00" RfcProvCertif="SPR190613I52" SelloCFD="abc123..." NoCertificadoSAT="00001000000504160107" SelloSAT="def456..."/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


# ---------------------------------------------------------------------------
# Bank Transaction Factory
# ---------------------------------------------------------------------------
class BankTransactionFactory:
    """Factory for bank transaction test data."""

    @staticmethod
    def spei_transfer(
        monto: float = 5000.00,
        referencia: Optional[str] = None,
        fecha: Optional[str] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Generate a SPEI transfer bank transaction."""
        return {
            "fecha": fecha or date.today().isoformat(),
            "monto": monto,
            "referencia": referencia or f"REF{random.randint(100000, 999999)}",
            "descripcion": "Transferencia SPEI",
            "tipo": "abono",
            "cuenta_origen": f"****{random.randint(1000, 9999)}",
            "cuenta_destino": _random_clabe()[-10:],
            "banco_origen": random.choice(["BBVA", "Banamex", "Santander", "HSBC"]),
            **overrides,
        }

    @staticmethod
    def batch(n: int = 5, base_monto: float = 5000.00) -> List[Dict[str, Any]]:
        """Generate a batch of bank transactions."""
        return [
            BankTransactionFactory.spei_transfer(
                monto=base_monto + random.uniform(-1000, 5000),
                fecha=(date.today() - timedelta(days=i)).isoformat(),
            )
            for i in range(n)
        ]


# ---------------------------------------------------------------------------
# Tenant / User / API Key Factories
# ---------------------------------------------------------------------------
class TenantFactory:
    """Factory for tenant test data."""

    @staticmethod
    def create(
        name: str = "Test Despacho",
        rfc: Optional[str] = None,
        erp_type: str = "contpaqi",
        **overrides,
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "rfc": rfc or _random_rfc("moral"),
            "erp_type": erp_type,
            "plantilla_contable": "SAT",
            "blocked": False,
            **overrides,
        }


class UserFactory:
    """Factory for user test data."""

    @staticmethod
    def create(
        email: Optional[str] = None,
        role: str = "accountant",
        tenant_id: int = 1,
        **overrides,
    ) -> Dict[str, Any]:
        email = email or f"test_{secrets.token_hex(4)}@test.com"
        return {
            "email": email,
            "nombre": "Test User",
            "role": role,
            "tenant_id": tenant_id,
            "password_hash": "$2b$12$test_hash_for_testing_only",
            "active": True,
            **overrides,
        }


# ---------------------------------------------------------------------------
# Invoice Factory (for DB records)
# ---------------------------------------------------------------------------
class InvoiceFactory:
    """Factory for invoice DB records."""

    @staticmethod
    def create(
        tenant_id: int = 1,
        emisor_rfc: Optional[str] = None,
        receptor_rfc: Optional[str] = None,
        total: float = 10000.00,
        categoria: str = "gasto_operativo",
        valido: bool = True,
        **overrides,
    ) -> Dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "uuid": str(secrets.token_hex(8)).upper(),
            "emisor_rfc": emisor_rfc or _random_rfc("moral"),
            "receptor_rfc": receptor_rfc or _random_rfc("moral"),
            "fecha": date.today().isoformat(),
            "total": total,
            "subtotal": round(total / 1.16, 2),
            "iva": round(total - total / 1.16, 2),
            "moneda": "MXN",
            "categoria": categoria,
            "valido": valido,
            "metodo_pago": "PUE",
            "tipo_comprobante": "I",
            "erp_status": "synced",
            **overrides,
        }

    @staticmethod
    def batch(
        n: int = 10,
        tenant_id: int = 1,
        **overrides,
    ) -> List[Dict[str, Any]]:
        categorias = [
            "gasto_operativo", "inversion", "nomina", "honorarios",
            "arrendamiento", "servicio_profesional",
        ]
        return [
            InvoiceFactory.create(
                tenant_id=tenant_id,
                total=random.uniform(1000, 100000),
                categoria=random.choice(categorias),
                **overrides,
            )
            for _ in range(n)
        ]
