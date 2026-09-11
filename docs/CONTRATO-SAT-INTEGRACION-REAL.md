# Contrato de integración real con el SAT (FIS-019 pendiente / FIS-024 resuelto)

**Estado de este documento:** §1 (`SATValidator`, FIS-024) **SE IMPLEMENTÓ**
— ver `b2b_ai/sat/validator.py`, cuyo docstring confirma la versión del PDF
de especificación asumida (1.4, noviembre 2022) contra las tres copias
activas en sat.gob.mx a septiembre de 2026. §2 (`SATSubmitter._send_soap()`,
FIS-019) sigue siendo solo especificación — **no implementado** — porque el
propio §2 concluye que probablemente no existe un web service SOAP público
del SAT para envío de declaraciones (ver "(C) Consecuencia de diseño" más
abajo); no se fuerza una implementación sobre un endpoint no confirmado.

Referencias cruzadas:
- Hallazgos de auditoría: `docs/AUDIT-FINAL-FISCAL.md` (FIS-019 pendiente, FIS-024 resuelto)
- Panorama general de APIs mexicanas ya investigado: `docs/APIs-INTEGRACION-MEXICO.md` §1
- Código: `b2b_ai/features/declaraciones/sat_submitter.py` (stub, FIS-019 sigue pendiente),
  `b2b_ai/sat/validator.py` (real, FIS-024)

Este documento distingue explícitamente entre:
- **(A) Hechos verificados** — endpoints y comportamientos con documentación
  pública encontrada (SAT o librerías de terceros ampliamente usadas).
- **(B) No verificado / probablemente incorrecto** — cosas que el código
  actual asume o menciona pero que no se pudieron confirmar.
- **(C) Decisión de diseño pendiente** — huecos que un implementador real
  tendrá que resolver y que este documento no puede zanjar sin acceso a un
  ambiente con e.firma real.

---

## 1. `SATValidator` — Consulta de estatus de CFDI (FIS-024)

### (A) Servicio real identificado

- **Servicio:** "Verificación de Comprobantes Fiscales Digitales por
  Internet" — público, del SAT, **sin necesidad de e.firma ni CIEC**.
- **Endpoint / WSDL:**
  `https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc?wsdl`
- **Operación:** `Consulta(expresionImpresa: string) -> respuesta`
- **Parámro `expresionImpresa`:** query string con los mismos campos que
  trae el QR del CFDI:
  - `re` = RFC emisor
  - `rr` = RFC receptor
  - `tt` = total (con el formato exacto que usa el timbre, normalmente 6
    decimales)
  - `id` = UUID / folio fiscal
  - Ejemplo: `?re=AAA010101AAA&rr=XAXX010101000&tt=1000.000000&id=<uuid>`
- **Respuesta (campos documentados públicamente):**
  - `Estado`: `"Vigente"` | `"Cancelado"` | `"No Encontrado"`
  - `EsCancelable`: si se puede cancelar directo o requiere aceptación
  - `EstatusCancelacion`: estatus del proceso de cancelación, si aplica
  - `CodigoEstatus`: mensaje interno del SAT sobre la consulta
  - `ValidacionEFOS`: si el emisor/receptor está en la lista 69-B
- **Documentación oficial:** el SAT publica un PDF versionado
  ("Documentación del Servicio de Consulta de CFDI"); al momento de
  implementar, bajar la versión vigente desde sat.gob.mx (las versiones 1.2,
  1.3 y 1.4 han circulado — confirmar cuál está activa) en vez de copiar los
  campos de este documento sin revalidar.

### Interfaz objetivo (reemplazo de `SATValidator.check_status`)

```python
from typing import Protocol, TypedDict

class CFDIEstatusReal(TypedDict):
    ok: bool
    folio_fiscal: str
    estado: str            # "vigente" | "cancelado" | "no_encontrado"
    es_cancelable: str | None
    estatus_cancelacion: str | None
    validacion_efos: str | None
    consultado_en: str     # ISO 8601
    backend: str            # "SAT ConsultaCFDIService (real)"
    simulado: bool          # SIEMPRE False en la implementación real


class SATValidatorReal(Protocol):
    def check_status(
        self, folio_fiscal: str, rfc_emisor: str, rfc_receptor: str,
        total: str,
    ) -> CFDIEstatusReal: ...
```

**(C) Decisión pendiente — RESUELTA (FIS-024):** la firma de `check_status()`
se cambió a `check_status(folio_fiscal, rfc_emisor=None, rfc_receptor=None,
total=None, fe=None)` — se optó por pedirlos como parámetros explícitos del
llamador (no por resolverlos automáticamente contra la DB, cuyo esquema para
eso no estaba confirmado). `SATScheduler.run_weekly()` (ya tenía estos datos
en el ledger) y el endpoint `/api/v1/sat/verify` (campos nuevos opcionales en
`SATVerifyRequest`) se actualizaron para pasarlos. `b2b_ai/services/pipeline.py`
sigue llamando solo con el folio deliberadamente (ver TODO ahí): pasar los
datos reales activaría una llamada de red real y no mockeada en una amplia
suite de tests de pipeline que no fue auditada/actualizada en este cambio —
queda como seguimiento explícito. Ver `b2b_ai/sat/validator.py` para el
detalle completo.

**(C) `verify_chain()` (cadena de custodia) — RESUELTA (FIS-024):** ya no
fabrica una lista de eventos. Ahora es, literalmente, lo que este documento
sugería: (1) el acuse de timbrado del PAC si el llamador lo pasa
(`acuse_timbrado`), (2) la consulta de estatus real que se acaba de hacer.
Si no hay ninguno de los dos, `cadena` queda vacía — nunca se rellena con
eventos ficticios (el mock anterior sí lo hacía, con `datetime.now()` en
cada llamada).

### (A) Validación de RFC

- No existe un servicio público del SAT para "verificar si un RFC está
  registrado" fuera de trámites autenticados (constancia de situación
  fiscal). `verify_rfc()` seguirá siendo, en la práctica, solo una
  validación de formato salvo que se integre con la Constancia de
  Situación Fiscal (requiere el propio RFC y contraseña/e.firma del
  contribuyente consultado — no aplica para verificar RFCs de terceros).

---

## 2. `SATSubmitter._send_soap()` — Envío de declaraciones (FIS-019)

### (B) Lo que el código actual asume y que NO se pudo verificar

- La constante `DECLARASAT_ENDPOINT` en `sat_submitter.py`
  (`https://declara.sat.gob.mx/IntermediaDeContribuyente/servicioSolicitud`)
  **no tiene documentación pública encontrada**. No se confirmó que exista
  un web service SOAP de terceros para enviar declaraciones.
- Las constantes `SAT_WSDL_PRODUCTION`/`SAT_WSDL_TEST` en ese mismo archivo
  apuntan al servicio de **Descarga Masiva de CFDI** (correcto y
  documentado como servicio, ver abajo), no a un servicio de envío de
  declaraciones — están mal etiquetadas ahí y no se usan.

### (A) Lo que sí está documentado y verificado

- El SAT **no ofrece una API REST pública** para declaraciones (esto ya
  estaba correctamente documentado en `docs/APIs-INTEGRACION-MEXICO.md`).
- La presentación de declaraciones (ISR provisional/anual, IVA, DIOT) se
  hace hoy, según la documentación pública disponible, a través de:
  1. La aplicación **DeclaraSAT** (escritorio) o el portal web
     "Presenta tu declaración" / "Servicio de Declaraciones y Pagos" —
     ambos son flujos de **sesión de navegador autenticada** (CIEC o
     e.firma), no un web service SOAP/REST documentado para terceros.
  2. Software de despacho (CONTPAQi, Aspel) que integra por su cuenta con
     el SAT, o un **PAC** que ofrezca esta funcionalidad como parte de sus
     servicios de valor agregado.
- El servicio de **Descarga Masiva de CFDI** (`DescargaMasivaService.svc`,
  host `cfdidescargamasiva.cloud.sat.gob.mx` o similar según versión
  vigente) sí es un SOAP real, documentado y usado por librerías de
  terceros ampliamente probadas (ej. `phpcfdi/sat-ws-descarga-masiva`),
  usando WSSecurity con el certificado FIEL como binary token. Esto
  confirma que el *patrón* WSSecurity+FIEL que describe el docstring
  original de `sat_submitter.py` es real — pero está documentado para
  **descarga**, no para **envío de declaraciones**.

### (C) Consecuencia de diseño — decisión que un implementador real debe tomar primero

Antes de escribir código de `_send_soap()`, hay que resolver esta pregunta,
porque cambia la arquitectura completa del módulo:

> **¿Existe de verdad un web service SOAP del SAT para enviar
> declaraciones, o la única vía es automatizar la sesión de navegador de
> DeclaraSAT / el portal, o pasar por un PAC / software de despacho?**

Con la evidencia pública disponible hoy, lo más probable es la segunda
opción. Eso implica que la ruta realista para "envío automatizado" no es
`zeep.Client(wsdl=...)` como sugiere el código actual, sino una de:

1. **Integración con un PAC** que ya ofrezca presentación de declaraciones
   como servicio (revisar cuáles, si alguno, lo ofrecen — la mayoría de
   PACs mexicanos solo timbran CFDI, no presentan declaraciones).
2. **RPA sobre el portal SAT** (Selenium/Playwright autenticado con CIEC o
   e.firma) — fràgil ante cambios de UI del SAT y con riesgo de violar
   términos de uso del portal; requiere validación legal antes de
   construirse.
3. **Mantener el flujo manual** (este sistema genera el XML/DIOT
   correctamente firmado y el humano lo sube al portal) como la única vía
   soportada, documentándolo como tal en vez de simular un endpoint SOAP
   que no se pudo confirmar que existe.

### Prototipo de la opción 2 (RPA sobre el portal) — SOLO contra simulador local

Existe ya un prototipo de la opción 2 en
`b2b_ai/features/declaraciones/sat_portal_rpa_driver.py`
(`SATPortalRPADriver`, Playwright), construido bajo la regla no negociable
de nunca conectarse al dominio real del SAT. Su estado:

- Probado **exclusivamente** contra un simulador local propio
  (`tests/fixtures/sat_portal_simulator.py`, servidor HTTP stdlib que imita
  la estructura de pasos: login e.firma → portafolio → módulo DIOT → carga
  → confirmación → acuse). El simulador NO se construyó a partir de una
  sesión real del portal — es una conjetura educada a partir de
  conocimiento público general; cada selector que asume está marcado en el
  código como "simulador local (confirmado)" vs. "conjetura, NO verificada".
- `VERIFICADO_CONTRA_SAT_REAL = False` en ese módulo, y el driver **rechaza
  técnicamente** (`SATPortalRealDomainBlocked`) conectarse a cualquier host
  bajo `*.gob.mx` — no es solo un aviso en texto, es un guard-clause en
  `__init__`/`connect()`.
- Fail-closed: cada paso (login, navegación, carga, confirmación) solo
  avanza si reconoce explícitamente un marcador de éxito; CAPTCHA, error de
  credenciales, portal caído o cualquier estado no reconocido detienen el
  flujo con un resultado claro — nunca se reintenta a ciegas ni se fabrica
  un folio si el portal (simulador) no lo entregó.
- Pruebas de contrato completas en `tests/test_sat_portal_rpa_driver.py`:
  flujo exitoso de punta a punta, credenciales inválidas, CAPTCHA, portal
  caído, archivo DIOT rechazado y timeout — todas contra el simulador.

Antes de usar esto contra el SAT real con un cliente real faltan, sin
excepción, los tres pasos (a)/(b)/(c) del requisito no negociable #5 de la
tarea que originó este prototipo: (a) confirmar la estructura real del
portal contra una sesión manual real, (b) probar contra un sandbox del SAT
si existe uno para este flujo, (c) revisión legal de que automatizar el
portal no viola sus términos de uso. Ninguno de los tres se ha hecho.

### Interfaz objetivo (si la opción 1 resulta viable)

```python
from typing import Protocol

class SATSubmitterReal(Protocol):
    def submit_declaration(
        self,
        xml_signed: bytes,
        declaration_type: str,   # "iva" | "isr_provisional" | "isr_anual" | "diot"
        periodo: str,
        rfc: str,
        declaration_id: str | None = None,
        confirm: bool = False,   # mantener: nunca proceder sin confirm=True
    ) -> "SubmissionResult": ...
    # SubmissionResult.simulado DEBE ser False aquí, y status solo puede
    # llegar a ACCEPTED si el PAC/SAT devolvió un acuse verificable
    # (folio + sello, no un folio fabricado localmente).

    def check_status(self, declaration_id: str) -> "SubmissionResult | None": ...
```

Requisitos no negociables para que una implementación se considere "real"
(y pueda legítimamente poner `simulado=False`):

1. **Autenticación real** contra el PAC o servicio elegido (credenciales de
   API del PAC, o WSSecurity+FIEL si se confirma un endpoint SOAP real).
2. **Nunca** devolver `SubmissionStatus.ACCEPTED` sin un acuse verificable
   (folio + sello/hash que el propio SAT o PAC entregó) — no un folio
   generado localmente con `hashlib`.
3. Manejo explícito de rechazo (`REJECTED`), timeout (`TIMEOUT`) y error de
   red (`ERROR`), cada uno con el mensaje real que devolvió el proveedor,
   no un mensaje genérico.
4. Persistir el acuse/XML de respuesta (`acuse_xml`) tal cual lo entregó el
   proveedor, para auditoría.
5. Mantener el `confirm=True` obligatorio que ya existe — es una capa de
   seguridad correcta y debe conservarse en la implementación real.

---

## 3. Regla transversal para cualquier implementación futura

Cualquier código que reemplace estos stubs debe:

- Poner `simulado=False` (submitter) / `"simulado": False` (validator)
  **solo** cuando la respuesta vino de una llamada de red real que se
  completó.
- Seguir marcando `simulado=True` explícitamente en cualquier ruta de
  fallback, caché local o modo de prueba que se agregue después — el
  campo debe seguir existiendo y siendo confiable, no eliminarse al
  "graduarse" de mock a real.
- Actualizar `docs/AUDIT-FINAL-FISCAL.md` (cerrar FIS-019/FIS-024) y este
  documento en el mismo cambio que active la integración real.
