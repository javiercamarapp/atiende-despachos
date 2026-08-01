# -*- coding: utf-8 -*-
"""
validators.py — Validación de datos Complemento de Pagos 1.1 contra reglas SAT.

Reglas implementadas:
  1. Monto del pago debe ser > 0.
  2. FormaPagoP debe ser un código SAT válido (c_FormaPago, 01-30).
  3. MonedaP debe ser código ISO 4217 válido.
  4. TipoCambioP consistente con MonedaP (MXN no requiere tipo de cambio).
  5. RfcEmisorCtaOrd del pago debe coincidir con Rfc del Emisor del CFDI.
  6. DoctoRelacionado: ImpSaldoAnt >= ImpPagado.
  7. DoctoRelacionado: ImpSaldoInsoluto = ImpSaldoAnt - ImpPagado.
  8. TipoCadPago debe ser código SAT válido (c_TipoCadPago, 01-03).

Cada función retorna una lista de strings (errores vacía = válido).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from b2b_ai.features.pagos.parser import PagosData

# ---------------------------------------------------------------------------
# Catálogos SAT
# ---------------------------------------------------------------------------

# Forma de pago (SAT catálogo c_FormaPago)
FORMA_PAGO_CODES = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electrónica de fondos",
    "04": "Tarjeta de crédito",
    "05": "Monedero electrónico",
    "06": "Dinero electrónico",
    "07": "Acuses de contribuciones y aprovechamientos",
    "08": "Ingreso por compensación",
    "09": "Representación impresa",
    "10": "Pago por internet",
    "11": "Traspaso bancario",
    "12": "Disposición de fondo",
    "13": "Fideicomiso",
    "14": "Pago por distribución de bienes",
    "15": "Préstamo",
    "16": "Ingreso por retorno de mercancía",
    "17": "Seguros",
    "18": "Depósito bancario",
    "19": "Prima de seguro contra robo",
    "20": "Préstamo de banco",
    "21": "Ingresos por servicios",
    "22": "Ingresos por arrendamiento",
    "23": "Ingresos por honorarios",
    "24": "Ingresos por premios",
    "25": "Ingresos por donativos",
    "26": "Ingresos por otros conceptos",
    "27": "Transferencia de mercancías",
    "28": "Factura de crédito",
    "29": "Ficha de depósito",
    "30": "Pago con vales de despensa",
}

# Tipo de cadena de pago (SAT catálogo c_TipoCadPago)
TIPO_CADENA_PAGO_CODES = {
    "01": "CFDI",
    "02": "Anticipo",
    "03": "Anticipo",
}

# Monedas ISO 4217 soportadas (lista extendida para México)
MONEDAS_ISO_4217 = {
    "MXN": "Peso mexicano",
    "USD": "Dólar estadounidense",
    "EUR": "Euro",
    "JPY": "Yen japonés",
    "GBP": "Libra esterlina",
    "CAD": "Dólar canadiense",
    "CHF": "Franco suizo",
    "CNY": "Yuan chino",
    "ARS": "Peso argentino",
    "BRL": "Real brasileño",
    "CLP": "Peso chileno",
    "COP": "Peso colombiano",
    "PEN": "Sol peruano",
    "UYU": "Peso uruguayo",
    "KRW": "Won surcoreano",
    "TWD": "Dólar taiwanés",
    "AUD": "Dólar australiano",
    "SEK": "Corona sueca",
    "NOK": "Corona noruega",
    "DKK": "Corona danesa",
    "PLN": "Zloty polaco",
    "CZK": "Corona checa",
    "HUF": "Forinto húngaro",
    "TRY": "Lira turca",
    "ZAR": "Rand sudafricano",
    "INR": "Rupia india",
    "BRL": "Real brasileño",
    "SGD": "Dólar de Singapur",
    "HKD": "Dólar de Hong Kong",
    "THB": "Baht tailandés",
    "PHP": "Peso filipino",
    "IDR": "Rupia indonesia",
    "MYR": "Ringgit malayo",
    "VND": "Dong vietnamita",
    "NZD": "Dólar neozelandés",
}

# Monedas que NO requieren tipo de cambio (moneda local)
MONEDAS_LOCALES = {"MXN"}


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parsea una fecha/hora ISO a objeto datetime."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Validadores individuales
# ---------------------------------------------------------------------------

def validate_monto_pago(pagos_data: PagosData) -> List[str]:
    """Val. 1: Monto del pago debe ser > 0."""
    errors: List[str] = []
    if not pagos_data.pagos:
        errors.append("No hay pagos en el complemento.")
        return errors
    for i, pago in enumerate(pagos_data.pagos):
        if pago.monto is None:
            errors.append(f"Pago {i + 1}: Monto ausente.")
        elif pago.monto <= 0:
            errors.append(f"Pago {i + 1}: Monto ({pago.monto}) debe ser mayor a 0.")
    return errors


def validate_forma_pago(pagos_data: PagosData) -> List[str]:
    """Val. 2: FormaPagoP debe ser código SAT válido."""
    errors: List[str] = []
    for i, pago in enumerate(pagos_data.pagos):
        forma = (pago.forma_pago_p or "").strip()
        if not forma:
            errors.append(f"Pago {i + 1}: FormaPagoP ausente.")
        else:
            if forma not in FORMA_PAGO_CODES:
                errors.append(
                    f"Pago {i + 1}: FormaPagoP '{forma}' no es un código SAT válido. "
                    f"Códigos válidos: {', '.join(sorted(FORMA_PAGO_CODES.keys()))}."
                )
    return errors


def validate_moneda(pagos_data: PagosData) -> List[str]:
    """Val. 3: MonedaP debe ser código ISO 4217 válido."""
    errors: List[str] = []
    for i, pago in enumerate(pagos_data.pagos):
        moneda = (pago.moneda_p or "").strip()
        if not moneda:
            errors.append(f"Pago {i + 1}: MonedaP ausente.")
        else:
            code = moneda.upper()
            if code not in MONEDAS_ISO_4217:
                errors.append(
                    f"Pago {i + 1}: MonedaP '{code}' no es un código ISO 4217 válido."
                )
    return errors


def validate_tipo_cambio(pagos_data: PagosData) -> List[str]:
    """Val. 4: TipoCambioP consistente con MonedaP.
    Monedas locales (MXN) no requieren tipo de cambio.
    Monedas extranjeras requieren TipoCambioP > 0.
    """
    errors: List[str] = []
    for i, pago in enumerate(pagos_data.pagos):
        moneda = (pago.moneda_p or "").upper().strip()
        if moneda in MONEDAS_LOCALES:
            # Para moneda local, tipo de cambio debe ser 1 o ausente
            if pago.tipo_cambio_p is not None and pago.tipo_cambio_p != Decimal("1"):
                errors.append(
                    f"Pago {i + 1}: TipoCambioP ({pago.tipo_cambio_p}) debe ser 1 "
                    f"para moneda local {moneda}."
                )
        else:
            # Para moneda extranjera, tipo de cambio es requerido y debe ser > 0
            if pago.tipo_cambio_p is None:
                errors.append(
                    f"Pago {i + 1}: TipoCambioP es requerido para moneda extranjera {moneda}."
                )
            elif pago.tipo_cambio_p <= 0:
                errors.append(
                    f"Pago {i + 1}: TipoCambioP ({pago.tipo_cambio_p}) debe ser mayor a 0."
                )
    return errors


def validate_rfc_emisor(pagos_data: PagosData) -> List[str]:
    """Val. 5: RfcEmisorCtaOrd del pago debe coincidir con Rfc del Emisor del CFDI."""
    errors: List[str] = []
    rfc_emisor_cfdi = (pagos_data.cfdi_emisor_rfc or "").strip()

    if not rfc_emisor_cfdi:
        return errors  # No hay RFC del emisor CFDI para comparar

    for i, pago in enumerate(pagos_data.pagos):
        rfc_ordenante = (pago.rfc_emisor_cta_ord or "").strip()
        if rfc_ordenante and rfc_ordenante != rfc_emisor_cfdi:
            errors.append(
                f"Pago {i + 1}: RfcEmisorCtaOrd '{pago.rfc_emisor_cta_ord}' no coincide "
                f"con el RFC del Emisor del CFDI '{rfc_emisor_cfdi}'."
            )
    return errors


def validate_doctos_relacionados(pagos_data: PagosData) -> List[str]:
    """Val. 6-7: Validaciones de DoctoRelacionado.
    - ImpSaldoAnt >= ImpPagado
    - ImpSaldoInsoluto = ImpSaldoAnt - ImpPagado
    """
    errors: List[str] = []
    for i, pago in enumerate(pagos_data.pagos):
        for j, doc in enumerate(pago.documentos_relacionados):
            label = f"Pago {i + 1}, Docto {j + 1}"

            if doc.imp_saldo_ant is not None and doc.imp_pagado is not None:
                if doc.imp_saldo_ant < doc.imp_pagado:
                    errors.append(
                        f"{label}: ImpSaldoAnt ({doc.imp_saldo_ant}) es menor "
                        f"que ImpPagado ({doc.imp_pagado})."
                    )

            if (doc.imp_saldo_ant is not None and doc.imp_pagado is not None
                    and doc.imp_saldo_insoluto is not None):
                expected = doc.imp_saldo_ant - doc.imp_pagado
                if doc.imp_saldo_insoluto != expected:
                    errors.append(
                        f"{label}: ImpSaldoInsoluto ({doc.imp_saldo_insoluto}) "
                        f"no coincide con ImpSaldoAnt - ImpPagado ({expected})."
                    )
    return errors


def validate_tipo_cadena_pago(pagos_data: PagosData) -> List[str]:
    """Val. 8: TipoCadPago debe ser código SAT válido."""
    errors: List[str] = []
    for i, pago in enumerate(pagos_data.pagos):
        if pago.tipo_cad_pago is not None:
            code = pago.tipo_cad_pago.strip()
            if code not in TIPO_CADENA_PAGO_CODES:
                errors.append(
                    f"Pago {i + 1}: TipoCadPago '{code}' no es un código SAT válido. "
                    f"Códigos válidos: {', '.join(sorted(TIPO_CADENA_PAGO_CODES.keys()))}."
                )
    return errors


# ---------------------------------------------------------------------------
# Validador maestro
# ---------------------------------------------------------------------------

def validate_pagos(pagos_data: PagosData) -> List[str]:
    """Ejecuta todas las validaciones SAT sobre los datos de pagos.

    Args:
        pagos_data: Datos extraídos por parse_pagos().

    Returns:
        Lista de errores (vacía si todo es válido).
    """
    if pagos_data is None:
        return ["No se encontró complemento de Pagos 1.1 en el XML."]

    errors: List[str] = []
    errors.extend(validate_monto_pago(pagos_data))
    errors.extend(validate_forma_pago(pagos_data))
    errors.extend(validate_moneda(pagos_data))
    errors.extend(validate_tipo_cambio(pagos_data))
    errors.extend(validate_rfc_emisor(pagos_data))
    errors.extend(validate_doctos_relacionados(pagos_data))
    errors.extend(validate_tipo_cadena_pago(pagos_data))
    return errors
