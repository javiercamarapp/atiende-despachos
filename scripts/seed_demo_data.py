# -*- coding: utf-8 -*-
"""seed_demo_data.py — Seeder de datos demo realistas para el primer piloto.

Genera un dataset completo de un despacho contable mexicano para poblar la
aplicación y validar el flujo end-to-end del piloto:

    - 1 tenant  (despacho contable demo: "Grupo Contable MX S.A. de C.V.")
    - 5 usuarios (admin, contador senior, contador junior, auditor, viewer)
    - 100 CFDIs (emisores variados, montos realistas $1,000-$500,000 MXN)
    - 3 cuentas bancarias (BBVA, Banorte, Santander) con transacciones
    - 10 empleados de ejemplo para nóminas
    - 5 clientes del despacho
    - Dashboard con KPIs poblados

Salida (determinista, `random.seed` fijo para reproducibilidad):
    - JSON por entidad (tenant.json, users.json, cfdis.json,
      bank_accounts.json, bank_transactions.json, employees.json,
      clients.json, dashboard.json) + manifest.json
    - SQL inserts (seed_demo_data.sql) listos para correr contra el schema
      de `b2b_ai.db` (o el Postgres de producción vía `psql`).

Ejecución:
    python scripts/seed_demo_data.py                        # JSON + SQL
    python scripts/seed_demo_data.py --out-dir /tmp/seed    # salida custom
    python scripts/seed_demo_data.py --sql-only             # solo SQL
    python scripts/seed_demo_data.py --db b2b_ai.db         # además persiste en SQLite

Sin dependencias del repo para la GENERACIÓN (stdlib puro), de modo que el
script corre igual desde /private/tmp; la persistencia a DB es opcional y
solo se activa con `--db`.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

_SEED = 42
_RAZON_SOCIAL = "Grupo Contable MX S.A. de C.V."
_RFC_TENANT = "GCM920101AB1"

# Bancos mexicanos: (institución, CLABE demo, nombre corto).
_BANCOS = [
    ("BBVA", "012180001234567899", "Cuenta operativa BBVA"),
    ("Banorte", "072180001234567890", "Cuenta nómina Banorte"),
    ("Santander", "014027000000000000", "Cuenta pagos Santander"),
]

# Emisores frecuentes de un despacho contable (RFCs mock válidos).
_EMISORES = [
    ("GES860101A10", "Grupo Empresarial Siglo XXI, S.A. de C.V."),
    ("MTC951205AB2", "Mueblería Torres del Centro, S.A. de C.V."),
    ("RGE920815C12", "Restaurantes La Grande, S.A. de C.V."),
    ("COP771231D34", "Comercializadora del Pacífico, S.A. de C.V."),
    ("FRE040101E56", "Ferretería El Roble, S.A. de C.V."),
    ("TRC881213F78", "Transportes Ruta Central, S.A. de C.V."),
    ("ABG970314G90", "Abarrotes La Guadalupana, S.A. de C.V."),
    ("IND550810H11", "Industrias Metalúrgicas del Norte, S.A. de C.V."),
    ("CVS600525J22", "Consultora Vallarta y Socios, S.C."),
    ("SEP740618K33", "Servicios de Logística Peninsular, S.A. de C.V."),
    ("TEC050315AB2", "Tecnología Avanzada SA de CV"),
    ("FIN180601VW7", "Finanzas y Seguros SC"),
    ("SER080321LP9", "Servicios Profesionales Integrales"),
    ("LOG031205MN6", "Logística del Norte SA de CV"),
]

_CONCEPTOS = [
    "Servicios profesionales de contabilidad",
    "Honorarios por consultoría fiscal",
    "Renta mensual de oficina",
    "Papelería y artículos de oficina",
    "Mantenimiento de equipo de cómputo",
    "Publicidad y mercadotecnia digital",
    "Licencias de software contable",
    "Capacitación y actualización fiscal",
    "Servicios de mensajería y paquetería",
    "Mantenimiento de sistemas de seguridad",
    "Teléfono e internet",
    "Servicios de limpieza",
]

_BANCO_DESCRIPCIONES = [
    "Transferencia SPEI recibida",
    "Pago de nómina",
    "Depósito en ventanilla",
    "Pago a proveedor",
    "Retiro en cajero",
    "Pago de impuestos SAT",
    "Transferencia SPEI enviada",
    "Cargo por comisión bancaria",
    "Interés generado",
    "Pago de servicios (luz/agua)",
]

_ROLES = ["admin", "contador_senior", "contador_junior", "auditor", "viewer"]

_EMPLOYEE_FIRST = ["Ana", "Luis", "Mónica", "Jorge", "Sofía", "Carlos",
                   "María", "Pedro", "Lucía", "Roberto"]
_EMPLOYEE_LAST = ["García", "Martínez", "López", "Hernández", "González",
                  "Pérez", "Sánchez", "Ramírez", "Torres", "Flores"]

_CLIENTS = [
    ("Bodegas del Norte, S.A. de C.V.", "BDN920101AB1"),
    ("Farmacias Salud Total, S. de R.L.", "FST881213CD2"),
    ("Taller Mecánico El Motor, S.A.", "TME040101EF3"),
    ("Distribuidora Alimentos del Bajío", "DAB970314GH4"),
    ("Inmobiliaria Reforma 300, S.C.", "IRP550810IJ5"),
]

# Categorías contables (match b2b_ai/services/classify.py).
_CATEGORIAS = ["Gastos en general", "Servicios profesionales", "Nómina",
               "Transporte y logística", "Comunicaciones y marketing",
               "Mobiliario y equipo", "Inversión / capital", "Combustibles"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(_uuid.uuid4())


# ---------------------------------------------------------------------------
# Generadores por entidad
# ---------------------------------------------------------------------------

def generate_tenant() -> Dict[str, Any]:
    """El despacho contable demo (tenant del primer piloto)."""
    return {
        "tenant_id": 1,
        "name": _RAZON_SOCIAL,
        "razon_social": _RAZON_SOCIAL,
        "rfc": _RFC_TENANT,
        "regimen_fiscal": "601",          # General de Ley Personas Morales
        "codigo_postal": "06600",
        "calle": "Av. Paseo de la Reforma 300",
        "colonia": "Juárez",
        "municipio": "Cuauhtémoc",
        "estado": "CDMX",
        "plan": "pro",
        "fuente_datos": "cfdi_upload",
        "creado_en": _utcnow().isoformat(),
    }


def generate_users(tenant_id: int = 1, n: int = 5) -> List[Dict[str, Any]]:
    """Cinco usuarios del despacho con sus roles y permisos."""
    personas = [
        ("Lic. Mariana Fernández", "admin"),
        ("C.P. Ricardo Aguilar", "contador_senior"),
        ("C.P. Daniela Ortiz", "contador_junior"),
        ("Lic. Héctor Ruiz", "auditor"),
        ("Ing. Laura Méndez", "viewer"),
    ]
    users = []
    for i, (nombre, rol) in enumerate(personas[:n], start=1):
        # email limpio: inicial + primer apellido, sin acentos ni títulos
        parts = nombre.replace(".", "").replace("Lic ", "").replace("C.P. ", "") \
                       .replace("Ing. ", "").split()
        first = parts[0][0].lower()
        last = parts[-1].lower() if len(parts) > 1 else parts[0].lower()
        accent_map = str.maketrans("áéíóúñ", "aeioun")
        email = f"{first}{last.translate(accent_map)}@grupocontable.mx"
        users.append({
            "user_id": i,
            "tenant_id": tenant_id,
            "name": nombre,
            "email": email,
            "role": rol,
            "active": True,
            "creado_en": _utcnow().isoformat(),
        })
    return users


def generate_cfdis(n: int = 100, tenant_rfc: str = _RFC_TENANT) -> List[Dict[str, Any]]:
    """Genera `n` CFDIs con montos realistas entre $1,000 y $500,000 MXN."""
    random.seed(_SEED)
    cfdis: List[Dict[str, Any]] = []
    used_uuids: set = set()
    today = datetime.now(timezone.utc)
    for i in range(n):
        emisor_rfc, emisor_nombre = random.choice(_EMISORES)
        # Monto log-uniforme para tener pocos montos altos y muchos bajos.
        subtotal = round(random.uniform(1000, 500_000), 2)
        iva = round(subtotal * 0.16, 2)
        total = round(subtotal + iva, 2)
        uuid_val = ""
        while True:
            candidate = str(_uuid.uuid4()).upper()
            if candidate not in used_uuids:
                used_uuids.add(candidate)
                uuid_val = candidate
                break
        fecha = today - timedelta(days=random.randint(0, 365))
        cfdis.append({
            "cfdi_id": i + 1,
            "tenant_id": 1,
            "uuid": uuid_val,
            "serie": random.choice(["A", "B", "C", "D"]),
            "folio": f"{i+1:04d}",
            "fecha": fecha.replace(microsecond=0).isoformat(),
            "tipo": "I",                       # Ingreso
            "emisor_rfc": emisor_rfc,
            "emisor_nombre": emisor_nombre,
            "receptor_rfc": tenant_rfc,
            "receptor_nombre": _RAZON_SOCIAL,
            "subtotal": round(subtotal, 2),
            "iva": round(iva, 2),
            "total": round(total, 2),
            "moneda": "MXN",
            "descripcion": random.choice(_CONCEPTOS),
            "categoria": random.choice(_CATEGORIAS),
            "metodo_pago": random.choice(["PUE", "PPD"]),
            "forma_pago": random.choice(["01", "03", "99", "04"]),
            "status": "procesado",
        })
    return cfdis


def generate_bank_accounts() -> List[Dict[str, Any]]:
    """Tres cuentas bancarias (BBVA, Banorte, Santander)."""
    random.seed(_SEED + 10)
    accounts = []
    for i, (banco, clabe, label) in enumerate(_BANCOS, start=1):
        accounts.append({
            "account_id": f"acc-{banco.lower()}",
            "tenant_id": 1,
            "provider": banco,
            "clabe": clabe,
            "account_label": label,
            "currency": "MXN",
            "conectado_en": _utcnow().isoformat(),
        })
    return accounts


def generate_bank_transactions(n: int = 40) -> List[Dict[str, Any]]:
    """Transacciones repartidas entre las 3 cuentas."""
    random.seed(_SEED + 11)
    txs: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc)
    clabes = [b[1] for b in _BANCOS]
    for i in range(n):
        monto = round(random.uniform(-120_000, 300_000), 2)
        txs.append({
            "tx_id": f"demo-tx-{i+1:04d}",
            "tenant_id": 1,
            "account_clabe": random.choice(clabes),
            "banco": random.choice([b[0] for b in _BANCOS]),
            "tipo": "deposito" if monto >= 0 else "retiro",
            "monto_mxn": round(abs(monto), 2),
            "concepto": random.choice(_BANCO_DESCRIPCIONES),
            "referencia": f"REF{random.randint(100000000, 999999999)}",
            "fecha": (today - timedelta(days=random.randint(0, 120)))
                     .replace(microsecond=0).isoformat(),
        })
    return txs


def generate_employees(n: int = 10) -> List[Dict[str, Any]]:
    """Diez empleados de ejemplo para nóminas."""
    random.seed(_SEED + 20)
    employees = []
    rfc_set: set = set()
    for i in range(n):
        nombre = f"{_EMPLOYEE_FIRST[i]} {_EMPLOYEE_LAST[i]}"
        employees.append({
            "employee_id": i + 1,
            "tenant_id": 1,
            "name": nombre,
            "rfc": f"EMP{i+1:02d}010101AB{i % 10}",
            "curp": f"{nombre[0:1]}A{i+1:02d}010101HDFRRL0{i % 10}",
            "puesto": random.choice(["Contador", "Analista fiscal", "Auxiliar",
                                     "Recepcionista", "Atención a clientes"]),
            "sueldo_mensual": round(random.uniform(12_000, 60_000), 2),
            "nss": f"{random.randint(1000000000, 9999999999)}",
            "banco_pago": random.choice(["BBVA", "Banorte", "Santander"]),
            "fecha_ingreso": (datetime.now(timezone.utc)
                              - timedelta(days=random.randint(90, 3000)))
                              .date().isoformat(),
        })
        rfc_set.add(employees[-1]["rfc"])
    return employees


def generate_clients() -> List[Dict[str, Any]]:
    """Cinco clientes del despacho."""
    clients = []
    for i, (nombre, rfc) in enumerate(_CLIENTS, start=1):
        clients.append({
            "client_id": i,
            "tenant_id": 1,
            "name": nombre,
            "rfc": rfc,
            "email": f"contacto@client{i}.mx",
            "servicio": random.choice(["Contabilidad mensual", "Fiscal anual",
                                       "Nómina y RRHH", "Auditoría"]),
            "facturas_periodo": random.randint(3, 25),
            "monto_periodo": round(random.uniform(50_000, 900_000), 2),
            "desde": (datetime.now(timezone.utc)
                      - timedelta(days=random.randint(120, 2500))).date().isoformat(),
        })
    return clients


def generate_dashboard(tenant: Dict[str, Any],
                       cfdis: List[Dict[str, Any]],
                       bank_txs: List[Dict[str, Any]],
                       clients: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Dashboard con KPIs poblados a partir de los datos generados."""
    monto_mes = round(sum(c["total"] for c in cfdis), 2)
    iva_mes = round(sum(c["iva"] for c in cfdis), 2)
    ingresos_bancarios = round(sum(t["monto_mxn"] for t in bank_txs
                                   if t["tipo"] == "deposito"), 2)
    egresos_bancarios = round(sum(t["monto_mxn"] for t in bank_txs
                                  if t["tipo"] == "retiro"), 2)
    cats: Dict[str, int] = {}
    for c in cfdis:
        cats[c["categoria"]] = cats.get(c["categoria"], 0) + 1
    top_cats = sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "tenant_id": tenant["tenant_id"],
        "kpis": {
            "facturas_periodo": len(cfdis),
            "monto_periodo": monto_mes,
            "iva_periodo": iva_mes,
            "ingresos_bancarios": ingresos_bancarios,
            "egresos_bancarios": egresos_bancarios,
            "clientes_activos": len(clients),
            "tasa_procesamiento": "98.5%",
        },
        "top_categorias": [{"categoria": k, "count": v} for k, v in top_cats],
        "saldo_cuentas": {
            "BBVA": round(monto_mes * 0.4, 2),
            "Banorte": round(monto_mes * 0.35, 2),
            "Santander": round(monto_mes * 0.25, 2),
        },
    }


# ---------------------------------------------------------------------------
# Ensamblado del dataset
# ---------------------------------------------------------------------------

def build_dataset(cfdis: int = 100, bank_txs: int = 40, employees: int = 10) -> Dict[str, Any]:
    tenant = generate_tenant()
    return {
        "tenant": tenant,
        "users": generate_users(tenant["tenant_id"]),
        "cfdis": generate_cfdis(cfdis, tenant["rfc"]),
        "bank_accounts": generate_bank_accounts(),
        "bank_transactions": generate_bank_transactions(bank_txs),
        "employees": generate_employees(employees),
        "clients": generate_clients(),
        "dashboard": None,  # se rellena abajo para tener todos los datasets
        "generated_at": _utcnow().isoformat(),
    }


def _fill_dashboard(dataset: Dict[str, Any]) -> None:
    dataset["dashboard"] = generate_dashboard(
        dataset["tenant"], dataset["cfdis"], dataset["bank_transactions"],
        dataset["clients"])


# ---------------------------------------------------------------------------
# Persistencia: JSON + SQL inserts
# ---------------------------------------------------------------------------

_JSON_KEYS = ["tenant", "users", "cfdis", "bank_accounts", "bank_transactions",
              "employees", "clients", "dashboard"]


def _persist_json(dataset: Dict[str, Any], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for key in _JSON_KEYS:
        path = os.path.join(out_dir, f"{key}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dataset[key], fh, ensure_ascii=False, indent=2)
        paths.append(path)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "counts": {
                "tenants": 1,
                "users": len(dataset["users"]),
                "cfdis": len(dataset["cfdis"]),
                "bank_accounts": len(dataset["bank_accounts"]),
                "bank_transactions": len(dataset["bank_transactions"]),
                "employees": len(dataset["employees"]),
                "clients": len(dataset["clients"]),
            },
            "generated_at": dataset["generated_at"],
        }, fh, ensure_ascii=False, indent=2)
    paths.append(os.path.join(out_dir, "manifest.json"))
    return paths


def _sql_str(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _build_sql(dataset: Dict[str, Any]) -> str:
    """Genera los INSERT statements listos para el schema de b2b_ai.db."""
    lines = [
        "-- ============================================================",
        "-- Likida AI — seed de datos demo del piloto",
        f"-- generado: {dataset['generated_at']}",
        "-- ============================================================",
        "",
        "-- tenant",
        f"INSERT INTO tenants (id, name, rfc) VALUES "
        f"({dataset['tenant']['tenant_id']}, {_sql_str(dataset['tenant']['name'])}, "
        f"{_sql_str(dataset['tenant']['rfc'])});",
        "",
        "-- usuarios",
    ]
    for u in dataset["users"]:
        lines.append(
            f"INSERT INTO users (id, tenant_id, name, email, role) VALUES "
            f"({u['user_id']}, {u['tenant_id']}, {_sql_str(u['name'])}, "
            f"{_sql_str(u['email'])}, {_sql_str(u['role'])});")
    lines.append("")
    lines.append("-- cfdis")
    for c in dataset["cfdis"]:
        lines.append(
            f"INSERT INTO invoices (tenant_id, folio_fiscal, fecha, serie, folio, "
            f"emisor_rfc, emisor_nombre, receptor_rfc, subtotal, iva, total, "
            f"moneda, descripcion) VALUES "
            f"({c['tenant_id']}, {_sql_str(c['uuid'])}, {_sql_str(c['fecha'])}, "
            f"{_sql_str(c['serie'])}, {_sql_str(c['folio'])}, "
            f"{_sql_str(c['emisor_rfc'])}, {_sql_str(c['emisor_nombre'])}, "
            f"{_sql_str(c['receptor_rfc'])}, {c['subtotal']}, {c['iva']}, "
            f"{c['total']}, {_sql_str(c['moneda'])}, {_sql_str(c['descripcion'])});")
    lines.append("")
    lines.append("-- cuentas bancarias")
    for a in dataset["bank_accounts"]:
        lines.append(
            f"INSERT INTO bank_accounts (id, tenant_id, provider, clabe, label) VALUES "
            f"({_sql_str(a['account_id'])}, {a['tenant_id']}, "
            f"{_sql_str(a['provider'])}, {_sql_str(a['clabe'])}, "
            f"{_sql_str(a['account_label'])});")
    lines.append("")
    lines.append("-- transacciones bancarias")
    for t in dataset["bank_transactions"]:
        lines.append(
            f"INSERT INTO bank_transactions (tenant_id, account_clabe, banco, tipo, "
            f"monto_mxn, concepto, fecha) VALUES "
            f"({t['tenant_id']}, {_sql_str(t['account_clabe'])}, "
            f"{_sql_str(t['banco'])}, {_sql_str(t['tipo'])}, "
            f"{t['monto_mxn']}, {_sql_str(t['concepto'])}, {_sql_str(t['fecha'])});")
    lines.append("")
    lines.append("-- empleados")
    for e in dataset["employees"]:
        lines.append(
            f"INSERT INTO employees (id, tenant_id, name, rfc, puesto, "
            f"sueldo_mensual, banco_pago) VALUES "
            f"({e['employee_id']}, {e['tenant_id']}, {_sql_str(e['name'])}, "
            f"{_sql_str(e['rfc'])}, {_sql_str(e['puesto'])}, {e['sueldo_mensual']}, "
            f"{_sql_str(e['banco_pago'])});")
    lines.append("")
    lines.append("-- clientes")
    for cl in dataset["clients"]:
        lines.append(
            f"INSERT INTO clients (id, tenant_id, name, rfc, email, servicio) VALUES "
            f"({cl['client_id']}, {cl['tenant_id']}, {_sql_str(cl['name'])}, "
            f"{_sql_str(cl['rfc'])}, {_sql_str(cl['email'])}, "
            f"{_sql_str(cl['servicio'])});")
    lines.append("")
    return "\n".join(lines)


def _persist_sql(dataset: Dict[str, Any], path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_build_sql(dataset))


def _persist_db(dataset: Dict[str, Any], db_path: str) -> None:
    """Persiste el dataset en la base SQLite del repo vía `Database` (opcional)."""
    try:
        from b2b_ai.db.db import Database
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"DB no disponible (¿corres desde el repo?): {exc}")
    db = Database(db_path)
    t = dataset["tenant"]
    tenant_id = db.create_tenant(t["name"], rfc=t["rfc"])
    for u in dataset["users"]:
        db.create_user(tenant_id, u["name"], u["email"])
    for c in dataset["cfdis"]:
        datos = {
            "folio_fiscal": c["uuid"], "fecha": c["fecha"], "tipo": c["tipo"],
            "serie": c["serie"], "folio": c["folio"],
            "emisor_rfc": c["emisor_rfc"], "emisor_nombre": c["emisor_nombre"],
            "receptor_rfc": c["receptor_rfc"], "subtotal": c["subtotal"],
            "iva": c["iva"], "total": c["total"], "moneda": c["moneda"],
            "descripcion": c["descripcion"],
        }
        db.insert_invoice(tenant_id, datos,
                          {"categoria": c["categoria"], "confianza": 0.9},
                          {"ok": True, "issues": []})
    db.close()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera datos demo realistas de un despacho contable MX.")
    parser.add_argument("--out-dir", default="demo-output/seed",
                        help="Directorio de salida JSON (default: demo-output/seed)")
    parser.add_argument("--sql-path", default="",
                        help="Ruta del archivo SQL (default: <out-dir>/seed_demo_data.sql)")
    parser.add_argument("--sql-only", action="store_true",
                        help="Solo genera el SQL (sin JSON)")
    parser.add_argument("--db", default="",
                        help="Ruta opcional a b2b_ai.db para persistir en SQLite")
    parser.add_argument("--cfdis", type=int, default=100,
                        help="Número de CFDIs (default 100)")
    parser.add_argument("--txs", type=int, default=40,
                        help="Número de transacciones bancarias (default 40)")
    args = parser.parse_args(argv)

    dataset = build_dataset(cfdis=args.cfdis, bank_txs=args.txs)
    _fill_dashboard(dataset)

    lines = ["Datos demo generados:",
             f"  Despacho: {dataset['tenant']['name']} (RFC {dataset['tenant']['rfc']})",
             f"  Usuarios: {len(dataset['users'])}",
             f"  CFDIs: {len(dataset['cfdis'])}",
             f"  Cuentas bancarias: {len(dataset['bank_accounts'])}",
             f"  Transacciones: {len(dataset['bank_transactions'])}",
             f"  Empleados: {len(dataset['employees'])}",
             f"  Clientes: {len(dataset['clients'])}"]

    if not args.sql_only:
        json_paths = _persist_json(dataset, args.out_dir)
        lines.append(f"  JSON: {', '.join(json_paths)}")

    sql_path = args.sql_path or os.path.join(args.out_dir, "seed_demo_data.sql")
    _persist_sql(dataset, sql_path)
    lines.append(f"  SQL: {sql_path}")

    if args.db:
        _persist_db(dataset, args.db)
        lines.append(f"  SQLite: {args.db}")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
