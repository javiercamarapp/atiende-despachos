# Guía de Desarrollo — Extender B&B AI con nuevos ERPs

Esta guía está dirigida a **desarrolladores** que quieren añadir un ERP nuevo
al agente contable B&B AI. Explica la arquitectura de integración, los
contratos abstractos (`ERPInterface` y `BrowserAutomation` /
`DesktopAutomation`), cómo crear un conector y cómo registrarlo en el
pipeline.

---

## 1. Arquitectura de integración de ERPs

El principio rector es la **inversión de dependencias**: los servicios del
agente dependen de **interfaces abstractas**, no de implementaciones
concretas. Esto permite cambiar de ERP (o usar un mock) sin tocar el
pipeline.

```
        Servicios del agente (pipeline, tools)
                      │
                      ▼
          ERPInterface (abstracto)      ←  el contrato
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   MockCONTPAQi    CSVErp        TuNuevoErp
   (memoria)      (fallback)     (NUEVO)
```

Hay **dos vías** para conectar un ERP:

| Vía | Cuándo usarla | Contrato |
|---|---|---|
| **API REST** | El ERP tiene API estable (CONTPAQi contaDIGITAL, SAP, Odoo, etc.). | `ERPInterface` |
| **Computer use** | El ERP es on-premise / web legacy sin API (CONTPAQi escritorio, Aspel). | `BrowserAutomation` (web) o `DesktopAutomation` (escritorio) |

---

## 2. Vía A: ERP con API REST — implementa `ERPInterface`

### 2.1 El contrato

Archivo: `b2b_ai/erp/base.py`

```python
from abc import ABC, abstractmethod

class ERPInterface(ABC):
    @abstractmethod
    def register_invoice(self, invoice: dict) -> dict:
        """
        Registra una póliza/factura en el ERP.
        invoice: dict normalizado (folio_fiscal, emisor, conceptos, montos,
                 clasificación contable, etc.).
        Devuelve {ok: bool, poliza: str|None, status: str, message: str}.
        """

    @abstractmethod
    def get_invoice(self, folio_fiscal: str) -> dict | None:
        """Consulta el estado de una póliza por folio fiscal."""

    @abstractmethod
    def health(self) -> dict:
        """Devuelve {ok: bool, backend: str, detail: str}."""
```

### 2.2 Implementar un conector nuevo

Crea `b2b_ai/erp/<erp>.py`. Ejemplo mínimo (SAP B1 vía REST):

```python
# b2b_ai/erp/sap_b1.py
import requests
from b2b_ai.erp.base import ERPInterface

class SapB1ERP(ERPInterface):
    backend = "SAP B1 (REST)"

    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._headers = {"Authorization": f"Bearer {self.token}"}

    def register_invoice(self, invoice):
        folio = invoice.get("folio_fiscal")
        if not folio:
            return {"ok": False, "poliza": None, "status": "error",
                    "message": "Sin folio fiscal."}
        payload = {
            "folio_fiscal": folio,
            "emisor_rfc": invoice.get("emisor_rfc", ""),
            "total": str(invoice.get("total", "")),
            "categoria": invoice.get("categoria", "desconocido"),
            # ...mapear a la estructura de SAP B1
        }
        r = requests.post(f"{self.base_url}/Polizas", json=payload,
                          headers=self._headers, timeout=30)
        if r.status_code != 201:
            return {"ok": False, "poliza": None, "status": "error",
                    "message": f"HTTP {r.status_code}: {r.text}"}
        data = r.json()
        return {"ok": True, "poliza": data.get("id"), "status": "registrada",
                "message": f"Póliza {data.get('id')} en SAP B1."}

    def get_invoice(self, folio_fiscal):
        r = requests.get(f"{self.base_url}/Polizas/{folio_fiscal}",
                         headers=self._headers, timeout=30)
        return r.json() if r.status_code == 200 else None

    def health(self):
        try:
            r = requests.get(f"{self.base_url}/health", headers=self._headers,
                             timeout=10)
            ok = r.status_code == 200
        except Exception:
            ok = False
        return {"ok": ok, "backend": self.backend,
                "detail": "SAP B1 REST " + ("OK" if ok else "no responde")}
```

### 2.3 Usar el conector en el pipeline

El pipeline (`process_file`) acepta un `erp` inyectado. Ejemplo directo:

```python
from b2b_ai.services.pipeline import process_file
from b2b_ai.erp.sap_b1 import SapB1ERP

sap = SapB1ERP("https://sap.example.com/api", token="mi-token")
res = process_file("cfdi.xml", erp=sap)   # registra en SAP B1
```

La tool `register_erp` usa `MockCONTPAQi` por defecto; pasa tu ERP a
`process_file` vía el parámetro `erp=`.

---

## 3. Vía B: ERP sin API — Computer use

### 3.1 ERPs web → `BrowserAutomation`

Archivo: `b2b_ai/computer_use/browser.py`

```python
class BrowserAutomation(ABC):
    @abstractmethod
    def navigate_to_erp(self, url: str) -> dict: ...
    @abstractmethod
    def login(self, credentials: dict) -> dict: ...
    @abstractmethod
    def upload_cfdi(self, xml_path: str, **options) -> dict: ...
    @abstractmethod
    def read_screen(self) -> dict: ...
    @abstractmethod
    def click_element(self, selector: str) -> dict: ...
    @abstractmethod
    def type_text(self, field: str, text: str) -> dict: ...
    @abstractmethod
    def health(self) -> dict: ...
```

Para un driver web real (Playwright + visión), implementa esta interfaz y
regístralo con `set_default_browser()`:

```python
from b2b_ai.computer_use.browser import set_default_browser
from b2b_ai.computer_use.playwright_driver import PlaywrightVisionBrowser  # ejemplo

set_default_browser(PlaywrightVisionBrowser())
```

### 3.2 ERPs de escritorio → `DesktopAutomation`

Archivo: `b2b_ai/computer_use/contpaqi_driver.py` (define el contrato y ya
incluye `MockDesktop`, `ContpaqiDriver`, y `AspelDriver` en `aspel_driver.py`).

```python
class DesktopAutomation(ABC):
    @abstractmethod
    def screenshot(self) -> dict: ...
    @abstractmethod
    def read_window_title(self) -> str: ...
    @abstractmethod
    def click(self, x: int, y: int) -> dict: ...
    @abstractmethod
    def type_text(self, text: str) -> dict: ...
    @abstractmethod
    def press_key(self, key: str) -> dict: ...
    @abstractmethod
    def health(self) -> dict: ...
```

Para añadir otro ERP de escritorio, replica el patrón de `AspelDriver`:
implementa `DesktopAutomation` con la semántica de pantallas de tu ERP (abrir
app, login, capturar grid, registrar CFDI pendiente de revisión).

---

## 4. Registrar tu ERP en las tools

Si quieres que tu ERP esté disponible como **tool** invocable por el agente,
añade una tool en `b2b_ai/tools/tools.py`:

```python
from b2b_ai.tools.registry import tool

@tool(name="register_sap_b1",
      description="Registra una factura en SAP B1.",
      category="erp",
      parameters=[{"name": "invoice", "type": "object", "required": True}])
def register_sap_b1(invoice, erp=None):
    if erp is None:
        erp = SapB1ERP(...)   # o el default que configures
    return erp.register_invoice(invoice)
```

### 4.1 Añadir una ruta al router (opcional)

Para que el agente "decida" usar tu ERP por lenguaje natural, añade una regla
en `b2b_ai/tools/router.py`:

```python
ROUTING_RULES = [
    # ...reglas existentes...
    (["sap", "sap b1", "sapb1"], "register_sap_b1", "erp"),
]
```

---

## 5. Estructura de una factura normalizada

El dict que recibe `register_invoice` sigue el formato del parser CFDI:

```python
{
    "folio_fiscal": "<UUID>",        # identificador único
    "emisor_rfc": "XAXX010101000",
    "emisor_nombre": "...",
    "receptor_rfc": "...",
    "fecha": "2026-07-01T09:30:00",
    "subtotal": Decimal("1034.48"),
    "iva": Decimal("165.52"),
    "total": Decimal("1200.00"),
    "moneda": "MXN",
    "categoria": "gasto_operativo",  # puesto por el clasificador
    "confianza": 0.95,
    "conceptos": [ { "clave_prod_serv": "...", "descripcion": "...",
                     "cantidad": ..., "valor_unitario": ..., "importe": ... } ],
    "traslados": [...],
    "retenciones": [...],
}
```

> Recuerda: los montos pueden llegar como `Decimal` o `str`. Normaliza con
> `str()` o `Decimal()` de forma defensiva en tu conector.

---

## 6. Cuentas contables por categoría

El catálogo de cuentas sugerido está en `b2b_ai/erp/contpaqi.py`
(`_CUENTAS` / `_cuentas_para_categoria`). Si tu ERP usa cuentas propias,
mapea tú la categoría:

| Categoría | Cuenta cargo sugerida | Cuenta abono sugerida |
|---|---|---|
| `gasto_operativo` | `6131 Gastos generales` | `1130 Bancos` |
| `inversion` | `1115 Gastos de instalacion` | `1130 Bancos` |
| `activo_fijo` | `1210 Mobiliario y equipo` | `1130 Bancos` |
| `nomina` | `6110 Sueldos y salarios` | `1130 Bancos` |
| `desconocido` | `6100 Gastos por clasificar` | `1130 Bancos` |

---

## 7. Tests

El proyecto tiene **139 tests** (pytest). Al añadir un ERP, escribe al menos:

- Un test de `register_invoice` feliz + error sin folio.
- Un test de `get_invoice` (existente y ausente).
- Un test de `health`.
- Si es computer use, un test del flujo (navegar → login → upload → screen).

```bash
cd enterprise && source .venv/bin/activate
python -m pytest -q
```

Convención de naming: `tests/test_<modulo>.py`, funciones `test_*`.

---

## 8. Checklist para un nuevo ERP

- [ ] Implementas `ERPInterface` (API) o `BrowserAutomation`/`DesktopAutomation` (computer use).
- [ ] `register_invoice` devuelve `{ok, poliza, status, message}`.
- [ ] `get_invoice` y `health` implementados.
- [ ] Mapeo de cuentas contables por categoría.
- [ ] Normalización defensiva de montos (Decimal/str).
- [ ] Tool registrada (si aplica) + ruta en el router.
- [ ] Tests verdes (`python -m pytest -q`).
- [ ] Docs actualizadas (README + esta guía, sección de ERPs soportados).

---

## 9. ERPs soportados actualmente

| ERP | Vía | Estado | Archivo |
|---|---|---|---|
| CONTPAQi (mock) | API | Mock funcional | `erp/contpaqi.py` |
| CSV (fallback universal) | Archivo | Producción (fallback) | `erp/csv_erp.py` |
| CONTPAQi web | Computer use | Mock funcional | `computer_use/browser.py` |
| CONTPAQi escritorio | Computer use | Mock funcional | `computer_use/contpaqi_driver.py` |
| Aspel (SAE/COI) | Computer use | Mock funcional | `computer_use/aspel_driver.py` |

> Los mocks están listos para sustituirse por drivers reales (REST con
> credenciales, Playwright/visión) sin cambiar el contrato ni el pipeline.
