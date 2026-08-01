# -*- coding: utf-8 -*-
"""
catalogs.py — Catálogos SAT relevantes para validación fiscal (CFDI 4.0).

Catálogos oficiales: c_UsoCFDI, c_FormaPago, c_MetodoPago, c_TipoDeComprobante,
c_RegimenFiscal, c_Impuesto, c_TipoFactor.

Nota: los catálogos del SAT cambian con frecuencia (Anexo 20/24). Estas tablas
cubren los códigos vigentes más comunes para validación básica; en producción
deben descargarse y versionarse automáticamente. Marcado como ? INFERIDO para
los códigos completos — se validan contra el documento oficial del SAT.
"""
from __future__ import annotations

# c_Impuesto
IMPUESTOS = {
    "001": "ISR",
    "002": "IVA",
    "003": "IEPS",
    "004": "ISH",
}

# c_TipoFactor
TIPOS_FACTOR = {"Tasa", "Cuota", "Exento"}

# c_TipoDeComprobante
TIPOS_COMPROBANTE = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "P": "Pago",
    "N": "Nomina",
}

# c_MetodoPago
METODOS_PAGO = {"PUE": "Pago en una sola exhibicion", "PPD": "Pago en parcialidades o diferido"}

# c_FormaPago (códigos más comunes; lista no exhaustiva)
FORMAS_PAGO = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electronica de fondos",
    "04": "Tarjeta de credito",
    "05": "Monedero electronico",
    "06": "Dinero electronico",
    "08": "Vales de despensa",
    "28": "Tarjeta de debito",
    "29": "Tarjeta de servicio",
    "99": "Por definir",
}

# c_UsoCFDI (códigos más comunes)
USOS_CFDI = {
    "G01": "Adquisicion de mercancias",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "G04": "Construcciones",
    "G05": "Mobiliario y equipo de oficina por inversiones",
    "G06": "Equipo de transporte",
    "G07": "Equipo de computo y accesorios",
    "G08": "Dientes, piezas, accesorios y aparatos de ajuste",
    "G09": "Otros bienes o servicios",
    "G10": "Cargos, arrendamientos y accesorios",
    "G11": "Mercancias no identificadas",
    "G12": "Servicios de instalacion, reparacion y mantenimiento",
    "G13": "Bienes no identificados",
    "G24": "Obligaciones garantizadas por hipoteca",
    "G25": "Por definir",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina",
    "I03": "Equipo de transporte",
    "I04": "Equipo de computo y accesorios",
    "I05": "Dientes, piezas, accesorios y aparatos de ajuste",
    "I06": "Otros bienes o servicios",
    "I07": "Bienes no identificados",
    "I08": "Mercancias no identificadas",
    "P01": "Por definir",
    "S01": "Sin obligaciones fiscales",
    "CP01": "Pagos",
    "CN01": "Nomina",
    "D01": "Honorarios medicos, dentales y gastos hospitalarios",
    "D02": "Gastos medicos por incapacidad o discapacidad",
    "D03": "Gastos funerales",
    "D04": "Donativos",
    "D05": "Intereses reales efectivamente pagados por creditos hipotecarios",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas por seguros de gastos medicos",
    "D08": "Gastos de transporte escolar obligatorio",
    "D09": "Depositos en cuentas para el ahorro",
    "D10": "Pagos por servicios educativos (colegiaturas)",
}

# c_RegimenFiscal (códigos más comunes)
REGIMENES_FISCALES = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Regimen de Enajenacion o Adquisicion de Bienes",
    "608": "Demas ingresos",
    "609": "Consolidacion",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en Mexico",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Fisicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Regimen de los ingresos por obtencion de premios",
    "616": "Sin obligaciones fiscales",
    "621": "Incorporacion Fiscal",
    "622": "Actividades Agricolas, Ganaderas, Silvicolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Regimen de las Actividades Empresariales con ingresos a traves de Plataformas Tecnologicas",
    "626": "Regimen Simplificado de Confianza",
    "628": "Hidrocarburos",
    "629": "De los Regimenes Fiscales Preferentes y de las Empresas Multinacionales",
    "630": "Enajenacion de acciones en bolsa de valores",
}

# Prefijos de ClaveProdServ que delatan categoría contable (para classifier).
# NOTA: nómina NO se detecta por ClaveProdServ (84111505 también se usa en
# honorarios/consultoría); se detecta por TipoDeComprobante=N en el classifier.
CP_CATEGORIAS = {
    "activo_fijo": ["432115", "432118", "432119", "441115", "431915",
                    "811216", "811217"],
    "gasto_operativo": ["811111", "811121", "811122", "811211",
                        "821015", "821021", "821115"],
    "inversion": ["811000", "821110", "811115"],
}


def is_valid_uso_cfdi(code):
    return code in USOS_CFDI


def is_valid_forma_pago(code):
    return code in FORMAS_PAGO


def is_valid_metodo_pago(code):
    return code in METODOS_PAGO


def is_valid_tipo_comprobante(code):
    return code in TIPOS_COMPROBANTE


def is_valid_regimen(code):
    return code in REGIMENES_FISCALES


def is_valid_impuesto(code):
    return code in IMPUESTOS


def describe_impuesto(code):
    return IMPUESTOS.get(code, code)
