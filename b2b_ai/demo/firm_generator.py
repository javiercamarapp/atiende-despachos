# -*- coding: utf-8 -*-
"""
firm_generator.py — Generador de datos realistas para firma contable demo.

Genera un escenario completo de una firma contable ficticia con:
  - 50 clientes (empresas mexicanas realistas)
  - ~500 CFDIs/mes distribuidos entre los clientes
  - Ingresos, gastos, nómina, notas de crédito, activos fijos
  - Anomalías realistas para demostrar detección
  - KPIs de ROI y métricas de negocio

Uso:
    from b2b_ai.demo.firm_generator import generate_demo_firm
    firm = generate_demo_firm()
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Nombres y RFCs realistas de clientes de una firma contable
# ---------------------------------------------------------------------------

_CLIENT_SEEDS: List[Dict[str, Any]] = [
    # Grandes empresas
    {"nombre": "Grupo Industrial del Bajío SA de CV", "rfc": "GIB850101AB3", "regimen": "601", "ciudad": "León", "giro": "manufactura", "tamano": "grande", "facturas_mes": 25, "ticket_prom": 85000},
    {"nombre": "Constructora y Desarrolladora Norte S de RL", "rfc": "CDN920215QR7", "regimen": "601", "ciudad": "Monterrey", "giro": "construccion", "tamano": "grande", "facturas_mes": 30, "ticket_prom": 120000},
    {"nombre": "Comercializadora de Alimentos del Centro SA", "rfc": "CAC030320TK9", "regimen": "601", "ciudad": "Puebla", "giro": "alimentos", "tamano": "grande", "facturas_mes": 40, "ticket_prom": 45000},
    {"nombre": "Transportes y Logística Express SA de CV", "rfc": "TLE780101MN4", "regimen": "601", "ciudad": "Guadalajara", "giro": "transporte", "tamano": "grande", "facturas_mes": 35, "ticket_prom": 32000},
    {"nombre": "Inmobiliaria Los Pinos SC", "rfc": "ILP060410HV2", "regimen": "601", "ciudad": "Querétaro", "giro": "inmobiliaria", "tamano": "grande", "facturas_mes": 20, "ticket_prom": 250000},
    # Medianas empresas
    {"nombre": "Servicios Tecnológicos Avanzados S de RL", "rfc": "STA110205AB8", "regimen": "601", "ciudad": "CDMX", "giro": "tecnologia", "tamano": "mediana", "facturas_mes": 15, "ticket_prom": 28000},
    {"nombre": "Clínica Integral de Salud SC", "rfc": "CIS090115QR3", "regimen": "601", "ciudad": "Mérida", "giro": "salud", "tamano": "mediana", "facturas_mes": 12, "ticket_prom": 18000},
    {"nombre": "Agencia de Marketing Digital Global SC", "rfc": "AMG150620TK6", "regimen": "601", "ciudad": "CDMX", "giro": "marketing", "tamano": "mediana", "facturas_mes": 10, "ticket_prom": 15000},
    {"nombre": "Distribuidora de Bebidas del Sur SA", "rfc": "DBS880410MN1", "regimen": "601", "ciudad": "Oaxaca", "giro": "distribucion", "tamano": "mediana", "facturas_mes": 18, "ticket_prom": 22000},
    {"nombre": "Estudio Jurídico Asociados SC", "rfc": "EJA050120AB5", "regimen": "603", "ciudad": "CDMX", "giro": "legal", "tamano": "mediana", "facturas_mes": 8, "ticket_prom": 35000},
    {"nombre": "Ferretería Industrial del Norte SA de CV", "rfc": "FIN760101QR4", "regimen": "601", "ciudad": "Chihuahua", "giro": "comercio", "tamano": "mediana", "facturas_mes": 20, "ticket_prom": 12000},
    {"nombre": "Grupo de Arquitectos Modernos SC", "rfc": "GAM120301HV7", "regimen": "603", "ciudad": "Cancún", "giro": "arquitectura", "tamano": "mediana", "facturas_mes": 6, "ticket_prom": 80000},
    {"nombre": "Laboratorio de Análisis Clínicos SA", "rfc": "LAC010101TK2", "regimen": "601", "ciudad": "Veracruz", "giro": "salud", "tamano": "mediana", "facturas_mes": 15, "ticket_prom": 9500},
    {"nombre": "Papelería y Suministros Corporativos SC", "rfc": "PSC980101MN8", "regimen": "601", "ciudad": "Toluca", "giro": "comercio", "tamano": "mediana", "facturas_mes": 12, "ticket_prom": 8500},
    {"nombre": "Consultoría Financiera Integral SA de CV", "rfc": "CFI070101AB6", "regimen": "601", "ciudad": "CDMX", "giro": "finanzas", "tamano": "mediana", "facturas_mes": 10, "ticket_prom": 45000},
    # Pequeñas empresas
    {"nombre": "Cafetería Artesanal El Grano SC", "rfc": "CAG140101QR5", "regimen": "601", "ciudad": "Oaxaca", "giro": "alimentos", "tamano": "pequena", "facturas_mes": 8, "ticket_prom": 3500},
    {"nombre": "Taller Mecánico Los Hermanos SC", "rfc": "TMH080101HV3", "regimen": "601", "ciudad": "Puebla", "giro": "servicios", "tamano": "pequena", "facturas_mes": 6, "ticket_prom": 5000},
    {"nombre": "Tienda de Electrónica Digital SC", "rfc": "TED160101TK1", "regimen": "601", "ciudad": "CDMX", "giro": "comercio", "tamano": "pequena", "facturas_mes": 10, "ticket_prom": 7500},
    {"nombre": "Veterinaria PetCare SC", "rfc": "VPC100101MN6", "regimen": "601", "ciudad": "Guadalajara", "giro": "salud", "tamano": "pequena", "facturas_mes": 5, "ticket_prom": 2800},
    {"nombre": "Floristería Primavera SC", "rfc": "FPR050101AB9", "regimen": "601", "ciudad": "Morelia", "giro": "comercio", "tamano": "pequena", "facturas_mes": 4, "ticket_prom": 4200},
    {"nombre": "Gimnasio Fitness Plus SC", "rfc": "GFP130101QR8", "regimen": "601", "ciudad": "León", "giro": "servicios", "tamano": "pequena", "facturas_mes": 6, "ticket_prom": 3800},
    {"nombre": "Librería El Saber SC", "rfc": "LES020101HV4", "regimen": "601", "ciudad": "Oaxaca", "giro": "comercio", "tamano": "pequena", "facturas_mes": 7, "ticket_prom": 5500},
    {"nombre": "Restaurant La Casona SC", "rfc": "RLC070101TK5", "regimen": "601", "ciudad": "CDMX", "giro": "alimentos", "tamano": "pequena", "facturas_mes": 9, "ticket_prom": 4800},
    {"nombre": "Estudio Fotográfico Lumière SC", "rfc": "EFL110101MN2", "regimen": "601", "ciudad": "Guadalajara", "giro": "servicios", "tamano": "pequena", "facturas_mes": 4, "ticket_prom": 6200},
    {"nombre": "Jardín de Niños Estrellitas SC", "rfc": "JNE040101AB7", "regimen": "601", "ciudad": "Puebla", "giro": "educacion", "tamano": "pequena", "facturas_mes": 5, "ticket_prom": 3200},
    {"nombre": "Peluquería Glamour SC", "rfc": "PGL150101QR6", "regimen": "601", "ciudad": "Monterrey", "giro": "servicios", "tamano": "pequena", "facturas_mes": 6, "ticket_prom": 2500},
    {"nombre": "Taller de Joyería Artesanal SC", "rfc": "TJA090101HV1", "regimen": "601", "ciudad": "Taxco", "giro": "manufactura", "tamano": "pequena", "facturas_mes": 5, "ticket_prom": 8000},
    # Más medianas
    {"nombre": "Empresa de Seguridad Privada Vigilante SC", "rfc": "ESP060101MN3", "regimen": "601", "ciudad": "CDMX", "giro": "servicios", "tamano": "mediana", "facturas_mes": 14, "ticket_prom": 11000},
    {"nombre": "Grupo Hotelero Paraíso SA de CV", "rfc": "GHP080101AB4", "regimen": "601", "ciudad": "Cancún", "giro": "hoteleria", "tamano": "mediana", "facturas_mes": 22, "ticket_prom": 28000},
    {"nombre": "Imprenta Digital Alta Calidad SC", "rfc": "IDQ120101TK3", "regimen": "601", "ciudad": "CDMX", "giro": "manufactura", "tamano": "pequena", "facturas_mes": 8, "ticket_prom": 6800},
    {"nombre": "Ingeniería y Diseño Industrial SC", "rfc": "IDI100101QR2", "regimen": "603", "ciudad": "Monterrey", "giro": "ingenieria", "tamano": "mediana", "facturas_mes": 10, "ticket_prom": 42000},
    {"nombre": "Laboratorio Farmacéutico BioGen SA", "rfc": "LFB040101HV6", "regimen": "601", "ciudad": "CDMX", "giro": "salud", "tamano": "grande", "facturas_mes": 28, "ticket_prom": 55000},
    {"nombre": "Mueblería Moderna del Centro SC", "rfc": "MMC070101MN5", "regimen": "601", "ciudad": "Puebla", "giro": "comercio", "tamano": "mediana", "facturas_mes": 12, "ticket_prom": 16000},
    {"nombre": "Notaría Pública García y Asociados", "rfc": "NPG110101AB1", "regimen": "603", "ciudad": "CDMX", "giro": "legal", "tamano": "pequena", "facturas_mes": 4, "ticket_prom": 25000},
    {"nombre": "Operadora de Eventos Fiesta SC", "rfc": "OEF140101TK4", "regimen": "601", "ciudad": "Guadalajara", "giro": "servicios", "tamano": "pequena", "facturas_mes": 7, "ticket_prom": 12000},
    {"nombre": "Panadería Artesanal El Horno SC", "rfc": "PAE030101QR1", "regimen": "601", "ciudad": "Oaxaca", "giro": "alimentos", "tamano": "pequena", "facturas_mes": 6, "ticket_prom": 3000},
    {"nombre": "Revista Digital Visión SC", "rfc": "RDV160101HV5", "regimen": "601", "ciudad": "CDMX", "giro": "medios", "tamano": "pequena", "facturas_mes": 5, "ticket_prom": 9500},
    {"nombre": "Sistema de Riego Automatizado SA", "rfc": "SRA090101MN4", "regimen": "601", "ciudad": "Hermosillo", "giro": "tecnologia", "tamano": "mediana", "facturas_mes": 8, "ticket_prom": 18000},
    {"nombre": "Tienda Natural Orgánicos SC", "rfc": "TNO150101AB2", "regimen": "601", "ciudad": "CDMX", "giro": "comercio", "tamano": "pequena", "facturas_mes": 7, "ticket_prom": 4500},
    {"nombre": "Uniformes y Vestimenta Laboral SA", "rfc": "UVL080101TK7", "regimen": "601", "ciudad": "Monterrey", "giro": "manufactura", "tamano": "mediana", "facturas_mes": 10, "ticket_prom": 14000},
    # Más pequeñas
    {"nombre": "Xerigrafía Express SC", "rfc": "XES130101QR9", "regimen": "601", "ciudad": "CDMX", "giro": "servicios", "tamano": "pequena", "facturas_mes": 5, "ticket_prom": 2200},
    {"nombre": "Yogurtería Frozen Delight SC", "rfc": "YFD170101HV8", "regimen": "601", "ciudad": "Guadalajara", "giro": "alimentos", "tamano": "pequena", "facturas_mes": 4, "ticket_prom": 3100},
    {"nombre": "Zapatería El Paso SC", "rfc": "ZEP060101MN7", "regimen": "601", "ciudad": "León", "giro": "comercio", "tamano": "pequena", "facturas_mes": 8, "ticket_prom": 6500},
    {"nombre": "Academia de Idiomas Global SC", "rfc": "AIG100101AB3", "regimen": "601", "ciudad": "CDMX", "giro": "educacion", "tamano": "pequena", "facturas_mes": 6, "ticket_prom": 5000},
    {"nombre": "Barbería Clásica Los Reyes SC", "rfc": "BCL180101QR4", "regimen": "601", "ciudad": "Monterrey", "giro": "servicios", "tamano": "pequena", "facturas_mes": 3, "ticket_prom": 2800},
    {"nombre": "Carnicería La Tradición SC", "rfc": "CLT050101HV2", "regimen": "601", "ciudad": "Puebla", "giro": "alimentos", "tamano": "pequena", "facturas_mes": 7, "ticket_prom": 4000},
    {"nombre": "Despacho de Arquitectura Habitat SC", "rfc": "DAH120101MN1", "regimen": "603", "ciudad": "CDMX", "giro": "arquitectura", "tamano": "pequena", "facturas_mes": 4, "ticket_prom": 55000},
    {"nombre": "Escuela de Música Armonía SC", "rfc": "EMA090101AB8", "regimen": "601", "ciudad": "Guadalajara", "giro": "educacion", "tamano": "pequena", "facturas_mes": 5, "ticket_prom": 3500},
    {"nombre": "Refaccionaria AutoPartes del Centro SC", "rfc": "RAC110101QR7", "regimen": "601", "ciudad": "CDMX", "giro": "comercio", "tamano": "mediana", "facturas_mes": 14, "ticket_prom": 9200},
    {"nombre": "Consultora de Recursos Humanos Talento SC", "rfc": "CRH140101HV3", "regimen": "603", "ciudad": "Monterrey", "giro": "consultoria", "tamano": "mediana", "facturas_mes": 8, "ticket_prom": 22000},
]

# ---------------------------------------------------------------------------
# Proveedores realistas (emisores de CFDI)
# ---------------------------------------------------------------------------

_PROVIDER_SEEDS: List[Dict[str, str]] = [
    {"nombre": "Grupo Empresarial Papelerías del Centro SA", "rfc": "GEPC850101AB3", "regimen": "601", "giro": "papeleria"},
    {"nombre": "Servicios de Hosting Cloud México SA de CV", "rfc": "SHCM920101QR7", "regimen": "601", "giro": "tecnologia"},
    {"nombre": "Distribuidora de Limpieza Total SC", "rfc": "DLT080101MN4", "regimen": "601", "giro": "limpieza"},
    {"nombre": "Transportes Rápidos del Norte SA", "rfc": "TRN780101TK2", "regimen": "601", "giro": "transporte"},
    {"nombre": "Consultora Fiscal y Contable Integral SC", "rfc": "CFCI050101HV6", "regimen": "603", "giro": "consultoria"},
    {"nombre": "Seguros y Fianzas Protectora SA", "rfc": "SFP010101AB1", "regimen": "601", "giro": "seguros"},
    {"nombre": "Suministros Industriales del Bajío SC", "rfc": "SIB110101QR3", "regimen": "601", "giro": "suministros"},
    {"nombre": "Imprenta Digital Pro Impresiones SA", "rfc": "IDP090101MN8", "regimen": "601", "giro": "imprenta"},
    {"nombre": "Servicios de Limpieza Profesional SC", "rfc": "SLP140101TK5", "regimen": "601", "giro": "limpieza"},
    {"nombre": "Energía Solar México SA de CV", "rfc": "ESM160101AB9", "regimen": "601", "giro": "energia"},
    {"nombre": "Equipo de Oficina y Muebles SC", "rfc": "EOM070101HV4", "regimen": "601", "giro": "mobiliario"},
    {"nombre": "Agua Purificada Cristalina SA", "rfc": "APC100101QR1", "regimen": "601", "giro": "alimentos"},
    {"nombre": "Cableado Estructurado y Redes SC", "rfc": "CER130101MN3", "regimen": "601", "giro": "tecnologia"},
    {"nombre": "Mantenimiento de Elevadores Técnicos SA", "rfc": "MET060101TK6", "regimen": "601", "giro": "mantenimiento"},
    {"nombre": "Papelería y Artículos Promocionales SC", "rfc": "PAP150101AB2", "regimen": "601", "giro": "papeleria"},
]

# ---------------------------------------------------------------------------
# Conceptos de CFDI por giro
# ---------------------------------------------------------------------------

_CONCEPTOS_POR_GIRO: Dict[str, List[Dict[str, str]]] = {
    "tecnologia": [
        {"desc": "Licencia de software anual", "clave": "80101500"},
        {"desc": "Servicio de hosting cloud mensual", "clave": "81112200"},
        {"desc": "Soporte técnico remoto", "clave": "82121700"},
        {"desc": "Equipo de cómputo desktop", "clave": "43211500"},
        {"desc": "Monitor LED 27 pulgadas", "clave": "43211800"},
        {"desc": "Servicio de internet dedicado", "clave": "81112100"},
        {"desc": "Desarrollo de software a medida", "clave": "82121600"},
        {"desc": "Capacitación en herramientas digitales", "clave": "82112100"},
    ],
    "consultoria": [
        {"desc": "Consultoría fiscal mensual", "clave": "82131500"},
        {"desc": "Auditoría contable anual", "clave": "82111800"},
        {"desc": "Consultoría en reestructuración empresarial", "clave": "82111500"},
        {"desc": "Planeación patrimonial familiar", "clave": "82131600"},
    ],
    "transporte": [
        {"desc": "Flete terrestre carga completa", "clave": "78101500"},
        {"desc": "Flete internacional contenedor 40'", "clave": "78101800"},
        {"desc": "Seguro de carga mercancía", "clave": "85121500"},
        {"desc": "Almacenamiento temporal aduanal", "clave": "78111800"},
    ],
    "alimentos": [
        {"desc": "Materia prima agroindustrial", "clave": "32131500"},
        {"desc": "Servicios de catering empresarial", "clave": "82121400"},
        {"desc": "Empaque y embalaje alimentario", "clave": "34181500"},
        {"desc": "Insumos de limpieza industrial", "clave": "32132200"},
    ],
    "manufactura": [
        {"desc": "Materia prima industrial", "clave": "32131500"},
        {"desc": "Herramientas y maquinaria", "clave": "43211500"},
        {"desc": "Refacciones industriales", "clave": "43211800"},
        {"desc": "Servicio de mantenimiento preventivo", "clave": "81141500"},
    ],
    "salud": [
        {"desc": "Equipo médico diagnóstico", "clave": "43221500"},
        {"desc": "Insumos médicos desechables", "clave": "32132200"},
        {"desc": "Servicio de mantenimiento equipo médico", "clave": "81141500"},
        {"desc": "Consultoría en salud ocupacional", "clave": "84101600"},
    ],
    "comercio": [
        {"desc": "Mercancía para reventa", "clave": "32131500"},
        {"desc": "Mobiliario comercial", "clave": "43211500"},
        {"desc": "Señalización y exhibidores", "clave": "34182100"},
    ],
    "servicios": [
        {"desc": "Servicio profesional de consultoría", "clave": "82111500"},
        {"desc": "Mantenimiento de instalaciones", "clave": "81141500"},
        {"desc": "Servicio de limpieza diaria", "clave": "81131500"},
        {"desc": "Servicio de seguridad privada", "clave": "84121600"},
    ],
    "construccion": [
        {"desc": "Materiales de construcción", "clave": "32131500"},
        {"desc": "Mano de obra calificada", "clave": "82111500"},
        {"desc": "Maquinaria pesada rentada", "clave": "78101500"},
        {"desc": "Diseño arquitectónico", "clave": "82111700"},
    ],
    "legal": [
        {"desc": "Honorarios legales por consulta", "clave": "82111500"},
        {"desc": "Trámite notarial", "clave": "82111700"},
        {"desc": "Poder notarial y escrituras", "clave": "82111800"},
    ],
    "finanzas": [
        {"desc": "Consultoría financiera Q2", "clave": "82131500"},
        {"desc": "Prima de seguro anual", "clave": "85121400"},
        {"desc": "Auditoría de cumplimiento", "clave": "82111800"},
    ],
    "marketing": [
        {"desc": "Campaña digital redes sociales", "clave": "82111600"},
        {"desc": "Producción audiovisual", "clave": "82111900"},
        {"desc": "Diseño gráfico publicitario", "clave": "82112100"},
    ],
    "inmobiliaria": [
        {"desc": "Peritaje inmobiliario", "clave": "82111800"},
        {"desc": "Comisión inmobiliaria por venta", "clave": "82111500"},
        {"desc": "Estudio de factibilidad financiera", "clave": "82131500"},
    ],
    "educacion": [
        {"desc": "Programa educativo certificado", "clave": "82112100"},
        {"desc": "Material didáctico", "clave": "32131500"},
        {"desc": "Plataforma e-learning", "clave": "80101500"},
    ],
    "hoteleria": [
        {"desc": "Huéspedes habitaciones ejecutivas", "clave": "43211500"},
        {"desc": "Servicio de eventos y banquetes", "clave": "82121400"},
        {"desc": "Mantenimiento de instalaciones", "clave": "81141500"},
    ],
    "medios": [
        {"desc": "Diseño editorial revista", "clave": "82111600"},
        {"desc": "Producción de contenido digital", "clave": "82112100"},
    ],
    "arquitectura": [
        {"desc": "Proyecto arquitectónico residencial", "clave": "82111700"},
        {"desc": "Diseño de interiores", "clave": "82111700"},
    ],
    "ingenieria": [
        {"desc": "Ingeniería de diseño industrial", "clave": "82111700"},
        {"desc": "Consultoría técnica especializada", "clave": "82131500"},
    ],
    "limpieza": [
        {"desc": "Servicio de limpieza empresarial", "clave": "81131500"},
        {"desc": "Suministros de limpieza industrial", "clave": "32132200"},
    ],
    "papeleria": [
        {"desc": "Papelería y artículos de oficina", "clave": "44122000"},
        {"desc": "Impresión de documentos corporativos", "clave": "82111900"},
    ],
    "seguros": [
        {"desc": "Póliza de seguro empresarial", "clave": "85121400"},
        {"desc": "Fianza de cumplimiento", "clave": "85121500"},
    ],
    "suministros": [
        {"desc": "Herramientas industriales", "clave": "43211500"},
        {"desc": "Refacciones y partes mecánicas", "clave": "43211800"},
    ],
    "imprenta": [
        {"desc": "Impresión offset gran formato", "clave": "82111900"},
        {"desc": "Material impreso publicitario", "clave": "34182100"},
    ],
    "energia": [
        {"desc": "Paneles solares fotovoltaicos", "clave": "43211500"},
        {"desc": "Instalación de sistema solar", "clave": "81112200"},
    ],
    "mobiliario": [
        {"desc": "Escritorio ejecutivo modulable", "clave": "43211500"},
        {"desc": "Silla ergonómica corporativa", "clave": "43211800"},
    ],
    "mantenimiento": [
        {"desc": "Mantenimiento preventivo elevador", "clave": "81141500"},
        {"desc": "Reparación de componentes", "clave": "43211800"},
    ],
    "distribucion": [
        {"desc": "Distribución y logística regional", "clave": "78101500"},
        {"desc": "Almacenamiento y custody", "clave": "78111800"},
    ],
}


# ---------------------------------------------------------------------------
# Empleados nómina
# ---------------------------------------------------------------------------

_EMPLEADOS: List[Dict[str, Any]] = [
    {"nombre": "María Guadalupe López Hernández", "curp": "LOHG900101MMCPR01", "rfc": "LOHG900101MNC", "num": "001", "sueldo": 28000, "deduccion": 2500},
    {"nombre": "Juan Carlos Ramírez Mendoza", "curp": "RAMJ850101HDFNNC01", "rfc": "RAMJ850101HDF", "num": "002", "sueldo": 22000, "deduccion": 1800},
    {"nombre": "Ana Patricia García Torres", "curp": "GATA820205MDFRN01", "rfc": "GATA820205MDF", "num": "003", "sueldo": 35000, "deduccion": 3200},
    {"nombre": "Roberto Díaz Vega", "curp": "DIVR880315HMCRR01", "rfc": "DIVR880315HMC", "num": "004", "sueldo": 18000, "deduccion": 1500},
    {"nombre": "Laura Sofía Martínez Cruz", "curp": "MACL910520MDFR02", "rfc": "MACL910520MDF", "num": "005", "sueldo": 25000, "deduccion": 2200},
]


# ---------------------------------------------------------------------------
# Generador principal
# ---------------------------------------------------------------------------

def generate_demo_firm(
    month: str = "2026-07",
    seed: int = 42,
) -> Dict[str, Any]:
    """Genera datos completos de una firma contable demo.

    Args:
        month: Mes en formato YYYY-MM para generar CFDIs.
        seed: Semilla para reproducibilidad.

    Returns:
        Diccionario con firm, clients, cfdis, kpis, roi_metrics, anomalies.
    """
    random.seed(seed)

    year, mon = map(int, month.split("-"))
    days_in_month = 31 if mon in (1, 3, 5, 7, 8, 10, 12) else 30 if mon in (4, 6, 9, 11) else 28

    # -----------------------------------------------------------------------
    # 1. Perfil de la firma contable
    # -----------------------------------------------------------------------
    firm = {
        "nombre": "Despacho Contable & Fiscal Profesional SC",
        "rfc": "DCF090101AB1",
        "regimen": "603",
        "ciudad": "Ciudad de México",
        "domicilio": "Av. Reforma 123, Col. Centro, CDMX",
        "telefono": "+52 55 1234 5678",
        "email": "contacto@dcf-contadores.mx",
        "sitio_web": "https://dcf-contadores.mx",
        "num_clientes": len(_CLIENT_SEEDS),
        "empleados_firma": 12,
        "año_fundacion": 2009,
        "certificaciones": ["CIF", "ISO 9001:2015", "Banco de México"],
    }

    # -----------------------------------------------------------------------
    # 2. Clientes
    # -----------------------------------------------------------------------
    clients = []
    for i, seed in enumerate(_CLIENT_SEEDS):
        client = {
            "id": i + 1,
            "nombre": seed["nombre"],
            "rfc": seed["rfc"],
            "regimen": seed["regimen"],
            "ciudad": seed["ciudad"],
            "giro": seed["giro"],
            "tamano": seed["tamano"],
            "facturas_esperadas_mes": seed["facturas_mes"],
            "ticket_promedio": seed["ticket_prom"],
            "antiguedad_meses": random.randint(6, 84),
            "status": "activo",
            "servicios_contratados": _random_services(seed["tamano"]),
            "mensualidad": _calc_mensualidad(seed["tamano"], seed["facturas_mes"]),
        }
        clients.append(client)

    # -----------------------------------------------------------------------
    # 3. Generar CFDIs (~500 en el mes)
    # -----------------------------------------------------------------------
    cfdis = []
    total_target = 500
    total_generated = 0
    folio_counter = 1000

    for client in clients:
        # Distribuir facturas proporcionalmente al esperado
        n_expected = client["facturas_esperadas_mes"]
        n_actual = max(1, int(n_expected * random.uniform(0.8, 1.2)))
        if total_generated + n_actual > total_target + 20:
            n_actual = max(1, total_target - total_generated)

        for j in range(n_actual):
            folio_counter += 1
            dia = random.randint(1, days_in_month)
            hora = random.randint(8, 18)
            minuto = random.randint(0, 59)
            fecha = f"{month}-{dia:02d}T{hora:02d}:{minuto:02d}:00"

            # Elegir tipo de comprobante (mayoría Ingreso, algo de Nómina y Egreso)
            tipo_roll = random.random()
            if tipo_roll < 0.08:
                tipo = "Nómina"
            elif tipo_roll < 0.12:
                tipo = "Egreso"
            else:
                tipo = "Ingreso"

            # Proveedor (emisor)
            prov = random.choice(_PROVIDER_SEEDS)

            # Concepto
            giro = client["giro"]
            conceptos_list = _CONCEPTOS_POR_GIRO.get(giro, _CONCEPTOS_POR_GIRO["servicios"])
            concepto = random.choice(conceptos_list)

            # Monto
            ticket = client["ticket_promedio"]
            subtotal = round(random.uniform(ticket * 0.3, ticket * 2.5), 2)
            iva = round(subtotal * 0.16, 2)
            descuento = round(subtotal * random.uniform(0, 0.05), 2) if random.random() < 0.2 else 0.0
            total = round(subtotal - descuento + iva, 2)

            metodo = "PUE" if random.random() < 0.7 else "PPD"
            forma = random.choice(["01", "03", "04", "28"])

            uuid_val = str(uuid.uuid4()).upper()

            cfdi = {
                "id": len(cfdis) + 1,
                "client_id": client["id"],
                "client_nombre": client["nombre"],
                "client_rfc": client["rfc"],
                "version": "4.0",
                "tipo": tipo,
                "fecha": fecha,
                "serie": "A" if tipo == "Ingreso" else ("N" if tipo == "Nómina" else "E"),
                "folio": str(folio_counter),
                "subtotal": f"{subtotal:.2f}",
                "descuento": f"{descuento:.2f}",
                "total": f"{total:.2f}",
                "iva": f"{iva:.2f}",
                "tasa_iva": "0.160000",
                "moneda": "MXN",
                "metodo_pago": metodo,
                "forma_pago": forma,
                "emisor_rfc": prov["rfc"],
                "emisor_nombre": prov["nombre"],
                "emisor_regimen": prov["regimen"],
                "receptor_rfc": client["rfc"],
                "receptor_nombre": client["nombre"],
                "folio_fiscal": uuid_val,
                "conceptos_count": 1,
                "conceptos": [{"descripcion": concepto["desc"], "importe": f"{subtotal:.2f}", "clave_prod_serv": concepto["clave"]}],
                "status": "procesado",
            }
            cfdis.append(cfdi)
            total_generated += 1

            if total_generated >= total_target:
                break
        if total_generated >= total_target:
            break

    # Ajustar a exactamente 500 si sobra o falta
    while len(cfdis) < total_target:
        client = random.choice(clients)
        folio_counter += 1
        dia = random.randint(1, days_in_month)
        fecha = f"{month}-{dia:02d}T{random.randint(8,18):02d}:{random.randint(0,59):02d}:00"
        prov = random.choice(_PROVIDER_SEEDS)
        giro = client["giro"]
        conceptos_list = _CONCEPTOS_POR_GIRO.get(giro, _CONCEPTOS_POR_GIRO["servicios"])
        concepto = random.choice(conceptos_list)
        subtotal = round(random.uniform(3000, 50000), 2)
        iva = round(subtotal * 0.16, 2)
        total = round(subtotal + iva, 2)
        uuid_val = str(uuid.uuid4()).upper()
        cfdi = {
            "id": len(cfdis) + 1,
            "client_id": client["id"],
            "client_nombre": client["nombre"],
            "client_rfc": client["rfc"],
            "version": "4.0",
            "tipo": "Ingreso",
            "fecha": fecha,
            "serie": "A",
            "folio": str(folio_counter),
            "subtotal": f"{subtotal:.2f}",
            "descuento": "0.00",
            "total": f"{total:.2f}",
            "iva": f"{iva:.2f}",
            "tasa_iva": "0.160000",
            "moneda": "MXN",
            "metodo_pago": "PUE",
            "forma_pago": "03",
            "emisor_rfc": prov["rfc"],
            "emisor_nombre": prov["nombre"],
            "emisor_regimen": prov["regimen"],
            "receptor_rfc": client["rfc"],
            "receptor_nombre": client["nombre"],
            "folio_fiscal": uuid_val,
            "conceptos_count": 1,
            "conceptos": [{"descripcion": concepto["desc"], "importe": f"{subtotal:.2f}", "clave_prod_serv": concepto["clave"]}],
            "status": "procesado",
        }
        cfdis.append(cfdi)

    # -----------------------------------------------------------------------
    # 4. Anomalías inyectadas (realistas)
    # -----------------------------------------------------------------------
    anomalies = _inject_anomalies(cfdis, clients)

    # -----------------------------------------------------------------------
    # 5. Nómina
    # -----------------------------------------------------------------------
    nominas = []
    for emp in _EMPLEADOS:
        percepciones = emp["sueldo"] + random.uniform(1000, 5000)
        deducciones = emp["deduccion"]
        neto = percepciones - deducciones
        nominas.append({
            "empleado": emp["nombre"],
            "curp": emp["curp"],
            "rfc": emp["rfc"],
            "num_empleado": emp["num"],
            "sueldo_bruto": round(percepciones, 2),
            "deducciones": round(deducciones, 2),
            "neto": round(neto, 2),
            "dias_pagados": 30,
            "periodo": month,
        })

    # -----------------------------------------------------------------------
    # 6. KPIs y métricas de ROI
    # -----------------------------------------------------------------------
    total_monto = sum(float(c["total"]) for c in cfdis)
    total_iva = sum(float(c["iva"]) for c in cfdis)
    ingresos = sum(float(c["total"]) for c in cfdis if c["tipo"] == "Ingreso")
    egresos = sum(float(c["total"]) for c in cfdis if c["tipo"] == "Egreso")
    nominas_total = sum(n["sueldo_bruto"] for n in nominas)

    # Métricas manuales vs automatizadas
    manuales_por_factura = 4.5  # minutos promedio sin IA
    automaticas_por_factura = 0.8  # minutos con IA
    horas_ahorradas = round((manuales_por_factura - automaticas_por_factura) * len(cfdis) / 60, 1)
    costo_hora_contador = 350  # MXN/hora
    ahorro_mensual = round(horas_ahorradas * costo_hora_contador, 2)

    # Tasa de error humano vs AI
    tasa_error_humano = 3.2  # %
    tasa_error_ai = 0.4  # %
    facturas_anomalias = len([a for a in anomalies if a["severity"] in ("alta", "critical")])

    roi_metrics = {
        "periodo": month,
        "resumen_firma": {
            "total_clientes_activos": len([c for c in clients if c["status"] == "activo"]),
            "total_cfdi_procesados": len(cfdis),
            "monto_total_procesado": round(total_monto, 2),
            "iva_total": round(total_iva, 2),
            "ingresos_netos": round(ingresos, 2),
            "egresos_netos": round(egresos, 2),
            "nomina_total_firma": round(nominas_total, 2),
        },
        "ahorro_ia": {
            "minutos_por_factura_antes": manuales_por_factura,
            "minutos_por_factura_despues": automaticas_por_factura,
            "total_horas_ahorradas": horas_ahorradas,
            "ahorro_mensual_mx": ahorro_mensual,
            "ahorro_anual_mx": round(ahorro_mensual * 12, 2),
            "eficiencia_porcentaje": round((1 - automaticas_por_factura / manuales_por_factura) * 100, 1),
        },
        "calidad": {
            "tasa_error_humano_pct": tasa_error_humano,
            "tasa_error_ai_pct": tasa_error_ai,
            "mejora_calidad_factor": round(tasa_error_humano / tasa_error_ai, 1),
            "anomalias_detectadas": len(anomalies),
            "anomalias_criticas": facturas_anomalias,
        },
        "satisfaccion": {
            "nps_score": 72,
            "tiempo_respuesta_avg_seg": 1.2,
            "disponibilidad_pct": 99.9,
            "tickets_soporte_mes": 3,
        },
        "comparativa_roi": {
            "inversion_mensual_b2b_ai": 8500,  # MXN
            "ahorro_operativo_mensual": ahorro_mensual,
            "roi_mensual_pct": round((ahorro_mensual / 8500 - 1) * 100, 1),
            "payback_dias": round(8500 / (ahorro_mensual / 30), 1) if ahorro_mensual > 0 else 999,
            "roi_anual_pct": round(((ahorro_mensual * 12) / (8500 * 12) - 1) * 100, 1),
        },
    }

    # -----------------------------------------------------------------------
    # 7. Top proveedores y categorías
    # -----------------------------------------------------------------------
    from collections import Counter, defaultdict
    prov_counter = Counter()
    prov_monto = defaultdict(float)
    for c in cfdis:
        prov_counter[c["emisor_nombre"]] += 1
        prov_monto[c["emisor_nombre"]] += float(c["total"])

    top_proveedores = [
        {"nombre": n, "facturas": prov_counter[n], "monto_total": round(prov_monto[n], 2)}
        for n, _ in prov_counter.most_common(10)
    ]

    giro_counter = Counter()
    giro_monto = defaultdict(float)
    for cl in clients:
        giro_counter[cl["giro"]] += len([c for c in cfdis if c["client_id"] == cl["id"]])
        giro_monto[cl["giro"]] += sum(float(c["total"]) for c in cfdis if c["client_id"] == cl["id"])

    top_giros = [
        {"giro": g, "facturas": giro_counter[g], "monto_total": round(giro_monto[g], 2)}
        for g, _ in giro_counter.most_common(10)
    ]

    return {
        "firm": firm,
        "clients": clients,
        "cfdis": cfdis,
        "nominas": nominas,
        "anomalies": anomalies,
        "roi_metrics": roi_metrics,
        "top_proveedores": top_proveedores,
        "top_giros": top_giros,
        "month": month,
        "generated_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_services(tamano: str) -> List[str]:
    base = ["Procesamiento CFDI", "Clasificación automática"]
    if tamano in ("grande", "mediana"):
        base += ["Conciliación bancaria", "Reportes ejecutivos", "Notificaciones"]
    if tamano == "grande":
        base += ["Integración ERP", "Cobranza automatizada", "Contabilidad electrónica"]
    return base


def _calc_mensualidad(tamano: str, facturas: int) -> float:
    base = {"pequena": 3500, "mediana": 8500, "grande": 18000}.get(tamano, 3500)
    return round(base + facturas * 15, 2)


def _inject_anomalies(cfdis: List[Dict], clients: List[Dict]) -> List[Dict]:
    """Inyecta anomalías realistas en los CFDIs."""
    anomalies = []

    # 1. Monto inusual (>3x promedio del cliente)
    for client in clients[:5]:
        client_cfdis = [c for c in cfdis if c["client_id"] == client["id"]]
        if not client_cfdis:
            continue
        avg = sum(float(c["total"]) for c in client_cfdis) / len(client_cfdis)
        for c in client_cfdis:
            if float(c["total"]) > avg * 3.0:
                anomalies.append({
                    "tipo": "monto_atipico",
                    "severity": "alta",
                    "cfdi_id": c["id"],
                    "client": client["nombre"],
                    "monto": float(c["total"]),
                    "promedio_cliente": round(avg, 2),
                    "factor": round(float(c["total"]) / avg, 1),
                    "descripcion": f"Monto ${float(c['total']):,.2f} es {float(c['total'])/avg:.1f}x el promedio del cliente (${avg:,.2f})",
                    "referencia_legal": "Art. 79 Código Fiscal de la Federación — obligación de expedition de CFDI",
                })

    # 2. Factura cancelada detectada
    canceladas = random.sample(cfdis[:50], min(3, len(cfdis[:50])))
    for c in canceladas:
        anomalies.append({
            "tipo": "factura_cancelada",
            "severity": "media",
            "cfdi_id": c["id"],
            "client": c["client_nombre"],
            "monto": float(c["total"]),
            "descripcion": f"CFDI {c['folio']} cancelado en SAT — requiere ajuste contable",
            "referencia_legal": "Art. 29-A fracc. VII CFF — efectos fiscales de cancelación",
        })

    # 3. Duplicado potencial
    for c in cfdis[10:13]:
        anomalies.append({
            "tipo": "duplicado_potencial",
            "severity": "baja",
            "cfdi_id": c["id"],
            "client": c["client_nombre"],
            "monto": float(c["total"]),
            "descripcion": f"Folio fiscal posible duplicado detectado para {c['client_rfc']}",
            "referencia_legal": "Regla 2.7.1.33 RMF — verificación de unicidad de folio fiscal",
        })

    # 4. RFC receptor no coincide con empresa
    anomalies.append({
        "tipo": "rfc_inconsistente",
        "severity": "media",
        "cfdi_id": cfdis[50]["id"] if len(cfdis) > 50 else cfdis[0]["id"],
        "client": cfdis[50]["client_nombre"] if len(cfdis) > 50 else cfdis[0]["client_nombre"],
        "monto": float(cfdis[50]["total"]) if len(cfdis) > 50 else float(cfdis[0]["total"]),
        "descripcion": "RFC del receptor no coincide con el registrado del cliente",
        "referencia_legal": "Art. 29-A fracc. III CFF — datos correctos del receptor",
    })

    # 5. IVA cero en factura que debería tener IVA
    anomalies.append({
        "tipo": "iva_inconsistente",
        "severity": "alta",
        "cfdi_id": cfdis[75]["id"] if len(cfdis) > 75 else cfdis[0]["id"],
        "client": cfdis[75]["client_nombre"] if len(cfdis) > 75 else cfdis[0]["client_nombre"],
        "monto": float(cfdis[75]["total"]) if len(cfdis) > 75 else float(cfdis[0]["total"]),
        "descripcion": "Factura con IVA $0.00 pero régimen general gravado — posible omisión fiscal",
        "referencia_legal": "Art. 1 CFF — obligación de trasladar IVA en operaciones gravadas",
    })

    return anomalies


# ---------------------------------------------------------------------------
# Resumen ejecutivo para el reporte
# ---------------------------------------------------------------------------

def build_executive_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """Construye un resumen ejecutivo para el reporte PDF."""
    roi = data["roi_metrics"]
    firm = data["firm"]
    clients = data["clients"]

    return {
        "titulo": f"Reporte Mensual — {firm['nombre']}",
        "periodo": data["month"],
        "fecha_generacion": datetime.now().strftime("%d de %B de %Y"),
        "resumen": {
            "clientes_activos": roi["resumen_firma"]["total_clientes_activos"],
            "cfdis_procesados": roi["resumen_firma"]["total_cfdi_procesados"],
            "monto_total": roi["resumen_firma"]["monto_total_procesado"],
            "iva_total": roi["resumen_firma"]["iva_total"],
            "anomalias_detectadas": roi["calidad"]["anomalias_detectadas"],
            "horas_ahorradas_ia": roi["ahorro_ia"]["total_horas_ahorradas"],
            "ahorro_mensual": roi["ahorro_ia"]["ahorro_mensual_mx"],
            "roi_mensual_pct": roi["comparativa_roi"]["roi_mensual_pct"],
            "payback_dias": roi["comparativa_roi"]["payback_dias"],
        },
        "clientes_top5": sorted(clients, key=lambda c: c["mensualidad"], reverse=True)[:5],
        "kpi_cards": [
            {"label": "CFDIs Procesados", "value": str(roi["resumen_firma"]["total_cfdi_procesados"]), "icon": "📄"},
            {"label": "Monto Total", "value": f"${roi['resumen_firma']['monto_total_procesado']:,.0f}", "icon": "💰"},
            {"label": "Horas Ahorradas", "value": f"{roi['ahorro_ia']['total_horas_ahorradas']}h", "icon": "⏱️"},
            {"label": "Ahorro Mensual", "value": f"${roi['ahorro_ia']['ahorro_mensual_mx']:,.0f}", "icon": "📈"},
            {"label": "ROI Mensual", "value": f"{roi['comparativa_roi']['roi_mensual_pct']}%", "icon": "🎯"},
            {"label": "Calidad (error AI)", "value": f"{roi['calidad']['tasa_error_ai_pct']}%", "icon": "✅"},
        ],
    }
