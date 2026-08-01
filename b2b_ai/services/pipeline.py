# -*- coding: utf-8 -*-
"""
pipeline.py — Orquestador del pipeline completo del agente.

Flujo por CFDI (tool calling):
    parse_cfdi → validate_cfdi → classify_expense → register_erp
              → insert en DB (multi-tenant) → send_notification

Usa el framework de tools (router + registry + logger) para invocar cada paso,
de modo que TODAS las llamadas quedan en el audit_log. Acepta un solo archivo
o una carpeta (batch).
"""
from __future__ import annotations

import glob
import os

from b2b_ai.tools.registry import call_tool
from b2b_ai.tools.logger import logger
import b2b_ai.tools.tools  # noqa: F401  (registra las tools en el registry)
from b2b_ai.db.db import Database
from b2b_ai.erp.contpaqi import MockCONTPAQi
from b2b_ai.notifications.sender import EmailSender
from b2b_ai.services.classify import CATEGORIA_NOMBRE


def ensure_tenant(db: "Database", tenant_id: int | None = None, name: str = "Despacho Demo", rfc: str = "") -> int:
    """Devuelve un tenant_id existente (o crea el default)."""
    if tenant_id is not None:
        return tenant_id
    tenants = db.list_tenants()
    if tenants:
        return tenants[0]["id"]
    return db.create_tenant(name, rfc)


def _tool(name: str, logger_: "ToolCallLogger", tenant_id: int, **kwargs) -> dict:
    """Invoca una tool y la registra SIEMPRE en el audit_log."""
    try:
        result = call_tool(name, **kwargs)
        logger_.log(name, "pipeline", entity="pipeline", entity_id=name,
                    payload=result, status="ok", tenant_id=tenant_id)
        return result
    except Exception as e:  # noqa: BLE001
        logger_.log(name, "pipeline", entity="pipeline", entity_id=name,
                    payload={"error": str(e)}, status="error", tenant_id=tenant_id)
        raise


def process_file(xml_path: str, db: "Database | None" = None, tenant_id: int | None = None, erp: "MockCONTPAQi | None" = None, email: "EmailSender | None" = None,
                 logger_: "ToolCallLogger | None" = None) -> dict:
    """Procesa un solo CFDI por el pipeline de tools. Devuelve dict-resumen."""
    db = db or Database()
    erp = erp or MockCONTPAQi()
    logger_ = logger_ or logger
    if db is not None:
        logger_.set_db(db)
        tenant_id = ensure_tenant(db, tenant_id)

    archivo = os.path.basename(xml_path)

    # 1. Parse
    datos = _tool("parse_cfdi", logger_, tenant_id, xml_path=xml_path)

    # 2. Validate
    validacion = _tool("validate_cfdi", logger_, tenant_id, datos=datos)

    # 2b. PII detection (protección de datos) — escanea el CFDI en busca de
    # RFC/CURP/email/teléfono/cuentas y lo añade al resultado para audit.
    from b2b_ai.api.security import detect_pii
    pii = detect_pii(datos)

    # 2c. Verificación 69-B EFOS (CFF art. 69-B)
    from b2b_ai.sat.efos_69b import EFOSChecker
    efos = EFOSChecker().validate_cfdi_emisor(datos)
    if efos.get("en_lista_69b"):
        # El emisor está en la lista 69-B: registrar como issue crítico
        # pero NO bloquear (requiere revisión humana para acreditar materialidad)
        validacion["issues"].extend(efos.get("issues", []))
        validacion["warnings"].append(
            "ALERTA 69-B: Emisor en lista definitiva del art. 69-B CFF. "
            "Requiere acreditamiento de materialidad o la operación no "
            "produce efecto fiscal (CFF art. 69-B tercer párrafo)."
        )

    # 2d. Verificación de estatus CFDI ante SAT (vigente/cancelado)
    from b2b_ai.sat.validator import SATValidator
    sat_validator = SATValidator(db=db, tenant_id=tenant_id)
    folio_fiscal = datos.get("folio_fiscal", "")
    sat_status = {"checked": False}
    if folio_fiscal:
        sat_status = sat_validator.check_status(folio_fiscal)
        sat_status["checked"] = True
        if sat_status.get("estado") == "cancelado":
            validacion["ok"] = False
            validacion["issues"].append({
                "code": "cfdi_cancelado",
                "mensaje": (
                    f"El CFDI con folio fiscal {folio_fiscal} fue CANCELADO "
                    "según el SAT. Un comprobante cancelado no produce efecto "
                    "fiscal (deducción ni acreditamiento de IVA)."
                ),
                "ref": "CFF art. 29-A, Regla 2.7.1.39 RMF",
                "severidad": "error",
            })

    # 3. Classify
    clasif = _tool("classify_expense", logger_, tenant_id, datos=datos)

    # 3b. Anomaly detection (FASE 2) — después de clasificar
    invoice = dict(datos)
    invoice["categoria"] = clasif["categoria"]
    invoice["confianza"] = clasif["confianza"]
    historico = db.list_invoices(tenant_id=tenant_id, limit=200) \
        if db is not None and tenant_id else []
    anomalias = _tool("detect_anomalies", logger_, tenant_id,
                      invoice=invoice, historical=historico)

    # 3c. Approval flow (FASE 2) — gate humano ANTES de registrar en ERP
    aprobacion = _tool("evaluate_approval", logger_, tenant_id,
                       invoice=invoice)
    if not validacion.get("ok"):
        erp_res = {"ok": False, "poliza": None, "status": "rejected_invalid_cfdi"}
    elif aprobacion["decision"] in ("auto_approved", "approved"):
        erp_res = _tool("register_erp", logger_, tenant_id,
                        invoice=invoice, erp=erp)
    else:
        erp_res = {
            "ok": False, "poliza": None, "status": "pending_approval",
            "message": ("Requiere aprobación humana antes de registrar la "
                        f"póliza en ERP. Decisión: {aprobacion['decision']}."),
            "decision": aprobacion["decision"],
        }

    # 5. Persistir en DB
    inv_id, inserted = db.insert_invoice(
        tenant_id, datos, clasif, validacion, erp=erp_res)

    # 6. Notificación (si aplica; no bloquea el pipeline)
    notif = {"status": "skipped"}
    try:
        if validacion.get("ok"):
            event = "invoice_processed"
            ctx = {
                "nombre": "Equipo", "folio": datos.get("folio_fiscal", archivo)[:12],
                "emisor": datos.get("emisor_nombre", ""),
                "monto": datos.get("total", ""),
                "categoria": CATEGORIA_NOMBRE.get(clasif["categoria"],
                                                  clasif["categoria"]),
                "razon": clasif.get("razon", ""),
                "uuid": datos.get("folio_fiscal", ""),
                "revision": ("\nRequiere revisión humana por excepción.\n"
                             if (not validacion.get("ok")
                                 or validacion.get("requires_human_review"))
                             else ""),
            }
            notif = _tool("send_notification", logger_, tenant_id,
                          event_type=event, to="despacho@b2b-ai.local",
                          context=ctx, email=email or EmailSender())
            if db is not None:
                db.insert_notification(tenant_id, event,
                                       notif.get("status") == "sent" and "email" or "email",
                                       "despacho@b2b-ai.local",
                                       notif.get("subject", ""),
                                       notif.get("message", ""),
                                       status=notif.get("status", "sent"))
    except Exception as e:  # noqa: BLE001
        notif = {"status": "error", "message": str(e)}

    return {
        "archivo": archivo,
        "datos": datos,
        "validacion": validacion,
        "clasificacion": clasif,
        "anomalias": anomalias,
        "aprobacion": aprobacion,
        "erp": erp_res,
        "invoice_id": inv_id,
        "insertado": inserted,
        "tenant_id": tenant_id,
        "notificacion": notif,
        "pii": pii,
        "efos_69b": efos,
        "sat_status": sat_status,
    }


def process_batch(folder, db=None, tenant_id=None, pattern="*.xml"):
    """Procesa todos los CFDI de una carpeta. Devuelve lista de resúmenes."""
    archivos = sorted(glob.glob(os.path.join(folder, pattern)))
    results = []
    for f in archivos:
        results.append(process_file(f, db=db, tenant_id=tenant_id))
    return results


def summarize(results):
    ok = sum(1 for r in results if r["validacion"]["ok"])
    inserted = sum(1 for r in results if r["insertado"])
    from collections import Counter
    cats = Counter(r["clasificacion"]["categoria"] for r in results)
    return {
        "procesadas": len(results),
        "validas": ok,
        "con_observaciones": len(results) - ok,
        "insertadas": inserted,
        "por_categoria": dict(cats),
    }
