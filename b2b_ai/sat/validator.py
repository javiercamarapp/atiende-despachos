# -*- coding: utf-8 -*-
"""
validator.py — Verificación REAL de estatus de CFDI ante el SAT (FIS-024).

`SATValidator` consulta el estatus de un CFDI (Vigente / Cancelado / No
encontrado) contra el servicio público y gratuito del SAT "Verificación de
Comprobantes Fiscales Digitales por Internet" (no requiere e.firma ni CIEC):

    WSDL:      https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc?wsdl
    Operación: Consulta(expresionImpresa: string) -> ConsultaResponse

HONESTIDAD OBLIGATORIA (mismo principio que FACTURAPI_VERIFICADO_CONTRA_REAL
en b2b_ai/integrations/sat/pacs/facturapi_adapter.py y que
VERIFICADO_CONTRA_SAT_REAL en sat_portal_rpa_driver.py):

    SAT_VALIDATOR_VERIFICADO_CONTRA_REAL = False

Este módulo SÍ hace (o intenta hacer, según lo que se le inyecte) una llamada
SOAP real vía httpx contra el WSDL de arriba, pero **nunca se ha ejecutado
contra el servicio real del SAT**. Todas las pruebas de este módulo corren
exclusivamente contra el simulador local
`tests/fixtures/sat_consulta_cfdi_simulator.py` (mismo patrón que
`tests/fixtures/facturapi_simulator.py` para FacturAPI) — ninguna prueba toca
`consultaqr.facturaelectronica.sat.gob.mx`. La primera vez que alguien lo
corra contra el WSDL real del SAT con un CFDI real y confirme que el
contrato (namespaces, campos, códigos) coincide tal cual, debe actualizar
`SAT_VALIDATOR_VERIFICADO_CONTRA_REAL` a True y documentarlo.

Cada dict que este módulo devuelve incluye explícitamente:
    "simulado": False                        — nunca fabrica un resultado;
                                                "vigente"/"cancelado" solo se
                                                devuelve si vino de una
                                                llamada de red real que se
                                                completó y se pudo parsear.
    "verificado_contra_real": <constante>    — ver arriba.

VERSIÓN DE ESPECIFICACIÓN ASUMIDA (ver docs/CONTRATO-SAT-INTEGRACION-REAL.md
§1, que advertía explícitamente confirmar la versión vigente 1.2/1.3/1.4
antes de fijar el parseo en vez de copiarlo sin revalidar):

    Se confirmó, con acceso a internet real durante esta tarea (sept-2026),
    que sat.gob.mx sirve HOY tres versiones del PDF "Documentación del
    Servicio de Consulta de CFDI":
      - v1.2 (oct-2018): omawww.sat.gob.mx/.../DocumentacionWSConsulta_CFDIv1-2.pdf
      - v1.3 (nov-2020, Last-Modified jul-2025 en el servidor):
        www.sat.gob.mx/minisitio/Factura/documentos/cancelacion/ar_consulta_cfdi.pdf
      - v1.4 (nov-2022, Last-Modified jun-2026 en el servidor — la copia
        servida más recientemente tocada de las tres):
        omawww.sat.gob.mx/.../Documentacion_WS_Consulta_CFDI_v1.4.pdf
    Se leyó el PDF completo de v1.4 (18 páginas): trae el WSDL/XSD íntegro
    (namespaces, WSDL "Contrato" §2, incluido el bloque `<xs:complexType
    name="Acuse">` literal) y la tabla completa de códigos de respuesta EFOS
    (100-104, 200, 201) que v1.3 no documenta con el mismo detalle. Se asume
    **v1.4** como la versión vigente por ser la más completa y la de
    Last-Modified más reciente entre las tres copias activas; el contrato
    SOAP en sí (WSDL, namespaces, nombres de campos de `Acuse`) es idéntico
    entre v1.3 y v1.4 en las páginas verificadas — la diferencia es la
    documentación de códigos EFOS. Si en el futuro se confirma que otra
    versión es la oficialmente vigente, el parseo de
    Estado/EsCancelable/EstatusCancelacion/CodigoEstatus/ValidacionEFOS no
    debería cambiar (son los mismos 5 campos, mismos namespaces, en las 3
    versiones revisadas), pero los mensajes de CodigoEstatus/EFOS sí podrían.

Contrato SOAP confirmado directamente del WSDL real (targetNamespace
`http://tempuri.org/`, operación `Consulta`, soapAction
`http://tempuri.org/IConsultaCFDIService/Consulta`, SOAP 1.1 doc/literal):

    <xs:element name="Consulta">
      <xs:complexType><xs:sequence>
        <xs:element name="expresionImpresa" type="xs:string" minOccurs="0" nillable="true"/>
      </xs:sequence></xs:complexType>
    </xs:element>

    <xs:element name="ConsultaResponse">
      <xs:complexType><xs:sequence>
        <xs:element name="ConsultaResult" type="q1:Acuse" minOccurs="0" nillable="true"/>
      </xs:sequence></xs:complexType>
    </xs:element>

    <!-- namespace de Acuse: http://schemas.datacontract.org/2004/07/Sat.Cfdi.Negocio.ConsultaCfdi.Servicio -->
    <xs:complexType name="Acuse"><xs:sequence>
      <xs:element name="CodigoEstatus" type="xs:string" minOccurs="0" nillable="true"/>
      <xs:element name="EsCancelable" type="xs:string" minOccurs="0" nillable="true"/>
      <xs:element name="Estado" type="xs:string" minOccurs="0" nillable="true"/>
      <xs:element name="EstatusCancelacion" type="xs:string" minOccurs="0" nillable="true"/>
      <xs:element name="ValidacionEFOS" type="xs:string" minOccurs="0" nillable="true"/>
    </xs:sequence></xs:complexType>

Decisión de diseño no trivial (resuelve el "(C) Decisión pendiente" del
contrato): `check_status()` ahora requiere `rfc_emisor`, `rfc_receptor` y
`total` además de `folio_fiscal` — son obligatorios para construir
`expresionImpresa` tal como exige el servicio real (campos `re`/`rr`/`tt`/
`id`). Se optó por pedirlos como parámetros explícitos del llamador (y no
por resolverlos automáticamente contra `self.db`, cuyo esquema para eso no
está confirmado ni es responsabilidad de este módulo) — ver docstring de
`check_status`. Los llamadores que ya tenían esos datos a mano
(`SATScheduler.run_weekly()`, `b2b_ai.services.pipeline`, el endpoint
`/api/v1/sat/verify`) se actualizaron en este mismo cambio para pasarlos; un
llamador que solo tenga el folio recibe un `ok: False` fail-closed
explícito, nunca un estatus inventado.

`verify_rfc()` permanece como validación de FORMATO únicamente: no existe un
servicio público del SAT para verificar la existencia de un RFC de terceros
(ver docs/CONTRATO-SAT-INTEGRACION-REAL.md §1, "Validación de RFC") — se
documenta así en vez de fabricar una respuesta.

`verify_chain()` ya NO fabrica una lista de eventos de "cadena de custodia"
(el mock anterior inventaba Timbrado/Registro SAT/Consulta con la fecha de
`datetime.now()` sin relación con ningún dato real). Se redefinió, como
sugiere el contrato, como la consulta de estatus real más — si el llamador
lo tiene — el acuse de timbrado que ya emitió el PAC; nunca inventa eventos.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

from b2b_ai.common.rfc import is_valid_rfc

logger = logging.getLogger("b2b_ai.sat.validator")

# Ver disclaimer completo arriba: nunca se probó contra el WSDL REAL del SAT,
# solo contra el simulador local de
# tests/fixtures/sat_consulta_cfdi_simulator.py.
SAT_VALIDATOR_VERIFICADO_CONTRA_REAL = False

# Versión de la especificación asumida para el parseo del XML de respuesta —
# ver docstring del módulo ("VERSIÓN DE ESPECIFICACIÓN ASUMIDA").
SAT_CONSULTA_CFDI_SPEC_VERSION_ASUMIDA = "1.4 (noviembre 2022)"

SAT_CONSULTA_CFDI_BASE_URL_DEFAULT = "https://consultaqr.facturaelectronica.sat.gob.mx"
SAT_CONSULTA_CFDI_PATH = "/ConsultaCFDIService.svc"
SAT_CONSULTA_CFDI_SOAP_ACTION = "http://tempuri.org/IConsultaCFDIService/Consulta"

# Namespaces reales confirmados en el WSDL (ver docstring del módulo).
_NS_TEMPURI = "http://tempuri.org/"
_NS_SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"

# CodigoEstatus documentados (ver PDF v1.4 §3 "Mensajes de Respuesta").
_CODIGO_RECHAZO_NO_ENCONTRADO = "602"

_ESTADO_MAP = {
    "vigente": "vigente",
    "cancelado": "cancelado",
    "no encontrado": "no_encontrado",
}


def _es_rfc_valido(rfc: str) -> bool:
    """Valida RFC usando la función canónica centralizada."""
    return is_valid_rfc(rfc)


def _normalize_folio(folio: str) -> str:
    return (folio or "").strip()


class SATValidatorError(Exception):
    """Error real (red, timeout, XML inválido, SOAP Fault) consultando el
    servicio de Verificación de CFDI del SAT."""


# --------------------------------------------------------------------------#
# Construcción / parseo del sobre SOAP
# --------------------------------------------------------------------------#
def _build_expresion_impresa(
    folio_fiscal: str, rfc_emisor: str, rfc_receptor: str, total: Any,
    fe: Optional[str] = None,
) -> str:
    """Construye `expresionImpresa` con los campos re/rr/tt/id del QR del CFDI.

    Formato documentado (docs/CONTRATO-SAT-INTEGRACION-REAL.md §1):
    `?re=<rfc_emisor>&rr=<rfc_receptor>&tt=<total con 6 decimales>&id=<folio>`.
    `fe` (fragmento del sello, opcional) no forma parte del contrato mínimo
    documentado para esta tarea pero se admite pasarlo si el llamador lo
    tiene (algunos QR de CFDI lo incluyen) — nunca se inventa si no se pasa.
    """
    try:
        total_str = f"{float(total):.6f}"
    except (TypeError, ValueError) as exc:
        raise SATValidatorError(f"'total' no es un número válido: {total!r}") from exc
    partes = [
        f"re={quote(str(rfc_emisor), safe='')}",
        f"rr={quote(str(rfc_receptor), safe='')}",
        f"tt={total_str}",
        f"id={quote(str(folio_fiscal), safe='')}",
    ]
    if fe:
        partes.append(f"fe={quote(str(fe), safe='')}")
    return "?" + "&".join(partes)


def _build_soap_envelope(expresion_impresa: str) -> bytes:
    """Sobre SOAP 1.1 doc/literal para la operación `Consulta`.

    Estructura confirmada leyendo el WSDL real (ver docstring del módulo):
    elemento `Consulta` en el namespace `http://tempuri.org/`, con un único
    hijo `expresionImpresa` (xs:string).
    """
    from xml.sax.saxutils import escape

    body = escape(expresion_impresa)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<soap:Envelope xmlns:soap="{_NS_SOAP_ENV}" xmlns:tem="{_NS_TEMPURI}">'
        "<soap:Header/>"
        "<soap:Body>"
        "<tem:Consulta>"
        f"<tem:expresionImpresa>{body}</tem:expresionImpresa>"
        "</tem:Consulta>"
        "</soap:Body>"
        "</soap:Envelope>"
    ).encode("utf-8")


def _parse_consulta_response(xml_bytes: bytes) -> Dict[str, Optional[str]]:
    """Parsea la respuesta SOAP real de `ConsultaCFDIService.Consulta`.

    Devuelve los 5 campos documentados de `Acuse`
    (CodigoEstatus/EsCancelable/Estado/EstatusCancelacion/ValidacionEFOS),
    buscándolos por local-name (tolerante a variaciones de prefijo de
    namespace, que sí varían entre implementaciones SOAP reales) pero
    verificando primero que la respuesta sea XML válido y no un SOAP Fault.

    Nunca inventa un valor: un campo ausente en la respuesta real queda en
    None, tal cual — no se sustituye por un default.
    """
    from lxml import etree

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise SATValidatorError(
            f"La respuesta del SAT no es XML válido: {exc}"
        ) from exc

    fault = root.find(f".//{{{_NS_SOAP_ENV}}}Fault")
    if fault is not None:
        faultstring_el = fault.find(".//faultstring")
        detalle = (faultstring_el.text if faultstring_el is not None else None) \
            or "SOAP Fault del servicio del SAT sin detalle."
        raise SATValidatorError(f"El servicio del SAT devolvió un SOAP Fault: {detalle}")

    result: Dict[str, Optional[str]] = {}
    for campo in ("CodigoEstatus", "EsCancelable", "Estado",
                  "EstatusCancelacion", "ValidacionEFOS"):
        encontrados = root.xpath(f".//*[local-name()='{campo}']")
        valor = encontrados[0].text if encontrados else None
        result[campo] = valor.strip() if isinstance(valor, str) else valor
    return result


class SATValidator:
    """Verificación REAL de estatus de CFDI y RFC ante el SAT (FIS-024).

    Fail-closed: cualquier error de red, timeout, XML inválido o SOAP Fault
    se propaga como `ok: False` con el detalle real — nunca se fabrica un
    "vigente"/"cancelado" de reemplazo. Ver docstring del módulo.
    """

    backend = "SAT ConsultaCFDIService (real)"

    def __init__(
        self,
        db=None,
        tenant_id: Optional[Any] = None,
        *,
        base_url: Optional[str] = None,
        http_client: Optional[Any] = None,
        timeout_seconds: float = 20.0,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self._base_url = (base_url or SAT_CONSULTA_CFDI_BASE_URL_DEFAULT).rstrip("/")
        self._timeout_seconds = timeout_seconds
        # Inyección de cliente httpx para pruebas: evita CUALQUIER llamada de
        # red real en la suite de tests (mismo patrón que FacturapiAdapter,
        # ver tests/fixtures/sat_consulta_cfdi_simulator.py).
        self._injected_client = http_client
        self._owned_client: Optional[Any] = None
        logger.warning(
            "SATValidator instanciado en modo REAL (FIS-024) contra %s — "
            "SAT_VALIDATOR_VERIFICADO_CONTRA_REAL=%s (nunca ejecutado contra "
            "el servicio real del SAT; ver docstring del módulo). "
            "Fail-closed ante cualquier error de red o parseo.",
            self._base_url, SAT_VALIDATOR_VERIFICADO_CONTRA_REAL,
        )

    # ------------------------------------------------------------------ #
    # Cliente HTTP (real o inyectado en pruebas)
    # ------------------------------------------------------------------ #
    def _client(self):
        if self._injected_client is not None:
            return self._injected_client
        if self._owned_client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - dependencia declarada en pyproject
                raise SATValidatorError(
                    "httpx no está instalado; no se puede llamar al servicio "
                    "real de Verificación de CFDI del SAT."
                ) from exc
            self._owned_client = httpx.Client(
                base_url=self._base_url, timeout=self._timeout_seconds,
            )
        return self._owned_client

    def close(self) -> None:
        if self._owned_client is not None:
            try:
                self._owned_client.close()
            except Exception:
                logger.debug("SATValidator: error cerrando cliente httpx", exc_info=True)
            self._owned_client = None

    def _consulta_soap(self, expresion_impresa: str) -> Dict[str, Optional[str]]:
        """Hace la llamada SOAP real y devuelve los campos parseados.

        Cualquier error (red, timeout, HTTP no-200, XML inválido, SOAP
        Fault) se propaga como `SATValidatorError` — el llamador lo convierte
        en un `ok: False` fail-closed, nunca en un estatus fabricado.
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise SATValidatorError("httpx no está instalado.") from exc

        envelope = _build_soap_envelope(expresion_impresa)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SAT_CONSULTA_CFDI_SOAP_ACTION,
        }
        client = self._client()
        try:
            response = client.post(SAT_CONSULTA_CFDI_PATH, content=envelope, headers=headers)
        except httpx.TimeoutException as exc:
            raise SATValidatorError(
                f"Timeout consultando el servicio de Verificación de CFDI del SAT: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SATValidatorError(
                f"Error de red consultando el servicio de Verificación de CFDI del SAT: {exc}"
            ) from exc

        # Se intenta parsear el cuerpo SIEMPRE, incluso con HTTP >=400: los
        # SOAP Fault reales normalmente llegan con HTTP 500 y un cuerpo XML
        # con el detalle real (faultstring) — parsearlo primero da un error
        # más honesto/específico que solo reportar el código HTTP crudo.
        try:
            campos = _parse_consulta_response(response.content)
        except SATValidatorError as exc:
            if response.status_code >= 400:
                raise SATValidatorError(f"{exc} (HTTP {response.status_code})") from exc
            raise
        if response.status_code >= 400:
            # XML válido y sin Fault reconocible, pero con un HTTP de error:
            # contradicción que no se puede resolver a favor de un resultado
            # — se falla cerrado también.
            raise SATValidatorError(
                f"El servicio de Verificación de CFDI del SAT respondió "
                f"HTTP {response.status_code} sin un SOAP Fault reconocible: "
                f"{response.text[:300]!r}"
            )
        return campos

    # ------------------------------------------------------------------ #
    # Estatus de CFDI
    # ------------------------------------------------------------------ #
    def check_status(
        self,
        folio_fiscal: str,
        rfc_emisor: Optional[str] = None,
        rfc_receptor: Optional[str] = None,
        total: Optional[Any] = None,
        fe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Consulta el estatus real de un CFDI por folio fiscal (UUID).

        Requiere `rfc_emisor`, `rfc_receptor` y `total` (además de
        `folio_fiscal`) porque el servicio real del SAT necesita la misma
        `expresionImpresa` que trae el QR del CFDI (campos re/rr/tt/id) — no
        existe una consulta real solo por folio. Si faltan, se devuelve
        `ok: False` fail-closed explicando qué falta, en vez de adivinar o
        de responder con un estatus mock.

        Devuelve {ok, folio_fiscal, estado, descripcion, es_cancelable,
        estatus_cancelacion, codigo_estatus, validacion_efos, consultado_en,
        backend, simulado, verificado_contra_real} en éxito; en fallo,
        {ok: False, error, folio_fiscal, backend, simulado,
        verificado_contra_real} sin `estado` (nunca un `estado` fabricado:
        el campo simplemente no está presente).
        """
        folio = _normalize_folio(folio_fiscal)
        base_fail = {
            "backend": self.backend, "simulado": False,
            "verificado_contra_real": SAT_VALIDATOR_VERIFICADO_CONTRA_REAL,
        }
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.", **base_fail}

        faltantes = [
            nombre for nombre, valor in (
                ("rfc_emisor", rfc_emisor),
                ("rfc_receptor", rfc_receptor),
                ("total", total),
            ) if not valor and valor != 0
        ]
        if faltantes:
            return {
                "ok": False,
                "folio_fiscal": folio,
                "error": (
                    "El servicio real de Verificación de CFDI del SAT requiere "
                    f"{', '.join(faltantes)} (además de folio_fiscal) para "
                    "construir 'expresionImpresa' — no se puede consultar el "
                    "estatus real sin estos datos. No se fabrica un estatus "
                    "de reemplazo."
                ),
                **base_fail,
            }

        try:
            expresion = _build_expresion_impresa(folio, rfc_emisor, rfc_receptor, total, fe=fe)
            campos = self._consulta_soap(expresion)
        except SATValidatorError as exc:
            logger.warning("SATValidator.check_status: %s", exc)
            return {"ok": False, "folio_fiscal": folio, "error": str(exc), **base_fail}

        codigo_estatus = campos.get("CodigoEstatus")
        estado_raw = campos.get("Estado")
        now_iso = datetime.now().isoformat(timespec="seconds")

        if codigo_estatus and codigo_estatus.strip().upper().startswith("N"):
            if _CODIGO_RECHAZO_NO_ENCONTRADO in codigo_estatus:
                return {
                    "ok": True, "folio_fiscal": folio, "estado": "no_encontrado",
                    "descripcion": codigo_estatus,
                    "codigo_estatus": codigo_estatus,
                    "es_cancelable": campos.get("EsCancelable"),
                    "estatus_cancelacion": campos.get("EstatusCancelacion"),
                    "validacion_efos": campos.get("ValidacionEFOS"),
                    "consultado_en": now_iso, **base_fail,
                }
            # Otro rechazo (p.ej. N-601 expresión impresa mal formada): es un
            # problema de NUESTRA solicitud, no un veredicto sobre el CFDI —
            # no se traduce a "vigente"/"cancelado"/"no_encontrado".
            return {
                "ok": False, "folio_fiscal": folio,
                "error": f"El SAT rechazó la consulta: {codigo_estatus}",
                "codigo_estatus": codigo_estatus, **base_fail,
            }

        if not estado_raw:
            return {
                "ok": False, "folio_fiscal": folio,
                "error": (
                    "La respuesta del SAT no trae 'CodigoEstatus' de rechazo "
                    "ni 'Estado' reconocible; no se puede determinar el "
                    f"estatus real. Campos recibidos: {campos!r}"
                ),
                **base_fail,
            }

        estado_norm = _ESTADO_MAP.get(estado_raw.strip().lower())
        if estado_norm is None:
            return {
                "ok": False, "folio_fiscal": folio,
                "error": (
                    f"El SAT devolvió un valor de 'Estado' no reconocido: "
                    f"{estado_raw!r}. No se asume un valor por defecto."
                ),
                "codigo_estatus": codigo_estatus, **base_fail,
            }

        return {
            "ok": True, "folio_fiscal": folio, "estado": estado_norm,
            "descripcion": codigo_estatus or f"Estado: {estado_raw}",
            "codigo_estatus": codigo_estatus,
            "es_cancelable": campos.get("EsCancelable"),
            "estatus_cancelacion": campos.get("EstatusCancelacion"),
            "validacion_efos": campos.get("ValidacionEFOS"),
            "consultado_en": now_iso, **base_fail,
        }

    def verify_cfdi(
        self,
        folio_fiscal: str,
        rfc_emisor: Optional[str] = None,
        rfc_receptor: Optional[str] = None,
        total: Optional[Any] = None,
        acuse_timbrado: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Verificación completa de un CFDI: estatus real + cadena."""
        folio = _normalize_folio(folio_fiscal)
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.",
                    "backend": self.backend, "simulado": False,
                    "verificado_contra_real": SAT_VALIDATOR_VERIFICADO_CONTRA_REAL}
        status = self.check_status(folio, rfc_emisor, rfc_receptor, total)
        chain = self._verify_chain_con_status(
            folio, status, acuse_timbrado=acuse_timbrado,
        )
        valid = bool(status.get("ok")) and status.get("estado") == "vigente"
        return {
            "ok": valid,
            "folio_fiscal": folio,
            "estado": status.get("estado"),
            "valido": valid,
            "estatus": status,
            "cadena": chain,
            "backend": self.backend, "simulado": False,
            "verificado_contra_real": SAT_VALIDATOR_VERIFICADO_CONTRA_REAL,
        }

    # ------------------------------------------------------------------ #
    # Validación de RFC
    # ------------------------------------------------------------------ #
    def verify_rfc(self, rfc: str) -> Dict[str, Any]:
        """Valida el FORMATO de un RFC (no su existencia real ante el SAT).

        No existe un servicio público del SAT para verificar si un RFC de
        un tercero está registrado fuera de trámites autenticados con la
        e.firma/CIEC del propio contribuyente consultado (Constancia de
        Situación Fiscal) — ver docs/CONTRATO-SAT-INTEGRACION-REAL.md §1.
        Por eso este método sigue siendo, honestamente, solo una validación
        de formato: `registrado` es `None` (desconocido) salvo para RFCs
        genéricos (XAXX/XEXX), que se marcan explícitamente como no
        correspondientes a un contribuyente único. NUNCA se fabrica un
        "sí está registrado" / "no está registrado" para un RFC real.
        """
        rfc_n = (rfc or "").strip().upper()
        backend = ("SAT (validación de formato local; sin servicio público "
                   "de existencia de RFC de terceros)")
        if not _es_rfc_valido(rfc_n):
            return {"ok": False, "rfc": rfc_n, "valido": False,
                    "detalle": "El RFC no cumple el formato oficial.",
                    "backend": backend, "simulado": False}
        es_generico = rfc_n.startswith("XAXX") or rfc_n.startswith("XEXX")
        return {"ok": True, "rfc": rfc_n, "valido": True,
                "registrado": None if not es_generico else False,
                "detalle": ("RFC con formato válido. Existencia real NO verificable "
                            "(no existe servicio público del SAT para RFCs de "
                            "terceros; ver docs/CONTRATO-SAT-INTEGRACION-REAL.md §1)."
                            if not es_generico
                            else "RFC genérico (no corresponde a un contribuyente único)."),
                "backend": backend, "simulado": False}

    # ------------------------------------------------------------------ #
    # Cadena de custodia
    # ------------------------------------------------------------------ #
    def verify_chain(
        self,
        folio_fiscal: str,
        rfc_emisor: Optional[str] = None,
        rfc_receptor: Optional[str] = None,
        total: Optional[Any] = None,
        acuse_timbrado: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Cadena de custodia de un CFDI: consulta real + (si se tiene) el
        acuse de timbrado del PAC. NUNCA fabrica eventos.

        No existe un servicio público del SAT que devuelva un "historial de
        eventos" de timbrado/registro (ver docs/CONTRATO-SAT-INTEGRACION-REAL.md
        §1) — el mock anterior lo fabricaba con `datetime.now()` en cada
        llamada, exactamente el tipo de resultado inventado que esta tarea
        prohíbe. Aquí la "cadena" es, honestamente, la lista de eventos
        REALES que el llamador puede demostrar: el acuse de timbrado del PAC
        si lo pasa (`acuse_timbrado`, p.ej. de
        `FacturapiAdapter.timbrar_cfdi()`), más esta misma consulta de
        estatus real. Si no hay ni acuse ni consulta exitosa, `cadena` queda
        vacía — nunca se rellena con eventos ficticios.
        """
        folio = _normalize_folio(folio_fiscal)
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.",
                    "backend": self.backend, "simulado": False,
                    "verificado_contra_real": SAT_VALIDATOR_VERIFICADO_CONTRA_REAL}
        status = self.check_status(folio, rfc_emisor, rfc_receptor, total)
        return self._verify_chain_con_status(folio, status, acuse_timbrado=acuse_timbrado)

    def _verify_chain_con_status(
        self, folio: str, status: Dict[str, Any],
        acuse_timbrado: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Construye la cadena a partir de un `check_status()` ya calculado
        (evita una segunda llamada de red cuando `verify_cfdi()` ya la hizo)."""
        eventos = []
        if acuse_timbrado:
            eventos.append({
                "evento": "Timbrado",
                "fecha": acuse_timbrado.get("fecha_timbrado"),
                "autoridad": "PAC",
                "detalle": acuse_timbrado.get("cadena_timbre")
                    or acuse_timbrado.get("sello_cfdi"),
            })
        if status.get("ok"):
            eventos.append({
                "evento": "Consulta de estatus (SAT ConsultaCFDIService)",
                "fecha": status.get("consultado_en"),
                "autoridad": "SAT",
                "detalle": status.get("descripcion"),
            })

        estado = status.get("estado")
        ok = bool(status.get("ok")) and estado == "vigente"
        return {
            "ok": ok,
            "folio_fiscal": folio,
            "estado": estado,
            "cadena": eventos,
            "sello_valido": ok if status.get("ok") else None,
            "estatus_consulta": status,
            "backend": self.backend, "simulado": False,
            "verificado_contra_real": SAT_VALIDATOR_VERIFICADO_CONTRA_REAL,
        }
