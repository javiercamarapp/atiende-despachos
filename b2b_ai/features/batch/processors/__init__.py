# -*- coding: utf-8 -*-
"""Procesadores del módulo batch de CFDIs.

Existencias del pipeline:
  - :class:`BulkCfdiParser` : extracción y parseo de múltiples CFDIs (XML en
    ZIP), agnóstico al namespace CFDI 3.3 / 4.0.
  - :class:`BatchAggregator`: agregación de resultados individuales a un
    resumen (total procesado, fallidos, desglose por RFC y por categoría).

También se exportan los helpers monofunción (``extract_cfdi_pairs``,
``parse_cfdi_document``, ``parse_cfdi_pairs``, ``aggregate_results``,
``summarize_batch_job``) por compatibilidad con el test existente.

Estos procesadores son piezas reutilizables e independientes del servicio
batch (BatchService); funcionan sobre la forma normalizada de ``parse_cfdi_4``
y sobre el modelo :class:`b2b_ai.features.batch.models.BatchItem`.
"""
from b2b_ai.features.batch.processors.aggregator import (
    BatchAggregator,
    aggregate_results,
    summarize_batch_job,
)
from b2b_ai.features.batch.processors.bulk_parser import (
    BulkCfdiParser,
    extract_cfdi_pairs,
    parse_cfdi_document,
    parse_cfdi_pairs,
)

__all__ = [
    "BulkCfdiParser",
    "BatchAggregator",
    "extract_cfdi_pairs",
    "parse_cfdi_document",
    "parse_cfdi_pairs",
    "aggregate_results",
    "summarize_batch_job",
]
