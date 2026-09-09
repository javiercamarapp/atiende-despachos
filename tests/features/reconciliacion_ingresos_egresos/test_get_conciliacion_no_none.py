# -*- coding: utf-8 -*-
"""
test_get_conciliacion_no_none.py — REQ-IVA-012

Bug de código muerto: `conciliar_depositos_auxiliares()` construía el
objeto `ConciliacionIngresosEgresos` y lo retornaba, pero nunca lo
asignaba a `self._conciliaciones[...]`. Como resultado, `get_conciliacion()`
siempre devolvía `None`, sin importar cuántas veces se hubiera llamado a
`conciliar_depositos_auxiliares()` antes.

Esto bloqueaba que las clasificaciones de depósito con evidencia
documental (financiamiento/aportación de socio/garantía — REQ-IVA-002/
003/013) fueran recuperables después de conciliar: la única fuente de
verdad quedaba en el valor de retorno de esa llamada, no en el servicio.

Prueba de regresión (sin mocks): se llama al servicio real
`ReconciliacionIngresosEgresosService.conciliar_depositos_auxiliares(...)`
y luego a `get_conciliacion(periodo, tenant_id)` con la misma
combinación período/tenant, y se confirma que NO devuelve `None` sino la
misma conciliación que se acaba de calcular.
"""
from __future__ import annotations

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    AuxiliarContable,
    ClasificacionDeposito,
    DepositoBancario,
    MovimientoAuxiliar,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)


def _make_deposito(**overrides) -> DepositoBancario:
    defaults = dict(
        id="DEP-001",
        fecha="2026-06-15",
        monto=100000.0,
        descripcion="Pago cliente",
        referencia="CFDI-ABC-001",
        banco="BBVA",
        cuenta="0123456789",
        es_credito=True,
    )
    defaults.update(overrides)
    return DepositoBancario(**defaults)


def _make_auxiliar(**overrides) -> AuxiliarContable:
    defaults = dict(
        cuenta_id="AUX-001",
        cuenta_mayor="4010",
        cuenta_auxiliar="001",
        descripcion="Ingresos por ventas",
        saldo_inicial=50000.0,
        movimientos=[
            MovimientoAuxiliar(
                fecha="2026-06-15",
                concepto="Pago cliente ABC",
                debe=0.0,
                haber=100000.0,
                referencia="CFDI-ABC-001",
                tipo="ingreso",
            ),
        ],
        saldo_final=150000.0,
    )
    defaults.update(overrides)
    return AuxiliarContable(**defaults)


def test_get_conciliacion_no_devuelve_none_tras_conciliar():
    """Tras conciliar, get_conciliacion(periodo, tenant_id) debe recuperar
    la misma conciliación en vez de None."""
    service = ReconciliacionIngresosEgresosService()
    dep = _make_deposito()
    aux = _make_auxiliar()

    resultado = service.conciliar_depositos_auxiliares(
        [dep], [aux], periodo="2026-06", tenant_id="tenant-abc"
    )

    recuperada = service.get_conciliacion("2026-06", "tenant-abc")

    assert recuperada is not None
    assert recuperada is resultado
    assert recuperada.periodo == "2026-06"
    assert recuperada.tenant_id == "tenant-abc"
    assert len(recuperada.depositos) == 1
    assert len(recuperada.clasificaciones) == 1


def test_get_conciliacion_preserva_clasificaciones_con_evidencia():
    """Las clasificaciones con fundamento (financiamiento/aportación/
    garantía — REQ-IVA-002/003/013) deben seguir siendo recuperables desde
    el servicio después de conciliar, no solo en el valor de retorno."""
    service = ReconciliacionIngresosEgresosService()
    dep = _make_deposito(
        id="DEP-002",
        referencia="CONTRATO-MUTUO-01",
        descripcion="Préstamo de socio según contrato de mutuo",
        monto=200000.0,
    )
    aux = _make_auxiliar(
        cuenta_id="AUX-002",
        movimientos=[
            MovimientoAuxiliar(
                fecha="2026-06-20",
                concepto="Préstamo recibido",
                debe=0.0,
                haber=200000.0,
                referencia="CONTRATO-MUTUO-01",
                tipo="ingreso",
            ),
        ],
    )

    resultado = service.conciliar_depositos_auxiliares(
        [dep], [aux], periodo="2026-06", tenant_id="tenant-xyz"
    )

    recuperada = service.get_conciliacion("2026-06", "tenant-xyz")

    assert recuperada is not None
    assert len(recuperada.clasificaciones) == len(resultado.clasificaciones) == 1
    assert recuperada.clasificaciones[0].deposito_id == "DEP-002"


def test_get_conciliacion_sin_conciliar_previamente_devuelve_none():
    """Sanity check: si nunca se llamó a conciliar_depositos_auxiliares
    para ese período/tenant, get_conciliacion debe seguir devolviendo
    None (no debe inventar datos)."""
    service = ReconciliacionIngresosEgresosService()
    assert service.get_conciliacion("2099-01", "tenant-nunca-conciliado") is None


def test_conciliaciones_de_distintos_tenants_no_se_pisan():
    """Dos conciliaciones del mismo período pero distinto tenant deben
    quedar almacenadas bajo llaves independientes (aislamiento multi-tenant
    también en el almacenamiento en memoria)."""
    service = ReconciliacionIngresosEgresosService()
    dep_a = _make_deposito(id="DEP-A", referencia="REF-A", monto=1000.0)
    dep_b = _make_deposito(id="DEP-B", referencia="REF-B", monto=2000.0)

    resultado_a = service.conciliar_depositos_auxiliares(
        [dep_a], [], periodo="2026-06", tenant_id="tenant-1"
    )
    resultado_b = service.conciliar_depositos_auxiliares(
        [dep_b], [], periodo="2026-06", tenant_id="tenant-2"
    )

    recuperada_a = service.get_conciliacion("2026-06", "tenant-1")
    recuperada_b = service.get_conciliacion("2026-06", "tenant-2")

    assert recuperada_a is resultado_a
    assert recuperada_b is resultado_b
    assert recuperada_a.depositos[0].id == "DEP-A"
    assert recuperada_b.depositos[0].id == "DEP-B"


def test_conciliar_sin_periodo_ni_tenant_sigue_siendo_recuperable():
    """Llamadas que no pasan periodo/tenant_id (comportamiento previo,
    usado por la suite existente) deben seguir funcionando y quedar
    almacenadas bajo la llave por defecto, no perderse."""
    service = ReconciliacionIngresosEgresosService()
    dep = _make_deposito()
    aux = _make_auxiliar()

    resultado = service.conciliar_depositos_auxiliares([dep], [aux])

    recuperada = service.get_conciliacion("", None)

    assert recuperada is not None
    assert recuperada is resultado
