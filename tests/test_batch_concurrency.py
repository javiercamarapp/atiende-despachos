# -*- coding: utf-8 -*-
"""
Pruebas de concurrencia acotada para el procesamiento de lotes (BATCH-01,
BATCH-02 — auditoría de hardening de batch).

BATCH-01: `pipeline.process_batch()` procesaba los CFDI de un lote uno por
uno en un `for` secuencial. Se verifica aquí que ahora:
  (a) SÍ hay solapamiento real entre items (no sigue siendo secuencial),
  (b) el límite `max_workers` se respeta SIEMPRE (contador real de
      "workers activos ahora mismo", nunca por encima del límite), y
  (c) el fallo de un item se aísla: los demás items del lote se siguen
      procesando y aparecen en el resultado con su resultado normal.

BATCH-02: `api/v2.py` creaba un `threading.Thread` nuevo, sin límite, por
cada `POST /api/v2/batch` con `async=true`. Se verifica aquí, contra el
pool real del módulo (mismo que usa el endpoint en producción, no un doble
de prueba) que:
  (a) el número de threads del pool es FIJO (no crece con la cantidad de
      jobs encolados),
  (b) el límite de concurrencia se respeta con un contador real, y
  (c) el fallo de un job no mata a su worker: los demás jobs encolados
      se siguen procesando (si un worker muriera, `Queue.join()` se
      quedaría esperando para siempre a los jobs que ese worker ya no
      puede tomar -- este test cuelga/falla por timeout en ese caso).
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

from b2b_ai.services.pipeline import process_batch


# ---------------------------------------------------------------------------
# BATCH-01 — pipeline.process_batch
# ---------------------------------------------------------------------------

class _ConcurrencyProbe:
    """Espía `process_file` real: cuenta cuántas llamadas están activas AL
    MISMO TIEMPO (no cuántas se hicieron en total) y hace fallar una a
    propósito para probar aislamiento de fallos."""

    def __init__(self, fail_name: str):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.fail_name = fail_name

    def __call__(self, xml_path, db=None, tenant_id=None, **kw):
        import os
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            # Simula I/O real (parseo/tools/DB): sin esto, en una máquina
            # rápida los workers podrían terminar antes de que el siguiente
            # arranque y nunca se observaría solapamiento real.
            time.sleep(0.08)
            name = os.path.basename(xml_path)
            if name == self.fail_name:
                raise RuntimeError(f"fallo simulado en {name}")
            return {"archivo": name, "validacion": {"ok": True},
                    "insertado": True, "clasificacion": {"categoria": "x"}}
        finally:
            with self.lock:
                self.active -= 1


def test_process_batch_concurrencia_acotada_y_aislamiento_de_fallos(tmp_path):
    N = 12
    MAX_CONCURRENCY = 3
    FAIL_FILE = "fail_03.xml"
    for i in range(N):
        name = FAIL_FILE if i == 3 else f"file_{i:02d}.xml"
        (tmp_path / name).write_text("<xml/>")

    probe = _ConcurrencyProbe(fail_name=FAIL_FILE)
    with patch("b2b_ai.services.pipeline.process_file", side_effect=probe):
        results = process_batch(str(tmp_path), db=None, tenant_id=1,
                                 max_workers=MAX_CONCURRENCY)

    assert len(results) == N, "no se perdió ni se duplicó ningún item del lote"

    errores = [r for r in results if "error" in r]
    ok = [r for r in results if "validacion" in r]
    # Aislamiento de fallos: SOLO el item que falló vuelve como error; los
    # demás N-1 items completan normalmente pese a ese fallo.
    assert len(errores) == 1
    assert errores[0]["archivo"] == FAIL_FILE
    assert len(ok) == N - 1

    # Concurrencia real: si siguiera siendo el `for` secuencial original,
    # `max_active` sería siempre 1 (nunca dos llamadas activas al mismo
    # tiempo). Con 12 items de 0.08s repartidos en un pool de 3, SÍ deben
    # solaparse.
    assert probe.max_active > 1, (
        "no se observó solapamiento real entre items -- process_batch "
        "sigue procesando secuencialmente")
    # Límite de concurrencia respetado: NUNCA más de MAX_CONCURRENCY
    # llamadas activas al mismo tiempo, verificado con un contador real
    # (no inferido).
    assert probe.max_active <= MAX_CONCURRENCY, (
        f"se observaron hasta {probe.max_active} workers activos a la vez, "
        f"por encima del límite configurado ({MAX_CONCURRENCY})")


def test_process_batch_default_max_concurrency_no_crea_thread_por_item(tmp_path):
    """Sin `max_workers` explícito, el default (`B2B_BATCH_MAX_CONCURRENCY`
    o 8) también debe respetarse -- no "todos a la vez"."""
    N = 20
    for i in range(N):
        (tmp_path / f"f_{i:02d}.xml").write_text("<xml/>")

    probe = _ConcurrencyProbe(fail_name="__never__")
    with patch("b2b_ai.services.pipeline.process_file", side_effect=probe):
        with patch.dict("os.environ", {"B2B_BATCH_MAX_CONCURRENCY": "5"}):
            results = process_batch(str(tmp_path), db=None, tenant_id=1)

    assert len(results) == N
    assert probe.max_active <= 5
    assert probe.max_active > 1


# ---------------------------------------------------------------------------
# BATCH-02 — api/v2.py: pool acotado de jobs async (contra el pool REAL)
# ---------------------------------------------------------------------------

def test_batch_job_pool_concurrencia_acotada_y_aislamiento_de_fallos():
    from b2b_ai.api import v2 as v2mod

    max_conc = v2mod._BATCH_JOB_MAX_CONCURRENCY
    assert max_conc >= 1

    def _worker_threads():
        return [t for t in threading.enumerate()
                if t.name.startswith("batch-job-worker-")]

    workers_antes = _worker_threads()
    assert len(workers_antes) == max_conc, (
        "el pool de jobs async no tiene un número FIJO de threads "
        f"(esperado {max_conc}, encontrados {len(workers_antes)}) -- "
        "¿sigue creando un thread por request?")

    n_jobs = max_conc * 4
    fail_idx = 5 % n_jobs
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0, "completed": []}

    def make_task(i):
        def _task():
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                time.sleep(0.08)
                if i == fail_idx:
                    raise RuntimeError(f"fallo simulado en job {i}")
                with lock:
                    state["completed"].append(i)
            finally:
                with lock:
                    state["active"] -= 1
        return _task

    for i in range(n_jobs):
        v2mod._BATCH_JOB_QUEUE.put(make_task(i))

    # `Queue.join()` sólo retorna cuando TODOS los jobs fueron tomados Y
    # marcados con `task_done()` -- si el worker que corrió el job que
    # revienta muriera (aislamiento de fallos roto), los jobs que ese
    # worker nunca llega a tomar dejarían este `join()` colgado para
    # siempre (el test fallaría por timeout de la suite, no con un assert
    # bonito, pero sí fallaría de forma inequívoca).
    join_thread = threading.Thread(target=v2mod._BATCH_JOB_QUEUE.join)
    join_thread.start()
    join_thread.join(timeout=15)
    assert not join_thread.is_alive(), (
        "la cola de jobs no terminó de vaciarse -- un worker murió tras "
        "el fallo simulado (aislamiento de fallos roto)")

    esperado = [i for i in range(n_jobs) if i != fail_idx]
    assert sorted(state["completed"]) == esperado, (
        "el fallo de un job impidió que se procesaran los demás")

    assert state["max_active"] > 1, (
        "no se observó solapamiento real entre jobs async")
    assert state["max_active"] <= max_conc, (
        f"se observaron hasta {state['max_active']} jobs corriendo a la "
        f"vez, por encima del límite configurado ({max_conc})")

    workers_despues = _worker_threads()
    assert len(workers_despues) == max_conc, (
        "el número de threads del pool cambió tras procesar "
        f"{n_jobs} jobs (antes {len(workers_antes)}, después "
        f"{len(workers_despues)}) -- se crearon threads nuevos por job")
