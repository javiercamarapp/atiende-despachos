# -*- coding: utf-8 -*-
"""
test_reconciliacion_ingresos_egresos.py — Tests for Income/Expense Reconciliation module.

Minimum 25 tests covering:
  - Deposit classification (all 5 types)
  - Conciliation matching
  - Discrepancy detection
  - IVA balance calculation
  - Working paper generation
  - Edge cases (empty data, mismatches)
  - Validators
"""
from __future__ import annotations

import pytest
from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    AuxiliarContable,
    BalanceIVA,
    ClasificacionDeposito,
    ClasificacionDepositoResult,
    ConciliacionIngresosEgresos,
    DepositoBancario,
    DiscrepanciaFiscal,
    MovimientoAuxiliar,
    PapelTrabajoConciliacion,
    Severidad,
    TipoDiscrepancia,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.validators import (
    validate_auxiliar_contable,
    validate_balance_iva,
    validate_clasificacion,
    validate_deposito,
    validate_periodo,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.classification_rules import (
    ClassificationEngine,
    Rule,
    DEFAULT_RULES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Test classification (5 types)
# ---------------------------------------------------------------------------

class TestClasificacionIngreso:
    """Test INGRESO classification."""

    def test_clasificacion_ingreso_cfdi(self):
        """Depósito con referencia CFDI se clasifica como INGRESO."""
        dep = _make_deposito(referencia="CFDI-ABC-001")
        aux = _make_auxiliar()
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [aux])
        assert classification == ClasificacionDeposito.INGRESO
        assert confidence >= 0.8
        assert "CFDI" in reason or "ingreso" in reason.lower()

    def test_clasificacion_ingreso_factura(self):
        """Depósito con referencia FACTURA se clasifica como INGRESO."""
        dep = _make_deposito(referencia="FACTURA-12345")
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.INGRESO

    def test_clasificacion_ingreso_uuid(self):
        """Depósito con referencia UUID se clasifica como INGRESO."""
        dep = _make_deposito(referencia="UUID-A1B2C3D4-E5F6")
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.INGRESO


class TestClasificacionFinanciamiento:
    """Test FINANCIAMIENTO classification."""

    def test_clasificacion_prestamo(self):
        """Depósito con 'préstamo' en descripción se clasifica como FINANCIAMIENTO."""
        dep = _make_deposito(
            descripcion="Depósito de préstamo bancario",
            referencia="LOAN-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.FINANCIAMIENTO
        assert confidence >= 0.7

    def test_clasificacion_credito(self):
        """Depósito con 'crédito' en referencia se clasifica como FINANCIAMIENTO."""
        dep = _make_deposito(
            descripcion="Depósito línea de crédito",
            referencia="CREDITO-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.FINANCIAMIENTO

    def test_clasificacion_financiamiento(self):
        """Depósito con 'financiamiento' se clasifica como FINANCIAMIENTO."""
        dep = _make_deposito(
            descripcion="Financiamiento proveedor",
            referencia="FIN-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.FINANCIAMIENTO


class TestClasificacionAportacionSocio:
    """Test APORTACION_SOCIO classification."""

    def test_clasificacion_aportacion_socio(self):
        """Depósito con 'aportación de socio' se clasifica como APORTACION_SOCIO."""
        dep = _make_deposito(
            descripcion="Aportación de socio Juan Pérez",
            referencia="APORT-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.APORTACION_SOCIO
        assert confidence >= 0.8

    def test_clasificacion_capital_social(self):
        """Depósito con 'capital social' se clasifica como APORTACION_SOCIO."""
        dep = _make_deposito(
            descripcion="Depósito capital social",
            referencia="CS-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.APORTACION_SOCIO


class TestClasificacionGarantia:
    """Test GARANTIA classification."""

    def test_clasificacion_garantia(self):
        """Depósito con 'garantía' se clasifica como GARANTIA."""
        dep = _make_deposito(
            descripcion="Depósito en garantía arrendamiento",
            referencia="GAR-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.GARANTIA
        assert confidence >= 0.7

    def test_clasificacion_fianza(self):
        """Depósito con 'fianza' se clasifica como GARANTIA."""
        dep = _make_deposito(
            descripcion="Fianza arrendamiento",
            referencia="FZ-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.GARANTIA


class TestClasificacionOtroNoGravable:
    """Test OTRO_NO_GRAVABLE classification."""

    def test_clasificacion_default(self):
        """Depósito sin palabras clave se clasifica como OTRO_NO_GRAVABLE."""
        dep = _make_deposito(
            descripcion="Transferencia genérica",
            referencia="TXF-001",
        )
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.OTRO_NO_GRAVABLE
        assert confidence <= 0.6

    def test_clasificacion_referencia_vacia(self):
        """Depósito sin referencia se clasifica como OTRO_NO_GRAVABLE."""
        dep = _make_deposito(referencia="", descripcion="Sin referencia")
        engine = ClassificationEngine()
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert classification == ClasificacionDeposito.OTRO_NO_GRAVABLE


# ---------------------------------------------------------------------------
# Test conciliation matching
# ---------------------------------------------------------------------------

class TestConciliacionMatching:
    """Test conciliation matching logic."""

    def test_conciliacion_basica(self):
        """Depósito concilia con auxiliar por referencia."""
        dep = _make_deposito(monto=100000.0, referencia="CFDI-001")
        aux = _make_auxiliar(
            movimientos=[
                MovimientoAuxiliar(
                    fecha="2026-06-15",
                    concepto="Pago",
                    debe=0.0,
                    haber=100000.0,
                    referencia="CFDI-001",
                    tipo="ingreso",
                ),
            ],
        )
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        assert len(conciliacion.clasificaciones) == 1
        assert conciliacion.clasificaciones[0].clasificacion == ClasificacionDeposito.INGRESO

    def test_conciliacion_sin_coincidencia(self):
        """Depósito sin coincidencia genera discrepancia."""
        dep = _make_deposito(monto=50000.0, referencia="CFDI-999")
        aux = _make_auxiliar(
            movimientos=[
                MovimientoAuxiliar(
                    fecha="2026-06-15",
                    concepto="Pago",
                    debe=0.0,
                    haber=50000.0,
                    referencia="CFDI-001",
                    tipo="ingreso",
                ),
            ],
        )
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        assert len(conciliacion.discrepancias) > 0
        assert conciliacion.discrepancias[0].tipo == TipoDiscrepancia.FALTA_DOCUMENTACION

    def test_conciliacion_vacios(self):
        """Conciliación con datos vacíos no genera errores."""
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([], [])
        assert len(conciliacion.depositos) == 0
        assert len(conciliacion.auxiliares) == 0
        assert conciliacion.diferencia == 0.0


# ---------------------------------------------------------------------------
# Test discrepancy detection
# ---------------------------------------------------------------------------

class TestDeteccionDiscrepancias:
    """Test discrepancy detection."""

    def test_discrepancia_monto(self):
        """Monto del depósito difiere del auxiliar."""
        dep = _make_deposito(monto=100000.0, referencia="CFDI-001")
        aux = _make_auxiliar(
            movimientos=[
                MovimientoAuxiliar(
                    fecha="2026-06-15",
                    concepto="Pago",
                    debe=0.0,
                    haber=95000.0,
                    referencia="CFDI-001",
                    tipo="ingreso",
                ),
            ],
        )
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        monto_disc = [d for d in conciliacion.discrepancias if d.tipo == TipoDiscrepancia.MONTO]
        assert len(monto_disc) > 0
        assert monto_disc[0].monto_afectado > 0

    def test_discrepancia_fecha(self):
        """Fecha del depósito difiere del auxiliar."""
        dep = _make_deposito(fecha="2026-06-15", referencia="CFDI-001")
        aux = _make_auxiliar(
            movimientos=[
                MovimientoAuxiliar(
                    fecha="2026-06-20",
                    concepto="Pago",
                    debe=0.0,
                    haber=100000.0,
                    referencia="CFDI-001",
                    tipo="ingreso",
                ),
            ],
        )
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        fecha_disc = [d for d in conciliacion.discrepancias if d.tipo == TipoDiscrepancia.FECHA]
        assert len(fecha_disc) > 0

    def test_discrepancia_falta_documentacion(self):
        """Depósito sin referencia matching genera discrepancia de documentación."""
        dep = _make_deposito(referencia="CFDI-999")
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [])
        doc_disc = [d for d in conciliacion.discrepancias if d.tipo == TipoDiscrepancia.FALTA_DOCUMENTACION]
        assert len(doc_disc) > 0


# ---------------------------------------------------------------------------
# Test IVA balance calculation
# ---------------------------------------------------------------------------

class TestBalanceIVA:
    """Test IVA balance calculation."""

    def test_balance_iva_basico(self):
        """Cálculo básico de balance de IVA."""
        service = ReconciliacionIngresosEgresosService()
        declaraciones = [{
            "iva_cobrado": 16000.0,
            "iva_pagado": 12000.0,
            "declarado": 4000.0,
        }]
        balance = service.calcular_balance_iva(declaraciones, [], [])
        assert balance.iva_cobrado == 16000.0
        assert balance.iva_pagado == 12000.0
        assert balance.saldo_contra == 4000.0
        assert balance.saldo_favor == 0.0

    def test_balance_iva_favor(self):
        """IVA pagado mayor que cobrado → saldo a favor."""
        service = ReconciliacionIngresosEgresosService()
        declaraciones = [{
            "iva_cobrado": 8000.0,
            "iva_pagado": 10000.0,
            "declarado": 2000.0,
        }]
        balance = service.calcular_balance_iva(declaraciones, [], [])
        assert balance.saldo_favor == 2000.0
        assert balance.saldo_contra == 0.0

    def test_balance_iva_discrepancia(self):
        """Discrepancia entre cálculo y declaración."""
        service = ReconciliacionIngresosEgresosService()
        declaraciones = [{
            "iva_cobrado": 16000.0,
            "iva_pagado": 12000.0,
            "declarado": 3000.0,
        }]
        balance = service.calcular_balance_iva(declaraciones, [], [])
        assert balance.discrepancia == 1000.0

    def test_balance_iva_cero(self):
        """Balance de IVA en ceros."""
        service = ReconciliacionIngresosEgresosService()
        balance = service.calcular_balance_iva([], [], [])
        assert balance.iva_cobrado == 0.0
        assert balance.iva_pagado == 0.0
        assert balance.discrepancia == 0.0


# ---------------------------------------------------------------------------
# Test working paper generation
# ---------------------------------------------------------------------------

class TestPapelTrabajo:
    """Test working paper generation."""

    def test_papel_trabajo_basico(self):
        """Generación básica de papel de trabajo."""
        dep = _make_deposito(referencia="CFDI-001")
        aux = _make_auxiliar()
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        conciliacion.periodo = "2026-06"
        papel = service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)
        assert papel.periodo == "2026-06"
        assert len(papel.resumen) > 0
        assert len(papel.conclusiones) > 0
        assert papel.created_at is not None

    def test_papel_trabajo_con_balance_iva(self):
        """Papel de trabajo con balance de IVA."""
        dep = _make_deposito(referencia="CFDI-001")
        aux = _make_auxiliar()
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        conciliacion.periodo = "2026-06"
        balance = BalanceIVA(
            iva_cobrado=16000.0,
            iva_pagado=12000.0,
            saldo_contra=4000.0,
            declarado=4000.0,
        )
        papel = service.generar_papel_trabajo(
            conciliacion, conciliacion.clasificaciones, balance
        )
        assert len(papel.balanceiva) == 1
        assert papel.balanceiva[0].iva_cobrado == 16000.0

    def test_papel_trabajo_requiere_revision(self):
        """Papel de trabajo con discrepancias requiere revisión humana."""
        dep = _make_deposito(referencia="CFDI-999")
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [])
        conciliacion.periodo = "2026-06"
        papel = service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)
        assert papel.requires_human_review is True

    def test_papel_trabajo_get(self):
        """Recuperar papel de trabajo por período."""
        service = ReconciliacionIngresosEgresosService()
        dep = _make_deposito(referencia="CFDI-001")
        aux = _make_auxiliar()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [aux])
        conciliacion.periodo = "2026-06"
        service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)
        retrieved = service.get_papel_trabajo("2026-06")
        assert retrieved is not None
        assert retrieved.periodo == "2026-06"

    def test_papel_trabajo_no_encontrado(self):
        """Papel de trabajo inexistente retorna None."""
        service = ReconciliacionIngresosEgresosService()
        retrieved = service.get_papel_trabajo("2099-01")
        assert retrieved is None


# ---------------------------------------------------------------------------
# Test validators
# ---------------------------------------------------------------------------

class TestValidators:
    """Test validation functions."""

    def test_validate_periodo_valido(self):
        is_valid, err = validate_periodo("2026-06")
        assert is_valid is True
        assert err == ""

    def test_validate_periodo_invalido_formato(self):
        is_valid, err = validate_periodo("2026/06")
        assert is_valid is False
        assert "YYYY-MM" in err

    def test_validate_periodo_invalido_mes(self):
        is_valid, err = validate_periodo("2026-13")
        assert is_valid is False
        assert "Mes inválido" in err

    def test_validate_deposito_valido(self):
        dep = _make_deposito()
        is_valid, err = validate_deposito(dep)
        assert is_valid is True

    def test_validate_deposito_monto_cero(self):
        dep = _make_deposito(monto=0.0)
        is_valid, err = validate_deposito(dep)
        assert is_valid is False
        assert "mayor a cero" in err

    def test_validate_deposito_fecha_invalida(self):
        dep = _make_deposito(fecha="invalid-date")
        is_valid, err = validate_deposito(dep)
        assert is_valid is False

    def test_validate_auxiliar_valido(self):
        aux = _make_auxiliar()
        is_valid, err = validate_auxiliar_contable(aux)
        assert is_valid is True

    def test_validate_auxiliar_cuenta_invalida(self):
        aux = _make_auxiliar(cuenta_mayor="ABC")
        is_valid, err = validate_auxiliar_contable(aux)
        assert is_valid is False
        assert "4 dígitos" in err

    def test_validate_clasificacion_valida(self):
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-001",
            clasificacion=ClasificacionDeposito.INGRESO,
            confianza=0.95,
            razon="CFDI encontrado",
        )
        is_valid, err = validate_clasificacion(clas)
        assert is_valid is True

    def test_validate_clasificacion_confianza_invalida(self):
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-001",
            clasificacion=ClasificacionDeposito.INGRESO,
            confianza=1.5,
        )
        is_valid, err = validate_clasificacion(clas)
        assert is_valid is False
        assert "entre 0 y 1" in err

    def test_validate_balance_iva_valido(self):
        balance = BalanceIVA(
            iva_cobrado=16000.0,
            iva_pagado=12000.0,
            saldo_contra=4000.0,
            declarado=4000.0,
        )
        is_valid, err = validate_balance_iva(balance)
        assert is_valid is True

    def test_validate_balance_iva_negativo(self):
        balance = BalanceIVA(iva_cobrado=-1000.0)
        is_valid, err = validate_balance_iva(balance)
        assert is_valid is False
        assert "negativo" in err


# ---------------------------------------------------------------------------
# Test edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_multiple_deposits_multiple_auxiliares(self):
        """Múltiples depósitos y auxiliares."""
        deps = [
            _make_deposito(id="DEP-001", referencia="CFDI-001", monto=50000.0),
            _make_deposito(id="DEP-002", referencia="CFDI-002", monto=30000.0),
        ]
        auxs = [
            _make_auxiliar(
                cuenta_id="AUX-001",
                movimientos=[
                    MovimientoAuxiliar(
                        fecha="2026-06-15", concepto="Pago 1",
                        debe=0.0, haber=50000.0, referencia="CFDI-001", tipo="ingreso",
                    ),
                ],
            ),
            _make_auxiliar(
                cuenta_id="AUX-002",
                movimientos=[
                    MovimientoAuxiliar(
                        fecha="2026-06-20", concepto="Pago 2",
                        debe=0.0, haber=30000.0, referencia="CFDI-002", tipo="ingreso",
                    ),
                ],
            ),
        ]
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares(deps, auxs)
        assert len(conciliacion.clasificaciones) == 2
        assert conciliacion.saldo_bancario == 80000.0

    def test_clasificar_todos(self):
        """Clasificar múltiples depósitos."""
        deps = [
            _make_deposito(id="DEP-001", referencia="CFDI-001"),
            _make_deposito(id="DEP-002", descripcion="Préstamo banco", referencia="LOAN-001"),
            _make_deposito(id="DEP-003", descripcion="Aportación de socio", referencia="APORT-001"),
        ]
        service = ReconciliacionIngresosEgresosService()
        clasificaciones = service.clasificar_todos(deps, [])
        assert len(clasificaciones) == 3
        types = {c.clasificacion for c in clasificaciones}
        assert ClasificacionDeposito.INGRESO in types
        assert ClasificacionDeposito.FINANCIAMIENTO in types
        assert ClasificacionDeposito.APORTACION_SOCIO in types

    def test_custom_rule(self):
        """Agregar regla personalizada."""
        def my_condition(dep, auxs):
            return "MYPATTERN" in dep.referencia.upper()

        custom_rule = Rule(
            name="Custom-Pattern",
            description="Custom pattern match",
            classification=ClasificacionDeposito.OTRO_NO_GRAVABLE,
            condition=my_condition,
            confidence=0.6,
        )
        engine = ClassificationEngine()
        engine.add_rule(custom_rule)
        dep = _make_deposito(referencia="MYPATTERN-001")
        classification, confidence, reason, articulo = engine.classify(dep, [])
        assert "Custom-Pattern" in reason

    def test_service_clasificar_deposito(self):
        """Test clasificar_deposito method."""
        dep = _make_deposito(referencia="CFDI-001")
        aux = _make_auxiliar()
        service = ReconciliacionIngresosEgresosService()
        result = service.clasificar_deposito(dep, [aux])
        assert result.deposito_id == "DEP-001"
        assert result.clasificacion == ClasificacionDeposito.INGRESO

    def test_discrepancias_from_conciliacion(self):
        """Obtener discrepancias de conciliación."""
        dep = _make_deposito(referencia="CFDI-999")
        service = ReconciliacionIngresosEgresosService()
        conciliacion = service.conciliar_depositos_auxiliares([dep], [])
        discrepancies = service.detectar_discrepancias(conciliacion)
        assert len(discrepancies) > 0

    def test_model_dump_roundtrip(self):
        """Models serializan correctamente con model_dump."""
        dep = _make_deposito()
        data = dep.model_dump()
        assert data["id"] == "DEP-001"
        assert data["monto"] == 100000.0

        aux = _make_auxiliar()
        data = aux.model_dump()
        assert data["cuenta_id"] == "AUX-001"
        assert len(data["movimientos"]) == 1
