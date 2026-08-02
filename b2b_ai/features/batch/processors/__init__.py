# -*- coding: utf-8 -*-
"""Procesadores del módulo batch de CFDIs.

Existencias del pipeline:
  - :mod:`bulk_parser`  : extracción y parseo de múltiples CFDIs (XML en ZIP).
  - :mod:`aggregator`   : agregación de resultados individuales a un resumen
                          (total procesado, fallidos, desglose por RFC).

Estos procesadores son piezas reutilizables e independientes del servicio
batch (BatchService); funcionan sobre la forma normalizada de ``parse_cfdi_4``
y sobre el modelo :class:`b2b_ai.features.batch.models.BatchItem`.
"""
from b2b_ai.features.batch.processors.aggregator import (
    aggregate_results,
    summarize_batch_job,
)
from b2b_ai.features.batch.processors.bulk_parser import (
    extract_cfdi_pairs,
    parse_cfdi_document,
    parse_cfdi_pairs,
)

__all__ = [
    "extract_cfdi_pairs",
    "parse_cfdi_document",
    "parse_cfdi_pairs",
    "aggregate_results",
    "summarize_batch_job",
]
