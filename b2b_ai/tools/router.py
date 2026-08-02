# -*- coding: utf-8 -*-
"""
router.py — Router que decide qué tool usar según el contexto.

Dado un intent (descripción de la tarea en lenguaje natural), el router
relaciona el texto con la tool más adecuada mediante patrones de palabras
clave. Devuelve la tool y la invoca. Es la pieza que convierte "el agente
decide qué tool llamar" en lógica determinística y testeable.
"""
from __future__ import annotations

from b2b_ai.tools.registry import get_tool, all_tools, call_tool
from b2b_ai.tools.logger import logger

# Mapa de patrones -> tool. Se revisa en orden; en empate gana la declarada
# primero, por eso las reglas específicas (FASE 2) van antes que las genéricas.
ROUTING_RULES = [
    # (patrones, tool_name, category)
    (["anomalia", "anomalías", "duplicado", "monto atipico", "atipico",
      "proveedor nuevo", "detectar anomalia", "riesgo factura"],
     "detect_anomalies", "anomaly"),
    (["aprobar", "aprobacion", "aprobación", "gate humano", "efirma",
      "e.firma", "requiere aprobacion"],
     "evaluate_approval", "approval"),
    (["estado de cuenta", "extracto", "parser de banco", "parsear banco",
      "parsear estado"],
     "parse_bank_statement", "reconcile"),
    (["reporte de conciliacion", "reporte de reconciliacion", "status conciliacion",
      "reporte de conciliación"],
     "reconciliation_report", "reconcile"),
    (["nomina", "isr", "imss", "infonavit", "sueldo", "payroll", "aguinaldo",
      "ptu"],
     "calculate_payroll", "payroll"),
    (["enviar balanza", "enviar al sat", "presentar al sat", "balanza sat"],
     "send_balance_to_sat", "accounting"),
    (["balanza", "catálogo de cuentas", "catalogo de cuentas", "cuenta contable"],
     "build_balance", "accounting"),
    (["parse", "leer", "extraer", "xml", "cfdi"], "parse_cfdi", "parse"),
    (["validar", "validacion", "validate", "fiscal"], "validate_cfdi", "validate"),
    (["clasificar", "classify", "categoria", "gasto", "cuenta"], "classify_expense", "classify"),
    (["erp", "registrar", "poliza", "contpaqi", "contabilidad"], "register_erp", "erp"),
    (["notificar", "email", "whatsapp", "aviso", "alertar", "notificacion"],
     "send_notification", "notify"),
    (["conciliar", "reconcili", "banco", "bancaria"], "reconcile_bank", "reconcile"),
    (["reporte", "report", "resumen", "metricas", "dashboard"], "generate_report", "report"),
]


def route(intent: str):
    """Devuelve el nombre de la tool que mejor encaja con el intent.

    Usa scoring: cada regla suma puntos por patrón coincidente; gana la de
    mayor puntaje (empate resuelto por orden de declaración). Esto evita que
    un término genérico como "cfdi"/"xml" gane sobre el verbo de acción.
    """
    text = (intent or "").lower()
    best_tool = None
    best_score = 0
    for patterns, tool_name, _cat in ROUTING_RULES:
        score = sum(1 for p in patterns if p in text)
        if score > best_score:
            best_score = score
            best_tool = tool_name
    return best_tool if best_score > 0 else None


def dispatch(intent: str, *, tenant_id=None, **kwargs):
    """
    Enruta el intent a una tool, la invoca y la registra en el logger.

    Devuelve {tool, intent, result, status}.
    """
    tool_name = route(intent)
    if tool_name is None:
        return {"tool": None, "intent": intent, "result": None,
                "status": "no_route",
                "message": "No se pudo determinar qué tool usar."}
    try:
        result = call_tool(tool_name, **kwargs)
        logger.log(tool_name, "dispatch", entity="intent", entity_id=intent,
                   payload=result, status="ok", tenant_id=tenant_id)
        return {"tool": tool_name, "intent": intent, "result": result,
                "status": "ok"}
    except Exception as e:
        logger.log(tool_name, "dispatch", entity="intent", entity_id=intent,
                   payload={"error": str(e)}, status="error", tenant_id=tenant_id)
        return {"tool": tool_name, "intent": intent, "result": None,
                "status": "error", "message": str(e)}


def list_routes():
    return [{"tool": t, "patterns": p} for p, t, _ in ROUTING_RULES]
