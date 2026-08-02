# -*- coding: utf-8 -*-
"""demo_data.py — Genera y persiste datos de demo para el primer piloto.

Crea un dataset determinista (con `random.seed` fijo) para reproducibilidad:
    - Un despacho contable ficticio (tenant) con RFC y datos fiscales realistas.
    - 50 CFDIs de muestra (RFCs mock válidos, montos MXN realistas).
    - 20 transacciones bancarias (bancos MX, SPEI/transferencias, montos MXN).

Los datos se generan con funciones puras (sin dependencias del repo) para que
sean unitestables de forma aislada; la persistencia opcional en la base SQLite
del repo se hace vía `Database` de `b2b_ai.db`.

Ejecución:
    python -m seed.demo_data                      # escribe a demo-output/seed/*
    python -m seed.demo_data --db b2b_ai.db       # además persiste en SQLite
    python -m seed.demo_data --cfdis 100 --txs 40 # tamaños custom
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
_NUMEROS_CUENTA = (
    "0123456789",
    "012180001234567899",
    "012320011111111111",
    "014027000000000000",
    "002030000000000000",
)

# Bancos mexicanos comunes con su CLABE/institución.
_BANCOS = ["BBVA", "Banorte", "Santander", "HSBC", "Banamex", "Scotiabank"]

# Emisores frecuentes de un despacho contable (RFCs mock válidos, 12/13 chars).
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rfc_mock(existing: set) -> str:
    """Genera un RFC mock válido (12 o 13 caracteres) no repetido."""
    while True:
        n = random.choice([12, 13])
        if n == 12:
            rfc = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
            rfc += "".join(random.choice("0123456789") for _ in range(6))
            rfc += "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(3))
        else:
            rfc = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4))
            rfc += "".join(random.choice("0123456789") for _ in range(6))
            rfc += "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(3))
        if rfc not in existing:
            existing.add(rfc)
            return rfc


def generate_despacho() -> Dict[str, Any]:
    """Despacho contable ficticio (el tenant del primer piloto)."""
    return {
        "tenant_id": 1,
        "name": "Despacho Contable Fides, S.C.",
        "rfc": "DCF920101AB1",
        "regimen_fiscal": "601",          # General de Ley Personas Morales
        "codigo_postal": "06600",
        "razon_social": "Despacho Contable Fides, S.C.",
        "calle": "Av. Paseo de la Reforma 300",
        "colonia": "Juárez",
        "municipio": "Cuauhtémoc",
        "estado": "CDMX",
        "admin": {
            "name": "Lic. Mariana Fernández",
            "email": "mariana.fernandez@fides.mx",
            "role": "admin",
        },
        "fuente_datos": "cfdi_upload",
        "plan": "pro",
        "creado_en": _utcnow().isoformat(),
    }


def generate_cfdis(n: int = 50, despacho_rfc: str = "DCF920101AB1") -> List[Dict[str, Any]]:
    """Genera `n` CFDIs de muestra con montos MXN realistas.

    El receptor es el despacho (despacho_rfc); los emisores son RFCs mock.
    """
    random.seed(_SEED)
    cfdis: List[Dict[str, Any]] = []
    used_uuids: set = set()
    today = datetime.now(timezone.utc)
    for i in range(n):
        emisor_rfc, emisor_nombre = random.choice(_EMISORES)
        subtotal = round(random.uniform(500, 250_000), 2)
        iva = round(subtotal * 0.16, 2)
        total = round(subtotal + iva, 2)
        uuid_val = ""
        while True:
            candidate = str(_uuid.uuid4()).upper()
            if candidate not in used_uuids:
                used_uuids.add(candidate)
                uuid_val = candidate
                break
        fecha = today - timedelta(days=random.randint(0, 180))
        cfdis.append({
            "uuid": uuid_val,
            "serie": random.choice(["A", "B", "C", "D"]),
            "folio": f"{i+1:04d}",
            "fecha": fecha.replace(microsecond=0).isoformat(),
            "tipo": "I",                      # Ingreso
            "emisor_rfc": emisor_rfc,
            "emisor_nombre": emisor_nombre,
            "receptor_rfc": despacho_rfc,
            "receptor_nombre": "Despacho Contable Fides, S.C.",
            "subtotal": round(subtotal, 2),
            "iva": round(iva, 2),
            "total": round(total, 2),
            "moneda": "MXN",
            "descripcion": random.choice(_CONCEPTOS),
            "metodo_pago": random.choice(["PUE", "PPD"]),
            "forma_pago": random.choice(["01", "03", "99", "04"]),
        })
    return cfdis


def generate_bank_transactions(n: int = 20, account: str = "0123456789") -> List[Dict[str, Any]]:
    """Genera `n` transacciones bancarias MX (SPEI/transferencias)."""
    random.seed(_SEED + 1)
    txs: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc)
    for i in range(n):
        monto = round(random.uniform(-120_000, 300_000), 2)
        txs.append({
            "tx_id": f"demo-tx-{i+1:04d}",
            "banco": random.choice(_BANCOS),
            "cuenta": account,
            "tipo": "deposito" if monto >= 0 else "retiro",
            "monto_mxn": round(abs(monto), 2),
            "concepto": random.choice(_BANCO_DESCRIPCIONES),
            "referencia": f"REF{random.randint(100000000, 999999999)}",
            "fecha": (today - timedelta(days=random.randint(0, 120))).replace(microsecond=0).isoformat(),
        })
    return txs


def build_dataset(cfdis: int = 50, txs: int = 20) -> Dict[str, Any]:
    """Ensambla el dataset completo (despacho + CFDIs + transacciones)."""
    despacho = generate_despacho()
    return {
        "despacho": despacho,
        "cfdis": generate_cfdis(cfdis, despacho_rfc=despacho["rfc"]),
        "bank_transactions": generate_bank_transactions(txs, _NUMEROS_CUENTA[0]),
        "generated_at": _utcnow().isoformat(),
        "counts": {
            "despachos": 1,
            "cfdis": cfdis,
            "bank_transactions": txs,
        },
    }


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _persist_json(dataset: Dict[str, Any], out_dir: str) -> List[str]:
    """Escribe el dataset a archivos JSON en `out_dir`. Devuelve rutas."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for key in ("despacho", "cfdis", "bank_transactions"):
        path = os.path.join(out_dir, f"{key}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dataset[key], fh, ensure_ascii=False, indent=2)
        paths.append(path)
    # Manifest con los conteos.
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"counts": dataset["counts"], "generated_at": dataset["generated_at"]},
                  fh, ensure_ascii=False, indent=2)
    return paths


def _persist_db(dataset: Dict[str, Any], db_path: str) -> None:
    """Persiste el dataset en la base SQLite del repo vía `Database`."""
    try:
        from b2b_ai.db.db import Database
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"DB no disponible (¿corres desde el repo?): {exc}")

    db = Database(db_path)
    despacho = dataset["despacho"]
    tenant_id = db.create_tenant(despacho["name"], rfc=despacho["rfc"])
    db.create_user(tenant_id, despacho["admin"]["name"], despacho["admin"]["email"])
    for cfdi in dataset["cfdis"]:
        datos = {
            "folio_fiscal": cfdi["uuid"],
            "fecha": cfdi["fecha"],
            "tipo": cfdi["tipo"],
            "serie": cfdi["serie"],
            "folio": cfdi["folio"],
            "emisor_rfc": cfdi["emisor_rfc"],
            "emisor_nombre": cfdi["emisor_nombre"],
            "receptor_rfc": cfdi["receptor_rfc"],
            "subtotal": cfdi["subtotal"],
            "iva": cfdi["iva"],
            "total": cfdi["total"],
            "moneda": cfdi["moneda"],
            "descripcion": cfdi["descripcion"],
        }
        db.insert_invoice(tenant_id, datos, {"categoria": "desconocido", "confianza": 0.0},
                          {"ok": True, "issues": []})
    db.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Genera datos de demo para el piloto de Likida AI.")
    parser.add_argument("--db", default="", help="Ruta opcional a b2b_ai.db para persistir en SQLite")
    parser.add_argument("--out-dir", default="demo-output/seed", help="Directorio de salida JSON")
    parser.add_argument("--cfdis", type=int, default=50, help="Número de CFDIs (default 50)")
    parser.add_argument("--txs", type=int, default=20, help="Número de transacciones (default 20)")
    args = parser.parse_args(argv)

    dataset = build_dataset(cfdis=args.cfdis, txs=args.txs)
    paths = _persist_json(dataset, args.out_dir)

    lines = [
        "Datos de demo generados:",
        f"  Despacho contable: {dataset['despacho']['name']} (RFC {dataset['despacho']['rfc']})",
        f"  CFDIs: {dataset['counts']['cfdis']}",
        f"  Transacciones bancarias: {dataset['counts']['bank_transactions']}",
        f"  JSON: {', '.join(paths)}",
    ]
    if args.db:
        _persist_db(dataset, args.db)
        lines.append(f"  SQLite: {args.db}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
