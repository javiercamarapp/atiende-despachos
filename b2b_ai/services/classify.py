# -*- coding: utf-8 -*-
"""
classify.py — Clasificación contable de un CFDI parseado.

Categorías: gasto_operativo, inversion, activo_fijo, nomina, desconocido.
Híbrido: reglas determinísticas de palabras clave + ClaveProdServ. El modelo
LLM queda reservado para lo ambiguo (aquí se marca confianza baja → humano).

La clasificación NUNCA decide por sí sola la deducibilidad ni el registro
fiscal definitivo: produce una PROPUESTA con confianza y razón, y flag de
revisión humana cuando la confianza es baja (NIF manda criterio contable,
CFF el fiscal — de `04-leyes-fiscales.md`).
"""
from __future__ import annotations

from b2b_ai.cfdi import catalogs
from typing import Any, Dict, List

KEYWORDS: Dict[str, List[str]] = {
    "nomina": ["nomina", "sueldo", "salario", "percepcion", "aguinaldo",
               "prima vacacional", "complemento de pago", "pago de nomina"],
    "activo_fijo": ["computadora", "laptop", "servidor", "maquinaria",
                    "impresora", "equipo de computo", "vehiculo", "escritorio",
                    "mobiliario", "monitor", "cpu", "ups", "licencia perpetua",
                    "equipo industrial", "equipo de transporte"],
    "inversion": ["desarrollo de software", "consultoria", "asesoria",
                  "capacitacion", "implementacion", "proyecto", "marketing",
                  "publicidad", "campaña", "inversion", "licencia anual",
                  "suscripcion anual", "servicio profesional", "investigacion",
                  "estudio de mercado"],
    "gasto_operativo": ["papeleria", "consumibles", "internet", "telefonia",
                        "renta", "arrendamiento", "energia electrica", "luz",
                        "agua", "combustible", "gasolina", "limpieza",
                        "mantenimiento", "reparacion", "mensualidad",
                        "suscripcion mensual", "envio", "mensajeria", "oficina",
                        "viaticos", "seguro", "cafeteria", "impresion"],
}

PRIORITY: List[str] = ["nomina", "activo_fijo", "inversion", "gasto_operativo"]

CATEGORIA_NOMBRE: Dict[str, str] = {
    "gasto_operativo": "GASTO OPERATIVO",
    "inversion": "INVERSION",
    "activo_fijo": "ACTIVO FIJO",
    "nomina": "NOMINA",
    "desconocido": "DESCONOCIDO",
}


def classify_cfdi(datos: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve dict {categoria, confianza, razon, requires_human_review}.

    `datos` es la salida de `parse_cfdi` (un CFDI ya parseado). La categoría
    se resuelve por reglas determinísticas: palabras clave de conceptos +
    prefijos de ClaveProdServ + TipoDeComprobante=N. El resultado es una
    PROPUESTA con confianza y razón; `requires_human_review` se activa cuando
    la confianza es baja.
    """
    texto = " ".join(c.get("descripcion", "") for c in datos.get("conceptos", []))
    texto = texto.lower()
    claves = datos.get("claves_prod_serv", [])

    scores = {cat: 0 for cat in KEYWORDS}
    matched = {cat: [] for cat in KEYWORDS}

    for cat, words in KEYWORDS.items():
        for w in words:
            if w in texto:
                scores[cat] += 1
                matched[cat].append(w)

    for cp in claves:
        for cat, prefixes in catalogs.CP_CATEGORIAS.items():
            for p in prefixes:
                if cp.startswith(p) or cp[:6] == p:
                    scores[cat] += 1.5
                    matched[cat].append(f"ClaveProdServ={cp}")

    # Nómina: el TipoDeComprobante N manda categoría
    if datos.get("tipo") == "N":
        scores["nomina"] += 10
        matched["nomina"].append("TipoDeComprobante=N")

    best_cat = None
    best_score = 0.0
    for cat in PRIORITY:
        if scores[cat] > best_score:
            best_cat = cat
            best_score = scores[cat]

    if best_cat is None or best_score <= 0:
        return {"categoria": "desconocido", "confianza": 0.0,
                "razon": "No se encontraron palabras clave", "requires_human_review": True}

    n_matches = sum(len(m) for m in matched.values())
    confianza = min(0.98, 0.55 + 0.20 * n_matches)
    palabras = ", ".join(sorted(set(matched[best_cat])))
    requires = confianza < 0.70 or best_cat == "desconocido"

    return {
        "categoria": best_cat,
        "confianza": round(confianza, 2),
        "razon": f"Coincidencias: {palabras}",
        "requires_human_review": requires,
    }


def main():
    import sys
    import json
    from b2b_ai.cfdi.parser import parse_cfdi

    if len(sys.argv) < 2:
        print("Uso: python3 -m b2b_ai.services.classify <archivo.xml>")
        sys.exit(1)
    datos = parse_cfdi(sys.argv[1])
    print(json.dumps(classify_cfdi(datos), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
