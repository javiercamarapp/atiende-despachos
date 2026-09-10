# FacturapiAdapter — integración real con FacturAPI (PAC de CFDI)

**Estado:** `FACTURAPI_VERIFICADO_CONTRA_REAL = False` (constante en
`b2b_ai/integrations/sat/pacs/facturapi_adapter.py`). El código hace llamadas
`httpx` reales al API público de FacturAPI cuando hay una API key
configurada, pero **nunca se ha ejecutado contra una cuenta real de
FacturAPI** — sólo contra el simulador local de
`tests/fixtures/facturapi_simulator.py`. Este es un bloqueo de negocio de
Javier (conseguir cuenta y API key reales de FacturAPI), no de código.

## Alcance de este cambio

Se convirtió **solo `FacturapiAdapter`** en una integración genuinamente
real. Los otros 5 adaptadores de PAC del repo (`corefi`, `multifactura`,
`paxfacturas`, `ecodex`, `finkok`) **siguen siendo 100% simulación** — es una
decisión de negocio pendiente cuál PAC contratar realmente. FacturAPI se
eligió para este primer adaptador real por ser el más documentado
públicamente y el más fácil de verificar.

## Contrato real investigado (docs.facturapi.io/en/api/, sept-2026)

| Operación | Método real | Path |
|---|---|---|
| Timbrar CFDI | `POST` | `/invoices` |
| Cancelar CFDI | `DELETE` | `/invoices/{id}?motive=01-04[&substitution=<uuid>]` |
| Consultar CFDI | `GET` | `/invoices/{id}` |

- **Base URL:** `https://www.facturapi.io/v2`
- **Autenticación:** `Authorization: Bearer <api_key>` (`sk_test_...` /
  `sk_live_...`), vía `FACTURAPI_API_KEY`.
- **Errores:** 4xx/5xx con cuerpo JSON `{"message","status","ok":false,
  "code","errors":[...]}`.
- **Motivos de cancelación soportados por FacturAPI:** `01`-`04` únicamente
  (no existe `05` en el contrato real, aunque el enum interno
  `TipoCancelacion` sí lo declare para otros PACs/flujos — el adaptador lo
  rechaza localmente, sin llamar a la red, si se pide `05`).

### No confirmado / fuera del contrato documentado

- **Endpoint de validación de sola API key** (tipo `organizations/me` o
  `whoami`): no se encontró uno público. `connect()` por eso **no hace
  ninguna llamada de red** — sólo valida que la API key esté presente y
  difiere la validación real de credenciales a la primera llamada real
  (timbrar/cancelar/consultar), cuyo `401` se propaga honestamente. Está
  marcado `# TODO: endpoint no confirmado contra documentación real` en el
  código; si se confirma uno en el futuro, debe usarse ahí en lugar de este
  TODO.

## Capacidades que FacturAPI NO ofrece (por diseño, no fabricadas)

`consultar_rfc()` y `contabilidad_electronica()` lanzan **`NotImplementedError`**
explícito en vez de simular una respuesta. FacturAPI es un PAC de timbrado de
CFDI; ninguna de estas dos capacidades aparece en su documentación pública de
API:

- **Consulta de estatus de RFC ante el SAT** es un servicio del propio SAT
  (o de proveedores especializados en validación de identidad fiscal), no de
  un PAC de timbrado.
- **Contabilidad Electrónica** (balanza de comprobación, catálogo de
  cuentas, pólizas al buzón tributario) es un trámite del contribuyente ante
  el SAT o de software contable especializado, no de un PAC de CFDI.

## Fail-closed sin API key

Si `FACTURAPI_API_KEY` está vacía o ausente, `FacturapiAdapter.is_configured`
es `False`, `connect()` regresa `False` y **todo** método de timbrado,
cancelación o consulta lanza `SATAdapterError(code="NO_CONFIGURADO")` — nunca
se simula una respuesta exitosa (mismo criterio "esqueleto honesto" que
`SATPortalRPADriver` y `sat_rpa_bridge.py`).

## Cómo se probó

`tests/fixtures/facturapi_simulator.py` es un servidor HTTP local (stdlib
puro, sin dependencias externas) que imita el contrato documentado de
FacturAPI para `POST/DELETE/GET /invoices[/{id}]`, incluyendo los caminos de
error reales (401 por API key inválida, 400 por RFC receptor inválido, 404
por invoice inexistente). **No** se construyó a partir de tráfico real
capturado contra `facturapi.io` — la forma de payloads/respuestas es la
documentada públicamente.

`tests/test_facturapi_adapter.py` cubre, exclusivamente contra ese
simulador (ningún test toca `facturapi.io` ni ningún otro dominio real):

- Timbrado exitoso.
- RFC receptor inválido rechazado por el PAC (propagado como `exito=False`,
  nunca fingido como éxito).
- API key inválida → `401` propagado.
- Cancelación exitosa, cancelación de invoice inexistente (`404`), motivo de
  cancelación no soportado por FacturAPI rechazado localmente sin red.
- Consulta exitosa y consulta de invoice inexistente (`SATAdapterError`
  propagado, nunca un CFDI inventado).
- Sin `FACTURAPI_API_KEY`: fail-closed en timbrar/cancelar/consultar.
- `consultar_rfc()` / `contabilidad_electronica()`: `NotImplementedError`.

## Qué falta para marcar `FACTURAPI_VERIFICADO_CONTRA_REAL = True`

Bloqueo de negocio de Javier, no de código:

1. Conseguir una cuenta real de FacturAPI y una API key de prueba
   (`sk_test_...`).
2. Timbrar, consultar y cancelar al menos un CFDI real contra
   `https://www.facturapi.io/v2` y confirmar que la traducción de
   `CFDIRequest` → payload real (`_build_invoice_payload`) produce un CFDI
   válido ante el SAT.
3. Confirmar si existe (o sigue sin existir) un endpoint real de validación
   de sola API key, para poder quitar el TODO de `connect()`.
4. Actualizar `FACTURAPI_VERIFICADO_CONTRA_REAL` a `True` y documentar aquí
   la fecha y el resultado de esa primera verificación real.
