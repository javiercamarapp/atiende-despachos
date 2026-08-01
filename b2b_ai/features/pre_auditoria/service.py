# -*- coding: utf-8 -*-
"""
service.py — Servicio de Pre-Auditoría Contable.

Ejecuta un escaneo pre-audit sobre la contabilidad de un tenant, verificando:
  - Deducibilidad de gastos (Art. 28 y 105 LISR)
  - Consistencia del libro de contabilidad
  - Cumplimiento del CFF (Código Fiscal de la Federación)
"""
from __future__ import annotations

from typing import Any, Optional

from b2b_ai.features.pre_auditoria.models import (
    AuditFinding,
    AuditReport,
    DeductibilityCheck,
    Severity,
)

# ---------------------------------------------------------------------------
# Catálogo de gastos NO deducibles (Art. 28 LISR)
# ---------------------------------------------------------------------------
NON_DEDUCTIBLE_CONCEPTS = {
    "multas", "recargos", "penalizaciones", "propinas",
    "gastos personales", "donativos", "aportaciones",
    "multas sat", "infracciones", "gastos de representación excesivos",
}

# Artículos CFF relevantes
CFF_ARTICLES = {
    "deducibilidad": "Art. 28 LISR",
    "no_deducibilidad": "Art. 28 LISR",
    "informacion": "Art. 28 Fracc. III LISR",
    "cfdi_obligatorio": "Art. 29 CFF",
    "registros_contables": "Art. 28 Fracc. II LISR",
    "conservacion": "Art. 46 CFF",
}


def check_deductibility(invoices: list[dict]) -> list[DeductibilityCheck]:
    """Verifica si cada gasto es deducible según el Art. 28 LISR.

    Acepta una lista de diccionarios con al menos:
        invoice_id, concepto, monto, categoria (opcional).

    Retorna una lista de DeductibilityCheck por cada factura.
    """
    results = []
    for inv in invoices:
        concepto = (inv.get("concepto") or "").lower().strip()
        es_deducible = True
        razon = "Gasto deducible"
        articulo = CFF_ARTICLES["deducibilidad"]

        for nd in NON_DEDUCTIBLE_CONCEPTS:
            if nd in concepto:
                es_deducible = False
                razon = f"Concepto '{inv.get('concepto')}' clasificado como no deducible"
                articulo = CFF_ARTICLES["no_deducibilidad"]
                break

        # Verificar monto excesivo sin soporte (regla simplificada > $50,000)
        monto = inv.get("monto", 0)
        try:
            monto = float(monto)
        except (TypeError, ValueError):
            monto = 0.0
        if monto > 50_000 and es_deducible:
            razon += " (requiere documentación de soporte adicional)"
            articulo = CFF_ARTICLES["informacion"]

        results.append(DeductibilityCheck(
            invoice_id=str(inv.get("invoice_id", "")),
            concepto=inv.get("concepto", ""),
            es_deducible=es_deducible,
            razon=razon,
            articulo_cff=articulo,
        ))
    return results


def check_consistency(ledger: list[dict]) -> list[AuditFinding]:
    """Verifica consistencia del libro de contabilidad.

    Reglas verificadas:
      1. Cada asiento debe tener debe == haber (partida doble).
      2. Fechas no deben ser futuras.
      3. Cuentas no deben tener saldos vacíos.
      4. Descripción obligatoria en cada movimiento.
    """
    findings = []
    from datetime import date

    today = date.today()

    # 1) Partida doble
    for asiento in ledger:
        debe = float(asiento.get("debe", 0) or 0)
        haber = float(asiento.get("haber", 0) or 0)
        if abs(debe - haber) > 0.01:
            findings.append(AuditFinding(
                category="partida_doble",
                severity=Severity.CRITICAL,
                description=(
                    f"Asiento {asiento.get('id', '?')}: debe (${debe:.2f}) "
                    f"≠ haber (${haber:.2f})"
                ),
                recommendation="Revisar y corregir el asiento para cuadrar debe/haber.",
            ))

        # 2) Fecha futura
        fecha = asiento.get("fecha", "")
        if fecha and fecha > today.isoformat():
            findings.append(AuditFinding(
                category="fecha_futura",
                severity=Severity.HIGH,
                description=f"Asiento {asiento.get('id', '?')} tiene fecha futura: {fecha}",
                recommendation="Verificar la fecha del asiento antes de cerrar el periodo.",
            ))

        # 3) Cuenta vacía
        cuenta_deb = (asiento.get("cuenta_debito") or "").strip()
        cuenta_cred = (asiento.get("cuenta_credito") or "").strip()
        if not cuenta_deb or not cuenta_cred:
            findings.append(AuditFinding(
                category="cuenta_incompleta",
                severity=Severity.HIGH,
                description=(
                    f"Asiento {asiento.get('id', '?')}: cuenta de "
                    f"{'débito' if not cuenta_deb else 'crédito'} vacía"
                ),
                recommendation="Asignar cuentas contables a todos los movimientos.",
            ))

        # 4) Descripción
        desc = (asiento.get("descripcion") or "").strip()
        if not desc:
            findings.append(AuditFinding(
                category="sin_descripcion",
                severity=Severity.MEDIUM,
                description=f"Asiento {asiento.get('id', '?')}: sin descripción",
                recommendation="Agregar descripción para trazabilidad.",
            ))

    return findings


def check_cff_compliance(data: dict) -> list[AuditFinding]:
    """Verifica compliance con el CFF.

    Recibe un dict con:
        rfc, cfdi_count, tiene_contabilidad_electronica, periodos_cerrados.
    """
    findings = []
    rfc = data.get("rfc", "")
    cfdi_count = data.get("cfdi_count", 0)
    tiene_ce = data.get("tiene_contabilidad_electronica", False)
    periodos = data.get("periodos_cerrados", [])

    # RFC válido (12 o 13 caracteres)
    if not rfc or len(rfc) < 12:
        findings.append(AuditFinding(
            category="rfc_invalido",
            severity=Severity.CRITICAL,
            description=f"RFC inválido o ausente: '{rfc}'",
            recommendation="Registrar un RFC válido (12-13 caracteres) en la configuración del tenant.",
        ))

    # CFDI obligatorio (Art. 29 CFF)
    if cfdi_count == 0:
        findings.append(AuditFinding(
            category="sin_cfdi",
            severity=Severity.HIGH,
            description="No se encontraron CFDI registrados para este tenant.",
            recommendation="Emitir CFDI por cada operación (Art. 29 CFF).",
        ))

    # Contabilidad electrónica (Art. 28 Fracc. II)
    if not tiene_ce:
        findings.append(AuditFinding(
            category="sin_ce",
            severity=Severity.MEDIUM,
            description="El tenant no tiene contabilidad electrónica configurada.",
            recommendation="Configurar balanza y catálogo de cuentas SAT.",
        ))

    # Periodos cerrados
    if not periodos:
        findings.append(AuditFinding(
            category="sin_periodos",
            severity=Severity.MEDIUM,
            description="No hay periodos cerrados registrados.",
            recommendation="Cerrar y presentar periodos mensuales ante el SAT.",
        ))

    return findings


def generate_audit_report(findings: list[AuditFinding],
                          period: str = "",
                          tenant_id: Optional[int] = None) -> AuditReport:
    """Genera un reporte de auditoría a partir de los hallazgos.

    Calcula un score (100 = sin hallazgos; cada hallazgo resta puntos
    según su severidad).
    """
    severity_weights = {
        Severity.CRITICAL: 25,
        Severity.HIGH: 15,
        Severity.MEDIUM: 8,
        Severity.LOW: 3,
    }

    deductions = sum(severity_weights.get(f.severity, 0) for f in findings)
    score = max(0.0, 100.0 - deductions)

    # Resumen ejecutivo
    if not findings:
        summary = "Sin hallazgos. La contabilidad está lista para auditoría."
    else:
        counts = {}
        for f in findings:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
        parts = [f"{v} {k}" for k, v in counts.items()]
        summary = (
            f"{len(findings)} hallazgo(s): {', '.join(parts)}. "
            f"Score: {score:.0f}/100."
        )

    return AuditReport(
        period=period,
        tenant_id=tenant_id,
        findings=findings,
        score=score,
        summary=summary,
    )


def run_pre_audit(tenant_id: int,
                   period: str,
                   invoices: Optional[list[dict]] = None,
                   ledger: Optional[list[dict]] = None,
                   cff_data: Optional[dict] = None) -> AuditReport:
    """Ejecuta una pre-auditoría completa.

    Combina deducibilidad, consistencia y compliance CFF en un solo reporte.
    """
    all_findings: list[AuditFinding] = []

    # 1) Deducibilidad
    if invoices:
        checks = check_deductibility(invoices)
        for dc in checks:
            if not dc.es_deducible:
                all_findings.append(AuditFinding(
                    category="no_deducible",
                    severity=Severity.HIGH,
                    description=(
                        f"Factura {dc.invoice_id}: {dc.concepto} — {dc.razon}"
                    ),
                    recommendation=f"Revisar deducibilidad ({dc.articulo_cff}).",
                ))

    # 2) Consistencia contable
    if ledger:
        all_findings.extend(check_consistency(ledger))

    # 3) Compliance CFF
    if cff_data:
        all_findings.extend(check_cff_compliance(cff_data))

    return generate_audit_report(
        findings=all_findings,
        period=period,
        tenant_id=tenant_id,
    )
