# Likida AI Platform — Integrations Guide

> **Version:** 1.0 | **Last Updated:** August 2026
> **Audience:** Developers, Integration Engineers, Technical Leads

---

## Table of Contents

1. [Overview](#1-overview)
2. [SAT Integrations](#2-sat-integrations)
3. [ERP Integrations](#3-erp-integrations)
4. [Bank Integrations](#4-bank-integrations)
5. [Payroll (Nómina) Integrations](#5-payroll-nómina-integrations)
6. [Other Integrations](#6-other-integrations)
7. [Integration Status Matrix](#7-integration-status-matrix)
8. [Setup Instructions](#8-setup-instructions)
9. [Security Considerations](#9-security-considerations)

---

## 1. Overview

The Likida AI platform integrates with Mexico's tax authority (SAT), accounting software (ERPs), banking institutions, payroll systems, and productivity tools to automate workflows for accounting firms (despachos contables).

### Integration Categories

| Category | Method | Description |
|----------|--------|-------------|
| **API-Based** | REST / OAuth 2.0 | Direct integration via official APIs. Most reliable and maintainable. |
| **Computer Use** | Desktop automation | GUI automation for software without APIs (desktop ERPs, SAT portal). Requires cua-driver. |
| **File-Based** | Parsing (OFX, CSV, XML, PDF) | Import/export via structured files. No live connection required. |
| **Protocol** | SMTP/IMAP, SDK | Standard protocols for email, PDF generation, XML signing. |

### Cost Summary

| Integration Category | Estimated Monthly Cost |
|---------------------|----------------------|
| PAC (CFDI stamping) | $500–5,000 MXN |
| Cloud ERPs | $1,000–10,000 MXN |
| WhatsApp Business | $100–2,000 MXN |
| Cloud Storage | $100–500 MXN |
| Infrastructure | $2,000–10,000 MXN |
| **Total** | **$3,700–27,500 MXN/month** |

> **Note:** Bank APIs and government APIs (IMSS, INFONAVIT, SAR) are free with a valid account/e.firma. Costs scale with transaction volume.

---

## 2. SAT Integrations

The SAT (Servicio de Administración Tributaria) is Mexico's tax authority. Integration is mandatory for any accounting platform operating in Mexico.

### 2.1 CFDI 4.0 (Comprobante Fiscal Digital por Internet)

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official REST API |
| **URL** | `https://portalcfdi.facturaelectronica.sat.gob.mx` |
| **Auth** | e.firma (FIEL) + CSD (Certificado de Sello Digital) |
| **Sandbox** | ✅ Available for developers with test CSD |
| **Computer Use** | ❌ Not required |
| **Cost** | Free (CSD issuance) + PAC stamping fees |

**Operations:**
- Issue CFDI (Ingreso, Egreso, Traslado, Nómina, Pago)
- Cancel CFDI
- Query CFDI by UUID, RFC, or date range
- Validate CFDI status (Vigente, Cancelado, etc.)
- Query payment complements

**PAC Providers (Proveedores Autorizados de Certificación):**

| Provider | Cost per Stamp |
|----------|---------------|
| Ecodex | $2–5 MXN |
| Finkok | $2–5 MXN |
| FacturaDirecta | $2–4 MXN |
| Facturapi | $2–4 MXN |
| PAXFACTURAS | $2–5 MXN |

**Limitations:**
- Requires valid and current CSD issued by the SAT
- SAT may experience downtime during high-demand periods
- Stamping requires a PAC (not direct to SAT)
- Response times vary by server load

---

### 2.2 CFDI Cancellation

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official |
| **Auth** | e.firma or CSD of the issuer |
| **Computer Use** | ❌ Not required |

**Process:**
1. Issuer submits cancellation request to SAT
2. If receiver accepts within 48 hours → cancelled immediately
3. If no response → SAT evaluates the request
4. CFDI issued before 2019 may be cancelled without receiver acceptance

**Limitations:**
- Payroll CFDI only cancellable if no earnings recorded in the month
- Specific deadlines apply to retention CFDI
- Cancellation reason code required
- 72 business hours to accept/reject

---

### 2.3 RFC Status Check

| Aspect | Detail |
|--------|--------|
| **API** | ⚠️ Limited |
| **URL** | `https://www.sat.gob.mx/aplicacion/login/53027/genera-tu-constancia-de-situacion-fiscal` |
| **Auth** | e.firma or SAT portal password |
| **Computer Use** | ✅ Required (no public REST API) |

**Data Retrieved:**
- Tax status certificate (constancia de situación fiscal)
- Tax regime
- Tax obligations
- Economic activities
- Account balances (debt)

> **Note:** Requires web navigation or scraping of the SAT portal. Use computer-use automation for this integration.

---

### 2.4 DIOT (Declaración Informativa Operaciones con Terceros)

| Aspect | Detail |
|--------|--------|
| **API** | ⚠️ Limited |
| **Format** | CSV (SAT format) |
| **Computer Use** | ✅ Required (upload via web portal) |

**Process:**
1. Generate CSV file in SAT format
2. Upload via SAT web portal or electronic service
3. Must be submitted weekly before the 20th of the following month

---

### 2.5 Contabilidad Electrónica

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official (electronic service) |
| **Computer Use** | ❌ Not required |
| **Applies to** | Companies with assets > $46M MXN |

**Documents:**

| Document | Deadline | Format |
|----------|----------|--------|
| Balanza de Comprobación (Balance) | Monthly — before the 20th | XML per SAT catalog |
| Cuenta (Account Detail) | Monthly | XML with movement details by account |
| Catálogo de Cuentas (Chart of Accounts) | Once or at fiscal year start | XML per catalog structure |

---

### 2.6 Tax Declarations

| Type | Deadline | Computer Use Required |
|------|----------|----------------------|
| Monthly Declaration (IVA, ISR, IEPS) | 17th of following month | ✅ Yes |
| Provisional Declaration (ISR) | Monthly — 17th of following month | ✅ Yes |
| Annual Declaration | April of following year | ✅ Yes |
| Provisional Payments | Monthly | ✅ Yes |

> **Note:** All tax declarations are submitted through the SAT web portal (no REST API exists).

---

### 2.7 Dictamen Fiscal (Tax Audit Report)

| Aspect | Detail |
|--------|--------|
| **Computer Use** | ✅ Required |
| **Note** | Generated and submitted via SAT portal. No direct API. |

---

## 3. ERP Integrations

### 3.1 Desktop ERPs (Local Installation)

#### CONTPAQi (Contpaqi Contabilidad)

| Aspect | Detail |
|--------|--------|
| **Vendor** | INTRO (Grupo CONTPAQi) |
| **Type** | Desktop |
| **Official API** | ❌ No |
| **Integration Methods** | DB (SQL Server/ODBC), 3rd-party APIs, TXT/CSV import/export, COM automation, SDK |
| **Computer Use** | ✅ Required |
| **Cost** | License: $2,000–15,000 MXN/year |

**Available Modules:**
- CONTPAQi Contabilidad
- CONTPAQi Nómina
- CONTPAQi Facturación
- CONTPAQi Nómina Profesional

**Data Exchanged:** Chart of accounts, accounting journals, sub-ledgers, trial balance, financial statements, invoices, payroll

**Limitations:** Undocumented DB schema, schema changes between versions, requires valid license, no official integration support.

---

#### Aspel (SAE, COI, Nómina)

| Aspect | Detail |
|--------|--------|
| **Vendor** | INTRO (Grupo CONTPAQi / Aspel) |
| **Type** | Desktop |
| **Official API** | ❌ No |
| **Integration Methods** | DB (SQL Server), file import/export, unofficial API |
| **Computer Use** | ✅ Required |
| **Cost** | License: $1,500–10,000 MXN/year |

**Available Modules:**
- SAE (Sistema de Administración de Empresas)
- COI (Contabilidad Integral)
- Nómina Aspel
- Aspel Cloud

**Data Exchanged:** Chart of accounts, accounting journals, invoices, payroll, inventory, A/P and A/R

---

#### QuickBooks Desktop (MX)

| Aspect | Detail |
|--------|--------|
| **Vendor** | Intuit |
| **Type** | Desktop |
| **Official API** | ✅ Yes (SDK — QBXML) |
| **Auth** | OAuth 2.0 + local SDK |
| **Sandbox** | ✅ Available (company file copy) |
| **Computer Use** | ❌ Not required (SDK available, Windows only) |
| **Cost** | License: $3,000–20,000 MXN/year |

**Data Exchanged:** Customers, vendors, invoices, payments, bank transactions, chart of accounts, reports

**Limitations:** Requires QuickBooks Desktop installed, SDK requires Windows, migration to QuickBooks Online in progress.

---

#### Other Desktop ERPs (Computer Use Only)

| Software | Vendor | Official API | Cost |
|----------|--------|-------------|------|
| **Peak** | Peak (Mexican) | ❌ No | $1,000–5,000 MXN/year |
| **Multileg** | Multileg (Mexican) | ❌ No | $800–4,000 MXN/year |
| **Euroweb** | Euroweb (Mexican) | ❌ No | $500–3,000 MXN/year |
| **Absis** | Absis Software (Mexican) | ❌ No | $500–3,000 MXN/year |

All four require computer-use automation. Limited documentation and small user bases.

---

### 3.2 Cloud ERPs

#### CONTPAQi One

| Aspect | Detail |
|--------|--------|
| **Vendor** | INTRO (Grupo CONTPAQi) |
| **Type** | Cloud/SaaS |
| **API** | ✅ Official REST |
| **URL** | `https://api.contpaq.com.mx` |
| **Docs** | `https://documentacion.contpaq.com.mx` |
| **Auth** | OAuth 2.0 (client_id + client_secret) |
| **Sandbox** | ✅ Available |
| **Computer Use** | ❌ Not required |
| **Cost** | $500–3,000 MXN/month |

**Modules:** Contabilidad, Facturación, Nómina, Compras, Cuentas por Pagar

**Data Exchanged:** Chart of accounts, journals, invoices, payroll, A/P and A/R, financial statements, CFDI

---

#### Aspel Cloud

| Aspect | Detail |
|--------|--------|
| **Vendor** | INTRO (Grupo CONTPAQi / Aspel) |
| **Type** | Cloud/SaaS |
| **API** | ✅ Official REST |
| **URL** | `https://api.aspel.com.mx` |
| **Docs** | `https://documentacion.aspel.com.mx` |
| **Auth** | OAuth 2.0 |
| **Sandbox** | ✅ Available |
| **Computer Use** | ❌ Not required |
| **Cost** | $300–2,500 MXN/month |

**Modules:** SAE Cloud, COI Cloud, Nómina Cloud

**Data Exchanged:** Chart of accounts, journals, invoices, payroll, inventory, A/P and A/R

---

#### QuickBooks Online (MX)

| Aspect | Detail |
|--------|--------|
| **Vendor** | Intuit |
| **Type** | Cloud/SaaS |
| **API** | ✅ Official REST |
| **Auth** | OAuth 2.0 with refresh tokens |
| **Sandbox** | ✅ Full sandbox for development |
| **Computer Use** | ❌ Not required |
| **Cost** | $300–1,500 MXN/month |

**Data Exchanged:** Customers, vendors, invoices, payments, bank transactions, chart of accounts, reports, CFDI (Mexico module)

**Limitations:** Transaction limits per plan, some Mexico features limited vs US, CFDI integration not always updated.

---

#### Xero (MX)

| Aspect | Detail |
|--------|--------|
| **Vendor** | Xero Limited |
| **Type** | Cloud/SaaS |
| **API** | ✅ Official REST |
| **URL** | `https://developer.xero.com/documentation/api/accounting/overview` |
| **Auth** | OAuth 2.0 |
| **Sandbox** | ✅ Demo company + partner sandbox |
| **Computer Use** | ❌ Not required |
| **Cost** | $400–1,200 MXN/month |

**Data Exchanged:** Customers, vendors, invoices, payments, bank transactions, chart of accounts, reports, inventory

**Limitations:** CFDI not natively integrated (requires PAC or add-on), limited support for Mexican regulations vs Australia/NZ.

---

#### Other Cloud ERPs

| Software | Vendor | API | Auth | Cost |
|----------|--------|-----|------|------|
| **Factor D** | Factor D (Mexican) | ✅ Yes | API Key | $200–800 MXN/month |
| **Taxko** | Taxko (Mexican) | ✅ Yes | API Key | $150–500 MXN/month |
| **FacturaDirecta** | FacturaDirecta (Mexican) | ✅ Yes | API Key + Token | $100–600 MXN/month |
| **Contpaqi Web** | INTRO | ❌ No | — | Included with CONTPAQi license |

- **Factor D:** Invoicing, basic accounting, payroll via API
- **Taxko:** Invoicing only (CFDI 4.0, cancellation, queries)
- **FacturaDirecta:** Invoicing only (CFDI 4.0, cancellation, payroll CFDI)
- **Contpaqi Web:** Requires computer-use (web scraping, no official API)

---

## 4. Bank Integrations

### 4.1 Bank APIs

| Bank | API | Auth | Cost | Formats |
|------|-----|------|------|---------|
| **BBVA México** | BBVA API Market | OAuth 2.0 | Free | OFX, CSV, PDF, QFX |
| **Banorte** | Official API | OAuth 2.0 | Free | OFX, CSV, PDF |
| **Santander México** | Official API | OAuth 2.0 | Free | OFX, CSV, PDF |
| **HSBC México** | Official API | OAuth 2.0 | Free | OFX, CSV, PDF |
| **Banamex (Citibanamex)** | Official API | OAuth 2.0 | Free | OFX, CSV, PDF |

**Data Retrieved:** Account statements, transactions, balances, transfers, service payments

**BBVA API Market Details:**
- URL: `https://developer.bbva.com`
- Public API limited to account queries and transactions
- Transfers require additional OTP authentication
- Rate limits on public API

---

### 4.2 OFX/CSV Universal Parser

#### OFX Format (Open Financial Exchange)

| Aspect | Detail |
|--------|--------|
| **Description** | Standard for financial data exchange |
| **Libraries** | `ofxparse` (Python), `ofx` (Ruby), `qfx.js` (Node.js) |
| **Recommendation** | Preferred format for automatic bank statement import |

#### CSV Parsing

**Challenges:**
- Each bank has a different CSV format
- Different encodings (UTF-8, Latin-1)
- Different delimiters (comma, semicolon, tab)
- Different columns and order

**Solution:** Bank-specific parsers or standardization layer. Use `pandas` for flexible parsing.

#### PDF Extraction (Last Resort)

| Tool | Description |
|------|-------------|
| OCR | Tesseract, AWS Textract, Google Vision |
| Table Extraction | Tabula, camelot |

> Use PDF extraction only when no structured format (OFX/CSV) is available.

---

## 5. Payroll (Nómina) Integrations

### 5.1 CFDI de Nómina 1.2

| Aspect | Detail |
|--------|--------|
| **Version** | 1.2 (current) |
| **API** | ✅ Official (SAT stamping API) |
| **URL** | `https://portalcfdi.facturaelectronica.sat.gob.mx` |
| **Auth** | e.firma (FIEL) + CSD of payroll issuer |
| **Computer Use** | ❌ Not required |
| **Cost** | CSD issuance + PAC stamping ($2–5 MXN per stamp) |

**Operations:**
- Issue payroll CFDI (type: Nómina)
- Cancel payroll CFDI
- Query issued payroll CFDI

**Complemento de Nómina 1.2 Fields:**

**Percepciones (Earnings):** Sueldos, Vacaciones, Aguinaldo, Prima dominical, Prima vacacional, Prima de antigüedad, Participación en utilidades, Compensación, Horas extra, Primas, Gratificaciones, Indemnización, Jubilación, Pagos por separación, Subsidio al empleo, Becas, Comisiones, Cuota al SNTE, Fondo de ahorro, Enajenación de acciones, Reparto de utilidades, Cuotas al IMSS, Aplicación de anticipo

**Deducciones (Deductions):** Sueldos, Enajenación de acciones, Aportaciones adicionales al SAR, Cuotas al IMSS, Préstamos al SAR, Pagos por crédito de vivienda, Descuento por incapacidad, Pensión alimenticia, Renta, Préstamos, Hipotecas, Fondo de ahorro, Cuotas sindicales, Pagos hechos con exceso de errores, Otras deducciones

**Otros Pagos (Other Payments):** Reembolso por gastos médicos, Fondo de ahorro, Cuotas al IMSS, Comisión por administración de ahorro, Cuotas al SAR, Subsidio por incapacidad, Becas, Horas extra, Primas, Gratificaciones, Indemnización, Jubilación, Pagos por separación, Subsidio al empleo, Aplicación de anticipo

**Limitations:**
- Payroll CFDI only cancellable if no earnings in the month
- Requires valid and current CSD
- Stamping through PAC
- Must be stamped before payment

---

### 5.2 IMSS (Instituto Mexicano del Seguro Social)

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official |
| **URL** | `https://serviciosdigitales.imss.gob.mx` |
| **Auth** | e.firma (FIEL) or IMSS password |
| **Computer Use** | ❌ Not required |
| **Cost** | Free |

**Available Services:**

| Service | API Available |
|---------|--------------|
| Employee registration (Alta) | ✅ Yes |
| Queried weeks contributed (Semanas cotizadas) | ✅ Yes |
| Employer quota payment (Cuotas patronales) | ✅ Yes |
| Debt inquiry | ✅ Yes |
| Disability/incapacity records | ✅ Yes |
| Weeks contributed certificate | ✅ Yes |

**Limitations:** Requires employer's e.firma, some procedures require web portal, variable response times.

---

### 5.3 INFONAVIT

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official |
| **URL** | `https://www.infonavit.org.mx` |
| **Auth** | e.firma (FIEL) or INFONAVIT password |
| **Computer Use** | ❌ Not required |
| **Cost** | Free |

**Available Services:**

| Service | API Available |
|---------|--------------|
| Employer inquiry | ✅ Yes |
| Employer quota payment | ✅ Yes |
| Debt inquiry | ✅ Yes |
| No-debt certificate | ✅ Yes |

---

### 5.4 SAR (Sistema de Ahorro para el Retiro)

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official |
| **URL** | `https://www.e-sar.com.mx` |
| **Auth** | e.firma (FIEL) or SAR password |
| **Computer Use** | ❌ Not required |
| **Cost** | Free |

**Available Services:**

| Service | API Available |
|---------|--------------|
| Employer inquiry | ✅ Yes |
| Employer quota payment | ✅ Yes |
| Debt inquiry | ✅ Yes |

---

## 6. Other Integrations

### 6.1 Excel / Google Sheets

#### Microsoft Excel (Microsoft Graph API)

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Microsoft Graph API |
| **Auth** | OAuth 2.0 |
| **Computer Use** | ❌ Not required |
| **Libraries** | openpyxl, xlsxwriter (Python), EPPlus (.NET), SheetJS (JS) |

#### Google Sheets API

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Google Sheets API |
| **Auth** | OAuth 2.0 |
| **Computer Use** | ❌ Not required |
| **Libraries** | gspread (Python), sheets (Node.js) |

**Data Exchanged:** Spreadsheets, data tables, financial reports, accounting templates

---

### 6.2 Email (SMTP/IMAP)

| Protocol | Purpose | Ports | Auth |
|----------|---------|-------|------|
| SMTP | Sending emails | 587, 465, 25 | User/Password or OAuth 2.0 |
| IMAP | Receiving/reading emails | 993, 143 | User/Password or OAuth 2.0 |

**Provider Configuration:**

| Provider | SMTP | IMAP | Auth |
|----------|------|------|------|
| Gmail | smtp.gmail.com | imap.gmail.com | OAuth 2.0 or App Password |
| Outlook/365 | smtp.office365.com | outlook.office365.com | OAuth 2.0 |
| Yahoo | smtp.mail.yahoo.com | imap.mail.yahoo.com | App Password |

**Libraries:** `smtplib` (Python), `nodemailer` (Node.js), ActionMailer (Ruby)

---

### 6.3 WhatsApp Business API

| Aspect | Detail |
|--------|--------|
| **API** | ✅ Official |
| **URL** | `https://developers.facebook.com/docs/whatsapp` |
| **Auth** | API Key + Token |
| **Computer Use** | ❌ Not required |

**Providers:**

| Provider | Auth | Cost |
|----------|------|------|
| Meta Cloud API (direct) | Bearer Token | Free (with verified number) |
| Twilio | Account SID + Auth Token | $0.005–0.05 USD/message |
| MessageBird | API Key | $0.005–0.05 USD/message |

**Data Exchanged:** Text messages, template messages, documents (PDFs, images), interactive messages (buttons, lists)

**Limitations:** Verified WhatsApp Business number required, sending limits for new accounts, templates require Meta approval.

---

### 6.4 Cloud Storage

| Provider | API | Auth | Cost |
|----------|-----|------|------|
| Google Drive | ✅ Official | OAuth 2.0 | Free (15GB) / $2–30 USD/month |
| OneDrive | ✅ Official (Graph API) | OAuth 2.0 | Free (5GB) / $2–10 USD/month |
| Dropbox | ✅ Official | OAuth 2.0 | Free (2GB) / $10–20 USD/month |

**Data Exchanged:** Files, folders, metadata, permissions

---

### 6.5 PDF Generation

| Tool | Type | Computer Use | Cost |
|------|------|-------------|------|
| ReportLab (Python) | Library | ❌ No | Free (open source) |
| wkhtmltopdf | CLI/Wrapper | ❌ No | Free (open source) |
| Puppeteer (Node.js) | Library | ❌ No | Free (open source) |
| Adobe PDF Services API | Cloud API | ❌ No | Freemium (100 transactions/month free) |

---

### 6.6 XML Parsing & Signing

**XML Parsing:**

| Tool | Description |
|------|-------------|
| `lxml` (Python) | Full XML parsing |
| `xml.etree.ElementTree` (Python stdlib) | Basic XML parsing |
| XSLT processors | XML transformation |

**SAT XSD Schemas:**
- `http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd`
- `http://www.sat.gob.mx/sitio_internet/cfd/Nomina12/nomina12.xsd`
- `http://www.sat.gob.mx/sitio_internet/cfd/TipoDatos/tdCFDI/tdCFDI.xsd`

**XML Signing:**

| Tool | Description |
|------|-------------|
| `xmlsec` (Python) | XML signing with XAdES-BES |
| `pyxades` (Python) | XAdES signing for Python |
| `openssl` (CLI) | Signing and encryption with certificates |

**Requirements:** CSD from SAT (.cer + .key) and keystore password.

---

## 7. Integration Status Matrix

### 7.1 API-Based Integrations

| Integration | API | Computer Use | Status | Est. Monthly Cost |
|-------------|-----|-------------|--------|-------------------|
| CFDI 4.0 (SAT) | ✅ | ❌ | Ready | $2–5 MXN/stamp (PAC) |
| CFDI Cancellation | ✅ | ❌ | Ready | $2–5 MXN/stamp (PAC) |
| Contabilidad Electrónica | ✅ | ❌ | Ready | Free |
| CONTPAQi One | ✅ | ❌ | Ready | $500–3,000 MXN |
| Aspel Cloud | ✅ | ❌ | Ready | $300–2,500 MXN |
| QuickBooks Online | ✅ | ❌ | Ready | $300–1,500 MXN |
| Xero | ✅ | ❌ | Ready | $400–1,200 MXN |
| Factor D | ✅ | ❌ | Ready | $200–800 MXN |
| Taxko | ✅ | ❌ | Ready | $150–500 MXN |
| FacturaDirecta | ✅ | ❌ | Ready | $100–600 MXN |
| BBVA México | ✅ | ❌ | Ready | Free |
| Banorte | ✅ | ❌ | Ready | Free |
| Santander México | ✅ | ❌ | Ready | Free |
| HSBC México | ✅ | ❌ | Ready | Free |
| Banamex | ✅ | ❌ | Ready | Free |
| CFDI Nómina 1.2 | ✅ | ❌ | Ready | $2–5 MXN/stamp |
| IMSS | ✅ | ❌ | Ready | Free |
| INFONAVIT | ✅ | ❌ | Ready | Free |
| SAR | ✅ | ❌ | Ready | Free |
| Excel (Graph API) | ✅ | ❌ | Ready | Free |
| Google Sheets | ✅ | ❌ | Ready | Free |
| WhatsApp Business | ✅ | ❌ | Ready | Variable |
| Google Drive | ✅ | ❌ | Ready | Free / $2–30 USD |
| OneDrive | ✅ | ❌ | Ready | Free / $2–10 USD |
| Dropbox | ✅ | ❌ | Ready | Free / $10–20 USD |

### 7.2 Computer-Use Required Integrations

| Integration | Reason | Alternative |
|-------------|--------|-------------|
| RFC Status Check (SAT) | No public REST API | Web scraping |
| DIOT | Upload via web portal | Manual CSV generation |
| Tax Declarations | SAT web portal | None (portal mandatory) |
| Dictamen Fiscal | SAT web portal | None (portal mandatory) |
| CONTPAQi Desktop | No official API | SQL Server DB access |
| Aspel Desktop | No official API | SQL Server DB access |
| Peak Desktop | No official API | SQL Server DB access |
| Multileg Desktop | No official API | None |
| Euroweb Desktop | No official API | None |
| Absis Desktop | No official API | None |
| Contpaqi Web | No official API | Web scraping |

### 7.3 File-Based Integrations

| Integration | Method | Computer Use Required |
|-------------|--------|----------------------|
| Bank statements (CSV/OFX/PDF) | File parsing | ❌ No |
| Email (SMTP/IMAP) | Standard protocol | ❌ No |
| PDF generation | Local libraries | ❌ No |
| XML parsing | Local libraries | ❌ No |
| XML signing | Local libraries | ❌ No |

---

## 8. Setup Instructions

### 8.1 Environment Variables

Create a `.env` file in the project root with the following configuration:

```bash
# =============================================
# SAT / CFDI Configuration
# =============================================
SAT_CSD_CERT_PATH=/path/to/csd_certificate.cer
SAT_CSD_KEY_PATH=/path/to/csd_private.key
SAT_CSD_PASSWORD=your_csd_password

# PAC Provider
PAC_PROVIDER=ecodex          # Options: ecodex, finkok, facturadirecta
PAC_API_KEY=your_pac_api_key
PAC_API_SECRET=your_pac_api_secret
PAC_API_URL=https://wsfactura.ecodex.com.mx/...

# e.firma (FIEL)
E_FIRMA_CERT_PATH=/path/to/fiel_certificate.cer
E_FIRMA_KEY_PATH=/path/to/fiel_private.key
E_FIRMA_PASSWORD=your_fiel_password

# =============================================
# ERP Configuration
# =============================================

# CONTPAQi One
CONTPAQI_ONE_CLIENT_ID=your_client_id
CONTPAQI_ONE_CLIENT_SECRET=your_client_secret
CONTPAQI_ONE_API_URL=https://api.contpaq.com.mx

# Aspel Cloud
ASPEL_CLOUD_CLIENT_ID=your_client_id
ASPEL_CLOUD_CLIENT_SECRET=your_client_secret
ASPEL_CLOUD_API_URL=https://api.aspel.com.mx

# QuickBooks Online
QBO_CLIENT_ID=your_client_id
QBO_CLIENT_SECRET=your_client_secret
QBO_ACCESS_TOKEN=your_access_token
QBO_REFRESH_TOKEN=your_refresh_token
QBO_COMPANY_ID=your_company_id
QBO_ENVIRONMENT=sandbox        # Options: sandbox, production

# Xero
XERO_CLIENT_ID=your_client_id
XERO_CLIENT_SECRET=your_client_secret
XERO_REDIRECT_URI=http://localhost:8000/callback

# =============================================
# Bank Configuration
# =============================================
BBVA_API_KEY=your_bbva_api_key
BBVA_API_SECRET=your_bbva_api_secret
BANORTE_API_KEY=your_banorte_api_key
BANORTE_API_SECRET=your_banorte_api_secret

# =============================================
# Email (SMTP/IMAP)
# =============================================
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
IMAP_HOST=imap.gmail.com
IMAP_PORT=993

# =============================================
# WhatsApp Business
# =============================================
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_ACCESS_TOKEN=your_access_token
WHATSAPP_API_VERSION=v17.0

# =============================================
# Cloud Storage
# =============================================
GOOGLE_DRIVE_CREDENTIALS_PATH=/path/to/service_account.json
ONEDRIVE_CLIENT_ID=your_client_id
ONEDRIVE_CLIENT_SECRET=your_client_secret
DROPBOX_ACCESS_TOKEN=your_access_token

# =============================================
# General Settings
# =============================================
ENVIRONMENT=development         # Options: development, staging, production
LOG_LEVEL=INFO
ENCRYPTION_KEY=your_32char_encryption_key_here!!
```

### 8.2 PAC Provider Setup (Ecodex Example)

1. Register at [ecodex.com.mx](https://www.ecodex.com.mx)
2. Obtain API credentials (API Key + Secret)
3. Configure test environment with CSD de prueba
4. Set environment variables:
   ```bash
   PAC_PROVIDER=ecodex
   PAC_API_KEY=ecodex_api_key_here
   PAC_API_SECRET=ecodex_api_secret_here
   PAC_API_URL=https://wsfactura.ecodex.com.mx/...
   ```
5. Test with sandbox CSD before production

### 8.3 QuickBooks Online Setup

1. Register at [developer.intuit.com](https://developer.intuit.com)
2. Create an app in the developer portal
3. Configure OAuth 2.0 redirect URI
4. Obtain Client ID and Client Secret
5. Complete OAuth flow to get access + refresh tokens
6. Configure:
   ```bash
   QBO_CLIENT_ID=your_client_id
   QBO_CLIENT_SECRET=your_client_secret
   QBO_COMPANY_ID=your_company_id
   QBO_ENVIRONMENT=sandbox
   ```

### 8.4 Xero Setup

1. Register at [developer.xero.com](https://developer.xero.com)
2. Create an app
3. Configure OAuth 2.0 redirect URI
4. Obtain Client ID and Client Secret
5. Complete OAuth flow
6. Configure:
   ```bash
   XERO_CLIENT_ID=your_client_id
   XERO_CLIENT_SECRET=your_client_secret
   ```

### 8.5 CONTPAQi One Setup

1. Register at [contpaq.com.mx](https://contpaq.com.mx)
2. Subscribe to CONTPAQi One API access
3. Obtain OAuth 2.0 credentials
4. Configure:
   ```bash
   CONTPAQi_ONE_CLIENT_ID=your_client_id
   CONTPAQi_ONE_CLIENT_SECRET=your_client_secret
   ```

### 8.6 IMSS / INFONAVIT / SAR Setup

1. Ensure employer has valid e.firma (FIEL)
2. Register for digital services at each institution's portal
3. Store e.firma credentials securely:
   ```bash
   E_FIRMA_CERT_PATH=/secure/path/fiel.cer
   E_FIRMA_KEY_PATH=/secure/path/fiel.key
   E_FIRMA_PASSWORD=your_fiel_password
   ```

### 8.7 WhatsApp Business Setup

1. Create a Meta Business account
2. Register a WhatsApp Business number
3. Create a WhatsApp Business API app at [developers.facebook.com](https://developers.facebook.com/docs/whatsapp)
4. Obtain Phone Number ID and Access Token
5. Configure:
   ```bash
   WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
   WHATSAPP_ACCESS_TOKEN=your_access_token
   ```

---

## 9. Security Considerations

### 9.1 Credential Storage

- **Never** store credentials in source code or version control
- Use **HashiCorp Vault** or **AWS Secrets Manager** for production
- Encrypt all credentials at rest with **AES-256**
- Use environment variables for local development
- Rotate credentials quarterly or on personnel changes

### 9.2 API Key Rotation

| Service | Rotation Frequency | Method |
|---------|-------------------|--------|
| PAC API Keys | Every 90 days | Provider portal |
| QBO/Xero Tokens | Auto-refresh | OAuth 2.0 refresh token flow |
| Bank API Keys | Every 90 days | Bank developer portal |
| WhatsApp Tokens | Every 90 days | Meta Business Manager |
| e.firma/FIEL | Per certificate expiry (usually 4 years) | SAT office |

### 9.3 Rate Limiting

| Service | Limit | Handling |
|---------|-------|----------|
| SAT API | Variable by endpoint | Retry with exponential backoff |
| BBVA API | Rate-limited | Queue requests, respect limits |
| QBO API | 500 requests/minute | Implement request throttling |
| Xero API | 60 calls/minute | Queue + throttle |
| WhatsApp | Depends on account tier | Monitor usage, implement queuing |

**Implementation:**
```python
# Example: Exponential backoff for rate-limited APIs
import asyncio
import random

async def call_with_backoff(fn, max_retries=5):
    for attempt in range(max_retries):
        try:
            return await fn()
        except RateLimitError:
            wait = 2 ** attempt + random.uniform(0, 1)
            await asyncio.sleep(wait)
    raise MaxRetriesExceeded()
```

### 9.4 Error Handling

All integrations should implement:

1. **Retry logic** — Transient failures (network, rate limits)
2. **Circuit breaker** — Stop calling failed services temporarily
3. **Fallback** — Graceful degradation when a service is unavailable
4. **Logging** — Structured logs for all API calls and errors
5. **Alerting** — Notify operations team on repeated failures
6. **Dead letter queue** — Capture failed messages for later processing

```python
# Example: Circuit breaker pattern
class CircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = "closed"  # closed, open, half-open
        self.last_failure_time = None

    async def call(self, fn):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit breaker is open")

        try:
            result = await fn()
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            raise
```

### 9.5 Data Protection

| Requirement | Implementation |
|-------------|---------------|
| **Encryption at rest** | AES-256 for all stored data |
| **Encryption in transit** | TLS 1.3 for all API calls |
| **Access control** | RBAC (Role-Based Access Control) |
| **Audit logging** | Log all fiscal operations with timestamps |
| **Data retention** | Comply with Mexican tax law (minimum 5 years for fiscal documents) |
| **Backup** | Daily backups of critical data |
| **PII handling** | Comply with Ley Federal de Protección de Datos Personales |

### 9.6 Compliance

- **Ley del ISR** — Income Tax Law compliance
- **Ley del IVA** — Value Added Tax Law compliance
- **Código Fiscal de la Federación** — Federal Tax Code
- **Ley Federal de Protección de Datos Personales** — Data protection law
- **Normas de Información Financiera (NIF)** — Financial reporting standards

---

## Appendix: Glossary

| Term | Definition |
|------|-----------|
| **CFDI** | Comprobante Fiscal Digital por Internet (Digital Tax Receipt) |
| **CSD** | Certificado de Sello Digital (Digital Seal Certificate) |
| **FIEL** | Firma Electrónica Avanzada (Advanced Electronic Signature) |
| **PAC** | Proveedor Autorizado de Certificación (Authorized Certification Provider) |
| **SAT** | Servicio de Administración Tributaria (Mexican Tax Authority) |
| **IMSS** | Instituto Mexicano del Seguro Social (Mexican Social Security Institute) |
| **INFONAVIT** | Instituto del Fondo Nacional de la Vivienda para los Trabajadores (Workers' Housing Fund Institute) |
| **SAR** | Sistema de Ahorro para el Retiro (Retirement Savings System) |
| **DIOT** | Declaración Informativa Operaciones con Terceros (Third-Party Operations Information Return) |
| **OFX** | Open Financial Exchange |
| **XSD** | XML Schema Definition |
| **XAdES** | XML Advanced Electronic Signatures |
| **ERP** | Enterprise Resource Planning |
| **SaaS** | Software as a Service |
| **IVA** | Impuesto al Valor Agregado (Value Added Tax) |
| **ISR** | Impuesto Sobre la Renta (Income Tax) |

---

**Document generated as part of the Likida AI platform integration research for accounting firms in Mexico.**
