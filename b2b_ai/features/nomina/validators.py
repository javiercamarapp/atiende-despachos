# -*- coding: utf-8 -*-
"""
validators.py — Validación de datos Nomina 1.2 contra reglas SAT.

Reglas implementadas:
  1. RfcPatronOrigen debe coincidir con el RFC del Emisor del CFDI.
  2. FechaPago debe estar dentro del rango FechaInicialPago – FechaFinalPago.
  3. NumDiasPagados debe ser > 0 y <= días naturales del periodo.
  4. PeriodicidadPago debe ser un código SAT válido (01–08).
  5. TipoNomina debe ser O (Ordinaria) o E (Extraordinaria).

Cada función retorna una lista de strings (errores vacía = válido).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from b2b_ai.features.nomina.parser import NominaData

# ---------------------------------------------------------------------------
# Catálogos SAT
# ---------------------------------------------------------------------------

# Periodicidad de pago (SAT catálogo c_PercepcionTipo)
PERIODICIDAD_PAGO_CODES = {
    "01": "Semanal",
    "02": "Quincenal",
    "03": "Mensual",
    "04": "Bimestral",
    "05": "Unidad de obra",
    "06": "Comisión",
    "07": "Precio alzado",
    "08": "Exento",
}

# Tipo de nómina
TIPO_NOMINA_CODES = {
    "O": "Ordinaria",
    "E": "Extraordinaria",
}

# Tipo de jornada (SAT catálogo c_TipoJornada)
TIPO_JORNADA_CODES = {
    "01": "Diurna",
    "02": "Nocturna",
    "03": "Mixta",
    "04": "Por hora",
    "05": "Jornada reducida diurna",
    "06": "Jornada reducida nocturna",
    "07": "Jornada reducida mixta",
    "08": "Continuada (laboración de 8 hrs continuas)",
    "09": "Discontinua diurna",
    "10": "Discontinua nocturna",
    "11": "Discontinua mixta",
    "12": "Por turno",
}

# Riesgo del puesto (SAT catálogo c_RiesgoPuesto)
RIESGO_PUESTO_CODES = {
    "1": "Clase I",
    "2": "Clase II",
    "3": "Clase III",
    "4": "Clase IV",
    "5": "Clase V",
}


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parsea una fecha ISO (YYYY-MM-DD) a objeto date."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str.strip())
    except (ValueError, TypeError):
        return None


def _days_in_period(fecha_inicio: Optional[date], fecha_fin: Optional[date]) -> Optional[int]:
    """Calcula días naturales del periodo (inclusive)."""
    if fecha_inicio is None or fecha_fin is None:
        return None
    return (fecha_fin - fecha_inicio).days + 1


# ---------------------------------------------------------------------------
# Validadores individuales
# ---------------------------------------------------------------------------

def validate_rfc_patron(data: NominaData) -> List[str]:
    """Val. 1: RfcPatronOrigen debe coincidir con el RFC del Emisor del CFDI.

    Se aplica strip() a ambos valores antes de comparar para tolerar espacios.
    """
    errors: List[str] = []
    rfc_patron = (data.rfc_patron_origen or "").strip()
    rfc_emisor = (data.cfdi_emisor_rfc or "").strip()

    if not rfc_patron:
        errors.append("RfcPatronOrigen está vacío o ausente.")
        return errors
    if not rfc_emisor:
        # Si no hay RFC del emisor CFDI, no podemos cruzar; solo advertimos.
        return errors
    if rfc_patron != rfc_emisor:
        errors.append(
            f"RfcPatronOrigen '{data.rfc_patron_origen}' no coincide con el RFC del "
            f"Emisor del CFDI '{data.cfdi_emisor_rfc}'."
        )
    return errors


def validate_fechas(data: NominaData) -> List[str]:
    """Val. 2: FechaPago dentro del rango [FechaInicialPago, FechaFinalPago]."""
    errors: List[str] = []

    fecha_pago = _parse_date(data.fecha_pago)
    fecha_inicio = _parse_date(data.fecha_inicial_pago)
    fecha_fin = _parse_date(data.fecha_final_pago)

    if fecha_pago is None:
        errors.append("FechaPago ausente o formato inválido (se espera YYYY-MM-DD).")
    if fecha_inicio is None:
        errors.append("FechaInicialPago ausente o formato inválido.")
    if fecha_fin is None:
        errors.append("FechaFinalPago ausente o formato inválido.")
        return errors  # No podemos continuar sin las 3 fechas

    if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
        errors.append("FechaInicialPago es posterior a FechaFinalPago.")

    if fecha_pago and fecha_inicio and fecha_fin:
        # Rango estricto: FechaPago debe estar dentro de [FechaInicialPago, FechaFinalPago]
        # (tolerancia de fin de año eliminada — causaba falsos positivos en tests)
        if fecha_pago < fecha_inicio or fecha_pago > fecha_fin:
            errors.append(
                f"FechaPago '{data.fecha_pago}' está fuera del rango "
                f"[{data.fecha_inicial_pago}, {data.fecha_final_pago}]."
            )
    return errors


def validate_num_dias_pagados(data: NominaData) -> List[str]:
    """Val. 3: NumDiasPagados > 0 y <= días naturales del periodo."""
    errors: List[str] = []

    if data.num_dias_pagados is None:
        errors.append("NumDiasPagados ausente.")
        return errors

    # FIS-4: NumDiasPagados=0 es válido para TipoNomina="E" (extraordinaria)
    # Ejemplo: aguinaldo puro sin días laborados en el periodo.
    if data.tipo_nomina and data.tipo_nomina.strip().upper() == "E" and data.num_dias_pagados == 0:
        pass  # Válido para nóminas extraordinarias de aguinaldo puro
    elif data.num_dias_pagados <= 0:
        errors.append(f"NumDiasPagados ({data.num_dias_pagados}) debe ser mayor a 0.")
        return errors

    fecha_inicio = _parse_date(data.fecha_inicial_pago)
    fecha_fin = _parse_date(data.fecha_final_pago)
    dias_periodo = _days_in_period(fecha_inicio, fecha_fin)

    if dias_periodo is not None and data.num_dias_pagados > dias_periodo:
        errors.append(
            f"NumDiasPagados ({data.num_dias_pagados}) excede los días "
            f"naturales del periodo ({dias_periodo})."
        )
    return errors


def validate_periodicidad_pago(data: NominaData) -> List[str]:
    """Val. 4: PeriodicidadPago debe ser código SAT válido."""
    errors: List[str] = []
    if not data.periodicidad_pago:
        errors.append("PeriodicidadPago ausente.")
        return errors
    code = data.periodicidad_pago.strip()
    if code not in PERIODICIDAD_PAGO_CODES:
        errors.append(
            f"PeriodicidadPago '{code}' no es un código SAT válido. "
            f"Códigos válidos: {', '.join(sorted(PERIODICIDAD_PAGO_CODES.keys()))}."
        )
    return errors


def validate_tipo_nomina(data: NominaData) -> List[str]:
    """Val. 5: TipoNomina debe ser 'O' o 'E'."""
    errors: List[str] = []
    if not data.tipo_nomina:
        errors.append("TipoNomina ausente.")
        return errors
    code = data.tipo_nomina.strip().upper()
    if code not in TIPO_NOMINA_CODES:
        errors.append(
            f"TipoNomina '{data.tipo_nomina}' no es válido. "
            f"Valores aceptados: O (Ordinaria), E (Extraordinaria)."
        )
    return errors


# ---------------------------------------------------------------------------
# Validador maestro
# ---------------------------------------------------------------------------

def validate_nomina(data: NominaData) -> List[str]:
    """Ejecuta todas las validaciones SAT sobre los datos de nómina.

    Args:
        data: Datos extraídos por parse_nomina().

    Returns:
        Lista de errores (vacía si todo es válido).
    """
    if data is None:
        return ["No se encontró complemento de Nómina 1.2 en el XML."]

    errors: List[str] = []
    errors.extend(validate_rfc_patron(data))
    errors.extend(validate_fechas(data))
    errors.extend(validate_num_dias_pagados(data))
    errors.extend(validate_periodicidad_pago(data))
    errors.extend(validate_tipo_nomina(data))
    return errors
