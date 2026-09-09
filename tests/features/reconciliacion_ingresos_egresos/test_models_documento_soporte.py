# -*- coding: utf-8 -*-
"""
test_models_documento_soporte.py — REQ-IVA-002

Criterio de aceptación: `DepositoBancario` y `ClasificacionDepositoResult`
deben ganar `documento_soporte_id` (FK a repositorio de documentos),
`fecha_documento` y `estado_recaracterizacion`
(`vigente`/`requiere_formalizacion`/`recaracterizado`); ninguna clasificación
FINANCIAMIENTO, APORTACION_SOCIO o GARANTIA puede persistirse sin
`documento_soporte_id` no nulo.

ADR-4 (docs/BLUEPRINT-AGENTES-FISCALES.md): el motor de reglas produce
sugerencias automáticas de primera pasada que NUNCA deben bloquearse por
falta de documento (nadie ha tenido la oportunidad de adjuntarlo todavía);
lo que nunca debe pasar es que una de esas clasificaciones sensibles se
declare lista para persistirse (vigente/recaracterizada) sin evidencia
documental real. Estas pruebas cubren ambos lados de esa regla, sin mocks:
todo pasa por el modelo Pydantic real.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE,
    ClasificacionDeposito,
    ClasificacionDepositoResult,
    DepositoBancario,
    EstadoRecaracterizacion,
    assert_puede_persistirse,
)


def _make_deposito(**overrides) -> DepositoBancario:
    defaults = dict(
        id="DEP-001",
        fecha="2026-06-15",
        monto=200000.0,
        descripcion="Préstamo de socio según contrato de mutuo",
        referencia="CONTRATO-MUTUO-01",
        banco="BBVA",
        cuenta="0123456789",
        es_credito=True,
    )
    defaults.update(overrides)
    return DepositoBancario(**defaults)


def _make_clasificacion(**overrides) -> ClasificacionDepositoResult:
    defaults = dict(
        deposito_id="DEP-001",
        clasificacion=ClasificacionDeposito.FINANCIAMIENTO,
        confianza=0.85,
        razon="Regla 'Financiamiento-Bancario'",
    )
    defaults.update(overrides)
    return ClasificacionDepositoResult(**defaults)


# ---------------------------------------------------------------------------
# 1. Los modelos ganan los campos nuevos, con los defaults correctos
# ---------------------------------------------------------------------------

class TestCamposNuevosDepositoBancario:
    def test_deposito_bancario_tiene_documento_soporte_id_por_defecto_none(self):
        dep = _make_deposito()
        assert dep.documento_soporte_id is None

    def test_deposito_bancario_tiene_fecha_documento_por_defecto_none(self):
        dep = _make_deposito()
        assert dep.fecha_documento is None

    def test_deposito_bancario_estado_recaracterizacion_por_defecto_vigente(self):
        dep = _make_deposito()
        assert dep.estado_recaracterizacion == EstadoRecaracterizacion.VIGENTE

    def test_deposito_bancario_acepta_los_tres_campos_explicitos(self):
        dep = _make_deposito(
            documento_soporte_id="DOC-001",
            fecha_documento="2026-05-01",
            estado_recaracterizacion=EstadoRecaracterizacion.RECARACTERIZADO,
        )
        assert dep.documento_soporte_id == "DOC-001"
        assert dep.fecha_documento == "2026-05-01"
        assert dep.estado_recaracterizacion == EstadoRecaracterizacion.RECARACTERIZADO


class TestCamposNuevosClasificacionDepositoResult:
    def test_clasificacion_tiene_documento_soporte_id_por_defecto_none(self):
        clas = _make_clasificacion(documento_soporte_id="DOC-XYZ")
        assert clas.documento_soporte_id == "DOC-XYZ"

    def test_clasificacion_ingreso_no_requiere_documento_por_defecto(self):
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-999",
            clasificacion=ClasificacionDeposito.INGRESO,
            confianza=0.95,
            razon="CFDI encontrado",
        )
        assert clas.documento_soporte_id is None
        assert clas.fecha_documento is None
        assert clas.estado_recaracterizacion == EstadoRecaracterizacion.VIGENTE

    def test_estado_recaracterizacion_enum_tiene_los_tres_valores_del_criterio(self):
        assert EstadoRecaracterizacion.VIGENTE.value == "vigente"
        assert EstadoRecaracterizacion.REQUIERE_FORMALIZACION.value == "requiere_formalizacion"
        assert EstadoRecaracterizacion.RECARACTERIZADO.value == "recaracterizado"


# ---------------------------------------------------------------------------
# 2. La sugerencia automática de primera pasada (sin documento) sigue
#    siendo construible — ADR-4 exige que nunca se bloquee la sugerencia,
#    solo la persistencia como determinación firme.
# ---------------------------------------------------------------------------

class TestSugerenciaAutomaticaSinDocumentoNoSeBloquea:
    @pytest.mark.parametrize(
        "clasificacion",
        [
            ClasificacionDeposito.FINANCIAMIENTO,
            ClasificacionDeposito.APORTACION_SOCIO,
            ClasificacionDeposito.GARANTIA,
        ],
    )
    def test_se_puede_construir_sin_documento_como_sugerencia(self, clasificacion):
        """El motor de reglas debe poder seguir generando una sugerencia
        automática (sin documento_soporte_id) para que un humano la revise;
        el modelo no debe levantar excepción en este caso."""
        clas = _make_clasificacion(clasificacion=clasificacion, documento_soporte_id=None)
        assert clas.documento_soporte_id is None

    @pytest.mark.parametrize(
        "clasificacion",
        [
            ClasificacionDeposito.FINANCIAMIENTO,
            ClasificacionDeposito.APORTACION_SOCIO,
            ClasificacionDeposito.GARANTIA,
        ],
    )
    def test_sin_documento_queda_marcada_requiere_formalizacion(self, clasificacion):
        """Sin documento_soporte_id, una clasificación sensible se
        autoasigna estado_recaracterizacion='requiere_formalizacion',
        nunca 'vigente' ni 'recaracterizado' (nunca una determinación
        fiscal firme sin evidencia real)."""
        clas = _make_clasificacion(clasificacion=clasificacion)
        assert clas.estado_recaracterizacion == EstadoRecaracterizacion.REQUIERE_FORMALIZACION

    def test_ingreso_sin_documento_no_se_fuerza_a_requiere_formalizacion(self):
        """INGRESO y OTRO_NO_GRAVABLE no recaracterizan el depósito, así
        que no exigen documento y no deben forzarse a
        'requiere_formalizacion'."""
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-999",
            clasificacion=ClasificacionDeposito.INGRESO,
            confianza=0.95,
        )
        assert clas.estado_recaracterizacion == EstadoRecaracterizacion.VIGENTE


# ---------------------------------------------------------------------------
# 3. Guardarraíl: no se puede declarar una clasificación sensible como
#    'vigente' ni 'recaracterizado' sin documento_soporte_id.
# ---------------------------------------------------------------------------

class TestNoSePuedeDeclararCerradaSinEvidencia:
    def test_declarar_vigente_sin_documento_levanta_valueerror(self):
        with pytest.raises(ValidationError) as excinfo:
            _make_clasificacion(
                clasificacion=ClasificacionDeposito.FINANCIAMIENTO,
                documento_soporte_id=None,
                estado_recaracterizacion=EstadoRecaracterizacion.VIGENTE,
            )
        assert "documento_soporte_id" in str(excinfo.value)

    def test_declarar_recaracterizado_sin_documento_levanta_valueerror(self):
        with pytest.raises(ValidationError):
            _make_clasificacion(
                clasificacion=ClasificacionDeposito.APORTACION_SOCIO,
                documento_soporte_id=None,
                estado_recaracterizacion=EstadoRecaracterizacion.RECARACTERIZADO,
            )

    def test_declarar_vigente_con_documento_si_se_permite(self):
        """Con documento_soporte_id real, sí se puede declarar 'vigente'
        (o 'recaracterizado') explícitamente."""
        clas = _make_clasificacion(
            clasificacion=ClasificacionDeposito.GARANTIA,
            documento_soporte_id="DOC-GARANTIA-01",
            fecha_documento="2026-01-10",
            estado_recaracterizacion=EstadoRecaracterizacion.VIGENTE,
        )
        assert clas.estado_recaracterizacion == EstadoRecaracterizacion.VIGENTE
        assert clas.documento_soporte_id == "DOC-GARANTIA-01"


# ---------------------------------------------------------------------------
# 4. Núcleo del criterio de aceptación: ningún depósito clasificado como
#    FINANCIAMIENTO/APORTACION_SOCIO/GARANTIA puede *persistirse* sin
#    documento_soporte_id no nulo.
# ---------------------------------------------------------------------------

class TestNoPuedePersistirseSinDocumentoSoporte:
    @pytest.mark.parametrize(
        "clasificacion", sorted(CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE, key=lambda c: c.value)
    )
    def test_puede_persistirse_false_sin_documento(self, clasificacion):
        clas = _make_clasificacion(clasificacion=clasificacion, documento_soporte_id=None)
        assert clas.puede_persistirse() is False

    @pytest.mark.parametrize(
        "clasificacion", sorted(CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE, key=lambda c: c.value)
    )
    def test_puede_persistirse_true_con_documento(self, clasificacion):
        clas = _make_clasificacion(clasificacion=clasificacion, documento_soporte_id="DOC-100")
        assert clas.puede_persistirse() is True

    def test_puede_persistirse_true_para_ingreso_sin_documento(self):
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-999",
            clasificacion=ClasificacionDeposito.INGRESO,
            confianza=0.95,
        )
        assert clas.puede_persistirse() is True

    def test_puede_persistirse_true_para_otro_no_gravable_sin_documento(self):
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-999",
            clasificacion=ClasificacionDeposito.OTRO_NO_GRAVABLE,
            confianza=0.5,
        )
        assert clas.puede_persistirse() is True

    @pytest.mark.parametrize(
        "clasificacion", sorted(CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE, key=lambda c: c.value)
    )
    def test_assert_puede_persistirse_levanta_valueerror_sin_documento(self, clasificacion):
        clas = _make_clasificacion(clasificacion=clasificacion, documento_soporte_id=None)
        with pytest.raises(ValueError, match="documento_soporte_id"):
            assert_puede_persistirse(clas)

    @pytest.mark.parametrize(
        "clasificacion", sorted(CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE, key=lambda c: c.value)
    )
    def test_assert_puede_persistirse_no_levanta_con_documento(self, clasificacion):
        clas = _make_clasificacion(clasificacion=clasificacion, documento_soporte_id="DOC-200")
        assert_puede_persistirse(clas)  # no debe levantar

    def test_assert_puede_persistirse_no_levanta_para_ingreso(self):
        clas = ClasificacionDepositoResult(
            deposito_id="DEP-999",
            clasificacion=ClasificacionDeposito.INGRESO,
            confianza=0.95,
        )
        assert_puede_persistirse(clas)  # no debe levantar

    @pytest.mark.parametrize(
        "clasificacion", sorted(CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE, key=lambda c: c.value)
    )
    def test_documento_soporte_id_vacio_cuenta_como_nulo(self, clasificacion):
        """Un string vacío no debe poder usarse para burlar la regla: sigue
        contando como 'sin documento_soporte_id no nulo'."""
        clas = _make_clasificacion(clasificacion=clasificacion, documento_soporte_id="")
        assert clas.puede_persistirse() is False
        with pytest.raises(ValueError):
            assert_puede_persistirse(clas)


# ---------------------------------------------------------------------------
# 5. Regresión: el flujo real de clasificación automática (REQ-IVA-013 /
#    ClassificationEngine + ReconciliacionIngresosEgresosService) sigue
#    funcionando sin romperse por la nueva regla — las sugerencias sin
#    documento deben seguir generándose, solo marcadas como pendientes.
# ---------------------------------------------------------------------------

class TestRegresionServicioClasificacionAutomatica:
    def test_clasificar_deposito_financiamiento_no_levanta_excepcion(self):
        from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
            ReconciliacionIngresosEgresosService,
        )

        service = ReconciliacionIngresosEgresosService()
        dep = _make_deposito(
            descripcion="Préstamo bancario recibido",
            referencia="PRESTAMO-001",
        )

        resultado = service.clasificar_deposito(dep, [])

        assert resultado.clasificacion == ClasificacionDeposito.FINANCIAMIENTO
        assert resultado.documento_soporte_id is None
        assert resultado.estado_recaracterizacion == EstadoRecaracterizacion.REQUIERE_FORMALIZACION
        assert resultado.puede_persistirse() is False
