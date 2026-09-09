# -*- coding: utf-8 -*-
"""
concurrency.py — Concurrencia ACOTADA para procesamiento en lote (BATCH-01/02).

Contexto (auditoría, ronda de hardening de batch):
  - `pipeline.process_batch()` procesaba los CFDI de un lote uno por uno en
    un `for` secuencial: un lote de 1000 archivos tardaba 1000x el tiempo de
    un solo archivo aunque la mayor parte de ese tiempo es I/O (parseo de
    XML, tools, inserts en DB) que sí puede solaparse.
  - `api/v2.py` creaba un `threading.Thread` NUEVO por cada request
    `POST /api/v2/batch?async=true`, sin ningún límite: un cliente (o varios
    tenants) mandando muchos lotes async en poco tiempo podía crear cientos
    de threads del proceso, con riesgo real de agotar los threads del SO
    (cada thread reserva stack de memoria; el límite típico de threads por
    proceso en Linux/containers es de unos cuantos miles).

Se buscó un precedente de "MAX_CONCURRENCY" en el motor de conciliación
bancaria (`b2b_ai/services/bank_reconciliation.py`, `b2b_ai/api/reconciliation.py`)
para reusar el mismo patrón: NO existe tal precedente en este repo (ese
motor no usa threads ni límites de concurrencia). Este módulo se escribe
desde cero con `ThreadPoolExecutor` + un límite explícito y configurable,
que es el patrón que ambos call-sites (pipeline.py y api/v2.py) reusan.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# Límite por default si no hay env var: suficiente para solapar I/O (parseo
# de XML, llamadas a tools, inserts en DB) sin crear cientos de threads.
DEFAULT_MAX_CONCURRENCY = 8


def get_max_concurrency(env_var: str = "B2B_BATCH_MAX_CONCURRENCY",
                        default: int = DEFAULT_MAX_CONCURRENCY) -> int:
    """Lee el límite de concurrencia desde una env var, con default seguro.

    Nunca devuelve <1 (evita `ThreadPoolExecutor(max_workers=0)`, que
    revienta con ValueError) ni explota con una env var no numérica: en
    ambos casos cae al `default`.
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


def run_bounded(items: List[T], worker: Callable[[T], R],
                max_workers: "int | None" = None) -> List[R]:
    """Ejecuta `worker(item)` para cada item en `items` con un pool ACOTADO.

    Garantías:
      - Concurrencia acotada real: nunca hay más de `max_workers` llamadas a
        `worker` corriendo simultáneamente (lo garantiza `ThreadPoolExecutor`
        internamente — no arranca la tarea N+1 hasta que un worker se libera).
      - Aislamiento de fallos: se espera que `worker` NO deje escapar
        excepciones (los callers de este helper envuelven su lógica real en
        try/except y devuelven un dict `{"error": ...}` en caso de fallo,
        igual que hacía el `for` secuencial original) — así una excepción en
        un item no aborta el resto del lote. Si `worker` sí deja escapar una
        excepción para un item, ésta se re-lanza al pedir `future.result()`
        para ESE item únicamente; los demás items ya encolados siguen
        procesándose (ThreadPoolExecutor no cancela el resto del pool).
      - Preserva el orden: `results[i]` corresponde a `items[i]`,
        independientemente del orden real de terminación.
    """
    if not items:
        return []
    n = max_workers if max_workers is not None else get_max_concurrency()
    n = max(1, min(n, len(items)))
    results: List[R] = [None] * len(items)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=n) as executor:
        future_to_idx = {executor.submit(worker, item): idx
                         for idx, item in enumerate(items)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()
    return results
