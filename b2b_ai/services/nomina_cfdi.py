# -*- coding: utf-8 -*-
"""
nomina_cfdi.py — Complemento de Nómina CFDI 4.0 (Complemento Nomina 1.2).

Parser y generador de nóminas electrónicas con soporte completo para:

  • Percepciones: sueldos, primas, aguinaldo, vacaciones, PTU, incapacidades
  • Deducciones: ISR, IMSS, INFONAVIT, cuotas sindicales, otros
  • Otros pagos: subsidio para el empleo, viáticos, finiquito
  • Horas extra (dobles y triples) — LFT arts. 66-68
  • Incapacidades (riesgo de trabajo, enfermedad, maternidad)
  • Tipos de nómina: O (ordinaria), E (extraordinaria), S (subsidio)

Estructura CFDI 4.0 esperada:
  <cfdi:Comprobante TipoDeComprobante="N" ...>
    <cfdi:Complemento>
      <nomina:Nomina Version="1.2" TipoNomina="O" ...>
        <nomina:Percepciones>
          <nomina:Percepcion TipoPercepcion="001" .../>
        </nomina:Percepciones>
        <nomina:Deducciones>
          <nomina:Deduccion TipoDeduccion="002" .../>
        </nomina:Deducciones>
        <nomina:Incapacidades>
          <nomina:Incapacidad .../>
        </nomina:Incapacidades>
        <nomina:HorasExtras>
          <nomina:HorasExtra .../>
        </nomina:HorasExtras>
        <nomina:OtrosPagos>
          <nomina:OtroPago TipoOtroPago="002" .../>
        </nomina:OtrosPagos>
      </nomina:Nomina>
    </cfdi:Complemento>
  </cfdi:Comprobante>

Referencias:
  - Anexo 20 CFDI 4.0 (DOF 20-ene-2022)
  - Guía de llenado Complemento Nómina 1.2 (SAT)
  - LISR art. 96, 174 · LSS arts. 105-109 · LFT arts. 66-68, 76-80, 87

FECHA: 2026-08-01
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from b2b_ai.cfdi.xml_security import safe_parser, safe_parse, MAX_XML_BYTES
from b2b_ai.cfdi.catalogs import (
    REGIMENES_FISCALES, USOS_CFDI, TIPOS_COMPROBANTE, FORMAS_PAGO,
)
from b2b_ai.common.rfc import is_valid_rfc

# ---------------------------------------------------------------------------
# Namespaces CFDI 4.0 + Complemento Nómina 1.2
# ---------------------------------------------------------------------------
NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "nomina": "http://www.sat.gob.mx/nomina12",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

SCHEMA_LOCATIONS = (
    "http://www.sat.gob.mx/cfd/4 "
    "http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd "
    "http://www.sat.gob.mx/nomina12 "
    "http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd"
)

# ---------------------------------------------------------------------------
# Catálogos SAT para Complemento Nómina 1.2
# ---------------------------------------------------------------------------

# c_TipoNomina (Complemento Nómina 1.2)
TIPOS_NOMINA: Dict[str, str] = {
    "O": "Nómina ordinaria",
    "E": "Nómina extraordinaria",
    "S": "Nómina por subsidio",
}

# c_TipoPercepcion (Complemento Nómina 1.2)
TIPOS_PERCEPCION: Dict[str, str] = {
    "001": "Sueldos, Salarios, Rayas y Jornales",
    "002": "Gratificación anual (aguinaldo)",
    "003": "Participación de los Trabajadores en las Utilidades PTU",
    "004": "Reembolso de gastos médicos dentales y hospitalarios",
    "005": "Fondo de ahorro",
    "006": "Contribuciones al SAR o al Infonavit cubiertas por el patrón",
    "007": "Contribuciones al IMSS cubiertas por el patrón",
    "008": "Prima por antigüedad",
    "009": "Prima vacacional",
    "010": "Prima dominical",
    "011": "Prima de productividad",
    "012": "Ayuda para renta",
    "013": "Ayuda para artículos escolares",
    "014": "Ayuda para anteojos",
    "015": "Ayuda para transporte",
    "016": "Ayuda para gastos de funeral",
    "017": "Cuotas sindicales",
    "018": "Despensa",
    "019": "Premios por puntualidad",
    "020": "Premios por asistencia",
    "021": "Pago por separación",
    "022": "Seguro de gastos médicos",
    "023": "Seguro de vida",
    "024": "Vales de despensa",
    "025": "Vales de restaurante",
    "026": "Vales de gasolina",
    "027": "Fondo de ahorro (patrón)",
    "028": "Premios por antigüedad",
    "029": "Bono de productividad",
    "030": "Compensación por días laborados",
    "031": "Viáticos",
    "032": "Otros",
    "033": "Ingresos asimilados a salarios",
    "034": "Remuneración por comisiones",
    "035": "Remuneración por horas extraordinarias (dobles)",
    "036": "Remuneración por horas extraordinarias (triples)",
    "037": "Remuneración por servicios profesionales",
    "038": "Indemnización por despido",
    "039": "Apoyo para capacitación",
    "040": "Apoyo para guardería",
    "041": "Prima vacacional (proporcional)",
    "042": "Prima de antigüedad (proporcional)",
    "043": "Ayuda para gastos de mudanza",
    "044": "Estímulos por productividad",
    "045": "Premios por asistencia (adicional)",
    "046": "Remuneración por horas extras (dobles, sobre excedente)",
    "047": "Remuneración por horas extras (triples, sobre excedente)",
    "048": "Compensación por días de descanso",
    "049": "Bonos por desempeño",
    "050": "Participación por ventas",
}

# c_TipoDeduccion (Complemento Nómina 1.2)
TIPOS_DEDUCCION: Dict[str, str] = {
    "001": "Seguridad social",
    "002": "ISR",
    "003": "Aportaciones a retiro, cesantía en edad avanzada y vejez",
    "004": "Otros",
    "005": "Aportaciones a fondos de vivienda",
    "006": "Descuento por incapacidad",
    "007": "Pensión alimenticia",
    "008": "Renta",
    "009": "Préstamos provenientes del Fondo Nacional de la Vivienda",
    "010": "Pago por crédito de vivienda",
    "011": "Pago de abonos INFONAVIT",
    "012": "Anticipo de salarios",
    "013": "Pago de crédito FONACOT",
    "014": "Descuento por aportación voluntaria SAR",
    "015": "Descuento por aportación voluntaria AFORE",
    "016": "Descuento por aportación complementaria de retiro",
    "017": "Descuento por aportación a la subcuenta de retiro",
    "018": "Descuento por crédito hipotecario",
    "019": "Descuento por pensión alimenticia (por decreto judicial)",
    "020": "Cuotas sindicales",
    "021": "Descuento por adeudo INFONACOT",
    "022": "Descuento por cuota INFONAVIT",
    "023": "Descuento por adeudo FOVISSSTE",
    "024": "Descuento por cuota FOVISSSTE",
    "025": "Descuento por adeudo FONACOT",
    "026": "Descuento por adeudo ISSSTE",
    "027": "Descuento por cuota ISSSTE",
    "028": "Descuento por retiro ISSSTE",
    "029": "Descuento por préstamo personal",
    "030": "Descuento por aportación voluntaria ISSSTE",
    "031": "Descuento por préstamo hipotecario ISSSTE",
    "032": "Descuento por adeudo de agua",
    "033": "Descuento por adeudo de luz",
    "034": "Descuento por adeudo de teléfono",
    "035": "Descuento de seguridad social (patrón)",
    "036": "Descuento de SAR/INFONAVIT (patrón)",
    "037": "Descuento por pensión alimenticia provisional",
    "038": "Descuento judicial",
    "039": "Descuento por adeudo de vivienda ISSSTE",
}

# c_TipoOtroPago (Complemento Nómina 1.2)
TIPOS_OTRO_PAGO: Dict[str, str] = {
    "001": "Reintegro de ISR pagado en exceso (cuando el ISR se retuvo y se pagó)",
    "002": "Subsidio para el empleo",
    "003": "Viáticos",
    "004": "Aplicación de saldo a favor",
    "005": "Compensación por saldo a favor",
    "006": "Finiquito por separación",
    "007": "Indemnización por separación",
    "008": "Otros pagos",
}

# c_TipoIncapacidad (Complemento Nómina 1.2)
TIPOS_INCAPACIDAD: Dict[str, str] = {
    "01": "Riesgo de trabajo",
    "02": "Enfermedad en general",
    "03": "Maternidad",
    "04": "Licencia por cuidados maternos",
}

# c_PeriodicidadPago (Complemento Nómina 1.2)
PERIODICIDADES_PAGO: Dict[str, str] = {
    "Diario": "Diario",
    "Semanal": "Semanal",
    "Decenal": "Decenal",
    "Catorcenal": "Catorcenal",
    "Quincenal": "Quincenal",
    "Mensual": "Mensual",
    "Bimestral": "Bimestral",
    "Unidad obra": "Unidad obra",
    "Comision": "Comisión",
    "Precio alzado": "Precio alzado",
}

VALID_PERIODICIDADES = set(PERIODICIDADES_PAGO.keys())

# c_TipoContrato (Complemento Nómina 1.2)
TIPOS_CONTRATO: Dict[str, str] = {
    "01": "Contrato de trabajo por tiempo indeterminado",
    "02": "Contrato de trabajo para obra determinada",
    "03": "Contrato de trabajo por tiempo determinado",
    "04": "Contrato de trabajo por temporada",
    "05": "Contrato de trabajo sujeto a prueba",
    "06": "Contrato de trabajo con periodo de capacitación inicial",
    "07": "Modalidad de contratación por pago de hora laborada",
    "08": "Modalidad de contratación por comisión laboral",
    "09": "Modalidades de contratación donde no existe relación de trabajo",
    "10": "Jubilación, pensión, retiro",
    "99": "Otro contrato",
}

# c_TipoJornada
TIPOS_JORNADA: Dict[str, str] = {
    "01": "Diurna",
    "02": "Nocturna",
    "03": "Mixta",
    "04": "Por hora",
    "05": "Reducida",
    "06": "Continuada",
    "07": "Partida",
    "99": "Otra jornada",
}

# c_TipoRegimen (Complemento Nómina 1.2)
TIPOS_REGIMEN: Dict[str, str] = {
    "01": "Asimilados a salarios",
    "02": "Sueldos y salarios",
    "03": "Jubilación",
    "04": "Pensión",
    "05": "Acciones o títulos valor que representan bienes",
}

# c_RiesgoPuesto
RIESGOS_PUESTO: Dict[str, str] = {
    "01": "Clase I (Riesgo mínimo)",
    "02": "Clase II (Riesgo bajo)",
    "03": "Clase III (Riesgo medio)",
    "04": "Clase IV (Riesgo alto)",
    "05": "Clase V (Riesgo máximo)",
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NominaPercepcion:
    """Una percepción individual en el complemento de nómina."""
    tipo_percepcion: str  # Catálogo c_TipoPercepcion
    clave: str
    concepto: str
    importe_gravado: Decimal = Decimal("0")
    importe_exento: Decimal = Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tipo_percepcion": self.tipo_percepcion,
            "clave": self.clave,
            "concepto": self.concepto,
            "importe_gravado": str(self.importe_gravado),
            "importe_exento": str(self.importe_exento),
        }


@dataclass
class NominaDeduccion:
    """Una deducción individual en el complemento de nómina."""
    tipo_deduccion: str  # Catálogo c_TipoDeduccion
    clave: str
    concepto: str
    importe: Decimal = Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tipo_deduccion": self.tipo_deduccion,
            "clave": self.clave,
            "concepto": self.concepto,
            "importe": str(self.importe),
        }


@dataclass
class NominaOtroPago:
    """Otro pago en el complemento de nómina (subsidio, viáticos, etc.)."""
    tipo_otro_pago: str  # Catálogo c_TipoOtroPago
    clave: str
    concepto: str
    importe: Decimal = Decimal("0")

    # Campos opcionales para subsidio al empleo
    subsidio_causado: Optional[Decimal] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "tipo_otro_pago": self.tipo_otro_pago,
            "clave": self.clave,
            "concepto": self.concepto,
            "importe": str(self.importe),
        }
        if self.subsidio_causado is not None:
            d["subsidio_causado"] = str(self.subsidio_causado)
        return d


@dataclass
class NominaIncapacidad:
    """Incapacidad registrada en el complemento de nómina."""
    tipo_incapacidad: str  # 01=Riesgo trabajo, 02=Enfermedad, 03=Maternidad
    dias_incapacidad: int
    importe: Decimal = Decimal("0")
    descripcion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tipo_incapacidad": self.tipo_incapacidad,
            "dias_incapacidad": self.dias_incapacidad,
            "importe": str(self.importe),
            "descripcion": self.descripcion,
        }


@dataclass
class NominaHoraExtra:
    """Registro de horas extra (dobles o triples)."""
    dias: int
    tipo_horas: str  # "Dobles" o "Triples"
    horas_extra: int
    importe_pagado: Decimal = Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dias": self.dias,
            "tipo_horas": self.tipo_horas,
            "horas_extra": self.horas_extra,
            "importe_pagado": str(self.importe_pagado),
        }


@dataclass
class NominaEmisorData:
    """Datos del Emisor en el complemento Nómina."""
    rfc: str
    nombre: str
    regimen_fiscal: str  # Catálogo c_RegimenFiscal
    registro_patronal: str = ""

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not is_valid_rfc(self.rfc):
            errors.append(f"RFC emisor inválido: {self.rfc}")
        if self.regimen_fiscal not in REGIMENES_FISCALES:
            errors.append(f"Régimen fiscal inválido: {self.regimen_fiscal}")
        if not self.registro_patronal.strip():
            errors.append("Registro patronal es obligatorio en complemento nómina")
        return errors


@dataclass
class NominaReceptorData:
    """Datos del Receptor (trabajador) en el complemento Nómina."""
    rfc: str
    nombre: str
    curp: str
    num_seguridad_social: str = ""
    periodicidad_pago: str = "Mensual"  # Catálogo c_PeriodicidadPago
    tipo_contrato: str = "01"  # Catálogo c_TipoContrato
    tipo_jornada: str = "01"  # Catálogo c_TipoJornada
    tipo_regimen: str = "02"  # Catálogo c_TipoRegimen
    num_empleado: str = "1"
    departamento: str = ""
    puesto: str = ""
    riesgo_puesto: str = "01"
    salario_diario_integrado: Optional[Decimal] = None
    salario_base_cotizacion: Optional[Decimal] = None

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not is_valid_rfc(self.rfc):
            errors.append(f"RFC receptor inválido: {self.rfc}")
        if not self.curp or len(self.curp.strip()) < 18:
            errors.append(f"CURP inválido: {self.curp}")
        if self.periodicidad_pago not in VALID_PERIODICIDADES:
            errors.append(
                f"Periodicidad de pago inválida: {self.periodicidad_pago}. "
                f"Valores: {', '.join(sorted(VALID_PERIODICIDADES))}"
            )
        if self.tipo_contrato not in TIPOS_CONTRATO:
            errors.append(f"Tipo contrato inválido: {self.tipo_contrato}")
        if self.tipo_jornada not in TIPOS_JORNADA:
            errors.append(f"Tipo jornada inválido: {self.tipo_jornada}")
        if self.tipo_regimen not in TIPOS_REGIMEN:
            errors.append(f"Tipo régimen inválido: {self.tipo_regimen}")
        if self.riesgo_puesto not in RIESGOS_PUESTO:
            errors.append(f"Riesgo puesto inválido: {self.riesgo_puesto}")
        return errors


@dataclass
class NominaPeriodo:
    """Periodo de pago de la nómina."""
    fecha_pago: str  # ISO date
    fecha_inicial: str  # ISO date
    fecha_final: str  # ISO date
    num_dias_pagados: int = 30

    def validate(self) -> List[str]:
        errors: List[str] = []
        try:
            fp = date.fromisoformat(self.fecha_pago)
            fi = date.fromisoformat(self.fecha_inicial)
            ff = date.fromisoformat(self.fecha_final)
            if ff < fi:
                errors.append("Fecha final no puede ser anterior a fecha inicial")
            if self.num_dias_pagados <= 0 or self.num_dias_pagados > 365:
                errors.append(f"Días pagados inválidos: {self.num_dias_pagados}")
            if fp < ff:
                # Fecha de pago debe ser >= fecha final del periodo
                errors.append(
                    f"Fecha de pago ({self.fecha_pago}) debe ser >= "
                    f"fecha final ({self.fecha_final})"
                )
        except ValueError as e:
            errors.append(f"Fecha inválida: {e}")
        return errors


@dataclass
class NominaTotales:
    """Totales del complemento nómina."""
    total_percepciones: Decimal = Decimal("0")
    total_deducciones: Decimal = Decimal("0")
    total_otros_pagos: Decimal = Decimal("0")

    def to_dict(self) -> Dict[str, str]:
        return {
            "total_percepciones": str(self.total_percepciones),
            "total_deducciones": str(self.total_deducciones),
            "total_otros_pagos": str(self.total_otros_pagos),
        }


@dataclass
class NominaData:
    """Datos completos de una nómina CFDI 4.0."""
    emisor: NominaEmisorData
    receptor: NominaReceptorData
    periodo: NominaPeriodo
    tipo_nomina: str = "O"  # O, E, S
    percepciones: List[NominaPercepcion] = field(default_factory=list)
    deducciones: List[NominaDeduccion] = field(default_factory=list)
    otros_pagos: List[NominaOtroPago] = field(default_factory=list)
    incapacidades: List[NominaIncapacidad] = field(default_factory=list)
    horas_extras: List[NominaHoraExtra] = field(default_factory=list)
    totales: NominaTotales = field(default_factory=NominaTotales)

    def validate(self) -> Dict[str, Any]:
        """Valida todos los datos de la nómina. Retorna dict con 'valid' y 'errors'."""
        errors: List[str] = []
        warnings: List[str] = []

        e_errors = self.emisor.validate()
        errors.extend(f"[Emisor] {e}" for e in e_errors)

        r_errors = self.receptor.validate()
        errors.extend(f"[Receptor] {e}" for e in r_errors)

        p_errors = self.periodo.validate()
        errors.extend(f"[Periodo] {e}" for e in p_errors)

        if self.tipo_nomina not in TIPOS_NOMINA:
            errors.append(
                f"Tipo nómina inválido: {self.tipo_nomina}. "
                f"Valores: {', '.join(TIPOS_NOMINA.keys())}"
            )

        if not self.percepciones:
            warnings.append("No hay percepciones registradas")

        if not self.deducciones:
            warnings.append("No hay deducciones registradas")

        for p in self.percepciones:
            if p.tipo_percepcion not in TIPOS_PERCEPCION:
                warnings.append(
                    f"TipoPercepcion {p.tipo_percepcion} ({p.concepto}) "
                    f"no está en catálogo SAT"
                )

        for d in self.deducciones:
            if d.tipo_deduccion not in TIPOS_DEDUCCION:
                warnings.append(
                    f"TipoDeduccion {d.tipo_deduccion} ({d.concepto}) "
                    f"no está en catálogo SAT"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
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


def _round2(d: Decimal) -> Decimal:
    """Redondea a 2 decimales."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(d: Decimal) -> str:
    """Formatea Decimal a string con 2 decimales."""
    return str(_round2(d))


def _localname(node) -> str:
    """Obtiene el nombre local (sin namespace) de un elemento lxml."""
    return etree.QName(node).localname


def _find_first(root, localname) -> Optional[etree._Element]:
    """Encuentra el primer descendiente con el localname dado."""
    for child in root.iter():
        if _localname(child) == localname:
            return child
    return None


def _find_all(root, localname) -> List[etree._Element]:
    """Encuentra todos los descendientes con el localname dado."""
    return [c for c in root.iter() if _localname(c) == localname]


# ---------------------------------------------------------------------------
# NominaCFDIProcessor
# ---------------------------------------------------------------------------


class NominaCFDIProcessorError(Exception):
    """Error base del procesador de nómina CFDI."""


class NominaCFDIProcessor:
    """
    Procesador de nóminas CFDI 4.0 con Complemento Nomina 1.2.

    Proporciona:
      - parse_nomina_cfdi(xml_path) → NominaData
      - generate_nomina_cfdi(data) → str (XML)
      - generate_xml_with_timbre(data, timbre_data) → str (XML con TFD)
      - validate_nomina_data(data) → dict
    """

    # ------------------------------------------------------------------
    # Parseo
    # ------------------------------------------------------------------

    @staticmethod
    def parse_nomina_cfdi(xml_path: str) -> NominaData:
        """
        Parsea un archivo XML de CFDI 4.0 con complemento de nómina.

        Args:
            xml_path: Ruta al archivo XML.

        Returns:
            NominaData con todos los campos extraídos.

        Raises:
            NominaCFDIProcessorError: Si el XML no es una nómina válida.
            OSError: Si el archivo no existe.
        """
        if not os.path.exists(xml_path):
            raise OSError(f"Archivo no encontrado: {xml_path}")

        try:
            tree = safe_parse(xml_path)
        except etree.XMLSyntaxError as e:
            raise NominaCFDIProcessorError(f"XML mal formado: {e}") from e
        except ValueError as e:
            raise NominaCFDIProcessorError(str(e)) from e

        root = tree.getroot()

        if _localname(root) != "Comprobante":
            raise NominaCFDIProcessorError(
                f"{os.path.basename(xml_path)} no es un CFDI "
                "(root no es 'Comprobante')"
            )

        tipo = root.get("TipoDeComprobante", "")
        if tipo != "N":
            raise NominaCFDIProcessorError(
                f"TipoDeComprobante es '{tipo}', se esperaba 'N' (Nómina)"
            )

        # ---- Emisor ----
        emisor_node = _find_first(root, "Emisor")
        if emisor_node is None:
            raise NominaCFDIProcessorError("No se encontró nodo Emisor")

        emisor = NominaEmisorData(
            rfc=emisor_node.get("Rfc", ""),
            nombre=emisor_node.get("Nombre", ""),
            regimen_fiscal=emisor_node.get("RegimenFiscal", ""),
        )

        # ---- Receptor ----
        receptor_node = _find_first(root, "Receptor")
        if receptor_node is None:
            raise NominaCFDIProcessorError("No se encontró nodo Receptor")

        # ---- Complemento Nómina ----
        nomina_node = _find_first(root, "Nomina")
        if nomina_node is None:
            raise NominaCFDIProcessorError(
                "No se encontró complemento Nomina en el CFDI"
            )

        tipo_nomina = nomina_node.get("TipoNomina", "O")
        num_dias = int(nomina_node.get("NumDiasPagados", "0"))

        periodo = NominaPeriodo(
            fecha_pago=nomina_node.get("FechaPago", ""),
            fecha_inicial=nomina_node.get("FechaInicialPago", ""),
            fecha_final=nomina_node.get("FechaFinalPago", ""),
            num_dias_pagados=num_dias,
        )

        # ---- Receptor dentro del complemento nómina ----
        nomina_receptor = _find_first(nomina_node, "Receptor")
        if nomina_receptor is None:
            raise NominaCFDIProcessorError(
                "No se encontró nodo Receptor dentro del complemento Nómina"
            )

        salario_diario = _safe_dec(nomina_receptor.get("SalarioDiarioIntegrado"))
        sbc = _safe_dec(nomina_receptor.get("SalarioBaseCotizacion"))

        receptor = NominaReceptorData(
            rfc=receptor_node.get("Rfc", ""),
            nombre=receptor_node.get("Nombre", ""),
            curp=nomina_receptor.get("Curp", ""),
            num_seguridad_social=nomina_receptor.get("NumSeguridadSocial", ""),
            periodicidad_pago=nomina_receptor.get("PeriodicidadPago", "Mensual"),
            tipo_contrato=nomina_receptor.get("TipoContrato", "01"),
            tipo_jornada=nomina_receptor.get("TipoJornada", "01"),
            tipo_regimen=nomina_receptor.get("TipoRegimen", "02"),
            num_empleado=nomina_receptor.get("NumEmpleado", "1"),
            departamento=nomina_receptor.get("Departamento", ""),
            puesto=nomina_receptor.get("Puesto", ""),
            riesgo_puesto=nomina_receptor.get("RiesgoPuesto", "01"),
            salario_diario_integrado=salario_diario,
            salario_base_cotizacion=sbc,
        )

        # ---- Percepciones ----
        percepciones_node = _find_first(nomina_node, "Percepciones")
        percepciones: List[NominaPercepcion] = []
        if percepciones_node is not None:
            for perc_node in _find_all(percepciones_node, "Percepcion"):
                percepciones.append(NominaPercepcion(
                    tipo_percepcion=perc_node.get("TipoPercepcion", ""),
                    clave=perc_node.get("Clave", ""),
                    concepto=perc_node.get("Concepto", ""),
                    importe_gravado=_safe_dec(perc_node.get("ImporteGravado")),
                    importe_exento=_safe_dec(perc_node.get("ImporteExento")),
                ))

        # ---- Deducciones ----
        deducciones_node = _find_first(nomina_node, "Deducciones")
        deducciones: List[NominaDeduccion] = []
        if deducciones_node is not None:
            for ded_node in _find_all(deducciones_node, "Deduccion"):
                deducciones.append(NominaDeduccion(
                    tipo_deduccion=ded_node.get("TipoDeduccion", ""),
                    clave=ded_node.get("Clave", ""),
                    concepto=ded_node.get("Concepto", ""),
                    importe=_safe_dec(ded_node.get("Importe")),
                ))

        # ---- Otros pagos ----
        otros_pagos_node = _find_first(nomina_node, "OtrosPagos")
        otros_pagos: List[NominaOtroPago] = []
        if otros_pagos_node is not None:
            for op_node in _find_all(otros_pagos_node, "OtroPago"):
                subsidio = _safe_dec(op_node.get("SubsidioCausado"))
                op = NominaOtroPago(
                    tipo_otro_pago=op_node.get("TipoOtroPago", ""),
                    clave=op_node.get("Clave", ""),
                    concepto=op_node.get("Concepto", ""),
                    importe=_safe_dec(op_node.get("Importe")),
                )
                if subsidio > 0:
                    op.subsidio_causado = subsidio
                otros_pagos.append(op)

        # ---- Incapacidades ----
        incapacidades_node = _find_first(nomina_node, "Incapacidades")
        incapacidades: List[NominaIncapacidad] = []
        if incapacidades_node is not None:
            for inc_node in _find_all(incapacidades_node, "Incapacidad"):
                incapacidades.append(NominaIncapacidad(
                    tipo_incapacidad=inc_node.get("TipoIncapacidad", ""),
                    dias_incapacidad=int(
                        inc_node.get("DiasIncapacidad", "0")
                    ),
                    importe=_safe_dec(inc_node.get("ImporteMonetario")),
                    descripcion=inc_node.get("Descripcion", ""),
                ))

        # ---- Horas extra ----
        horas_extras_node = _find_first(nomina_node, "HorasExtras")
        horas_extras: List[NominaHoraExtra] = []
        if horas_extras_node is not None:
            for he_node in _find_all(horas_extras_node, "HorasExtra"):
                horas_extras.append(NominaHoraExtra(
                    dias=int(he_node.get("Dias", "0")),
                    tipo_horas=he_node.get("TipoHoras", "Dobles"),
                    horas_extra=int(he_node.get("HorasExtra", "0")),
                    importe_pagado=_safe_dec(he_node.get("ImportePagado")),
                ))

        # ---- Totales ----
        totales = NominaTotales(
            total_percepciones=_safe_dec(
                nomina_node.get("TotalPercepciones")
            ),
            total_deducciones=_safe_dec(
                nomina_node.get("TotalDeducciones")
            ),
            total_otros_pagos=_safe_dec(
                nomina_node.get("TotalOtrosPagos")
            ),
        )

        return NominaData(
            emisor=emisor,
            receptor=receptor,
            periodo=periodo,
            tipo_nomina=tipo_nomina,
            percepciones=percepciones,
            deducciones=deducciones,
            otros_pagos=otros_pagos,
            incapacidades=incapacidades,
            horas_extras=horas_extras,
            totales=totales,
        )

    # ------------------------------------------------------------------
    # Validación
    # ------------------------------------------------------------------

    @staticmethod
    def validate_nomina_data(data: NominaData) -> Dict[str, Any]:
        """Valida los datos de una nómina. Retorna {'valid', 'errors', 'warnings'}."""
        return data.validate()

    # ------------------------------------------------------------------
    # Generación de XML
    # ------------------------------------------------------------------

    @classmethod
    def generate_nomina_cfdi(
        cls,
        data: NominaData,
        serie: str = "N",
        folio: str = "1",
        lugar_expedicion: str = "06600",
        forma_pago: str = "99",
    ) -> str:
        """
        Genera el XML de un CFDI 4.0 de tipo nómina (sin timbrar).

        Args:
            data: Datos completos de la nómina.
            serie: Serie del CFDI (default "N").
            folio: Folio del CFDI (default "1").
            lugar_expedicion: Código postal del lugar de expedición.
            forma_pago: Clave FormaPago (default "99" = Por definir).

        Returns:
            String XML listo para timbrar (requiere e.firma / PAC).

        Raises:
            NominaCFDIProcessorError: Si la validación falla.
        """
        validation = cls.validate_nomina_data(data)
        if not validation["valid"]:
            raise NominaCFDIProcessorError(
                "Datos de nómina inválidos:\n  - "
                + "\n  - ".join(validation["errors"])
            )

        # ---- Calcular totales ----
        total_perc = sum(p.importe_gravado + p.importe_exento for p in data.percepciones)
        total_ded = sum(d.importe for d in data.deducciones)
        total_op = sum((op.importe for op in data.otros_pagos), Decimal("0"))

        total_perc_r = _round2(total_perc)
        total_ded_r = _round2(total_ded)
        total_op_r = _round2(total_op)

        total = _round2(total_perc_r - total_ded_r + total_op_r)
        subtotal = total_perc_r

        # ---- Construir XML con lxml ----
        # Registramos namespaces primero para que lxml los maneje correctamente
        etree.register_namespace("cfdi", NS["cfdi"])
        etree.register_namespace("nomina", NS["nomina"])
        etree.register_namespace("tfd", NS["tfd"])
        etree.register_namespace("xsi", NS["xsi"])

        CFDI = f"{{{NS['cfdi']}}}"
        NOM = f"{{{NS['nomina']}}}"
        TFD = f"{{{NS['tfd']}}}"
        XSI = f"{{{NS['xsi']}}}"

        comprobante = etree.Element(
            f"{CFDI}Comprobante",
            attrib={
                f"{XSI}schemaLocation": SCHEMA_LOCATIONS,
                "Version": "4.0",
                "Serie": serie,
                "Folio": str(folio),
                "Fecha": data.periodo.fecha_pago,
                "FormaPago": forma_pago,
                "MetodoPago": "PUE",
                "Moneda": "MXN",
                "TipoDeComprobante": "N",
                "Exportacion": "01",
                "LugarExpedicion": lugar_expedicion,
                "SubTotal": _fmt(subtotal),
                "Total": _fmt(total),
            },
        )

        # -- Emisor --
        em = etree.SubElement(
            comprobante, f"{CFDI}Emisor",
            attrib={
                "Rfc": data.emisor.rfc,
                "Nombre": data.emisor.nombre,
                "RegimenFiscal": data.emisor.regimen_fiscal,
            },
        )

        # -- Receptor --
        domicilio_fiscal = "06600"
        rc = etree.SubElement(
            comprobante, f"{CFDI}Receptor",
            attrib={
                "Rfc": data.receptor.rfc,
                "Nombre": data.receptor.nombre,
                "DomicilioFiscalReceptor": domicilio_fiscal,
                "RegimenFiscalReceptor": "605",  # Sueldos y salarios
                "UsoCFDI": "CN01",  # Nómina
            },
        )

        # -- Conceptos --
        conceptos = etree.SubElement(comprobante, f"{CFDI}Conceptos")
        etree.SubElement(
            conceptos, f"{CFDI}Concepto",
            attrib={
                "ClaveProdServ": "84111505",
                "Cantidad": "1",
                "ClaveUnidad": "ACT",
                "Unidad": "Actividad",
                "Descripcion": "Pago de nómina",
                "ValorUnitario": _fmt(subtotal),
                "Importe": _fmt(subtotal),
                "ObjetoImp": "01",
            },
        )

        # -- Complemento --
        complemento = etree.SubElement(comprobante, f"{CFDI}Complemento")

        nomina_attrs = {
            "Version": "1.2",
            "TipoNomina": data.tipo_nomina,
            "FechaPago": data.periodo.fecha_pago,
            "FechaInicialPago": data.periodo.fecha_inicial,
            "FechaFinalPago": data.periodo.fecha_final,
            "NumDiasPagados": str(data.periodo.num_dias_pagados),
            "TotalPercepciones": _fmt(total_perc_r),
            "TotalDeducciones": _fmt(total_ded_r),
            "TotalOtrosPagos": _fmt(total_op_r),
        }
        nomina = etree.SubElement(complemento, f"{NOM}Nomina", attrib=nomina_attrs)

        # Emisor dentro de complemento nómina
        emisor_attrs = {}
        if data.emisor.registro_patronal:
            emisor_attrs["RegistroPatronal"] = data.emisor.registro_patronal
        if (rfc_curp := getattr(data.emisor, 'rfc_curp', '')):
            emisor_attrs["RfcPatronOrigen"] = rfc_curp
        if emisor_attrs:
            etree.SubElement(nomina, f"{NOM}Emisor", attrib=emisor_attrs)

        # Receptor dentro de complemento nómina
        receptor_attrs = {
            "Curp": data.receptor.curp,
            "NumSeguridadSocial": data.receptor.num_seguridad_social,
            "PeriodicidadPago": data.receptor.periodicidad_pago,
            "TipoContrato": data.receptor.tipo_contrato,
            "TipoJornada": data.receptor.tipo_jornada,
            "TipoRegimen": data.receptor.tipo_regimen,
            "NumEmpleado": data.receptor.num_empleado,
        }
        if data.receptor.departamento:
            receptor_attrs["Departamento"] = data.receptor.departamento
        if data.receptor.puesto:
            receptor_attrs["Puesto"] = data.receptor.puesto
        if data.receptor.riesgo_puesto:
            receptor_attrs["RiesgoPuesto"] = data.receptor.riesgo_puesto
        if data.receptor.salario_diario_integrado is not None:
            receptor_attrs["SalarioDiarioIntegrado"] = _fmt(
                data.receptor.salario_diario_integrado
            )
        if data.receptor.salario_base_cotizacion is not None:
            receptor_attrs["SalarioBaseCotizacion"] = _fmt(
                data.receptor.salario_base_cotizacion
            )
        etree.SubElement(nomina, f"{NOM}Receptor", attrib=receptor_attrs)

        # -- Percepciones --
        if data.percepciones:
            total_gravado = sum(p.importe_gravado for p in data.percepciones)
            total_exento = sum(p.importe_exento for p in data.percepciones)
            perc_wrapper = etree.SubElement(
                nomina, f"{NOM}Percepciones",
                attrib={
                    "TotalSueldos": _fmt(
                        sum(
                            p.importe_gravado + p.importe_exento
                            for p in data.percepciones
                            if p.tipo_percepcion == "001"
                        )
                    ),
                    "TotalGravado": _fmt(_round2(total_gravado)),
                    "TotalExento": _fmt(_round2(total_exento)),
                },
            )
            for p in data.percepciones:
                etree.SubElement(
                    perc_wrapper, f"{NOM}Percepcion",
                    attrib={
                        "TipoPercepcion": p.tipo_percepcion,
                        "Clave": p.clave,
                        "Concepto": p.concepto,
                        "ImporteGravado": _fmt(p.importe_gravado),
                        "ImporteExento": _fmt(p.importe_exento),
                    },
                )

        # -- Deducciones --
        if data.deducciones:
            # Calcular subtotales por tipo
            total_isr = _round2(
                sum(d.importe for d in data.deducciones if d.tipo_deduccion == "002")
            )
            total_ss = _round2(
                sum(d.importe for d in data.deducciones if d.tipo_deduccion == "001")
            )
            total_otras = _round2(
                sum(
                    d.importe
                    for d in data.deducciones
                    if d.tipo_deduccion not in ("001", "002")
                )
            )

            ded_wrapper = etree.SubElement(
                nomina, f"{NOM}Deducciones",
                attrib={
                    "TotalOtrasDeducciones": _fmt(total_otras),
                    "TotalImpuestosRetenidos": _fmt(total_isr),
                },
            )
            if total_ss > 0:
                ded_wrapper.set("TotalSeguridadSocial", _fmt(total_ss))

            for d in data.deducciones:
                etree.SubElement(
                    ded_wrapper, f"{NOM}Deduccion",
                    attrib={
                        "TipoDeduccion": d.tipo_deduccion,
                        "Clave": d.clave,
                        "Concepto": d.concepto,
                        "Importe": _fmt(d.importe),
                    },
                )

        # -- Otros pagos --
        if data.otros_pagos:
            op_wrapper = etree.SubElement(nomina, f"{NOM}OtrosPagos")
            for op in data.otros_pagos:
                op_attrs = {
                    "TipoOtroPago": op.tipo_otro_pago,
                    "Clave": op.clave,
                    "Concepto": op.concepto,
                    "Importe": _fmt(op.importe),
                }
                if op.subsidio_causado is not None:
                    op_attrs["SubsidioCausado"] = _fmt(op.subsidio_causado)
                etree.SubElement(op_wrapper, f"{NOM}OtroPago", attrib=op_attrs)

        # -- Incapacidades --
        if data.incapacidades:
            inc_wrapper = etree.SubElement(nomina, f"{NOM}Incapacidades")
            for inc in data.incapacidades:
                etree.SubElement(
                    inc_wrapper, f"{NOM}Incapacidad",
                    attrib={
                        "TipoIncapacidad": inc.tipo_incapacidad,
                        "DiasIncapacidad": str(inc.dias_incapacidad),
                        "ImporteMonetario": _fmt(inc.importe),
                        "Descripcion": inc.descripcion or "Incapacidad",
                    },
                )

        # -- Horas extra --
        if data.horas_extras:
            he_wrapper = etree.SubElement(nomina, f"{NOM}HorasExtras")
            for he in data.horas_extras:
                etree.SubElement(
                    he_wrapper, f"{NOM}HorasExtra",
                    attrib={
                        "Dias": str(he.dias),
                        "TipoHoras": he.tipo_horas,
                        "HorasExtra": str(he.horas_extra),
                        "ImportePagado": _fmt(he.importe_pagado),
                    },
                )

        # -- Serializar --
        xml_bytes = etree.tostring(
            comprobante, xml_declaration=True, encoding="UTF-8", pretty_print=True
        )
        return xml_bytes.decode("UTF-8")

    # ------------------------------------------------------------------
    # Generación con timbre
    # ------------------------------------------------------------------

    @classmethod
    def generate_xml_with_timbre(
        cls,
        data: NominaData,
        timbre_data: Dict[str, str],
        serie: str = "N",
        folio: str = "1",
        lugar_expedicion: str = "06600",
    ) -> str:
        """
        Genera el XML completo con TimbreFiscalDigital (TFD) insertado.

        ``timbre_data`` debe contener:
            - uuid: UUID del timbre
            - fecha_timbrado: Fecha ISO de timbrado
            - sello_cfd: Sello del CFDI (certificado)
            - no_certificado: Número de certificado SAT
            - certificado: Certificado SAT (base64)
            - sello_sat: Sello digital del SAT
            - rfc_prov_certif: RFC del PAC (opcional)
            - leyenda: Leyenda (opcional)

        Returns:
            String XML completo con el TimbreFiscalDigital.
        """
        # Generar XML base (sin timbre)
        base_xml = cls.generate_nomina_cfdi(
            data, serie=serie, folio=folio, lugar_expedicion=lugar_expedicion
        )

        # Parsear y añadir el timbre
        root = etree.fromstring(base_xml.encode("UTF-8"), parser=safe_parser())

        # Encontrar el complemento
        complemento = _find_first(root, "Complemento")
        if complemento is None:
            raise NominaCFDIProcessorError(
                "No se encontró nodo Complemento en el XML generado"
            )

        # Construir TimbreFiscalDigital
        TFD = f"{{{NS['tfd']}}}"
        tfd_attrs = {
            "Version": "1.1",
            "UUID": timbre_data.get("uuid", ""),
            "FechaTimbrado": timbre_data.get("fecha_timbrado", ""),
            "SelloCFD": timbre_data.get("sello_cfd", ""),
            "NoCertificado": timbre_data.get("no_certificado", ""),
            "Certificado": timbre_data.get("certificado", ""),
            "SelloSAT": timbre_data.get("sello_sat", ""),
        }
        if rfc_prov := timbre_data.get("rfc_prov_certif"):
            tfd_attrs["RfcProvCertif"] = rfc_prov
        if leyenda := timbre_data.get("leyenda"):
            tfd_attrs["Leyenda"] = leyenda

        etree.SubElement(complemento, f"{TFD}TimbreFiscalDigital", attrib=tfd_attrs)

        # Serializar
        xml_bytes = etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", pretty_print=True
        )
        return xml_bytes.decode("UTF-8")

    # ------------------------------------------------------------------
    # Conveniencia: crear NominaData desde un dict
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NominaData:
        """Crea un NominaData desde un diccionario. Útil para tests/API."""
        emisor = NominaEmisorData(
            rfc=data.get("emisor", {}).get("rfc", ""),
            nombre=data.get("emisor", {}).get("nombre", ""),
            regimen_fiscal=data.get("emisor", {}).get("regimen_fiscal", "601"),
            registro_patronal=data.get("emisor", {}).get("registro_patronal", ""),
        )
        receptor = NominaReceptorData(
            rfc=data.get("receptor", {}).get("rfc", ""),
            nombre=data.get("receptor", {}).get("nombre", ""),
            curp=data.get("receptor", {}).get("curp", ""),
            num_seguridad_social=data.get("receptor", {}).get(
                "num_seguridad_social", ""
            ),
            periodicidad_pago=data.get("receptor", {}).get(
                "periodicidad_pago", "Mensual"
            ),
            tipo_contrato=data.get("receptor", {}).get("tipo_contrato", "01"),
            tipo_jornada=data.get("receptor", {}).get("tipo_jornada", "01"),
            tipo_regimen=data.get("receptor", {}).get("tipo_regimen", "02"),
            num_empleado=data.get("receptor", {}).get("num_empleado", "1"),
            departamento=data.get("receptor", {}).get("departamento", ""),
            puesto=data.get("receptor", {}).get("puesto", ""),
            riesgo_puesto=data.get("receptor", {}).get("riesgo_puesto", "01"),
            salario_diario_integrado=_safe_dec(
                data.get("receptor", {}).get("salario_diario_integrado")
            ),
            salario_base_cotizacion=_safe_dec(
                data.get("receptor", {}).get("salario_base_cotizacion")
            ),
        )
        periodo = NominaPeriodo(
            fecha_pago=data.get("periodo", {}).get("fecha_pago", ""),
            fecha_inicial=data.get("periodo", {}).get("fecha_inicial", ""),
            fecha_final=data.get("periodo", {}).get("fecha_final", ""),
            num_dias_pagados=data.get("periodo", {}).get("num_dias_pagados", 30),
        )

        percepciones = [
            NominaPercepcion(**p) for p in data.get("percepciones", [])
        ]
        deducciones = [
            NominaDeduccion(**d) for d in data.get("deducciones", [])
        ]
        otros_pagos = [
            NominaOtroPago(**o) for o in data.get("otros_pagos", [])
        ]
        incapacidades = [
            NominaIncapacidad(**i) for i in data.get("incapacidades", [])
        ]
        horas_extras = [
            NominaHoraExtra(**h) for h in data.get("horas_extras", [])
        ]

        return NominaData(
            emisor=emisor,
            receptor=receptor,
            periodo=periodo,
            tipo_nomina=data.get("tipo_nomina", "O"),
            percepciones=percepciones,
            deducciones=deducciones,
            otros_pagos=otros_pagos,
            incapacidades=incapacidades,
            horas_extras=horas_extras,
        )