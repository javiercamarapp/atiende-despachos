# -*- coding: utf-8 -*-
"""
demo.py — Modo demo interactivo para presentaciones a clientes.

Procesa CFDI de ejemplo por el pipeline completo y genera un reporte HTML
visual con resumen, tabla y alertas de anomalías. Soporta flag ``--live``
para usar DeepSeek real (OpenRouter) en vez de MockLLM.

Uso:
    b2b-ai demo [--live] [--data CARPETA] [--output CARPETA]
"""
from __future__ import annotations

import os
import sys
import time
import uuid
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from b2b_ai.services.pipeline import process_file
from b2b_ai.services.classify import CATEGORIA_NOMBRE
from b2b_ai.tools.logger import logger
from b2b_ai.db.db import Database, DEFAULT_DB

# ---------------------------------------------------------------------------
# CFDI 4.0 Templates — 10 facturas realistas para la demo
# ---------------------------------------------------------------------------

def _xml_payment_complement(total: str, uuid_f: str, fecha: str) -> str:
    """CFDI de tipo P (complemento de pagos)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:pago20="http://www.sat.gob.mx/Pagos20"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="P" Folio="1" Fecha="{fecha}"
    FormaPago="03" MetodoPago="PPD" Moneda="MXN"
    TipoDeComprobante="P" Exportacion="01"
    LugarExpedicion="06600" SubTotal="0.00" Total="0.00">
    <cfdi:Emisor Rfc="PAG010101AAA" Nombre="SISTEMAS DE PAGO S.A. DE C.V." RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="JCCP840101HDA" Nombre="DESPACHO CONTABLE JAVIER C. S.C." DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="CP01"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT" Unidad="Actividad"
            Descripcion="Pago de factura" ValorUnitario="0.00" Importe="0.00" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <pago20:Pagos Version="2.0">
    <pago20:Pago FechaPago="{fecha}" FormaDePagoP="03" MonedaP="MXN" Monto="{total}">
            <pago20:DoctoRelacionado IdDocumento="{uuid_f}" Serie="D" Folio="1" MonedaDR="MXN"
                MetodoDePagoDR="PPD" NumParcialidad="1" ImpSaldoAnt="{total}" ImpPagado="{total}" ImpSaldoInsoluto="0.00"/>
        </pago20:Pago>
        </pago20:Pagos>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


def _base_xml(serie: str, folio: int, fecha: str, tipo: str, subtotal: str,
              iva: str, total: str, emisor_rfc: str, emisor_nombre: str,
              regimen_fiscal: str, uso_cfdi: str, descripcion: str,
              clave_prod_serv: str, uuid_val: str | None = None,
              metodo_pago: str = "PUE", forma_pago: str = "03",
              objeto_imp: str = "02", base_iva: str | None = None,
              exportacion: str = "01") -> str:
    """Genera un CFDI 4.0 base con TimbreFiscalDigital."""
    uuid_val = uuid_val or str(uuid.uuid4())
    base_iva = base_iva or subtotal
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="{serie}" Folio="{folio}"
    Fecha="{fecha}"
    FormaPago="{forma_pago}" MetodoPago="{metodo_pago}" Moneda="MXN"
    TipoDeComprobante="{tipo}" Exportacion="{exportacion}"
    LugarExpedicion="06600" SubTotal="{subtotal}" Total="{total}">
    <cfdi:Emisor Rfc="{emisor_rfc}" Nombre="{emisor_nombre}" RegimenFiscal="{regimen_fiscal}"/>
    <cfdi:Receptor Rfc="JCCP840101HDA" Nombre="DESPACHO CONTABLE JAVIER C. S.C."
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="{uso_cfdi}"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="{clave_prod_serv}" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="{descripcion}"
            ValorUnitario="{subtotal}" Importe="{subtotal}" ObjetoImp="{objeto_imp}">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="{base_iva}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="{iva}"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="{iva}">
        <cfdi:Traslados>
            <cfdi:Traslado Base="{base_iva}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="{iva}"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid_val}"
            FechaTimbrado="{fecha}" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


def _nomina_xml(serie: str, folio: int, fecha: str, total: str, subtotal: str,
                iva: str, emisor_rfc: str, emisor_nombre: str,
                empleado_nombre: str, curp: str, rfc_emp: str,
                num_empleado: str, percepciones: str, deducciones: str,
                dias_pagados: str, uuid_val: str | None = None) -> str:
    """Genera un CFDI 4.0 de nómina con complemento de nómina."""
    uuid_val = uuid_val or str(uuid.uuid4())
    fecha_fin = (datetime.strptime(fecha[:10], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    fecha_ini = (datetime.strptime(fecha_fin, "%Y-%m-%d") - timedelta(days=int(dias_pagados) - 1)).strftime("%Y-%m-%d")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:nomina12="http://www.sat.gob.mx/nomina12"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="{serie}" Folio="{folio}"
    Fecha="{fecha}"
    FormaPago="99" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="N" Exportacion="01"
    LugarExpedicion="06600" SubTotal="{subtotal}" Total="{total}">
    <cfdi:Emisor Rfc="{emisor_rfc}" Nombre="{emisor_nombre}" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="{rfc_emp}" Nombre="{empleado_nombre}"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="605" UsoCFDI="CN01"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="84111505" Cantidad="1"
            ClaveUnidad="ACT" Unidad="Actividad"
            Descripcion="Pago de nómina" ValorUnitario="{subtotal}" Importe="{subtotal}" ObjetoImp="01"/>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="{iva}">
        <cfdi:Traslados>
            <cfdi:Traslado Base="{subtotal}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="{iva}"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <nomina12:Nomina Version="1.2" TipoNomina="O" FechaPago="{fecha[:10]}"
            FechaInicialPago="{fecha_ini}" FechaFinalPago="{fecha_fin}"
            NumDiasPagados="{dias_pagados}"
            TotalPercepciones="{percepciones}" TotalDeducciones="{deducciones}">
            <nomina12:Emisor RegistroPatronal="Z-1234567-01" RfcPatronOrigen="{emisor_rfc}"/>
            <nomina12:Receptor Curp="{curp}" NumEmpleado="{num_empleado}"
                TipoJornada="01" RiesgoPuesto="2" PeriodicidadPago="04"/>
        </nomina12:Nomina>
        <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid_val}"
            FechaTimbrado="{fecha}" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


def _nota_credito_xml(serie: str, folio: int, fecha: str, subtotal: str,
                      iva: str, total: str, emisor_rfc: str, emisor_nombre: str,
                      descripcion: str, clave_prod_serv: str,
                      uuid_relacionado: str, uuid_val: str | None = None) -> str:
    """Genera un CFDI 4.0 de nota de crédito (TipoDeComprobante=E)."""
    uuid_val = uuid_val or str(uuid.uuid4())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="{serie}" Folio="{folio}"
    Fecha="{fecha}"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="E" Exportacion="01"
    LugarExpedicion="06600" SubTotal="0.00" Total="0.00">
    <cfdi:Emisor Rfc="{emisor_rfc}" Nombre="{emisor_nombre}" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="JCCP840101HDA" Nombre="DESPACHO CONTABLE JAVIER C. S.C."
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="D08"/>
    <cfdi:CfdiRelacionados TipoRelacion="04">
        <cfdi:CfdiRelacionado UUID="{uuid_relacionado}"/>
    </cfdi:CfdiRelacionados>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="{clave_prod_serv}" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="{descripcion}"
            ValorUnitario="{subtotal}" Importe="{subtotal}" ObjetoImp="02"
            Descuento="{subtotal}">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="0.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="0.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid_val}"
            FechaTimbrado="{fecha}" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


# Los 10 CFDI de ejemplo como dicts estructurados
CFDI_TEMPLATES: List[Dict[str, Any]] = [
    # 1. Gasto operativo — papelería
    {
        "id": "papeleria",
        "file": "gasto_papeleria.xml",
        "category": "gasto_operativo",
        "xml": _base_xml(
            serie="D", folio=100, fecha="2026-07-03T10:00:00",
            tipo="I",
            subtotal="1500.00", iva="240.00", total="1740.00",
            emisor_rfc="PAP850101JKL", emisor_nombre="PAPELERIA Y SUMINISTROS DEL CENTRO S.A. DE C.V.",
            regimen_fiscal="601", uso_cfdi="G03",
            descripcion="Papelería y artículos de oficina (hojas, folders, plumas, tinta para impresora)",
            clave_prod_serv="44122000",
        ),
    },
    # 2. Gasto operativo — hosting
    {
        "id": "hosting",
        "file": "gasto_hosting.xml",
        "category": "gasto_operativo",
        "xml": _base_xml(
            serie="D", folio=101, fecha="2026-07-05T11:30:00",
            tipo="I",
            subtotal="2200.00", iva="352.00", total="2552.00",
            emisor_rfc="HST890101MNA", emisor_nombre="HOSTING PROFESIONAL MEXICO S.A. DE C.V.",
            regimen_fiscal="601", uso_cfdi="G03",
            descripcion="Servicio de hosting cloud y dominio anual para la oficina",
            clave_prod_serv="81112100",
        ),
    },
    # 3. Gasto operativo — servicios profesionales
    {
        "id": "servicios_profesionales",
        "file": "gasto_servicios_profesionales.xml",
        "category": "gasto_operativo",
        "xml": _base_xml(
            serie="D", folio=102, fecha="2026-07-08T09:15:00",
            tipo="I",
            subtotal="8500.00", iva="1360.00", total="9860.00",
            emisor_rfc="CON880101XYZ", emisor_nombre="CONSULTORIA ESTRATEGICA INTEGRAL S.C.",
            regimen_fiscal="603", uso_cfdi="G03",
            descripcion="Servicios profesionales de consultoría fiscal y contable mensual",
            clave_prod_serv="80121600",
        ),
    },
    # 4. Nómina — empleado 1
    {
        "id": "nomina1",
        "file": "nomina_empleado1.xml",
        "category": "nomina",
        "xml": _nomina_xml(
            serie="N", folio=1, fecha="2026-07-15T08:00:00",
            total="25500.00", subtotal="25500.00", iva="0.00",
            emisor_rfc="JCCP840101HDA", emisor_nombre="DESPACHO CONTABLE JAVIER C. S.C.",
            empleado_nombre="MARIA GUADALUPE LOPEZ HERNANDEZ",
            curp="LOHG900101MMCPR01", rfc_emp="LOHG900101MNC",
            num_empleado="001", percepciones="28000.00", deducciones="2500.00",
            dias_pagados="30",
        ),
    },
    # 5. Nómina — empleado 2
    {
        "id": "nomina2",
        "file": "nomina_empleado2.xml",
        "category": "nomina",
        "xml": _nomina_xml(
            serie="N", folio=2, fecha="2026-07-15T08:00:00",
            total="18500.00", subtotal="18500.00", iva="0.00",
            emisor_rfc="JCCP840101HDA", emisor_nombre="DESPACHO CONTABLE JAVIER C. S.C.",
            empleado_nombre="JUAN CARLOS RAMIREZ MENDOZA",
            curp="RAMJ850101HDFNNC01", rfc_emp="RAMJ850101HDF",
            num_empleado="002", percepciones="20000.00", deducciones="1500.00",
            dias_pagados="30",
        ),
    },
    # 6. Nota de crédito 1
    {
        "id": "nota_credito1",
        "file": "nota_credito1.xml",
        "category": "gasto_operativo",
        "xml": _nota_credito_xml(
            serie="E", folio=1, fecha="2026-07-12T14:00:00",
            subtotal="500.00", iva="80.00", total="0.00",
            emisor_rfc="PAP850101JKL", emisor_nombre="PAPELERIA Y SUMINISTROS DEL CENTRO S.A. DE C.V.",
            descripcion="Descuento por devolución de mercancía (papelería en mal estado)",
            clave_prod_serv="44122000",
            uuid_relacionado="550e8400-e29b-41d4-a716-446655440000",  # reference UUID
        ),
    },
    # 7. Nota de crédito 2
    {
        "id": "nota_credito2",
        "file": "nota_credito2.xml",
        "category": "gasto_operativo",
        "xml": _nota_credito_xml(
            serie="E", folio=2, fecha="2026-07-18T11:00:00",
            subtotal="2200.00", iva="352.00", total="0.00",
            emisor_rfc="HST890101MNA", emisor_nombre="HOSTING PROFESIONAL MEXICO S.A. DE C.V.",
            descripcion="Ajuste por cambio de plan de hosting (diferencia a favor del cliente)",
            clave_prod_serv="81112100",
            uuid_relacionado="550e8400-e29b-41d4-a716-446655440001",
        ),
    },
    # 8. Activo fijo — equipo de cómputo
    {
        "id": "activo_fijo",
        "file": "activo_fijo_computo.xml",
        "category": "activo_fijo",
        "xml": _base_xml(
            serie="D", folio=103, fecha="2026-07-10T16:20:00",
            tipo="I",
            subtotal="35000.00", iva="5600.00", total="40600.00",
            emisor_rfc="COM940101QWE", emisor_nombre="COMPUTADORAS Y TECNOLOGIA DE MEXICO S.A. DE C.V.",
            regimen_fiscal="601", uso_cfdi="G03",
            descripcion="Equipo de cómputo: laptop Dell Latitude 5540 para uso administrativo",
            clave_prod_serv="43211500",
        ),
    },
    # 9. Factura cancelada (con Estatus = "Cancelado" en el TimbreFiscalDigital, o sin timbre)
    {
        "id": "cancelada",
        "file": "factura_cancelada.xml",
        "category": "gasto_operativo",
        "xml": f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
    Version="4.0" Serie="D" Folio="200"
    Fecha="2026-06-30T10:00:00"
    FormaPago="01" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="3000.00" Total="3480.00">
    <cfdi:Emisor Rfc="CAN990101AAA" Nombre="SERVICIOS CANCELADOS S.A. DE C.V." RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="JCCP840101HDA" Nombre="DESPACHO CONTABLE JAVIER C. S.C."
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="80121600" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Servicio cancelado (factura anulada por error en RFC)"
            ValorUnitario="3000.00" Importe="3000.00" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="3000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="480.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="480.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="3000.00" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="480.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1" UUID="cccccccc-1111-2222-3333-aaaaaaaaaaaa"
            FechaTimbrado="2026-06-30T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>""",
    },
    # 10. Monto inusual (anomalía — $980,000 para activo fijo)
    {
        "id": "monto_inusual",
        "file": "monto_inusual.xml",
        "category": "activo_fijo",
        "xml": _base_xml(
            serie="D", folio=104, fecha="2026-07-20T10:00:00",
            tipo="I",
            subtotal="980000.00", iva="156800.00", total="1136800.00",
            emisor_rfc="EQP990101RTY", emisor_nombre="MAQUINARIA PESADA Y EQUIPO INDUSTRIAL S.A. DE C.V.",
            regimen_fiscal="601", uso_cfdi="G03",
            descripcion="Maquinaria industrial: equipo de producción automatizado (línea completa)",
            clave_prod_serv="43191500",
        ),
    },
]


def ensure_output_dir(path: str) -> str:
    """Crea el directorio de salida si no existe."""
    os.makedirs(path, exist_ok=True)
    return path


def generate_sample_xmls(output_dir: str) -> List[str]:
    """Genera los 10 CFDI de ejemplo en output_dir. Devuelve paths."""
    ensure_output_dir(output_dir)
    paths = []
    for t in CFDI_TEMPLATES:
        filepath = os.path.join(output_dir, t["file"])
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(t["xml"])
        paths.append(filepath)
    return paths


def _fmt_monto(val: Any) -> str:
    """Formatea un monto a string con 2 decimales y $."""
    try:
        return f"${float(str(val).replace(',', '')):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _get_total(entry: dict) -> float:
    """Extrae el total como float desde el resultado del pipeline."""
    d = entry["datos"]
    try:
        total = d.get("total", 0)
        if total is None:
            return 0.0
        return float(str(total).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def generate_demo_report(results: List[Dict], output_dir: str,
                         elapsed: float) -> str:
    """Genera un HTML report visual a partir de los resultados del pipeline."""
    ensure_output_dir(output_dir)

    # Resumen
    total_facturas = len(results)
    monto_total = sum(_get_total(r) for r in results)
    iva_total = 0.0
    for r in results:
        d = r["datos"]
        try:
            iva_total += float(str(d.get("iva", 0)).replace(",", ""))
        except (TypeError, ValueError):
            pass

    # Conteo por categoría
    from collections import Counter
    cats = Counter(r["clasificacion"]["categoria"] for r in results if r.get("clasificacion"))
    cat_names = {k: CATEGORIA_NOMBRE.get(k, k) for k in cats}

    # Anomalías (el pipeline devuelve {'anomalies': [...]})
    def _get_anomalies(r):
        raw = r.get("anomalias") or {}
        if isinstance(raw, dict):
            return raw.get("anomalies") or []
        return raw if isinstance(raw, list) else []

    todas_anomalias = [r for r in results
                       if _get_anomalies(r)]

    # Tabla rows
    rows_html = ""
    for i, r in enumerate(results):
        d = r["datos"]
        cl = r.get("clasificacion", {}) or {}
        an = _get_anomalies(r)
        val = r.get("validacion", {}) or {}
        arch = r.get("archivo", "desconocido")
        emisor = d.get("emisor_nombre", d.get("emisor_rfc", "?"))
        fecha = str(d.get("fecha", "?"))[:10]
        total = _fmt_monto(d.get("total"))
        cat = CATEGORIA_NOMBRE.get(cl.get("categoria", ""), cl.get("categoria", "?"))
        confianza = cl.get("confianza", 0)

        has_anomaly = len(an) > 0
        max_sev = max((a.get("severity", "low") for a in an), key=lambda s: {
            "low": 0, "medium": 1, "high": 2, "critical": 3
        }.get(s, 0)) if an else None

        row_class = "anomaly-row" if has_anomaly else ""
        ok_badge = '<span class="badge badge-ok">OK</span>'
        badge = f'<span class="badge anomaly-high">{max_sev.upper()}</span>' if max_sev else ok_badge
        conf_class = "conf-low" if confianza < 0.7 else "conf-high"

        rows_html += f"""        <tr class="{row_class}">
            <td>{i + 1}</td>
            <td>{arch[:30]}</td>
            <td>{emisor[:25]}</td>
            <td>{fecha}</td>
            <td class="monto">{total}</td>
            <td><span class="{conf_class}">{cat}</span></td>
            <td>{badge}</td>
        </tr>"""

    # Tarjetas de anomalías
    anom_cards = ""
    for r in todas_anomalias:
        arch = r.get("archivo", "desconocido")
        for a in _get_anomalies(r):
            sev = a.get("severity", "low")
            sev_class = f"anomaly-{sev}"
            desc = a.get("descripcion", "Sin descripción")
            det = a.get("detalle", {})
            detalle_txt = "; ".join(f"{k}: {v}" for k, v in det.items())
            ref = a.get("referencia_legal", "")
            anom_cards += f"""    <div class="anomaly-card {sev_class}">
        <div class="anomaly-header">
            <span class="anomaly-type">{a.get('tipo', '?')}</span>
            <span class="anomaly-severity">{sev.upper()}</span>
        </div>
        <p class="anomaly-desc">{desc}</p>
        <p class="anomaly-detalle"><strong>Detalle:</strong> {detalle_txt}</p>
        <p class="anomaly-ref"><strong>Ref. Legal:</strong> {ref}</p>
        <p class="anomaly-file"><strong>Factura:</strong> {arch}</p>
    </div>"""

    # Gráfico de distribución por categoría (barras CSS puras)
    cat_bars = ""
    colors = {
        "gasto_operativo": "#4CAF50",
        "nomina": "#2196F3",
        "activo_fijo": "#FF9800",
        "inversion": "#9C27B0",
        "desconocido": "#607D8B",
    }
    max_cat_count = max(cats.values()) if cats else 1
    for cat_key in sorted(cats, key=lambda c: cats[c], reverse=True):
        count = cats[cat_key]
        pct = (count / max_cat_count) * 100
        color = colors.get(cat_key, "#888")
        name = cat_names.get(cat_key, cat_key)
        cat_bars += f"""    <div class="chart-row">
        <span class="chart-label">{name}</span>
        <div class="chart-bar-bg">
            <div class="chart-bar" style="width: {pct}%; background: {color};"></div>
        </div>
        <span class="chart-count">{count}</span>
    </div>"""

    tiempo_str = f"{elapsed:.2f}s" if elapsed < 60 else f"{elapsed / 60:.1f}min"
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Likida AI Enterprise — Demo Reporte CFDI</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
            background: #0f172a; color: #e2e8f0; padding: 2rem; line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{
            font-size: 2rem; font-weight: 700; margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #c084fc, #38bdf8);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .subtitle {{ color: #94a3b8; margin-bottom: 2rem; }}
        .stats-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem; margin-bottom: 2rem;
        }}
        .stat-card {{
            background: #1e293b; border: 1px solid #334155; border-radius: 12px;
            padding: 1.25rem;
        }}
        .stat-card h3 {{ font-size: 0.9rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
        .stat-card .value {{ font-size: 1.8rem; font-weight: 700; color: #38bdf8; margin-top: 0.25rem; }}
        .stat-card .value.green {{ color: #4ade80; }}
        .stat-card .value.amber {{ color: #fbbf24; }}
        .stat-card .value.rose {{ color: #fb7185; }}
        .section-title {{ font-size: 1.3rem; font-weight: 600; margin: 2rem 0 1rem; color: #f1f5f9; }}

        table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem; }}
        th, td {{ padding: 0.6rem 0.8rem; text-align: left; font-size: 0.9rem; }}
        th {{
            background: #1e293b; color: #94a3b8; font-weight: 600;
            border-bottom: 2px solid #334155; position: sticky; top: 0;
        }}
        td {{ border-bottom: 1px solid #1e293b; }}
        tr:hover td {{ background: rgba(56, 189, 248, 0.05); }}
        tr.anomaly-row td {{ background: rgba(251, 113, 133, 0.08); }}
        tr.anomaly-row:hover td {{ background: rgba(251, 113, 133, 0.15); }}
        .monto {{ font-family: 'SF Mono', monospace; text-align: right; }}
        .badge {{
            display: inline-block; padding: 0.15rem 0.5rem; border-radius: 9999px;
            font-size: 0.75rem; font-weight: 600;
        }}
        .badge-ok {{ background: rgba(74, 222, 128, 0.15); color: #4ade80; }}
        .badge.anomaly-high {{ background: rgba(251, 113, 133, 0.2); color: #fb7185; }}
        .badge.anomaly-medium {{ background: rgba(251, 191, 36, 0.2); color: #fbbf24; }}
        .badge.anomaly-low {{ background: rgba(148, 163, 184, 0.2); color: #94a3b8; }}
        .conf-low {{ color: #fbbf24; }}
        .conf-high {{ color: #4ade80; }}

        .chart {{ margin: 1rem 0 2rem; }}
        .chart-row {{
            display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;
        }}
        .chart-label {{ width: 140px; font-size: 0.85rem; text-align: right; color: #cbd5e1; }}
        .chart-bar-bg {{
            flex: 1; height: 24px; background: #1e293b; border-radius: 12px; overflow: hidden;
        }}
        .chart-bar {{ height: 100%; border-radius: 12px; transition: width 0.6s ease; min-width: 4px; }}
        .chart-count {{ width: 40px; font-size: 0.85rem; color: #94a3b8; }}

        .anomalies {{ margin: 1rem 0 2rem; }}
        .anomaly-card {{
            background: #1e293b; border-left: 4px solid; border-radius: 8px;
            padding: 1rem; margin-bottom: 0.75rem;
        }}
        .anomaly-card.anomaly-low {{ border-color: #94a3b8; }}
        .anomaly-card.anomaly-medium {{ border-color: #fbbf24; }}
        .anomaly-card.anomaly-high {{ border-color: #fb7185; }}
        .anomaly-card.anomaly-critical {{ border-color: #ef4444; }}
        .anomaly-header {{ display: flex; justify-content: space-between; margin-bottom: 0.5rem; }}
        .anomaly-type {{ font-weight: 600; color: #f1f5f9; text-transform: capitalize; }}
        .anomaly-severity {{
            font-size: 0.75rem; font-weight: 700; padding: 0.1rem 0.4rem;
            border-radius: 4px; text-transform: uppercase;
        }}
        .anomaly-low .anomaly-severity {{ background: rgba(148,163,184,0.2); color:#94a3b8; }}
        .anomaly-medium .anomaly-severity {{ background: rgba(251,191,36,0.2); color:#fbbf24; }}
        .anomaly-high .anomaly-severity {{ background: rgba(251,113,133,0.2); color:#fb7185; }}
        .anomaly-critical .anomaly-severity {{ background: rgba(239,68,68,0.2); color:#ef4444; }}
        .anomaly-desc {{ color: #cbd5e1; font-size: 0.9rem; }}
        .anomaly-detalle, .anomaly-ref, .anomaly-file {{ color: #94a3b8; font-size: 0.8rem; margin-top: 0.25rem; }}
        .footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #334155; color: #64748b; font-size: 0.85rem; text-align: center; }}
        .logo {{ font-size: 1.5rem; font-weight: 800; background: linear-gradient(135deg, #c084fc, #38bdf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Likida AI Enterprise <span style="font-weight:300;font-size:1.4rem;background:none;-webkit-text-fill-color:#94a3b8;">— Demo Procesamiento CFDI</span></h1>
        <p class="subtitle">Procesado el {hoy} &middot; Tiempo total: {tiempo_str}</p>

        <div class="stats-grid">
            <div class="stat-card">
                <h3>Facturas Procesadas</h3>
                <div class="value green">{total_facturas}</div>
            </div>
            <div class="stat-card">
                <h3>Monto Total</h3>
                <div class="value">{_fmt_monto(monto_total)}</div>
            </div>
            <div class="stat-card">
                <h3>IVA Total</h3>
                <div class="value amber">{_fmt_monto(iva_total)}</div>
            </div>
            <div class="stat-card">
                <h3>Anomalías Detectadas</h3>
                <div class="value rose">{len(todas_anomalias)}</div>
            </div>
        </div>

        <h2 class="section-title">📊 Distribución por Categoría</h2>
        <div class="chart">{cat_bars}</div>

        <h2 class="section-title">📋 Detalle de Facturas</h2>
        <div style="overflow-x:auto;">
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Archivo</th>
                    <th>Emisor</th>
                    <th>Fecha</th>
                    <th>Total</th>
                    <th>Categoría</th>
                    <th>Estado</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        </div>

        {f'''<h2 class="section-title">🚨 Anomalías Detectadas</h2>
        <div class="anomalies">{anom_cards}</div>''' if anom_cards else ''}

        <div class="footer">
            <p class="logo">Likida AI Enterprise</p>
            <p>Reporte generado automáticamente por el agente contable inteligente.</p>
            <p>Los resultados son informativos y no constituyen asesoría fiscal.</p>
        </div>
    </div>
</body>
</html>"""

    report_path = os.path.join(output_dir, "demo-report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return report_path


def run_demo(data_dir: str, output_dir: str, live: bool = False) -> int:
    """Ejecuta la demo completa: procesa CFDI y genera reporte.

    Returns:
        0 en éxito, 1 en error.
    """
    # Crear DB temporal para la demo
    db = Database(":memory:")

    if live:
        # Forzar uso de OpenRouterLLM en vez de MockLLM
        from b2b_ai.services.llm import OpenRouterLLM
        from b2b_ai.tools.registry import inject_tool
        llm = OpenRouterLLM()
        print("  🟢 Modo LIVE: usando DeepSeek real vía OpenRouter")
        print("  ⚡ Mostrando reasoning del LLM en tiempo real (streaming)...\n")
    else:
        print("  🟡 Modo DEMO: usando LLM simulado (MockLLM)")
        print("  💡 Usa --live para procesar con DeepSeek real\n")

    logger.set_db(db)

    # Asegurar directorios
    ensure_output_dir(data_dir)
    ensure_output_dir(output_dir)

    # Si no hay XMLs en data_dir, generar los de ejemplo
    xmls = sorted(
        os.path.join(data_dir, f)
        for f in os.listdir(data_dir)
        if f.endswith(".xml")
    )
    if not xmls:
        print("  📦 Generando CFDI de ejemplo...")
        xmls = generate_sample_xmls(data_dir)
        print(f"     {len(xmls)} archivos XML creados")

    total = len(xmls)
    print(f"\n  {'='*50}")
    print(f"  🔄 Procesando {total} CFDI(s)...")
    print(f"  {'='*50}\n")

    t_start = time.time()
    results = []

    for idx, xml_path in enumerate(xmls, 1):
        fname = os.path.basename(xml_path)
        print(f"  [{idx}/{total}] {fname}")

        # Barra de progreso simple (5 bloques = 100%)
        bar_len = 20
        progress = int(bar_len * idx / total)
        bar = "█" * progress + "░" * (bar_len - progress)
        print(f"     {bar} {int(100 * idx / total)}%")

        try:
            res = process_file(xml_path, db=db, logger_=logger)
            results.append(res)
            total_amt = float(str(res["datos"].get("total", 0)).replace(",", ""))
            cat = CATEGORIA_NOMBRE.get(
                res["clasificacion"].get("categoria", ""),
                res["clasificacion"].get("categoria", "?"),
            )
            anom_count = len(res.get("anomalias", []))
            anom_flag = f" ⚠️ {anom_count} anomalía(s)" if anom_count else ""
            print(f"     ✔ ${total_amt:,.2f} — {cat}{anom_flag}")
        except Exception as e:
            print(f"     ✖ Error: {e}")
            results.append({
                "archivo": fname,
                "datos": {"total": 0, "emisor_nombre": "ERROR", "emisor_rfc": "",
                          "fecha": "", "folio_fiscal": "", "iva": 0},
                "validacion": {"ok": False, "issues": [{"mensaje": str(e)}], "warnings": [],
                               "requires_human_review": True},
                "clasificacion": {"categoria": "desconocido", "confianza": 0.0, "razon": str(e)},
                "anomalias": [],
                "erp": {"poliza": None, "status": "error"},
                "aprobacion": {"decision": "error"},
                "notificacion": {"status": "error"},
            })

    elapsed = time.time() - t_start

    # Resumen
    print(f"\n  {'='*50}")
    print(f"  ✅ Procesamiento completado en {elapsed:.2f}s")
    ok = sum(1 for r in results if r.get("validacion", {}).get("ok"))
    print(f"  📊 {ok}/{total} facturas válidas")
    print(f"  🚨 {sum(1 for r in results if r.get('anomalias'))} con anomalías")
    print(f"  {'='*50}\n")

    # Generar reporte HTML
    print(f"  📄 Generando reporte HTML...")
    report_path = generate_demo_report(results, output_dir, elapsed)
    print(f"     Reporte: {report_path}")
    print(f"\n  {'='*50}")
    print(f"  🎉 Demo completada. Abre el reporte en tu navegador:")
    print(f"     file://{report_path}")
    print(f"  {'='*50}\n")

    db.close()
    return 0


def main(args):
    """Entry point para el subcomando demo."""
    # demo.py está en b2b_ai/services/ -> subir 3 niveles para enterprise/
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return run_demo(
        data_dir=args.data or os.path.join(root, "demo-data"),
        output_dir=args.output or os.path.join(root, "demo-output"),
        live=args.live,
    )