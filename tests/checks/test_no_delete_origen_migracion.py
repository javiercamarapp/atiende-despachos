# -*- coding: utf-8 -*-
"""
REQ-MIG-011 (docs/BLUEPRINT-AGENTES-FISCALES.md §3 — Migración/fusión de
catálogo de cuentas).

Criterio de aceptación exacto:
  "El migrador nunca debe emitir `DELETE` sobre las pólizas/cuentas de
  origen; prueba estática tipo `scripts/checks/no-delete-events.ts`
  (equivalente Python) que falle el build si aparece un `DELETE FROM`
  en `migracion_catalogo/migrador.py` contra las tablas de origen."

Esta suite prueba el chequeo estático real de
`scripts/checks/no_delete_origen_migracion.py` (se carga por ruta de
archivo, sin mocks) en dos frentes:

1. Contra el archivo real `b2b_ai/features/migracion_catalogo/
   migrador.py` tal como existe hoy en el repo -- debe pasar limpio.
2. Contra texto fuente sintético que SÍ contiene `DELETE FROM` en
   distintas variantes (mayúsculas, comillas, esquema calificado, salto
   de línea, tabla no resoluble estáticamente) -- para probar que el
   chequeo de verdad detecta la violación y no es un chequeo vacío que
   "pasa" solo porque nunca encontraría nada. Sin esto, un chequeo
   estático roto (p. ej. una regex que nunca matchea nada) pasaría la
   prueba #1 de forma indistinguible de uno que sí funciona.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "checks" / "no_delete_origen_migracion.py"
MIGRADOR_REAL = REPO_ROOT / "b2b_ai" / "features" / "migracion_catalogo" / "migrador.py"


def _cargar_modulo_chequeo():
    """Carga el script por ruta de archivo (no es un paquete instalado
    ni tiene __init__.py: es un script de chequeo standalone, tal como
    lo describe el criterio de aceptación -- `python scripts/checks/
    no_delete_origen_migracion.py`)."""
    spec = importlib.util.spec_from_file_location(
        "no_delete_origen_migracion", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def chequeo():
    return _cargar_modulo_chequeo()


# ---------------------------------------------------------------------------
# El archivo real del repo hoy debe estar limpio.
# ---------------------------------------------------------------------------


class TestArchivoRealEstaLimpio:
    def test_migrador_real_existe_en_la_ruta_esperada(self):
        # Si esto falla, el script apunta a una ruta obsoleta -- no un
        # falso negativo silencioso.
        assert MIGRADOR_REAL.exists(), (
            f"{MIGRADOR_REAL} no existe; el script de chequeo apunta a "
            "una ruta desactualizada."
        )

    def test_sin_violaciones_en_migrador_real(self, chequeo):
        assert chequeo.verificar(MIGRADOR_REAL) == []

    def test_main_devuelve_0_sobre_el_archivo_real(self, chequeo, capsys):
        codigo = chequeo.main()
        assert codigo == 0
        salida = capsys.readouterr()
        assert "OK" in salida.out
        assert salida.err == ""

    def test_ejecutar_script_como_proceso_termina_en_0(self):
        # Ejercita el comando previsto exacto del criterio de
        # aceptación: `python scripts/checks/no_delete_origen_migracion.py`.
        resultado = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert resultado.returncode == 0, resultado.stderr
        assert "OK" in resultado.stdout

    def test_archivo_inexistente_no_es_violacion(self, chequeo, tmp_path):
        # Un módulo previsto que aún no existe no debe reportarse como
        # violación (distinto de un archivo que existe y sí tiene un
        # DELETE prohibido).
        assert chequeo.verificar(tmp_path / "no_existe.py") == []


# ---------------------------------------------------------------------------
# El chequeo de verdad detecta un DELETE FROM contra una tabla de origen,
# en variantes realistas de cómo podría escribirse en Python (SQL crudo,
# multilínea, comillas, esquema calificado, mayúsculas/minúsculas).
# ---------------------------------------------------------------------------


class TestDetectaDeleteContraTablasDeOrigen:
    @pytest.mark.parametrize(
        "fragmento",
        [
            'cur.execute("DELETE FROM cuentas_contables WHERE id = %s", (cuenta_id,))',
            'cur.execute("DELETE FROM asientos_contables WHERE id = %s", (poliza_id,))',
            "cur.execute('delete from cuentas_contables where tenant_id = %s')",
            'cur.execute("DELETE   FROM\n    asientos_contables\nWHERE id = %s")',
            'cur.execute("DELETE FROM public.cuentas_contables WHERE id = %s")',
            'cur.execute(\'DELETE FROM "asientos_contables" WHERE id = %s\')',
            "cur.execute(f\"DELETE FROM {TABLA_ASIENTOS} WHERE id = %s\")",
        ],
        ids=[
            "cuentas_contables-simple",
            "asientos_contables-simple",
            "minusculas",
            "multilinea",
            "esquema-calificado",
            "comillas-dobles",
            "fstring-tabla-dinamica",
        ],
    )
    def test_detecta_violacion(self, chequeo, fragmento):
        violaciones = chequeo.encontrar_deletes_contra_origen(fragmento)
        assert violaciones, f"debió detectar una violación en: {fragmento!r}"

    def test_verificar_detecta_delete_contra_origen_en_archivo_arbitrario(
        self, chequeo, tmp_path
    ):
        # `main()` usa la ruta real hard-codeada (ARCHIVO_MIGRADOR); el
        # código de salida 1 end-to-end contra un migrador con DELETE se
        # prueba más abajo ejecutando el script real como subproceso
        # sobre un árbol de repo temporal.
        archivo_falso = tmp_path / "migrador.py"
        archivo_falso.write_text(
            'def borrar_poliza_origen(cur, poliza_id):\n'
            '    cur.execute("DELETE FROM asientos_contables WHERE id = %s", (poliza_id,))\n'
        )
        violaciones = chequeo.verificar(archivo_falso)
        assert violaciones
        assert "asientos_contables" in violaciones[0].lower()

    def test_script_como_proceso_falla_si_migrador_tiene_delete_origen(
        self, tmp_path
    ):
        """Prueba de extremo a extremo del criterio de aceptación: copia
        el árbol `scripts/checks/` a un directorio temporal que imita la
        estructura del repo (`<tmp>/scripts/checks/...py` y
        `<tmp>/b2b_ai/features/migracion_catalogo/migrador.py`), planta
        un DELETE FROM contra una tabla de origen en el migrador, y
        verifica que ejecutar el script real como subproceso termina
        con código de salida distinto de 0 -- "falla el build", tal
        cual exige el criterio de aceptación."""
        raiz_falsa = tmp_path / "repo_falso"
        script_destino = raiz_falsa / "scripts" / "checks" / "no_delete_origen_migracion.py"
        migrador_destino = (
            raiz_falsa / "b2b_ai" / "features" / "migracion_catalogo" / "migrador.py"
        )
        script_destino.parent.mkdir(parents=True)
        migrador_destino.parent.mkdir(parents=True)
        script_destino.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        migrador_destino.write_text(
            'def migrar_poliza(cur, poliza_id, cuenta_id):\n'
            '    """Migra y purga la póliza origen (PROHIBIDO)."""\n'
            '    cur.execute("DELETE FROM asientos_contables WHERE id = %s", (poliza_id,))\n',
            encoding="utf-8",
        )

        resultado = subprocess.run(
            [sys.executable, str(script_destino)],
            cwd=raiz_falsa,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert resultado.returncode == 1
        assert "asientos_contables" in resultado.stderr.lower()
        assert "REQ-MIG-011" in resultado.stderr


# ---------------------------------------------------------------------------
# El chequeo NO debe convertirse en un candado que bloquee DELETEs
# legítimos contra tablas que no son de origen (p. ej. una cola interna
# de trabajo del propio módulo) -- el criterio de aceptación es
# específico a "contra las tablas de origen", no "cualquier DELETE".
# ---------------------------------------------------------------------------


class TestNoBloqueaDeletesLegitimosFueraDeOrigen:
    @pytest.mark.parametrize(
        "fragmento",
        [
            'cur.execute("DELETE FROM polizas_bloqueadas WHERE id = %s", (job_id,))',
            'cur.execute("DELETE FROM migracion_catalogo_cache_temporal WHERE id = %s", (x,))',
        ],
    )
    def test_no_marca_violacion_tabla_ajena_a_origen(self, chequeo, fragmento):
        assert chequeo.encontrar_deletes_contra_origen(fragmento) == []

    def test_ausencia_total_de_delete_no_marca_nada(self, chequeo):
        texto = (
            "def migrar_linea_con_mapeo(mapeo, linea_origen):\n"
            "    validar_mapeo_migrable(mapeo)\n"
            "    return {**linea_origen, 'cuenta_id': mapeo.destino_cuenta_id}\n"
        )
        assert chequeo.encontrar_deletes_contra_origen(texto) == []


# ---------------------------------------------------------------------------
# Normalización de nombres de tabla: comillas, mayúsculas, esquema.
# ---------------------------------------------------------------------------


class TestNormalizacionDeNombreDeTabla:
    @pytest.mark.parametrize(
        "crudo,esperado",
        [
            ("cuentas_contables", "cuentas_contables"),
            ('"cuentas_contables"', "cuentas_contables"),
            ("`asientos_contables`", "asientos_contables"),
            ("public.cuentas_contables", "cuentas_contables"),
            ("CUENTAS_CONTABLES", "cuentas_contables"),
        ],
    )
    def test_normaliza(self, chequeo, crudo, esperado):
        assert chequeo._normalizar_nombre_tabla(crudo) == esperado

    def test_identificador_literal_vs_placeholder(self, chequeo):
        assert chequeo._es_identificador_literal("cuentas_contables") is True
        assert chequeo._es_identificador_literal("{tabla}") is False
        assert chequeo._es_identificador_literal("%s") is False
        assert chequeo._es_identificador_literal("tabla-con-guion") is False
