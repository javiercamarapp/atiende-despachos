"""
test_contabilidad.py — Tests para el módulo de Contabilidad.

Cubre:
  - Generación de balance general
  - Generación de estado de resultados
  - Registro y validación de asientos contables
  - Consulta de catálogo de cuentas
  - Conciliación de asientos
  - Cálculo de impuestos (ISR, IVA, PTU)
  - Casos borde: saldos negativos, períodos vacíos, multi-empresa
"""
from __future__ import annotations

import pytest
from datetime import date

from b2b_ai.features.contabilidad.models import (
    AsientoContable,
    BalanceGeneral,
    CuentaCatalogo,
    EstadoResultados,
    GrupoCuenta,
    LineaAsiento,
    NaturalezaCuenta,
    TipoAsiento,
    TipoCuenta,
)
from b2b_ai.features.contabilidad.service import (
    ContabilidadError,
    ContabilidadService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service() -> ContabilidadService:
    """Servicio limpio para cada test."""
    s = ContabilidadService()
    yield s
    s._reset_state()


@pytest.fixture
def empresa_a() -> str:
    return "EMPRESA_A_001"


@pytest.fixture
def empresa_b() -> str:
    return "EMPRESA_B_002"


@pytest.fixture
def periodo() -> str:
    return "2026-01"


@pytest.fixture
def catalogo_basico() -> list[CuentaCatalogo]:
    """Catálogo de cuentas realista para empresa manufacturera."""
    return [
        CuentaCatalogo(
            codigo="1100",
            nombre="Caja",
            tipo=TipoCuenta.ACTIVO,
            grupo=GrupoCuenta.ACTIVO_CORRIENTE,
            nivel=2,
            naturaleza=NaturalezaCuenta.DEUDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="1200",
            nombre="Bancos",
            tipo=TipoCuenta.ACTIVO,
            grupo=GrupoCuenta.ACTIVO_CORRIENTE,
            nivel=2,
            naturaleza=NaturalezaCuenta.DEUDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="1500",
            nombre="Inmuebles",
            tipo=TipoCuenta.ACTIVO,
            grupo=GrupoCuenta.ACTIVO_NO_CORRIENTE,
            nivel=2,
            naturaleza=NaturalezaCuenta.DEUDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="2100",
            nombre="Proveedores",
            tipo=TipoCuenta.PASIVO,
            grupo=GrupoCuenta.PASIVO_CORRIENTE,
            nivel=2,
            naturaleza=NaturalezaCuenta.ACREEDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="2200",
            nombre="Créditos Bancarios",
            tipo=TipoCuenta.PASIVO,
            grupo=GrupoCuenta.PASIVO_NO_CORRIENTE,
            nivel=2,
            naturaleza=NaturalezaCuenta.ACREEDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="3100",
            nombre="Capital Social",
            tipo=TipoCuenta.CAPITAL,
            grupo=GrupoCuenta.CAPITAL_CONTABLE,
            nivel=2,
            naturaleza=NaturalezaCuenta.ACREEDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="4100",
            nombre="Ventas",
            tipo=TipoCuenta.INGRESO,
            grupo=GrupoCuenta.INGRESOS_OPERACIONALES,
            nivel=2,
            naturaleza=NaturalezaCuenta.ACREEDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="5100",
            nombre="Costo de Mercancía Vendida",
            tipo=TipoCuenta.COSTO,
            grupo=GrupoCuenta.COSTOS,
            nivel=2,
            naturaleza=NaturalezaCuenta.DEUDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="6100",
            nombre="Gastos de Nómina",
            tipo=TipoCuenta.GASTO,
            grupo=GrupoCuenta.GASTOS_OPERACIONALES,
            nivel=2,
            naturaleza=NaturalezaCuenta.DEUDORA,
            empresa_id="EMPRESA_A_001",
        ),
        CuentaCatalogo(
            codigo="6200",
            nombre="Gastos de Arrendamiento",
            tipo=TipoCuenta.GASTO,
            grupo=GrupoCuenta.GASTOS_OPERACIONALES,
            nivel=2,
            naturaleza=NaturalezaCuenta.DEUDORA,
            empresa_id="EMPRESA_A_001",
        ),
    ]


@pytest.fixture
def asiento_balanceado(empresa_a: str, periodo: str) -> AsientoContable:
    """Asiento que cuadra: débito == crédito."""
    return AsientoContable(
        empresa_id=empresa_a,
        partida_id="PART-001",
        fecha=date(2026, 1, 15),
        periodo=periodo,
        tipo=TipoAsiento.DIARIO,
        descripcion="Compra de mercancía a crédito",
        lineas=[
            LineaAsiento(
                cuenta_contable="5100",
                debito=50000.0,
                credito=0.0,
                descripcion="Costo de mercancía",
            ),
            LineaAsiento(
                cuenta_contable="2100",
                debito=0.0,
                credito=50000.0,
                descripcion="A proveedores",
            ),
        ],
    )


@pytest.fixture
def asiento_no_balanceado(empresa_a: str, periodo: str) -> AsientoContable:
    """Asiento que NO cuadra: débito != crédito."""
    return AsientoContable(
        empresa_id=empresa_a,
        partida_id="PART-002",
        fecha=date(2026, 1, 15),
        periodo=periodo,
        tipo=TipoAsiento.DIARIO,
        descripcion="Asiento desbalanceado",
        lineas=[
            LineaAsiento(
                cuenta_contable="1100",
                debito=10000.0,
                credito=0.0,
            ),
            LineaAsiento(
                cuenta_contable="4100",
                debito=0.0,
                credito=5000.0,
            ),
        ],
    )


def _cargar_datos_completos(
    service: ContabilidadService,
    empresa_id: str,
    periodo: str,
    catalogo: list[CuentaCatalogo],
) -> None:
    """Helper: carga catálogo y asientos de ejemplo."""
    service.cargar_catalogo(empresa_id, catalogo)

    asientos_data = [
        # Venta de mercancía
        AsientoContable(
            empresa_id=empresa_id,
            partida_id="PART-100",
            fecha=date(2026, 1, 10),
            periodo=periodo,
            tipo=TipoAsiento.INGRESO,
            descripcion="Venta de mercancía",
            lineas=[
                LineaAsiento(
                    cuenta_contable="1200",
                    debito=200000.0,
                    credito=0.0,
                    descripcion="Bancos",
                ),
                LineaAsiento(
                    cuenta_contable="4100",
                    debito=0.0,
                    credito=200000.0,
                    descripcion="Ventas",
                ),
            ],
        ),
        # Costo de mercancía
        AsientoContable(
            empresa_id=empresa_id,
            partida_id="PART-101",
            fecha=date(2026, 1, 10),
            periodo=periodo,
            tipo=TipoAsiento.EGRESO,
            descripcion="Costo de mercancía vendida",
            lineas=[
                LineaAsiento(
                    cuenta_contable="5100",
                    debito=80000.0,
                    credito=0.0,
                    descripcion="CMV",
                ),
                LineaAsiento(
                    cuenta_contable="2100",
                    debito=0.0,
                    credito=80000.0,
                    descripcion="Proveedores",
                ),
            ],
        ),
        # Nómina
        AsientoContable(
            empresa_id=empresa_id,
            partida_id="PART-102",
            fecha=date(2026, 1, 15),
            periodo=periodo,
            tipo=TipoAsiento.EGRESO,
            descripcion="Nómina quincenal",
            lineas=[
                LineaAsiento(
                    cuenta_contable="6100",
                    debito=45000.0,
                    credito=0.0,
                    descripcion="Nómina",
                ),
                LineaAsiento(
                    cuenta_contable="1200",
                    debito=0.0,
                    credito=45000.0,
                    descripcion="Bancos",
                ),
            ],
        ),
        # Arrendamiento
        AsientoContable(
            empresa_id=empresa_id,
            partida_id="PART-103",
            fecha=date(2026, 1, 20),
            periodo=periodo,
            tipo=TipoAsiento.EGRESO,
            descripcion="Renta de oficina",
            lineas=[
                LineaAsiento(
                    cuenta_contable="6200",
                    debito=15000.0,
                    credito=0.0,
                    descripcion="Arrendamiento",
                ),
                LineaAsiento(
                    cuenta_contable="1200",
                    debito=0.0,
                    credito=15000.0,
                    descripcion="Bancos",
                ),
            ],
        ),
        # Inmueble (activo no corriente)
        AsientoContable(
            empresa_id=empresa_id,
            partida_id="PART-104",
            fecha=date(2026, 1, 5),
            periodo=periodo,
            tipo=TipoAsiento.APERTURA,
            descripcion="Compra de equipo",
            lineas=[
                LineaAsiento(
                    cuenta_contable="1500",
                    debito=100000.0,
                    credito=0.0,
                    descripcion="Inmuebles",
                ),
                LineaAsiento(
                    cuenta_contable="2200",
                    debito=0.0,
                    credito=100000.0,
                    descripcion="Crédito bancario",
                ),
            ],
        ),
    ]

    for asiento in asientos_data:
        service.registrar_asiento(asiento)


# ---------------------------------------------------------------------------
# Tests: Balance General
# ---------------------------------------------------------------------------

class TestBalanceGeneral:
    """Tests para generar_balance_general."""

    def test_balance_general_vacio(self, service, empresa_a, periodo):
        """Sin movimientos: todo en cero."""
        balance = service.generar_balance_general(empresa_a, periodo)
        assert balance.activos == 0.0
        assert balance.pasivos == 0.0
        assert balance.capital == 0.0

    def test_balance_general_con_datos(
        self, service, empresa_a, periodo, catalogo_basico
    ):
        """Balance con datos reales: activos > pasivos."""
        _cargar_datos_completos(service, empresa_a, periodo, catalogo_basico)

        balance = service.generar_balance_general(empresa_a, periodo)

        # Activos: 200000(bancos) - 45000(nómina) - 15000(arrend) + 100000(inmueble)
        # = 140000
        assert balance.activos > 0
        # Pasivos: 80000(proveedores) + 100000(crédito) = 180000
        assert balance.pasivos > 0
        # Capital = activos - pasivos
        assert balance.capital == pytest.approx(
            balance.activos - balance.pasivos, rel=1e-2
        )

    def test_balance_activos_corrientes_vs_no_corrientes(
        self, service, empresa_a, periodo, catalogo_basico
    ):
        """Verifica separación de activos corrientes y no corrientes."""
        _cargar_datos_completos(service, empresa_a, periodo, catalogo_basico)

        balance = service.generar_balance_general(empresa_a, periodo)

        assert balance.activos_corriente > 0  # caja, bancos
        assert balance.activos_no_corriente > 0  # inmuebles
        assert balance.activos == pytest.approx(
            balance.activos_corriente + balance.activos_no_corriente,
            rel=1e-2,
        )


# ---------------------------------------------------------------------------
# Tests: Estado de Resultados
# ---------------------------------------------------------------------------

class TestEstadoResultados:
    """Tests para generar_estado_resultados."""

    def test_estado_resultados_vacio(self, service, empresa_a, periodo):
        """Sin movimientos: todo en cero."""
        er = service.generar_estado_resultados(empresa_a, periodo)
        assert er.ingresos == 0.0
        assert er.costos == 0.0
        assert er.gastos == 0.0
        assert er.utilidad_neta == 0.0

    def test_estado_resultados_con_ganancia(
        self, service, empresa_a, periodo, catalogo_basico
    ):
        """Empresa con ganancia: ingresos > costos + gastos."""
        _cargar_datos_completos(service, empresa_a, periodo, catalogo_basico)

        er = service.generar_estado_resultados(empresa_a, periodo)

        assert er.ingresos == 200000.0
        assert er.costos == 80000.0
        assert er.gastos == 60000.0  # 45000 nómina + 15000 arrend
        assert er.utilidad_bruta == 120000.0  # 200000 - 80000
        assert er.utilidad_neta > 0  # hay ganancia

    def test_estado_resultados_perdida(self, service, empresa_a, periodo):
        """Empresa con pérdida: costos + gastos > ingresos."""
        service.cargar_catalogo(empresa_a, [
            CuentaCatalogo(
                codigo="4100", nombre="Ventas", tipo=TipoCuenta.INGRESO,
                grupo=GrupoCuenta.INGRESOS_OPERACIONALES, empresa_id=empresa_a,
            ),
            CuentaCatalogo(
                codigo="5100", nombre="CMV", tipo=TipoCuenta.COSTO,
                grupo=GrupoCuenta.COSTOS, empresa_id=empresa_a,
            ),
            CuentaCatalogo(
                codigo="6100", nombre="Nómina", tipo=TipoCuenta.GASTO,
                grupo=GrupoCuenta.GASTOS_OPERACIONALES, empresa_id=empresa_a,
            ),
            CuentaCatalogo(
                codigo="1200", nombre="Bancos", tipo=TipoCuenta.ACTIVO,
                grupo=GrupoCuenta.ACTIVO_CORRIENTE, empresa_id=empresa_a,
            ),
            CuentaCatalogo(
                codigo="2100", nombre="Proveedores", tipo=TipoCuenta.PASIVO,
                grupo=GrupoCuenta.PASIVO_CORRIENTE, empresa_id=empresa_a,
            ),
        ])
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="P-1", fecha=date(2026, 1, 5),
            periodo=periodo, tipo=TipoAsiento.INGRESO, descripcion="Venta",
            lineas=[
                LineaAsiento(cuenta_contable="1200", debito=10000, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=10000),
            ],
        ))
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="P-2", fecha=date(2026, 1, 10),
            periodo=periodo, tipo=TipoAsiento.EGRESO, descripcion="CMV",
            lineas=[
                LineaAsiento(cuenta_contable="5100", debito=8000, credito=0),
                LineaAsiento(cuenta_contable="2100", debito=0, credito=8000),
            ],
        ))
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="P-3", fecha=date(2026, 1, 15),
            periodo=periodo, tipo=TipoAsiento.EGRESO, descripcion="Nómina",
            lineas=[
                LineaAsiento(cuenta_contable="6100", debito=5000, credito=0),
                LineaAsiento(cuenta_contable="1200", debito=0, credito=5000),
            ],
        ))

        er = service.generar_estado_resultados(empresa_a, periodo)

        assert er.ingresos == 10000.0
        assert er.costos == 8000.0
        assert er.gastos == 5000.0
        assert er.utilidad_neta < 0  # hay pérdida


# ---------------------------------------------------------------------------
# Tests: Registro de Asientos
# ---------------------------------------------------------------------------

class TestRegistrarAsiento:
    """Tests para registrar_asiento."""

    def test_registrar_asiento_balanceado(
        self, service, asiento_balanceado
    ):
        """Asiento que cuadra se registra correctamente."""
        result = service.registrar_asiento(asiento_balanceado)

        assert result.id == asiento_balanceado.id
        assert len(service._asientos) == 1
        # Se registran 2 entries individuales
        assert len(service._entries) == 2

    def test_registrar_asiento_no_balanceado(
        self, service, asiento_no_balanceado
    ):
        """Asiento que no cuadra lanza error."""
        with pytest.raises(ContabilidadError) as exc_info:
            service.registrar_asiento(asiento_no_balanceado)

        assert exc_info.value.code == "asiento_no_cuadra"
        assert len(service._asientos) == 0

    def test_registrar_asiento_una_sola_linea(self, service, empresa_a, periodo):
        """Asiento con una sola línea lanza error."""
        asiento = AsientoContable(
            empresa_id=empresa_a,
            partida_id="PART-999",
            fecha=date(2026, 1, 1),
            periodo=periodo,
            tipo=TipoAsiento.DIARIO,
            descripcion="Incomplete",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=1000, credito=0),
            ],
        )
        with pytest.raises(ContabilidadError) as exc_info:
            service.registrar_asiento(asiento)

        assert exc_info.value.code == "asiento_incompleto"

    def test_registrar_asiento_cero_cero(self, service, empresa_a, periodo):
        """Asiento con débito y crédito en cero lanza error."""
        asiento = AsientoContable(
            empresa_id=empresa_a,
            partida_id="PART-998",
            fecha=date(2026, 1, 1),
            periodo=periodo,
            tipo=TipoAsiento.DIARIO,
            descripcion="Zero",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=0, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=0),
            ],
        )
        with pytest.raises(ContabilidadError) as exc_info:
            service.registrar_asiento(asiento)

        assert exc_info.value.code == "asiento_vacio"


# ---------------------------------------------------------------------------
# Tests: Catálogo de Cuentas
# ---------------------------------------------------------------------------

class TestCatalogoCuentas:
    """Tests para consultar_catalogo_cuentas y cargar_catalogo."""

    def test_consultar_catalogo_vacio(self, service, empresa_a):
        """Sin catálogo cargado: retorna lista vacía."""
        catalogo = service.consultar_catalogo_cuentas(empresa_a)
        assert catalogo == []

    def test_cargar_y_consultar_catalogo(
        self, service, empresa_a, catalogo_basico
    ):
        """Carga y consulta catálogo."""
        result = service.cargar_catalogo(empresa_a, catalogo_basico)

        assert len(result) == len(catalogo_basico)

        consultado = service.consultar_catalogo_cuentas(empresa_a)
        assert len(consultado) == len(catalogo_basico)
        assert consultado[0].codigo == "1100"
        assert consultado[0].nombre == "Caja"


# ---------------------------------------------------------------------------
# Tests: Conciliación
# ---------------------------------------------------------------------------

class TestConciliacionAsientos:
    """Tests para conciliar_asientos."""

    def test_conciliacion_sin_asientos(self, service, empresa_a, periodo):
        """Sin asientos: conciliado = True (no hay nada que reconciliar)."""
        result = service.conciliar_asientos(empresa_a, periodo)

        assert result["conciliado"] is True
        assert result["total_asientos"] == 0
        assert result["discrepancias"] == []

    def test_conciliacion_con_asientos_balanceados(
        self, service, empresa_a, periodo, catalogo_basico
    ):
        """Asientos que cuadran: conciliado = True."""
        _cargar_datos_completos(service, empresa_a, periodo, catalogo_basico)

        result = service.conciliar_asientos(empresa_a, periodo)

        assert result["conciliado"] is True
        assert result["total_asientos"] == 5
        assert result["discrepancias"] == []

    def test_multi_empresa_no_mezcla(self, service, empresa_a, empresa_b, periodo):
        """Dos empresas: conciliación no mezcla datos."""
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="P-A", fecha=date(2026, 1, 1),
            periodo=periodo, tipo=TipoAsiento.DIARIO, descripcion="A",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=1000, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=1000),
            ],
        ))
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_b, partida_id="P-B", fecha=date(2026, 1, 1),
            periodo=periodo, tipo=TipoAsiento.DIARIO, descripcion="B",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=2000, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=2000),
            ],
        ))

        result_a = service.conciliar_asientos(empresa_a, periodo)
        result_b = service.conciliar_asientos(empresa_b, periodo)

        assert result_a["total_asientos"] == 1
        assert result_b["total_asientos"] == 1
        assert result_a["total_debito"] == 1000.0
        assert result_b["total_debito"] == 2000.0


# ---------------------------------------------------------------------------
# Tests: Cálculo de Impuestos
# ---------------------------------------------------------------------------

class TestCalcularImpuestos:
    """Tests para calcular_impuestos."""

    def test_impuestos_empresa_con_ganancia(
        self, service, empresa_a, periodo, catalogo_basico
    ):
        """Empresa con ganancia: ISR, IVA y PTU positivos."""
        _cargar_datos_completos(service, empresa_a, periodo, catalogo_basico)

        impuestos = service.calcular_impuestos(empresa_a, periodo)

        assert impuestos["isr"] > 0
        assert impuestos["ptu"] > 0
        assert impuestos["iva_tasa"] == 0.16
        assert impuestos["isr_tasa"] == 0.30
        assert impuestos["ptu_tasa"] == 0.10

    def test_impuestos_empresa_en_perdida(self, service, empresa_a, periodo):
        """Empresa con pérdida: ISR y PTU en cero."""
        service.cargar_catalogo(empresa_a, [
            CuentaCatalogo(
                codigo="4100", nombre="Ventas", tipo=TipoCuenta.INGRESO,
                grupo=GrupoCuenta.INGRESOS_OPERACIONALES, empresa_id=empresa_a,
            ),
            CuentaCatalogo(
                codigo="6100", nombre="Gastos", tipo=TipoCuenta.GASTO,
                grupo=GrupoCuenta.GASTOS_OPERACIONALES, empresa_id=empresa_a,
            ),
        ])
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="P-1", fecha=date(2026, 1, 5),
            periodo=periodo, tipo=TipoAsiento.INGRESO, descripcion="Venta",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=10000, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=10000),
            ],
        ))
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="P-2", fecha=date(2026, 1, 10),
            periodo=periodo, tipo=TipoAsiento.EGRESO, descripcion="Gasto",
            lineas=[
                LineaAsiento(cuenta_contable="6100", debito=20000, credito=0),
                LineaAsiento(cuenta_contable="1100", debito=0, credito=20000),
            ],
        ))

        impuestos = service.calcular_impuestos(empresa_a, periodo)

        assert impuestos["isr"] == 0.0  # sin utilidad, sin ISR
        assert impuestos["ptu"] == 0.0  # sin utilidad, sin PTU

    def test_impuestos_multi_empresa(self, service, empresa_a, empresa_b, periodo):
        """Impuestos calculados por separado por empresa."""
        service.cargar_catalogo(empresa_a, [
            CuentaCatalogo(
                codigo="4100", nombre="Ventas", tipo=TipoCuenta.INGRESO,
                grupo=GrupoCuenta.INGRESOS_OPERACIONALES, empresa_id=empresa_a,
            ),
            CuentaCatalogo(
                codigo="6100", nombre="Gastos", tipo=TipoCuenta.GASTO,
                grupo=GrupoCuenta.GASTOS_OPERACIONALES, empresa_id=empresa_a,
            ),
        ])
        service.cargar_catalogo(empresa_b, [
            CuentaCatalogo(
                codigo="4100", nombre="Ventas", tipo=TipoCuenta.INGRESO,
                grupo=GrupoCuenta.INGRESOS_OPERACIONALES, empresa_id=empresa_b,
            ),
            CuentaCatalogo(
                codigo="6100", nombre="Gastos", tipo=TipoCuenta.GASTO,
                grupo=GrupoCuenta.GASTOS_OPERACIONALES, empresa_id=empresa_b,
            ),
        ])
        # Empresa A: venta 100k, gastos 30k
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="PA-1", fecha=date(2026, 1, 5),
            periodo=periodo, tipo=TipoAsiento.INGRESO, descripcion="Venta A",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=100000, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=100000),
            ],
        ))
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_a, partida_id="PA-2", fecha=date(2026, 1, 10),
            periodo=periodo, tipo=TipoAsiento.EGRESO, descripcion="Gasto A",
            lineas=[
                LineaAsiento(cuenta_contable="6100", debito=30000, credito=0),
                LineaAsiento(cuenta_contable="1100", debito=0, credito=30000),
            ],
        ))
        # Empresa B: venta 50k, gastos 10k
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_b, partida_id="PB-1", fecha=date(2026, 1, 5),
            periodo=periodo, tipo=TipoAsiento.INGRESO, descripcion="Venta B",
            lineas=[
                LineaAsiento(cuenta_contable="1100", debito=50000, credito=0),
                LineaAsiento(cuenta_contable="4100", debito=0, credito=50000),
            ],
        ))
        service.registrar_asiento(AsientoContable(
            empresa_id=empresa_b, partida_id="PB-2", fecha=date(2026, 1, 10),
            periodo=periodo, tipo=TipoAsiento.EGRESO, descripcion="Gasto B",
            lineas=[
                LineaAsiento(cuenta_contable="6100", debito=10000, credito=0),
                LineaAsiento(cuenta_contable="1100", debito=0, credito=10000),
            ],
        ))

        imp_a = service.calcular_impuestos(empresa_a, periodo)
        imp_b = service.calcular_impuestos(empresa_b, periodo)

        assert imp_a["isr"] > imp_b["isr"]  # A tiene más utilidad
        assert imp_a["empresa_id"] == empresa_a
        assert imp_b["empresa_id"] == empresa_b


# ---------------------------------------------------------------------------
# Tests: Modelos
# ---------------------------------------------------------------------------

class TestModelos:
    """Tests de validación de modelos Pydantic."""

    def test_cuenta_contable_codigo_invalido(self):
        """Código de cuenta con letras lanza error."""
        with pytest.raises(Exception):
            CuentaCatalogo(
                codigo="ABCD",
                nombre="Test",
                tipo=TipoCuenta.ACTIVO,
                grupo=GrupoCuenta.ACTIVO_CORRIENTE,
                empresa_id="TEST",
            )

    def test_cuenta_contable_codigo_corto(self):
        """Código de cuenta con menos de 4 dígitos lanza error."""
        with pytest.raises(Exception):
            CuentaCatalogo(
                codigo="123",
                nombre="Test",
                tipo=TipoCuenta.ACTIVO,
                grupo=GrupoCuenta.ACTIVO_CORRIENTE,
                empresa_id="TEST",
            )

    def test_periodo_formato_invalido(self):
        """Periodo con formato incorrecto lanza error."""
        with pytest.raises(Exception):
            BalanceGeneral(
                empresa_id="TEST",
                periodo="2026/01",  # formato incorrecto
            )
