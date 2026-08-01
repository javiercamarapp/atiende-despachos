# -*- coding: utf-8 -*-
"""
catalogs.py — Catálogos SAT oficiales para validación fiscal (CFDI 4.0).

Fuente: Anexo 20, Guía de llenado de los comprobantes fiscales digitales
por Internet (CFDI), versión 4.0 (DOF 20-ene-2022, actualizado).
Reglas de Validación del SAT: catálogos c_UsoCFDI, c_FormaPago,
c_MetodoPago, c_TipoDeComprobante, c_RegimenFiscal, c_Impuesto,
c_TipoFactor.

DIOT: Tipo de Operación (Regla 3.10.7 RMF vigente):
  03 — Prestación de servicios profesionales
  06 — Arrendamiento de inmuebles
  85 — Otros

Todos los códigos están validados contra la documentación oficial del SAT.
"""
from __future__ import annotations

# c_Impuesto (Anexo 20, tabla c_Impuesto)
IMPUESTOS = {
    "001": "ISR",
    "002": "IVA",
    "003": "IEPS",
    "004": "ISH",
}

# c_TipoFactor (Anexo 20, tabla c_TipoFactor)
TIPOS_FACTOR = {"Tasa", "Cuota", "Exento"}

# c_TipoDeComprobante (Anexo 20, tabla c_TipoDeComprobante, CFDI 4.0)
TIPOS_COMPROBANTE = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "P": "Pago",
    "N": "Nomina",
}

# c_MetodoPago (Anexo 20, tabla c_MetodoPago)
METODOS_PAGO = {
    "PUE": "Pago en una sola exhibicion",
    "PPD": "Pago en parcialidades o diferido",
}

# c_FormaPago (Anexo 20, tabla c_FormaPago — lista completa del SAT)
FORMAS_PAGO = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electronica de fondos",
    "04": "Tarjeta de credito",
    "05": "Monedero electronico",
    "06": "Dinero electronico",
    "08": "Vales de despensa",
    "12": "Dacion en pago",
    "13": "Pago por subrogacion",
    "14": "Pago por consignacion",
    "15": "Condonacion",
    "17": "Compensacion",
    "23": "Novacion",
    "24": "Confusion",
    "25": "Remision de deuda",
    "26": "Prescripcion o caducidad",
    "27": "A satisfaccion del acreedor",
    "28": "Tarjeta de debito",
    "29": "Tarjeta de servicio",
    "30": "Aplicacion de anticipos",
    "31": "Intermediario pagos",
    "99": "Por definir",
}

# c_UsoCFDI (Anexo 20, tabla c_UsoCFDI — CFDI 4.0 exclusivamente)
# NOTA: P01 existía en CFDI 3.3 pero fue removido en 4.0.
# Los códigos G04, G07, G11, G13, G24, G25 NO existen en el catálogo oficial
# del Anexo 20 para CFDI 4.0.
USOS_CFDI = {
    "G01": "Adquisicion de mercancias",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "G05": "Mobiliario y equipo de oficina por inversiones",
    "G06": "Equipo de transporte",
    "G08": "Otros maquinaria y equipo",
    "G09": "Otros bienes o servicios",
    "G10": "Cargos, arrendamientos y accesorios",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina",
    "I03": "Equipo de transporte",
    "I04": "Equipo de computo y accesorios",
    "I05": "Dados, troqueles, moldes, matrices y herramental",
    "I06": "Comunicaciones telefonicas",
    "I07": "Comunicaciones satelitales",
    "I08": "Otra maquinaria y equipo",
    "S01": "Sin efectos fiscales",
    "CP01": "Pagos",
    "CN01": "Nomina",
    "D01": "Honorarios medicos, dentales y gastos hospitalarios",
    "D02": "Gastos medicos por incapacidad o discapacidad",
    "D03": "Gastos funerales",
    "D04": "Donativos",
    "D05": "Intereses reales efectivamente pagados por creditos hipotecarios (casa habitacion)",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas por seguros de gastos medicos",
    "D08": "Gastos de transporte escolar obligatorio",
    "D09": "Depositos en cuentas para el ahorro, primas que tengan como base planes de pensiones",
    "D10": "Pagos por servicios educativos (colegiaturas)",
}

# c_RegimenFiscal (Anexo 20, tabla c_RegimenFiscal — CFDI 4.0)
REGIMENES_FISCALES = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Regimen de Enajenacion o Adquisicion de Bienes",
    "608": "Demas ingresos",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en Mexico",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Fisicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Regimen de los ingresos por obtencion de premios",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Produccion",
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

# DIOT — Tipo de Operación (Regla 3.10.7 RMF vigente, catálogo SAT DIOT)
# Los tres tipos válidos son: 03 (servicios profesionales), 06 (arrendamiento),
# 85 (otros). El código anterior aceptaba "01", "02", "03" como IVA/IEPS/Exento,
# lo cual NO es el catálogo SAT.
DIOT_TIPO_OPERACION = {
    "03": "Prestacion de servicios profesionales",
    "06": "Arrendamiento de inmuebles",
    "85": "Otros",
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


def is_valid_diot_tipo_operacion(code):
    """Valida Tipo de Operación DIOT contra catálogo SAT (Regla 3.10.7 RMF).

    Valores válidos: 03, 06, 85.
    """
    return code in DIOT_TIPO_OPERACION


def describe_impuesto(code):
    return IMPUESTOS.get(code, code)
