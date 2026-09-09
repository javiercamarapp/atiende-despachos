# -*- coding: utf-8 -*-
"""
test_cargar_catalogo_merge_no_destructivo.py — REQ-MIG-017
(docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-MIG).

Bug real confirmado por auditoría: `ContabilidadService.cargar_catalogo()`
sobrescribía destructivamente el catálogo completo de cuentas de una
empresa (`self._catalogo[empresa_id] = cuentas`) en vez de hacer merge.

Este archivo tiene DOS partes:

  1. `TestReproduceElBugOriginal` -- reproduce el bug real tal cual lo
     describe la auditoría: cargar un catálogo, registrar un asiento
     (una "póliza") real contra una de sus cuentas, volver a cargar un
     catálogo que NO incluya esa cuenta, y confirmar que la cuenta con
     movimientos NUNCA desaparece del catálogo ni deja su saldo huérfano
     del balance/estado de resultados. Contra el código SIN el fix (ver
     el propio historial de commits de esta rama: el commit anterior a
     éste reproduce el bug con exactamente este mismo test -- correr
     `git show <commit-anterior>:.../service.py` y aplicar este test
     sobre esa versión falla tal como se documenta en el resumen del PR),
     `test_cuenta_con_movimientos_no_desaparece_ni_pierde_saldo` FALLA.

  2. `TestCaminoFeliz` -- el caso normal: un catálogo nuevo agrega
     cuentas y actualiza nombres sin tocar las que ya tienen movimientos,
     y sin duplicar ninguna cuenta.
"""
from __future__ import annotations

import pytest
from datetime import date

from b2b_ai.features.contabilidad.models import (
    AsientoContable,
    CuentaCatalogo,
    GrupoCuenta,
    LineaAsiento,
    NaturalezaCuenta,
    TipoAsiento,
    TipoCuenta,
)
from b2b_ai.features.contabilidad.service import ContabilidadService


EMPRESA = "EMPRESA_MIG017"
PERIODO = "2026-01"


@pytest.fixture
def service() -> ContabilidadService:
    s = ContabilidadService()
    yield s
    s._reset_state()


def _catalogo_inicial() -> list[CuentaCatalogo]:
    """Catálogo con 3 cuentas: caja, bancos (la que tendrá movimientos)
    y proveedores."""
    return [
        CuentaCatalogo(
            codigo="1100", nombre="Caja", tipo=TipoCuenta.ACTIVO,
            grupo=GrupoCuenta.ACTIVO_CORRIENTE,
            naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
        ),
        CuentaCatalogo(
            codigo="1200", nombre="Bancos", tipo=TipoCuenta.ACTIVO,
            grupo=GrupoCuenta.ACTIVO_CORRIENTE,
            naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
        ),
        CuentaCatalogo(
            codigo="2100", nombre="Proveedores", tipo=TipoCuenta.PASIVO,
            grupo=GrupoCuenta.PASIVO_CORRIENTE,
            naturaleza=NaturalezaCuenta.ACREEDORA, empresa_id=EMPRESA,
        ),
    ]


def _registrar_poliza_real(service: ContabilidadService) -> AsientoContable:
    """Registra un asiento (póliza) real de pago a proveedor contra la
    cuenta '1200' (Bancos), usando el catálogo ya cargado."""
    asiento = AsientoContable(
        empresa_id=EMPRESA,
        partida_id="PART-MIG017-1",
        fecha=date(2026, 1, 10),
        periodo=PERIODO,
        tipo=TipoAsiento.EGRESO,
        descripcion="Pago a proveedor",
        lineas=[
            LineaAsiento(cuenta_contable="2100", debito=5000.0, credito=0.0),
            LineaAsiento(cuenta_contable="1200", debito=0.0, credito=5000.0),
        ],
    )
    return service.registrar_asiento(asiento)


def _catalogo_nuevo_sin_bancos() -> list[CuentaCatalogo]:
    """Catálogo entrante que YA NO incluye '1200' (Bancos) -- p.ej. el
    contador subió un catálogo actualizado y olvidó esa cuenta, o el
    cliente mandó un catálogo recortado."""
    return [
        CuentaCatalogo(
            codigo="1100", nombre="Caja Chica", tipo=TipoCuenta.ACTIVO,
            grupo=GrupoCuenta.ACTIVO_CORRIENTE,
            naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
        ),
        CuentaCatalogo(
            codigo="2100", nombre="Proveedores Nacionales",
            tipo=TipoCuenta.PASIVO, grupo=GrupoCuenta.PASIVO_CORRIENTE,
            naturaleza=NaturalezaCuenta.ACREEDORA, empresa_id=EMPRESA,
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Reproducción del bug original (adversarial)
# ---------------------------------------------------------------------------

class TestReproduceElBugOriginal:
    """Reproduce el escenario exacto de la auditoría REQ-MIG-017."""

    def test_cuenta_con_movimientos_no_desaparece_ni_pierde_saldo(
        self, service: ContabilidadService
    ) -> None:
        # 1) Alta inicial del catálogo del tenant.
        service.cargar_catalogo(EMPRESA, _catalogo_inicial())

        # 2) Se registra una póliza REAL contra la cuenta '1200' (Bancos).
        _registrar_poliza_real(service)

        # Confirmamos que el asiento sí quedó registrado y que el saldo
        # es visible en el balance ANTES de la segunda carga.
        balance_antes = service.generar_balance_general(EMPRESA, PERIODO)
        assert balance_antes.pasivos_corriente != 0.0, (
            "precondición del test: la póliza debe afectar el balance "
            "antes de recargar el catálogo"
        )

        # 3) Se vuelve a cargar un catálogo que NO incluye '1200'.
        service.cargar_catalogo(EMPRESA, _catalogo_nuevo_sin_bancos())

        catalogo_resultante = service.consultar_catalogo_cuentas(EMPRESA)
        codigos_resultantes = {c.codigo for c in catalogo_resultante}

        # ESTA es la aserción que reproduce el bug: antes del fix,
        # `cargar_catalogo` hacía `self._catalogo[empresa_id] = cuentas`
        # y '1200' desaparecía por completo del catálogo -- esta
        # aserción FALLA contra el código sin el fix.
        assert "1200" in codigos_resultantes, (
            "BUG REQ-MIG-017: la cuenta '1200' tenía una póliza real "
            "registrada y fue borrada del catálogo por una recarga que "
            "no la incluía -- exactamente el escenario que preocupa al "
            "dueño del proyecto (rompe integridad referencial contra "
            "asientos ya registrados)."
        )

        # Y el balance general, que depende de poder clasificar '1200'
        # contra el catálogo, debe seguir reflejando la póliza -- si la
        # cuenta desapareció del catálogo, este balance queda en 0
        # (saldo huérfano perdido en silencio, sin ninguna excepción).
        balance_despues = service.generar_balance_general(EMPRESA, PERIODO)
        assert balance_despues.pasivos_corriente == balance_antes.pasivos_corriente, (
            "BUG REQ-MIG-017: el saldo de una póliza real quedó huérfano "
            "(0) porque su cuenta ya no está en el catálogo tras la "
            "recarga."
        )

        # Además: se debe reportar como huérfana pendiente de revisión
        # manual (no se pierde en silencio la señal de que había una
        # cuenta con movimientos que el catálogo entrante omitió).
        assert "1200" in service.huerfanas_pendientes(EMPRESA)

        # La cuenta huérfana conserva sus datos originales intactos (no
        # se le aplican los cambios del catálogo entrante, que ni
        # siquiera la mencionaba).
        cuenta_1200 = next(c for c in catalogo_resultante if c.codigo == "1200")
        assert cuenta_1200.nombre == "Bancos"
        assert cuenta_1200.activa is True

    def test_reproduce_directo_sobre_el_dict_interno(
        self, service: ContabilidadService
    ) -> None:
        """Variante más directa del mismo bug, sin pasar por balance
        general: compara el tamaño y el contenido del catálogo antes y
        después de una recarga parcial."""
        service.cargar_catalogo(EMPRESA, _catalogo_inicial())
        _registrar_poliza_real(service)

        antes = {c.codigo for c in service.consultar_catalogo_cuentas(EMPRESA)}
        assert antes == {"1100", "1200", "2100"}

        service.cargar_catalogo(EMPRESA, _catalogo_nuevo_sin_bancos())

        despues = {c.codigo for c in service.consultar_catalogo_cuentas(EMPRESA)}
        # Con el bug original: despues == {"1100", "2100"} (se perdió
        # "1200"). Con el fix: nunca se pierde una cuenta con movimientos.
        assert despues == {"1100", "1200", "2100"}


# ---------------------------------------------------------------------------
# 2. Camino feliz
# ---------------------------------------------------------------------------

class TestCaminoFeliz:
    """Un catálogo nuevo agrega cuentas y actualiza nombres, sin tocar
    las que tienen movimientos."""

    def test_agrega_cuentas_nuevas(self, service: ContabilidadService) -> None:
        service.cargar_catalogo(EMPRESA, _catalogo_inicial())

        resultado = service.cargar_catalogo(EMPRESA, [
            *_catalogo_inicial(),
            CuentaCatalogo(
                codigo="4100", nombre="Ventas", tipo=TipoCuenta.INGRESO,
                grupo=GrupoCuenta.INGRESOS_OPERACIONALES,
                naturaleza=NaturalezaCuenta.ACREEDORA, empresa_id=EMPRESA,
            ),
        ])

        codigos = {c.codigo for c in resultado}
        assert codigos == {"1100", "1200", "2100", "4100"}
        assert len(resultado) == 4  # sin duplicados

    def test_actualiza_nombre_de_cuenta_existente_sin_recrearla(
        self, service: ContabilidadService
    ) -> None:
        service.cargar_catalogo(EMPRESA, _catalogo_inicial())

        resultado = service.cargar_catalogo(EMPRESA, [
            CuentaCatalogo(
                codigo="1100", nombre="Caja General (renombrada)",
                tipo=TipoCuenta.ACTIVO, grupo=GrupoCuenta.ACTIVO_CORRIENTE,
                naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
            ),
            CuentaCatalogo(
                codigo="1200", nombre="Bancos", tipo=TipoCuenta.ACTIVO,
                grupo=GrupoCuenta.ACTIVO_CORRIENTE,
                naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
            ),
            CuentaCatalogo(
                codigo="2100", nombre="Proveedores", tipo=TipoCuenta.PASIVO,
                grupo=GrupoCuenta.PASIVO_CORRIENTE,
                naturaleza=NaturalezaCuenta.ACREEDORA, empresa_id=EMPRESA,
            ),
        ])

        assert len(resultado) == 3  # no se duplicó "1100"
        cuenta_1100 = next(c for c in resultado if c.codigo == "1100")
        assert cuenta_1100.nombre == "Caja General (renombrada)"

    def test_cuenta_sin_movimientos_omitida_se_marca_inactiva_no_se_pierde(
        self, service: ContabilidadService
    ) -> None:
        """'2100' nunca tuvo movimientos: es seguro retirarla del
        catálogo activo si el catálogo entrante ya no la incluye -- se
        marca `activa=False` en vez de borrarla físicamente."""
        service.cargar_catalogo(EMPRESA, _catalogo_inicial())
        # Ningún registrar_asiento aquí: "2100" no tiene movimientos.

        resultado = service.cargar_catalogo(EMPRESA, [
            CuentaCatalogo(
                codigo="1100", nombre="Caja", tipo=TipoCuenta.ACTIVO,
                grupo=GrupoCuenta.ACTIVO_CORRIENTE,
                naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
            ),
            CuentaCatalogo(
                codigo="1200", nombre="Bancos", tipo=TipoCuenta.ACTIVO,
                grupo=GrupoCuenta.ACTIVO_CORRIENTE,
                naturaleza=NaturalezaCuenta.DEUDORA, empresa_id=EMPRESA,
            ),
        ])

        codigos = {c.codigo for c in resultado}
        assert "2100" in codigos, "no se elimina físicamente, se conserva"
        cuenta_2100 = next(c for c in resultado if c.codigo == "2100")
        assert cuenta_2100.activa is False
        assert "2100" not in service.huerfanas_pendientes(EMPRESA), (
            "sin movimientos no cuenta como huérfana pendiente de "
            "revisión: se resolvió sola marcándose inactiva"
        )

    def test_no_hay_catalogo_previo_equivale_a_cargar_tal_cual(
        self, service: ContabilidadService
    ) -> None:
        catalogo = _catalogo_inicial()
        resultado = service.cargar_catalogo(EMPRESA, catalogo)
        assert len(resultado) == len(catalogo)
        assert {c.codigo for c in resultado} == {"1100", "1200", "2100"}
        assert service.huerfanas_pendientes(EMPRESA) == []
