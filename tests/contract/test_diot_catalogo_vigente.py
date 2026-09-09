# -*- coding: utf-8 -*-
"""
tests/contract/test_diot_catalogo_vigente.py — REQ-IVA-017.

Contract test: confirma que los códigos de `TipoOperacion`
(`b2b_ai/features/diot/models.py`) siguen vigentes contra el catálogo REAL
de "tipo de operación" que usa la DIOT (Declaración Informativa de
Operaciones con Terceros).

Estado de la fuente oficial (verificado 2026-09-08, ver también fila
REQ-IVA-017 y la matriz de "Dependencias externas bloqueantes" de
`docs/BLUEPRINT-AGENTES-FISCALES.md`):

- El requisito original cita "Anexo 19 RMF" como la fuente de este
  catálogo. Una búsqueda web el 2026-09-08 indica que el Anexo 19 de la
  RMF vigente corresponde al "Dictamen de Estados Financieros para
  efectos fiscales Tipo II (SIPRED)", NO al catálogo de tipos de
  operación de la DIOT. Esa cita del requisito original parece
  incorrecta; se documenta aquí en vez de "corregirla" silenciosamente,
  porque tampoco hay todavía confirmación oficial de cuál es el
  anexo/regla correcto.
- Desde agosto de 2025 la DIOT se presenta exclusivamente en la nueva
  plataforma del SAT (pstcdi.clouda.sat.gob.mx), que requiere e.firma o
  RFC+contraseña y no expone ninguna API pública ni archivo descargable
  con el catálogo de tipos de operación.
- No existe, al momento de escribir este test, ninguna URL oficial
  pública y verificada (DOF/SAT) desde la que se pueda descargar
  programáticamente ese catálogo.

Por lo tanto este test:
  1. Intenta primero una descarga real si se configura
     `DIOT_CATALOGO_OFICIAL_URL` (variable de entorno) — punto de
     extensión para cuando exista una fuente oficial conectada. Si esa
     descarga funciona y el catálogo es parseable, el test corre la
     comparación real como una prueba normal (sin xfail).
  2. Si no hay URL configurada (el caso de hoy), cae a un fixture local
     EXPLÍCITAMENTE etiquetado como snapshot de una fuente secundaria no
     oficial (`tests/contract/fixtures/diot_catalogo_tipo_operacion_snapshot.json`)
     y el test se marca `xfail`: la comparación se ejecuta igual (para
     dejar evidencia útil en el mensaje de fallo) pero el resultado
     NUNCA debe leerse como "vigencia confirmada".

Nunca se debe quitar el `xfail` sin haber conectado y documentado una
fuente oficial SAT/RMF real y verificable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import pytest

from b2b_ai.features.diot.models import TipoOperacion

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "diot_catalogo_tipo_operacion_snapshot.json"

ENV_VAR_URL_OFICIAL = "DIOT_CATALOGO_OFICIAL_URL"


def _cargar_fixture_no_oficial() -> dict:
    """Carga el snapshot local etiquetado como fuente secundaria NO oficial."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("fuente_tipo") == "secundaria_no_oficial", (
        "El fixture de catálogo DIOT debe seguir etiquetado explícitamente "
        "como fuente secundaria no oficial; si esto cambió, revisar por qué."
    )
    return data


def _intentar_descarga_oficial(url: str) -> Optional[dict]:
    """Intenta descargar el catálogo real desde una fuente oficial configurada.

    Punto de extensión: cuando exista una URL oficial SAT/RMF verificada,
    exportarla en `DIOT_CATALOGO_OFICIAL_URL` hará que este test deje de
    depender del fixture no oficial. Se espera un JSON con una lista
    `codigos` de objetos `{"codigo": ..., "descripcion": ...}`.

    Devuelve `None` si la descarga o el parseo fallan por cualquier razón
    (sin red, timeout, formato inesperado, etc.) — nunca lanza, porque la
    ausencia de fuente oficial es un estado esperado hoy, no un error de
    programación.
    """
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload.get("codigos"), list) or not payload["codigos"]:
            return None
        return payload
    except Exception:
        return None


def test_codigos_tipo_operacion_vigentes_contra_catalogo_diot():
    """Los códigos de `TipoOperacion` deben existir en el catálogo real vigente.

    Mientras no haya fuente oficial conectada, este test corre la
    comparación real contra el mejor snapshot disponible (fuente
    secundaria, explícitamente etiquetada como tal) mas queda `xfail`:
    su fallo hoy documenta una discrepancia real detectada, no una
    afirmación de que el catálogo esté confirmado como vigente.
    """
    url_oficial = os.environ.get(ENV_VAR_URL_OFICIAL, "").strip()
    catalogo_oficial = _intentar_descarga_oficial(url_oficial) if url_oficial else None
    fuente_verificada_en_vivo = catalogo_oficial is not None

    if not fuente_verificada_en_vivo:
        catalogo_oficial = _cargar_fixture_no_oficial()

    descripcion_por_codigo = {item["codigo"]: item["descripcion"] for item in catalogo_oficial["codigos"]}
    codigos_catalogo = set(descripcion_por_codigo)
    codigos_actuales = {miembro.value for miembro in TipoOperacion}

    faltantes = sorted(codigos_actuales - codigos_catalogo)

    # Diagnóstico adicional: para los códigos que sí coinciden numéricamente,
    # ¿el significado (nombre del miembro del enum) parece corresponder a la
    # descripción del catálogo? Es una comparación heurística en texto libre
    # (no una prueba estricta) — solo aporta evidencia extra al mensaje de
    # xfail, nunca decide por sí sola si el test pasa o falla.
    coincidencias_dudosas = []
    for miembro in TipoOperacion:
        if miembro.value in codigos_catalogo:
            etiqueta_actual = miembro.name.replace("_", " ").lower()
            descripcion_catalogo = descripcion_por_codigo[miembro.value].lower()
            palabras_actuales = set(etiqueta_actual.split())
            palabras_catalogo = set(descripcion_catalogo.split())
            if not (palabras_actuales & palabras_catalogo):
                coincidencias_dudosas.append(
                    f"{miembro.value} ({miembro.name}='{etiqueta_actual}' vs. "
                    f"catálogo='{descripcion_catalogo}')"
                )

    if not fuente_verificada_en_vivo and (faltantes or coincidencias_dudosas):
        pytest.xfail(
            "REQ-IVA-017: no hay fuente oficial SAT/RMF conectada "
            f"(configure {ENV_VAR_URL_OFICIAL} para conectarla). Contra el "
            f"snapshot no oficial ({catalogo_oficial.get('fuente_url')}): "
            f"códigos de TipoOperacion sin respaldo en el catálogo = {faltantes}; "
            f"códigos que coinciden numéricamente pero cuyo significado parece "
            f"distinto = {coincidencias_dudosas}. Esto es evidencia de una "
            "posible desactualización real (consistente con REQ-IVA-004), pero "
            "NO debe tratarse como determinación fiscal firme sin verificar "
            "contra la fuente oficial."
        )

    assert not faltantes and not coincidencias_dudosas, (
        f"Códigos de TipoOperacion sin respaldo en el catálogo oficial vigente: {faltantes}; "
        f"códigos cuyo significado no corresponde al catálogo oficial: {coincidencias_dudosas}"
    )


def test_fixture_no_oficial_esta_correctamente_etiquetada():
    """Salvaguarda: el fixture usado como respaldo debe seguir auto-identificándose
    como fuente NO oficial, para que nadie lo confunda con una fuente verificada
    ni borre esa etiqueta por accidente al editarlo.
    """
    data = _cargar_fixture_no_oficial()
    assert "_ADVERTENCIA" in data
    assert "fuente_url" in data and data["fuente_url"]
    assert data["fuente_tipo"] == "secundaria_no_oficial"
