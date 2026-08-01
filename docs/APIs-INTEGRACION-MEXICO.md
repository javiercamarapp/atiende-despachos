# APIs y Servicios de Integración para Agentes Contables en México

> **Proyecto:** likida-ai-enterprise — 5 agentes contables autónomos para despachos mexicanos
> **Última actualización:** 2026-08-01
> **Stack:** Python FastAPI — ya procesa CFDI 4.0 y nómina

---

## Índice

1. [SAT — Servicio de Administración Tributaria](#1-sat--servicio-de-administración-tributaria)
2. [Facturadores Electrónicos (APIs)](#2-facturadores-electrónicos-apis)
3. [ERPs Mexicanos (Integración)](#3-erps-mexicanos-integración)
4. [Banca y Pagos](#4-banca-y-pagos)
5. [Tabla Comparativa Resumen](#5-tabla-comparativa-resumen)
6. [Recomendaciones para Likida AI](#6-recomendaciones-para-likida-ai)

---

## 1. SAT — Servicio de Administración Tributaria

El SAT no ofrece APIs REST públicas amigables. Sus servicios son web services SOAP/XML o portales web. Los agentes contables deben integrarse a través de PACs (Proveedores Autorizados de Certificación) o librerías que abstraen la complejidad del SAT.

### 1.1 Web Services de Facturación (CFDI 4.0)

**Endpoint del SAT (SOAP):**
```
# Producción
https://cfdi.sat.gob.mx/nuevocontribuyente/

# WSDL de timbrado (vía PAC, no directo)
Los PACs autorizados exponen REST/SOAP que a su vez hablan con el SAT.
```

**Autenticación:** CSD (Certificado de Sello Digital) + FIEL (e.firma) — archivos .cer, .key + contraseña

**Documentación oficial:**
- Portal SAT: https://www.sat.gob.mx/planes-y-programas/70273.html
- Especificación técnica CFDI 4.0: http://www.sat.gob.mx/informacion_fiscal/factura_electronica/Documents/Anexo20.pdf
- Catálogos: http://www.sat.gob.mx/informacion_fiscal/factura_electronica/Documents/catCFDI.xls

**Limitaciones:**
- No hay API REST directa — todo pasa por PACs autorizados
- Los web services SOAP del SAT tienen alta latencia y disponibilidad variable
- El SAT requiere FIEL/e.firma para operaciones críticas (cancelación, descarga masiva)

**Recomendación:** No intentar hablar directamente con el SAT. Usar un PAC (Facturapi, FiscalAPI, etc.) que abstraiga la complejidad.

### 1.2 Consulta de CFDIs Emitidos/Recibidos

**Portal:** https://www.sat.gob.mx/aplicacion/login/53027/genera-tus-reportes-de-emision-y-recepcion

**Servicios disponibles:**
- **Descarga Masiva de CFDIs:** Permite descargar XML de CFDIs emitidos/recibidos
  - Web service SOAP: `https://cfdi.sat.gob.mx/WS/DescargaMasivaService.svc`
  - Requiere FIEL + Solicitud de descarga por UUID, RFC, fecha
  - Tiempo de procesamiento: 24-72 horas para paquetes grandes
- **Consulta individual por UUID:** No existe servicio público; se verifica validando el XML

**Integración recomendada:** FiscalAPI y Facturapi ofrecen módulos de Descarga Masiva que abstraen el proceso del SAT:
- FiscalAPI: Módulo adicional $99 MXN/mes por RFC
- Facturapi: Producto de Descarga Masiva integrado

### 1.3 Validación de RFC

**Servicio del SAT:**
- Portal web: https://www.sat.gob.mx/aplicacion/login/46899/verifica-tu-rfc-con-huella-digital
- No hay API pública directa

**Endpoints vía PACs/APIs:**

| Servicio | Endpoint | Método |
|----------|----------|--------|
| **Facturapi** | `GET /tools/validate_tax_id` | REST API |
| **FiscalAPI** | Validador de RFC integrado | Dashboard + API |

**Facturapi — Ejemplo de validación:**
```bash
curl https://www.facturapi.io/v2/tools/validate_tax_id \
  -H "Authorization: Bearer sk_live_XXXX" \
  -d "tax_id=WXKE800401B12"
```

**Respuesta típica:**
```json
{
  "legal_name": "KIM WEXLER",
  "tax_system": "612",
  "zip": "06600",
  "status": "active"
}
```

### 1.4 Consulta 69-B (EFOS — Empresas Facturadoras de Operaciones Simuladas)

**Portal SAT:** https://www.sat.gob.mx/consultas/46347/consulta-de-contribuyentes-con-sentencia-favorable-de-69-b
- Se consulta por RFC individual o lista masiva en PDF/Excel
- No hay API — es un listado estático publicado periódicamente

**Integración para agentes:**
- Descargar el listado 69-B del SAT periódicamente
- Comparar RFCs contra la lista antes de timbrar
- Facturapi ya incluye verificación contra "lista negra" del SAT en su endpoint de validación

### 1.5 Buzón Tributario

**Portal:** https://www.sat.gob.mx/tramites/buzontributario
- Acceso con RFC + contraseña o FIEL
- Comunicaciones oficiales del SAT al contribuyente
- Notificaciones de inconsistencias, requerimientos

**Integración directa:** No existe API. Alternativas:
- Web scraping con Playwright/Selenium (riesgoso, puede violar ToS)
- Solicitar al contribuyente acceso a su buzón
- Algunos sistemas como CONTPAQi integran lectura del buzón

### 1.6 Envío de Declaraciones (DIOT, Provisionales, Anuales)

**DIOT (Declaración Informativa de Operaciones con Terceros):**
- Portal: https://www.sat.gob.mx/declaraciones/informativas/70000-70299
- Se envía vía portal web con CIEC/FIEL
- Formato: TXT delimitado por pipes según especificación del SAT
- No hay API pública

**Declaraciones Provisionales/Anuales:**
- Portal: DeclaraSAT (aplicación de escritorio) o portal web
- ISR, IVA, IDE
- Requiere FIEL para declaraciones con saldo a favor

**Para agentes contables:**
- Generar el TXT de DIOT programáticamente (formato documentado)
- El envío final requiere intervención humana o simulación del portal
- Considerar integración con CONTPAQi/Aspel que generan formatos listos para enviar

### 1.7 Cancelación de CFDIs

**Servicio SAT (SOAP):**
- Endpoint: `https://cfdi.sat.gob.mx/WS/CancelaCFDService.svc`
- Requiere FIEL (certificado .cer/.key + contraseña)
- Tipos de cancelación:
  1. **Sin aceptación del receptor** (CFDI global, nómina, egreso)
  2. **Con aceptación del receptor** (CFDI de ingreso — el receptor debe aceptar)

**Vía PACs (recomendado):**

```bash
# Facturapi
DELETE /invoices/{invoice_id}

# FiscalAPI
DELETE /api/invoices/{invoice_id}
```

**Flujo con aceptación:**
1. Emisor solicita cancelación → PAC → SAT
2. SAT notifica al receptor (plazo de 3 días hábiles)
3. Receptor acepta/rechaza vía su portal o PAC
4. Si no responde, se cancela automáticamente

### 1.8 Firma Electrónica (e.firma / FIEL)

**Descripción:** Certificado digital X.509 emitido por el SAT para identificación y firma de documentos.

**Componentes:**
- Archivo `.cer` — Certificado (público)
- Archivo `.key` — Llave privada
- Contraseña de la llave privada

**Uso en agentes contables:**
- Timbrado de CFDIs (requiere CSD, no FIEL)
- Cancelación de CFDIs (requiere FIEL)
- Descarga masiva de CFDIs (requiere FIEL)
- Envío de declaraciones (requiere FIEL)
- Representación legal ante el SAT

**Almacenamiento seguro recomendado:**
```python
# Ejemplo de estructura en sistema de archivos cifrado
certificates/
├── {rfc}/
│   ├── csd.cer          # Certificado de Sello Digital
│   ├── csd.key          # Llave privada CSD
│   ├── csd_password.txt # Contraseña (cifrar en reposo)
│   ├── fiel.cer         # FIEL
│   ├── fiel.key         # Llave privada FIEL
│   └── fiel_password.txt
```

### 1.9 CSD (Certificado de Sello Digital)

**Generación:**
- Portal SAT: https://www.sat.gob.mx/tramites/75229/genera-tu-certificado-de-sello-digital
- Requiere FIEL vigente
- Vigencia: 4 años

**Uso:** Firma electrónica de CFDIs — timbrado y cancelación

**Para PACs:** Se debe subir el CSD (.cer + .key + contraseña) al PAC para que pueda timbrar en nombre del emisor.

---

## 2. Facturadores Electrónicos (APIs)

### 2.1 Facturapi ⭐ RECOMENDADO

**URL:** https://www.facturapi.io
**Documentación API:** https://docs.facturapi.io/api/
**Tutoriales:** https://docs.facturapi.io/docs/intro/
**GitHub:** https://github.com/facturapi

**Descripción:** API REST completa para emisión, timbrado, cancelación y gestión de CFDIs. Multi-RFC. El más popular entre startups y SaaS mexicanos.

**Autenticación:**
```
Header: Authorization: Bearer sk_live_XXXXX
- Test Key: sk_test_XXXXX (ambiente de pruebas)
- Live Key: sk_live_XXXXX (producción, timbra ante SAT)
```

**Endpoints principales:**

| Recurso | Método | Endpoint | Descripción |
|---------|--------|----------|-------------|
| **Clientes** | POST | `/v2/customers` | Crear cliente |
| | GET | `/v2/customers` | Listar clientes |
| | GET | `/v2/customers/{id}` | Obtener cliente |
| | PUT | `/v2/customers/{id}` | Editar cliente |
| | DELETE | `/v2/customers/{id}` | Eliminar cliente |
| | POST | `/v2/customers/{id}/send_edit_link` | Enviar enlace de edición |
| | GET | `/v2/tools/validate_tax_id` | Validar RFC |
| **Productos** | POST | `/v2/products` | Crear producto |
| | GET | `/v2/products` | Listar productos |
| | GET | `/v2/products/{id}` | Obtener producto |
| **Facturas** | POST | `/v2/invoices` | **Crear y timbrar CFDI 4.0** |
| | GET | `/v2/invoices` | Listar facturas |
| | GET | `/v2/invoices/{id}` | Obtener factura |
| | DELETE | `/v2/invoices/{id}` | **Cancelar factura** |
| | GET | `/v2/invoices/{id}/download/pdf` | Descargar PDF |
| | GET | `/v2/invoices/{id}/download/xml` | Descargar XML |
| | POST | `/v2/invoices/{id}/send_by_email` | Enviar por email |
| | POST | `/v2/invoices/{id}/copy_to_draft` | Copiar a borrador |
| | POST | `/v2/invoices/preview` | Vista previa PDF |
| **Recibos** | POST | `/v2/receipts` | Crear recibo (E-Receipt) |
| | POST | `/v2/receipts/{id}/invoice` | Facturar recibo |
| | POST | `/v2/receipts/invoice_multiple` | Facturar múltiples |
| **Retenciones** | POST | `/v2/retentions` | Crear retención |
| | GET | `/v2/retentions` | Listar retenciones |
| | DELETE | `/v2/retentions/{id}` | Cancelar retención |
| **Organizaciones** | POST | `/v2/organizations` | Crear organización (RFC) |
| | PUT | `/v2/organizations/{id}/certificate` | Subir CSD |
| | PUT | `/v2/organizations/{id}/fiel` | Subir FIEL |
| **Webhooks** | POST | `/v2/webhooks` | Crear webhook |
| | GET | `/v2/webhooks` | Listar webhooks |
| **Herramientas** | GET | `/v2/catalogs/product_key` | Catálogo productos SAT |
| | GET | `/v2/catalogs/unit_code` | Catálogo unidades |

**Ejemplo Python:**
```python
from facturapi import Facturapi

client = Facturapi("sk_live_XXXXX")

# Crear factura CFDI 4.0
invoice = client.invoices.create({
    "customer": {
        "legal_name": "Kim Wexler",
        "tax_id": "WXKE800401B12",
        "tax_system": "601",  # General Ley PM
        "address": {"zip": "12345", "country": "MEX"}
    },
    "items": [{
        "quantity": 2,
        "product": {
            "description": "Servicio de consultoría",
            "product_key": "80101500",  # Servicios de consultoría
            "price": 5000.00
        }
    }],
    "payment_form": "03",  # Transferencia electrónica
    "payment_method": "PUE"  # Pago en una sola exhibición
})

# Enviar factura por email
client.invoices.send_by_email(invoice["id"], {"email": "kim@example.com"})
```

**Pricing (verificado 2026-08-01):**
- **API CFDI:** $299 MXN/mes + consumo
- **Costo por timbre:** $0.60 MXN (IVA incluido)
- **Multi-RFC:** Sin costo adicional por RFC emisor
- **Prueba gratuita:** 14 días sin costo
- **Almacenamiento:** CFDIs hasta 5 años
- **Facturación Web:** $199 MXN por organización/mes + consumo
- **E-Receipts:** $599 MXN por organización/mes + $0.40 MXN/recibo + $0.60 MXN/timbre

**SDKs oficiales:** Node.js, .NET, PHP, cURL

**Ventajas para Likida AI:**
- API REST limpia, fácil de integrar con Python
- Multi-RFC: perfecto para despachos con múltiples clientes
- Webhooks para notificaciones asíncronas
- Validación de RFC y catálogos SAT incluidos
- Descarga masiva disponible
- Costo bajo por timbre ($0.60 MXN)

---

### 2.2 FiscalAPI

**URL:** https://www.fiscalapi.com
**Documentación:** https://www.fiscalapi.com/docs (referencia API)
**GitHub:** https://github.com/fiscalapi
**Oficina:** Zapopan, Jalisco

**Descripción:** API REST para timbrado CFDI 4.0 con énfasis en simplicidad y multi-RFC. PAC autorizado.

**Autenticación:**
```
Header: x-api-key: tu_api_key
- Ambiente de pruebas: key de sandbox (sin costo, ilimitado)
- Producción: key de producción
```

**Endpoints principales:**

| Recurso | Método | Endpoint | Descripción |
|---------|--------|----------|-------------|
| **CFDI** | POST | `/api/v1/invoices` | Crear y timbrar factura |
| | GET | `/api/v1/invoices` | Listar facturas |
| | GET | `/api/v1/invoices/{uuid}` | Obtener factura por UUID |
| | DELETE | `/api/v1/invoices/{uuid}` | Cancelar factura |
| | GET | `/api/v1/invoices/{uuid}/xml` | Descargar XML |
| | GET | `/api/v1/invoices/{uuid}/pdf` | Descargar PDF |
| **Empresas** | POST | `/api/v1/companies` | Crear empresa (RFC) |
| | PUT | `/api/v1/companies/{id}/certificate` | Subir CSD |
| **Productos** | POST | `/api/v1/products` | Crear producto |
| | GET | `/api/v1/products` | Listar productos |
| **Clientes** | POST | `/api/v1/customers` | Crear cliente |
| | GET | `/api/v1/customers` | Listar clientes |
| **Descarga Masiva** | POST | `/api/v1/mass-download` | Solicitar descarga |
| | GET | `/api/v1/mass-download/{id}` | Estado de descarga |
| **Catálogos** | GET | `/api/v1/catalogs/*` | Catálogos SAT |
| **Validador** | GET | `/api/v1/tools/validate-rfc/{rfc}` | Validar RFC |

**Ejemplo Python:**
```python
import requests

API_KEY = "tu_api_key"
BASE = "https://www.fiscalapi.com/api/v1"

headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}

# Timbrar factura
invoice = requests.post(f"{BASE}/invoices", json={
    "version": "4.0",
    "type": "I",  # Ingreso
    "series": "A",
    "payment_form": "03",
    "payment_method": "PUE",
    "currency": "MXN",
    "issuer": {"id": "empresa_id"},
    "recipient": {"id": "cliente_id"},
    "items": [{"product_id": "prod_1", "quantity": 1, "discount": 0}]
}, headers=headers)
```

**Pricing (verificado 2026-08-01):**
- **Suscripción base:** $199 MXN/mes
- **Paquetes de timbres (no caducan):**
  - 100 timbres: $170.52 MXN ($1.71/timbre)
  - 500 timbres: $678.60 MXN ($1.36/timbre)
  - 1,000 timbres: $1,183.20 MXN ($1.18/timbre)
  - 5,000 timbres: $4,176.00 MXN ($0.84/timbre)
  - 10,000 timbres: $7,482.00 MXN ($0.75/timbre)
  - 50,000 timbres: $28,710.00 MXN ($0.57/timbre)
  - 100,000 timbres: $48,720.00 MXN ($0.49/timbre)
- **Descarga Masiva:** $99 MXN/mes por RFC (requiere suscripción base)
- **Descuento anual:** 10%
- **Pruebas:** Ilimitadas, sin costo

**SDKs oficiales:** C#, Python, JavaScript, PHP, Java

**Ventajas para Likida AI:**
- Pricing escalado favorable para alto volumen ($0.49/timbre a 100K)
- Descarga Masiva integrada
- Multi-RFC nativo
- SDK Python oficial

---

### 2.3 Finkok

**URL:** https://www.finkok.com
**Contacto:** info@finkok.com, Tel: +52 (55) 46-24-01-81
**Oficina:** Morelia, Michoacán

> ⚠️ **ADVERTENCIA:** Finkok tuvo su autorización como PAC revocada por el SAT en 2019. Verificar estatus actual antes de integrarse.

**Descripción:** Facturación electrónica OnDemand. Modelo de pago por consumo sin pago anticipado.

**Modelo de integración:**
- Asignan un "experto integrador de sistemas" sin costo
- Integración vía API (SOAP/XML) + REST
- Facturación OnDemand: paga solo lo que consumes al final de 30 días

**API (SOAP/REST):**
```xml
<!-- Endpoint SOAP -->
https://facturacion.finkok.com/sandbox.php
https://facturacion.finkok.com/invoice.php

<!-- Operaciones principales -->
- stamp: Timbrar CFDI
- cancel: Cancelar CFDI
- sign: Firmar XML
- query: Consultar CFDI
```

**Autenticación:** Usuario + contraseña asignados por Finkok

**Pricing:**
- **Sin costo de suscripción** — solo pagas por timbres usados
- **Costo por timbre:** No publicado — contactar para cotización
- **Integración:** Sin costo

**Limitaciones:**
- Estatus de PAC cuestionable (revocado en 2019)
- Documentación API escasa/obsoleta
- Interfaz menos moderna que competidores

---

### 2.4 SW Sapien (Sapien)

**URL:** https://sapien.com.mx
**Tipo:** Suite fiscal completa (no solo API)

**Descripción:** Plataforma de facturación electrónica con múltiples productos: timbrado, nómina, contabilidad, reportes. Orientada a empresas medianas/grandes.

**Productos principales:**
- Facturación electrónica (CFDI 4.0)
- Nómina electrónica (Nómina 1.2)
- Complemento de Pago
- Carta Porte
- Reportes fiscales
- Contabilidad electrónica

**Integración:**
- API REST para timbrado
- Conectores para ERPs (CONTPAQi, Aspel, SAP)
- Web services SOAP legacy

**Pricing:** No público — contacto directo con ventas

**Documentación:** https://sapien.com.mx/docs (requiere registro)

---

### 2.5 Timbox

**URL:** https://timbox.com.mx
**Tipo:** PAC autorizado

**Descripción:** Proveedor de Certificación de CFDI con API de timbrado.

**Servicios:**
- Timbrado de CFDI 4.0
- Cancelación de CFDIs
- Nómina electrónica
- Carta Porte
- Validación de XML

**API:**
- Endpoint base: `https://services.timbox.com.mx`
- Autenticación: API key
- Formato: XML/SOAP y REST (JSON)

**Pricing:** No público — contacto directo

**Notas:** Documentación API limitada. Más orientado a integración vía partners/consultores.

---

### 2.6 Compac / CONTPAQi Factura Electrónica

**URL:** https://www.contpaqi.com/contpaqi-factura-electronica
**Tipo:** Software desktop + nube

**Descripción:** Módulo de facturación electrónica de CONTPAQi. Se integra con los demás productos de la suite (Contabilidad, Nóminas, Comercial).

**Productos relevantes:**
- **CONTPAQi Factura Electrónica®** — Desktop
- **CONTPAQi CFDI Facturación en Línea+®** — Nube
- **CONTPAQi Timbra®** — Servicio de timbrado en la nube

**Integración:**
- SDK COM/ActiveX para integración desde desktop
- CONTPAQi Timbra: API REST para timbrado desde la nube
- Base de datos: SQL Server local (estructura documentada parcialmente)
- Acceso vía ODBC/OLE DB para lectura de datos contables

**Pricing:**
- Licenciamiento por usuario/estación
- CONTPAQi Timbra: por volumen de timbres
- Contactar distribuidor autorizado

**Limitaciones:**
- SDK legacy (COM, no moderno)
- Documentación de base de datos no oficial
- Integración directa requiere conocimiento del esquema de BD

---

## 3. ERPs Mexicanos (Integración)

### 3.1 CONTPAQi Suite

**URL:** https://www.contpaqi.com
**Cuota de mercado:** Líder en México para despachos contables y PYMEs

**Productos y sus integraciones:**

| Producto | Tipo | Base de Datos | API/SDK |
|----------|------|---------------|---------|
| CONTPAQi Contabilidad® | Desktop | SQL Server | SDK COM, ODBC |
| CONTPAQi Nóminas® | Desktop | SQL Server | SDK COM, ODBC |
| CONTPAQi Bancos® | Desktop | SQL Server | SDK COM, ODBC |
| CONTPAQi Comercial Premium® | Desktop | SQL Server | SDK COM, ODBC |
| CONTPAQi Comercial Pro® | Desktop | SQL Server | SDK COM, ODBC |
| CONTPAQi XML en Línea+® | Desktop | SQL Server | Lectura XML |
| CONTPAQi Contabiliza® | Nube | API REST | REST API |
| CONTPAQi Timbra® | Nube | API REST | REST API |
| CONTPAQi Vende® | Nube | API REST | REST API |

**Esquema de base de datos (CONTPAQi Contabilidad — SQL Server):**
```sql
-- Tablas principales (estructura aproximada)
dbo.ACUENTAS          -- Catálogo de cuentas contables
dbo.ACONCEPTOS        -- Pólizas (encabezados)
dbo.AMOVIMIENTOS      -- Movimientos contables (partidas)
dbo.APOLIZAS          -- Pólizas contables
dbo.APERIODO          -- Periodos contables
dbo.AEMPRESA          -- Datos de la empresa
dbo.ACONFIGURACION    -- Configuración del sistema

-- CONTPAQi Comercial (adicional)
dbo.ADMCIDOCUMENTOS   -- Facturas/documentos
dbo.ADMCIMOVTO        -- Movimientos de inventario
dbo.ADMCICLIENTES     -- Clientes
dbo.ADMCIPROVEEDORES  -- Proveedores
dbo.ADMCIPRODUCTOS    -- Productos
```

**Integración para agentes Likida:**
```python
# Conexión directa a BD CONTPAQi vía pyodbc
import pyodbc

conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=localhost;'
    'DATABASE=CONTPAQi_Contabilidad;'
    'UID=sa;PWD=password'
)

# Leer pólizas
cursor = conn.execute("""
    SELECT c.cNombreConcepto, p.cFecha, m.cImporte, m.cReferencia
    FROM ACONCEPTOS c
    JOIN APOLIZAS p ON c.cIdConcepto = p.cIdConcepto
    JOIN AMOVIMIENTOS m ON p.cIdPoliza = m.cIdPoliza
    WHERE p.cFecha BETWEEN '2026-01-01' AND '2026-12-31'
""")
```

**SDK COM (legacy):**
```csharp
// CONTPAQi COM SDK — C#/.NET
// Cargar librería
dynamic contpaqi = Activator.CreateInstance(
    Type.GetTypeFromProgID("CONTPAQi.Contabilidad"));

// Abrir empresa
contpaqi.AbreEmpresa("C:\\CONTPAQi\\Empresa\\");
var polizas = contpaqi.LeePolizas(periodo: 1);
```

**Notas importantes:**
- La BD SQL Server es la vía más confiable para integración programática
- El SDK COM es legacy pero funcional
- CONTPAQi Contabiliza (nube) tiene API REST moderna pero cobertura limitada
- Los distribuidores controlan acceso a documentación técnica avanzada

---

### 3.2 Aspel (COI, FAX, NOI)

**URL:** https://www.aspel.com.mx
**Productos contables:**

| Producto | Descripción | BD |
|----------|-------------|-----|
| Aspel COI 8.0 | Contabilidad integral | SQL Server / Btrieve |
| Aspel FAX 6.0 | Facturación electrónica | SQL Server |
| Aspel NOI 8.0 | Nómina | SQL Server / Btrieve |

**Integración:**
- Acceso a base de datos vía ODBC/OLE DB
- SDK COM (Aspel SDK) para integración programática
- Plugins y complementos disponibles
- Aspel SAE: sistema de punto de venta integrado

**Estructura de BD (Aspel COI — Btrieve/SQL):**
```
-- Archivos principales
CUENTA.DB    -- Catálogo de cuentas
POLIZA.DB    -- Pólizas contables
MOVTO.DB     -- Movimientos
EMPRESA.DB   -- Datos empresa
PERIODO.DB   -- Periodos
```

**Limitaciones:**
- Btrieve/Pervasive SQL como motor de BD (no trivial de consultar remotamente)
- SDK COM desactualizado
- Documentación técnica escasa
- Migración a SQL Server en versiones recientes

---

### 3.3 Sage México

**URL:** https://www.sage.com/es-mx
**Productos:**
- Sage 50 (contabilidad PYME)
- Sage 100 (ERP mediano)
- Sage 300 (ERP corporativo)
- Sage X3 (enterprise)

**Integración:**
- API REST para Sage X3 y Sage Intacct
- SDK .NET para Sage 50/100
- ODBC para acceso a base de datos
- Integradores de terceros

**Pricing:** Enterprise pricing — contacto directo

**Para agentes contables mexicanos:**
- Sage 50 México: más usado en PYMEs
- Integración vía base de datos (SQL Server)
- Limitada documentación de API pública para versiones mexicanas

---

### 3.4 SAP Business One

**URL:** https://www.sap.com/mexico/products/business-one.html
**Tipo:** ERP para empresas medianas

**Integración:**
- **Service Layer (API REST):** `https://server:50000/b1s/v1/`
  - Autenticación: Login con usuario SAP
  - CRUD completo de entidades contables
  - Documentación: SAP Business One Service Layer Reference
- **DI API (SDK .NET):** Para integraciones más profundas
- **DI Server (SOAP):** Para integraciones servidor a servidor

**Endpoints Service Layer (ejemplos):**
```bash
# Login
POST https://server:50000/b1s/v1/Login
{"CompanyDB": "SBODemoMX", "UserName": "manager", "Password": "xxx"}

# Obtener journal entries
GET https://server:50000/b1s/v1/JournalEntries

# Obtener facturas de compra
GET https://server:50000/b1s/v1/PurchaseInvoices

# Obtener cuentas contables
GET https://server:50000/b1s/v1/ChartOfAccounts
```

**Pricing:**
- Licencia named user: ~$3,000-5,000 USD/año
- Implementación: $10,000-50,000 USD según complejidad
- Partner ecosystem en México activo

**Para agentes contables:**
- Service Layer es la vía moderna recomendada
- Acceso completo a datos contables y financieros
- Ideal para empresas medianas con presupuesto SAP

---

### 3.5 QuickBooks México

**URL:** https://quickbooks.intuit.com/mx/
**Tipo:** Contabilidad en la nube para PYMEs

**Integración:**
- **QuickBooks Online API (REST):**
  - Base URL: `https://quickbooks.api.intuit.com/v3/company/{companyId}/`
  - OAuth 2.0 para autenticación
  - Documentación: https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account

**Endpoints principales:**
```bash
# Obtener cuentas
GET /v3/company/{id}/query?query=SELECT * FROM Account

# Obtener facturas
GET /v3/company/{id}/query?query=SELECT * FROM Invoice

# Obtener transacciones de banco
GET /v3/company/{id}/query?query=SELECT * FROM BankTransaction

# Crear factura
POST /v3/company/{id}/invoice
```

**Autenticación OAuth 2.0:**
```
Client ID:     qbodexxxxxxxxxxx
Client Secret: xxxxxxxxxxxxxxxx
Redirect URI:  https://tu-app.com/callback
Scopes:        com.intuit.quickbooks.accounting
```

**Pricing México:**
- Simple Start: ~$280 MXN/mes
- Essentials: ~$450 MXN/mes
- Plus: ~$680 MXN/Mes
- Advanced: ~$1,200 MXN/mes

**Limitaciones:**
- API de QuickBooks Online (no desktop)
- Rate limit: 500 requests/minuto
- No soporta CFDI directamente (requiere integración adicional)
- Datos contables limitados vs ERP completo

---

### 3.6 Odoo (Open Source)

**URL:** https://www.odoo.com/es
**Tipo:** ERP open source, modular

**Integración:**
- **XML-RPC / JSON-RPC:** Protocolo nativo
- **REST API:** Disponible desde Odoo 15+
- **Módulos de contabilidad mexicana:** Localización MX oficial

**API JSON-RPC (Odoo 16+):**
```python
import json, requests

URL = "https://tu-odoo.com"
DB = "tu_base_de_datos"

# Autenticación
auth = requests.post(f"{URL}/web/session/authenticate", json={
    "jsonrpc": "2.0",
    "params": {"login": "admin", "password": "xxx", "db": DB}
})
session_id = auth.cookies.get("session_id")

# Leer facturas
response = requests.post(f"{URL}/web/dataset/call_kw", json={
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "model": "account.move",
        "method": "search_read",
        "args": [[["move_type", "=", "out_invoice"]]],
        "kwargs": {"fields": ["name", "partner_id", "amount_total", "invoice_date"]}
    }
}, cookies={"session_id": session_id})
```

**Endpoints REST (Odoo 16+):**
```bash
GET  /api/account.move          # Listar facturas
POST /api/account.move          # Crear factura
GET  /api/account.move/{id}     # Obtener factura
GET  /api/account.account       # Listar cuentas contables
GET  /api/account.journal       # Listar diarios
GET  /api/res.partner           # Listar contactos
```

**Módulos de localización México:**
- `l10n_mx` — Plan contable mexicano, CFDI 3.3/4.0
- `l10n_mx_edi` — Facturación electrónica CFDI
- Integración con PACs (Facturapi, SW Sapien, etc.)

**Pricing:**
- **Community (open source):** Gratis — self-hosted
- **Enterprise:** Desde ~$24.90 USD/usuario/mes
- **Odoo.sh (hosted):** Desde ~$75.20/mes

**Ventajas para agentes contables:**
- Open source = acceso completo al código y BD
- Localización MX oficial y mantenida
- API moderna y bien documentada
- Comunidad activa en México
- Se puede auto-hospedar con control total

---

### 3.7 Bind ERP

**URL:** https://www.bind.com.mx
**Tipo:** ERP cloud mexicano

**Descripción:** ERP 100% mexicano en la nube. Módulos: facturación, inventarios, cuentas por cobrar/pagar, contabilidad, compras.

**Integración:**
- API REST disponible para clientes enterprise
- Webhooks para notificaciones
- Integración con plataformas de e-commerce
- No documentación pública de API detallada

**Pricing:**
- Planes desde ~$990 MXN/mes
- Facturación electrónica incluida (timbres incluidos según plan)

**Limitaciones:**
- API menos documentada que competidores
- Ecosistema más cerrado
- Menos flexible para integraciones custom

---

## 4. Banca y Pagos

### 4.1 SPEI (Sistema de Pagos Electrónicos Interbancarios — Banxico)

**URL:** https://www.banxico.org.mx/sistemas-de-pago/spei.html
**Operador:** Banco de México (Banxico)

**Descripción:** Sistema de transferencias interbancarias en tiempo real. Operado por Banxico. Disponible 24/7/365.

**Características:**
- Transferencias instantáneas (segundos)
- Montos: $0.01 a $999,999.99 por operación (límites por banco)
- CLABE interbancaria (18 dígitos) como identificador de cuenta
- Disponible para personas físicas y morales

**Integración directa:**
- ❌ No hay API directa de Banxico para enviar SPEI
- ✅ Cada banco ofrece su propia API para operaciones SPEI
- ✅ STP (Sistema de Transferencias y Pagos) ofrece API para fintechs

**STP (Proveedor tecnológico):**
- URL: https://www.stpmex.com
- API REST para envío de SPEIs programáticamente
- Usado por fintechs como Cuenca, Kueski, etc.
- Requiere contrato directo con STP

```bash
# STP API — Envío de transferencia
POST https://services.stpmex.com/ordenPago
Authorization: Bearer {token}
Content-Type: application/json

{
    "claveRastreo": "TEST12345678",
    "conceptoPago": "Pago de servicios",
    "cuentaBeneficiario": "646180157000000004",
    "cuentaOrdenante": "646180157000000005",
    "empresa": "EMPRESA01",
    "institucionContraparte": "90646",
    "institucionOperante": "90646",
    "monto": 1500.00,
    "nombreBeneficiario": "Juan Perez",
    "nombreOrdenante": "Empresa SA",
    "rfcCurpBeneficiario": "PEGJ800101XXX",
    "rfcCurpOrdenante": "EMP010101XXX",
    "tipoCuentaBeneficiario": 40,
    "tipoCuentaOrdenante": 40,
    "tipoPago": 1
}
```

### 4.2 CoDi (Cobros Digitalizados)

**URL:** https://www.banxico.org.mx/transferencias-y-pagos/codi.html
**Operador:** Banxico, desarrollado con Banxico y bancos

**Descripción:** Sistema de cobros mediante códigos QR y NFC. Permite cobrar sin terminal bancaria.

**Cómo funciona:**
1. Comercio genera QR (estático o dinámico)
2. Cliente escanea con app de su banco
3. Autoriza el pago
4. SPEI procesa la transferencia

**Integración:**
- CoDi **no tiene API directa** para comercios
- Se integra vía los bancos que ofrecen generación de QR
- Cada banco tiene su SDK/API para generar QRs CoDi

**Alternativas para agentes:**
- Usar SPEI directamente (transferencia bancaria)
- Integrar con plataformas de cobro (Conekta, Stripe) que soportan SPEI
- Solicitar al banco partner la generación de QRs CoDi

### 4.3 APIs Bancarias en México

#### BBVA México
- **Portal desarrolladores:** https://developers.bbva.mx (legacy) / https://www.bbva.mx/empresas/productos/pagos-y-cobros/api-bbva.html
- **APIs disponibles:** SPEI, cobros, consultas de cuenta
- **Autenticación:** OAuth 2.0 con certificado digital
- **Documentación:** Requiere registro como partner
- **Limitaciones:** Proceso de onboarding largo, aprobación manual

#### Banorte
- **Portal:** https://api.market.banorte.com
- **APIs disponibles:** SPEI, cobros, consulta de saldos, DIOT
- **Autenticación:** API Key + certificado
- **Pricing:** Por transacción — contacto con Banorte Empresas
- **Notas:** Banorte tiene alianza con CONTPAQi

#### Santander México
- **Portal:** https://developers.santander.com.mx (puede requerir registro)
- **APIs disponibles:** SPEI, cobros, consulta de movimientos
- **Autenticación:** OAuth 2.0
- **Documentación:** Limitada públicamente

#### Citibanamex
- **Portal:** https://developer.citi.com (global, incluye México)
- **APIs disponibles:** Cuentas, transacciones, pagos
- **Autenticación:** OAuth 2.0 + certificados
- **Limitaciones:** Menos APIs específicas para México

#### Banregio
- **Portal:** No público
- **Contacto:** Área de Banca Empresarial
- **APIs disponibles:** SPEI, cobros básicos

### 4.4 Open Banking México

**Regulación:** CNBV (Comisión Nacional Bancaria y de Valores)
**Estado actual (2026):**

- La Ley Fintech (2018) establece el marco para Open Banking
- La CNBV ha publicado disposiciones para APIs abiertas
- **Estado:** En implementación gradual
- Los bancos deben compartir datos (cuentas, tarjetas, pagos) vía APIs
- Proveedores de servicios (TPVs, fintechs) pueden acceder con autorización del usuario

**APIs abiertas disponibles:**
- Catálogos de CLABES y sucursales (Banxico)
- Tipo de cambio (Banxico — API pública)
- Ubicación de sucursales/ATMs

### 4.5 Conekta

**URL:** https://www.conekta.com
**Documentación:** https://developers.conekta.com/docs
**Changelog:** https://developers.conekta.com/docs/changelog

**Descripción:** Plataforma de pagos mexicana. Líder en México para cobros online. Soporta tarjetas, OXXO, SPEI, transferencias, Apple Pay, Google Pay.

**Autenticación:**
```bash
# API Keys
Header: Authorization: Bearer key_live_xxx    # Producción
Header: Authorization: Bearer key_test_xxx    # Pruebas
```

**Endpoints principales:**

| Recurso | Método | Endpoint | Descripción |
|---------|--------|----------|-------------|
| **Órdenes** | POST | `/orders` | Crear orden/cargo |
| | GET | `/orders/{id}` | Obtener orden |
| | PUT | `/orders/{id}` | Actualizar orden |
| | POST | `/orders/{id}/charges` | Crear cargo |
| | POST | `/orders/{id}/refunds` | Reembolsar |
| **Clientes** | POST | `/customers` | Crear cliente |
| | GET | `/customers` | Listar clientes |
| **Suscripciones** | POST | `/plans` | Crear plan |
| | POST | `/subscription` | Crear suscripción |
| **Checkout** | POST | `/checkouts` | Crear checkout link |
| **Webhooks** | POST | `/webhooks` | Crear webhook |

**Métodos de pago soportados:**
- 💳 Tarjetas (Visa, Mastercard, Amex)
- 🏪 OXXO (efectivo)
- 🏦 Transferencia SPEI
- 📱 Apple Pay / Google Pay
- 💰 Pago en plazos (meses sin intereses)
- 🔄 Cobros recurrentes

**Ejemplo — Crear cargo con OXXO:**
```python
import conekta

conekta.api_key = "key_live_xxx"

order = conekta.Order.create({
    "line_items": [{
        "name": "Servicio contable mensual",
        "unit_price": 500000,  # En centavos
        "quantity": 1
    }],
    "customer": {
        "name": "Juan Pérez",
        "email": "juan@empresa.com",
        "phone": "+525512345678"
    },
    "charges": [{
        "payment_method": {
            "type": "oxxo_cash"
        }
    }]
})
```

**Pricing:**
- **Tarjetas:** 2.9% + $2.50 MXN por transacción
- **OXXO:** $5 MXN por transacción
- **SPEI:** $5 MXN por transacción
- **Transferencia:** $5 MXN por transacción
- **Sin mensualidad** — solo pago por transacción

**SDKs:** Node.js, PHP, Ruby, Python, Java, .NET

---

### 4.6 Stripe México

**URL:** https://stripe.com/mx
**Documentación:** https://stripe.com/docs/api
**Referencia API:**

**Descripción:** Plataforma de pagos global con presencia en México. Soporta cobros internacionales y locales.

**Autenticación:**
```bash
Header: Authorization: Bearer sk_live_xxx   # Secret key
Header: Authorization: Bearer pk_live_xxx   # Publishable key
```

**Endpoints principales:**

| Recurso | Método | Endpoint | Descripción |
|---------|--------|----------|-------------|
| **Payment Intents** | POST | `/v1/payment_intents` | Crear intento de pago |
| | GET | `/v1/payment_intents/{id}` | Obtener intento |
| | POST | `/v1/payment_intents/{id}/confirm` | Confirmar pago |
| **Customers** | POST | `/v1/customers` | Crear cliente |
| **Subscriptions** | POST | `/v1/subscriptions` | Crear suscripción |
| **Charges** | POST | `/v1/charges` | Crear cargo directo |
| **Invoices** | POST | `/v1/invoices` | Crear factura (no fiscal) |
| **Payouts** | GET | `/v1/payouts` | Listar retiros |
| **Checkout** | POST | `/v1/checkout/sessions` | Crear sesión checkout |

**Métodos de pago México:**
- 💳 Tarjetas (Visa, Mastercard, Amex)
- 🏦 OXXO Pay
- 📱 SPEI (transferencia)
- 🍎 Apple Pay

**Ejemplo Python:**
```python
import stripe
stripe.api_key = "sk_live_xxx"

# Crear cargo con OXXO
payment_intent = stripe.PaymentIntent.create(
    amount=500000,  # $5,000.00 MXN en centavos
    currency="mxn",
    payment_method_types=["oxxo"],
    customer="cus_xxx",
    metadata={"invoice_month": "2026-08"}
)
```

**Pricing México:**
- **Tarjetas:** 3.6% + $3.00 MXN por transacción
- **OXXO:** $10 MXN por transacción
- **SPEI:** 2.9% + $3.00 MXN por transacción
- **Sin mensualidad**

**Ventajas:**
- API extremadamente bien documentada
- Ecosistema de integraciones amplio
- Facturapi ofrece integración directa con Stripe para CFDI
- Webhooks robustos

**Limitaciones vs Conekta:**
- Pricing ligeramente más alto en México
- Menos métodos de pago locales
- Menos presencia de soporte local

---

### 4.7 Comparativa Pagos: Conekta vs Stripe MX

| Característica | Conekta | Stripe MX |
|----------------|---------|-----------|
| Tarjetas | 2.9% + $2.50 | 3.6% + $3.00 |
| OXXO | $5.00 | $10.00 |
| SPEI | $5.00 | 2.9% + $3.00 |
| Apple Pay | ✅ | ✅ |
| Google Pay | ✅ | ✅ |
| Meses sin intereses | ✅ | ❌ |
| Cobros recurrentes | ✅ | ✅ |
| SDK Python | ✅ | ✅ |
| Webhooks | ✅ | ✅ |
| Soporte en español | ✅ | Limitado |
| Integración CFDI | vía Facturapi | vía Facturapi |

**Recomendación para Likida AI:** Conekta para cobros (menor costo, más métodos MX), Stripe para clientes internacionales.

---

## 5. Tabla Comparativa Resumen

### Facturadores Electrónicos

| Servicio | Pricing | Multi-RFC | SDK Python | API REST | Descarga Masiva | Recomendado |
|----------|---------|-----------|------------|----------|-----------------|-------------|
| **Facturapi** | $299/mes + $0.60/timbre | ✅ | ❌ (Node, .NET, PHP) | ✅ | ✅ | ⭐⭐⭐ |
| **FiscalAPI** | $199/mes + paquetes | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐ |
| **Finkok** | OnDemand | ❓ | ❌ | SOAP/REST | ❌ | ⚠️ |
| **SW Sapien** | No público | ❓ | ❓ | ✅ | ❓ | ⭐⭐ |
| **Timbox** | No público | ❓ | ❓ | ✅ | ❓ | ⭐⭐ |
| **CONTPAQi Timbra** | Por volumen | ❓ | ❓ | ✅ | ❓ | ⭐⭐ |

### ERPs

| ERP | API moderna | BD local | Mercado MX | Costo | Integración |
|-----|------------|----------|------------|-------|-------------|
| **CONTPAQi** | COM/REST (nube) | SQL Server | Líder despachos | $$ | ODBC/COM |
| **Aspel** | COM | Btrieve/SQL | PYME popular | $ | ODBC |
| **SAP B1** | REST (Service Layer) | SAP HANA | Enterprise | $$$$ | REST |
| **QuickBooks** | REST (OAuth) | Cloud | Creciente | $$ | REST |
| **Odoo** | REST + XML-RPC | PostgreSQL | Startup/PYME | Gratis/$$ | REST |
| **Bind ERP** | REST (limitado) | Cloud | PYME | $ | REST |
| **Sage** | REST (X3) | SQL Server | Mediano | $$$ | REST |

### Pagos

| Servicio | SPEI | Tarjetas | OXXO | Cobros recurrentes | API REST |
|----------|------|----------|------|--------------------|----------| 
| **Conekta** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Stripe MX** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **STP** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **BBVA API** | ✅ | ❌ | ❌ | ❓ | ✅ |
| **Banorte API** | ✅ | ❌ | ❌ | ❓ | ✅ |

---

## 6. Recomendaciones para Likida AI

### Stack de Integración Recomendado

```yaml
facturacion:
  primario: Facturapi        # Multi-RFC, API limpia, bajo costo
  alternativo: FiscalAPI     # Mejor pricing a alto volumen
  justificacion: "Multi-RFC = 1 cuenta para todos los clientes del despacho"

pagos_cobros:
  primario: Conekta          # Más barato, más métodos MX
  alternativo: Stripe        # Para clientes internacionales
  justificacion: "Costo menor, OXXO, SPEI nativo"

erp_integracion:
  contpaqi_odbc: "Lectura directa a SQL Server para despachos CONTPAQi"
  odoo_api: "REST API para clientes con Odoo"
  quickbooks_api: "OAuth 2.0 para PYMEs con QuickBooks"
  
banca:
  spei: "STP API para envío de pagos programáticos"
  conciliacion: "Lectura de movimientos bancarios vía APIs bancarias"
```

### Arquitectura de Integración Propuesta

```
┌─────────────────────────────────────────────────────┐
│                   LIKIDA AI AGENTS                   │
│                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Agent    │ │ Agent    │ │ Agent    │ │ Agent  │ │
│  │ Fiscal   │ │ Nómina   │ │ Contab.  │ │ Cobros │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       │            │            │            │      │
└───────┼────────────┼────────────┼────────────┼──────┘
        │            │            │            │
   ┌────▼────┐  ┌────▼────┐  ┌───▼────┐  ┌───▼────┐
   │Facturapi│  │CONTPAQi │  │QuickBks│  │Conekta │
   │  API    │  │  ODBC   │  │  API   │  │  API   │
   └─────────┘  └─────────┘  └────────┘  └────────┘
        │            │            │            │
   ┌────▼────┐  ┌────▼────┐  ┌───▼────┐  ┌───▼────┐
   │   SAT   │  │SQL Server│  │ QB Cloud│  │ SPEI  │
   │  (PAC)  │  │ (local) │  │         │  │ OXXO  │
   └─────────┘  └─────────┘  └─────────┘  └───────┘
```

### Prioridades de Implementación

1. **Fase 1 — Facturación:** Facturapi API → Agent Fiscal
2. **Fase 2 — Contabilidad:** CONTPAQi ODBC → Agent Contabilidad  
3. **Fase 3 — Cobros:** Conekta → Agent Cobros
4. **Fase 4 — Nómina:** Facturapi nómina + CONTPAQi Nóminas
5. **Fase 5 — Banca:** STP SPEI + conciliación bancaria

### Variables de Entorno Necesarias

```env
# Facturapi
FACTURAPI_SECRET_KEY=sk_live_xxxxx
FACTURAPI_TEST_KEY=sk_test_xxxxx

# Conekta
CONEKTA_API_KEY=key_live_xxxxx
CONEKTA_WEBHOOK_SECRET=whsec_xxxxx

# CONTPAQi (BD local)
CONTPAQI_DB_HOST=localhost
CONTPAQI_DB_PORT=1433
CONTPAQI_DB_NAME=CONTPAQi_Contabilidad
CONTPAQI_DB_USER=readonly_user
CONTPAQI_DB_PASSWORD=xxxxx

# QuickBooks
QB_CLIENT_ID=xxxxx
QB_CLIENT_SECRET=xxxxx
QB_REDIRECT_URI=https://likida.ai/callback

# STP (SPEI)
STP_API_URL=https://services.stpmex.com
STP_EMPRESA=EMPRESA01
STP_PRIVATE_KEY=xxxxx
```

---

> **Nota:** Este documento debe actualizarse trimestralmente. Los precios, endpoints y disponibilidad de APIs cambian frecuentemente. Verificar siempre en las fuentes oficiales antes de implementar.
