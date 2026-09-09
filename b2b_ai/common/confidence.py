# -*- coding: utf-8 -*-
"""
confidence.py — Fuente única de verdad para los umbrales de confianza del
agente (clasificación por reglas, LLM y ML).

Antes de este módulo, el mismo tipo de umbral vivía triplicado e
inconsistente en tres archivos distintos:

    - b2b_ai/agent/loop.py:
        DEFAULT_CONFIDENCE_THRESHOLD = 0.7   (umbral de auto-procesamiento;
        cada tenant puede subirlo/bajarlo vía cfg["confidence_threshold"],
        pero el default vivía hardcodeado ahí)
    - b2b_ai/services/classify.py:
        `requires = confianza < 0.50`         (piso duro hardcodeado inline,
        sin nombre ni referencia a ningún lado)
    - b2b_ai/features/bookkeeping/auto_classifier.py:
        CONFIDENCE_MEDIUM = 0.60              (umbral medio del clasificador
        ML, también hardcodeado como constante de clase)

Nada de eso estaba mal en el valor -- el problema es que cambiar "el umbral
de confianza" requería tocar 3 archivos a mano, sin garantía de que alguien
recordara los 3, y sin un solo lugar que documentara qué significa cada
número. Este módulo centraliza los valores; cada consumidor importa
exactamente el que le corresponde.

Todos son configurables por variable de entorno para no requerir un deploy
de código si el umbral necesita ajustarse en producción.
"""
from __future__ import annotations

import os


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Piso duro de confianza: por debajo de este valor, la clasificación SIEMPRE
# requiere revisión humana, sin importar la política del tenant ni el umbral
# de auto-procesamiento. Usado por agent/loop.py (gate AG-1) y por
# services/classify.py (reglas determinísticas).
CONFIDENCE_FLOOR: float = _float_env("B2B_CONFIDENCE_FLOOR", 0.50)

# Umbral medio: separa confianza "media" de "alta" para clasificadores ML
# (features/bookkeeping/auto_classifier.py).
CONFIDENCE_MEDIUM: float = _float_env("B2B_CONFIDENCE_MEDIUM", 0.60)

# Umbral de confianza alta, banda superior del clasificador ML
# (features/bookkeeping/auto_classifier.py).
CONFIDENCE_HIGH: float = _float_env("B2B_CONFIDENCE_HIGH", 0.85)

# Umbral de auto-procesamiento por defecto: con confianza igual o mayor (y
# sin otras señales de alerta) la factura se registra sin revisión humana.
# Cada tenant puede sobreescribirlo vía cfg["confidence_threshold"]
# (agent/loop.py). Debe ser >= CONFIDENCE_FLOOR; de lo contrario el piso
# duro nunca actuaría antes que el umbral de auto-procesamiento.
DEFAULT_CONFIDENCE_THRESHOLD: float = _float_env(
    "B2B_CONFIDENCE_THRESHOLD", 0.70)

if DEFAULT_CONFIDENCE_THRESHOLD < CONFIDENCE_FLOOR:
    raise ValueError(
        "Configuración de confianza inconsistente: "
        f"DEFAULT_CONFIDENCE_THRESHOLD ({DEFAULT_CONFIDENCE_THRESHOLD}) "
        f"no puede ser menor que CONFIDENCE_FLOOR ({CONFIDENCE_FLOOR})."
    )
