# -*- coding: utf-8 -*-
"""
mock_data.py — Realistic mock data for Likida AI Enterprise demo mode.

Provides Mexican CFDI data, invoices, analytics, and dashboard data
that mimic what the production system would return from real processing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Realistic Mexican company RFCs
# ---------------------------------------------------------------------------
_DEMO_COMPANIES: List[Dict[str, str]] = [
    {"rfc": "TEC050315AB2", "nombre": "Tecnología Avanzada SA de CV",
     "regimen": "601", "ciudad": "Ciudad de México"},
    {"rfc": "COS850101QR3", "nombre": "Constructora del Sur S de RL",
     "regimen": "601", "ciudad": "Guadalajara"},
    {"rfc": "MED120220TU4", "nombre": "Medicina Integral SC",
     "regimen": "601", "ciudad": "Monterrey"},
    {"rfc": "PLA970815HV5", "nombre": "Plásticos Industriales SA",
     "regimen": "601", "ciudad": "Puebla"},
    {"rfc": "LOG031205MN6", "nombre": "Logística del Norte SA de CV",
     "regimen": "601", "ciudad": "Querétaro"},
    {"rfc": "FIN180601VW7", "nombre": "Finanzas y Seguros SC",
     "regimen": "601", "ciudad": "Mérida"},
    {"agr": "AGD010101AAA", "nombre": "Agencia de Publicidad Global",
     "regimen": "601", "ciudad": "Cancún"},
    {"rfc": "ALI150430IK8", "nombre": "Alimentos del Bajío SA",
     "regimen": "601", "ciudad": "León"},
    {"rfc": "SER080321LP9", "nombre": "Servicios Profesionales Integrales",
     "regimen": "601", "ciudad": "Oaxaca"},
    {"rfc": "ENE200101QT0", "nombre": "Energías Renovables del Sur",
     "regimen": "601", "ciudad": "Tijuana"},
]

# ---------------------------------------------------------------------------
# Categories (match b2b_ai/services/classify.py)
# ---------------------------------------------------------------------------
_CATEGORIES = [
    ("G01", "Gastos en general"),
    ("G02", "Mobiliario y equipo de oficina"),
    ("G03", "Equipo de cómputo"),
    ("NOM", "Nómina"),
    ("SER", "Servicios profesionales"),
    ("RET", "Honorarios con retención"),
    ("CAP", "Inversión / capital"),
    ("FIN", "Servicios financieros"),
    ("COM", "Comunicaciones y marketing"),
    ("TRA", "Transporte y logística"),
    ("MED", "Gastos médicos"),
    ("COMB", "Combustibles"),
    ("DEP", "Depreciación"),
]

# ---------------------------------------------------------------------------
# Payment forms and methods
# ---------------------------------------------------------------------------
_FORMAS_PAGO = ["01", "03", "04", "28"]
METODOS_PAGO = ["PUE", "PPD"]

# ---------------------------------------------------------------------------
# CFDI sample data
# ---------------------------------------------------------------------------

def _gen_uuid() -> str:
    """Generate a mock CFDI fiscal UUID (folio fiscal)."""
    return str(uuid.uuid4()).upper()


def _random_amount(min_val: float, max_val: float) -> float:
    """Deterministic-ish amount based on company hash."""
    import random
    random.seed(int(min_val * 1000 + max_val * 100))
    return round(random.uniform(min_val, max_val), 2)


DEMO_CFDI_SAMPLES: List[Dict[str, Any]] = [
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-07-15T10:30:00",
        "serie": "A",
        "folio": "1042",
        "subtotal": "45000.00",
        "descuento": "0.00",
        "total": "52200.00",
        "moneda": "MXN",
        "metodo_pago": "PUE",
        "forma_pago": "01",
        "emisor_rfc": "TEC050315AB2",
        "emisor_nombre": "Tecnología Avanzada SA de CV",
        "emisor_regimen": "601",
        "receptor_rfc": "COS850101QR3",
        "receptor_nombre": "Constructora del Sur S de RL",
        "folio_fiscal": _gen_uuid(),
        "iva": "7200.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 3,
        "conceptos": [
            {"descripcion": "Servidor Dell PowerEdge R750", "importe": "35000.00", "clave_prod_serv": "43212300"},
            {"descripcion": "Licencia Windows Server 2025", "importe": "5000.00", "clave_prod_serv": "80101500"},
            {"descripcion": "Instalación y configuración", "importe": "5000.00", "clave_prod_serv": "81112200"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-07-18T14:15:00",
        "serie": "B",
        "folio": "2156",
        "subtotal": "12000.00",
        "descuento": "500.00",
        "total": "13320.00",
        "moneda": "MXN",
        "metodo_pago": "PPD",
        "forma_pago": "03",
        "emisor_rfc": "MED120220TU4",
        "emisor_nombre": "Medicina Integral SC",
        "emisor_regimen": "601",
        "receptor_rfc": "PLA970815HV5",
        "receptor_nombre": "Plásticos Industriales SA",
        "folio_fiscal": _gen_uuid(),
        "iva": "1820.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 2,
        "conceptos": [
            {"descripcion": "Consultoría médica ocupacional", "importe": "8000.00", "clave_prod_serv": "84101600"},
            {"descripcion": "Estudios de laboratorio", "importe": "4000.00", "clave_prod_serv": "82121500"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-07-22T09:00:00",
        "serie": "A",
        "folio": "3089",
        "subtotal": "28500.00",
        "descuento": "0.00",
        "total": "33060.00",
        "moneda": "MXN",
        "metodo_pago": "PUE",
        "forma_pago": "01",
        "emisor_rfc": "LOG031205MN6",
        "emisor_nombre": "Logística del Norte SA de CV",
        "emisor_regimen": "601",
        "receptor_rfc": "ENE200101QT0",
        "receptor_nombre": "Energías Renovables del Sur",
        "folio_fiscal": _gen_uuid(),
        "iva": "4560.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 1,
        "conceptos": [
            {"descripcion": "Flete internacional Contenedor 40'", "importe": "28500.00", "clave_prod_serv": "78101800"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-07-25T16:45:00",
        "serie": "C",
        "folio": "5001",
        "subtotal": "89000.00",
        "descuento": "2000.00",
        "total": "102280.00",
        "moneda": "MXN",
        "metodo_pago": "PPD",
        "forma_pago": "04",
        "emisor_rfc": "FIN180601VW7",
        "emisor_nombre": "Finanzas y Seguros SC",
        "emisor_regimen": "601",
        "receptor_rfc": "TEC050315AB2",
        "receptor_nombre": "Tecnología Avanzada SA de CV",
        "folio_fiscal": _gen_uuid(),
        "iva": "14080.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 4,
        "conceptos": [
            {"descripcion": "Prima de seguro anual", "importe": "50000.00", "clave_prod_serv": "85121400"},
            {"descripcion": "Consultoría financiera Q2", "importe": "20000.00", "clave_prod_serv": "82131500"},
            {"descripcion": "Auditoría de cumplimiento", "importe": "12000.00", "clave_prod_serv": "82111800"},
            {"descripcion": "Comisión por transferencia", "importe": "5000.00", "clave_prod_serv": "81161900"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Nómina",
        "fecha": "2026-07-31T08:00:00",
        "serie": "N",
        "folio": "107",
        "subtotal": "350000.00",
        "descuento": "0.00",
        "total": "350000.00",
        "moneda": "MXN",
        "metodo_pago": "PUE",
        "forma_pago": "01",
        "emisor_rfc": "COS850101QR3",
        "emisor_nombre": "Constructora del Sur S de RL",
        "emisor_regimen": "601",
        "receptor_rfc": "COS850101QR3",
        "receptor_nombre": "Constructora del Sur S de RL",
        "folio_fiscal": _gen_uuid(),
        "iva": "0.00",
        "tasa_iva": "0.000000",
        "conceptos_count": 1,
        "conceptos": [
            {"descripcion": "Nómina quincenal julio 2026", "importe": "350000.00", "clave_prod_serv": "83121500"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-08-01T11:20:00",
        "serie": "A",
        "folio": "6203",
        "subtotal": "15600.00",
        "descuento": "0.00",
        "total": "18096.00",
        "moneda": "MXN",
        "metodo_pago": "PUE",
        "forma_pago": "03",
        "emisor_rfc": "SER080321LP9",
        "emisor_nombre": "Servicios Profesionales Integrales",
        "emisor_regimen": "601",
        "receptor_rfc": "MED120220TU4",
        "receptor_nombre": "Medicina Integral SC",
        "folio_fiscal": _gen_uuid(),
        "iva": "2496.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 2,
        "conceptos": [
            {"descripcion": "Asesoría legal laboral", "importe": "10000.00", "clave_prod_serv": "82111500"},
            {"descripcion": "Elaboración contrato colectivo", "importe": "5600.00", "clave_prod_serv": "82111700"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-08-02T15:30:00",
        "serie": "B",
        "folio": "7044",
        "subtotal": "6200.00",
        "descuento": "0.00",
        "total": "7192.00",
        "moneda": "MXN",
        "metodo_pago": "PUE",
        "forma_pago": "01",
        "emisor_rfc": "PLA970815HV5",
        "emisor_nombre": "Plásticos Industriales SA",
        "emisor_regimen": "601",
        "receptor_rfc": "ALI150430IK8",
        "receptor_nombre": "Alimentos del Bajío SA",
        "folio_fiscal": _gen_uuid(),
        "iva": "992.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 3,
        "conceptos": [
            {"descripcion": "Envases plásticos 500ml x200", "importe": "2800.00", "clave_prod_serv": "34181500"},
            {"descripcion": "Etiquetas autoadhesivas", "importe": "1200.00", "clave_prod_serv": "34182100"},
            {"descripcion": "Tapones rosca", "importe": "2200.00", "clave_prod_serv": "34181900"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-08-03T08:45:00",
        "serie": "D",
        "folio": "801",
        "subtotal": "210000.00",
        "descuento": "5000.00",
        "total": "237100.00",
        "moneda": "MXN",
        "metodo_pago": "PPD",
        "forma_pago": "04",
        "emisor_rfc": "AGD010101AAA",
        "emisor_nombre": "Agencia de Publicidad Global",
        "emisor_regimen": "601",
        "receptor_rfc": "LOG031205MN6",
        "receptor_nombre": "Logística del Norte SA de CV",
        "folio_fiscal": _gen_uuid(),
        "iva": "32800.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 2,
        "conceptos": [
            {"descripcion": "Campaña digital Q3 2026", "importe": "150000.00", "clave_prod_serv": "82111600"},
            {"descripcion": "Producción audiovisual", "importe": "60000.00", "clave_prod_serv": "82111900"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-08-04T13:10:00",
        "serie": "A",
        "folio": "9102",
        "subtotal": "3200.00",
        "descuento": "0.00",
        "total": "3712.00",
        "moneda": "MXN",
        "metodo_pago": "PUE",
        "forma_pago": "01",
        "emisor_rfc": "ENE200101QT0",
        "emisor_nombre": "Energías Renovables del Sur",
        "emisor_regimen": "601",
        "receptor_rfc": "FIN180601VW7",
        "receptor_nombre": "Finanzas y Seguros SC",
        "folio_fiscal": _gen_uuid(),
        "iva": "512.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 1,
        "conceptos": [
            {"descripcion": "Mantenimiento paneles solares", "importe": "3200.00", "clave_prod_serv": "72101500"},
        ],
    },
    {
        "version": "4.0",
        "tipo": "Ingreso",
        "fecha": "2026-08-05T10:00:00",
        "serie": "E",
        "folio": "10050",
        "subtotal": "75000.00",
        "descuento": "3000.00",
        "total": "84480.00",
        "moneda": "MXN",
        "metodo_pago": "PPD",
        "forma_pago": "03",
        "emisor_rfc": "TEC050315AB2",
        "emisor_nombre": "Tecnología Avanzada SA de CV",
        "emisor_regimen": "601",
        "receptor_rfc": "AGD010101AAA",
        "receptor_nombre": "Agencia de Publicidad Global",
        "folio_fiscal": _gen_uuid(),
        "iva": "12480.00",
        "tasa_iva": "0.160000",
        "conceptos_count": 3,
        "conceptos": [
            {"descripcion": "Infraestructura cloud AWS", "importe": "40000.00", "clave_prod_serv": "82121600"},
            {"descripcion": "Soporte técnico 24/7", "importe": "20000.00", "clave_prod_serv": "82121700"},
            {"descripcion": "Capacitación equipo técnico", "importe": "15000.00", "clave_prod_serv": "82112100"},
        ],
    },
]


def _build_demo_invoices() -> List[Dict[str, Any]]:
    """Build a list of demo invoice records for the /invoices endpoint."""
    invoices = []
    for i, sample in enumerate(DEMO_CFDI_SAMPLES):
        invoices.append({
            "id": i + 1,
            "tenant_id": 1,
            "folio_fiscal": sample["folio_fiscal"],
            "emisor_rfc": sample["emisor_rfc"],
            "emisor_nombre": sample["emisor_nombre"],
            "receptor_rfc": sample["receptor_rfc"],
            "total": sample["total"],
            "moneda": sample["moneda"],
            "fecha": sample["fecha"],
            "tipo": sample["tipo"],
            "metodo_pago": sample["metodo_pago"],
            "categoria": _CATEGORIES[i % len(_CATEGORIES)][0],
            "confianza": round(0.85 + (i % 15) * 0.01, 2),
            "status": "procesado",
        })
    return invoices


DEMO_INVOICES = _build_demo_invoices()


# ---------------------------------------------------------------------------
# Stats (mirror generate_report output)
# ---------------------------------------------------------------------------
DEMO_STATS: Dict[str, Any] = {
    "invoices_total": len(DEMO_INVOICES),
    "tenants": [{"id": 1, "name": "Demo Corp SA de CV", "active": True}],
    "audit_calls": 42,
    "notifications": 7,
    "report": {
        "total_facturas": len(DEMO_INVOICES),
        "monto_total": sum(float(inv["total"]) for inv in DEMO_INVOICES),
        "iva_total": sum(
            float(DEMO_CFDI_SAMPLES[i].get("iva", "0"))
            for i in range(len(DEMO_CFDI_SAMPLES))
        ),
        "por_categoria": {
            "Gastos en general": 3,
            "Servicios profesionales": 3,
            "Comunicaciones y marketing": 1,
            "Transporte y logística": 1,
            "Nómina": 1,
            "Gastos médicos": 1,
        },
        "por_tipo": {
            "Ingreso": 9,
            "Nómina": 1,
        },
        "por_mes": {
            "2026-07": 5,
            "2026-08": 5,
        },
    },
    "tools_registered": [
        "process", "classify", "anomaly_detection", "batch",
        "reports", "billing", "notifications",
    ],
}


# ---------------------------------------------------------------------------
# Analytics (mirror build_analytics output)
# ---------------------------------------------------------------------------
DEMO_ANALYTICS: Dict[str, Any] = {
    "periodo": "2026-Q3",
    "resumen": {
        "total_facturas": len(DEMO_INVOICES),
        "monto_total": sum(float(inv["total"]) for inv in DEMO_INVOICES),
        "crecimiento_mensual": "+12.5%",
        "top_proveedor": "Tecnología Avanzada SA de CV",
        "top_categoria": "Servicios profesionales",
    },
    "tendencia_mensual": [
        {"mes": "2026-05", "monto": 180000, "facturas": 8},
        {"mes": "2026-06", "monto": 215000, "facturas": 12},
        {"mes": "2026-07", "monto": 237000, "facturas": 15},
        {"mes": "2026-08", "monto": 195000, "facturas": 10},
    ],
    "top_emisores": [
        {"rfc": "TEC050315AB2", "nombre": "Tecnología Avanzada SA de CV",
         "facturas": 3, "monto_total": 356500},
        {"rfc": "COS850101QR3", "nombre": "Constructora del Sur S de RL",
         "facturas": 2, "monto_total": 363320},
        {"rfc": "FIN180601VW7", "nombre": "Finanzas y Seguros SC",
         "facturas": 1, "monto_total": 102280},
    ],
    "distribucion_cats": [
        {"categoria": "Servicios profesionales", "count": 3, "monto": 89200},
        {"categoria": "Gastos en general", "count": 3, "monto": 123400},
        {"categoria": "Transporte y logística", "count": 2, "monto": 62500},
        {"categoria": "Comunicaciones y marketing", "count": 1, "monto": 210000},
        {"categoria": "Nómina", "count": 1, "monto": 350000},
    ],
    "anomalias_detectadas": 2,
    "anomalias": [
        {
            "tipo": "monto_atipico",
            "factura_id": 4,
            "monto": 102280.00,
            "descripcion": "Factura con monto 3.2x por encima del promedio del emisor",
            "severidad": "media",
        },
        {
            "tipo": "duplicado_potencial",
            "factura_id": 1,
            "descripcion": "Folio fiscal posible duplicado detectado",
            "severidad": "baja",
        },
    ],
}


# ---------------------------------------------------------------------------
# Dashboard summary (mirror /dashboard/summary and /dashboard/kpi)
# ---------------------------------------------------------------------------
DEMO_DASHBOARD_SUMMARY: Dict[str, Any] = {
    "kpis": {
        "facturas_hoy": 12,
        "facturas_mes": 147,
        "monto_mes": 2_450_000.00,
        "iva_mes": 392_000.00,
        "anomalias_pendientes": 2,
        "tasa_procesamiento": "98.5%",
        "tiempo_respuesta_avg_ms": 340,
    },
    "top_categories": [
        {"nombre": "Servicios profesionales", "count": 45, "monto": 890_000},
        {"nombre": "Gastos en general", "count": 38, "monto": 720_000},
        {"nombre": "Comunicaciones y marketing", "count": 22, "monto": 410_000},
        {"nombre": "Transporte y logística", "count": 18, "monto": 280_000},
        {"nombre": "Nómina", "count": 12, "monto": 650_000},
    ],
    "monthly_trend": [
        {"mes": "2026-03", "facturas": 98, "monto": 1_650_000},
        {"mes": "2026-04", "facturas": 112, "monto": 1_890_000},
        {"mes": "2026-05", "facturas": 125, "monto": 2_100_000},
        {"mes": "2026-06", "facturas": 135, "monto": 2_280_000},
        {"mes": "2026-07", "facturas": 142, "monto": 2_390_000},
        {"mes": "2026-08", "facturas": 147, "monto": 2_450_000},
    ],
    "recent_anomalies": [
        {
            "id": 1,
            "tipo": "monto_atipico",
            "emisor": "Finanzas y Seguros SC",
            "monto": 102_280.00,
            "fecha": "2026-07-25",
            "severidad": "media",
            "status": "pendiente",
        },
        {
            "id": 2,
            "tipo": "duplicado_potencial",
            "emisor": "Tecnología Avanzada SA de CV",
            "monto": 52_200.00,
            "fecha": "2026-07-15",
            "severidad": "baja",
            "status": "revisado",
        },
    ],
}


# ---------------------------------------------------------------------------
# Process result (what /process returns for a single CFDI)
# ---------------------------------------------------------------------------
def demo_process_result(sample_index: int = 0) -> Dict[str, Any]:
    """Return a realistic process result for a single CFDI."""
    sample = DEMO_CFDI_SAMPLES[sample_index % len(DEMO_CFDI_SAMPLES)]
    return {
        "id": str(uuid.uuid4())[:8],
        "archivo": f"demo_{sample['folio']}.xml",
        "datos": {
            "version": sample["version"],
            "tipo": sample["tipo"],
            "fecha": sample["fecha"],
            "serie": sample["serie"],
            "folio": sample["folio"],
            "subtotal": sample["subtotal"],
            "descuento": sample["descuento"],
            "total": sample["total"],
            "moneda": sample["moneda"],
            "metodo_pago": sample["metodo_pago"],
            "forma_pago": sample["forma_pago"],
            "emisor_rfc": sample["emisor_rfc"],
            "emisor_nombre": sample["emisor_nombre"],
            "emisor_regimen": sample["emisor_regimen"],
            "receptor_rfc": sample["receptor_rfc"],
            "receptor_nombre": sample["receptor_nombre"],
            "folio_fiscal": sample["folio_fiscal"],
            "iva": sample["iva"],
            "tasa_iva": sample["tasa_iva"],
            "conceptos_count": sample["conceptos_count"],
            "conceptos": sample["conceptos"],
        },
        "clasificacion": {
            "categoria": _CATEGORIES[sample_index % len(_CATEGORIES)][0],
            "nombre": _CATEGORIES[sample_index % len(_CATEGORIES)][1],
            "confianza": round(0.88 + (sample_index % 10) * 0.01, 2),
            "metodo": "reglas + LLM",
        },
        "anomalias": (
            [{"tipo": "monto_atipico", "severidad": "media",
              "descripcion": "Monto 3.2x por encima del promedio"}]
            if sample_index == 3 else []
        ),
        "anomalias_summary": {
            "total": 1 if sample_index == 3 else 0,
            "por_severidad": {"alta": 0, "media": 1, "baja": 0} if sample_index == 3 else {},
        },
        "timestamp": datetime.now().isoformat(),
    }
