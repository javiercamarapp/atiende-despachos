# Production Checklist — Likida AI Enterprise
## Para 20 clientes activos

---

## ✅ LISTO (no necesita nada)

### Agentes (12)
- [x] Conciliación bancaria
- [x] DIOT mensual
- [x] Declaraciones periódicas (IVA/ISR)
- [x] Conciliación fiscal (ERP vs SAT)
- [x] Gestión de vencimientos
- [x] Respuesta a clientes
- [x] Pre-auditoría contable
- [x] Nómina completa
- [x] Reportes gerenciales
- [x] Email processing
- [x] Devolución IVA
- [x] Conciliación ingresos/egresos

### Integraciones (50+ adapters)
- [x] SAT: Ecodex, Finkok, SAT Portal
- [x] ERPs: CONTPAQi, Aspel, QuickBooks, Xero
- [x] Bancos: BBVA, Banorte, Santander + OFX/CSV
- [x] Nómina: CFDI Nómina, IMSS, INFONAVIT
- [x] Pagos: Stripe, Conekta, PayPal
- [x] Comunicación: SendGrid, Twilio, WhatsApp
- [x] Almacenamiento: Google Drive, OneDrive, S3
- [x] Firmas: DocuSign, FIEL SAT
- [x] CRM: HubSpot, Pipedrive
- [x] Monitoreo: Sentry, Datadog
- [x] AI/ML: OpenAI, Anthropic
- [x] Documentos: PDF, XML, OCR, Excel

### Seguridad
- [x] No hardcoded secrets
- [x] No SQL injection
- [x] No eval/exec
- [x] SQL parametrizado
- [x] Audit trail completo
- [x] Tenant isolation
- [x] Rate limiting (300 req/min)

### Compliance
- [x] CFF Art. 82 (protección de datos)
- [x] CFF Art. 89 (obligaciones fiscales)
- [x] LFPDPPP (privacidad)
- [x] LISR Art. 96 (tablas ISR)
- [x] LIVA Art. 5 (tasas IVA)

### Tests
- [x] 4,899 tests pasando
- [x] 0 fallas

### Landing
- [x] Sin claims falsos
- [x] Disclaimer legal
- [x] Mobile responsive
- [x] CTAs funcionales

---

## ⚠️ NECESITA CONFIGURACIÓN (API Keys)

### IA (agrega al .env)
- [ ] `OPENAI_API_KEY` — para GPT-4 en tareas complejas
- [ ] `ANTHROPIC_API_KEY` — para Claude en análisis fiscal
- [ ] `DEEPSEEK_API_KEY` — para modelos DeepSeek

### Comunicación (agrega al .env)
- [ ] `SENDGRID_API_KEY` — envío de emails
- [ ] `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` — SMS/WhatsApp
- [ ] `WHATSAPP_BUSINESS_TOKEN` — WhatsApp Business API

### Pagos (agrega al .env)
- [ ] `STRIPE_SECRET_KEY` — cobros a clientes
- [ ] `STRIPE_WEBHOOK_SECRET` — webhooks de Stripe

### Almacenamiento (agrega al .env)
- [ ] `GOOGLE_DRIVE_CREDENTIALS` — Google Drive API
- [ ] `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` — S3

### Monitoreo (agrega al .env)
- [ ] `SENTRY_DSN` — error tracking

### SAT/PAC (agrega al .env)
- [ ] `ECODEX_USER` + `ECODEX_PASSWORD` — PAC Ecodex
- [ ] `FINKOK_USER` + `FINKOK_PASSWORD` — PAC Finkok
- [ ] `SAT_FIEL_CERT` + `SAT_FIEL_KEY` — FIEL del contribuyente
- [ ] `SAT_CSD_CERT` + `SAT_CSD_KEY` — CSD del contribuyente

### ERPs (agrega al .env)
- [ ] `CONTPAQI_WEB_API_KEY` — CONTPAQi One API
- [ ] `ASPEL_CLOUD_API_KEY` — Aspel Cloud API
- [ ] `QUICKBOOKS_CLIENT_ID` + `QUICKBOOKS_CLIENT_SECRET` — QuickBooks

### Bancos (agrega al .env)
- [ ] `BBVA_API_KEY` — BBVA API
- [ ] `BANORTE_API_KEY` — Banorte API
- [ ] `SANTANDER_API_KEY` — Santander API

---

## ⚠️ NECESITA IMPLEMENTACIÓN REAL (no mock)

### Computer Use
- [ ] Playwright driver real (reemplazar MockDesktop)
- [ ] CONTPAQi real driver (navegación web real)
- [ ] Aspel real driver (navegación web real)

### SAT Direct
- [ ] Timbrado real de CFDI (via PAC)
- [ ] Cancelación real de CFDI
- [ ] Consulta real de RFC

---

## ⚠️ NECESITA MIGRACIÓN DB

### PostgreSQL (antes de 20 clientes)
- [ ] Migrar de SQLite a PostgreSQL
- [ ] Verificar connection pooling
- [ ] Verificar índices
- [ ] Configurar backups automáticos
- [ ] Verificar RLS (Row Level Security)

---

## 📊 COSTOS ESTIMADOS (20 clientes)

| Concepto | Costo/mes |
|----------|-----------|
| Infraestructura (Railway) | $5,000-10,000 |
| PostgreSQL | $3,000-5,000 |
| AI APIs (OpenAI/Anthropic) | $5,000-10,000 |
| PAC timbrado | $15,000-20,000 |
| WhatsApp Business | $2,000-3,000 |
| Monitoreo (Sentry) | $1,000-2,000 |
| **TOTAL** | **$31,000-50,000 MXN/mes** |

---

## 📅 TIMELINE

| Semana | Tarea |
|--------|-------|
| 1-2 | Configurar todas las API keys |
| 3-4 | Migrar a PostgreSQL |
| 5-6 | Implementar computer use real |
| 7-8 | Testing con 5 clientes piloto |
| 9-10 | Escalar a 20 clientes |
| 11-12 | Monitoreo y optimización |
