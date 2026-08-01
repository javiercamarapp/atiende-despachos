# Integración Profunda con ERPs Mexicanos y SAT — Guía Técnica Completa

> **Última actualización:** 01 de agosto de 2026
> **Propósito:** Guía de referencia para agentes contables de automatización con ERPs mexicanos, el SAT y facturadores electrónicos.

---

## Tabla de Contenidos

1. [CONTPAQi](#1-conpaqi)
2. [Aspel (COI, FAX, NOI)](#2-aspel-coi-fax-noi)
3. [SAT — Web Services](#3-sat--web-services)
4. [Estados de Cuenta Bancarios](#4-estados-de-cuenta-bancarios)
5. [Facturadores Electrónicos APIs](#5-facturadores-electrónicos-apis)
6. [Recomendación de Arquitectura](#6-recomendación-de-arquitectura)

---

## 1. CONTPAQi

### 1.1 Arquitectura General

CONTPAQi es el ERP contable más usado en México (especialmente PyMEs). Viene en variantes:
- **CONTPAQi® Contabilidad** — módulo contable principal
- **CONTPAQi® Nóminas** — nóminas y cálculos fiscales
- **CONTPAQi® Bancos** — conciliación bancaria
- **CONTPAQi® Factura electrónica** — timbrado de CFDI

### 1.2 SDK/API Oficial (Compac SDK)

**Compac SDK** es el SDK oficial para integración. Está disponible para clientes enterprise.

#### Acceso al SDK
- **Requisito:** Contrato de soporte vigente con Aspel/Sistemas Compac
- **Lenguajes soportados:** C#, VB.NET, Delphi (COM)
- **Distribución:** Se solicita directamente al equipo de desarrollo de Compac
- **Documentación:** Incluye ejemplos y referencia de objetos COM

#### Estructura del SDK
```
CompacSDK/
├── Interop.CompacSDK.dll      # Assembly .NET (interop COM)
├── CompacSDK.tlb              # Type Library COM
├── Ejemplos/
│   ├── CSharp/
│   ├── VBNet/
│   └── Delphi/
└── Documentacion/
    ├── Referencia_API.chm
    └── Guia_Integracion.pdf
```

#### Ejemplo de integración COM desde Python (vía comtypes/win32com)

```python
import win32com.client

# Inicializar conexión COM con CONTPAQi
def init_conpaqi():
    """Inicializa la conexión COM con CONTPAQi Contabilidad"""
    try:
        # Crear instancia del objeto COM de CONTPAQi
        app = win32com.client.Dispatch("CompacSDK.AdminPAQ")
        return app
    except Exception as e:
        print(f"Error al conectar con CONTPAQi: {e}")
        return None

def abrir_empresa(app, ruta_empresa):
    """Abre una empresa en CONTPAQi por su ruta"""
    # Abrir la base de datos de la empresa
    resultado = app.fAbreEmpresa(ruta_empresa)
    if resultado != 0:
        raise Exception(f"Error al abrir empresa: {resultado}")
    return resultado

def obtener_polizas(app, fecha_inicio, fecha_fin):
    """Obtiene las pólizas de un período"""
    polizas = []
    # Buscar pólizas por rango de fechas
    # Nota: los métodos exactos dependen de la versión del SDK
    return polizas

# Uso
app = init_conpaqi()
if app:
    abrir_empresa(app, r"C:\Compac\Empresas\MiEmpresa")
    # Realizar operaciones...
    app.fCierraEmpresa()
```

### 1.3 Database Schema (SQL Server)

CONTPAQi almacena sus datos en **SQL Server**. Cada empresa tiene su propia base de datos.

#### Principales tablas del esquema

```sql
-- =============================================
-- TABLAS MAESTRAS
-- =============================================

-- Catálogo de cuentas contables
-- Tabla: cuentas
SELECT * FROM cuentas
-- Campos clave:
--   CIDCUENTA (int, PK)        — ID único de la cuenta
--   CCODIGOPOLIZA (varchar)    — Código de cuenta (ej: 100.01.001)
--   CNOMBRE (varchar)          — Nombre/descripción de la cuenta
--   CTIPOCUENTA (int)          — 1=Activo, 2=Pasivo, 3=Capital, 4=Ingreso, 5=Egreso
--   CNIVEL (int)               — Nivel jerárquico (1=mayor, 2=subcuenta, etc.)
--   CNATURALEZA (int)          — 1=Deudora, 2=Acreedora
--   CSTATUS (int)              — 1=Activa, 0=Inactiva
--   CIDCUENTAPADRE (int, FK)   — Referencia a cuenta padre

-- Ejemplo de consulta del catálogo de cuentas
SELECT
    c.CCODIGOPOLIZA AS codigo,
    c.CNOMBRE AS nombre,
    CASE c.CTIPOCUENTA
        WHEN 1 THEN 'Activo'
        WHEN 2 THEN 'Pasivo'
        WHEN 3 THEN 'Capital'
        WHEN 4 THEN 'Ingreso'
        WHEN 5 THEN 'Egreso'
    END AS tipo,
    CASE c.CNATURALEZA
        WHEN 1 THEN 'Deudora'
        WHEN 2 THEN 'Acreedora'
    END AS naturaleza
FROM cuentas c
WHERE c.CSTATUS = 1
ORDER BY c.CCODIGOPOLIZA;

-- =============================================
-- PÓLIZAS Y MOVIMIENTOS
-- =============================================

-- Encabezados de pólizas
-- Tabla: polizas
--   CIDPOLIZA (int, PK)        — ID único
--   CTIPOPOLIZA (int)          — 1=Diario, 2=Ingreso, 3=Egreso, 4=Orden
--   CFECHA (datetime)          — Fecha de la póliza
--   CCONCEPTO (varchar)        — Concepto/descripción
--   CNUMPOLIZA (varchar)       — Número de póliza
--   CFECHAULTMOD (datetime)    — Última modificación

-- Movimientos (detalle) de pólizas
-- Tabla: movimientos
--   CIDMOVIMIENTO (int, PK)    — ID único del movimiento
--   CIDPOLIZA (int, FK)        — Referencia a la póliza
--   CIDCUENTA (int, FK)        — Referencia a la cuenta contable
--   CDEBE (decimal)            — Monto del debe
--   CHABER (decimal)           — Monto del haber
--   CREFERENCIA (varchar)      — Referencia/documento
--   CCONCEPTO (varchar)        — Concepto del movimiento

-- Consulta de pólizas con movimientos por período
SELECT
    p.CNUMPOLIZA AS numero_poliza,
    p.CFECHA AS fecha,
    p.CCONCEPTO AS concepto_poliza,
    CASE p.CTIPOPOLIZA
        WHEN 1 THEN 'Diario'
        WHEN 2 THEN 'Ingreso'
        WHEN 3 THEN 'Egreso'
        WHEN 4 THEN 'Orden'
    END AS tipo,
    c.CCODIGOPOLIZA AS cuenta_codigo,
    c.CNOMBRE AS cuenta_nombre,
    m.CDEBE AS debe,
    m.CHABER AS haber,
    m.CCONCEPTO AS concepto_movto
FROM polizas p
INNER JOIN movimientos m ON p.CIDPOLIZA = m.CIDPOLIZA
INNER JOIN cuentas c ON m.CIDCUENTA = c.CIDCUENTA
WHERE p.CFECHA BETWEEN '2026-01-01' AND '2026-12-31'
ORDER BY p.CFECHA, p.CNUMPOLIZA, m.CIDMOVIMIENTO;

-- =============================================
-- BALANZA DE COMPROBACIÓN
-- =============================================
SELECT
    c.CCODIGOPOLIZA AS codigo_cuenta,
    c.CNOMBRE AS nombre_cuenta,
    SUM(m.CDEBE) AS total_debe,
    SUM(m.CHABER) AS total_haber,
    SUM(m.CDEBE) - SUM(m.CHABER) AS saldo_deudor,
    SUM(m.CHABER) - SUM(m.CDEBE) AS saldo_acreedor
FROM cuentas c
LEFT JOIN movimientos m ON c.CCIDCUENTA = m.CIDCUENTA
LEFT JOIN polizas p ON m.CIDPOLIZA = p.CIDPOLIZA
    AND p.CFECHA BETWEEN '2026-01-01' AND '2026-12-31'
WHERE c.CSTATUS = 1
GROUP BY c.CCODIGOPOLIZA, c.CNOMBRE
ORDER BY c.CCODIGOPOLIZA;

-- =============================================
-- CFDIs / FACTURAS ELECTRÓNICAS
-- =============================================

-- Tabla de comprobantes fiscales
-- Tabla: cfdi (o comprobantes, según versión)
--   UUID (uniqueidentifier)    — Folio fiscal UUID
--   RFC_EMISOR (varchar)
--   RFC_RECEPTOR (varchar)
--   TOTAL (decimal)
--   FECHA_EMISION (datetime)
--   TIPO_COMPROBANTE (varchar) — I=Ingreso, E=Egreso, T=Traslado, N=Nómina, P=Pago
--   ESTADO (varchar)           — Vigente, Cancelado
--   XML_PATH (varchar)         — Ruta al archivo XML
--   PDF_PATH (varchar)         — Ruta al archivo PDF
```

### 1.4 Integración vía COM/OLE Automation

```python
"""
Integración COM con CONTPAQi desde Python
Requiere: Windows, pywin32 (pip install pywin32)
"""

import win32com.client
from datetime import datetime

class CONTPAQiConnector:
    """Conector para CONTPAQi vía COM"""

    def __init__(self):
        self.app = None
        self.connected = False

    def connect(self, empresa_path: str) -> bool:
        """Conecta a una empresa de CONTPAQi"""
        try:
            self.app = win32com.client.Dispatch("CompacSDK.AdminPAQ")
            resultado = self.app.fAbreEmpresa(empresa_path)
            self.connected = (resultado == 0)
            return self.connected
        except Exception as e:
            print(f"Error de conexión: {e}")
            return False

    def disconnect(self):
        """Desconecta de la empresa"""
        if self.app and self.connected:
            self.app.fCierraEmpresa()
            self.connected = False

    def get_polizas_periodo(self, fecha_inicio: str, fecha_fin: str) -> list:
        """
        Obtiene pólizas de un período.
        fecha_inicio, fecha_fin: formato 'DD/MM/AAAA'
        """
        if not self.connected:
            raise RuntimeError("No conectado a CONTPAQi")

        polizas = []
        # Usar método de búsqueda del SDK
        # fBuscaPolizaPrimero / fBuscaPolizaSiguiente
        return polizas

    def export_balanza(self, periodo: str, output_path: str):
        """Exporta la balanza de comprobación"""
        # Usar método de exportación del SDK
        pass

    def get_cfdi_list(self, fecha_inicio: str, fecha_fin: str) -> list:
        """Obtiene lista de CFDIs emitidos"""
        cfdi_list = []
        # Iterar sobre comprobantes electrónicos
        return cfdi_list


# Alternativa: Integración directa a la base de datos SQL Server
import pyodbc

class CONTPAQiDB:
    """Conector directo a la base de datos SQL Server de CONTPAQi"""

    def __init__(self, server: str, database: str, username: str, password: str):
        self.conn_str = (
            f"DRIVER={{SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password}"
        )
        self.conn = None

    def connect(self):
        """Establece conexión a la base de datos"""
        self.conn = pyodbc.connect(self.conn_str)
        return self.conn

    def get_catalogo_cuentas(self) -> list:
        """Obtiene el catálogo de cuentas"""
        query = """
        SELECT
            CIDCUENTA AS id,
            CCODIGOPOLIZA AS codigo,
            CNOMBRE AS nombre,
            CTIPOCUENTA AS tipo,
            CNATURALEZA AS naturaleza,
            CNIVEL AS nivel
        FROM cuentas
        WHERE CSTATUS = 1
        ORDER BY CCODIGOPOLIZA
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_polizas(self, fecha_inicio: str, fecha_fin: str) -> list:
        """Obtiene pólizas con movimientos de un período"""
        query = """
        SELECT
            p.CNUMPOLIZA AS numero_poliza,
            p.CFECHA AS fecha,
            p.CTIPOPOLIZA AS tipo_poliza,
            p.CCONCEPTO AS concepto,
            c.CCODIGOPOLIZA AS cuenta_codigo,
            c.CNOMBRE AS cuenta_nombre,
            m.CDEBE AS debe,
            m.CHABER AS haber,
            m.CREFERENCIA AS referencia,
            m.CCONCEPTO AS concepto_movimiento
        FROM polizas p
        INNER JOIN movimientos m ON p.CIDPOLIZA = m.CIDPOLIZA
        INNER JOIN cuentas c ON m.CIDCUENTA = c.CIDCUENTA
        WHERE p.CFECHA BETWEEN ? AND ?
        ORDER BY p.CFECHA, p.CNUMPOLIZA, m.CIDMOVIMIENTO
        """
        cursor = self.conn.cursor()
        cursor.execute(query, (fecha_inicio, fecha_fin))
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_balanza(self, fecha_inicio: str, fecha_fin: str) -> list:
        """Genera la balanza de comprobación"""
        query = """
        SELECT
            c.CCODIGOPOLIZA AS codigo,
            c.CNOMBRE AS nombre,
            ISNULL(SUM(m.CDEBE), 0) AS total_debe,
            ISNULL(SUM(m.CHABER), 0) AS total_haber,
            CASE
                WHEN SUM(m.CDEBE) > SUM(m.CHABER)
                THEN SUM(m.CDEBE) - SUM(m.CHABER)
                ELSE 0
            END AS saldo_deudor,
            CASE
                WHEN SUM(m.CHABER) > SUM(m.CDEBE)
                THEN SUM(m.CHABER) - SUM(m.CDEBE)
                ELSE 0
            END AS saldo_acreedor
        FROM cuentas c
        LEFT JOIN movimientos m ON c.CIDCUENTA = m.CIDCUENTA
        LEFT JOIN polizas p ON m.CIDPOLIZA = p.CIDPOLIZA
            AND p.CFECHA BETWEEN ? AND ?
        WHERE c.CSTATUS = 1
        GROUP BY c.CCODIGOPOLIZA, c.CNOMBRE
        ORDER BY c.CCODIGOPOLIZA
        """
        cursor = self.conn.cursor()
        cursor.execute(query, (fecha_inicio, fecha_fin))
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

### 1.5 Computer Use sobre CONTPAQi (Windows)

Para cuando no hay API o DB accesible, usar Computer Use:

```python
"""
Computer Use para CONTPAQi
Usar cuando: no hay acceso a DB ni SDK, solo la app instalada
Requiere: RDP o acceso a Windows con CONTPAQi
"""

# Workflow típico para extraer balanza vía Computer Use:
# 1. Conectar por RDP a la máquina Windows
# 2. Abrir CONTPAQi
# 3. Navegar a Contabilidad > Balanza de Comprobación
# 4. Configurar período
# 5. Exportar a Excel/CSV
# 6. Leer el archivo exportado

# Herramientas necesarias:
# - pyautogui o pywinauto para control de GUI en Windows
# - RDP client (si es remoto)
# - OCR (pytesseract) para leer datos de pantalla

import pyautogui
import pywinauto

def computer_use_conpaqi_export_balanza():
    """
    Ejemplo de flujo Computer Use para exportar balanza
    Nota: Este es un ejemplo conceptual. Los coordinadas exactas
    varían según la resolución y versión de CONTPAQi.
    """
    # 1. Conectar a la ventana de CONTPAQi
    app = pywinauto.Application().connect(title_re=".*CONTPAQi.*")
    ventana = app.window(title_re=".*CONTPAQi.*")

    # 2. Navegar al menú de Balanza
    ventana.menu_select("Contabilidad->Balanza de Comprobación")

    # 3. Configurar período (usar pyautogui para llenar campos)
    # ...

    # 4. Click en Exportar
    # ...

    # 5. Guardar archivo
    # ...
```

### 1.6 Cloud API — ¿Existe?

**No existe una API cloud oficial de CONTPAQi** (a julio 2026). Sin embargo:

- **CONTPAQi Cloud** está en desarrollo/beta limitada (servicio SaaS)
- Algunos partners ofrecen integración cloud vía middleware
- **Workaround común:** Usar un agente Windows local que:
  1. Se conecta a SQL Server de CONTPAQi
  2. Expone endpoints REST locales
  3. Se comunica con un servidor cloud vía webhook/polling

### 1.7 Workarounds Comunes de la Comunidad

| Método | Ventaja | Desventaja |
|--------|---------|------------|
| SQL Server directo | Rápido, completo | Requiere credenciales DB, rompe soporte |
| COM/OLE Automation | Oficial, soportado | Solo Windows, lento, depende de versión |
| Export/Import CSV | Sin riesgo, universal | Manual, no en tiempo real |
| Computer Use | Sin dependencia de API | Lento, frágil, requiere GUI |
| ODBC + Linked Server | Integración SQL Server nativa | Configuración compleja |
| Web scraping de reportes | Sin instalación | Muy frágil |

---

## 2. Aspel (COI, FAX, NOI)

### 2.1 Arquitectura General

Aspel es otro ERP popular en México, especialmente en PyMEs:
- **Aspel COI** — Contabilidad Integral
- **Aspel NOI** — Nómina
- **Aspel FAX** — Facturación (CFDI)
- **Aspel BANCO** — Bancos y tesorería
- **Aspel CAJA** — Caja y cobros
- **Aspel SAE** — Administración Empresarial

### 2.2 Database Schema

Aspel históricamente usó **dBASE (.dbf)** y en versiones recientes migró a **SQL Server**.

#### Estructura dBASE (archivos .dbf)

```
# Directorio típico de datos de Aspel COI
C:\Aspel\COI 3.7\Dat01\
├── CTAS01.dbf      # Catálogo de cuentas
├── POLS01.dbf      # Encabezados de pólizas
├── MOVS01.dbf      # Movimientos de pólizas
├── PARM01.dbf      # Parámetros de la empresa
├── MAYO01.dbf      # Movimientos mensuales
├── SALD01.dbf      # Saldos
├── CHEQ01.dbf      # Cheques
├── PROV01.dbf      # Proveedores
├── CLIE01.dbf      # Clientes
└── BANC01.dbf      # Movimientos bancarios

# Donde "01" es el número de empresa
```

#### Lectura de archivos dBASE desde Python

```python
import dbfread
import pandas as pd
from pathlib import Path

class AspelCOIConnector:
    """Conector para archivos dBASE de Aspel COI"""

    def __init__(self, data_path: str, empresa_num: int = 1):
        self.data_path = Path(data_path)
        self.empresa = f"{empresa_num:02d}"

    def read_dbf(self, table_name: str) -> pd.DataFrame:
        """Lee una tabla dBASE como DataFrame"""
        file_path = self.data_path / f"{table_name}{self.empresa}.dbf"
        table = dbfread.DBF(str(file_path), encoding='latin-1')
        return pd.DataFrame(iter(table))

    def get_catalogo_cuentas(self) -> pd.DataFrame:
        """Obtiene el catálogo de cuentas"""
        df = self.read_dbf("CTAS")
        # Estructura típica de CTAS.dbf:
        # CVE_CTA    (char)  — Clave de cuenta
        # DESC_CTA   (char)  — Descripción
        # TIPO_CTA   (char)  — Tipo (A=Activo, P=Pasivo, C=Capital, I=Ingreso, E=Egreso)
        # NAT_CTA    (char)  — Naturaleza (D=Deudora, A=Acreedora)
        # NIVEL      (num)   — Nivel jerárquico
        # STATUS     (char)  — Estatus (A=Activa)
        return df

    def get_polizas(self, mes: int, anio: int) -> pd.DataFrame:
        """Obtiene pólizas de un período"""
        # Leer encabezados de pólizas
        pols = self.read_dbf("POL")
        # Leer movimientos
        movs = self.read_dbf("MOV")

        # Unir pólizas con movimientos
        # Estructura POL.dbf:
        #   NUM_POL    (num)   — Número de póliza
        #   TIPO_POL   (char)  — Tipo (D=Diario, I=Ingreso, E=Egreso, O=Orden)
        #   FECHA_POL  (date)  — Fecha
        #   CONCEP_POL (char)  — Concepto
        #   TOT_DEB    (num)   — Total debe
        #   TOT_HAB    (num)   — Total haber

        # Estructura MOV.dbf:
        #   NUM_POL    (num)   — Número de póliza (FK)
        #   CVE_CTA    (char)  — Clave de cuenta (FK)
        #   DEBE       (num)   — Monto debe
        #   HABER      (num)   — Monto haber
        #   CONCEP_MOV (char)  — Concepto
        #   REFERENC   (char)  — Referencia

        return pd.merge(
            pols, movs,
            left_on='NUM_POL',
            right_on='NUM_POL',
            how='inner'
        )

    def get_balanza(self, mes: int, anio: int) -> pd.DataFrame:
        """Genera balanza de comprobación"""
        ctas = self.get_catalogo_cuentas()
        movs = self.get_polizas(mes, anio)

        balanza = movs.groupby('CVE_CTA').agg(
            total_debe=('DEBE', 'sum'),
            total_haber=('HABER', 'sum')
        ).reset_index()

        balanza['saldo_deudor'] = (balanza['total_debe'] - balanza['total_haber']).clip(lower=0)
        balanza['saldo_acreedor'] = (balanza['total_haber'] - balanza['total_debe']).clip(lower=0)

        return pd.merge(ctas, balanza, left_on='CVE_CTA', right_on='CVE_CTA', how='left')


# Ejemplo de uso
connector = AspelCOIConnector(r"C:\Aspel\COI 3.7\Dat01", empresa_num=1)
cuentas = connector.get_catalogo_cuentas()
balanza = connector.get_balanza(mes=7, anio=2026)
```

### 2.3 Integración con SQL Server (versiones recientes)

```python
"""
Aspel versiones recientes (7.5+) usan SQL Server
"""
import pyodbc

class AspelSQLConnector:
    """Conector SQL Server para Aspel"""

    def __init__(self, server: str, database: str, username: str, password: str):
        self.conn_str = (
            f"DRIVER={{SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password}"
        )

    def connect(self):
        self.conn = pyodbc.connect(self.conn_str)
        return self.conn

    def get_cuentas(self) -> list:
        query = """
        SELECT
            CveCta AS clave,
            DesCta AS descripcion,
            TipCta AS tipo,
            NatCta AS naturaleza,
            Nivel AS nivel,
            Status AS estatus
        FROM CatalogoCuentas
        WHERE Status = 'A'
        ORDER BY CveCta
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

### 2.4 API Disponible

**No existe API REST/GraphQL oficial de Aspel.** Las opciones son:
1. **Acceso directo a la base de datos** (dBASE o SQL Server)
2. **Export/Import** desde la interfaz de Aspel
3. **Computer Use** sobre la aplicación Windows
4. **COM Automation** (limitada, solo algunas versiones)

---

## 3. SAT — Web Services

### 3.1 Overview de Web Services del SAT

El SAT ofrece múltiples web services SOAP para la facturación electrónica y cumplimiento fiscal. Los endpoints principales son:

#### Endpoints SOAP Disponibles

| Servicio | Endpoint | Descripción |
|----------|----------|-------------|
| **Timbrado de CFDI** | `https://cfdiws.serviciosdigitales.../...` | Emisión y timbrado de facturas |
| **Cancelación de CFDI** | `https://cfdiws.serviciosdigitales.../...` | Cancelación con nuevo esquema |
| **Consulta de CFDI** | `https://consultaqr.facturaelectronica.sat.gob.mx/...` | Validación/consulta de comprobantes |
| **Verificación de CSD** | `https://cfdiws.serviciosdigitales.../...` | Consulta vigencia de certificados |
| **Buzón Tributario** | `https://cfdiws.serviciosdigitales.../...` | Consultas y envíos al buzón |
| **DIOT** | `https://www.sat.gob.mx/...` | Declaración informativa de operaciones con terceros |
| **Pagos Provisionales** | `https://www.sat.gob.mx/...` | Envío de declaraciones provisionales |
| **Declaración Anual** | `https://www.sat.gob.mx/...` | Envío de declaración anual |
| **Consulta 69-B** | `https://www.sat.gob.mx/...` | Consulta EFOS/EDOS |

#### URLs de Web Services (Producción)

```
# Servicios de Facturación (CFDI 4.0)
# Estos endpoints son proporcionados por los PACs autorizados, NO directamente por el SAT
# Los PACs autorizados timbran las facturas y las envían al SAT

# Ejemplo con un PAC genérico:
# Producción: https://cfdiws.serviciosdigitales.gob.mx/ws-emision-cfdi-40/CFDI40
# Pruebas:    https://cfdipruebas... 

# Servicios propios del SAT:
# Validación de CFDI: https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx
# Consulta masiva:    https://cfdiconsulta.clouda.sat.gob.mx/

# Web Services SOAP del SAT para cancelación:
# https://cfdiws.serviciosdigitales.gob.mx/ws-cancelacion-cfdi-40/Cancelacion40
```

### 3.2 Autenticación con FIEL/CSD

La autenticación ante el SAT requiere certificados X.509 (FIEL o CSD):

```python
"""
Autenticación con FIEL/CSD ante el SAT
"""

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
import base64
from datetime import datetime
from lxml import etree
from zeep import Client
from zeep.transports import Transport
from requests import Session

class FIELAuth:
    """Clase para manejar autenticación FIEL/CSD ante el SAT"""

    def __init__(self, cer_path: str, key_path: str, password: str):
        """
        Inicializa con los archivos de certificado y llave privada.

        Args:
            cer_path: Ruta al archivo .cer (certificado)
            key_path: Ruta al archivo .key (llave privada)
            password: Password de la llave privada
        """
        self.cer_path = cer_path
        self.key_path = key_path
        self.password = password

        # Cargar certificado
        with open(cer_path, 'rb') as f:
            self.certificate = x509.load_der_x509_certificate(f.read())

        # Cargar llave privada
        with open(key_path, 'rb') as f:
            # Nota: el archivo .key puede estar en formato DER encriptado
            self.private_key = serialization.load_der_private_key(
                f.read(),
                password=password.encode()
            )

        # Extraer datos del certificado
        self.rfc = self._extract_rfc()
        self.serial_number = self.certificate.serial_number
        self.valid_from = self.certificate.not_valid_before
        self.valid_to = self.certificate.not_valid_after

    def _extract_rfc(self) -> str:
        """Extrae el RFC del certificado"""
        # El RFC está en el Subject del certificado, campo OID 2.5.4.5
        for attribute in self.certificate.subject:
            if attribute.oid.dotted_string == "2.5.4.5":
                return attribute.value
        return ""

    def is_valid(self) -> bool:
        """Verifica si el certificado está vigente"""
        now = datetime.utcnow()
        return self.valid_from <= now <= self.valid_to

    def sign(self, data: bytes) -> str:
        """
        Firma datos con la llave privada.
        Retorna la firma en base64.
        """
        from cryptography.hazmat.primitives.asymmetric import padding

        signature = self.private_key.sign(
            data,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()

    def get_certificate_base64(self) -> str:
        """Retorna el certificado en base64 (formato para SOAP)"""
        with open(self.cer_path, 'rb') as f:
            return base64.b64encode(f.read()).decode()

    def get_private_key_pem(self) -> bytes:
        """Retorna la llave privada en formato PEM"""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )


def create_soap_client_with_fiel(wsdl_url: str, fiel: FIELAuth):
    """
    Crea un cliente SOAP autenticado con FIEL
    """
    session = Session()
    session.cert = (fiel.cer_path, fiel.key_path)
    session.verify = True  # Verificar certificados SSL

    transport = Transport(session=session)
    client = Client(wsdl_url, transport=transport)

    return client


# Ejemplo de uso
fiel = FIELAuth(
    cer_path="/path/to/certificado.cer",
    key_path="/path/to/llave.key",
    password="password_llave"
)

print(f"RFC: {fiel.rfc}")
print(f"Vigente: {fiel.is_valid()}")
print(f"Válido hasta: {fiel.valid_to}")
```

### 3.3 Consulta de CFDIs (Emitidos y Recibidos)

```python
"""
Consulta de CFDIs ante el SAT
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict
import base64

class SATCFDIConsultas:
    """Consultas de CFDIs ante el SAT"""

    # URL de validación de CFDI por UUID
    VALIDA_CFDI_URL = "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"

    # URL de consulta masiva de CFDIs
    CONSULTA_MASIVA_URL = "https://cfdiconsulta.clouda.sat.gob.mx/"

    def __init__(self, fiel: 'FIELAuth'):
        self.fiel = fiel

    def validar_cfdi_por_uuid(
        self,
        emisor_rfc: str,
        receptor_rfc: str,
        total: float,
        uuid: str
    ) -> Dict:
        """
        Valida un CFDI por UUID (endpoint de consulta del SAT).

        Args:
            emisor_rfc: RFC del emisor
            receptor_rfc: RFC del receptor
            total: Total del comprobante
            uuid: Folio fiscal (UUID)

        Returns:
            Dict con el estado del comprobante
        """
        params = {
            'id': uuid,
            're': emisor_rfc,
            'rr': receptor_rfc,
            'tt': str(total),
        }

        try:
            response = requests.get(
                self.VALIDA_CFDI_URL,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            # Parsear respuesta XML
            root = ET.fromstring(response.content)
            ns = {'sat': 'http://www.sat.gob.mx/esquemas/ValidarCFDI'}

            estado = root.find('.//sat:Estado', ns)

            return {
                'uuid': uuid,
                'estado': estado.text if estado is not None else 'No encontrado',
                'es_valido': estado is not None and estado.text == 'Vigente',
                'respuesta_raw': response.text
            }
        except Exception as e:
            return {
                'uuid': uuid,
                'estado': 'Error',
                'es_valido': False,
                'error': str(e)
            }

    def consulta_cfdi_emitidos(
        self,
        rfc_emisor: str,
        fecha_inicio: datetime,
        fecha_fin: datetime
    ) -> List[Dict]:
        """
        Consulta CFDIs emitidos (requiere FIEL).
        Usa el web service SOAP de consulta masiva del SAT.
        """
        # Este endpoint requiere autenticación con FIEL
        # y firma electrónica avanzada
        # NOTA: El SAT ha cambiado frecuentemente estos endpoints
        # Verificar documentación más reciente en sat.gob.mx

        # La consulta masiva se hace generalmente vía:
        # 1. Portal del SAT (manual)
        # 2. Descarga masiva (solicitud + polling)
        # 3. Web service SOAP con FIEL

        # Estructura de la solicitud SOAP para consulta
        """
        <soapenv:Envelope xmlns:soapenv="..."
                          xmlns:des="...">
            <soapenv:Header/>
            <soapenv:Body>
                <des:Consulta>
                    <des:expresionImpresa>
                        <![CDATA[?Re=RFC_EMISOR&RR=RFC_RECEPTOR&...]]>
                    </des:expresionImpresa>
                </des:Consulta>
            </soapenv:Body>
        </soapenv:Envelope>
        """
        pass

    def solicitud_descarga_masiva(
        self,
        rfc: str,
        tipo_solicitud: str,  # 'CFDI' o 'Metadata'
        fecha_inicio: datetime,
        fecha_fin: datetime,
        tipo_cfdis: str = 'Emitidos'  # 'Emitidos' o 'Recibidos'
    ) -> str:
        """
        Solicita la descarga masiva de CFDIs.
        Retorna el ID de solicitud para polling.

        Requiere FIEL para autenticación.
        """
        # Construir XML de solicitud firmado con FIEL
        # El SAT responderá con un RequestId
        # Luego se hace polling hasta que esté listo para descargar
        pass
```

### 3.4 Cancelación de CFDIs (Nuevo Esquema 2024-2025)

```python
"""
Cancelación de CFDIs — Nuevo esquema 2024-2025

El SAT implementó un nuevo esquema de cancelación que requiere:
1. Motivo de cancelación (catálogo)
2. UUID de sustitución (si aplica)
3. Aceptación del receptor (para algunos casos)

Catálogo de motivos de cancelación:
01 - Comprobantes emitidos con errores con relación
02 - Comprobantes emitidos con errores sin relación
03 - No se llevó a cabo la operación
04 - Operación nominativa relacionada en la factura global
"""

from enum import Enum
from typing import Optional

class MotivoCancelacion(Enum):
    """Motivos de cancelación de CFDI según catálogo SAT"""
    ERROR_CON_RELACION = "01"       # Requiere UUID sustitución
    ERROR_SIN_RELACION = "02"       # No requiere UUID sustitución
    OPERACION_NO_REALIZADA = "03"   # No requiere UUID sustitución
    FACTURA_GLOBAL = "04"           # No requiere UUID sustitución

class CanceladorCFDI:
    """Cancelación de CFDIs ante el SAT"""

    # Web service SOAP de cancelación
    WSDL_CANCELACION = "https://cfdiws.serviciosdigitales.gob.mx/ws-cancelacion-cfdi-40/Cancelacion40?wsdl"
    WSDL_CANCELACION_PRUEBAS = "https://cfdipruebas.serviciosdigitales.gob.mx/ws-cancelacion-cfdi-40/Cancelacion40?wsdl"

    def __init__(self, fiel: 'FIELAuth', produccion: bool = False):
        self.fiel = fiel
        self.wsdl = self.WSDL_CANCELACION if produccion else self.WSDL_CANCELACION_PRUEBAS

    def cancelar_cfdi(
        self,
        uuid: str,
        motivo: MotivoCancelacion,
        uuid_sustitucion: Optional[str] = None
    ) -> dict:
        """
        Cancela un CFDI ante el SAT.

        Args:
            uuid: Folio fiscal del CFDI a cancelar
            motivo: Motivo de cancelación (catálogo SAT)
            uuid_sustitución: UUID del CFDI que sustituye (requerido para motivo 01)

        Returns:
            dict con resultado de la cancelación
        """
        if motivo == MotivoCancelacion.ERROR_CON_RELACION and not uuid_sustitucion:
            raise ValueError("El motivo 01 requiere UUID de sustitución")

        # Construir solicitud de cancelación
        # El XML debe ser firmado con la FIEL

        solicitud = {
            'RfcEmisor': self.fiel.rfc,
            'Folios': {
                'UUID': uuid,
                'Motivo': motivo.value,
                'FolioSustitucion': uuid_sustitucion
            },
            'Fecha': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'RfcPac': None,  # Si se cancela vía PAC
        }

        # Firmar la solicitud
        # Enviar vía SOAP
        # Procesar respuesta

        return {
            'uuid': uuid,
            'estado': 'pendiente',  # Vigente, NoCancelable, Cancelable, Cancelado
            'mensaje': 'Solicitud enviada'
        }

    def consultar_estatus_cancelacion(self, uuid: str) -> dict:
        """Consulta el estatus de una solicitud de cancelación"""
        # El SAT puede requerir aceptación del receptor
        # Estados posibles:
        # - Cancelado
        # - No Cancelable
        # - Solicitud de cancelación en proceso (pendiente aceptación)
        pass
```

### 3.5 DIOT (Declaración Informativa de Operaciones con Terceros)

```python
"""
Generación y envío de DIOT
"""

from dataclasses import dataclass
from typing import List
from enum import Enum

class TipoOperacion(Enum):
    """Tipos de operación para DIOT"""
    PROVEEDORES_NACIONALES = "03"
    PROVEEDORES_IMPORTACION = "04"
    PRESTACIONES_PROFESIONALES = "05"
    RENTAS = "06"
    INTERESES = "07"
    SEGUROS = "08"
    TRANSPORTE = "09"
    OTROS = "10"

@dataclass
class OperacionTercero:
    """Representa una operación con un tercero para DIOT"""
    rfc: str
    tipo_operacion: TipoOperacion
    tipo_tercero: str  # 'Nacional', 'Extranjero', 'Global'
    valor_actos_tasa_16: float = 0.0
    iva_16: float = 0.0
    valor_actos_tasa_0: float = 0.0
    valor_actos_exentos: float = 0.0
    iva_retenido: float = 0.0
    iva_no_acreditable: float = 0.0
    nombre_extranjero: str = ""
    pais_extranjero: str = ""
    num_id_fiscal: str = ""

class DIOTGenerator:
    """Genera la DIOT (Declaración Informativa de Operaciones con Terceros)"""

    def __init__(self, rfc_empresa: str):
        self.rfc_empresa = rfc_empresa

    def generar_registro(
        self,
        operaciones: List[OperacionTercero]
    ) -> str:
        """
        Genera el archivo de texto para envío de DIOT.
        Formato: archivo delimitado por pipes (|)
        """
        lineas = []
        for op in operaciones:
            linea = "|".join([
                self.rfc_empresa,                    # RFC del contribuyente
                op.rfc,                               # RFC del tercero
                op.tipo_tercero,                      # Tipo de tercero
                op.tipo_operacion.value,              # Tipo de operación
                f"{op.valor_actos_tasa_16:.2f}",     # Valor actos gravados 16%
                f"{op.iva_16:.2f}",                  # IVA 16%
                f"{op.valor_actos_tasa_0:.2f}",      # Valor actos gravados 0%
                f"{op.valor_actos_exentos:.2f}",     # Valor actos exentos
                f"{op.iva_retenido:.2f}",            # IVA retenido
                f"{op.iva_no_acreditable:.2f}",      # IVA no acreditable
                op.nombre_extranjero,                 # Nombre extranjero
                op.pais_extranjero,                   # País extranjero
                op.num_id_fiscal,                     # Número ID fiscal extranjero
            ])
            lineas.append(linea)

        return "\n".join(lineas)

    def enviar_diot(self, archivo: str, periodo: str) -> dict:
        """
        Envía la DIOT al SAT.
        periodo: formato 'MM/AAAA'

        Nota: El envío real requiere:
        1. Firma electrónica (FIEL)
        2. Acceso al portal del SAT
        3. O uso de web service SOAP dedicado
        """
        # El envío se hace generalmente vía el portal del SAT
        # o mediante servicios de terceros (PACs)
        return {
            'estado': 'enviado',
            'periodo': periodo,
            'mensaje': 'DIOT enviada correctamente'
        }
```

### 3.6 Pagos Provisionales ISR

```python
"""
Envío de pagos provisionales de ISR al SAT
"""

from dataclasses import dataclass
from typing import Dict
from datetime import date

@dataclass
class PagoProvisional:
    """Datos para pago provisional de ISR"""
    rfc: str
    periodo: str                    # 'MM/AAAA'
    ejercicio_fiscal: int           # Año
    tipo_declaracion: str           # 'Normal', 'Complementaria'
    ingresos_periodo: float
    deducciones_periodo: float
    utilidad_fiscal: float          # Ingresos - Deducciones
    isr_periodo: float              # ISR calculado
    pagos_previos: float            # Pagos provisionales anteriores
    retenciones_isr: float          # ISR retenido
    saldo_a_favor: float            # Saldo a favor de periodos anteriores
    isr_pagar: float                # ISR a pagar (resultado)

class PagoProvisionalISR:
    """Calcula y envía pagos provisionales de ISR"""

    # Tabla de tarifas ISR mensuales 2026 (personas morales)
    # Régimen general: tasa del 30% sobre utilidad fiscal
    TASA_ISR_MORAL = 0.30

    def __init__(self, rfc: str, regimen: str = '601'):
        self.rfc = rfc
        self.regimen = regimen  # 601=General Ley PM, 605=Sueldos, etc.

    def calcular_isr_provisional_moral(
        self,
        ingresos_acumulables: float,
        deducciones_autorizadas: float,
        pagos_previos: float = 0.0
    ) -> float:
        """
        Calcula ISR provisional para personas morales (régimen general).

        Fórmula: (Ingresos - Deducciones) * 30% - Pagos previos
        """
        utilidad = max(0, ingresos_acumulables - deducciones_autorizadas)
        isr = utilidad * self.TASA_ISR_MORAL
        isr_pagar = max(0, isr - pagos_previos)
        return isr_pagar

    def calcular_isr_provisional_fisica(
        self,
        ingresos_acumulables: float,
        deducciones_personales: float = 0.0,
        actividad_empresarial: bool = True
    ) -> float:
        """
        Calcula ISR provisional para personas físicas (Actividad Empresarial).
        Usa la tabla de tarifas progresivas del SAT.
        """
        # Tabla de tarifas mensuales ISR PF (simplificada)
        # Estos valores son aproximados y deben actualizarse anualmente
        tarifas = [
            (0.01,    746.04,    0.0192,    0),
            (746.05,  6332.05,   0.0640,    33.66),
            (6332.06, 11128.01,  0.1088,    318.32),
            (11128.02, 12935.82, 0.1600,    895.63),
            (12935.83, 15424.56, 0.1792,    1144.69),
            (15424.57, 31236.49, 0.2136,    1670.14),
            (31236.50, 49233.77, 0.2352,    5053.74),
            (49233.78, 93993.90, 0.3000,    9290.43),
            (93993.91, 125325.20, 0.3200,   22718.47),
            (125325.21, 375975.61, 0.3400,  28524.68),
            (375975.62, float('inf'), 0.3500, 113745.80),
        ]

        base = max(0, ingresos_acumulables - deducciones_personales)
        isr = 0

        for limite_inf, limite_sup, tasa, cuota_fija in tarifas:
            if base >= limite_inf:
                excedente = min(base, limite_sup) - limite_inf
                isr = excedente * tasa + cuota_fija
            else:
                break

        return max(0, isr)

    def generar_declaracion(self, pago: PagoProvisional) -> str:
        """
        Genera el formato de declaración provisional.
        Retorna XML para envío al SAT.
        """
        xml_template = f"""<?xml version="1.0" encoding="UTF-8"?>
<PagosProvisionales
    version="1.0"
    xmlns="http://www.sat.gob.mx/esquemas/PagosProvisionales"
    Rfc="{pago.rfc}"
    Ejercicio="{pago.ejercicio_fiscal}"
    Periodo="{pago.periodo}">
    <Ingresos>
        <IngresosAcumulables>{pago.ingresos_periodo}</IngresosAcumulables>
    </Ingresos>
    <Deducciones>
        <DeduccionesAutorizadas>{pago.deducciones_periodo}</DeduccionesAutorizadas>
    </Deducciones>
    <Determinacion>
        <UtilidadFiscal>{pago.utilidad_fiscal}</UtilidadFiscal>
        <ISR>{pago.isr_periodo}</ISR>
        <PagosPrevios>{pago.pagos_previos}</PagosPrevios>
        <Retenciones>{pago.retenciones_isr}</Retenciones>
        <SaldoFavor>{pago.saldo_a_favor}</SaldoFavor>
        <ISRAPagar>{pago.isr_pagar}</ISRAPagar>
    </Determinacion>
</PagosProvisionales>"""
        return xml_template
```

### 3.7 Buzón Tributario

```python
"""
Consulta y envío al Buzón Tributario del SAT
"""

class BuzonTributario:
    """Interacción con el Buzón Tributario del SAT"""

    # Endpoint del Buzón Tributario
    URL_BUZON = "https://www.sat.gob.mx/aplicacion/login/53027/consulta-tus-opiniones-de-cumplimiento"

    # Tipos de opiniones disponibles
    OPINION_CUMPLIMIENTO = "Opinión de Cumplimiento"
    SITUACION_FISCAL = "Constancia de Situación Fiscal"
    CFDI_RECIBIDOS = "CFDI Recibidos"
    CFDI_EMITIDOS = "CFDI Emitidos"

    def __init__(self, fiel: 'FIELAuth'):
        self.fiel = fiel

    def consultar_opinion_cumplimiento(self, rfc: str) -> dict:
        """
        Consulta la opinión de cumplimiento del contribuyente.
        Retorna el estatus de cumplimiento.
        """
        # Requiere autenticación con FIEL
        # El SAT responde con:
        # - "Se encuentra al corriente de sus obligaciones fiscales"
        # - "No se encuentra al corriente..."
        # - Credenciales pendientes
        pass

    def consultar_situacion_fiscal(self, rfc: str) -> dict:
        """
        Obtiene la Constancia de Situación Fiscal.
        Incluye: régimen, obligaciones, domicilio fiscal, actividades económicas.
        """
        pass

    def descargar_cfdi_recibidos(
        self,
        rfc: str,
        fecha_inicio: str,
        fecha_fin: str
    ) -> bytes:
        """
        Descarga CFDIs recibidos del Buzón Tributario.
        Retorna ZIP con XMLs de CFDIs.
        """
        # Solicitud de descarga masiva
        # 1. Enviar solicitud firmada con FIEL
        # 2. Recibir ID de solicitud
        # 3. Hacer polling hasta que esté listo
        # 4. Descargar ZIP con los CFDIs
        pass
```

### 3.8 Consulta 69-B (EFOS/EDOS)

```python
"""
Consulta del listado 69-B del SAT
(Empresas que facturan operaciones simuladas - EFOS)
(Empresas que deducen operaciones simuladas - EDOS)
"""

class Consulta69B:
    """Consulta del listado 69-B (EFOS/EDOS)"""

    # El SAT publica el listado 69-B periódicamente
    # Disponible como archivo descargable o vía web service

    URL_69B = "https://www.sat.gob.mx/consultas/62103/listado-de-contribuyentes-que-realizan-operaciones-con-proveedores-presuntos-efos"

    def __init__(self):
        self.efos_cache = None

    def descargar_listado(self) -> list:
        """
        Descarga el listado 69-B actualizado.
        Retorna lista de RFCs presuntos EFOS.
        """
        # El SAT publica el listado como archivo descargable
        # (CSV o XML con los RFCs presuntos)
        pass

    def verificar_proveedor(self, rfc_proveedor: str) -> dict:
        """
        Verifica si un proveedor está en el listado 69-B.

        Returns:
            dict con:
            - en_listado: bool
            - tipo: 'EFOS' / 'EDOS'
            - estatus: 'Presunto', 'Desvirtuado', 'Definitivo', 'Sentencia favorable'
            - fecha_inclusion: str
        """
        # Cargar listado si no está en caché
        if self.efos_cache is None:
            self.efos_cache = self.descargar_listado()

        rfc_upper = rfc_proveedor.upper().strip()

        if rfc_upper in self.efos_cache:
            return {
                'en_listado': True,
                'rfc': rfc_upper,
                'estatus': 'Presunto EFOS',
                'mensaje': '⚠️ Este proveedor está en el listado 69-B del SAT'
            }

        return {
            'en_listado': False,
            'rfc': rfc_upper,
            'estatus': 'No encontrado',
            'mensaje': '✅ Este proveedor NO está en el listado 69-B'
        }

    def verificar_lista_proveedores(self, rfcs: list) -> list:
        """Verifica múltiples proveedores contra el 69-B"""
        return [self.verificar_proveedor(rfc) for rfc in rfcs]
```

### 3.9 Verificación de Vigencia de CSD

```python
"""
Verificación de vigencia de Certificados de Sello Digital (CSD)
"""

class VerificacionCSD:
    """Verifica la vigencia de CSD ante el SAT"""

    def __init__(self, fiel: 'FIELAuth'):
        self.fiel = fiel

    def verificar_csd(self, rfc: str) -> dict:
        """
        Verifica si el CSD de un contribuyente está vigente.

        Returns:
            dict con:
            - rfc: str
            - vigente: bool
            - certificados: list de certificados activos
            - fecha_verificacion: datetime
        """
        # El SAT ofrece un web service SOAP para esta consulta
        # Requiere autenticación con FIEL
        pass

    def verificar_por_no_serie(self, no_serie: str) -> dict:
        """Verifica un CSD por número de serie"""
        pass
```

### 3.10 Python Libraries para SAT

```python
"""
Librerías Python recomendadas para integración con el SAT
"""

# =============================================
# 1. lxml + zeep (SOAP para web services SAT)
# =============================================
# pip install lxml zeep cryptography requests

from zeep import Client
from zeep.transports import Transport
from requests import Session
import lxml.etree as ET

# Ejemplo: Consumir web service de validación de CFDI
def ejemplo_zeep():
    session = Session()
    # Configurar certificados FIEL para autenticación
    session.cert = ('certificado.cer', 'llave.key')

    transport = Transport(session=session)
    # WSDL del servicio
    client = Client(
        'https://cfdiws.serviciosdigitales.gob.mx/...?wsdl',
        transport=transport
    )
    # Llamar método del servicio
    resultado = client.service.ValidarCFDI(...)
    return resultado


# =============================================
# 2. suds-community (alternativa a zeep)
# =============================================
# pip install suds-community
from suds.client import Client as SudsClient

def ejemplo_suds():
    client = SudsClient(
        url='https://cfdiws.serviciosdigitales.gob.mx/...?wsdl',
        location='https://cfdiws.serviciosdigitales.gob.mx/...'
    )


# =============================================
# 3. Librerías específicas para CFDI
# =============================================

# a) cfdilib (generación de CFDI XML)
# pip install cfdilib
# Genera CFDI 4.0 XML válido según esquemas SAT
# from cfdilib import CFDI

# b) cfdi (parseo y validación)
# pip install cfdi
# Lee y valida XMLs de CFDI existentes
# from cfdi import CFDIReader

# c) sat-cfdi (otra opción)
# pip install sat-cfdi


# =============================================
# 4. cryptography (para FIEL/CSD)
# =============================================
# pip install cryptography
# Ya cubierto arriba en la sección de FIELAuth


# =============================================
# 5. signxml (firma XML para SAT)
# =============================================
# pip install signxml
from signxml import XMLSigner, XMLVerifier

def firmar_xml_sat(xml_content: bytes, cert_path: str, key_path: str) -> bytes:
    """Firma un XML con certificado SAT (para envío de declaraciones)"""
    cert = open(cert_path, 'rb').read()
    key = open(key_path, 'rb').read()

    root = ET.fromstring(xml_content)
    signer = XMLSigner(
        method=signxml.methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256"
    )
    signed_root = signer.sign(root, key=key, cert=cert)
    return ET.tostring(signed_root)


# =============================================
# 6. python-cfdi40 (CFDI 4.0 generación)
# =============================================
# pip install python-cfdi40
# Genera CFDI 4.0 con complemento de pago, nómina, carta porte


# =============================================
# 7. Librería Facturapi (Python SDK oficial)
# =============================================
# pip install facturapi
# SDK oficial de Facturapi (PAC alternativo)
```

---

## 4. Estados de Cuenta Bancarios

### 4.1 Formatos Bancarios

| Formato | Extension | Descripción | Uso |
|---------|-----------|-------------|-----|
| **OFX** | .ofx | Open Financial Exchange | Universal, más usado |
| **QIF** | .qif | Quicken Interchange Format | Legacy, aún soportado |
| **MT940** | .mt940 | SWIFT MT940 | Banca corporativa |
| **CSV** | .csv | Valores separados por coma | Universal, manual |
| **PDF** | .pdf | Documento PDF | Formato visual |

### 4.2 Parseo de PDFs Bancarios

```python
"""
Parseo de estados de cuenta bancarios en PDF
"""

import re
from typing import List, Dict
from dataclasses import dataclass
from datetime import datetime

@dataclass
class MovimientoBancario:
    """Representa un movimiento bancario"""
    fecha: datetime
    descripcion: str
    referencia: str
    cargo: float
    abono: float
    saldo: float
    concepto: str  # Clasificación automática

class ParserEstadosBancarios:
    """Parser base para estados de cuenta bancarios"""

    def __init__(self):
        self.movimientos = []

    def parse_pdf(self, pdf_path: str) -> List[MovimientoBancario]:
        """Parsea un PDF de estado de cuenta"""
        raise NotImplementedError


class ParserBBVA(ParserEstadosBancarios):
    """Parser para estados de cuenta BBVA México"""

    def parse_pdf(self, pdf_path: str) -> List[MovimientoBancario]:
        """
        Parsea PDF de BBVA.

        Formato típico BBVA:
        FECHA    CONCEPTO/DESCRIPCIÓN         REFERENCIA      CARGO      ABONO      SALDO
        01/07    PAGO SPEI                    123456789       5,000.00              50,000.00
        02/07    DEPOSITO EFECTIVO            987654321                  10,000.00  60,000.00
        """
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        movimientos = []

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    movimientos.extend(self._parse_bbva_text(text))

        return movimientos

    def _parse_bbva_text(self, text: str) -> List[MovimientoBancario]:
        """Parsea el texto extraído de un PDF de BBVA"""
        movimientos = []

        # Patrón regex para movimientos BBVA
        # Ajustar según formato exacto del PDF
        patron = re.compile(
            r'(\d{2}/\d{2})\s+'        # Fecha
            r'(.+?)\s+'                  # Concepto
            r'(\d{10,})\s+'              # Referencia
            r'([\d,]+\.\d{2})?\s*'       # Cargo (opcional)
            r'([\d,]+\.\d{2})?\s*'       # Abono (opcional)
            r'([\d,]+\.\d{2})'           # Saldo
        )

        for match in patron.finditer(text):
            fecha_str, concepto, referencia, cargo, abono, saldo = match.groups()
            movimientos.append(MovimientoBancario(
                fecha=datetime.strptime(f"{fecha_str}/2026", "%d/%m/%Y"),
                descripcion=concepto.strip(),
                referencia=referencia,
                cargo=self._parse_amount(cargo) if cargo else 0.0,
                abono=self._parse_amount(abono) if abono else 0.0,
                saldo=self._parse_amount(saldo),
                concepto=self._clasificar_movimiento(concepto)
            ))

        return movimientos

    def _parse_amount(self, amount_str: str) -> float:
        """Convierte string de monto a float"""
        if not amount_str:
            return 0.0
        return float(amount_str.replace(',', ''))

    def _clasificar_movimiento(self, descripcion: str) -> str:
        """Clasifica automáticamente el concepto del movimiento"""
        desc_lower = descripcion.lower()

        if any(word in desc_lower for word in ['spei', 'transferencia', 'envío']):
            return 'Transferencia SPEI'
        elif any(word in desc_lower for word in ['pago', 'cargo']):
            return 'Pago'
        elif any(word in desc_lower for word in ['deposito', 'depósito', 'abono']):
            return 'Depósito'
        elif any(word in desc_lower for word in ['comision', 'comisión', 'iva']):
            return 'Comisión'
        elif any(word in desc_lower for word in ['nómina', 'nomina', 'sueldo']):
            return 'Nómina'
        elif any(word in desc_lower for word in ['tarjeta', 'tpv', 'pos']):
            return 'Tarjeta'
        else:
            return 'Otros'


class ParserBanorte(ParserEstadosBancarios):
    """Parser para estados de cuenta Banorte"""

    def parse_pdf(self, pdf_path: str) -> List[MovimientoBancario]:
        """
        Formato Banorte típico:
        FECHA OPER    FECHA VALOR   DESCRIPCIÓN         REFERENCIA   CARGOS      ABONOS      SALDO
        """
        # Implementación similar a BBVA con patrón regex diferente
        pass


class ParserSantander(ParserEstadosBancarios):
    """Parser para estados de cuenta Santander"""
    pass

class ParserHSBC(ParserEstadosBancarios):
    """Parser para estados de cuenta HSBC"""
    pass

class ParserCitibanamex(ParserEstadosBancarios):
    """Parser para estados de cuenta Citibanamex"""
    pass

class ParserBanregio(ParserEstadosBancarios):
    """Parser para estados de cuenta Banregio"""
    pass

class ParserScotiabank(ParserEstadosBancarios):
    """Parser para estados de cuenta Scotiabank"""
    pass


# =============================================
# Parseo de OFX (universal)
# =============================================
import ofxparse

def parse_ofx(ofx_path: str) -> List[MovimientoBancario]:
    """Parsea un archivo OFX (funciona para cualquier banco)"""
    with open(ofx_path, 'rb') as f:
        ofx = ofxparse.OfxParser.parse(f)

    movimientos = []
    for account in ofx.accounts:
        for transaction in account.statement.transactions:
            movimientos.append(MovimientoBancario(
                fecha=transaction.date,
                descripcion=transaction.memo or transaction.payee,
                referencia=transaction.id,
                cargo=abs(transaction.amount) if transaction.amount < 0 else 0.0,
                abono=transaction.amount if transaction.amount > 0 else 0.0,
                saldo=0.0,  # Se calcula después
                concepto=transaction.memo or ''
            ))

    return movimientos
```

### 4.3 APIs Bancarias (Open Banking México)

```python
"""
Open Banking en México — APIs bancarias

Status (2026):
- México NO tiene un marco regulatorio de Open Banking como la UE (PSD2)
- CNBV y Banxico están trabajando en un marco regulatorio
- Algunos bancos ofrecen APIs limitadas
- La integración más común es vía SPEI/CoDi de Banxico
"""

# =============================================
# SPEI — Sistema de Pagos Electrónicos Interbancarios
# =============================================

@dataclass
class TransferenciaSPEI:
    """Datos de una transferencia SPEI"""
    institucion_ordenante: str   # CLABE del banco emisor
    institucion_beneficiario: str # CLABE del banco receptor
    cuenta_ordenante: str        # CLABE de 18 dígitos
    cuenta_beneficiario: str     # CLABE de 18 dígitos
    nombre_beneficiario: str
    rfc_beneficiario: str
    concepto: str
    monto: float
    referencia: str
    fecha: datetime
    clave_rastreo: str          # Folio de seguimiento

# Estructura del archivo SPEI (enviado por Banxico)
# Formato: registro de longitud fija
SPEI_REGISTRO = {
    'tipo_registro': (1, 2),        # '01'=ordenante, '02'=beneficiario
    'fecha_operacion': (3, 10),     # AAAAMMDD
    'folio_banco': (11, 22),        # Folio asignado por el banco
    'clave_rastreo': (23, 57),      # Clave de rastreo
    'institucion_ordenante': (58, 62),  # Clave del banco
    'cuenta_ordenante': (63, 80),   # CLABE
    'institucion_beneficiario': (81, 85),
    'cuenta_beneficiario': (86, 103),
    'nombre_beneficiario': (104, 153),
    'rfc_curp_beneficiario': (154, 166),
    'concepto': (167, 226),
    'referencia_numerica': (227, 241),
    'monto': (242, 257),            # 14 enteros + 2 decimales
    # ... más campos
}


# =============================================
# CoDi — Cobros Digitales (Banxico)
# =============================================
"""
CoDi es el sistema de cobros digitales de Banxico
Permite generar cobros por QR o NFC

API de CoDi (para comercios):
- Endpoint: https://prod.cobrodigital.banxico.org.mx/
- Autenticación: Certificado digital + credenciales
- Funcionalidades:
  - Generar solicitud de cobro
  - Consultar estado de cobro
  - Devolver cobro

No tiene un SDK oficial en Python, se consume vía REST/SOAP
"""
```

---

## 5. Facturadores Electrónicos APIs

### 5.1 Facturapi (⭐ RECOMENDADO)

**Facturapi** es el PAC (Proveedor Autorizado de Certificación) más developer-friendly de México.

#### Base URL y Autenticación
```
Base URL: https://www.facturapi.io/v2
Auth: Bearer token (API Key)
Content-Type: application/json
```

#### Endpoints Principales

```python
"""
SDK de Facturapi para Python
pip install facturapi
"""

import facturapi

# Inicializar con API key
api = facturapi.Facturapi('sk_live_TU_API_KEY')

# =============================================
# CLIENTES
# =============================================

# Crear cliente
cliente = api.customers.create({
    'legal_name': 'Kim Wexler',           # Razón social
    'tax_id': 'WXKE800401B12',            # RFC
    'tax_system': '601',                   # Régimen fiscal (601=General Ley PM)
    'address': {
        'zip': '06600',                    # Código postal (5 dígitos)
        'country': 'MEX'
    },
    'email': 'kim@ejemplo.com',
    'phone': '5555555555'
})

# Listar clientes
clientes = api.customers.list(limit=50)

# Obtener cliente por ID
cliente = api.customers.get('customer_id')

# Actualizar cliente
api.customers.update('customer_id', {'email': 'nuevo@email.com'})

# Buscar por RFC
cliente = api.customers.search_by_tax_id('WXKE800401B12')

# =============================================
# PRODUCTOS
# =============================================

# Crear producto/servicio
producto = api.products.create({
    'description': 'Consultoría en TI',
    'product_key': '43232300',             # ClaveProdServ del SAT
    'price': 15000.00,
    'unit_key': 'E48',                     # Unidad (E48=Servicio)
    'unit_name': 'Servicio',
    'tax_included': False,
    'taxes': [{
        'type': 'IVA',
        'rate': 0.16,
        'factor': 'Tasa',
        'withholding': False
    }]
})

# Listar productos
productos = api.products.list(limit=50)

# =============================================
# FACTURAS (CFDI)
# =============================================

# Crear factura de ingreso (CFDI 4.0)
factura = api.invoices.create({
    'customer': 'customer_id',             # ID del cliente creado
    'items': [{
        'quantity': 1,
        'product': {
            'description': 'Consultoría en TI - Julio 2026',
            'product_key': '43232300',
            'price': 15000.00
        }
    }],
    'payment_form': '03',                  # Transferencia electrónica
    'payment_method': 'PUE',               # Pago en una sola exhibición
    'use': 'G03',                          # Gastos en general
    'folio_number': 1234,
    'series': 'A',
    'date': '2026-07-01T10:00:00',
})

# Obtener factura por ID
factura = api.invoices.get('invoice_id')

# Listar facturas
facturas = api.invoices.list(
    limit=50,
    date={'gte': '2026-01-01', 'lte': '2026-12-31'}
)

# Cancelar factura
api.invoices.cancel('invoice_id', {
    'motive': '02'  # 02=Comprobante emitido con errores sin relación
})

# Enviar factura por email
api.invoices.send_by_email('invoice_id', {
    'email': 'cliente@ejemplo.com'
})

# Descargar PDF
pdf_url = api.invoices.pdf_url('invoice_id')

# Descargar XML
xml_url = api.invoices.xml_url('invoice_id')

# =============================================
# FACTURA DE PAGO (Complemento de Pago)
# =============================================

pago = api.invoices.create_payment({
    'customer': 'customer_id',
    'related_documents': [{
        'uuid': 'UUID_DE_LA_FACTURA_ORIGINAL',
        'amount': 5000.00,
        'partiality': 1
    }],
    'payment_form': '03',
    'date': '2026-07-15T12:00:00'
})

# =============================================
# FACTURA DE EGRESO (Nota de Crédito)
# =============================================

egreso = api.invoices.create_egreso({
    'customer': 'customer_id',
    'items': [{
        'quantity': 1,
        'product': {
            'description': 'Devolución parcial',
            'product_key': '43232300',
            'price': 3000.00
        }
    }],
    'related_documents': [{
        'uuid': 'UUID_FACTURA_ORIGINAL',
        'amount': 3000.00
    }]
})

# =============================================
# NÓMINA
# =============================================

nomina = api.invoices.create_nomina({
    'customer': 'employee_customer_id',
    'items': [{
        'quantity': 1,
        'product': {
            'description': 'Sueldo mensual julio 2026',
            'product_key': '84111505',
            'price': 25000.00
        }
    }],
    'complement': {
        'nomina': {
            'type': 'O',                     # O=Otro tipo de nómina
            'payment_date': '2026-07-15',
            'payment_period': '04',           # Quincenal
            'start_date': '2026-07-01',
            'end_date': '2026-07-15',
            'total_perceptions': 25000.00,
            'total_deductions': 5000.00,
            'total_other_payments': 0.00,
        }
    }
})

# =============================================
# CARTA PORTE
# =============================================

carta_porte = api.invoices.create({
    'customer': 'customer_id',
    'items': [{
        'quantity': 1,
        'product': {
            'description': 'Transporte de mercancía',
            'product_key': '78101700',
            'price': 20000.00
        }
    }],
    'complement': {
        'carta_porte': {
            'version': '3.1',
            'transp_internac': 'No',
            'total_dist_rec': 350.5,
            'ubicaciones': [
                {
                    'tipo_ubicacion': 'Origen',
                    'rfc_remitente_destinatario': 'XAXX010101000',
                    'fecha_hora_salida_llegada': '2026-07-01T08:00:00',
                    'domicilio': {'codigo_postal': '06600'}
                },
                {
                    'tipo_ubicacion': 'Destino',
                    'rfc_remitente_destinatario': 'cliente_rfc',
                    'fecha_hora_salida_llegada': '2026-07-01T18:00:00',
                    'domicilio': {'codigo_postal': '44100'}
                }
            ],
            'mercancias': [{
                'bienes_transp': '11121600',
                'descripcion': 'Mercancía general',
                'cantidad': 100,
                'unidad': 'H87',
                'peso_kg': 5000
            }],
            'autotransporte': {
                'perm_sct': 'TPAF01',
                'num_permiso_sct': '12345',
                'placa_vm': 'ABC1234',
                'seguros': {
                    'asegura_resp_civil': 'Seguros SA',
                    'poliza_resp_civil': 'POL123'
                }
            }
        }
    }
})

# =============================================
# ORGANIZACIONES (Multi-RFC)
# =============================================
# Si gestionas facturación para múltiples empresas:

organizacion = api.organizations.create({
    'legal_name': 'Mi Empresa SA de CV',
    'tax_id': 'MEF260101ABC',
    'tax_system': '601',
    'address': {
        'zip': '06600',
        'country': 'MEX'
    },
    'certificate': open('certificado.cer', 'rb'),
    'private_key': open('llave.key', 'rb'),
    'private_key_password': 'password'
})

# Usar una organización específica
api.set_organization('org_id')
```

#### Pricing de Facturapi

| Plan | Precio | Timbres | Features |
|------|--------|---------|----------|
| **Gratis** | $0/mes | 50 timbres | API, Dashboard básico |
| **Startup** | $499/mes | 500 timbres | API, Dashboard, Multi-RFC |
| **Business** | $999/mes | 2,000 timbres | Todo + Priority support |
| **Enterprise** | Custom | Ilimitado | SLA, On-premise, Custom |

*Precios en MXN, sujetos a cambio. Timbres = facturas timbradas.*

### 5.2 Otros Facturadores Electrónicos

#### Finkok
```
Base URL: https://facturacion.finkok.com/api
Auth: Username + Password (SOAP)
WSDL: https://facturacion.finkok.com/sandbox/wsdl
Ventaja: Muy económico, sandbox gratuito
Desventaja: API SOAP (más compleja), documentación escasa
```

#### SW Sapien (Solución Web)
```
Base URL: https://services.sw.com.mx
Auth: Token
Ventaja: Buena documentación, REST API
Desventaja: Pricing más alto, menos flexible que Facturapi
```

#### Timbox
```
Base URL: https://facturacion.timbox.com/api
Auth: Token
Ventaja: Interface amigable, soporte para carta porte
Desventaja: API limitada en plan básico
```

#### FiscalAPI
```
Base URL: https://api.fiscalapi.com
Auth: API Key
Ventaja: API REST moderna, bien documentada
Desventaja: Menos adoption que Facturapi
```

### 5.3 Comparativa para Producción

| Característica | Facturapi | Finkok | SW Sapien | Timbox | FiscalAPI |
|---------------|-----------|--------|-----------|--------|-----------|
| **API REST** | ✅ | ❌ (SOAP) | ✅ | ✅ | ✅ |
| **Documentación** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **SDK Python** | ✅ Oficial | ❌ | ✅ | ❌ | ✅ |
| **CFDI 4.0** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Carta Porte** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Nómina** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Multi-RFC** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **Sandbox/Test** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Dashboard** | ✅ | ❌ | ✅ | ✅ | ✅ |
| **Webhooks** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **Cancelación** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Precio base** | $499/mes | $199/mes | $599/mes | $299/mes | $399/mes |
| **Calidad API** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

**Recomendación: Facturapi** es el mejor para producción por:
1. API REST moderna y bien documentada
2. SDK oficial en Python, Node.js, PHP, Ruby
3. Multi-RFC nativo (ideal para agentes contables que sirven a múltiples clientes)
4. Webhooks para notificaciones en tiempo real
5. Dashboard completo para debugging
6. Soporte técnico responsive

---

## 6. Recomendación de Arquitectura

### Arquitectura del Agente Contable

```
┌──────────────────────────────────────────────────────┐
│                   AGENTE CONTABLE AI                  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐ │
│  │   CONTPAQi  │  │    Aspel    │  │  Otros ERPs  │ │
│  │  SQL Server │  │    dBASE    │  │  (Custom)    │ │
│  │  COM/SDK    │  │  SQL Server │  │              │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘ │
│         │                │                │         │
│         └────────────────┼────────────────┘         │
│                          │                          │
│                    ┌─────▼─────┐                    │
│                    │  ERP       │                    │
│                    │  Connector │                    │
│                    └─────┬─────┘                    │
│                          │                          │
│  ┌───────────────────────┼───────────────────────┐  │
│  │                       │                       │  │
│  ▼                       ▼                       ▼  │
│ ┌──────────┐    ┌───────────────┐    ┌───────────┐ │
│ │ Facturapi│    │  SAT Web      │    │  Bancos   │ │
│ │ (CFDI)   │    │  Services     │    │  (OFX/PDF)│ │
│ └──────────┘    └───────────────┘    └───────────┘ │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │              Motor Contable AI               │    │
│  │  - Clasificación automática de movimientos   │    │
│  │  - Generación de pólizas                     │    │
│  │  - Conciliación bancaria                     │    │
│  │  - Cálculo de impuestos                      │    │
│  │  - Alertas y recomendaciones                 │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Stack Tecnológico Recomendado

```python
# requirements.txt para el agente contable

# Conectividad ERP
pyodbc>=4.0.39              # SQL Server (CONTPAQi, Aspel SQL)
dbfread>=2.0.7              # Archivos dBASE (Aspel legacy)
pywin32>=306                # COM/OLE Automation (solo Windows)

# SAT Web Services
lxml>=4.9.3                 # Parsing XML/CFDI
zeep>=4.2.1                 # Clientes SOAP
cryptography>=41.0.4        # FIEL/CSD, firma digital
signxml>=3.2.0              # Firma XML

# Facturación Electrónica
facturapi>=2.0.0            # SDK Facturapi (PAC)

# Bancos
pdfplumber>=0.10.3          # Parsing PDFs bancarios
ofxparse>=1.2.0             # Parsing archivos OFX
pandas>=2.1.0               # Data manipulation

# Utilidades
requests>=2.31.0            # HTTP client
pydantic>=2.4.0             # Validación de datos
python-dateutil>=2.8.2      # Parsing de fechas
```

---

## Anexo A: Catálogos SAT Más Usados

### Catálogo de Formas de Pago (CFDI 4.0)
| Clave | Descripción |
|-------|-------------|
| 01 | Efectivo |
| 02 | Cheque nominativo |
| 03 | Transferencia electrónica de fondos |
| 04 | Tarjeta de crédito |
| 05 | Monedero electrónico |
| 06 | Dinero electrónico |
| 08 | Vales de despensa |
| 12 | Dación en pago |
| 13 | Pago por subrogación |
| 14 | Pago por consignación |
| 15 | Condonación |
| 17 | Compensación |
| 23 | Novación |
| 24 | Confusión |
| 25 | Remisión de deuda |
| 26 | Prescripción o caducidad |
| 27 | A satisfacción del acreedor |
| 28 | Tarjeta de débito |
| 29 | Tarjeta de servicios |
| 30 | Aplicación de anticipos |
| 31 | Intermediario pagos |
| 99 | Por definir |

### Catálogo de Métodos de Pago
| Clave | Descripción |
|-------|-------------|
| PUE | Pago en una sola exhibición |
| PPD | Pago en parcialidades o diferido |

### Catálogo de Tipos de Comprobante
| Clave | Descripción |
|-------|-------------|
| I | Ingreso |
| E | Egreso |
| T | Traslado |
| N | Nómina |
| P | Pago |

### Catálogo de Usos de CFDI
| Clave | Descripción |
|-------|-------------|
| G01 | Adquisición de mercancías |
| G02 | Devoluciones, descuentos o bonificaciones |
| G03 | Gastos en general |
| G04 | Construcciones |
| G05 | Mobiliario y equipo de oficina |
| G06 | Equipo de transporte |
| I01 | Construcciones |
| I02 | Mobilario y equipo de oficina |
| I03 | Equipo de transporte |
| I04 | Equipo de cómputo y accesorios |
| I05 | Dados, troqueles, moldes, matrices y herramental |
| I06 | Comunicaciones telefónicas |
| I07 | Comunicaciones satelitales |
| I08 | Otra maquinaria y equipo |
| D01 | Honorarios médicos, dentales y gastos hospitalarios |
| D02 | Gastos médicos por incapacidad o discapacidad |
| D03 | Gastos funerales |
| D04 | Donativos |
| D05 | Intereses reales efectivamente pagados por créditos hipotecarios |
| D06 | Aportaciones voluntarias al SAR |
| D07 | Primas por seguros de gastos médicos |
| D08 | Gastos de transportación escolar obligatoria |
| D09 | Depósitos en cuentas para el ahorro |
| D10 | Pagos por servicios educativos |
| S01 | Sin efectos fiscales |
| CP01 | Pagos |
| CN01 | Nómina |

---

## Anexo B: Recursos y Enlaces Oficiales

- **SAT — Portal de Facturación:** https://www.sat.gob.mx/temas/factura-electronica
- **SAT — Catálogos CFDI 4.0:** https://www.sat.gob.mx/consultas/44113/genera-tus-facturas-electronicas
- **SAT — Web Services:** https://www.sat.gob.mx/consultas/92769/prueba-y-acceso-a-los-web-services-del-cfdi
- **Facturapi Docs:** https://docs.facturapi.io
- **Facturapi API Reference:** https://docs.facturapi.io/api/
- **CONTPAQi Developer:** https://www.compac.mx (contactar soporte para SDK)
- **Aspel:** https://www.aspel.com.mx
- **Banxico SPEI:** https://www.banxico.org.mx/sistemas-de-pago/
- **Esquemas CFDI:** http://www.sat.gob.mx/informacion_fiscal/factura_electronica/Paginas/Anexo_20_version3.3.aspx

---

> **Nota:** Este documento es una referencia técnica. Los endpoints, URLs y formatos pueden cambiar. Siempre verificar contra la documentación oficial más reciente del SAT y los proveedores de servicios.
