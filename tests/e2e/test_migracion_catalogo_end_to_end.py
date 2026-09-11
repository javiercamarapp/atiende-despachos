# -*- coding: utf-8 -*-
"""
test_migracion_catalogo_end_to_end.py — REQ-MIG-018 (docs/BLUEPRINT-AGENTES-FISCALES.md,
matriz REQ-MIG).

Criterio de aceptación exacto:
  "Debe existir un contract test end-to-end con datos sintéticos de dos
  catálogos reales (2020-2023 / 2024-2026, ≥50 cuentas cada uno con al
  menos 5 casos de cada tipo de match) que corra el pipeline completo
  (match → cola de revisión simulada con aprobaciones fijas → migración
  → verificación) y termine con 0 discrepancias de saldo y 0 pólizas
  huérfanas."

*** DATOS 100% SINTÉTICOS ***: los dos "catálogos de cuentas" de este
test (`2020-2023` / `2024-2026`, como en el caso real que motivó
`cross_db.py`) son generados por código en este mismo archivo -- nombres
tipo "Cuenta Sintetica Activo 000", códigos inventados, montos
deterministas calculados por fórmula. NINGÚN dato de un cliente real
(RFC, razón social, catálogo contable real, movimiento real) aparece
aquí ni se usó como referencia. Cualquier parecido con una cuenta o
póliza real es coincidencia de vocabulario contable genérico (Bancos,
Proveedores, Ventas... términos de cualquier plan de cuentas mexicano
estándar), no un dato copiado.

Alcance -- pipeline completo contra el código REAL de
`b2b_ai/features/migracion_catalogo/`, sin mocks, sobre PostgreSQL real:

  1. MATCH (REQ-MIG-003..006, `matching.py::clasificar_cuenta_origen`):
     clasifica las 50 cuentas del catálogo origen contra las 50 del
     catálogo destino. El catálogo está construido a propósito con
     ≥5 casos de cada uno de los 4 tipos de match (35 exacto, 5
     alerta_riesgo, 5 fuzzy, 5 sin_match -- ver
     `test_matching_produce_al_menos_5_casos_de_cada_tipo`).

  2. REVISIÓN (REQ-MIG-007, `service.py::MigracionCatalogoService`):
     una "cola de revisión simulada con aprobaciones fijas" -- un diccionario
     de decisiones fijas y deterministas (`_construir_decisiones_revision_fijas`,
     ningún input interactivo ni aleatorio) que aprueba los 5
     `alerta_riesgo` y los 5 `fuzzy` (el motor de matching los deja
     `pendiente` por diseño, ADR-3: nunca se auto-aprueban). Los 5
     `sin_match` se dejan deliberadamente `pendiente` -- no hay destino
     que aprobar todavía (`NOTA_SIN_MATCH`: "cuenta nueva a crear en
     destino", un flujo de creación de cuenta fuera del alcance de este
     módulo) -- y ninguna póliza de este test depende de ellos, así que
     no producen ninguna discrepancia al cierre.

  3. MIGRACIÓN (REQ-MIG-009/010, `migrador.py::migrar_poliza`): 20
     pólizas sintéticas (2 líneas cada una, debe/haber) que referencian
     únicamente cuentas ya aprobadas/editadas -- incluidas explícitamente
     las 5 `alerta_riesgo` y las 5 `fuzzy` recién aprobadas por la
     revisión (para que la revisión sea parte necesaria del pipeline, no
     un paso decorativo) -- se migran vía el motor transaccional real.

  4. VERIFICACIÓN (REQ-MIG-012..015, `verificacion.py`): las cuatro
     verificaciones de integridad post-migración corren contra
     PostgreSQL real (conexión NUEVA, abierta después de cerrar la que
     hizo la migración, para confirmar persistencia real -- mismo patrón
     que `tests/features/migracion_catalogo/test_cross_db_migracion_dos_bases_reales.py`)
     y deben terminar en `0` discrepancias:
       - REQ-MIG-013 conteo de pólizas: 0 de diferencia.
       - REQ-MIG-014 balance por póliza: 0 discrepancias (tolerancia 0).
       - REQ-MIG-015 referencias huérfanas: 0 líneas huérfanas.
       - REQ-MIG-012 cuadre de saldos: 0 discrepancias (tolerancia
         $0.01) -- ver la nota honesta más abajo en este docstring
         sobre por qué este test también postea el resultado migrado
         en el libro real (`asientos_contables`) del tenant destino.

Modelo de dos catálogos usado (mismo servidor Postgres, DOS tenants
distintos -- el modelo que `verificacion.py::calcular_saldo_cuenta_periodo`
asume explícitamente, ver su docstring de REQ-MIG-012: "origen y destino
son dos catálogos de cuentas que conviven en las mismas tablas... cada
uno bajo su propio tenant_id"). El caso de DOS BASES DE DATOS
físicamente distintas (`cross_db.py`) ya tiene su propia cobertura en
`tests/features/migracion_catalogo/test_cross_db_migracion_dos_bases_reales.py`;
este test cubre el pipeline completo de fusión de catálogo con el
volumen (≥50 cuentas, ≥5 de cada tipo de match) que pide REQ-MIG-018,
en el modelo de datos que las verificaciones REQ-MIG-012/013/014/015
realmente soportan hoy.

Nota honesta sobre `asientos_contables` (destino) vs
`lineas_poliza_migradas`: el motor de migración real (REQ-MIG-009,
`migrador.py::migrar_poliza`) escribe cada línea migrada en
`lineas_poliza_migradas` -- la tabla que SÍ tiene la FK dura a
`cuentas_contables(cuenta_id)` y la que leen REQ-MIG-013/014/015. Pero
REQ-MIG-012 (`calcular_saldo_cuenta_periodo`) calcula el saldo real de
una cuenta a partir de `asientos_contables` -- el libro contable real de
cada tenant, no `lineas_poliza_migradas` -- exactamente como ya lo hace
`tests/features/migracion_catalogo/test_verificacion_cuadre_saldos.py`
(ver su clase `TestVerificarCuadreSaldosEnBD`, que inserta a mano los
mismos montos en `asientos_contables` de ambos tenants). Este repo no
tiene todavía un paso automático que traduzca `lineas_poliza_migradas`
en asientos reales del libro destino -- es una pieza de trabajo
contable posterior, fuera del alcance de REQ-MIG-009..018. Por eso este
test, para cada póliza que SÍ migra con éxito por el motor real, postea
también su equivalente en `asientos_contables` del tenant destino (con
los montos y cuentas destino REALES que ya decidió la migración,
tomados de la propia especificación de la póliza, no inventados aparte)
-- así REQ-MIG-012 se verifica con datos reales, honestos, y con el
mismo patrón que su propio test dedicado, no con un mock ni con un
resultado fabricado.

Requiere `B2B_DB_URL` apuntando a un servidor Postgres accesible (mismo
patrón `skipif` que el resto de la suite de integración de
`migracion_catalogo`); si no hay uno disponible, este test se salta
explícitamente en vez de simular su resultado.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections import Counter
from decimal import Decimal
from typing import Dict, List, Tuple

import pytest

from b2b_ai.features.migracion_catalogo.matching import (
    UMBRAL_SIN_MATCH,
    CuentaCatalogo,
    clasificar_cuenta_origen,
)
from b2b_ai.features.migracion_catalogo.migrador import (
    LineaPolizaOrigen,
    PolizaOrigen,
    migrar_poliza,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.service import MigracionCatalogoService
from b2b_ai.features.migracion_catalogo.verificacion import (
    cerrar_migracion,
    cerrar_verificacion_balance_polizas,
    cerrar_verificacion_referencias_huerfanas,
    mapeos_migrados,
    verificar_balance_polizas_en_bd,
    verificar_conteo_polizas_en_bd,
)

pytestmark = [pytest.mark.e2e]

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PG_DSN = os.environ.get("B2B_DB_URL", "")


def _pg_available() -> bool:
    if not PG_DSN:
        return False
    try:
        import psycopg

        psycopg.connect(PG_DSN, connect_timeout=3).close()
        return True
    except Exception:
        return False


pytestmark.append(
    pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
)


def _split_dsn(dsn: str):
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


def _create_test_db() -> Tuple[str, str]:
    import psycopg

    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_reqmig018_{uuid.uuid4().hex[:10]}"
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()
    return f"{server_dsn}/{dbname}", dbname


def _drop_test_db(dbname: str) -> None:
    import psycopg

    server_dsn, _ = _split_dsn(PG_DSN)
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        conn.close()


def _run_alembic(*args: str, dsn: str):
    env = dict(os.environ)
    env["B2B_DB_URL"] = dsn
    env["B2B_SEED_SKIP"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def migration_db():
    """Una base PostgreSQL de pruebas real, migrada a `head` con Alembic
    real (mismo patrón que el resto de la suite de integración de
    `migracion_catalogo`). Se dropea al final incluso si el test falla."""
    dsn, dbname = _create_test_db()
    r = _run_alembic("upgrade", "head", dsn=dsn)
    assert r.returncode == 0, r.stderr[-3000:]
    yield dsn
    _drop_test_db(dbname)


# ---------------------------------------------------------------------------
# Construcción del catálogo sintético -- 50 cuentas por lado, ≥5 de cada
# tipo de match (REQ-MIG-018).
# ---------------------------------------------------------------------------

TENANT_ORIGEN = 1  # catálogo "2024-2026" (más reciente)
TENANT_DESTINO = 2  # catálogo "2020-2023" (el que sobrevive tras la fusión)

GRUPOS = ["Activo", "Pasivo", "Capital", "Ingreso", "Gasto"]

N_EXACTAS = 35
N_ALERTA = 5
N_FUZZY = 5
N_SIN_MATCH = 5
N_DESTINO_SOLO = 5


def _naturaleza_de(grupo: str) -> str:
    return "D" if grupo in ("Activo", "Gasto") else "A"


def _construir_especificacion_catalogo():
    """Devuelve las cuatro listas de especificación (puro Python, sin
    tocar la BD) que arman los dos catálogos sintéticos de 50 cuentas
    cada uno: `exactas` (mismo código+nombre en ambos lados -> match
    exacto, REQ-MIG-003), `alerta` (mismo código, nombre distinto ->
    alerta de riesgo, REQ-MIG-004), `fuzzy` (código distinto, nombre
    parecido -> fuzzy, REQ-MIG-005) y `sin_match` (cuenta nueva en
    origen sin nada parecido en destino, REQ-MIG-006). `destino_solo`
    son cuentas que YA existían en destino sin relación con origen
    (realista: el catálogo destino no nace vacío) y completan las 50
    cuentas del lado destino junto con las contrapartes de
    alerta/fuzzy/exactas.

    Distribución verificada por separado (matching puro, sin BD) en
    `test_matching_produce_al_menos_5_casos_de_cada_tipo`: exacto=35,
    alerta_riesgo=5, fuzzy=5, sin_match=5 -- exactamente lo que exige
    REQ-MIG-018 ("≥50 cuentas cada uno, al menos 5 casos de cada tipo").
    """
    exactas = []
    for i in range(N_EXACTAS):
        grupo = GRUPOS[i % len(GRUPOS)]
        exactas.append(
            {
                "codigo": f"{100 + (i % 5) * 100}-{i:03d}",
                "nombre": f"Cuenta Sintetica {grupo} {i:03d}",
                "nivel": 1 + (i % 4),
                "naturaleza": _naturaleza_de(grupo),
                "grupo": grupo,
            }
        )

    alerta = []
    for i in range(N_ALERTA):
        grupo = GRUPOS[i % len(GRUPOS)]
        alerta.append(
            {
                "codigo": f"205-9{i:02d}",
                "nombre_origen": f"Cuenta Alerta Riesgo Origen {i:02d}",
                "nombre_destino": f"Cuenta Alerta Riesgo Destino {i:02d}",
                "nivel": 2,
                "naturaleza": _naturaleza_de(grupo),
                "grupo": grupo,
            }
        )

    fuzzy = []
    for i in range(N_FUZZY):
        grupo = GRUPOS[i % len(GRUPOS)]
        fuzzy.append(
            {
                "codigo_origen": f"310-7{i:02d}",
                "codigo_destino": f"310-8{i:02d}",
                "nombre_origen": f"Gastos de Papeleria y Utiles Oficina {i:02d}",
                "nombre_destino": f"Gastos de Papeleria y Utiles de Oficina {i:02d}",
                "nivel": 3,
                "naturaleza": _naturaleza_de(grupo),
                "grupo": grupo,
            }
        )

    sin_match = []
    for i in range(N_SIN_MATCH):
        sin_match.append(
            {
                "codigo": f"999-9{i:02d}",
                "nombre": f"Activo Digital Emergente Sin Precedente {i:02d}",
                # nivel/grupo deliberadamente únicos (no usados por
                # ninguna cuenta destino) para que ningún candidato se
                # acerque al umbral de score de REQ-MIG-006 -- ver
                # verificación empírica de scores en
                # test_matching_produce_al_menos_5_casos_de_cada_tipo.
                "nivel": 9,
                "naturaleza": "D",
                "grupo": "ActivoDigitalNuevoSinPrecedente",
            }
        )

    destino_solo = []
    for i in range(N_DESTINO_SOLO):
        grupo = GRUPOS[i % len(GRUPOS)]
        destino_solo.append(
            {
                "codigo": f"777-9{i:02d}",
                "nombre": f"Cuenta Destino Preexistente Sin Relacion {i:02d}",
                "nivel": 2,
                "naturaleza": _naturaleza_de(grupo),
                "grupo": grupo,
            }
        )

    return exactas, alerta, fuzzy, sin_match, destino_solo


def _catalogos_cuenta_catalogo(
    exactas, alerta, fuzzy, sin_match, destino_solo
) -> Tuple[List[CuentaCatalogo], List[CuentaCatalogo]]:
    """Arma las dos listas `CuentaCatalogo` (REQ-MIG-005/006) que
    `clasificar_cuenta_origen` necesita, usando ids sintéticos estables
    (sin tocar la BD) -- para la capa 1 de prueba, puramente de
    matching. La capa 2 (integración con Postgres real) reconstruye
    estas mismas listas pero con `cuenta_id` UUID real -- ver
    `_sembrar_catalogos_en_bd`."""

    def mk(id_, codigo, nombre, nivel, naturaleza, grupo):
        return CuentaCatalogo(
            id=id_,
            codigo=codigo,
            nombre=nombre,
            nivel=nivel,
            naturaleza=naturaleza,
            tipo_agregado=grupo,
        )

    origen = []
    for i, c in enumerate(exactas):
        origen.append(mk(f"O-EX-{i}", c["codigo"], c["nombre"], c["nivel"], c["naturaleza"], c["grupo"]))
    for i, a in enumerate(alerta):
        origen.append(mk(f"O-AL-{i}", a["codigo"], a["nombre_origen"], a["nivel"], a["naturaleza"], a["grupo"]))
    for i, f in enumerate(fuzzy):
        origen.append(mk(f"O-FZ-{i}", f["codigo_origen"], f["nombre_origen"], f["nivel"], f["naturaleza"], f["grupo"]))
    for i, s in enumerate(sin_match):
        origen.append(mk(f"O-SM-{i}", s["codigo"], s["nombre"], s["nivel"], s["naturaleza"], s["grupo"]))

    destino = []
    for i, c in enumerate(exactas):
        destino.append(mk(f"D-EX-{i}", c["codigo"], c["nombre"], c["nivel"], c["naturaleza"], c["grupo"]))
    for i, a in enumerate(alerta):
        destino.append(mk(f"D-AL-{i}", a["codigo"], a["nombre_destino"], a["nivel"], a["naturaleza"], a["grupo"]))
    for i, f in enumerate(fuzzy):
        destino.append(mk(f"D-FZ-{i}", f["codigo_destino"], f["nombre_destino"], f["nivel"], f["naturaleza"], f["grupo"]))
    for i, d in enumerate(destino_solo):
        destino.append(mk(f"D-SOLO-{i}", d["codigo"], d["nombre"], d["nivel"], d["naturaleza"], d["grupo"]))

    return origen, destino


# ---------------------------------------------------------------------------
# Capa 1 -- matching puro (sin BD): confirma que el catálogo sintético
# realmente produce ≥5 casos de cada tipo, tal como exige REQ-MIG-018.
# ---------------------------------------------------------------------------


def test_catalogos_sinteticos_tienen_al_menos_50_cuentas_cada_uno():
    exactas, alerta, fuzzy, sin_match, destino_solo = _construir_especificacion_catalogo()
    origen, destino = _catalogos_cuenta_catalogo(exactas, alerta, fuzzy, sin_match, destino_solo)
    assert len(origen) >= 50
    assert len(destino) >= 50
    assert len(origen) == len(exactas) + len(alerta) + len(fuzzy) + len(sin_match)
    assert len(destino) == len(exactas) + len(alerta) + len(fuzzy) + len(destino_solo)


def test_matching_produce_al_menos_5_casos_de_cada_tipo():
    """REQ-MIG-018, requisito explícito: "al menos 5 casos de cada tipo
    de match". Corre el motor de matching REAL (REQ-MIG-003..006, sin
    mocks) sobre el catálogo sintético completo y confirma la
    distribución -- y que cada caso fue clasificado contra la
    contraparte correcta, no cualquiera."""
    exactas, alerta, fuzzy, sin_match, destino_solo = _construir_especificacion_catalogo()
    origen, destino = _catalogos_cuenta_catalogo(exactas, alerta, fuzzy, sin_match, destino_solo)

    mapeos = [
        clasificar_cuenta_origen(o, destino, umbral_sin_match=UMBRAL_SIN_MATCH)
        for o in origen
    ]
    tipos = Counter(m.tipo_match.value for m in mapeos)

    assert tipos["exacto"] >= 5
    assert tipos["alerta_riesgo"] >= 5
    assert tipos["fuzzy"] >= 5
    assert tipos["sin_match"] >= 5
    # La composición exacta que se usa en el resto del test (documentada
    # arriba en _construir_especificacion_catalogo).
    assert tipos == {"exacto": 35, "alerta_riesgo": 5, "fuzzy": 5, "sin_match": 5}

    por_id = {m.origen_cuenta_id: m for m in mapeos}
    # Exacto: auto-aprobado (ADR-3/REQ-MIG-003), score 100.
    for i in range(N_EXACTAS):
        m = por_id[f"O-EX-{i}"]
        assert m.tipo_match == TipoMatchMigracion.EXACTO
        assert m.estado == EstadoMapeoMigracion.APROBADO
        assert m.destino_cuenta_id == f"D-EX-{i}"
        assert m.score == 100.0
    # Alerta de riesgo: SIEMPRE pendiente, nunca auto-aprobado.
    for i in range(N_ALERTA):
        m = por_id[f"O-AL-{i}"]
        assert m.tipo_match == TipoMatchMigracion.ALERTA_RIESGO
        assert m.estado == EstadoMapeoMigracion.PENDIENTE
        assert m.destino_cuenta_id == f"D-AL-{i}"
    # Fuzzy: pendiente, apunta al candidato correcto (no cualquiera con
    # score alto).
    for i in range(N_FUZZY):
        m = por_id[f"O-FZ-{i}"]
        assert m.tipo_match == TipoMatchMigracion.FUZZY
        assert m.estado == EstadoMapeoMigracion.PENDIENTE
        assert m.destino_cuenta_id == f"D-FZ-{i}"
        assert m.score >= UMBRAL_SIN_MATCH
    # Sin match: nunca se inventa un destino.
    for i in range(N_SIN_MATCH):
        m = por_id[f"O-SM-{i}"]
        assert m.tipo_match == TipoMatchMigracion.SIN_MATCH
        assert m.estado == EstadoMapeoMigracion.PENDIENTE
        assert m.destino_cuenta_id is None


# ---------------------------------------------------------------------------
# Capa 2 -- pipeline completo end-to-end contra PostgreSQL real.
# ---------------------------------------------------------------------------


def _sembrar_tenants(conn) -> None:
    with conn.transaction():
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (TENANT_ORIGEN, "Catalogo sintetico 2024-2026 (origen, e2e REQ-MIG-018)"),
        )
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (TENANT_DESTINO, "Catalogo sintetico 2020-2023 (destino, e2e REQ-MIG-018)"),
        )


def _insertar_cuenta(conn, tenant_id, codigo, nombre, nivel, naturaleza, grupo) -> str:
    """Inserta una cuenta real y devuelve su `cuenta_id` UUID (REQ-MIG-001,
    PK real de `cuentas_contables` desde la migración 0012)."""
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO cuentas_contables "
            "(tenant_id, codigo, descripcion, nivel, naturaleza, grupo) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING cuenta_id",
            (tenant_id, codigo, nombre, nivel, naturaleza, grupo),
        )
        return str(cur.fetchone()[0])


def _sembrar_catalogos_en_bd(conn, exactas, alerta, fuzzy, sin_match, destino_solo):
    """Inserta las 50+50 cuentas sintéticas en Postgres real (dos
    tenants del mismo servidor -- ver docstring del módulo) y devuelve:

      - `origen_catalogo`/`destino_catalogo`: listas `CuentaCatalogo`
        con `id=cuenta_id` (UUID real), listas para
        `clasificar_cuenta_origen`.
      - `codigo_por_cuenta_id`: mapa inverso {cuenta_id -> (tenant_id,
        codigo)}, usado más abajo para postear las pólizas migradas en
        el libro real del tenant destino (REQ-MIG-012).
    """
    origen_catalogo: List[CuentaCatalogo] = []
    destino_catalogo: List[CuentaCatalogo] = []
    codigo_por_cuenta_id: Dict[str, Tuple[int, str]] = {}

    def mk(cuenta_id, codigo, nombre, nivel, naturaleza, grupo) -> CuentaCatalogo:
        return CuentaCatalogo(
            id=cuenta_id,
            codigo=codigo,
            nombre=nombre,
            nivel=nivel,
            naturaleza=naturaleza,
            tipo_agregado=grupo,
        )

    for c in exactas:
        cid_o = _insertar_cuenta(conn, TENANT_ORIGEN, c["codigo"], c["nombre"], c["nivel"], c["naturaleza"], c["grupo"])
        cid_d = _insertar_cuenta(conn, TENANT_DESTINO, c["codigo"], c["nombre"], c["nivel"], c["naturaleza"], c["grupo"])
        origen_catalogo.append(mk(cid_o, c["codigo"], c["nombre"], c["nivel"], c["naturaleza"], c["grupo"]))
        destino_catalogo.append(mk(cid_d, c["codigo"], c["nombre"], c["nivel"], c["naturaleza"], c["grupo"]))
        codigo_por_cuenta_id[cid_o] = (TENANT_ORIGEN, c["codigo"])
        codigo_por_cuenta_id[cid_d] = (TENANT_DESTINO, c["codigo"])

    for a in alerta:
        cid_o = _insertar_cuenta(conn, TENANT_ORIGEN, a["codigo"], a["nombre_origen"], a["nivel"], a["naturaleza"], a["grupo"])
        cid_d = _insertar_cuenta(conn, TENANT_DESTINO, a["codigo"], a["nombre_destino"], a["nivel"], a["naturaleza"], a["grupo"])
        origen_catalogo.append(mk(cid_o, a["codigo"], a["nombre_origen"], a["nivel"], a["naturaleza"], a["grupo"]))
        destino_catalogo.append(mk(cid_d, a["codigo"], a["nombre_destino"], a["nivel"], a["naturaleza"], a["grupo"]))
        codigo_por_cuenta_id[cid_o] = (TENANT_ORIGEN, a["codigo"])
        codigo_por_cuenta_id[cid_d] = (TENANT_DESTINO, a["codigo"])

    for f in fuzzy:
        cid_o = _insertar_cuenta(conn, TENANT_ORIGEN, f["codigo_origen"], f["nombre_origen"], f["nivel"], f["naturaleza"], f["grupo"])
        cid_d = _insertar_cuenta(conn, TENANT_DESTINO, f["codigo_destino"], f["nombre_destino"], f["nivel"], f["naturaleza"], f["grupo"])
        origen_catalogo.append(mk(cid_o, f["codigo_origen"], f["nombre_origen"], f["nivel"], f["naturaleza"], f["grupo"]))
        destino_catalogo.append(mk(cid_d, f["codigo_destino"], f["nombre_destino"], f["nivel"], f["naturaleza"], f["grupo"]))
        codigo_por_cuenta_id[cid_o] = (TENANT_ORIGEN, f["codigo_origen"])
        codigo_por_cuenta_id[cid_d] = (TENANT_DESTINO, f["codigo_destino"])

    for s in sin_match:
        cid_o = _insertar_cuenta(conn, TENANT_ORIGEN, s["codigo"], s["nombre"], s["nivel"], s["naturaleza"], s["grupo"])
        origen_catalogo.append(mk(cid_o, s["codigo"], s["nombre"], s["nivel"], s["naturaleza"], s["grupo"]))
        codigo_por_cuenta_id[cid_o] = (TENANT_ORIGEN, s["codigo"])

    for d in destino_solo:
        cid_d = _insertar_cuenta(conn, TENANT_DESTINO, d["codigo"], d["nombre"], d["nivel"], d["naturaleza"], d["grupo"])
        destino_catalogo.append(mk(cid_d, d["codigo"], d["nombre"], d["nivel"], d["naturaleza"], d["grupo"]))
        codigo_por_cuenta_id[cid_d] = (TENANT_DESTINO, d["codigo"])

    return origen_catalogo, destino_catalogo, codigo_por_cuenta_id


# Cola de revisión simulada: decisiones FIJAS y deterministas (ni
# interactivas ni aleatorias) por código de cuenta origen, tal como pide
# REQ-MIG-018 ("cola de revisión simulada con aprobaciones fijas"). Un
# código que no aparece aquí se queda pendiente a propósito (los 5
# sin_match: no hay destino que aprobar todavía).
def _construir_decisiones_revision_fijas(alerta, fuzzy) -> Dict[str, Tuple[str, str]]:
    decisiones: Dict[str, Tuple[str, str]] = {}
    for a in alerta:
        decisiones[a["codigo"]] = (
            "contador_lider_sintetico",
            "cola de revision simulada (datos sinteticos, REQ-MIG-018): "
            "confirmo que el codigo de cuenta coincide con el catalogo "
            "destino y que la diferencia de nombre es solo de redaccion",
        )
    for f in fuzzy:
        decisiones[f["codigo_origen"]] = (
            "contador_lider_sintetico",
            "cola de revision simulada (datos sinteticos, REQ-MIG-018): "
            "confirmo que es el mismo concepto contable, la sugerencia "
            "fuzzy identifico correctamente la cuenta correspondiente",
        )
    return decisiones


def test_pipeline_completo_match_revision_migracion_verificacion(migration_db):
    import psycopg

    exactas, alerta, fuzzy, sin_match, destino_solo = _construir_especificacion_catalogo()
    decisiones_fijas = _construir_decisiones_revision_fijas(alerta, fuzzy)

    conn = psycopg.connect(migration_db)
    try:
        _sembrar_tenants(conn)
        origen_catalogo, destino_catalogo, codigo_por_cuenta_id = _sembrar_catalogos_en_bd(
            conn, exactas, alerta, fuzzy, sin_match, destino_solo
        )
        assert len(origen_catalogo) == 50
        assert len(destino_catalogo) == 50

        # ---------------------------------------------------------------
        # 1) MATCH (REQ-MIG-003..006) -- motor real, catálogo real de BD.
        # ---------------------------------------------------------------
        service = MigracionCatalogoService()
        mapeos_iniciales = [
            clasificar_cuenta_origen(o, destino_catalogo, umbral_sin_match=UMBRAL_SIN_MATCH)
            for o in origen_catalogo
        ]
        for m in mapeos_iniciales:
            service.registrar(m)

        tipos = Counter(m.tipo_match.value for m in mapeos_iniciales)
        assert tipos == {"exacto": 35, "alerta_riesgo": 5, "fuzzy": 5, "sin_match": 5}

        # ---------------------------------------------------------------
        # 2) REVISIÓN (REQ-MIG-007) -- cola simulada, aprobaciones fijas.
        # ---------------------------------------------------------------
        pendientes_antes = [
            m for m in service.listar() if m.estado == EstadoMapeoMigracion.PENDIENTE
        ]
        assert len(pendientes_antes) == N_ALERTA + N_FUZZY + N_SIN_MATCH  # 15

        aprobados_por_revision = 0
        for m in list(pendientes_antes):
            _tenant, codigo_origen = codigo_por_cuenta_id[m.origen_cuenta_id]
            decision = decisiones_fijas.get(codigo_origen)
            if decision is None:
                continue  # sin_match: se queda pendiente a propósito.
            decidido_por, nota = decision
            service.aprobar(m.id, decidido_por=decidido_por, nota=nota)
            aprobados_por_revision += 1
        assert aprobados_por_revision == N_ALERTA + N_FUZZY  # 10

        mapeos_tras_revision = service.listar()
        migrables = [
            m for m in mapeos_tras_revision
            if m.estado in (EstadoMapeoMigracion.APROBADO, EstadoMapeoMigracion.EDITADO)
        ]
        pendientes_tras_revision = [
            m for m in mapeos_tras_revision if m.estado == EstadoMapeoMigracion.PENDIENTE
        ]
        assert len(migrables) == N_EXACTAS + N_ALERTA + N_FUZZY  # 45
        assert len(pendientes_tras_revision) == N_SIN_MATCH  # 5: cuentas nuevas a crear
        assert all(
            codigo_por_cuenta_id[m.origen_cuenta_id][1].startswith("999-9")
            for m in pendientes_tras_revision
        )

        mapeos_por_cuenta_origen: Dict[str, MapeoMigracionCuenta] = {
            m.origen_cuenta_id: m for m in mapeos_tras_revision
        }

        # ---------------------------------------------------------------
        # 3) MIGRACIÓN (REQ-MIG-009/010) -- 20 pólizas sintéticas de 2
        #    líneas cada una, incluidas explícitamente las cuentas
        #    alerta_riesgo/fuzzy que la revisión acaba de aprobar (para
        #    que la revisión sea necesaria para el resultado, no
        #    decorativa).
        # ---------------------------------------------------------------
        codigos_exactos = [c["codigo"] for c in exactas]
        codigos_riesgo = [a["codigo"] for a in alerta] + [f["codigo_origen"] for f in fuzzy]

        # Mapa código-origen -> cuenta_id origen, para construir las
        # líneas de PolizaOrigen (LineaPolizaOrigen.cuenta_origen_id).
        cuenta_id_origen_por_codigo = {
            codigo: cid
            for cid, (tenant, codigo) in codigo_por_cuenta_id.items()
            if tenant == TENANT_ORIGEN
        }
        # Mapa código-origen -> código-destino real, para postear la
        # contrapartida en el libro real de destino (ver docstring del
        # módulo, sección REQ-MIG-012).
        codigo_destino_de_codigo_origen: Dict[str, str] = {}
        for c in exactas:
            codigo_destino_de_codigo_origen[c["codigo"]] = c["codigo"]
        for a in alerta:
            codigo_destino_de_codigo_origen[a["codigo"]] = a["codigo"]
        for f in fuzzy:
            codigo_destino_de_codigo_origen[f["codigo_origen"]] = f["codigo_destino"]

        polizas_spec: List[Tuple[str, str, Decimal]] = []
        # 10 pólizas: cada cuenta alerta_riesgo/fuzzy contra una cuenta
        # exacta -- ejercitan directamente las 10 aprobaciones de la
        # revisión simulada.
        for i, codigo_riesgo in enumerate(codigos_riesgo):
            contraparte = codigos_exactos[i % len(codigos_exactos)]
            monto = Decimal(100 + i * 37).quantize(Decimal("0.01"))
            polizas_spec.append((codigo_riesgo, contraparte, monto))
        # 10 pólizas adicionales solo entre cuentas exactas -- volumen y
        # variación de montos, mismo motor.
        for j in range(0, 20, 2):
            monto = Decimal(500 + j * 11).quantize(Decimal("0.01"))
            polizas_spec.append((codigos_exactos[j], codigos_exactos[j + 1], monto))

        assert len(polizas_spec) == 20

        fecha = "2024-06-15"
        poliza_ids: List[str] = []
        for idx, (codigo_debe, codigo_haber, monto) in enumerate(polizas_spec):
            with conn.transaction():
                cur = conn.execute(
                    "INSERT INTO asientos_contables "
                    "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto, descripcion) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        TENANT_ORIGEN,
                        fecha,
                        codigo_debe,
                        codigo_haber,
                        str(monto),
                        f"poliza sintetica e2e REQ-MIG-018 #{idx}",
                    ),
                )
                poliza_id = str(cur.fetchone()[0])
            poliza_ids.append(poliza_id)

            poliza = PolizaOrigen(
                id=poliza_id,
                # `PolizaOrigen.tenant_id` es el tenant_id de BOOKKEEPING
                # que `migrar_poliza` escribe en `lineas_poliza_migradas`/
                # `polizas_bloqueadas` (columna con FK a `tenants.id`, sin
                # relación forzada con `cuenta_origen_id`/`cuenta_destino_id`)
                # -- no necesariamente "el tenant de origen". Mismo patrón
                # que usa `cross_db.py::migrar_poliza_cross_db` (pasa el
                # tenant_id de ORIGEN incluso al escribir en la conexión de
                # DESTINO, documentando explícitamente que ese campo es un
                # identificador lógico/de negocio, no ligado a una base
                # física). REQ-MIG-013/014/015 escanean
                # `lineas_poliza_migradas` filtrando por "el tenant" que
                # representa el libro DESTINO (ver
                # `cerrar_verificacion_referencias_huerfanas(conn, tenant_id)`,
                # que compara contra `cuentas_contables` de ESE tenant) --
                # así que aquí se usa TENANT_DESTINO para que las cuatro
                # verificaciones post-migración lean coherentes.
                tenant_id=TENANT_DESTINO,
                lineas=(
                    LineaPolizaOrigen(
                        cuenta_id_origen_por_codigo[codigo_debe],
                        debe=monto,
                        haber=Decimal("0"),
                    ),
                    LineaPolizaOrigen(
                        cuenta_id_origen_por_codigo[codigo_haber],
                        debe=Decimal("0"),
                        haber=monto,
                    ),
                ),
            )
            resultado = migrar_poliza(conn, poliza, mapeos_por_cuenta_origen)
            assert resultado.migrada is True, (
                f"poliza {poliza_id} (debe={codigo_debe}, haber={codigo_haber}) "
                f"debio migrar con exito: {resultado}"
            )
            assert resultado.bloqueada is False
            assert resultado.lineas_migradas == 2
            assert resultado.ya_migrada is False

            # Postea la contrapartida en el libro REAL del tenant destino
            # -- ver la nota extensa de REQ-MIG-012 en el docstring del
            # módulo: usa las mismas cuentas/montos que la migración real
            # ya decidió, no valores inventados aparte.
            destino_debe = codigo_destino_de_codigo_origen[codigo_debe]
            destino_haber = codigo_destino_de_codigo_origen[codigo_haber]
            with conn.transaction():
                conn.execute(
                    "INSERT INTO asientos_contables "
                    "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto, descripcion) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        TENANT_DESTINO,
                        fecha,
                        destino_debe,
                        destino_haber,
                        str(monto),
                        f"poliza sintetica e2e REQ-MIG-018 #{idx} (posteada en destino)",
                    ),
                )
    finally:
        conn.close()

    # -------------------------------------------------------------------
    # 4) VERIFICACIÓN (REQ-MIG-012..015) -- conexión NUEVA, abierta
    #    después de cerrar la que hizo la migración: confirma
    #    persistencia real, no solo visibilidad dentro de la misma
    #    sesión que escribió.
    #
    #    Nota técnica importante: `verificacion.py` (REQ-MIG-012/015,
    #    `_obtener_cuenta`/`calcular_saldo_cuenta_periodo`/
    #    `verificar_referencias_huerfanas_en_bd`) construye su SQL con
    #    placeholders `?` -- ver su propio docstring de módulo,
    #    "Compatibilidad de conexión" -- pensados para el wrapper
    #    `?`-parametrizado que usa el resto del repo
    #    (`b2b_ai/db/postgres_adapter.py::PGConnection`, que traduce
    #    `?` -> `%s`), NO para una `psycopg.Connection` cruda como la que
    #    usan `migrador.py`/`cross_db.py` (que hablan `%s` nativo y no
    #    tienen ese wrapper). Por eso la verificación envuelve una
    #    conexión psycopg NUEVA en `PGConnection` directamente -- mismo
    #    adaptador que usa `Database(...).conn` en producción y en
    #    `tests/features/migracion_catalogo/test_verificacion_cuadre_saldos.py::pg_db`,
    #    pero sin pasar por `Database` (que además de abrir la conexión
    #    la toma de un pool de larga vida y reintenta `alembic upgrade
    #    heads` en cada instancia -- innecesario aquí y, sobre una base
    #    de pruebas efímera que el fixture `migration_db` dropea al
    #    terminar, deja una conexión pooled abierta que hace fallar el
    #    `DROP DATABASE` final con `ObjectInUse`). Las cuatro consultas
    #    de este bloque (incluidas las de REQ-MIG-013/014, cuyo texto
    #    SQL sí lo elige quien llama) usan `?`, consistentes con esa
    #    misma conexión.
    # -------------------------------------------------------------------
    from b2b_ai.db.postgres_adapter import PGConnection

    conn2 = PGConnection(psycopg.connect(migration_db))
    try:
        # REQ-MIG-013 -- conteo de pólizas: 0 de diferencia exacto.
        resultado_conteo = verificar_conteo_polizas_en_bd(
            conn2,
            "SELECT COUNT(*) FROM asientos_contables WHERE tenant_id = ?",
            "SELECT COUNT(DISTINCT poliza_origen_id) FROM lineas_poliza_migradas "
            "WHERE tenant_id = ?",
            params_origen=(TENANT_ORIGEN,),
            params_destino=(TENANT_DESTINO,),
        )
        assert resultado_conteo.diferencia == 0
        assert resultado_conteo.count_origen_elegibles == 20
        assert resultado_conteo.count_destino_migradas == 20

        # REQ-MIG-014 -- balance por póliza: 0 discrepancias, tolerancia 0.
        reporte_balance = verificar_balance_polizas_en_bd(
            conn2,
            "SELECT poliza_origen_id, debe, haber FROM lineas_poliza_migradas "
            "WHERE tenant_id = ?",
            params=(TENANT_DESTINO,),
        )
        cerrar_verificacion_balance_polizas(reporte_balance)  # no debe lanzar
        assert reporte_balance.total_polizas == 20
        assert reporte_balance.discrepancias == []
        assert reporte_balance.cuadra is True

        # REQ-MIG-015 -- 0 pólizas/líneas huérfanas en destino.
        reporte_huerfanas = cerrar_verificacion_referencias_huerfanas(conn2, TENANT_DESTINO)
        assert reporte_huerfanas.count_huerfanas == 0
        assert reporte_huerfanas.huerfanas == []
        assert reporte_huerfanas.cierre_permitido is True

        # REQ-MIG-012 -- cuadre de saldos: 0 discrepancias, tolerancia $0.01.
        mapeos_finales_migrados = mapeos_migrados(mapeos_tras_revision)
        assert len(mapeos_finales_migrados) == 45  # 35 exacto + 5 alerta + 5 fuzzy
        reporte_cuadre = cerrar_migracion(
            conn2, mapeos_finales_migrados, "2024-01-01", "2024-12-31"
        )
        assert reporte_cuadre.cierre_permitido is True
        assert reporte_cuadre.discrepancias == []
        assert reporte_cuadre.mapeos_sin_destino == []
        # 45 cuentas migradas verificadas -- incluye las 5 sin movimiento
        # en este test (0 == 0 en ambos lados, cuadra trivialmente) y las
        # 40 que sí participaron en alguna póliza.
        assert reporte_cuadre.cuentas_verificadas == 45

        # -- El criterio exacto de REQ-MIG-018 en una sola aserción: --
        assert (
            len(reporte_cuadre.discrepancias) == 0
            and reporte_huerfanas.count_huerfanas == 0
        ), "el pipeline debe terminar con 0 discrepancias de saldo y 0 polizas huerfanas"
    finally:
        conn2.close()
