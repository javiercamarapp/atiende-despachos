# -*- coding: utf-8 -*-
"""
Módulo de Migración/Fusión de Catálogo de Cuentas.

Ver docs/BLUEPRINT-AGENTES-FISCALES.md §3 (REQ-MIG) y ADR-3: ninguna
reclasificación de cuenta se auto-aplica sin aprobación humana explícita,
salvo coincidencia exacta de código+nombre normalizados.

Estado actual de `matching.py` (este módulo ha recibido ediciones
concurrentes de varios requisitos de la misma matriz; este docstring
refleja lo que el archivo expone en este momento, verificado con
`pytest tests/features/migracion_catalogo/` en verde, no el historial):
  - REQ-MIG-002: esquema de datos (`MapeoMigracionCuenta`) implementado.
  - REQ-MIG-003: match exacto (`es_match_exacto` / `evaluar_match_exacto`)
    implementado — ÚNICO camino de auto-aprobación: `tipo_match=exacto` y
    `estado=aprobado` sin intervención humana, solo cuando código Y
    nombre normalizados son idénticos entre origen y destino.
  - REQ-MIG-004: alerta de riesgo (`es_alerta_riesgo` /
    `evaluar_alerta_riesgo`) implementado — marca `tipo_match=alerta_riesgo`
    y `estado=pendiente` SIEMPRE cuando código XOR nombre coincide
    (normalizados); nunca auto-aprueba.
  - REQ-MIG-005: score compuesto fuzzy (`calcular_score_compuesto`,
    `construir_match_fuzzy`) implementado — siempre `estado=pendiente`.
  - REQ-MIG-006: sin_match (`clasificar_cuenta_origen`, `UMBRAL_SIN_MATCH`,
    `NOTA_SIN_MATCH`) implementado — combina 003/004/005 contra todos los
    candidatos de destino y cae en `tipo_match=sin_match` sin inventar
    `destino_cuenta_id` cuando ninguno alcanza el umbral.
  - Los endpoints de aprobación (`routes.py`, ver
    `tests/features/migracion_catalogo/test_routes_aprobacion.py`), el
    migrador transaccional y las verificaciones de integridad son
    requisitos separados de la misma matriz (REQ-MIG-007..018) y no están
    todos implementados en este módulo.

Expone:
  - Enums: TipoMatchMigracion, EstadoMapeoMigracion
  - Model: MapeoMigracionCuenta
  - Matching (REQ-MIG-003): CuentaCatalogoPar, es_match_exacto,
    evaluar_match_exacto, normalizar_codigo, normalizar_nombre
  - Matching (REQ-MIG-004): CuentaCatalogo, es_alerta_riesgo,
    evaluar_alerta_riesgo
  - Matching (REQ-MIG-005): calcular_score_compuesto, construir_match_fuzzy,
    similitud_nombre
  - Matching (REQ-MIG-006): clasificar_cuenta_origen, UMBRAL_SIN_MATCH,
    NOTA_SIN_MATCH
"""
from b2b_ai.features.migracion_catalogo.matching import (
    NOTA_SIN_MATCH,
    UMBRAL_SIN_MATCH,
    CuentaCatalogo,
    CuentaCatalogoPar,
    calcular_score_compuesto,
    clasificar_cuenta_origen,
    construir_match_fuzzy,
    es_alerta_riesgo,
    es_match_exacto,
    evaluar_alerta_riesgo,
    evaluar_match_exacto,
    normalizar_codigo,
    normalizar_nombre,
    similitud_nombre,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.cross_db import (
    ConexionesInvalidasError,
    ConexionesMigracion,
    PolizaOrigenNoEncontradaError,
    cargar_catalogo_destino,
    cargar_catalogo_origen,
    cargar_poliza_origen,
    clasificar_catalogo_cross_db,
    listar_ids_polizas_origen_elegibles,
    migrar_lote_cross_db,
    migrar_poliza_cross_db,
)
from b2b_ai.features.migracion_catalogo.repositorio_postgres import (
    RepositorioMapeosPostgres,
)

__all__ = [
    "TipoMatchMigracion",
    "EstadoMapeoMigracion",
    "MapeoMigracionCuenta",
    "CuentaCatalogoPar",
    "es_match_exacto",
    "evaluar_match_exacto",
    "normalizar_codigo",
    "normalizar_nombre",
    "CuentaCatalogo",
    "es_alerta_riesgo",
    "evaluar_alerta_riesgo",
    "calcular_score_compuesto",
    "construir_match_fuzzy",
    "similitud_nombre",
    "clasificar_cuenta_origen",
    "UMBRAL_SIN_MATCH",
    "NOTA_SIN_MATCH",
    "ConexionesMigracion",
    "ConexionesInvalidasError",
    "PolizaOrigenNoEncontradaError",
    "cargar_catalogo_origen",
    "cargar_catalogo_destino",
    "clasificar_catalogo_cross_db",
    "cargar_poliza_origen",
    "listar_ids_polizas_origen_elegibles",
    "migrar_poliza_cross_db",
    "migrar_lote_cross_db",
    "RepositorioMapeosPostgres",
]
