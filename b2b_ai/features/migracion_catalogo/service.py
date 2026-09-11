# -*- coding: utf-8 -*-
"""
service.py — Servicio de revisión humana de mapeos de migración de
catálogo (REQ-MIG-007), incluida la guardia de cardinalidad N:1/1:N
(REQ-MIG-008).

Contexto (ADR-3, docs/BLUEPRINT-AGENTES-FISCALES.md §3/§7): ningún
`MapeoMigracionCuenta` con `tipo_match` distinto de `exacto` puede
usarse para migrar pólizas sin haber pasado antes por una decisión
humana explícita e identificada. `MigracionCatalogoService` es el ÚNICO
código de este repo que mueve un mapeo fuera de `estado=PENDIENTE`:

  - El motor de matching (REQ-MIG-003..006, `matching.py`) solo CREA
    mapeos vía `registrar()`; nunca los transiciona de estado él mismo
    (salvo el caso `tipo_match=EXACTO`, que el propio motor construye ya
    con `estado=APROBADO` desde su creación — REQ-MIG-003 — sin pasar
    por este servicio, porque no hubo nunca un `PENDIENTE` que decidir).
  - El motor de migración de pólizas (REQ-MIG-009, `migrador.py`) solo
    LEE `estado` para decidir si migra o lanza una excepción; nunca lo
    escribe.

Las tres operaciones de decisión humana (`aprobar`/`rechazar`/`editar`)
exigen `decidido_por` no vacío (ninguna decisión anónima) y solo aplican
sobre un mapeo en `estado=PENDIENTE`; sobre cualquier otro estado de
partida lanzan `TransicionEstadoInvalidaError` explícita — nunca
reescriben en silencio una decisión humana ya tomada.

REQ-MIG-008: `aprobar()`/`editar()` además validan la cardinalidad de la
correspondencia contra el resto del repositorio antes de confirmar nada
(`_validar_cardinalidad_antes_de_confirmar`): un mapeo N:1 (varias
cuentas origen hacia el mismo `destino_cuenta_id`) exige
`estrategia_conciliacion_saldos` no nula; un mapeo 1:N (la misma cuenta
origen hacia destinos distintos) se rechaza por completo
(`DivisionUnoANoAutomaticaError`), sin que ningún campo lo autorice.

Persistencia: este servicio usa un repositorio en memoria (dict
inyectable). La matriz de requisitos (docs/BLUEPRINT-AGENTES-FISCALES.md
§3) no marca REQ-MIG-007 como dependiente de "credenciales de BD de
pruebas" — a diferencia de REQ-MIG-001/009/012..016, que sí requieren
tablas Postgres reales y son requisitos separados — así que una
persistencia real para `MapeoMigracionCuenta` (tabla `SQLAlchemy`/
Alembic) queda fuera del alcance de este archivo. Ver
`repositorio_postgres.py::RepositorioMapeosPostgres` para la
implementación real inyectable.

REQ-MIG-016 (log de auditoría append-only): cada `aprobar()`/
`rechazar()`/`editar()` -- las tres únicas operaciones que mueven un
mapeo fuera de `PENDIENTE`, ver arriba -- llama además a
`self._auditoria.registrar(...)` si se inyectó un `RegistradorAuditoria`
(constructor, parámetro `auditoria`, default `None`). Igual que con el
repositorio de mapeos, este archivo permanece agnóstico de Postgres:
`RegistradorAuditoria` es solo un `Protocol` estructural definido más
abajo; la implementación real que escribe en
`migracion_catalogo_audit_log` (tabla protegida contra UPDATE/DELETE por
un trigger, `migrations/versions/0019_migracion_audit_log.py`)
vive en `repositorio_postgres.py::RegistroAuditoriaPostgres`. Con
`auditoria=None` (el default, usado por todas las pruebas unitarias en
memoria existentes antes de REQ-MIG-016) el comportamiento de este
servicio no cambia en absoluto -- no auditar no es un error, es
simplemente no tener a dónde escribir la auditoría.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .models import EstadoMapeoMigracion, MapeoMigracionCuenta


class MapeoNoEncontradoError(Exception):
    """No existe ningún `MapeoMigracionCuenta` con el id dado."""


class TransicionEstadoInvalidaError(Exception):
    """Se intentó decidir (aprobar/rechazar/editar) un mapeo que ya no
    está en `estado=PENDIENTE` — nunca se sobrescribe en silencio una
    decisión humana previa."""


class DecisionSinResponsableError(Exception):
    """Se intentó aprobar/rechazar/editar un mapeo sin identificar quién
    decide (`decidido_por` vacío) — ninguna decisión sobre un mapeo de
    migración puede quedar anónima (ADR-3)."""


class DivisionUnoANoAutomaticaError(Exception):
    """Se intentó confirmar (aprobar/editar) un mapeo cuya cuenta origen
    ya queda repartida hacia más de un `destino_cuenta_id` distinto —
    una división 1:N de cuenta (REQ-MIG-008). Fuera de alcance
    automático sin excepción: ningún campo adicional puede autorizarla,
    a diferencia de la fusión N:1 (ver `EstrategiaConciliacionRequeridaError`)."""


class EstrategiaConciliacionRequeridaError(Exception):
    """Se intentó aprobar/editar un mapeo N:1 (varias cuentas origen hacia
    el mismo `destino_cuenta_id`) sin que el contador confirmara
    explícitamente `estrategia_conciliacion_saldos` (REQ-MIG-008); el
    campo es obligatorio no nulo antes de aprobar ese tipo de mapeo."""


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@runtime_checkable
class RegistradorAuditoria(Protocol):
    """Interfaz mínima que `MigracionCatalogoService` necesita para dejar
    rastro de auditoría (REQ-MIG-016) de una decisión humana. Un
    `Protocol` estructural a propósito -- cualquier objeto con este
    método sirve, sin que este módulo importe ni sepa nada de Postgres.
    Implementación real: `repositorio_postgres.RegistroAuditoriaPostgres`.
    """

    def registrar(
        self,
        *,
        mapeo_id: str,
        accion: str,
        decidido_por: str,
        nota: Optional[str],
        valores_antes: Optional[Dict[str, Any]],
        valores_despues: Dict[str, Any],
    ) -> Any: ...


class MigracionCatalogoService:
    """Único punto de escritura de `estado` para `MapeoMigracionCuenta`
    fuera de la creación inicial por el motor de matching."""

    def __init__(
        self,
        repositorio: Optional[Dict[str, MapeoMigracionCuenta]] = None,
        auditoria: Optional[RegistradorAuditoria] = None,
    ) -> None:
        # mapeo_id -> MapeoMigracionCuenta. Inyectable para pruebas o
        # para compartir el mismo repositorio entre el router y el motor
        # de matching dentro del mismo proceso.
        self._mapeos: Dict[str, MapeoMigracionCuenta] = (
            repositorio if repositorio is not None else {}
        )
        # REQ-MIG-016: sumidero opcional de auditoría append-only. `None`
        # (default) preserva el comportamiento de siempre -- ver
        # docstring de módulo arriba.
        self._auditoria = auditoria

    # -- auditoría (REQ-MIG-016) -----------------------------------------

    def _registrar_auditoria(
        self,
        *,
        accion: str,
        decidido_por: str,
        nota: Optional[str],
        mapeo_antes: MapeoMigracionCuenta,
        mapeo_despues: MapeoMigracionCuenta,
    ) -> None:
        if self._auditoria is None:
            return
        self._auditoria.registrar(
            mapeo_id=mapeo_despues.id,
            accion=accion,
            decidido_por=decidido_por,
            nota=nota,
            valores_antes=mapeo_antes.model_dump(mode="json"),
            valores_despues=mapeo_despues.model_dump(mode="json"),
        )

    # -- registro / lectura ---------------------------------------------

    def registrar(self, mapeo: MapeoMigracionCuenta) -> MapeoMigracionCuenta:
        """Da de alta (o reemplaza) un mapeo en el repositorio.

        Usado por el motor de matching (REQ-MIG-003..006) para publicar
        sus resultados. Este método NUNCA decide si un mapeo queda
        aprobado — simplemente persiste el `MapeoMigracionCuenta` tal
        como el motor lo construyó (incluyendo su `estado` inicial, que
        para `tipo_match=EXACTO` ya viene `APROBADO` desde el propio
        motor, y `PENDIENTE` para todo lo demás).
        """
        self._mapeos[mapeo.id] = mapeo
        return mapeo

    def obtener(self, mapeo_id: str) -> MapeoMigracionCuenta:
        mapeo = self._mapeos.get(mapeo_id)
        if mapeo is None:
            raise MapeoNoEncontradoError(
                f"No existe un mapeo de migración con id={mapeo_id!r}"
            )
        return mapeo

    def listar(self) -> List[MapeoMigracionCuenta]:
        return list(self._mapeos.values())

    # -- cardinalidad N:1 / 1:N (REQ-MIG-008) ----------------------------
    #
    # Un mapeo NUNCA vive aislado: puede compartir `destino_cuenta_id` con
    # otros mapeos (fusión N:1, requiere `estrategia_conciliacion_saldos`
    # explícita) o -- si algo intentara mapear la MISMA cuenta origen hacia
    # destinos distintos -- representar una división 1:N, que este
    # servicio nunca deja confirmar. Un mapeo `RECHAZADO` es una decisión
    # humana de "esta correspondencia no aplica": no cuenta para ninguna
    # de las dos cardinalidades.

    def _destinos_activos_para_origen(
        self, origen_cuenta_id: str, excluir_id: str
    ) -> "set[str]":
        return {
            m.destino_cuenta_id
            for m in self._mapeos.values()
            if m.id != excluir_id
            and m.origen_cuenta_id == origen_cuenta_id
            and m.estado != EstadoMapeoMigracion.RECHAZADO
            and m.destino_cuenta_id is not None
        }

    def _origenes_activos_para_destino(
        self, destino_cuenta_id: str, excluir_id: str
    ) -> "set[str]":
        return {
            m.origen_cuenta_id
            for m in self._mapeos.values()
            if m.id != excluir_id
            and m.destino_cuenta_id == destino_cuenta_id
            and m.estado != EstadoMapeoMigracion.RECHAZADO
        }

    def _validar_cardinalidad_antes_de_confirmar(
        self,
        mapeo: MapeoMigracionCuenta,
        nuevo_destino_cuenta_id: Optional[str],
        estrategia_conciliacion_saldos: Optional[str],
    ) -> None:
        """Guardia de REQ-MIG-008, invocada por `aprobar()`/`editar()`
        ANTES de escribir cualquier cambio de estado.

        1. 1:N (la cuenta origen de `mapeo` ya está repartida hacia otro
           destino distinto de `nuevo_destino_cuenta_id`): se rechaza por
           completo, sin excepción -- ningún campo puede autorizarlo.
        2. N:1 (más de una cuenta origen activa apunta al mismo
           `nuevo_destino_cuenta_id`, contando a `mapeo`): exige
           `estrategia_conciliacion_saldos` no nula (ya presente en el
           mapeo o provista en esta misma llamada).

        No hace nada si `nuevo_destino_cuenta_id` es `None` (p.ej.
        `sin_match`): sin destino no hay cardinalidad que evaluar.
        """
        if nuevo_destino_cuenta_id is None:
            return

        otros_destinos = self._destinos_activos_para_origen(
            mapeo.origen_cuenta_id, excluir_id=mapeo.id
        )
        otros_destinos.discard(nuevo_destino_cuenta_id)
        if otros_destinos:
            raise DivisionUnoANoAutomaticaError(
                f"división 1:N fuera de alcance automático: la cuenta "
                f"origen {mapeo.origen_cuenta_id} (mapeo {mapeo.id}) ya "
                f"está mapeada hacia {sorted(otros_destinos)!r} además de "
                f"{nuevo_destino_cuenta_id!r}. Dividir una cuenta origen "
                "entre varias cuentas destino requiere un proceso "
                "contable manual separado; nunca se aprueba ni se edita "
                "por este camino."
            )

        otros_origenes = self._origenes_activos_para_destino(
            nuevo_destino_cuenta_id, excluir_id=mapeo.id
        )
        origenes_relacionados = otros_origenes | {mapeo.origen_cuenta_id}
        if len(origenes_relacionados) > 1:
            estrategia = (
                estrategia_conciliacion_saldos
                if estrategia_conciliacion_saldos is not None
                else mapeo.estrategia_conciliacion_saldos
            )
            if not estrategia or not str(estrategia).strip():
                raise EstrategiaConciliacionRequeridaError(
                    f"El mapeo {mapeo.id} fusiona varias cuentas origen "
                    f"({sorted(origenes_relacionados)!r}) hacia el mismo "
                    f"destino {nuevo_destino_cuenta_id!r} (mapeo N:1); el "
                    "contador debe confirmar explícitamente "
                    "'estrategia_conciliacion_saldos' (no nulo) antes de "
                    "aprobar."
                )

    # -- decisiones humanas (REQ-MIG-007) --------------------------------

    def _exigir_pendiente_y_responsable(
        self,
        mapeo: MapeoMigracionCuenta,
        decidido_por: Optional[str],
        accion: str,
    ) -> None:
        if not decidido_por or not str(decidido_por).strip():
            raise DecisionSinResponsableError(
                f"No se puede {accion} el mapeo {mapeo.id} sin "
                "identificar quién toma la decisión (decidido_por vacío)."
            )
        if mapeo.estado != EstadoMapeoMigracion.PENDIENTE:
            raise TransicionEstadoInvalidaError(
                f"El mapeo {mapeo.id} ya no está pendiente "
                f"(estado actual={mapeo.estado.value!r}); no se puede "
                f"{accion} dos veces ni sobrescribir una decisión humana "
                "previa."
            )

    def aprobar(
        self,
        mapeo_id: str,
        decidido_por: str,
        nota: Optional[str] = None,
        estrategia_conciliacion_saldos: Optional[str] = None,
    ) -> MapeoMigracionCuenta:
        """Único camino para que un mapeo `alerta_riesgo`/`fuzzy`/
        `sin_match` llegue a `estado=APROBADO` (REQ-MIG-007 / ADR-3).

        REQ-MIG-008: antes de confirmar, valida la cardinalidad de la
        correspondencia contra el resto del repositorio -- ver
        `_validar_cardinalidad_antes_de_confirmar`. Un mapeo N:1 exige
        `estrategia_conciliacion_saldos` (aquí o ya presente en el
        mapeo); un mapeo 1:N nunca se aprueba, sin importar qué se pase.
        """
        mapeo = self.obtener(mapeo_id)
        self._exigir_pendiente_y_responsable(mapeo, decidido_por, "aprobar")
        self._validar_cardinalidad_antes_de_confirmar(
            mapeo, mapeo.destino_cuenta_id, estrategia_conciliacion_saldos
        )
        estrategia_final = (
            estrategia_conciliacion_saldos
            if estrategia_conciliacion_saldos is not None
            else mapeo.estrategia_conciliacion_saldos
        )
        actualizado = mapeo.model_copy(
            update={
                "estado": EstadoMapeoMigracion.APROBADO,
                "aprobado_por": decidido_por,
                "aprobado_en": _ahora_iso(),
                "nota": nota if nota is not None else mapeo.nota,
                "estrategia_conciliacion_saldos": estrategia_final,
            }
        )
        self._mapeos[mapeo_id] = actualizado
        self._registrar_auditoria(
            accion="aprobar",
            decidido_por=decidido_por,
            nota=actualizado.nota,
            mapeo_antes=mapeo,
            mapeo_despues=actualizado,
        )
        return actualizado

    def rechazar(
        self,
        mapeo_id: str,
        decidido_por: str,
        nota: str,
    ) -> MapeoMigracionCuenta:
        mapeo = self.obtener(mapeo_id)
        self._exigir_pendiente_y_responsable(mapeo, decidido_por, "rechazar")
        if not nota or not nota.strip():
            raise ValueError(
                "Rechazar un mapeo exige una nota que justifique la "
                "decisión."
            )
        actualizado = mapeo.model_copy(
            update={
                "estado": EstadoMapeoMigracion.RECHAZADO,
                "aprobado_por": decidido_por,
                "aprobado_en": _ahora_iso(),
                "nota": nota,
            }
        )
        self._mapeos[mapeo_id] = actualizado
        self._registrar_auditoria(
            accion="rechazar",
            decidido_por=decidido_por,
            nota=actualizado.nota,
            mapeo_antes=mapeo,
            mapeo_despues=actualizado,
        )
        return actualizado

    def editar(
        self,
        mapeo_id: str,
        decidido_por: str,
        destino_cuenta_id: str,
        nota: str,
        estrategia_conciliacion_saldos: Optional[str] = None,
    ) -> MapeoMigracionCuenta:
        """Corrige el `destino_cuenta_id` propuesto por el motor antes de
        confirmarlo y lo deja en `estado=EDITADO` — una decisión humana
        explícita y auditable, distinta de `APROBADO` (el humano no
        aceptó la sugerencia tal cual, la corrigió), pero igual de válida
        que una aprobación para efectos de trazabilidad: registra quién
        decidió y cuándo, igual que `aprobar()`.

        REQ-MIG-008: el `destino_cuenta_id` corregido pasa por la misma
        validación de cardinalidad que `aprobar()` -- editar no es una
        puerta trasera para crear una división 1:N ni para fusionar N:1
        sin declarar `estrategia_conciliacion_saldos`.
        """
        mapeo = self.obtener(mapeo_id)
        self._exigir_pendiente_y_responsable(mapeo, decidido_por, "editar")
        if not destino_cuenta_id or not str(destino_cuenta_id).strip():
            raise ValueError(
                "Editar un mapeo exige un destino_cuenta_id explícito "
                "(nunca se inventa ni se deja vacío)."
            )
        if not nota or not nota.strip():
            raise ValueError(
                "Editar un mapeo exige una nota que justifique el cambio "
                "de destino."
            )
        self._validar_cardinalidad_antes_de_confirmar(
            mapeo, destino_cuenta_id, estrategia_conciliacion_saldos
        )
        estrategia_final = (
            estrategia_conciliacion_saldos
            if estrategia_conciliacion_saldos is not None
            else mapeo.estrategia_conciliacion_saldos
        )
        actualizado = mapeo.model_copy(
            update={
                "destino_cuenta_id": destino_cuenta_id,
                "estado": EstadoMapeoMigracion.EDITADO,
                "aprobado_por": decidido_por,
                "aprobado_en": _ahora_iso(),
                "nota": nota,
                "estrategia_conciliacion_saldos": estrategia_final,
            }
        )
        self._mapeos[mapeo_id] = actualizado
        self._registrar_auditoria(
            accion="editar",
            decidido_por=decidido_por,
            nota=actualizado.nota,
            mapeo_antes=mapeo,
            mapeo_despues=actualizado,
        )
        return actualizado
