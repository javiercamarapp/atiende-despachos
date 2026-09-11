# -*- coding: utf-8 -*-
"""
repositorio_postgres.py — Persistencia real en Postgres para
`MapeoMigracionCuenta` (REQ-MIG-016, marcado pendiente por la auditoría
de producción: "los mapeos de migración hoy solo viven en memoria").

`MigracionCatalogoService` (`service.py`) ya estaba diseñado para
recibir un repositorio inyectable
(`repositorio: Optional[Dict[str, MapeoMigracionCuenta]]`) y SOLO lo usa
con operaciones de `dict` (`self._mapeos[id] = mapeo`, `.get(id)`,
`.values()`). Por eso `RepositorioMapeosPostgres` no cambia absolutamente
nada de `service.py`: implementa `collections.abc.MutableMapping` con
esa misma interfaz, pero cada lectura/escritura es una consulta SQL real
contra una tabla nueva (`mapeos_migracion_catalogo`,
`migrations/versions/0018_mapeos_migracion_catalogo.py`) en vez de un
diccionario en memoria de proceso. `MigracionCatalogoService(repositorio=
RepositorioMapeosPostgres(conn, migracion_id))` es un reemplazo directo
(drop-in) de `MigracionCatalogoService()` -- mismo comportamiento,
`aprobar`/`rechazar`/`editar`/`registrar`/`listar`/`obtener` idénticos,
guardias de REQ-MIG-007/008 idénticas -- con la única diferencia de que
el estado sobrevive a un reinicio del proceso.

Por qué esto resuelve REQ-MIG-016: hoy, si el proceso que corre una
migración larga (cientos de pólizas, con sus mapeos ya aprobados/
editados por un humano) se reinicia a la mitad, todas las decisiones de
aprobación tomadas hasta ese momento se pierden -- vivían solo en el
`dict` en memoria de `MigracionCatalogoService` -- y habría que volver a
aprobar mapeo por mapeo desde cero. Con este repositorio, cada
aprobación/edición/rechazo/registro queda escrito en Postgres en el
momento en que ocurre (dentro de la misma llamada), así que un proceso
nuevo que reconstruya `MigracionCatalogoService(repositorio=
RepositorioMapeosPostgres(conn, migracion_id))` con el MISMO
`migracion_id` recupera exactamente el mismo estado -- la migración es
reanudable y auditable (la tabla nueva queda como registro permanente de
quién aprobó/editó/rechazó qué y cuándo, con `creado_en`/`actualizado_en`
reales de Postgres).

`migracion_id` identifica una migración cross-database concreta (p.ej.
"empresa-x:2024-2026->2020-2023"): todos los mapeos de esa migración
comparten el mismo `migracion_id`, y dos migraciones distintas nunca se
mezclan aunque corran contra la misma tabla física.

Nota sobre RLS (ver `migrations/versions/0017_rls_tenant_isolation.py`):
`mapeos_migracion_catalogo` deliberadamente NO tiene una política de
aislamiento por tenant_id -- cada fila puede involucrar DOS tenants
potencialmente en DOS bases físicas distintas (origen y destino), así
que no hay un único `tenant_id` dueño de la fila al que atarle esa
política; el aislamiento real aquí es por `migracion_id`, aplicado en
cada consulta de este módulo (todas las consultas de abajo filtran por
`migracion_id`, nunca se lee/escribe sin ese filtro).
"""
from __future__ import annotations

import json
import uuid as _uuid
from collections.abc import MutableMapping
from typing import Any, Dict, Iterator, Optional

from .models import EstadoMapeoMigracion, MapeoMigracionCuenta, TipoMatchMigracion


def _fila_a_mapeo(fila: Any) -> MapeoMigracionCuenta:
    (
        id_,
        origen_cuenta_id,
        destino_cuenta_id,
        tipo_match,
        score,
        estado,
        aprobado_por,
        aprobado_en,
        nota,
        estrategia,
    ) = fila
    return MapeoMigracionCuenta(
        id=id_,
        origen_cuenta_id=origen_cuenta_id,
        destino_cuenta_id=destino_cuenta_id,
        tipo_match=TipoMatchMigracion(tipo_match),
        score=float(score),
        estado=EstadoMapeoMigracion(estado),
        aprobado_por=aprobado_por,
        aprobado_en=aprobado_en,
        nota=nota,
        estrategia_conciliacion_saldos=estrategia,
    )


_SELECT_COLUMNAS = (
    "id, origen_cuenta_id, destino_cuenta_id, tipo_match, score, estado, "
    "aprobado_por, aprobado_en, nota, estrategia_conciliacion_saldos"
)


class RepositorioMapeosPostgres(MutableMapping):
    """Repositorio de `MapeoMigracionCuenta` respaldado por Postgres,
    compatible con la interfaz de `dict` que `MigracionCatalogoService`
    ya espera (`__setitem__`, `__getitem__`, `.get`, `.values()`,
    `.keys()`, `.items()`, `len()`, `in`, iteración).

    Cada operación de escritura (`__setitem__`, `__delitem__`) abre su
    propia transacción de Postgres (`conn.transaction()`); no depende de
    que el llamador gestione commits -- igual que
    `migrador.py::_encolar_poliza_bloqueada`.
    """

    def __init__(self, conn: Any, migracion_id: str) -> None:
        if not migracion_id or not str(migracion_id).strip():
            raise ValueError(
                "migracion_id no puede estar vacío -- identifica a qué "
                "migración cross-database pertenecen estos mapeos."
            )
        self._conn = conn
        self._migracion_id = migracion_id

    @property
    def migracion_id(self) -> str:
        return self._migracion_id

    # -- MutableMapping ---------------------------------------------------

    def __setitem__(self, mapeo_id: str, mapeo: MapeoMigracionCuenta) -> None:
        if mapeo.id != mapeo_id:
            raise ValueError(
                f"la clave ({mapeo_id!r}) debe ser igual a mapeo.id "
                f"({mapeo.id!r}) -- mismo contrato que un dict "
                "{mapeo.id: mapeo} (ver MigracionCatalogoService.registrar)."
            )
        with self._conn.transaction():
            self._conn.execute(
                """
                INSERT INTO mapeos_migracion_catalogo (
                    id, migracion_id, origen_cuenta_id, destino_cuenta_id,
                    tipo_match, score, estado, aprobado_por, aprobado_en,
                    nota, estrategia_conciliacion_saldos
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    destino_cuenta_id = EXCLUDED.destino_cuenta_id,
                    tipo_match = EXCLUDED.tipo_match,
                    score = EXCLUDED.score,
                    estado = EXCLUDED.estado,
                    aprobado_por = EXCLUDED.aprobado_por,
                    aprobado_en = EXCLUDED.aprobado_en,
                    nota = EXCLUDED.nota,
                    estrategia_conciliacion_saldos =
                        EXCLUDED.estrategia_conciliacion_saldos,
                    actualizado_en = now()
                """,
                (
                    mapeo.id,
                    self._migracion_id,
                    mapeo.origen_cuenta_id,
                    mapeo.destino_cuenta_id,
                    mapeo.tipo_match.value,
                    float(mapeo.score),
                    mapeo.estado.value,
                    mapeo.aprobado_por,
                    mapeo.aprobado_en,
                    mapeo.nota,
                    mapeo.estrategia_conciliacion_saldos,
                ),
            )

    def __getitem__(self, mapeo_id: str) -> MapeoMigracionCuenta:
        # Envuelto en `with conn.transaction()` a propósito -- ver la
        # nota extensa en `migrador.py::poliza_ya_migrada` sobre por
        # qué un `conn.execute()` SUELTO (fuera de un bloque de
        # transacción explícito) deja una transacción implícita abierta
        # en la conexión que silenciosamente convierte el PRÓXIMO
        # `with conn.transaction():` (p.ej. el `__setitem__` de más
        # abajo, o el de quien use esta misma conexión después) en un
        # SAVEPOINT anidado que nunca hace el COMMIT real. Encontrado
        # exactamente así por
        # `test_estado_sobrevive_a_reinicio_simulado_del_proceso`.
        with self._conn.transaction():
            fila = self._conn.execute(
                f"SELECT {_SELECT_COLUMNAS} FROM mapeos_migracion_catalogo "
                "WHERE migracion_id = %s AND id = %s",
                (self._migracion_id, mapeo_id),
            ).fetchone()
        if fila is None:
            raise KeyError(mapeo_id)
        return _fila_a_mapeo(fila)

    def __delitem__(self, mapeo_id: str) -> None:
        with self._conn.transaction():
            cur = self._conn.execute(
                "DELETE FROM mapeos_migracion_catalogo "
                "WHERE migracion_id = %s AND id = %s",
                (self._migracion_id, mapeo_id),
            )
        if cur.rowcount == 0:
            raise KeyError(mapeo_id)

    def __iter__(self) -> Iterator[str]:
        # Ver la nota en `__getitem__` sobre por qué toda lectura de
        # este repositorio va envuelta en su propia transacción.
        with self._conn.transaction():
            filas = self._conn.execute(
                "SELECT id FROM mapeos_migracion_catalogo "
                "WHERE migracion_id = %s ORDER BY id",
                (self._migracion_id,),
            ).fetchall()
        return iter(f[0] for f in filas)

    def __len__(self) -> int:
        with self._conn.transaction():
            fila = self._conn.execute(
                "SELECT COUNT(*) FROM mapeos_migracion_catalogo "
                "WHERE migracion_id = %s",
                (self._migracion_id,),
            ).fetchone()
        return int(fila[0])

    def __contains__(self, mapeo_id: object) -> bool:
        with self._conn.transaction():
            fila = self._conn.execute(
                "SELECT 1 FROM mapeos_migracion_catalogo "
                "WHERE migracion_id = %s AND id = %s",
                (self._migracion_id, mapeo_id),
            ).fetchone()
        return fila is not None


# ---------------------------------------------------------------------------
# Log de auditoría append-only (REQ-MIG-016)
# ---------------------------------------------------------------------------
#
# `migracion_catalogo_audit_log`
# (`migrations/versions/0019_migracion_audit_log.py`) es una tabla
# separada de `mapeos_migracion_catalogo`, protegida por un trigger de
# Postgres que rechaza cualquier UPDATE/DELETE (ver el docstring extenso de
# esa migración sobre por qué trigger y no GRANT/REVOKE en este repo).
# `RegistroAuditoriaPostgres` es el equivalente, para esa tabla, de lo que
# `RepositorioMapeosPostgres` es para `mapeos_migracion_catalogo`: un
# adaptador inyectable que `MigracionCatalogoService` (`service.py`) usa a
# través de la interfaz mínima `service.RegistradorAuditoria` (un
# `Protocol` con un solo método, `.registrar(...)`) -- `service.py` NO
# importa este módulo ni sabe que existe Postgres; solo llama a
# `self._auditoria.registrar(...)` si se le inyectó algo (default `None` =
# sin auditoría, para no romper ninguna de las pruebas unitarias en
# memoria que ya existían antes de REQ-MIG-016).
#
# NOTA sobre atomicidad: igual que `RepositorioMapeosPostgres.__setitem__`
# de arriba, cada llamada a `.registrar()` abre y cierra su propia
# transacción (`with conn.transaction():`). Si `service.py` construye el
# repositorio de mapeos y este registrador con la MISMA conexión, hay dos
# COMMITs secuenciales (mapeo, luego auditoría) -- no una única
# transacción atómica que cubra ambas escrituras. Un crash exactamente
# entre esos dos commits dejaría el mapeo actualizado sin su fila de
# auditoría correspondiente. Esto es una limitación real, documentada
# aquí a propósito (no un half-fix silencioso): unificarlas requeriría que
# `service.py` conozca y controle una transacción compartida entre dos
# repositorios inyectables distintos, lo cual rompería el diseño actual
# (repositorio de mapeos 100% agnóstico de Postgres, ver su propio
# docstring de módulo). Dado que REQ-MIG-016 solo pide que la fila se
# inserte "en cada punto donde se modifique el catálogo" y que el log sea
# append-only una vez escrito -- no que sea transaccionalmente atómico con
# el cambio de estado -- se acepta esta limitación en vez de forzar un
# rediseño más amplio fuera de alcance.
class RegistroAuditoriaPostgres:
    """Escribe una fila inmutable en `migracion_catalogo_audit_log` por
    cada aprobación/rechazo/edición de un `MapeoMigracionCuenta`
    (REQ-MIG-016). Cumple la interfaz `service.RegistradorAuditoria`."""

    def __init__(self, conn: Any, migracion_id: str) -> None:
        if not migracion_id or not str(migracion_id).strip():
            raise ValueError(
                "migracion_id no puede estar vacío -- identifica a qué "
                "migración cross-database pertenece esta fila de "
                "auditoría (mismo criterio que RepositorioMapeosPostgres)."
            )
        self._conn = conn
        self._migracion_id = migracion_id

    @property
    def migracion_id(self) -> str:
        return self._migracion_id

    def registrar(
        self,
        *,
        mapeo_id: str,
        accion: str,
        decidido_por: str,
        nota: Optional[str],
        valores_antes: Optional[Dict[str, Any]],
        valores_despues: Dict[str, Any],
    ) -> str:
        """Inserta una fila de auditoría. Devuelve el `id` generado.

        `valores_antes`/`valores_despues` son dicts JSON-serializables
        (típicamente `MapeoMigracionCuenta.model_dump(mode="json")`,
        que ya deja los `Enum` como su `.value` de cadena) -- se
        serializan aquí con `json.dumps` y se castean a `jsonb` en el
        propio SQL, en vez de depender del adaptador automático de
        psycopg para dicts (ambiguo entre `json`/`jsonb`), igual que ya
        hace `b2b_ai/audit/trail.py` con columnas JSON de este repo.
        """
        entrada_id = str(_uuid.uuid4())
        with self._conn.transaction():
            self._conn.execute(
                """
                INSERT INTO migracion_catalogo_audit_log (
                    id, migracion_id, mapeo_id, accion, decidido_por,
                    nota, valores_antes, valores_despues
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    entrada_id,
                    self._migracion_id,
                    mapeo_id,
                    accion,
                    decidido_por,
                    nota,
                    json.dumps(valores_antes, default=str, ensure_ascii=False)
                    if valores_antes is not None
                    else None,
                    json.dumps(valores_despues, default=str, ensure_ascii=False),
                ),
            )
        return entrada_id
