# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración con ERPs (CONTPAQi, Aspel, QuickBooks, Xero).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ERPType(str, Enum):
    """Tipos de ERP soportados."""
    CONTPAQi_WEB = "contpaqi_web"
    CONTPAQi_DESKTOP = "contpaqi_desktop"
    CONTPAQi_ONE = "contpaqi_one"
    ASPEL_CLOUD = "aspel_cloud"
    QUICKBOOKS_ONLINE = "quickbooks_online"
    QUICKBOOKS_DESKTOP = "quickbooks_desktop"
    XERO = "xero"
    PEAK = "peak"
    MULTILEG = "multileg"
    EUROWEB = "euroweb"
    ABSIS = "absis"
    FACTOR_D = "factor_d"
    TAXKO = "taxko"
    FACTURADIRECTA = "facturadirecta"
    GENERIC = "generic"


class TipoCuenta(str, Enum):
    """Tipos de cuenta contable."""
    ACTIVO = "activo"
    PASIVO = "pasivo"
    CAPITAL = "capital"
    INGRESO = "ingreso"
    GASTO = "gasto"
    RESULTADO = "resultado"


class StatusPoliza(str, Enum):
    """Estado de una póliza contable."""
    REGISTRADA = "registrada"
    CONTABILIZADA = "contabilizada"
    CANCELADA = "cancelada"
    ENVIADA = "enviada"


# ---------------------------------------------------------------------------
# ERP Configuration
# ---------------------------------------------------------------------------

class ERPConfig(BaseModel):
    """Configuración de conexión al ERP."""
    type: ERPType = Field(..., description="Tipo de ERP")
    endpoint: Optional[str] = Field(default=None, description="URL del endpoint API")
    database: Optional[str] = Field(default=None, description="Nombre de la base de datos")
    empresa: Optional[str] = Field(default=None, description="Nombre/ID de la empresa")
    username: Optional[str] = Field(default=None, description="Usuario")
    password: Optional[str] = Field(default=None, description="Contraseña (encriptada)")
    api_key: Optional[str] = Field(default=None, description="API Key (para cloud)")
    company_id: Optional[str] = Field(default=None, description="Company ID (QuickBooks/Xero)")
    timeout: int = Field(default=30, description="Timeout en segundos")
    retry_attempts: int = Field(default=3, description="Intentos de reintento")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "type": "quickbooks_online",
                "endpoint": "https://quickbooks.api.intuit.com/v3",
                "company_id": "12345678",
                "api_key": "qb-api-key-xxx",
            }]
        }
    }


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

class Invoice(BaseModel):
    """Factura del ERP."""
    id: str = Field(default="", description="ID de la factura en el ERP")
    uuid: Optional[str] = Field(default=None, description="UUID del CFDI (si aplica)")
    rfc: str = Field(default="", description="RFC del cliente/proveedor")
    fecha: str = Field(default="", description="Fecha de la factura YYYY-MM-DD")
    monto: float = Field(default=0.0, description="Monto total")
    subtotal: float = Field(default=0.0, description="Subtotal")
    iva: float = Field(default=0.0, description="IVA")
    status: str = Field(default="activa", description="Estado de la factura")
    concepto: str = Field(default="", description="Concepto/descripción")
    serie: str = Field(default="", description="Serie")
    folio: str = Field(default="", description="Folio")
    moneda: str = Field(default="MXN", description="Moneda")
    tipo_cambio: float = Field(default=1.0, description="Tipo de cambio")
    forma_pago: str = Field(default="", description="Forma de pago")
    metodo_pago: str = Field(default="", description="Método de pago")
    rfc_receptor: str = Field(default="", description="RFC del receptor")
    nombre_receptor: str = Field(default="", description="Nombre del receptor")
    regimen_fiscal: str = Field(default="", description="Régimen fiscal")


# ---------------------------------------------------------------------------
# Póliza
# ---------------------------------------------------------------------------

class CuentaPoliza(BaseModel):
    """Línea de cuenta en una póliza."""
    cuenta: str = Field(..., description="Clave de la cuenta contable")
    descripcion: str = Field(default="", description="Descripción del movimiento")
    debe: float = Field(default=0.0, ge=0, description="Cargo (debe)")
    haber: float = Field(default=0.0, ge=0, description="Abono (haber)")
    rfc: Optional[str] = Field(default=None, description="RFC asociado (si aplica)")


class Poliza(BaseModel):
    """Póliza contable del ERP."""
    id: str = Field(default="", description="ID de la póliza en el ERP")
    fecha: str = Field(default="", description="Fecha de la póliza YYYY-MM-DD")
    concepto: str = Field(default="", description="Concepto de la póliza")
    tipo: str = Field(default="Diario", description="Tipo de póliza (Diario, Ingresos, Egresos)")
    numero: Optional[int] = Field(default=None, description="Número de póliza")
    cuentas: List[CuentaPoliza] = Field(default_factory=list, description="Movimientos contables")
    monto_total: float = Field(default=0.0, description="Monto total (suma de cargos)")
    status: StatusPoliza = Field(default=StatusPoliza.REGISTRADA)
    serie: Optional[str] = Field(default=None, description="Serie del documento origen")
    folio: Optional[int] = Field(default=None, description="Folio del documento origen")
    uuid_cfdi: Optional[str] = Field(default=None, description="UUID del CFDI asociado")

    def calcular_totales(self) -> tuple[float, float]:
        """Calcula totales de debe y haber."""
        total_debe = sum(c.debe for c in self.cuentas)
        total_haber = sum(c.haber for c in self.cuentas)
        return total_debe, total_haber

    def esta_cuadrada(self) -> bool:
        """Verifica si la póliza está cuadrada (debe == haber)."""
        total_debe, total_haber = self.calcular_totales()
        return abs(total_debe - total_haber) < 0.01


class CuentaContable(BaseModel):
    """Cuenta del catálogo de cuentas."""
    clave: str = Field(..., description="Clave de la cuenta")
    nombre: str = Field(default="", description="Nombre de la cuenta")
    tipo: TipoCuenta = Field(default=TipoCuenta.ACTIVO, description="Tipo de cuenta")
    nivel: int = Field(default=1, description="Nivel en la jerarquía")
    padre: Optional[str] = Field(default=None, description="Cuenta padre")
    saldo: float = Field(default=0.0, description="Saldo actual")
    es_auxiliar: bool = Field(default=False, description="Si es cuenta auxiliar (movimiento)")
    moneda: str = Field(default="MXN", description="Moneda")
    estatus: str = Field(default="activa", description="Estatus de la cuenta")
    descripcion: str = Field(default="", description="Descripción de la cuenta")


class ChartOfAccounts(BaseModel):
    """Catálogo de cuentas del ERP."""
    empresa: str = Field(default="", description="Nombre de la empresa")
    ejercicio: int = Field(default=2026, description="Ejercicio fiscal")
    cuentas: List[CuentaContable] = Field(default_factory=list, description="Cuentas contables")
    fecha_exportacion: Optional[str] = Field(default=None, description="Fecha de exportación")


class BalanzaComprobacion(BaseModel):
    """Balanza de comprobación."""
    ejercicio: int = Field(..., description="Ejercicio fiscal")
    mes: int = Field(..., ge=1, le=12, description="Mes")
    rfc: str = Field(default="", description="RFC de la empresa")
    cuentas: List[Dict[str, Any]] = Field(default_factory=list, description="Cuentas con saldos")
    total_deudor: float = Field(default=0.0, description="Total deudor")
    total_acreedor: float = Field(default=0.0, description="Total acreedor")
    fecha_generacion: Optional[str] = Field(default=None, description="Fecha de generación")
