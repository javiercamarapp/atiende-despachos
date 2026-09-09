"""
service.py — ContabilidadService: lógica de negocio del módulo de Contabilidad.

Servicio stateless-ish que gestiona operaciones contables para despachos
contables mexicanos. Usa stores en memoria para MVP con _reset_state() para tests.

Operaciones:
  - generar_balance_general        : balance general de un período
  - generar_estado_resultados      : estado de resultados de un período
  - registrar_asiento               : registra un asiento contable (valida cuadre)
  - consultar_catalogo_cuentas     : catálogo de cuentas de una empresa
  - conciliar_asientos              : detecta discrepancias entre débitos y créditos
  - calcular_impuestos              : ISR, IVA y PTU estimados
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    AsientoContable,
    BalanceGeneral,
    CuentaCatalogo,
    ContabilidadEntry,
    EstadoResultados,
    GrupoCuenta,
    LineaAsiento,
    NaturalezaCuenta,
    TipoAsiento,
    TipoCuenta,
)

logger = logging.getLogger(__name__)


class ContabilidadError(Exception):
    """Error de dominio del módulo de contabilidad."""

    def __init__(self, message: str, code: str = "contabilidad_error") -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)


class ContabilidadService:
    """Servicio de contabilidad para despachos contables mexicanos.

    Gestiona el ciclo contable: registro de movimientos, generación de
    estados financieros, conciliación y cálculo de impuestos.
    """

    def __init__(self) -> None:
        self._entries: List[ContabilidadEntry] = []
        self._asientos: List[AsientoContable] = []
        self._catalogo: Dict[str, List[CuentaCatalogo]] = {}
        # REQ-MIG-017: códigos de cuenta que tenían movimientos y no vinieron
        # en la última carga de catálogo -- nunca se borraron, quedan aquí
        # para revisión manual. Ver cargar_catalogo()/huerfanas_pendientes().
        self._huerfanas_pendientes: Dict[str, List[str]] = {}

    def _reset_state(self) -> None:
        """Limpia el estado en memoria (uso en tests)."""
        self._entries.clear()
        self._asientos.clear()
        self._catalogo.clear()
        self._huerfanas_pendientes.clear()

    # ------------------------------------------------------------------
    # Balance General
    # ------------------------------------------------------------------

    def generar_balance_general(
        self, empresa_id: str, periodo: str
    ) -> BalanceGeneral:
        """Genera el balance general para una empresa y período.

        Clasifica las cuentas por tipo y grupo, sumando saldos.

        Parameters
        ----------
        empresa_id : str
            Identificador de la empresa.
        periodo : str
            Período contable (YYYY-MM).

        Returns
        -------
        BalanceGeneral
            Snapshot del balance general.
        """
        entries = [
            e
            for e in self._entries
            if e.empresa_id == empresa_id and e.periodo == periodo
        ]

        catalogo = self._catalogo.get(empresa_id, [])
        cuenta_tipo: Dict[str, TipoCuenta] = {
            c.codigo: c.tipo for c in catalogo
        }
        cuenta_grupo: Dict[str, GrupoCuenta] = {
            c.codigo: c.grupo for c in catalogo
        }
        cuenta_naturaleza: Dict[str, NaturalezaCuenta] = {
            c.codigo: c.naturaleza for c in catalogo
        }

        activos_corriente = 0.0
        activos_no_corriente = 0.0
        pasivos_corriente = 0.0
        pasivos_no_corriente = 0.0

        for entry in entries:
            tipo = cuenta_tipo.get(entry.cuenta_contable)
            grupo = cuenta_grupo.get(entry.cuenta_contable)
            naturaleza = cuenta_naturaleza.get(entry.cuenta_contable)
            # El saldo de una cuenta acreedora (pasivo/capital: crece con el
            # crédito) es credito - debito; el de una deudora (activo: crece
            # con el débito) es debito - credito. Antes se usaba SIEMPRE
            # `debito - credito`, lo que invertía el signo de todo pasivo
            # (crédito neto de proveedores/créditos bancarios llegaba
            # negativo) y rompía `pasivos`/`capital` del balance general.
            if naturaleza == NaturalezaCuenta.ACREEDORA:
                saldo = entry.credito - entry.debito
            else:
                saldo = entry.debito - entry.credito

            if tipo == TipoCuenta.ACTIVO:
                if grupo == GrupoCuenta.ACTIVO_CORRIENTE:
                    activos_corriente += saldo
                elif grupo == GrupoCuenta.ACTIVO_NO_CORRIENTE:
                    activos_no_corriente += saldo
                else:
                    activos_corriente += saldo  # default corriente

            elif tipo == TipoCuenta.PASIVO:
                if grupo == GrupoCuenta.PASIVO_CORRIENTE:
                    pasivos_corriente += saldo
                elif grupo == GrupoCuenta.PASIVO_NO_CORRIENTE:
                    pasivos_no_corriente += saldo
                else:
                    pasivos_corriente += saldo

        activos = activos_corriente + activos_no_corriente
        pasivos = pasivos_corriente + pasivos_no_corriente
        capital = activos - pasivos

        return BalanceGeneral(
            empresa_id=empresa_id,
            periodo=periodo,
            activos=round(activos, 2),
            pasivos=round(pasivos, 2),
            capital=round(capital, 2),
            activos_corriente=round(activos_corriente, 2),
            activos_no_corriente=round(activos_no_corriente, 2),
            pasivos_corriente=round(pasivos_corriente, 2),
            pasivos_no_corriente=round(pasivos_no_corriente, 2),
        )

    # ------------------------------------------------------------------
    # Estado de Resultados
    # ------------------------------------------------------------------

    def generar_estado_resultados(
        self, empresa_id: str, periodo: str
    ) -> EstadoResultados:
        """Genera el estado de resultados para una empresa y período.

        Parameters
        ----------
        empresa_id : str
            Identificador de la empresa.
        periodo : str
            Período contable (YYYY-MM).

        Returns
        -------
        EstadoResultados
            Estado de resultados del período.
        """
        entries = [
            e
            for e in self._entries
            if e.empresa_id == empresa_id and e.periodo == periodo
        ]

        catalogo = self._catalogo.get(empresa_id, [])
        cuenta_tipo: Dict[str, TipoCuenta] = {
            c.codigo: c.tipo for c in catalogo
        }

        ingresos = 0.0
        costos = 0.0
        gastos = 0.0
        otros_ingresos = 0.0
        otros_gastos = 0.0

        for entry in entries:
            monto = entry.debito - entry.credito
            tipo = cuenta_tipo.get(entry.cuenta_contable)

            if tipo == TipoCuenta.INGRESO:
                # Ingresos son acreedores: saldo negativo → restar
                ingresos += abs(monto)
            elif tipo == TipoCuenta.COSTO:
                costos += abs(monto)
            elif tipo == TipoCuenta.GASTO:
                gastos += abs(monto)

        utilidad_bruta = ingresos - costos
        utilidad_antes_impuestos = utilidad_bruta - gastos + otros_ingresos - otros_gastos

        # ISR estimado: 30% sobre utilidad antes de impuestos (simplificado)
        impuestos = max(0.0, utilidad_antes_impuestos * 0.30)
        utilidad_neta = utilidad_antes_impuestos - impuestos

        return EstadoResultados(
            empresa_id=empresa_id,
            periodo=periodo,
            ingresos=round(ingresos, 2),
            costos=round(costos, 2),
            utilidad_bruta=round(utilidad_bruta, 2),
            gastos=round(gastos, 2),
            otros_ingresos=round(otros_ingresos, 2),
            otros_gastos=round(otros_gastos, 2),
            utilidad_antes_impuestos=round(utilidad_antes_impuestos, 2),
            impuestos=round(impuestos, 2),
            utilidad_neta=round(utilidad_neta, 2),
        )

    # ------------------------------------------------------------------
    # Registro de Asientos
    # ------------------------------------------------------------------

    def registrar_asiento(self, asiento: AsientoContable) -> AsientoContable:
        """Registra un asiento contable validando que cuadre.

        El asiento debe tener al menos 2 líneas y la suma de débitos
        debe ser igual a la suma de créditos.

        Parameters
        ----------
        asiento : AsientoContable
            Asiento a registrar.

        Returns
        -------
        AsientoContable
            Asiento registrado (con ID asignado).

        Raises
        ------
        ContabilidadError
            Si el asiento no cuadra o tiene datos inválidos.
        """
        if len(asiento.lineas) < 2:
            raise ContabilidadError(
                "Un asiento debe tener al menos 2 líneas.",
                code="asiento_incompleto",
            )

        total_debito = sum(l.debito for l in asiento.lineas)
        total_credito = sum(l.credito for l in asiento.lineas)

        if abs(total_debito - total_credito) > 0.01:
            raise ContabilidadError(
                f"El asiento no cuadra: débito ({total_debito:.2f}) "
                f"!= crédito ({total_credito:.2f}).",
                code="asiento_no_cuadra",
            )

        if total_debito == 0 and total_credito == 0:
            raise ContabilidadError(
                "El asiento no puede tener débito y crédito en cero.",
                code="asiento_vacio",
            )

        # Registrar también como entries individuales
        for linea in asiento.lineas:
            entry = ContabilidadEntry(
                empresa_id=asiento.empresa_id,
                cuenta_contable=linea.cuenta_contable,
                descripcion=linea.descripcion or asiento.descripcion,
                debito=linea.debito,
                credito=linea.credito,
                fecha=asiento.fecha,
                periodo=asiento.periodo,
            )
            self._entries.append(entry)

        self._asientos.append(asiento)
        logger.info(
            "Asiento registrado id=%s empresa=%s periodo=%s tipo=%s",
            asiento.id,
            asiento.empresa_id,
            asiento.periodo,
            asiento.tipo.value,
        )
        return asiento

    # ------------------------------------------------------------------
    # Catálogo de Cuentas
    # ------------------------------------------------------------------

    def consultar_catalogo_cuentas(
        self, empresa_id: str
    ) -> List[CuentaCatalogo]:
        """Consulta el catálogo de cuentas de una empresa.

        Parameters
        ----------
        empresa_id : str
            Identificador de la empresa.

        Returns
        -------
        List[CuentaCatalogo]
            Lista de cuentas del catálogo.
        """
        return self._catalogo.get(empresa_id, [])

    def cargar_catalogo(
        self, empresa_id: str, cuentas: List[CuentaCatalogo]
    ) -> List[CuentaCatalogo]:
        """Carga (mergea) el catálogo de cuentas de una empresa.

        REQ-MIG-017: antes, este método hacía `self._catalogo[empresa_id]
        = cuentas`, un reemplazo destructivo completo. Si el catálogo
        entrante omitía una cuenta que ya tenía asientos registrados
        (`registrar_asiento` -> `self._entries`), esa cuenta desaparecía
        del catálogo y sus movimientos quedaban huérfanos: no hay FK real
        aquí (todo en memoria), así que no truena nada -- simplemente
        `generar_balance_general`/`generar_estado_resultados` dejan de
        poder clasificar esos montos (`cuenta_tipo.get(...)` regresa
        `None` y el saldo se pierde en silencio del reporte). Ver
        `tests/features/contabilidad/test_cargar_catalogo_merge_no_destructivo.py`
        para la reproducción exacta del bug contra el código sin este fix.

        Comportamiento nuevo (merge seguro por código de cuenta):
          - Código nuevo (no existía en el catálogo de la empresa): se
            agrega tal cual viene.
          - Código existente que SÍ viene en el catálogo entrante: se
            actualiza in place (misma posición en la lista -- no se hace
            pop+append) solo en sus campos editables (nombre, tipo,
            grupo, nivel, naturaleza, activa).
          - Código existente que NO viene en el catálogo entrante:
              * si tiene movimientos (algún `ContabilidadEntry` con ese
                `cuenta_contable` para esta empresa, es decir ya se usó en
                un asiento/póliza real): fail-closed -- NUNCA se borra ni
                se desactiva. Se conserva intacta y se reporta en
                `huerfanas_pendientes(empresa_id)` para revisión manual
                (además de un `logger.warning`).
              * si NO tiene movimientos: es seguro retirarla del catálogo
                activo. Se elige marcarla `activa=False` en vez de
                eliminarla físicamente de la lista -- conserva el
                registro (auditoría/histórico) sin ningún costo de
                integridad ya que nada la referencia, y es reversible si
                una carga futura la vuelve a incluir.

        Parameters
        ----------
        empresa_id : str
            Identificador de la empresa.
        cuentas : List[CuentaCatalogo]
            Catálogo entrante. NO reemplaza el existente: se mergea.

        Returns
        -------
        List[CuentaCatalogo]
            Catálogo COMPLETO resultante para la empresa (existentes
            actualizadas + nuevas agregadas + huérfanas conservadas +
            sin-movimiento marcadas inactivas). Para una empresa sin
            catálogo previo, equivale exactamente a `cuentas`.
        """
        existentes = self._catalogo.get(empresa_id, [])
        existentes_por_codigo: Dict[str, CuentaCatalogo] = {
            c.codigo: c for c in existentes
        }
        entrantes_por_codigo: Dict[str, CuentaCatalogo] = {
            c.codigo: c for c in cuentas
        }
        codigos_con_movimientos = {
            e.cuenta_contable
            for e in self._entries
            if e.empresa_id == empresa_id
        }

        resultado: List[CuentaCatalogo] = []
        huerfanas: List[str] = []
        actualizadas = 0

        for codigo, actual in existentes_por_codigo.items():
            nueva = entrantes_por_codigo.get(codigo)
            if nueva is not None:
                resultado.append(actual.model_copy(update={
                    "nombre": nueva.nombre,
                    "tipo": nueva.tipo,
                    "grupo": nueva.grupo,
                    "nivel": nueva.nivel,
                    "naturaleza": nueva.naturaleza,
                    "activa": nueva.activa,
                }))
                actualizadas += 1
            elif codigo in codigos_con_movimientos:
                # Fail-closed: tiene movimientos reales, no se toca.
                resultado.append(actual)
                huerfanas.append(codigo)
            else:
                # Sin movimientos y ya no viene en el catálogo entrante:
                # seguro retirarla -- se desactiva, no se borra (ver
                # docstring de la clase para la justificación).
                resultado.append(actual.model_copy(update={"activa": False}))

        nuevas_agregadas = 0
        for codigo, nueva in entrantes_por_codigo.items():
            if codigo not in existentes_por_codigo:
                resultado.append(nueva)
                nuevas_agregadas += 1

        self._catalogo[empresa_id] = resultado
        if huerfanas:
            self._huerfanas_pendientes[empresa_id] = huerfanas
            logger.warning(
                "Catálogo empresa=%s: %d cuenta(s) con movimientos no "
                "vinieron en el catálogo entrante y NO se borraron "
                "(requieren revisión manual): %s",
                empresa_id,
                len(huerfanas),
                huerfanas,
            )
        else:
            self._huerfanas_pendientes.pop(empresa_id, None)

        logger.info(
            "Catálogo cargado (merge) empresa=%s total=%d nuevas=%d "
            "actualizadas=%d huerfanas_pendientes=%d",
            empresa_id,
            len(resultado),
            nuevas_agregadas,
            actualizadas,
            len(huerfanas),
        )
        return resultado

    def huerfanas_pendientes(self, empresa_id: str) -> List[str]:
        """Códigos de cuenta con movimientos que la última carga de
        catálogo omitió y que, por eso, NO se borraron (REQ-MIG-017).

        Lista vacía si no hay ninguna pendiente de revisión manual.
        """
        return list(self._huerfanas_pendientes.get(empresa_id, []))

    # ------------------------------------------------------------------
    # Conciliación
    # ------------------------------------------------------------------

    def conciliar_asientos(
        self, empresa_id: str, periodo: str
    ) -> Dict[str, Any]:
        """Concilia asientos: verifica que débitos == créditos por período.

        Parameters
        ----------
        empresa_id : str
            Identificador de la empresa.
        periodo : str
            Período contable (YYYY-MM).

        Returns
        -------
        dict
            Resultado de conciliación con discrepancias encontradas.
        """
        asientos_periodo = [
            a
            for a in self._asientos
            if a.empresa_id == empresa_id and a.periodo == periodo
        ]

        total_debito = 0.0
        total_credito = 0.0
        discrepancias = []

        for asiento in asientos_periodo:
            a_debito = sum(l.debito for l in asiento.lineas)
            a_credito = sum(l.credito for l in asiento.lineas)
            total_debito += a_debito
            total_credito += a_credito

            if abs(a_debito - a_credito) > 0.01:
                discrepancias.append(
                    {
                        "asiento_id": asiento.id,
                        "partida_id": asiento.partida_id,
                        "debito": round(a_debito, 2),
                        "credito": round(a_credito, 2),
                        "diferencia": round(abs(a_debito - a_credito), 2),
                    }
                )

        return {
            "empresa_id": empresa_id,
            "periodo": periodo,
            "total_asientos": len(asientos_periodo),
            "total_debito": round(total_debito, 2),
            "total_credito": round(total_credito, 2),
            "diferencia_global": round(abs(total_debito - total_credito), 2),
            "conciliado": len(discrepancias) == 0
            and abs(total_debito - total_credito) < 0.01,
            "discrepancias": discrepancias,
        }

    # ------------------------------------------------------------------
    # Cálculo de Impuestos
    # ------------------------------------------------------------------

    def calcular_impuestos(
        self, empresa_id: str, periodo: str
    ) -> Dict[str, Any]:
        """Calcula impuestos estimados: ISR, IVA y PTU.

        Basado en el estado de resultados del período.

        Parameters
        ----------
        empresa_id : str
            Identificador de la empresa.
        periodo : str
            Período contable (YYYY-MM).

        Returns
        -------
        dict
            Desglose de impuestos calculados.
        """
        er = self.generar_estado_resultados(empresa_id, periodo)

        # ISR: 30% sobre utilidad antes de impuestos (tasa fija simplificada)
        isr = max(0.0, er.utilidad_antes_impuestos * 0.30)

        # IVA: se calcula sobre ingresos gravados (simplificado: 16% del IVA cobrado)
        # En el MVP usamos un estimado del 16% sobre ingresos
        iva_cobrado = er.ingresos * 0.16
        iva_pagado = er.costos * 0.16 + er.gastos * 0.16
        iva_neto = iva_cobrado - iva_pagado

        # PTU: 10% de la utilidad fiscal antes de impuestos (art. 123 LFT)
        ptu = max(0.0, er.utilidad_antes_impuestos * 0.10)

        return {
            "empresa_id": empresa_id,
            "periodo": periodo,
            "isr": round(isr, 2),
            "isr_tasa": 0.30,
            "iva_cobrado": round(iva_cobrado, 2),
            "iva_pagado": round(iva_pagado, 2),
            "iva_neto": round(iva_neto, 2),
            "iva_tasa": 0.16,
            "ptu": round(ptu, 2),
            "ptu_tasa": 0.10,
            "total_impuestos": round(isr + max(0.0, iva_neto) + ptu, 2),
            "utilidad_antes_impuestos": er.utilidad_antes_impuestos,
        }
