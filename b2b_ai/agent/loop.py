# -*- coding: utf-8 -*-
"""
loop.py — Loop de agente con LLM + decisión (FASE 4).

Orquesta el procesamiento de UNA factura de principio a fin con inteligencia
LLM y árbol de decisión explícito:

    recibir → validar → clasificar(LLM) → detectar anomalía
             → decidir → registrar(ERP) → notificar

Árbol de decisión (decision tree):

    parse falla        ─► escalate(parse_failed), NO registrar
    inválida           ─► escalate(invalid), NO registrar, notificar humano
    anomalía alerta    ─► escalate(anomaly), registrar con revisión (política)
    clasif. confianza baja
      / no mapeable    ─► según política:
                           - 'hold'          : escalar, NO registrar ERP
                           - 'auto_register' : registrar + revisión
    todo bien          ─► auto_processed: registrar ERP + notificar

Human-in-the-loop: toda escalada crea una fila en `reviews` (DB) para que un
contador la resuelva, y emite una notificación de revisión.

Sin API keys ni dependencias externas: el LLM es `LLMService` (mock por
defecto, fallback a reglas automático).
"""
from __future__ import annotations

import os

from b2b_ai.services.timeouts import (
    with_timeout, ServiceTimeoutError,
    TIMEOUT_SAT, TIMEOUT_LLM, TIMEOUT_ERP,
)

from b2b_ai.db.db import Database
from b2b_ai.db.tenants import TenantManager
from b2b_ai.services.llm import LLMService
from b2b_ai.services.classify import CATEGORIA_NOMBRE
from b2b_ai.tools.registry import call_tool
from b2b_ai.tools.logger import logger
import b2b_ai.tools.tools  # noqa: F401  (registra las tools del agente)
from b2b_ai.notifications.sender import EmailSender
from b2b_ai.monitoring.logger import mask_pii as _mask_pii

# Confidence threshold for auto-processing invoices
DEFAULT_CONFIDENCE_THRESHOLD = 0.7


class AgentLoop:
    """Loop de agente para una factura, con árbol de decisión y HITL."""

    def __init__(self, db=None, llm=None, tenants=None, erp=None,
                 email=None, logger_=None, notify=True):
        self.db = db or Database()
        self.logger = logger_ or logger
        if self.db is not None:
            self.logger.set_db(self.db)
        self.tenants = tenants or TenantManager(self.db)
        self.llm = llm or LLMService()
        self.erp = erp                    # override opcional
        self.email = email or EmailSender()
        self.notify = notify

    # ---- herramientas con auditoría --------------------------------------
    def _call(self, name, tenant_id, **kwargs):
        try:
            res = call_tool(name, **kwargs)
            self.logger.log(name, "agent_loop", entity="agent", entity_id=name,
                            payload=res, status="ok", tenant_id=tenant_id)
            return res
        except Exception as e:  # noqa: BLE001
            self.logger.log(name, "agent_loop", entity="agent", entity_id=name,
                            payload={"error": str(e)}, status="error",
                            tenant_id=tenant_id)
            raise

    def _llm_log(self, tenant_id, step, payload):
        self.logger.log(f"llm_{step}", "agent_loop", entity="agent",
                        entity_id=step, payload=payload, status="ok",
                        tenant_id=tenant_id)

    # ---- notificaciones ---------------------------------------------------
    def _send(self, tenant_id, event, context, channel):
        if not self.notify:
            return {"status": "skipped"}
        cfg = self.tenants.get_config(tenant_id)
        to = cfg.get("notif_recipient", "despacho@b2b-ai.local")
        try:
            return self._call("send_notification", tenant_id,
                              event_type=event, to=to, context=context,
                              channel=channel, email=self.email)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": str(e)}

    def _escalate(self, tenant_id, invoice_id, reason):
        """Crea una revisión humana pendiente y devuelve su id."""
        return self.db.create_review(tenant_id, invoice_id, reason)

    # ---- pipeline principal -----------------------------------------------
    def process(self, xml_path, tenant_id=None, send_notifications=None):
        """
        Procesa un CFDI y devuelve el resultado con la decisión tomada.
        `send_notifications` sobreescribe el flag self.notify si se pasa.
        """
        notify = self.notify if send_notifications is None else send_notifications
        self.notify = notify

        tenant_id = self._resolve_tenant(tenant_id)
        cfg = self.tenants.get_config(tenant_id)
        policy = cfg.get("policy_human_review", "hold")
        channel = cfg.get("notif_channel", "email")
        archivo = os.path.basename(xml_path)

        pasos = []
        review_id = None
        review_reason = None
        erp_res = None
        inv_id = None
        inserted = False

        def paso(nombre, ok, detalle=""):
            pasos.append({"paso": nombre, "ok": ok, "detalle": detalle})

        # 1) Recibir / parsear
        try:
            datos = self._call("parse_cfdi", tenant_id, xml_path=xml_path)
            paso("recibir", True)
        except Exception as e:  # noqa: BLE001
            paso("recibir", False, str(e))
            review_id = self._escalate(tenant_id, None, f"parse_failed: {e}")
            self._send(tenant_id, "invoice_parse_failed",
                       {"nombre": "Equipo", "archivo": archivo,
                        "error": str(e)}, channel)
            return self._result("parse_failed", archivo, pasos, review_id,
                                "No se pudo leer el CFDI.", erp_res, inv_id,
                                inserted, datos=None)

        # 2) Validar
        try:
            validacion = self._call("validate_cfdi", tenant_id, datos=datos)
        except Exception as e:  # noqa: BLE001
            validacion = {"ok": False, "requires_human_review": True,
                          "issues": [{"mensaje": str(e)}]}
        if not validacion.get("ok"):
            paso("validar", False)
            inv_id, inserted = self.db.insert_invoice(
                tenant_id, datos,
                {"categoria": "desconocido", "confianza": 0.0, "razon": ""},
                validacion)
            review_id = self._escalate(tenant_id, inv_id,
                                       "invalid: factura con errores de validación")
            self._send(tenant_id, "invoice_rejected",
                       {"nombre": "Equipo", "archivo": archivo,
                        "detalle": "; ".join(i["mensaje"] for i in
                                             validacion.get("issues", []))},
                       channel)
            return self._result("invalid", archivo, pasos, review_id,
                                "Factura inválida fiscalmente.", erp_res,
                                inv_id, inserted, datos, validacion)
        paso("validar", True)

        # 3) Clasificar (LLM con fallback a reglas)
        # SECURITY/LFPDPPP-06: Filter nomina data AND mask PII before
        # sending to external LLMs. Worker data (CURP, salary, deductions)
        # must not leave Mexico without consent.
        _SENSITIVE_KEYS = {"nomina", "curp", "rfc_receptor", "rfc_emisor"}
        datos_para_llm = {
            k: _mask_pii(v) if isinstance(v, str) else v
            for k, v in datos.items()
            if k not in _SENSITIVE_KEYS
        }
        try:
            clasif = with_timeout(
                self.llm.classify_invoice, TIMEOUT_LLM, "LLM"
            )(datos_para_llm)
        except ServiceTimeoutError:
            clasif = {"categoria": "desconocido", "confianza": 0.0,
                      "razon": "Timeout en LLM", "source": "timeout_fallback",
                      "requires_human_review": True}
        self._llm_log(tenant_id, "classify", clasif)
        paso("clasificar", True,
             f"{clasif['categoria']} ({clasif['source']})")

        # 4) Detectar anomalía
        try:
            anomalia = with_timeout(
                self.llm.detect_anomaly, TIMEOUT_LLM, "LLM"
            )(datos)
        except ServiceTimeoutError:
            anomalia = {"nivel": "normal", "anomalias": [],
                        "razon": "Timeout en LLM, asumiendo normal"}
        self._llm_log(tenant_id, "anomaly", anomalia)
        paso("anomalia", anomalia["nivel"] == "normal",
             anomalia["nivel"])

        # 5) Decidir
        # AG-1: Confidence gate — always hold if below threshold
        # HARD GATE: confianza < 0.50 SIEMPRE requiere revisión, sin importar policy
        _CONFIDENCE_FLOOR = 0.50
        if clasif.get("confianza", 0) < _CONFIDENCE_FLOOR:
            clasif["requires_human_review"] = True
        confidence_threshold = cfg.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)
        confianza = clasif.get("confianza", 0.0)
        low_confidence = confianza < confidence_threshold
        requiere_rev = (clasif.get("requires_human_review", False)
                        or anomalia["nivel"] == "alerta"
                        or low_confidence)
        decision = None
        if requiere_rev:
            paso("decidir", False, "requiere revisión humana")
            decision = "needs_review"
            if policy == "auto_register" and not low_confidence:
                erp_res = self._register(tenant_id, datos, clasif)
                inv_id, inserted = self.db.insert_invoice(
                    tenant_id, datos, clasif, validacion, erp=erp_res)
                review_reason = ("clasificación de baja confianza"
                                 if clasif.get("requires_human_review")
                                 else "anomalía detectada")
            else:  # 'hold' or low confidence gate
                erp_res = None
                inv_id, inserted = self.db.insert_invoice(
                    tenant_id, datos, clasif, validacion)
                review_reason = ("clasificación de baja confianza"
                                 if clasif.get("requires_human_review")
                                 else "anomalía detectada")
                if low_confidence:
                    review_reason = f"confianza ({confianza}) bajo umbral ({confidence_threshold})"
        else:
            paso("decidir", True, "auto")
            decision = "auto_processed"
            erp_res = self._register(tenant_id, datos, clasif)
            inv_id, inserted = self.db.insert_invoice(
                tenant_id, datos, clasif, validacion, erp=erp_res)

        # 6) Notificar (si aplica)
        notif = {"status": "skipped"}
        if decision != "parse_failed":
            evento = "invoice_review" if decision == "needs_review" \
                else "invoice_processed"
            ctx = {
                "nombre": "Equipo", "archivo": archivo,
                "folio": datos.get("folio_fiscal", archivo),
                "uuid": datos.get("folio_fiscal", archivo),
                "revision": "",
                "emisor": datos.get("emisor_nombre", ""),
                "monto": datos.get("total", ""),
                "categoria": CATEGORIA_NOMBRE.get(
                    clasif["categoria"], clasif["categoria"]),
                "razon": clasif.get("razon", ""),
                "confianza": clasif.get("confianza", 0),
                "fuente": clasif.get("source", ""),
                "anomalias": ", ".join(anomalia.get("anomalias", [])) or "ninguna",
            }
            notif = self._send(tenant_id, evento, ctx, channel)

        if decision == "needs_review":
            review_id = self._escalate(tenant_id, inv_id, review_reason)

        return self._result(decision, archivo, pasos, review_id, review_reason,
                            erp_res, inv_id, inserted, datos, validacion,
                            clasif, anomalia, notif)

    # ---- helpers ----------------------------------------------------------
    def _register(self, tenant_id, datos, clasif):
        invoice = dict(datos)
        invoice["categoria"] = clasif["categoria"]
        invoice["confianza"] = clasif["confianza"]
        erp = self.tenants.erp_factory(tenant_id, erp=self.erp)
        return self._call("register_erp", tenant_id, invoice=invoice, erp=erp)

    def _resolve_tenant(self, tenant_id):
        if tenant_id is not None:
            self.tenants.get_tenant(tenant_id)  # valida existencia
            return tenant_id
        tenants = self.db.list_tenants()
        if tenants:
            return tenants[0]["id"]
        return self.db.create_tenant("Despacho Demo", "")

    def _result(self, decision, archivo, pasos, review_id, review_reason,
                erp_res, inv_id, inserted, datos=None, validacion=None,
                clasif=None, anomalia=None, notif=None):
        return {
            "decision": decision,
            "archivo": archivo,
            "pasos": pasos,
            "review_id": review_id,
            "review_reason": review_reason,
            "erp": erp_res,
            "invoice_id": inv_id,
            "insertado": inserted,
            "datos": datos,
            "validacion": validacion,
            "clasificacion": clasif,
            "anomalia": anomalia,
            "notificacion": notif or {"status": "skipped"},
        }


def main():
    import sys
    import json
    from b2b_ai.db.tenants import onboard_tenant
    if len(sys.argv) < 2:
        print("Uso: python3 -m b2b_ai.agent.loop <archivo.xml> [tenant_id]")
        sys.exit(1)
    db = Database()
    tm = TenantManager(db)
    if not tm.exists(1):
        onboard_tenant(db, name="Despacho Demo", rfc="XAXX010101000")
    tid = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    res = AgentLoop(db=db).process(sys.argv[1], tenant_id=tid,
                                   send_notifications=False)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
