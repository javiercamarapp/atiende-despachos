# -*- coding: utf-8 -*-
"""
approval.py — Flujo de aprobación (gate humano) FASE 2.

Control de cuatro ojos sobre el registro contable de una factura. Reglas:
  - monto < umbral  -> auto-aprobado (sin intervención humana).
  - monto >= umbral -> requiere aprobación humana.
  - Por defecto el umbral es $50,000 MXN (configurable).

El gate humano es SIEMPRE obligatorio para pagos (tipo complemento de pago /
pago parcialidad) y, en general, para cualquier decisión que requiera
aprobación, se exige e.firma como control de autoría y autenticación
(firmar un acto de disposición de recursos).

Diseño (de `04-leyes-fiscales.md` / `03-proceso-completo.md`):
  - `evaluate()`       : decide auto-aprobado vs requiere aprobación y genera
                         la notificación (WhatsApp/email) cuando aplica.
  - `approve()/reject()`: registran la decisión con timestamp y responsable;
                         `approve` exige e.firma (gate duro).
  - `record_decision()`: bitácora en memoria de cada decisión (auditoría).

El ApprovalManager NO firma nada y no libera pagos: marca el estado para que
el flujo aguas abajo (ERP connector) solo registre la póliza cuando la
decisión es aprobada. Referencia legal de control interno / e.firma:
CFF Art. 17-D (e.firma) y buenas prácticas de control interno (Código de
Ética del IMCP / control de pagos).
"""
from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Dict, List, Optional

DEFAULT_AUTO_THRESHOLD = 50000  # $50,000 MXN
EFIRMA_NOTICE = ("Toda aprobación exige la e.firma del responsable como "
                 "control de autoría y autenticación.")


def _dec(v: Any) -> float:
    """Convierte a float de forma tolerante."""
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _is_payment(invoice: Dict[str, Any]) -> bool:
    """True si el comprobante es un pago (tipo P o complemento de pago)."""
    tipo = str(invoice.get("tipo") or "").upper()
    concepto = " ".join(
        str(c.get("descripcion", "")) for c in invoice.get("conceptos", [])
    ).lower()
    return tipo in ("P", "PAGO") or "complemento de pago" in concepto \
        or "pago parcialidad" in concepto


class ApprovalManager:
    """Gestiona el gate de aprobación de una factura antes de registrar en ERP."""

    def __init__(self, auto_threshold: float = DEFAULT_AUTO_THRESHOLD,
                 notifier: Optional[Any] = None) -> None:
        self.auto_threshold = float(auto_threshold)
        self.notifier = notifier  # MockWhatsApp / EmailSender (opcional)
        self.decisions: List[Dict[str, Any]] = []  # bitácora de decisiones (auditoría)

    # ---- Decisión ----
    def evaluate(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Evalúa si una factura se auto-aprueba o requiere aprobación humana.

        Devuelve dict {decision, amount, threshold, requires_approval,
        requires_efirma, reason, notification}.
        """
        amount = _dec(invoice.get("total") or invoice.get("monto"))
        is_payment = _is_payment(invoice)

        if is_payment:
            decision = "requires_approval"
            reason = "Comprobante de pago: el gate humano exige e.firma siempre."
        elif amount < self.auto_threshold:
            decision = "auto_approved"
            reason = f"Monto {amount:.2f} por debajo del umbral " \
                     f"{self.auto_threshold:.2f}."
        else:
            decision = "requires_approval"
            reason = f"Monto {amount:.2f} alcanza/rebasa el umbral " \
                     f"{self.auto_threshold:.2f}."

        requires_approval = decision == "requires_approval"
        requires_efirma = is_payment or requires_approval

        notification = None
        if requires_approval:
            notification = self._notify_approval(invoice, amount, reason)

        return {
            "decision": decision,
            "amount": round(amount, 2),
            "threshold": round(self.auto_threshold, 2),
            "requires_approval": requires_approval,
            "requires_efirma": requires_efirma,
            "efirma_notice": EFIRMA_NOTICE,
            "reason": reason,
            "notification": notification,
        }

    def _notify_approval(self, invoice: Dict[str, Any], amount: float,
                         reason: str) -> Dict[str, Any]:
        """Genera la notificación de aprobación pendiente (WhatsApp/email)."""
        folio = invoice.get("folio_fiscal") or ""
        emisor = invoice.get("emisor_nombre") or invoice.get("emisor_rfc") or ""
        text = (f"[Aprobacion pendiente] Factura {folio} de {emisor} por "
                f"${amount:.2f} requiere aprobacion. {EFIRMA_NOTICE}")
        if self.notifier is None:
            return {"status": "queued", "channel": "none", "message": text}
        # WhatsApp mock y EmailSender comparten la firma send_message/send.
        if hasattr(self.notifier, "send_message"):
            _default_to = os.environ.get("B2B_DEFAULT_EMAIL", "")
            res = self.notifier.send_message(_default_to, text,
                                             template_name="approval_required")
            return {"status": res.get("status", "sent"), "channel": "whatsapp",
                    "message": text, "detail": res}
        if hasattr(self.notifier, "send"):
            _default_to = os.environ.get("B2B_DEFAULT_EMAIL", "")
            res = self.notifier.send(_default_to,
                                     "Aprobación pendiente de factura", text)
            return {"status": res.get("status", "sent"), "channel": "email",
                    "message": text, "detail": res}
        return {"status": "queued", "channel": "none", "message": text}

    # ---- Acciones del humano ----
    def approve(self, invoice: Dict[str, Any], responsable: str,
                efirma_ok: bool = False, notes: str = "") -> Dict[str, Any]:
        """Aprueba la factura. Exige e.firma (gate duro). Devuelve dict."""
        ev = self.evaluate(invoice)
        if ev["requires_approval"] and not efirma_ok:
            return {
                "ok": False, "status": "blocked_efirma",
                "message": "Aprobación denegada: se requiere e.firma del "
                           "responsable para pagos/aprobaciones.",
                "decisions": self.record_decision(invoice, "blocked_efirma",
                                                  responsable, efirma_ok, notes),
            }
        decision = "approved"
        return {
            "ok": True, "status": "approved",
            "message": f"Factura aprobada por {responsable}.",
            "decisions": self.record_decision(invoice, decision, responsable,
                                              efirma_ok, notes),
        }

    def reject(self, invoice: Dict[str, Any], responsable: str,
               notes: str = "") -> Dict[str, Any]:
        """Rechaza la factura. Devuelve dict."""
        return {
            "ok": True, "status": "rejected",
            "message": f"Factura rechazada por {responsable}.",
            "decisions": self.record_decision(invoice, "rejected", responsable,
                                              False, notes),
        }

    def record_decision(self, invoice: Dict[str, Any], decision: str,
                        responsable: str, efirma_ok: bool = False,
                        notes: str = "") -> int:
        """Registra una decisión con timestamp y responsable. Devuelve el id."""
        record = {
            "id": len(self.decisions) + 1,
            "folio_fiscal": invoice.get("folio_fiscal") or "",
            "monto": _dec(invoice.get("total") or invoice.get("monto")),
            "decision": decision,
            "responsable": responsable,
            "efirma_ok": bool(efirma_ok),
            "notes": notes,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        self.decisions.append(record)
        return record["id"]

    def can_register(self, invoice: Dict[str, Any], decision: str) -> bool:
        """True si la decisión permite registrar la póliza en el ERP.

        Solo registra cuando la decisión es auto_approved o approved. Las
        decisiones requires_approval sin aprobar, blocked_efirma y rejected
        bloquean el registro.
        """
        return decision in ("auto_approved", "approved")
