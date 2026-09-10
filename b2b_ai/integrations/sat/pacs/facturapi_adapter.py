# -*- coding: utf-8 -*-
"""facturapi_adapter.py — Adaptador REAL para el PAC FacturAPI.

HONESTIDAD OBLIGATORIA (mismo principio que CONTPAQI_VERIFICADO_CONTRA_REAL en
b2b_ai/computer_use/contpaqi_real_driver.py y que VERIFICADO_CONTRA_SAT_REAL en
sat_portal_rpa_driver.py):

    FACTURAPI_VERIFICADO_CONTRA_REAL = False

Este adaptador SÍ hace llamadas httpx reales al API público de FacturAPI
(https://www.facturapi.io/v2 — ver docs.facturapi.io/en/api/) cuando hay una
API key configurada, pero NUNCA se ha ejecutado contra una cuenta real de
FacturAPI en este entorno — sólo contra el simulador local de
`tests/fixtures/facturapi_simulator.py`. La primera vez que alguien lo corra
contra una cuenta real y confirme que timbrar/cancelar/consultar funcionan
tal cual, debe actualizar esta constante a True y documentarlo (ver
docs/integraciones/facturapi-pac-real.md) — bloqueo de negocio de Javier
(conseguir cuenta y API key reales), no de código.

Contrato real investigado (docs.facturapi.io/en/api/, sept-2026):
    - Base URL:      https://www.facturapi.io/v2
    - Auth:          Authorization: Bearer <api_key>  (sk_test_/sk_live_)
    - Timbrar:       POST   /invoices           -> 200 (o 202 si Facturapi
                      preserva la factura como "pending" por un error
                      intermitente del PAC/SAT del lado de Facturapi)
    - Cancelar:       DELETE /invoices/{id}?motive=NN[&substitution=<uuid>]
    - Consultar:      GET    /invoices/{id}
    - Errores:        4xx/5xx con JSON {"message","status","ok":false,
                      "code","errors":[...]}

TODO: endpoint no confirmado contra documentación real — no existe (o no se
pudo confirmar públicamente) un endpoint dedicado sólo a validar una API key
(tipo "organizations/me"/"whoami"). Por eso `connect()` NO hace ninguna
llamada de red: valida sólo que la API key esté presente y difiere la
validación real de las credenciales a la primera llamada real (timbrar,
cancelar o consultar), cuyo 401 se propaga honestamente si la key es
inválida. Si en el futuro se confirma un endpoint real para esto, debe
usarse aquí en vez de este TODO.

Capacidades que FacturAPI NO ofrece (ver `consultar_rfc` y
`contabilidad_electronica` abajo): FacturAPI es un PAC de timbrado de CFDI,
no un proveedor de consulta de estatus de RFC ante el SAT ni de envío de
Contabilidad Electrónica (balanza/catálogo/pólizas al buzón tributario). Esas
capacidades no aparecen en su documentación pública de API. Fabricar una
respuesta simulada para ellas sería peor que no implementarlas: se decidió
lanzar `NotImplementedError` explícito en vez de inventar un contrato falso.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from b2b_ai.infrastructure.structured_logging import mask_pii
from b2b_ai.integrations.sat.adapter import SATAdapter, SATAdapterError
from b2b_ai.integrations.sat.models import (
    CFDI,
    CFDIRequest,
    CancelacionRequest,
    CFDIStatus,
    ContabilidadElectronica,
    RFCStatus,
    TimbradoResponse,
)

logger = logging.getLogger(__name__)

# Ver disclaimer completo arriba: nunca se probó contra el servidor REAL de
# FacturAPI, sólo contra el simulador local de tests/fixtures/facturapi_simulator.py.
FACTURAPI_VERIFICADO_CONTRA_REAL = False

FACTURAPI_BASE_URL_DEFAULT = "https://www.facturapi.io/v2"

# Motivos de cancelación que FacturAPI/SAT reconocen para el query param
# `motive` de DELETE /invoices/{id} (01-04; no existe "05" en el contrato
# real investigado, aunque TipoCancelacion del modelo interno lo declare
# para otros PACs/flujos — no se inventa soporte para él aquí).
_MOTIVOS_FACTURAPI_VALIDOS = {"01", "02", "03", "04"}


class FacturapiAdapter(SATAdapter):
    """Adaptador REAL para el PAC FacturAPI (https://www.facturapi.io).

    Fail-closed: sin `FACTURAPI_API_KEY` (o `api_key` en config) configurada,
    el adaptador se declara `no_configurado` y ningún método de timbrado,
    cancelación o consulta hace ni simula una llamada — todos lanzan
    `SATAdapterError(code="NO_CONFIGURADO")`. Nunca se regresa una respuesta
    simulada como si fuera real.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        base_url: Optional[str] = None,
        http_client: Optional[Any] = None,
        timeout_seconds: float = 20.0,
    ):
        config = config or {
            "api_key": os.environ.get("FACTURAPI_API_KEY", ""),
            "pac_name": "facturapi",
        }
        super().__init__(name="facturapi", config=config)

        self._base_url = (
            base_url
            or os.environ.get("FACTURAPI_BASE_URL", "").strip()
            or FACTURAPI_BASE_URL_DEFAULT
        ).rstrip("/")
        self._timeout_seconds = timeout_seconds
        # Inyección de cliente httpx para pruebas: evita CUALQUIER llamada de
        # red real en la suite de tests (ver tests/fixtures/facturapi_simulator.py).
        self._injected_client = http_client
        self._owned_client: Optional[Any] = None

        api_key = str(self.config.get("api_key") or "").strip()
        self._configured = bool(api_key)

    # ------------------------------------------------------------------
    # Estado / configuración
    # ------------------------------------------------------------------
    @property
    def is_configured(self) -> bool:
        """True si hay una API key presente (no implica que sea válida)."""
        return self._configured

    def connect(self) -> bool:
        """Marca el adaptador como listo para operar, fail-closed.

        NO hace ninguna llamada de red (ver TODO en el docstring del módulo:
        no se confirmó un endpoint público de FacturAPI para validar
        solamente la API key). Si no hay API key configurada, el adaptador
        se declara `no_configurado` explícitamente y `connect()` regresa
        False; nunca se activa un "modo mock" que finja éxito.
        """
        if not self._configured:
            self._connected = False
            logger.warning(
                "%s: no_configurado — FACTURAPI_API_KEY vacío o ausente. "
                "Fail-closed: no se hará ninguna llamada real ni se simulará "
                "una respuesta exitosa.",
                self.name,
            )
            return False

        self._connected = True
        logger.info(
            "%s: connected (api_key configurada; base_url=%s). La validez "
            "real de la key se confirma en la primera llamada real, ver "
            "TODO en el módulo sobre endpoint de validación no confirmado.",
            self.name, self._base_url,
        )
        return True

    def disconnect(self) -> None:
        super().disconnect()
        if self._owned_client is not None:
            try:
                self._owned_client.close()
            except Exception:
                logger.debug("%s: error cerrando cliente httpx", self.name, exc_info=True)
            self._owned_client = None

    def _ensure_configured_and_connected(self) -> None:
        """Fail-closed: exige API key configurada Y connect() previo."""
        if not self._configured:
            raise SATAdapterError(
                f"Adaptador '{self.name}' no_configurado: falta FACTURAPI_API_KEY. "
                "No se realiza ninguna llamada real a FacturAPI ni se simula "
                "una respuesta exitosa (fail-closed).",
                code="NO_CONFIGURADO",
            )
        self._ensure_connected()

    def _client(self):
        """Cliente httpx.Client real (o inyectado en pruebas).

        Import perezoso de httpx (mismo patrón que pywinauto en
        contpaqi_rpa_backend.py): si httpx no está instalado, se convierte en
        un SATAdapterError explícito en vez de un ImportError críptico.
        """
        if self._injected_client is not None:
            return self._injected_client
        if self._owned_client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - dependencia declarada en pyproject
                raise SATAdapterError(
                    f"Adaptador '{self.name}': httpx no está instalado; no se puede "
                    "llamar al API real de FacturAPI.",
                    code="HTTPX_NO_DISPONIBLE",
                ) from exc
            api_key = str(self.config.get("api_key") or "")
            self._owned_client = httpx.Client(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout_seconds,
            )
        return self._owned_client

    @staticmethod
    def _parse_error_body(response) -> Dict[str, Any]:
        """Extrae {"message","code",...} del cuerpo de error real de FacturAPI.

        Nunca lanza: si el cuerpo no es el JSON documentado (p.ej. un 5xx sin
        cuerpo, o un proxy intermedio), regresa un mensaje genérico honesto
        en vez de fingir que sí se entendió la respuesta del PAC.
        """
        try:
            body = response.json()
        except Exception:
            return {
                "message": f"FacturAPI respondió {response.status_code} sin cuerpo JSON entendible.",
                "code": "RESPUESTA_NO_JSON",
            }
        if isinstance(body, dict):
            return {
                "message": body.get("message", f"Error {response.status_code} de FacturAPI."),
                "code": body.get("code", str(response.status_code)),
                "errors": body.get("errors", []),
            }
        return {
            "message": f"FacturAPI respondió {response.status_code}: {body!r}",
            "code": str(response.status_code),
        }

    def _do_request(self, method: str, path: str, **kwargs):
        """Envuelve la llamada httpx real; errores de red -> SATAdapterError.

        Un error real del PAC (4xx/5xx con cuerpo entendible) NO se convierte
        en excepción aquí — se deja que cada método público decida cómo
        reportarlo (TimbradoResponse.exito=False, dict con exito=False, o
        propagando el error en consultar_cfdi) para no perder el detalle real
        que mandó FacturAPI.
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise SATAdapterError(
                f"Adaptador '{self.name}': httpx no está instalado.",
                code="HTTPX_NO_DISPONIBLE",
            ) from exc
        client = self._client()
        try:
            return client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.error("%s: error de red llamando a FacturAPI (%s %s): %s",
                         self.name, method, path, exc)
            raise SATAdapterError(
                f"Error de red llamando a FacturAPI ({method} {path}): {exc}",
                code="NETWORK_ERROR",
            ) from exc

    # ------------------------------------------------------------------
    # Construcción del payload real de FacturAPI a partir de CFDIRequest
    # ------------------------------------------------------------------
    @staticmethod
    def _build_invoice_payload(cfdi_data: CFDIRequest) -> Dict[str, Any]:
        """Traduce CFDIRequest (modelo interno) al payload real de FacturAPI.

        Basado en el ejemplo documentado de POST /invoices (customer,
        items[].product, payment_form). FacturAPI calcula impuestos a partir
        del precio e ISR/IVA del producto en su propio motor de timbrado; el
        `iva`/`subtotal`/`total` que trae CFDIRequest son, para efectos de
        esta traducción, informativos del lado interno — se manda el total
        como precio único del concepto cuando no hay conceptos detallados,
        que es lo mínimo que el contrato real documentado requiere para
        timbrar.
        """
        conceptos = cfdi_data.conceptos or [{
            "description": "Servicios/productos facturados",
            "product_key": "01010101",
            "price": round(cfdi_data.subtotal, 2),
            "quantity": 1,
        }]
        items = []
        for c in conceptos:
            items.append({
                "quantity": c.get("cantidad", c.get("quantity", 1)),
                "product": {
                    "description": c.get("descripcion", c.get("description", "Concepto")),
                    "product_key": c.get("clave_prod_serv", c.get("product_key", "01010101")),
                    "price": round(float(c.get("valor_unitario", c.get("price", cfdi_data.subtotal))), 2),
                },
            })

        return {
            "customer": {
                "legal_name": cfdi_data.rfc_receptor,
                "tax_id": cfdi_data.rfc_receptor,
                "tax_system": cfdi_data.regimen_fiscal,
                "address": {"zip": cfdi_data.lugar_expedicion},
            },
            "items": items,
            "payment_form": cfdi_data.forma_pago,
            "use": cfdi_data.uso_cfdi,
            "series": cfdi_data.serie,
        }

    # ------------------------------------------------------------------
    # Timbrado / cancelación / consulta — llamadas REALES
    # ------------------------------------------------------------------
    def timbrar_cfdi(self, cfdi_data: CFDIRequest) -> TimbradoResponse:
        """Timbra un CFDI vía POST /invoices real de FacturAPI."""
        self._ensure_configured_and_connected()
        logger.info(
            "%s: timbrando CFDI rfc_emisor=%s rfc_receptor=%s",
            self.name, mask_pii(cfdi_data.rfc_emisor), mask_pii(cfdi_data.rfc_receptor),
        )
        payload = self._build_invoice_payload(cfdi_data)
        response = self._do_request("POST", "/invoices", json=payload)

        if response.status_code >= 400:
            detail = self._parse_error_body(response)
            logger.warning(
                "%s: FacturAPI rechazó el timbrado codigo=%s mensaje=%s",
                self.name, response.status_code, detail.get("message"),
            )
            return TimbradoResponse(
                exito=False,
                uuid="",
                fecha_timbrado="",
                codigo_response=str(response.status_code),
                mensaje=detail.get("message", "FacturAPI rechazó el timbrado."),
            )

        data = response.json()
        stamp = data.get("stamp") or {}
        exito = bool(data.get("uuid")) and data.get("status") != "canceled"
        return TimbradoResponse(
            exito=exito,
            uuid=data.get("uuid", "") or "",
            fecha_timbrado=stamp.get("date") or data.get("created_at", "") or "",
            codigo_response=str(response.status_code),
            mensaje="CFDI timbrado exitosamente." if exito else "FacturAPI aceptó la solicitud pero sin UUID (revisar status).",
            xml_timbrado=None,
            cadena_timbre=stamp.get("sat_seal"),
            sello_cfdi=stamp.get("cfdi_seal"),
            no_certificado_sat=stamp.get("sat_cert_number"),
        )

    def cancelar_cfdi(self, request: CancelacionRequest) -> Dict[str, Any]:
        """Cancela un CFDI vía DELETE /invoices/{id}?motive=NN real de FacturAPI.

        `request.uuid` se usa como el id del recurso de FacturAPI: el
        contrato real de la API identifica/cancela invoices por su `id`
        interno de FacturAPI (no directamente por el UUID fiscal del SAT) —
        para timbrados hechos por este mismo adaptador, `TimbradoResponse.uuid`
        es el UUID fiscal que FacturAPI expone en el invoice, así que en la
        práctica ambos coinciden para este flujo; si se integra con UUIDs
        fiscales obtenidos fuera de este adaptador, el llamador es
        responsable de resolverlos al id real de FacturAPI antes de llamar.
        """
        self._ensure_configured_and_connected()
        logger.info("%s: cancelando CFDI uuid=%s", self.name, request.uuid)

        motivo = request.motivo.value
        if motivo not in _MOTIVOS_FACTURAPI_VALIDOS:
            return {
                "exito": False,
                "uuid": request.uuid,
                "codigo_response": "400",
                "mensaje": (
                    f"Motivo de cancelación '{motivo}' no es válido para FacturAPI "
                    f"(valores aceptados: {sorted(_MOTIVOS_FACTURAPI_VALIDOS)})."
                ),
                "motivo": motivo,
            }

        params: Dict[str, str] = {"motive": motivo}
        if motivo == "01" and request.uuid_sustitucion:
            params["substitution"] = request.uuid_sustitucion

        response = self._do_request("DELETE", f"/invoices/{request.uuid}", params=params)

        if response.status_code >= 400:
            detail = self._parse_error_body(response)
            logger.warning(
                "%s: FacturAPI rechazó la cancelación codigo=%s mensaje=%s",
                self.name, response.status_code, detail.get("message"),
            )
            return {
                "exito": False,
                "uuid": request.uuid,
                "codigo_response": str(response.status_code),
                "mensaje": detail.get("message", "FacturAPI rechazó la cancelación."),
                "motivo": motivo,
            }

        data = response.json()
        status = data.get("status")
        cancellation_status = data.get("cancellation_status")
        exito = status == "canceled" or cancellation_status in ("accepted", "pending", "verifying")
        return {
            "exito": exito,
            "uuid": request.uuid,
            "codigo_response": str(response.status_code),
            "mensaje": (
                f"Cancelación {cancellation_status or status} en FacturAPI."
                if exito else "FacturAPI procesó la solicitud pero no confirmó la cancelación."
            ),
            "motivo": motivo,
            "cancellation_status": cancellation_status,
        }

    def consultar_cfdi(self, uuid: str) -> CFDI:
        """Consulta un CFDI vía GET /invoices/{id} real de FacturAPI.

        A diferencia de timbrar/cancelar (que regresan `exito: bool`), aquí
        el contrato de `SATAdapter.consultar_cfdi` exige devolver un `CFDI`
        — no hay una forma honesta de "devolver un CFDI vacío que no
        existe", así que un 404/4xx/5xx real de FacturAPI se propaga como
        `SATAdapterError` en vez de fabricar un CFDI con datos inventados.
        """
        self._ensure_configured_and_connected()
        logger.info("%s: consultando CFDI uuid=%s", self.name, uuid)

        response = self._do_request("GET", f"/invoices/{uuid}")

        if response.status_code >= 400:
            detail = self._parse_error_body(response)
            raise SATAdapterError(
                f"FacturAPI no pudo resolver el CFDI {uuid}: {detail.get('message')}",
                code=detail.get("code", str(response.status_code)),
                details=detail,
            )

        data = response.json()
        customer = data.get("customer") or {}
        total = float(data.get("total", 0.0) or 0.0)
        status_raw = data.get("status")
        status = CFDIStatus.CANCELADO if status_raw == "canceled" else (
            CFDIStatus.TIMBRADO if data.get("uuid") else CFDIStatus.PENDIENTE
        )
        return CFDI(
            uuid=data.get("uuid", "") or "",
            rfc_emisor=(data.get("organization") or {}).get("tax_id", ""),
            rfc_receptor=customer.get("tax_id", ""),
            fecha=(data.get("created_at") or "")[:10],
            subtotal=float(data.get("subtotal", 0.0) or 0.0),
            iva=max(total - float(data.get("subtotal", 0.0) or 0.0), 0.0),
            total=total,
            status=status,
            serie=data.get("series", ""),
            folio=str(data.get("folio_number", "")),
        )

    # ------------------------------------------------------------------
    # Capacidades que FacturAPI NO ofrece: honestidad, no simulación.
    # ------------------------------------------------------------------
    def consultar_rfc(self, rfc: str) -> RFCStatus:
        """FacturAPI no ofrece consulta de estatus de RFC ante el SAT.

        Esa capacidad (RFC activo/cancelado, régimen fiscal vigente,
        obligaciones) es un servicio del propio SAT (p. ej. "Valida tu RFC" /
        constancia de situación fiscal) o de proveedores especializados en
        validación de identidad fiscal — no del contrato público de API de
        un PAC de timbrado como FacturAPI (docs.facturapi.io/en/api/, revisado
        sept-2026). Fabricar una respuesta simulada aquí sería peor que no
        implementarla: se declara explícitamente no soportada.
        """
        logger.warning(
            "%s: consultar_rfc no soportado por FacturAPI (rfc=%s); "
            "lanzando NotImplementedError en vez de simular una respuesta.",
            self.name, mask_pii(rfc),
        )
        raise NotImplementedError(
            "FacturAPI (PAC de timbrado de CFDI) no ofrece consulta de estatus de "
            "RFC ante el SAT en su API pública. Esa capacidad pertenece al SAT "
            "directamente o a proveedores de validación de identidad fiscal, no "
            "a este PAC. No se simula una respuesta."
        )

    def contabilidad_electronica(self, datos: ContabilidadElectronica) -> Dict[str, Any]:
        """FacturAPI no ofrece envío de Contabilidad Electrónica al SAT.

        El envío de balanza de comprobación, catálogo de cuentas y pólizas al
        buzón tributario del SAT es un trámite del contribuyente ante el SAT
        (o de proveedores de software contable especializados), no una
        capacidad documentada del API pública de FacturAPI, que es un PAC de
        timbrado de CFDI (docs.facturapi.io/en/api/, revisado sept-2026).
        """
        logger.warning(
            "%s: contabilidad_electronica no soportado por FacturAPI "
            "(ejercicio=%s, mes=%s); lanzando NotImplementedError en vez de "
            "simular una respuesta.",
            self.name, datos.ejercicio, datos.mes,
        )
        raise NotImplementedError(
            "FacturAPI (PAC de timbrado de CFDI) no ofrece envío de Contabilidad "
            "Electrónica al SAT en su API pública. Ese trámite corresponde al "
            "contribuyente ante el SAT o a proveedores de software contable "
            "especializados, no a este PAC. No se simula una respuesta."
        )
