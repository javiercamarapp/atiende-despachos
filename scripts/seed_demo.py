# -*- coding: utf-8 -*-
"""seed_demo.py — Puebla la BD con datos contables mexicanos realistas para demo.

Genera y persiste un dataset demo determinista (random.seed=42) de un
despacho contable mexicano para mostrar a prospectos:

    3  tenants        despachos contables de ejemplo
    5  clientes/tenant  empresas mexicanas con RFC válido (personas morales)
    20 CFDIs/cliente    emitidos (I) y recibidos (E), montos realistas MXN
    50 transacciones/tenant  BBVA, Banorte, Santander, HSBC
    10 nóminas/tenant   CFDI de nómina (tipo N) + detalle de percepciones
    5  documentos/tenant  índice de gestión documental (formato _StateCodec)
    Roles y permisos    admin/contador/auditor/readonly por tenant
    1  usuario admin/tenant

El script es AUTO-CONTENIDO (stdlib + sqlite3). No importa `b2b_ai` para no
acoplar el seeder a la app y poder correrlo desde cualquier carpeta. El
esquema que crea replica el modelo canónico de `b2b_ai/db/models.py`
(tenants, users, client_users, invoices, bank_transactions) y añade dos
tablas auxiliares para el demo (nominas, documents) + la matriz RBAC
(roles, permissions, user_roles).

Salida:
    - JSON por entidad en scripts/seed_data/ (tenants, clientes, cfdis,
      transacciones, nominas, documents, roles)
    - Inserciones en la BD indicada.

Conexión (orden de precedencia):
    1. `--db <ruta|dsn>`  : ruta SQLite o DSN Postgres (psycopg2).
    2. env B2B_DB_URL     : DSN Postgres (postgresql://...).
    3. env B2B_DB_PATH    : ruta SQLite.
    4. por defecto        : `b2b_ai.db` (SQLite, junto al script).

Ejemplos:
    python scripts/seed_demo.py                     # SQLite b2b_ai.db
    python scripts/seed_demo.py --db /tmp/demo.db   # SQLite custom
    python scripts/seed_demo.py --json-only         # solo genera JSONs
    B2B_DB_URL=postgresql://u:p@host/db python scripts/seed_demo.py

Reproducible: mismo output con el mismo seed (por defecto 42).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_SEED = 42
_BANCOS = ["BBVA", "Banorte", "Santander", "HSBC"]
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SEED_DIR = os.path.join(_BASE_DIR, "seed_data")


# ---------------------------------------------------------------------------
# Generación determinista
# ---------------------------------------------------------------------------

def _rfc_empresa(rng: random.Random) -> str:
    """RFC válido de persona moral: 3 letras + 6 dígitos (YYMMDD) + 3 homoclave."""
    letras = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=3))
    fecha = f"{rng.randint(0, 99):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
    homoclave = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=3))
    return f"{letras}{fecha}{homoclave}"


def _rfc_fisica(rng: random.Random) -> str:
    """RFC de persona física: 4 letras + 6 dígitos (YYMMDD) + 3 homoclave."""
    letras = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=4))
    fecha = f"{rng.randint(0, 99):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
    homoclave = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=3))
    return f"{letras}{fecha}{homoclave}"


_TENANTS = [
    {
        "name": "Contadores Asociados del Bajío, S.C.",
        "rfc": "CAB091012AB1",
        "erp_type": "contpaqi",
        "plantilla_contable": "SAT",
        "ciudad": "León, Guanajuato",
        "admin_email": "admin@bajio.contadores.mx",
    },
    {
        "name": "Grupo Fiscal del Norte, S.C.",
        "rfc": "GFN940523CD2",
        "erp_type": "contpaqi",
        "plantilla_contable": "SAT",
        "ciudad": "Monterrey, Nuevo León",
        "admin_email": "admin@norte.grupofiscal.mx",
    },
    {
        "name": "Despacho Contable del Pacífico, S.C.",
        "rfc": "DCP971108EF3",
        "erp_type": "aspel",
        "plantilla_contable": "CoA",
        "ciudad": "Guadalajara, Jalisco",
        "admin_email": "admin@pacifico.despacho.mx",
    },
]

_SECTORES = [
    "Manufactura", "Comercio", "Servicios", "Construcción", "Logística",
    "Tecnología", "Alimentos y bebidas", "Salud", "Textil", "Agroindustria",
]

_NOMBRES_EMPRESA = [
    "Comercializadora", "Manufacturera", "Industrial", "Inmobiliaria",
    "Logística", "Farmacéutica", "Textilera", "Agropecuaria", "Constructora",
    "Distribuidora",
]
_SUFIJOS = ["S.A. de C.V.", "S.A.P.I. de C.V.", "S. de R.L. de C.V."]

_CONCEPTOS_CFDI = [
    ("Servicios profesionales de contabilidad", "861118"),
    ("Asesoría fiscal y laboral", "861118"),
    ("Venta de mercancía al mayoreo", "60111500"),
    ("Servicios de transporte de carga", "78111500"),
    ("Mantenimiento de equipo de cómputo", "81111800"),
    ("Arrendamiento de oficina", "93141500"),
    ("Servicios de publicidad y marketing", "83111500"),
    ("Venta de equipo de oficina", "60101600"),
    ("Consultoría en tecnologías de la información", "81112100"),
    ("Servicios de construcción y remodelación", "72100000"),
]

_CATEGORIAS = ["Gastos", "Ingresos", "Compras", "Ventas", "Servicios"]


def _generar_tenant(rng: random.Random, t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": t["name"],
        "rfc": t["rfc"],
        "erp_type": t["erp_type"],
        "plantilla_contable": t["plantilla_contable"],
        "ciudad": t["ciudad"],
        "admin_email": t["admin_email"],
        "blocked": 0,
    }


def _generar_clientes(rng: random.Random, n: int, tenant_idx: int) -> List[Dict[str, Any]]:
    clientes = []
    for i in range(n):
        nombre = rng.choice(_NOMBRES_EMPRESA) + " " + rng.choice(_SUFIJOS)
        email = f"contacto{tenant_idx}{i}@{_slug(nombre)}"
        clientes.append({
            "tenant_idx": tenant_idx,
            "name": nombre,
            "rfc": _rfc_empresa(rng),
            "email": email,
            "sector": rng.choice(_SECTORES),
            "ciudad": rng.choice(["CDMX", "Guadalajara", "Monterrey", "Puebla", "Querétaro"]),
        })
    return clientes


def _slug(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())[:24]


def _generar_cfdi(rng: random.Random, cliente: Dict[str, Any], idx: int,
                   emisor_despacho: Dict[str, Any]) -> Dict[str, Any]:
    # 60% recibidos (emisor = proveedor externo, receptor = cliente/despacho),
    # 40% emitidos (emisor = despacho, receptor = cliente).
    emitido = rng.random() < 0.4
    subtotal = round(rng.uniform(500.0, 250000.0), 2)
    iva = round(subtotal * 0.16, 2)
    total = round(subtotal + iva, 2)
    concepto, sat_id = rng.choice(_CONCEPTOS_CFDI)
    fecha = date.today() - timedelta(days=rng.randint(0, 365))
    tipo = "I" if emitido else "E"
    serie = rng.choice(["A", "B", "C", "F", "G"])
    folio = f"{rng.randint(1000, 99999)}"
    folio_fiscal = "-".join(
        "".join(rng.choice("ABCDEF0123456789") for _ in range(s)) for s in (8, 4, 4, 4, 12))
    confianza = round(rng.uniform(0.75, 0.99), 2)
    return {
        "tenant_idx": cliente["tenant_idx"],
        "cliente_idx": None,  # se rellena después
        "tipo_comprobante": tipo,
        "fecha": fecha.isoformat(),
        "serie": serie,
        "folio": folio,
        "folio_fiscal": folio_fiscal,
        "emisor_rfc": emisor_despacho["rfc"] if emitido else _rfc_empresa(rng),
        "emisor_nombre": emisor_despacho["name"] if emitido else rng.choice(_NOMBRES_EMPRESA) + " " + rng.choice(_SUFIJOS),
        "receptor_rfc": cliente["rfc"] if emitido else emisor_despacho["rfc"],
        "receptor_nombre": cliente["name"] if emitido else emisor_despacho["name"],
        "subtotal": subtotal,
        "iva": iva,
        "total": total,
        "moneda": "MXN",
        "descripcion": f"{concepto} (CLAVE_SAT {sat_id})",
        "categoria": rng.choice(_CATEGORIAS),
        "confianza": confianza,
        "valido": 1,
        "requires_human_review": 0,
        "status": "procesado",
    }


def _generar_transacciones(rng: random.Random, tenant_idx: int,
                           n: int) -> List[Dict[str, Any]]:
    tx = []
    for i in range(n):
        banco = rng.choice(_BANCOS)
        monto = round(rng.uniform(100.0, 150000.0), 2)
        tipo = "ingreso" if rng.random() < 0.55 else "egreso"
        if tipo == "egreso":
            monto = -abs(monto)
        desc = rng.choice([
            "Transferencia SPEI", "Pago a proveedor", "Depósito en ventanilla",
            "Pago de nómina", "Retiro ATM", "Cargo por comisión",
            "Abono de cliente", "Pago de impuestos SAT", "Renta de oficina",
            "Compra de suministros",
        ])
        fecha = date.today() - timedelta(days=rng.randint(0, 90))
        tx_id = f"{banco[:3]}{tenant_idx}{i:04d}-{rng.randint(1000000000, 9999999999)}"
        tx.append({
            "tenant_idx": tenant_idx,
            "tx_id": tx_id,
            "banco": banco,
            "fecha": fecha.isoformat(),
            "descripcion": desc,
            "tipo": tipo,
            "monto": monto,
            "referencia": f"SPEI{rng.randint(1000, 999999)}",
            "beneficiario": rng.choice(["Cliente", "Proveedor", "Proveedor externo", "SAT", "Banco", "Arrendador"]),
            "saldo": round(rng.uniform(50000.0, 5000000.0), 2),
        })
    return tx


_EMPLEADOS = ["Luis", "María", "Carlos", "Ana", "José", "Rosa", "Pedro", "Laura", "Miguel", "Sofía"]
_APELLIDOS = ["García", "Martínez", "López", "Hernández", "González", "Pérez", "Rodríguez", "Sánchez", "Ramírez", "Torres"]


def _generar_nominas(rng: random.Random, tenant_idx: int, n: int) -> List[Dict[str, Any]]:
    nominas = []
    for i in range(n):
        nom = rng.choice(_EMPLEADOS)
        ape = rng.choice(_APELLIDOS)
        dias = rng.choice([15, 30])
        sueldo_diario = round(rng.uniform(250.0, 2500.0), 2)
        sueldo_mensual = round(sueldo_diario * dias, 2)
        iva_s = round(sueldo_mensual * 0.16, 2)
        isr = round(sueldo_mensual * rng.uniform(0.05, 0.12), 2)
        imss = round(sueldo_mensual * rng.uniform(0.04, 0.07), 2)
        total_percepciones = round(sueldo_mensual + iva_s, 2)
        total_deducciones = round(isr + imss, 2)
        liquido = round(total_percepciones - total_deducciones, 2)
        periodo = (date.today().replace(day=1) - timedelta(days=rng.randint(0, 180))).isoformat()
        nominas.append({
            "tenant_idx": tenant_idx,
            "empleado_nombre": f"{nom} {ape}",
            "rfc": _rfc_fisica(rng),
            "fecha_periodo": periodo,
            "tipo_regimen": rng.choice(["02", "03", "10"]),
            "dias_pagados": dias,
            "sueldo_diario": sueldo_diario,
            "sueldo_mensual": sueldo_mensual,
            "iva_subsidio": iva_s,
            "isr": isr,
            "imss": imss,
            "total_percepciones": total_percepciones,
            "total_deducciones": total_deducciones,
            "liquido": liquido,
            "total": round(total_percepciones, 2),
        })
    return nominas


def _generar_documentos(rng: random.Random, tenant_idx: int, n: int,
                        clientes: List[Dict[str, Any]]) -> Dict[str, Any]:
    docs = []
    tipos = [
        ("factura_demo.xml", "CFDI", "application/xml"),
        ("contrato_servicio.pdf", "contrato", "application/pdf"),
        ("carta_porte.pdf", "carta_porte", "application/pdf"),
        ("recibo_nomina_empleado.xml", "nomina_xml", "application/xml"),
        ("constancia_fiscal.pdf", "constancia", "application/pdf"),
    ]
    for i in range(n):
        name, cat, ct = tipos[i % len(tipos)]
        content = json.dumps({
            "tenant": tenant_idx, "idx": i,
            "desc": f"Documento demo {i+1} del tenant {tenant_idx}",
        }).encode()
        digest = hashlib.sha256(content).hexdigest()
        doc_id = "doc-" + str(rng.randint(10**15, 10**16))
        docs.append({
            "id": doc_id,
            "tenant_id": str(tenant_idx),
            "name": name,
            "category": cat,
            "content_type": ct,
            "size": len(content),
            "sha256": digest,
            "storage_path": f"T{tenant_idx}/{digest[:2]}/{digest}.bin",
            "version": 1,
            "metadata": {"tipo": cat, "rfc": clientes[0]["rfc"]},
            "tags": ["demo", cat.lower().replace("_", "")],
            "status": "ACTIVO",
            "created_by": f"admin@tenant{tenant_idx}",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 60))).isoformat().replace("+00:00", "Z"),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
    # Formato que carga DocumentService._load_state (modelos de
    # b2b_ai.features.document_management) vía DOCS_STATE_FILE.
    return {
        "documents": docs,
        "versions": {d["id"]: [{
            "document_id": d["id"], "version": 1, "sha256": d["sha256"],
            "storage_path": d["storage_path"], "size": d["size"],
            "note": "Versión inicial", "created_by": d["created_by"],
            "created_at": d["created_at"],
        }] for d in docs},
        "shares": {},
    }


_ROLES = {
    "admin": ["cfdi:read", "cfdi:write", "nominas:read", "nominas:write",
              "reportes:read", "reportes:write", "billing:read", "billing:write",
              "settings:read", "settings:write", "users:manage"],
    "contador": ["cfdi:read", "cfdi:write", "nominas:read", "nominas:write",
                 "reportes:read", "billing:read", "settings:read"],
    "auditor": ["cfdi:read", "nominas:read", "reportes:read",
                "billing:read", "settings:read"],
    "readonly": ["cfdi:read", "reportes:read"],
}


def generar_dataset(seed: int = _SEED) -> Dict[str, Any]:
    rng = random.Random(seed)
    tenants = [_generar_tenant(rng, t) for t in _TENANTS]
    clientes: List[Dict[str, Any]] = []
    for ti in range(len(tenants)):
        clientes.extend(_generar_clientes(rng, 5, ti))

    # CFDIs: 20 por cliente (emitidos y recibidos).
    cfdis: List[Dict[str, Any]] = []
    c_idx = 0
    for ti, t in enumerate(tenants):
        for cli in clientes:
            if cli["tenant_idx"] != ti:
                continue
            for _ in range(20):
                c = _generar_cfdi(rng, cli, c_idx, t)
                c["cliente_idx"] = c_idx
                c["tenant_idx"] = ti
                cfdis.append(c)
            c_idx += 1

    transacciones: List[Dict[str, Any]] = []
    for ti in range(len(tenants)):
        transacciones.extend(_generar_transacciones(rng, ti, 50))

    nominas: List[Dict[str, Any]] = []
    for ti in range(len(tenants)):
        nominas.extend(_generar_nominas(rng, ti, 10))

    documentos: Dict[str, Any] = {
        "documents": [],
        "versions": {},
        "shares": {},
    }
    doc_by_tenant: List[Dict[str, Any]] = []
    for ti in range(len(tenants)):
        tc = [cl for cl in clientes if cl["tenant_idx"] == ti]
        d = _generar_documentos(rng, ti, 5, tc)
        for doc in d["documents"]:
            doc_by_tenant.append(doc)
        documentos["documents"].extend(d["documents"])
        for k, v in d["versions"].items():
            documentos["versions"][k] = v

    return {
        "tenants": tenants,
        "clientes": clientes,
        "cfdis": cfdis,
        "transacciones": transacciones,
        "nominas": nominas,
        "documents": doc_by_tenant,
        "documents_state": documentos,
        "roles": _ROLES,
    }


# ---------------------------------------------------------------------------
# Esquema y persistencia (SQL portátil SQLite/Postgres)
# ---------------------------------------------------------------------------

# Replica el modelo canónico de b2b_ai/db/models.py + tablas auxiliares demo.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    rfc TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    role TEXT DEFAULT 'contador',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS client_users (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    role TEXT DEFAULT 'cliente',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    folio_fiscal TEXT,
    archivo TEXT NOT NULL,
    fecha TEXT,
    tipo TEXT,
    serie TEXT,
    folio TEXT,
    emisor_rfc TEXT,
    emisor_nombre TEXT,
    receptor_rfc TEXT,
    subtotal TEXT,
    iva TEXT,
    total TEXT,
    moneda TEXT DEFAULT 'MXN',
    descripcion TEXT,
    categoria TEXT,
    confianza REAL,
    razon_clasificacion TEXT,
    valido INTEGER DEFAULT 0,
    requires_human_review INTEGER DEFAULT 1,
    issues TEXT,
    erp_poliza TEXT,
    erp_status TEXT,
    status TEXT DEFAULT 'procesado',
    procesado_en TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    tx_id TEXT NOT NULL,
    banco TEXT,
    filename TEXT,
    data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS nominas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    empleado_nombre TEXT NOT NULL,
    rfc TEXT,
    fecha_periodo TEXT,
    tipo_regimen TEXT,
    dias_pagados INTEGER,
    sueldo_diario TEXT,
    total TEXT,
    liquido TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    content_type TEXT,
    size INTEGER DEFAULT 0,
    sha256 TEXT,
    storage_path TEXT,
    version INTEGER DEFAULT 1,
    metadata TEXT,
    tags TEXT,
    status TEXT DEFAULT 'ACTIVO',
    created_by TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    name TEXT NOT NULL,
    description TEXT,
    builtin INTEGER DEFAULT 1,
    permissions TEXT
);
CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER,
    role_name TEXT NOT NULL
);
"""

# Órdenes con id explícito para portabilidad SQLite/PG (seed determinista).
def _insert(conn: Any, table: str, cols: List[str], rows: List[List[Any]],
            placeholder: str = "?") -> None:
    if not rows:
        return
    ph = ",".join([placeholder] * len(cols))
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})"
    conn.executemany(sql, [list(r) for r in rows])
    conn.commit()


def crear_esquema(conn: Any) -> None:
    if isinstance(conn, sqlite3.Connection):
        conn.executescript(_SCHEMA)
        conn.commit()
    else:
        for stmt in _SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.commit()


def _tot(r: float) -> str:
    return f"{r:.2f}"


def poblar_db(conn: Any, ds: Dict[str, Any], placeholder: str = "?") -> None:
    crear_esquema(conn)

    tenants_rows = [
        [i, t["name"], t["rfc"]]
        for i, t in enumerate(ds["tenants"], start=1)
    ]
    _insert(conn, "tenants", ["id", "name", "rfc"], tenants_rows, placeholder)

    users_rows: List[List[Any]] = []
    user_roles_rows: List[List[Any]] = []
    role_rows: List[List[Any]] = []
    role_id = 1
    # 1 admin por tenant + un contador y un auditor por tenant (roles demo).
    for ti, t in enumerate(ds["tenants"], start=1):
        users_rows.append([ti, "admin", t["admin_email"], "admin"])
        users_rows.append([ti, "Contador Principal", f"contador@tenant{ti}.mx", "contador"])
        users_rows.append([ti, "Auditor Interno", f"auditor@tenant{ti}.mx", "auditor"])
        for name, desc, perms in [("admin", "Administrador: acceso total.", _ROLES["admin"]),
                                  ("contador", "Contador: opera CFDI y nómina.", _ROLES["contador"]),
                                  ("auditor", "Auditor: solo lectura.", _ROLES["auditor"]),
                                  ("readonly", "Solo lectura.", _ROLES["readonly"])]:
            role_rows.append([role_id, ti, name, desc, 1, json.dumps(perms)])
            role_id += 1
    _insert(conn, "roles", ["id", "tenant_id", "name", "description", "builtin", "permissions"],
            role_rows, placeholder)

    user_id = 1
    for ti in range(1, len(ds["tenants"]) + 1):
        # usuarios admin/contador/auditor de este tenant (ids 3*(ti-1)+1..3*ti)
        for role_name in ["admin", "contador", "auditor"]:
            user_roles_rows.append([ti, user_id, None, role_name])
            user_id += 1
    _insert(conn, "user_roles", ["tenant_id", "user_id", "role_id", "role_name"],
            user_roles_rows, placeholder)
    _insert(conn, "users", ["tenant_id", "name", "email", "role"], users_rows, placeholder)

    clientes_rows: List[List[Any]] = []
    for i, c in enumerate(ds["clientes"], start=1):
        clientes_rows.append([
            c["tenant_idx"] + 1, c["email"],
            hashlib.sha256(f"demo-pass-{c['email']}".encode()).hexdigest(),
            c["name"], "cliente",
        ])
    _insert(conn, "client_users", ["tenant_id", "email", "password_hash", "name", "role"],
            clientes_rows, placeholder)

    invoices_rows: List[List[Any]] = []
    for i, c in enumerate(ds["cfdis"], start=1):
        invoices_rows.append([
            c["tenant_idx"] + 1, c["folio_fiscal"],
            f"CFDI_{c['tipo_comprobante']}_{c['serie']}{c['folio']}.xml",
            c["fecha"], c["tipo_comprobante"], c["serie"], c["folio"],
            c["emisor_rfc"], c["emisor_nombre"], c["receptor_rfc"],
            _tot(c["subtotal"]), _tot(c["iva"]), _tot(c["total"]),
            "MXN", c["descripcion"], c["categoria"], c["confianza"],
            None, c["valido"], c["requires_human_review"], None, None, None,
            c["status"], datetime.now(timezone.utc).isoformat(),
        ])
    _insert(conn, "invoices",
            ["tenant_id", "folio_fiscal", "archivo", "fecha", "tipo", "serie", "folio",
             "emisor_rfc", "emisor_nombre", "receptor_rfc", "subtotal", "iva", "total",
             "moneda", "descripcion", "categoria", "confianza", "razon_clasificacion",
             "valido", "requires_human_review", "issues", "erp_poliza", "erp_status",
             "status", "procesado_en"],
            invoices_rows, placeholder)

    tx_rows: List[List[Any]] = []
    for i, t in enumerate(ds["transacciones"], start=1):
        data = json.dumps({
            "fecha": t["fecha"], "descripcion": t["descripcion"],
            "tipo": t["tipo"], "monto": t["monto"], "referencia": t["referencia"],
            "beneficiario": t["beneficiario"], "saldo": t["saldo"],
        })
        tx_rows.append([t["tenant_idx"] + 1, t["tx_id"], t["banco"],
                        f"estado_cuenta_{t['banco']}.csv", data])
    _insert(conn, "bank_transactions", ["tenant_id", "tx_id", "banco", "filename", "data"],
            tx_rows, placeholder)

    nomina_rows: List[List[Any]] = []
    for i, n in enumerate(ds["nominas"], start=1):
        nomina_rows.append([
            n["tenant_idx"] + 1, n["empleado_nombre"], n["rfc"], n["fecha_periodo"],
            n["tipo_regimen"], n["dias_pagados"], _tot(n["sueldo_diario"]),
            _tot(n["total"]), _tot(n["liquido"]),
        ])
    _insert(conn, "nominas",
            ["tenant_id", "empleado_nombre", "rfc", "fecha_periodo", "tipo_regimen",
             "dias_pagados", "sueldo_diario", "total", "liquido"],
            nomina_rows, placeholder)

    doc_rows: List[List[Any]] = []
    for d in ds["documents"]:
        doc_rows.append([
            d["id"], d["tenant_id"], d["name"], d["category"], d["content_type"],
            d["size"], d["sha256"], d["storage_path"], d["version"],
            json.dumps(d["metadata"]), json.dumps(d["tags"]), d["status"],
            d["created_by"], d["created_at"], d["updated_at"],
        ])
    _insert(conn, "documents",
            ["id", "tenant_id", "name", "category", "content_type", "size", "sha256",
             "storage_path", "version", "metadata", "tags", "status", "created_by",
             "created_at", "updated_at"],
            doc_rows, placeholder)
    conn.commit()


def _conectar(db: Optional[str]) -> Any:
    dsn = db
    if not dsn:
        dsn = os.environ.get("B2B_DB_URL") or os.environ.get("B2B_DB_PATH")
    if not dsn:
        dsn = os.path.join(_BASE_DIR, "b2b_ai.db")
    if dsn.startswith("postgres") or dsn.startswith("postgresql"):
        try:
            import psycopg2  # type: ignore
        except ImportError as e:
            sys.exit(f"Necesitas psycopg2 para Postgres (pip install psycopg2-binary). {e}")
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return conn
    if "://" in dsn:
        sys.exit(f"DSN no soportado: {dsn}. Usa SQLite (ruta) o postgresql://")
    os.makedirs(os.path.dirname(os.path.abspath(dsn)), exist_ok=True)
    return sqlite3.connect(dsn)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="Ruta SQLite o DSN Postgres. Default: B2B_DB_URL | B2B_DB_PATH | b2b_ai.db")
    ap.add_argument("--seed", type=int, default=_SEED, help="Semilla determinista (default 42)")
    ap.add_argument("--json-only", action="store_true",
                    help="Solo genera los JSON en scripts/seed_data/ (no toca la BD)")
    ap.add_argument("--seed-dir", default=_SEED_DIR,
                    help="Carpeta de salida de los JSON (default scripts/seed_data)")
    args = ap.parse_args(argv)

    ds = generar_dataset(args.seed)
    os.makedirs(args.seed_dir, exist_ok=True)

    def dump(name: str, payload: Any) -> None:
        path = os.path.join(args.seed_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"  ✓ {path}")

    print("Generando seed_data/ ...")
    dump("tenants.json", ds["tenants"])
    dump("clientes.json", ds["clientes"])
    dump("cfdis.json", ds["cfdis"])
    dump("transacciones.json", ds["transacciones"])
    dump("nominas.json", ds["nominas"])
    dump("documents.json", ds["documents"])
    dump("documents_state.json", ds["documents_state"])  # formato DOCS_STATE_FILE
    dump("roles.json", ds["roles"])

    if args.json_only:
        print("\n--json-only: no se tocó la BD.")
        return 0

    print(f"\nPoblando BD ({args.db or 'auto'}) ...")
    conn = _conectar(args.db)
    try:
        poblar_db(conn, ds)
        print("  BD poblada correctamente.")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    resumen(ds)
    return 0


def resumen(ds: Dict[str, Any]) -> None:
    n_tenants = len(ds["tenants"])
    n_clientes = len(ds["clientes"])
    n_cfdi = len(ds["cfdis"])
    n_tx = len(ds["transacciones"])
    n_nom = len(ds["nominas"])
    n_doc = len(ds["documents"])
    print("\n=== RESUMEN DEMO ===")
    print(f"  Tenants              : {n_tenants}")
    print(f"  Clientes/tenant      : {n_clientes // n_tenants}")
    print(f"  CFDIs (emitidos+recibidos) : {n_cfdi}  ({n_cfdi // n_tenants} por tenant)")
    print(f"  Transacciones        : {n_tx}  ({n_tx // n_tenants} por tenant)")
    print(f"  Nóminas              : {n_nom}  ({n_nom // n_tenants} por tenant)")
    print(f"  Documentos           : {n_doc}  ({n_doc // n_tenants} por tenant)")
    print(f"  Roles                : {', '.join(ds['roles'].keys())}")
    print(f"  Usuario admin/tenant : 1")
    for i, t in enumerate(ds["tenants"], start=1):
        print(f"    tenant {i} admin: {t['admin_email']} (role=admin)")


if __name__ == "__main__":
    sys.exit(main())
