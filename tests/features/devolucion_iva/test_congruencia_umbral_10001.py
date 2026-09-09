# -*- coding: utf-8 -*-
"""
REQ-IVA-010 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA).

Criterio de aceptación exacto:
  "Antes de generar una `SolicitudDevolucion` con `monto_solicitado >
  10001.00` MXN, el servicio debe correr una validación automática de
  congruencia DIOT↔CFDI↔declaración mensual (comparar totales
  agrupados) y, si la diferencia supera `$1.00` MXN (redondeo) o si la
  DIOT del periodo no existe, marcar la solicitud como
  `estado="requiere_aclaracion"` en vez de `"lista_para_envio"`."

Este archivo ejercita el servicio real (`preparar_solicitud` a nivel de
módulo, `DevolucionIVAService.preparar_solicitud` a nivel de wrapper, y
`validar_congruencia_diot_cfdi_declaracion` directamente) sin mocks: los
totales se agregan sobre objetos `FacturaCFDI`/`DIOTEntry`/
`DeclaracionMensual` reales.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.devolucion_iva.models import (
    DeclaracionMensual,
    DIOTEntry,
    EstadoEnvioSolicitud,
    FacturaCFDI,
)
from b2b_ai.features.devolucion_iva.service import (
    DevolucionIVAService,
    TOLERANCIA_CONGRUENCIA_MXN,
    UMBRAL_CONGRUENCIA_MONTO,
    preparar_solicitud,
    validar_congruencia_diot_cfdi_declaracion,
)


PERIODO = "2025-03"


def _factura(uuid: str, iva: float, fecha: str = f"{PERIODO}-15") -> FacturaCFDI:
    return FacturaCFDI(
        uuid=uuid,
        rfc_emisor="EMP850101AB1",
        rfc_receptor="REC850101AB2",
        fecha=fecha,
        subtotal=round(iva / 0.16, 2),
        iva=iva,
        total=round(iva / 0.16, 2) + iva,
        proporcionalidad=1.0,
    )


def _diot(iva_acreditable: float) -> DIOTEntry:
    return DIOTEntry(
        rfc_tercero="EMP850101AB1",
        nombre="Proveedor de Prueba",
        monto_neto=round(iva_acreditable / 0.16, 2),
        iva_trasladado=iva_acreditable,
        iva_acreditable=iva_acreditable,
        folios_fiscales=["uuid-1", "uuid-2"],
    )


def _declaracion(iva_pagado: float, mes: int = 3, año: int = 2025) -> DeclaracionMensual:
    return DeclaracionMensual(mes=mes, año=año, iva_pagado=iva_pagado)


# ---------------------------------------------------------------------------
# validar_congruencia_diot_cfdi_declaracion — función pura
# ---------------------------------------------------------------------------

class TestValidarCongruenciaFuncionPura:
    def test_totales_identicos_son_congruentes(self):
        facturas = [_factura("uuid-1", 8000.0), _factura("uuid-2", 8000.0)]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16000.0)]

        resultado = validar_congruencia_diot_cfdi_declaracion(
            PERIODO, facturas, diot_entries, declaraciones,
        )

        assert resultado["diot_existe"] is True
        assert resultado["diferencia_maxima"] == 0.0
        assert resultado["congruente"] is True

    def test_sin_diot_entries_nunca_es_congruente(self):
        facturas = [_factura("uuid-1", 16000.0)]
        declaraciones = [_declaracion(16000.0)]

        resultado = validar_congruencia_diot_cfdi_declaracion(
            PERIODO, facturas, diot_entries=[], declaraciones=declaraciones,
        )

        assert resultado["diot_existe"] is False
        assert resultado["congruente"] is False

    def test_diot_entries_none_nunca_es_congruente(self):
        resultado = validar_congruencia_diot_cfdi_declaracion(
            PERIODO, facturas=None, diot_entries=None, declaraciones=None,
        )
        assert resultado["diot_existe"] is False
        assert resultado["congruente"] is False

    def test_diferencia_exactamente_en_tolerancia_es_congruente(self):
        """$1.00 exacto de diferencia (redondeo) NO 'supera' la tolerancia."""
        facturas = [_factura("uuid-1", 16000.0)]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16000.0 + TOLERANCIA_CONGRUENCIA_MXN)]

        resultado = validar_congruencia_diot_cfdi_declaracion(
            PERIODO, facturas, diot_entries, declaraciones,
        )

        assert resultado["diferencia_maxima"] == pytest.approx(1.00)
        assert resultado["congruente"] is True

    def test_diferencia_apenas_por_encima_de_tolerancia_no_es_congruente(self):
        facturas = [_factura("uuid-1", 16000.0)]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16001.01)]

        resultado = validar_congruencia_diot_cfdi_declaracion(
            PERIODO, facturas, diot_entries, declaraciones,
        )

        assert resultado["diferencia_maxima"] > TOLERANCIA_CONGRUENCIA_MXN
        assert resultado["congruente"] is False

    def test_facturas_fuera_del_periodo_se_excluyen_del_total_cfdi(self):
        facturas = [
            _factura("uuid-1", 16000.0, fecha=f"{PERIODO}-10"),
            _factura("uuid-2", 999.0, fecha="2024-01-05"),  # otro periodo
        ]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16000.0)]

        resultado = validar_congruencia_diot_cfdi_declaracion(
            PERIODO, facturas, diot_entries, declaraciones,
        )

        assert resultado["total_cfdi_iva_acreditable"] == 16000.0
        assert resultado["congruente"] is True


# ---------------------------------------------------------------------------
# preparar_solicitud() — nivel de módulo
# ---------------------------------------------------------------------------

class TestPrepararSolicitudCongruencia:
    def test_monto_en_el_umbral_exacto_no_exige_congruencia(self):
        """monto_solicitado == 10001.00 (no > 10001.00): la validación no
        aplica, incluso sin DIOT/facturas/declaraciones."""
        saldo = {"monto_devolucion_sugerido": UMBRAL_CONGRUENCIA_MONTO}
        sol = preparar_solicitud(PERIODO, saldo)

        assert sol.monto_solicitado == UMBRAL_CONGRUENCIA_MONTO
        assert sol.estado == EstadoEnvioSolicitud.LISTA_PARA_ENVIO
        assert sol.motivo_aclaracion is None

    def test_monto_apenas_arriba_del_umbral_sin_diot_requiere_aclaracion(self):
        saldo = {"monto_devolucion_sugerido": UMBRAL_CONGRUENCIA_MONTO + 0.01}
        sol = preparar_solicitud(PERIODO, saldo)

        assert sol.estado == EstadoEnvioSolicitud.REQUIERE_ACLARACION
        assert sol.motivo_aclaracion is not None
        assert "DIOT" in sol.motivo_aclaracion

    def test_monto_alto_con_datos_congruentes_queda_lista_para_envio(self):
        saldo = {"monto_devolucion_sugerido": 50000.0}
        facturas = [_factura("uuid-1", 16000.0), _factura("uuid-2", 0.0, fecha=f"{PERIODO}-20")]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16000.0)]

        sol = preparar_solicitud(
            PERIODO,
            saldo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=declaraciones,
        )

        assert sol.estado == EstadoEnvioSolicitud.LISTA_PARA_ENVIO
        assert sol.motivo_aclaracion is None

    def test_monto_alto_con_diferencia_fuera_de_tolerancia_requiere_aclaracion(self):
        saldo = {"monto_devolucion_sugerido": 50000.0}
        facturas = [_factura("uuid-1", 16000.0)]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16500.0)]  # $500 de diferencia

        sol = preparar_solicitud(
            PERIODO,
            saldo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=declaraciones,
        )

        assert sol.estado == EstadoEnvioSolicitud.REQUIERE_ACLARACION
        assert "500.00" in sol.motivo_aclaracion or "500" in sol.motivo_aclaracion

    def test_monto_alto_sin_declaracion_del_periodo_requiere_aclaracion(self):
        """DIOT existe pero la declaración es de otro periodo: la
        declaración del periodo pedido efectivamente 'no existe', y su
        total se computa como 0 frente a un DIOT/CFDI != 0 -> incongruente."""
        saldo = {"monto_devolucion_sugerido": 50000.0}
        facturas = [_factura("uuid-1", 16000.0)]
        diot_entries = [_diot(16000.0)]
        declaraciones = [_declaracion(16000.0, mes=1, año=2025)]  # otro periodo

        sol = preparar_solicitud(
            PERIODO,
            saldo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=declaraciones,
        )

        assert sol.estado == EstadoEnvioSolicitud.REQUIERE_ACLARACION

    def test_nunca_bloquea_ni_reduce_el_monto_por_incongruencia(self):
        """ADR-4: el sistema nunca niega/reduce automáticamente; solo marca
        para aclaración humana. La solicitud SIEMPRE se crea con el monto
        completo, sin excepción ni reducción."""
        saldo = {"monto_devolucion_sugerido": 50000.0}
        sol = preparar_solicitud(PERIODO, saldo)  # sin DIOT -> incongruente

        assert sol.monto_solicitado == 50000.0
        assert sol.estado == EstadoEnvioSolicitud.REQUIERE_ACLARACION


# ---------------------------------------------------------------------------
# DevolucionIVAService.preparar_solicitud() — wrapper usado por el router
# ---------------------------------------------------------------------------

class TestServiceWrapperCongruencia:
    def test_wrapper_acepta_dicts_y_marca_requiere_aclaracion(self):
        svc = DevolucionIVAService()
        saldo = {"monto_devolucion_sugerido": 50000.0}

        sol = svc.preparar_solicitud(PERIODO, saldo)  # sin facturas/diot/declaraciones

        assert sol.estado == EstadoEnvioSolicitud.REQUIERE_ACLARACION

    def test_wrapper_acepta_dicts_congruentes_y_marca_lista_para_envio(self):
        svc = DevolucionIVAService()
        saldo = {"monto_devolucion_sugerido": 50000.0}
        facturas = [_factura("uuid-1", 16000.0).model_dump()]
        diot_entries = [_diot(16000.0).model_dump()]
        declaraciones = [_declaracion(16000.0).model_dump()]

        sol = svc.preparar_solicitud(
            PERIODO,
            saldo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=declaraciones,
        )

        assert sol.estado == EstadoEnvioSolicitud.LISTA_PARA_ENVIO
