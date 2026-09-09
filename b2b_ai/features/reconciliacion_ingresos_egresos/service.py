# -*- coding: utf-8 -*-
"""
service.py — ReconciliacionIngresosEgresosService: conciliación de ingresos
y egresos con auxiliares contables para despachos contables mexicanos.

This service:
  - Collects bank deposits and auxiliary accounting entries
  - Classifies deposits (income, financing, partner contributions, guarantees, other)
  - Matches deposits with auxiliary entries
  - Detects discrepancies between bank and accounting data
  - Calculates IVA balance
  - Generates working papers for tax auditor review
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE,
    NOTA_ART_59_FR_III_CFF,
    ORIGEN_MOTOR_REGLAS,
    AuxiliarContable,
    BalanceIVA,
    CasoDepositoSospechoso,
    ClasificacionDeposito,
    ClasificacionDepositoResult,
    ConciliacionIngresosEgresos,
    DepositoBancario,
    DiscrepanciaFiscal,
    EstadoCasoDeposito,
    EstadoRecaracterizacion,
    MovimientoAuxiliar,
    OrigenClasificacion,
    PapelTrabajoConciliacion,
    SeccionResumen,
    Severidad,
    TipoDiscrepancia,
    requiere_documento_soporte,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.classification_rules import (
    ClassificationEngine,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.validators import (
    validate_auxiliar_contable,
    validate_balance_iva,
    validate_deposito,
    validate_periodo,
)


class ReconciliacionIngresosEgresosService:
    """Core service for Income/Expense Reconciliation.

    Manages the complete reconciliation lifecycle:
      1. Data collection (deposits, auxiliaries)
      2. Classification (rule engine)
      3. Conciliation (matching)
      4. Discrepancy detection
      5. IVA balance calculation
      6. Working paper generation
    """

    # Clasificaciones "no triviales": requieren evidencia documental real
    # (contrato de mutuo, acta de asamblea, contrato de garantía) antes de
    # sostenerse ante una revisión — ver ADR-4. REQ-IVA-013 exige que estas
    # queden con `clasificado_por`/`clasificado_en` no nulos.
    CLASIFICACIONES_NO_TRIVIALES = frozenset({
        ClasificacionDeposito.FINANCIAMIENTO,
        ClasificacionDeposito.APORTACION_SOCIO,
        ClasificacionDeposito.GARANTIA,
    })

    # REQ-IVA-011 / ADR-4: umbral de confianza por debajo del cual una regla
    # de clasificación se considera "score bajo" para efectos de marcar un
    # depósito como sospechoso ante una devolución de IVA. Igual al umbral
    # ya usado en `clasificar_deposito` para `requires_human_review`, para
    # no introducir un segundo criterio de "confianza baja" en el módulo.
    UMBRAL_CONFIANZA_SOSPECHOSA = 0.7

    def __init__(self, classification_engine: Optional[ClassificationEngine] = None):
        self._engine = classification_engine or ClassificationEngine()
        self._conciliaciones: Dict[str, ConciliacionIngresosEgresos] = {}
        self._papeles_trabajo: Dict[str, PapelTrabajoConciliacion] = {}
        # REQ-IVA-013: registro de clasificaciones por id, para poder
        # localizarlas y aprobarlas humanamente vía
        # PATCH /clasificaciones/{id}/aprobar sin perder el estado entre
        # llamadas al servicio.
        self._clasificaciones: Dict[str, ClasificacionDepositoResult] = {}

    # -------------------------------------------------------------------
    # Step 1: Collect data
    # -------------------------------------------------------------------

    def recopilar_depositos(
        self,
        periodo: str,
        tenant_id: Optional[str],
        depositos_data: List[dict],
    ) -> List[DepositoBancario]:
        """Collect and validate bank deposits for a period.

        Parameters
        ----------
        periodo : str
            Period (YYYY-MM).
        tenant_id : Optional[str]
            Tenant identifier.
        depositos_data : List[dict]
            Raw deposit data (id, fecha, monto, descripcion, referencia, banco, cuenta, es_credito).

        Returns
        -------
        List[DepositoBancario]
            Validated deposits.
        """
        depositos: List[DepositoBancario] = []
        for d in depositos_data:
            dep = DepositoBancario(
                id=d.get("id", ""),
                fecha=d.get("fecha", ""),
                monto=float(d.get("monto", 0.0)),
                descripcion=d.get("descripcion", ""),
                referencia=d.get("referencia", ""),
                banco=d.get("banco", ""),
                cuenta=d.get("cuenta", ""),
                es_credito=d.get("es_credito", True),
            )
            is_valid, err = validate_deposito(dep)
            if is_valid:
                depositos.append(dep)
        return depositos

    def recopilar_auxiliares(
        self,
        periodo: str,
        tenant_id: Optional[str],
        auxiliares_data: List[dict],
    ) -> List[AuxiliarContable]:
        """Collect and validate auxiliary accounting entries for a period.

        Parameters
        ----------
        periodo : str
            Period (YYYY-MM).
        tenant_id : Optional[str]
            Tenant identifier.
        auxiliares_data : List[dict]
            Raw auxiliary data (cuenta_id, cuenta_mayor, cuenta_auxiliar,
            descripcion, saldo_inicial, movimientos, saldo_final).

        Returns
        -------
        List[AuxiliarContable]
            Validated auxiliaries.
        """
        auxiliares: List[AuxiliarContable] = []
        for a in auxiliares_data:
            movimientos = []
            for m in a.get("movimientos", []):
                movimientos.append(MovimientoAuxiliar(
                    fecha=m.get("fecha", ""),
                    concepto=m.get("concepto", ""),
                    debe=float(m.get("debe", 0.0)),
                    haber=float(m.get("haber", 0.0)),
                    referencia=m.get("referencia", ""),
                    tipo=m.get("tipo", "ingreso"),
                ))
            aux = AuxiliarContable(
                cuenta_id=a.get("cuenta_id", ""),
                cuenta_mayor=a.get("cuenta_mayor", ""),
                cuenta_auxiliar=a.get("cuenta_auxiliar", ""),
                descripcion=a.get("descripcion", ""),
                saldo_inicial=float(a.get("saldo_inicial", 0.0)),
                movimientos=movimientos,
                saldo_final=float(a.get("saldo_final", 0.0)),
            )
            is_valid, err = validate_auxiliar_contable(aux)
            if is_valid:
                auxiliares.append(aux)
        return auxiliares

    # -------------------------------------------------------------------
    # Step 2: Classify deposits
    # -------------------------------------------------------------------

    def clasificar_deposito(
        self,
        deposito: DepositoBancario,
        auxiliares: List[AuxiliarContable],
        tenant_id: Optional[str] = None,
    ) -> ClasificacionDepositoResult:
        """Classify a single deposit using the rule engine.

        REQ-IVA-013: el resultado del motor de reglas SIEMPRE nace con
        ``origen=OrigenClasificacion.AUTOMATICO_SUGERIDO`` — nunca
        ``APROBADO`` — sin importar cuán alta sea la confianza de la regla
        que hizo match. Solo ``aprobar_clasificacion()`` (invocado por el
        endpoint ``PATCH /clasificaciones/{id}/aprobar``) puede mover una
        clasificación a ``APROBADO``, y solo después de confirmación
        humana explícita. Además, toda clasificación "no trivial"
        (financiamiento/aportación de socio/garantía — ver
        ``CLASIFICACIONES_NO_TRIVIALES``) queda con ``clasificado_por``
        (el identificador del motor automático, nunca una persona) y
        ``clasificado_en`` (timestamp) no nulos, para que quede trazable
        quién y cuándo produjo esa sugerencia.

        Parameters
        ----------
        deposito : DepositoBancario
            The deposit to classify.
        auxiliares : List[AuxiliarContable]
            Available auxiliary entries for matching.
        tenant_id : Optional[str]
            Tenant owning this classification (stored so
            ``aprobar_clasificacion`` can enforce aislamiento multi-tenant).

        Returns
        -------
        ClasificacionDepositoResult
        """
        classification, confidence, reason, articulo = self._engine.classify(
            deposito, auxiliares
        )

        requires_review = confidence < 0.7

        no_trivial = classification in self.CLASIFICACIONES_NO_TRIVIALES
        clasificado_en = datetime.now().isoformat() if no_trivial else None
        clasificado_por = ORIGEN_MOTOR_REGLAS if no_trivial else None

        resultado = ClasificacionDepositoResult(
            tenant_id=tenant_id,
            deposito_id=deposito.id,
            clasificacion=classification,
            confianza=confidence,
            razon=reason or "",
            articulo_cff=articulo,
            requires_human_review=requires_review,
            origen=OrigenClasificacion.AUTOMATICO_SUGERIDO,
            clasificado_por=clasificado_por,
            clasificado_en=clasificado_en,
        )

        self._clasificaciones[resultado.id] = resultado
        return resultado

    def clasificar_todos(
        self,
        depositos: List[DepositoBancario],
        auxiliares: List[AuxiliarContable],
        tenant_id: Optional[str] = None,
    ) -> List[ClasificacionDepositoResult]:
        """Classify all deposits using the rule engine.

        Parameters
        ----------
        depositos : List[DepositoBancario]
            Deposits to classify.
        auxiliares : List[AuxiliarContable]
            Available auxiliary entries.
        tenant_id : Optional[str]
            Tenant owning these classifications.

        Returns
        -------
        List[ClasificacionDepositoResult]
        """
        return [
            self.clasificar_deposito(dep, auxiliares, tenant_id=tenant_id)
            for dep in depositos
        ]

    # -------------------------------------------------------------------
    # Step 2b: Human approval of a classification (REQ-IVA-013, ADR-4)
    # -------------------------------------------------------------------

    def get_clasificacion(
        self,
        clasificacion_id: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[ClasificacionDepositoResult]:
        """Retrieve a stored classification by id.

        Returns ``None`` both when the id does not exist and when it
        belongs to a different tenant — callers must not distinguish the
        two cases in their response (avoids leaking existence of another
        tenant's classification).
        """
        clas = self._clasificaciones.get(clasificacion_id)
        if clas is None:
            return None
        if tenant_id is not None and clas.tenant_id is not None and clas.tenant_id != tenant_id:
            return None
        return clas

    def aprobar_clasificacion(
        self,
        clasificacion_id: str,
        aprobado_por: str,
        tenant_id: Optional[str] = None,
    ) -> ClasificacionDepositoResult:
        """Confirm a suggested classification as a human, definitive decision.

        This is the ONLY code path that may set
        ``origen=OrigenClasificacion.APROBADO`` (REQ-IVA-013, ADR-4): the
        rule engine itself never produces ``APROBADO`` directly, so a
        classification only becomes a firm fiscal determination once a
        human has explicitly confirmed it here.

        Parameters
        ----------
        clasificacion_id : str
            Id of the classification to approve.
        aprobado_por : str
            Identifier (user id) of the human confirming the classification.
        tenant_id : Optional[str]
            Tenant of the caller; enforced against the classification's
            own tenant to prevent cross-tenant approval.

        Raises
        ------
        KeyError
            If no classification with that id exists (or it belongs to a
            different tenant — indistinguishable from "not found" on
            purpose, to avoid leaking cross-tenant existence).
        ValueError
            If the classification was already approved (approval is a
            one-time, explicit human action — not silently idempotent).
        """
        clas = self.get_clasificacion(clasificacion_id, tenant_id=tenant_id)
        if clas is None:
            raise KeyError(f"Clasificación '{clasificacion_id}' no encontrada.")

        if clas.origen == OrigenClasificacion.APROBADO:
            raise ValueError(
                f"La clasificación '{clasificacion_id}' ya fue aprobada "
                f"por '{clas.aprobado_por}' en '{clas.aprobado_en}'."
            )

        clas.origen = OrigenClasificacion.APROBADO
        clas.aprobado_por = aprobado_por
        clas.aprobado_en = datetime.now().isoformat()
        self._clasificaciones[clasificacion_id] = clas
        return clas

    # -------------------------------------------------------------------
    # Step 2c: Attach real supporting document (REQ-IVA-003, ADR-4)
    # -------------------------------------------------------------------

    def adjuntar_documento_soporte(
        self,
        clasificacion_id: str,
        documento_soporte_id: str,
        fecha_documento: str,
        tenant_id: Optional[str] = None,
    ) -> ClasificacionDepositoResult:
        """Adjunta el documento real (contrato de mutuo, acta de asamblea,
        contrato de garantía) que soporta una clasificación de depósito ya
        hecha (REQ-IVA-003 — mecanismo operativo que hace cumplible
        REQ-IVA-002/ADR-4).

        Antes de este adjunto, una clasificación FINANCIAMIENTO/
        APORTACION_SOCIO/GARANTIA nace con
        ``estado_recaracterizacion=EstadoRecaracterizacion.REQUIERE_FORMALIZACION``
        ("pendiente_evidencia" en el criterio de aceptación) y
        ``puede_persistirse()`` es ``False`` — no puede incluirse en un
        papel de trabajo exportable (ver ``generar_papel_trabajo_exportable``).
        Después de este adjunto queda ``RECARACTERIZADO`` y
        ``puede_persistirse()`` pasa a ``True``.

        Nunca sintetiza ni infiere el documento: quien llama debe pasar un
        ``documento_soporte_id`` real (referencia al repositorio de
        documentos/adjuntos) y su ``fecha_documento`` real; ninguno de los
        dos puede venir vacío.

        Parameters
        ----------
        clasificacion_id : str
            Id de la clasificación (``ClasificacionDepositoResult.id``) a
            la que se adjunta el documento.
        documento_soporte_id : str
            Identificador del documento real en el repositorio de
            documentos/adjuntos.
        fecha_documento : str
            Fecha del documento real (YYYY-MM-DD).
        tenant_id : Optional[str]
            Tenant del solicitante; se exige que coincida con el de la
            clasificación (mismo criterio de aislamiento que
            ``aprobar_clasificacion``).

        Raises
        ------
        KeyError
            Si no existe una clasificación con ese id, o pertenece a otro
            tenant (indistinguible a propósito, para no filtrar existencia
            entre tenants).
        ValueError
            Si ``documento_soporte_id`` o ``fecha_documento`` vienen vacíos.
        """
        if not documento_soporte_id or not documento_soporte_id.strip():
            raise ValueError(
                "documento_soporte_id es obligatorio y no puede estar vacío: "
                "debe referenciar el documento real (contrato de mutuo, acta "
                "de asamblea o contrato de garantía) en el repositorio de "
                "documentos/adjuntos. Un depósito 'sospechoso' nunca se "
                "recaracteriza sin evidencia documental real (ADR-4)."
            )
        if not fecha_documento or not fecha_documento.strip():
            raise ValueError("fecha_documento es obligatoria y no puede estar vacía.")

        clas = self.get_clasificacion(clasificacion_id, tenant_id=tenant_id)
        if clas is None:
            raise KeyError(f"Clasificación '{clasificacion_id}' no encontrada.")

        clas.documento_soporte_id = documento_soporte_id
        clas.fecha_documento = fecha_documento
        if clas.clasificacion in CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE:
            clas.estado_recaracterizacion = EstadoRecaracterizacion.RECARACTERIZADO

        self._clasificaciones[clasificacion_id] = clas
        return clas

    # -------------------------------------------------------------------
    # Step 3: Conciliate
    # -------------------------------------------------------------------

    def conciliar_depositos_auxiliares(
        self,
        depositos: List[DepositoBancario],
        auxiliares: List[AuxiliarContable],
        periodo: str = "",
        tenant_id: Optional[str] = None,
    ) -> ConciliacionIngresosEgresos:
        """Match deposits with auxiliary accounting entries.

        Matching strategy:
          - Exact match by reference
          - Amount match within tolerance (±0.01)
          - Date proximity (±1 day)

        Parameters
        ----------
        depositos : List[DepositoBancario]
            Bank deposits.
        auxiliares : List[AuxiliarContable]
            Auxiliary entries.
        periodo : str
            Period (YYYY-MM) this reconciliation belongs to, used as part
            of the storage key so it can be retrieved later via
            ``get_conciliacion``.
        tenant_id : Optional[str]
            Tenant identifier, used as part of the storage key.

        Returns
        -------
        ConciliacionIngresosEgresos
        """
        clasificaciones = self.clasificar_todos(depositos, auxiliares, tenant_id=tenant_id)
        discrepancias = self._detectar_discrepancias(depositos, auxiliares, clasificaciones)

        saldo_bancario = sum(d.monto for d in depositos if d.es_credito)
        saldo_contable = sum(a.saldo_final for a in auxiliares)

        conciliacion = ConciliacionIngresosEgresos(
            periodo=periodo,
            tenant_id=tenant_id,
            depositos=depositos,
            auxiliares=auxiliares,
            clasificaciones=clasificaciones,
            discrepancias=discrepancias,
            saldo_bancario=saldo_bancario,
            saldo_contable=saldo_contable,
            diferencia=saldo_bancario - saldo_contable,
        )

        # Bug REQ-IVA-012: este resultado nunca se guardaba en
        # self._conciliaciones, por lo que get_conciliacion() siempre
        # devolvía None y las clasificaciones con evidencia documental
        # (REQ-IVA-002/003/013) quedaban irrecuperables después de conciliar.
        conciliacion_id = f"{periodo}_{tenant_id or 'default'}"
        self._conciliaciones[conciliacion_id] = conciliacion

        return conciliacion

    # -------------------------------------------------------------------
    # Step 3b: Depósitos sospechosos ante una devolución de IVA
    # (REQ-IVA-011, ADR-4)
    # -------------------------------------------------------------------

    def evaluar_caso_deposito_sospechoso(
        self,
        deposito: DepositoBancario,
        clasificacion: ClasificacionDepositoResult,
    ) -> CasoDepositoSospechoso:
        """Evalúa si un depósito es "sospechoso" para efectos de una
        solicitud de devolución de IVA — nunca lo niega ni lo rechaza.

        REQ-IVA-011 / ADR-4: un depósito clasificado bajo la presunción del
        Art. 59 fracción III CFF (financiamiento, aportación de socio o
        garantía — ver ``requiere_documento_soporte``) se considera
        "sospechoso" cuando le falta documento de soporte real
        (``deposito.documento_soporte_id`` vacío) O cuando la regla que lo
        clasificó tuvo una confianza (score) por debajo de
        ``UMBRAL_CONFIANZA_SOSPECHOSA`` — cualquiera de las dos condiciones
        basta, no ambas.

        El sistema NUNCA niega ni reduce automáticamente la devolución por
        esto. Lo único que este método puede producir cuando el caso es
        sospechoso es ``estado=EstadoCasoDeposito.REQUIERE_REVISION_HUMANA``
        con ``requiere_revision_humana=True`` y la nota exacta que cita el
        criterio PRODECON 1/2026 sobre el Art. 59 fr. III CFF
        (``NOTA_ART_59_FR_III_CFF``). El tipo ``EstadoCasoDeposito`` no
        contempla ningún valor de rechazo, así que este método no puede,
        ni por error, producir una determinación de "rechazada" — no es una
        rama de código que dependa de que alguien la programe bien, es una
        restricción del propio tipo de retorno.

        Depósitos que NO caen bajo la presunción del Art. 59 fr. III CFF
        (p. ej. ``INGRESO`` u ``OTRO_NO_GRAVABLE``) nunca se marcan como
        sospechosos aquí, sin importar su score: esa evaluación queda fuera
        del alcance de este requisito.

        Parameters
        ----------
        deposito : DepositoBancario
            El depósito evaluado (se usa su ``documento_soporte_id``).
        clasificacion : ClasificacionDepositoResult
            El resultado de clasificación de ese mismo depósito (se usa su
            ``clasificacion`` y ``confianza``).

        Returns
        -------
        CasoDepositoSospechoso
        """
        documento_soporte_id = deposito.documento_soporte_id
        bajo_presuncion_art59 = requiere_documento_soporte(clasificacion.clasificacion)
        sin_documento = not documento_soporte_id
        score_bajo = clasificacion.confianza < self.UMBRAL_CONFIANZA_SOSPECHOSA

        es_sospechoso = bajo_presuncion_art59 and (sin_documento or score_bajo)

        return CasoDepositoSospechoso(
            deposito_id=deposito.id,
            clasificacion=clasificacion.clasificacion,
            confianza=clasificacion.confianza,
            documento_soporte_id=documento_soporte_id,
            estado=(
                EstadoCasoDeposito.REQUIERE_REVISION_HUMANA
                if es_sospechoso
                else EstadoCasoDeposito.EVIDENCIA_SUFICIENTE
            ),
            requiere_revision_humana=es_sospechoso,
            nota=NOTA_ART_59_FR_III_CFF if es_sospechoso else None,
        )

    def evaluar_casos_depositos_sospechosos(
        self,
        depositos: List[DepositoBancario],
        clasificaciones: List[ClasificacionDepositoResult],
    ) -> List[CasoDepositoSospechoso]:
        """Evalúa todos los depósitos clasificados de una conciliación
        (REQ-IVA-011). Ver ``evaluar_caso_deposito_sospechoso`` para la
        regla de negocio aplicada a cada uno.
        """
        depositos_por_id = {d.id: d for d in depositos}
        casos: List[CasoDepositoSospechoso] = []
        for clasificacion in clasificaciones:
            deposito = depositos_por_id.get(clasificacion.deposito_id)
            if deposito is None:
                continue
            casos.append(self.evaluar_caso_deposito_sospechoso(deposito, clasificacion))
        return casos

    def detectar_discrepancias(
        self,
        conciliacion: ConciliacionIngresosEgresos,
    ) -> List[DiscrepanciaFiscal]:
        """Find mismatches between bank deposits and auxiliary entries.

        Parameters
        ----------
        conciliacion : ConciliacionIngresosEgresos
            The reconciliation to analyze.

        Returns
        -------
        List[DiscrepanciaFiscal]
        """
        return conciliacion.discrepancias

    def _detectar_discrepancias(
        self,
        depositos: List[DepositoBancario],
        auxiliares: List[AuxiliarContable],
        clasificaciones: List[ClasificacionDepositoResult],
    ) -> List[DiscrepanciaFiscal]:
        """Internal: detect discrepancies between deposits and auxiliaries."""
        discrepancies: List[DiscrepanciaFiscal] = []

        # Build movement lookup by reference
        movimientos_by_ref: Dict[str, List[tuple]] = {}
        for aux in auxiliares:
            for mov in aux.movimientos:
                ref = mov.referencia.strip().upper()
                if ref:
                    movimientos_by_ref.setdefault(ref, []).append((aux, mov))

        # Check for deposits without matching auxiliary entries
        clas_map = {c.deposito_id: c for c in clasificaciones}
        for dep in depositos:
            ref = dep.referencia.strip().upper()
            if ref and ref not in movimientos_by_ref:
                clas = clas_map.get(dep.id)
                severity = Severidad.ALTA if clas and clas.clasificacion == ClasificacionDeposito.INGRESO else Severidad.MEDIA
                discrepancies.append(DiscrepanciaFiscal(
                    tipo=TipoDiscrepancia.FALTA_DOCUMENTACION,
                    deposito_id=dep.id,
                    monto_afectado=dep.monto,
                    descripcion=(
                        f"Depósito '{dep.id}' (monto: {dep.monto:.2f}, referencia: '{dep.referencia}') "
                        f"no tiene movimiento asociado en auxiliares contables."
                    ),
                    severidad=severity,
                ))

        # Check for amount mismatches on matched references
        for ref, mov_list in movimientos_by_ref.items():
            for dep in depositos:
                if dep.referencia.strip().upper() == ref:
                    for aux, mov in mov_list:
                        total_haber = mov.haber
                        if abs(dep.monto - total_haber) > 0.01:
                            discrepancies.append(DiscrepanciaFiscal(
                                tipo=TipoDiscrepancia.MONTO,
                                deposito_id=dep.id,
                                auxiliar_id=aux.cuenta_id,
                                monto_afectado=abs(dep.monto - total_haber),
                                descripcion=(
                                    f"Monto del depósito ({dep.monto:.2f}) difiere del "
                                    f"haber en auxiliar ({total_haber:.2f}) para referencia '{ref}'. "
                                    f"Diferencia: {abs(dep.monto - total_haber):.2f}."
                                ),
                                severidad=Severidad.MEDIA,
                            ))

        # Check for date mismatches
        for dep in depositos:
            ref = dep.referencia.strip().upper()
            if ref in movimientos_by_ref:
                for aux, mov in movimientos_by_ref[ref]:
                    if dep.fecha and mov.fecha and dep.fecha != mov.fecha:
                        discrepancies.append(DiscrepanciaFiscal(
                            tipo=TipoDiscrepancia.FECHA,
                            deposito_id=dep.id,
                            auxiliar_id=aux.cuenta_id,
                            monto_afectado=0.0,
                            descripcion=(
                                f"Fecha del depósito ({dep.fecha}) difiere de la fecha "
                                f"en auxiliar ({mov.fecha}) para referencia '{ref}'."
                            ),
                            severidad=Severidad.BAJA,
                        ))

        return discrepancies

    # -------------------------------------------------------------------
    # Step 3b: IVA balance
    # -------------------------------------------------------------------

    def calcular_balance_iva(
        self,
        declaraciones: List[dict],
        depositos_clasificados: List[ClasificacionDepositoResult],
        depositos: List[DepositoBancario],
    ) -> BalanceIVA:
        """Calculate IVA balance from declarations and classified deposits.

        Parameters
        ----------
        declaraciones : List[dict]
            Declaration data (iva_cobrado, iva_pagado, declarado).
        depositos_clasificados : List[ClasificacionDepositoResult]
            Classified deposits.
        depositos : List[DepositoBancario]
            Original deposits.

        Returns
        -------
        BalanceIVA
        """
        # Sum IVA from declarations
        iva_cobrado = sum(float(d.get("iva_cobrado", 0)) for d in declaraciones)
        iva_pagado = sum(float(d.get("iva_pagado", 0)) for d in declaraciones)
        declarado = sum(float(d.get("declarado", 0)) for d in declaraciones)

        # Calculate derived values
        iva_acreditable = max(0.0, iva_pagado - iva_cobrado)
        saldo_favor = max(0.0, iva_pagado - iva_cobrado)
        saldo_contra = max(0.0, iva_cobrado - iva_pagado)
        discrepancia = abs((iva_cobrado - iva_pagado) - declarado)

        return BalanceIVA(
            iva_cobrado=iva_cobrado,
            iva_pagado=iva_pagado,
            iva_acreditable=iva_acreditable,
            saldo_favor=saldo_favor,
            saldo_contra=saldo_contra,
            declarado=declarado,
            discrepancia=discrepancia,
        )

    # -------------------------------------------------------------------
    # Step 4: Generate working paper
    # -------------------------------------------------------------------

    def generar_papel_trabajo(
        self,
        conciliacion: ConciliacionIngresosEgresos,
        clasificaciones: List[ClasificacionDepositoResult],
        balance_iva: Optional[BalanceIVA] = None,
    ) -> PapelTrabajoConciliacion:
        """Generate a working paper for tax auditor review.

        Sections:
          1. Resumen (Summary)
          2. Clasificación de depósitos
          3. Conciliación bancaria vs contable
          4. Balance IVA
          5. Discrepancias
          6. Conclusiones

        Parameters
        ----------
        conciliacion : ConciliacionIngresosEgresos
            The reconciliation result.
        clasificaciones : List[ClasificacionDepositoResult]
            Classification results.
        balance_iva : Optional[BalanceIVA]
            IVA balance (optional).

        Returns
        -------
        PapelTrabajoConciliacion
        """
        # Build summary
        resumen = [
            SeccionResumen(
                titulo="Resumen de Conciliación",
                contenido=(
                    f"Período: {conciliacion.periodo or 'N/A'}. "
                    f"Total depósitos: {len(conciliacion.depositos)}. "
                    f"Total auxiliares: {len(conciliacion.auxiliares)}. "
                    f"Discrepancias: {len(conciliacion.discrepancias)}."
                ),
                total_depositos=len(conciliacion.depositos),
                total_auxiliares=len(conciliacion.auxiliares),
            ),
            SeccionResumen(
                titulo="Clasificación de Depósitos",
                contenido=self._resumen_clasificaciones(clasificaciones),
            ),
            SeccionResumen(
                titulo="Conciliación Bancaria vs Contable",
                contenido=(
                    f"Saldo bancario: ${conciliacion.saldo_bancario:,.2f}. "
                    f"Saldo contable: ${conciliacion.saldo_contable:,.2f}. "
                    f"Diferencia: ${conciliacion.diferencia:,.2f}."
                ),
            ),
        ]

        if balance_iva:
            resumen.append(SeccionResumen(
                titulo="Balance IVA",
                contenido=(
                    f"IVA cobrado: ${balance_iva.iva_cobrado:,.2f}. "
                    f"IVA pagado: ${balance_iva.iva_pagado:,.2f}. "
                    f"Saldo a favor: ${balance_iva.saldo_favor:,.2f}. "
                    f"Saldo en contra: ${balance_iva.saldo_contra:,.2f}. "
                    f"Declarado: ${balance_iva.declarado:,.2f}. "
                    f"Discrepancia: ${balance_iva.discrepancia:,.2f}."
                ),
            ))

        # Build conclusions
        conclusions: List[str] = []
        total_discrepancies = len(conciliacion.discrepancias)
        if total_discrepancies == 0:
            conclusions.append(
                "No se encontraron discrepancias. Los depósitos bancarios "
                "concilian con los auxiliares contables."
            )
        else:
            conclusions.append(
                f"Se encontraron {total_discrepancies} discrepancia(s) que "
                f"requieren revisión."
            )

        # Count by classification type
        by_type: Dict[str, int] = {}
        for c in clasificaciones:
            by_type[c.clasificacion.value] = by_type.get(c.clasificacion.value, 0) + 1
        for ctype, count in by_type.items():
            conclusions.append(f"Depósitos clasificados como '{ctype}': {count}.")

        if balance_iva and balance_iva.discrepancia > 0:
            conclusions.append(
                f"Existe discrepancia de ${balance_iva.discrepancia:,.2f} "
                f"en el balance de IVA declarado vs calculado."
            )

        # REQ-IVA-011 / ADR-4: depósitos sospechosos (sin documento de
        # soporte o con score bajo) bajo la presunción del Art. 59 fr. III
        # CFF nunca reducen ni niegan una devolución de IVA por sí solos —
        # solo se señalan para revisión humana, con la cita exacta del
        # criterio PRODECON 1/2026, dentro de las conclusiones del papel
        # de trabajo.
        casos_sospechosos = self.evaluar_casos_depositos_sospechosos(
            conciliacion.depositos, clasificaciones
        )
        casos_requieren_revision = [
            c for c in casos_sospechosos if c.requiere_revision_humana
        ]
        if casos_requieren_revision:
            ids_sospechosos = ", ".join(
                c.deposito_id for c in casos_requieren_revision if c.deposito_id
            )
            conclusions.append(
                f"{len(casos_requieren_revision)} depósito(s) sospechoso(s) "
                f"({ids_sospechosos}) requieren revisión humana antes de "
                f"sostener su clasificación ante una devolución de IVA: "
                f"{NOTA_ART_59_FR_III_CFF}."
            )

        requires_review = (
            any(c.requires_human_review for c in clasificaciones)
            or total_discrepancies > 0
            or bool(casos_requieren_revision)
        )

        papel = PapelTrabajoConciliacion(
            periodo=conciliacion.periodo,
            tenant_id=conciliacion.tenant_id,
            resumen=resumen,
            clasificaciones=clasificaciones,
            discrepancias=conciliacion.discrepancias,
            balanceiva=[balance_iva] if balance_iva else [],
            conclusiones=conclusions,
            requires_human_review=requires_review,
            created_at=datetime.now().isoformat(),
        )

        key = f"{conciliacion.periodo}_{conciliacion.tenant_id or 'default'}"
        self._papeles_trabajo[key] = papel

        return papel

    def get_papel_trabajo(self, periodo: str, tenant_id: Optional[str] = None) -> Optional[PapelTrabajoConciliacion]:
        """Retrieve a working paper by period and tenant."""
        key = f"{periodo}_{tenant_id or 'default'}"
        return self._papeles_trabajo.get(key)

    def generar_papel_trabajo_exportable(
        self,
        periodo: str,
        tenant_id: Optional[str] = None,
    ) -> "tuple[Optional[PapelTrabajoConciliacion], List[str]]":
        """Versión exportable del papel de trabajo (REQ-IVA-003): excluye
        toda clasificación que ``assert_puede_persistirse`` rechazaría —
        FINANCIAMIENTO/APORTACION_SOCIO/GARANTIA sin ``documento_soporte_id``
        real todavía (``estado_recaracterizacion="requiere_formalizacion"``,
        "pendiente_evidencia" en el criterio de aceptación).

        Consulta el estado MÁS RECIENTE de cada clasificación en el
        registro por id (``self._clasificaciones``) en vez de la foto
        tomada cuando se generó el papel original — así, adjuntar un
        documento después vía ``adjuntar_documento_soporte`` la vuelve
        exportable sin tener que re-conciliar el período completo.

        Parameters
        ----------
        periodo : str
            Período (YYYY-MM) del papel de trabajo.
        tenant_id : Optional[str]
            Tenant propietario del papel de trabajo.

        Returns
        -------
        (papel_exportable, excluidas_por_evidencia_pendiente)
            ``papel_exportable`` es ``None`` si no existe papel de trabajo
            para el período/tenant dados. ``excluidas_por_evidencia_pendiente``
            lista los ``deposito_id`` de las clasificaciones excluidas por
            falta de documento de soporte.
        """
        papel = self.get_papel_trabajo(periodo, tenant_id)
        if papel is None:
            return None, []

        incluidas: List[ClasificacionDepositoResult] = []
        excluidas: List[str] = []
        for clas_snapshot in papel.clasificaciones:
            actual = self._clasificaciones.get(clas_snapshot.id, clas_snapshot)
            if actual.puede_persistirse():
                incluidas.append(actual)
            else:
                excluidas.append(actual.deposito_id)

        papel_exportable = papel.model_copy(update={"clasificaciones": incluidas})
        return papel_exportable, excluidas

    def get_conciliacion(self, periodo: str, tenant_id: Optional[str] = None) -> Optional[ConciliacionIngresosEgresos]:
        """Retrieve a reconciliation by period and tenant."""
        key = f"{periodo}_{tenant_id or 'default'}"
        return self._conciliaciones.get(key)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _resumen_clasificaciones(self, clasificaciones: List[ClasificacionDepositoResult]) -> str:
        """Build a human-readable summary of classifications."""
        if not clasificaciones:
            return "No hay clasificaciones registradas."

        by_type: Dict[str, int] = {}
        for c in clasificaciones:
            by_type[c.clasificacion.value] = by_type.get(c.clasificacion.value, 0) + 1

        parts = [f"{count} depósito(s) como '{ctype}'" for ctype, count in by_type.items()]
        return "Clasificación: " + "; ".join(parts) + "."
