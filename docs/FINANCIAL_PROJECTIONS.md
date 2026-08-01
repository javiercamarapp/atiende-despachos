# Financial Projections — Likida AI Enterprise (Seed A)

> Documento de proyecciones financieras para ronda Seed A.
> Basado en el stack actual (FastAPI + SQLite/PG, Railway/AWS, LLM APIs, WhatsApp Business API).
> **Todos los montos en MXN** (1 USD ≈ 20 MXN).

---

## 1. Revenue Model

### Pricing Tiers

| Tier | Precio/mes (MXN) | CFDI incluidos | Overage | Target |
|------|-------------------|----------------|---------|--------|
| **Starter** | $8,000 | 300 | $25/CFDI | Despachos pequeños (1-2 contadores) |
| **Pro** | $20,000 | 900 | $22/CFDI | Despachos medianos (3-5 contadores) |
| **Business** | $40,000 | 2,500 | $18/CFDI | Despachos grandes (6-15 contadores) |
| **Enterprise** | $80,000 | 6,000 | $15/CFDI | Despachos multi-sucursal (15+ contadores) |

### Assumptions de mix de clientes

| Tier | % clientes | ARPU ponderado |
|------|-----------|----------------|
| Starter | 50% | $8,000 |
| Pro | 30% | $20,000 |
| Business | 15% | $40,000 |
| Enterprise | 5% | $80,000 |
| **ARPU promedio** | — | **$16,400/mes** |

---

## 2. Cost Structure (Mensual)

### Infraestructura

| Componente | Descripción | Costo mensual (MXN) |
|------------|-------------|---------------------|
| **Railway / VPS** | App hosting + cron jobs | $1,500 - $5,000 |
| **PostgreSQL** | Base de datos multi-tenant (Railway/Supabase) | $1,000 - $3,000 |
| **CDN / Static** | Landing + dashboard (Cloudflare/Vercel) | $0 - $500 |
| **Almacenamiento** | S3/Blob para CFDIs XML + backups | $500 - $1,500 |
| **Dominio + TLS** | Certificados SSL + DNS | $200 |
| **Subtotal infra** | | **$3,200 - $10,200** |

### AI API Costs

| Provider | Uso | Costo estimado/CFDI |
|----------|-----|---------------------|
| **OpenAI (GPT-4o-mini)** | Clasificación de gastos, extracción de datos | $0.50 - $1.50 |
| **Anthropic (Claude 3.5 Haiku)** | Análisis complejo, anomalias | $0.80 - $2.00 |
| **DeepSeek** | Fallback low-cost | $0.10 - $0.30 |

**Costo promedio por CFDI procesado:** $0.80 MXN (weighted average con fallback a reglas)

### WhatsApp Business API

| Proveedor | Costo por mensaje | Notas |
|-----------|-------------------|-------|
| **360dialog** | $0.05 - $0.15/mensaje | Channel fee separado |
| **Twilio** | $0.08 - $0.20/mensaje | Más estable, más caro |

**Costo estimado:** ~$50/mes por cliente activo (notificaciones + cobranza)

### PAC (Proveedor Autorizado de Certificación) — Timbrado

| PAC | Costo por timbrado | Volumen descuento |
|-----|-------------------|-------------------|
| **Finkok** | $3.50 - $5.00/CFDI | 20%+ en volumen |
| **PACiFico** | $3.00 - $4.50/CFDI | Negociable |
| **Corefi** | $4.00 - $6.00/CFDI | Incluye cancelaciones |

**Costo promedio:** $4.00 MXN por CFDI timbrado

### Equipo

| Rol | Headcount Y1 | Costo/mes (MXN) |
|-----|-------------|-----------------|
| CTO / Tech Lead | 1 | $45,000 - $60,000 |
| Backend Engineer | 1 | $35,000 - $50,000 |
| Full-Stack Engineer | 1 | $30,000 - $45,000 |
| Product / Growth | 1 | $30,000 - $40,000 |
| Sales / CSM | 1 | $25,000 - $35,000 |
| Contador / Compliance | 0.5 | $15,000 - $20,000 |
| **Subtotal equipo Y1** | **5.5 FTE** | **$180,000 - $250,000** |

*Nota: Co-founders no cuentan como gasto de nómina (equity). El equipo incluye hires post-seed.*

---

## 3. Proyecciones a 3 Años

### Escenario Base (Conservador)

#### Year 1 — Product-Market Fit

| Métrica | Valor |
|---------|-------|
| **Clientes activos (fin de año)** | 15 |
| **Churn mensual** | 5% |
| **ARR promedio** | $12,000 |
| **MRR promedio** | $180,000 |
| **Revenue total** | **$1,500,000** |
| **CFDIs procesados (total)** | 50,000 |

| Costo | Mensual | Anual |
|-------|---------|-------|
| Infraestructura | $5,000 | $60,000 |
| AI APIs (50K CFDIs × $0.80) | — | $40,000 |
| WhatsApp API | $2,500 | $30,000 |
| PAC timbrado (50K × $4) | — | $200,000 |
| Equipo | $200,000 | $2,400,000 |
| Marketing / Sales | $30,000 | $360,000 |
| Legal / Contabilidad | $5,000 | $60,000 |
| Misceláneos | $10,000 | $120,000 |
| **Total costos** | | **$3,270,000** |
| **Net income** | | **($1,770,000)** |

**CAC Year 1:** $240,000 (altísimo — es normal en B2B early stage)
**Burn rate promedio:** ~$272,500/mes

#### Year 2 — Growth

| Métrica | Valor |
|---------|-------|
| **Clientes activos (fin de año)** | 45 |
| **Churn mensual** | 3.5% |
| **ARR promedio** | $16,000 |
| **MRR promedio** | $720,000 |
| **Revenue total** | **$7,500,000** |
| **CFDIs procesados (total)** | 300,000 |

| Costo | Mensual | Anual |
|-------|---------|-------|
| Infraestructura | $12,000 | $144,000 |
| AI APIs (300K × $0.60*) | — | $180,000 |
| WhatsApp API | $8,000 | $96,000 |
| PAC timbrado (300K × $3.50) | — | $1,050,000 |
| Equipo (8 FTE) | $320,000 | $3,840,000 |
| Marketing / Sales | $80,000 | $960,000 |
| Legal / Contabilidad | $8,000 | $96,000 |
| Misceláneos | $15,000 | $180,000 |
| **Total costos** | | **$6,546,000** |
| **Net income** | | **$954,000** |

*\*Costo AI baja con escala + fine-tuning + fallback a reglas*

**CAC Year 2:** $64,000 (mejora por brand + referrals)
**ARR growth:** 5x

#### Year 3 — Scale

| Métrica | Valor |
|---------|-------|
| **Clientes activos (fin de año)** | 120 |
| **Churn mensual** | 2.5% |
| **ARR promedio** | $20,000 |
| **MRR promedio** | $2,400,000 |
| **Revenue total** | **$24,000,000** |
| **CFDIs procesados (total)** | 1,200,000 |

| Costo | Mensual | Anual |
|-------|---------|-------|
| Infraestructura | $25,000 | $300,000 |
| AI APIs (1.2M × $0.40*) | — | $480,000 |
| WhatsApp API | $20,000 | $240,000 |
| PAC timbrado (1.2M × $3.00) | — | $3,600,000 |
| Equipo (15 FTE) | $550,000 | $6,600,000 |
| Marketing / Sales | $150,000 | $1,800,000 |
| Legal / Contabilidad | $12,000 | $144,000 |
| Misceláneos | $25,000 | $300,000 |
| **Total costos** | | **$13,464,000** |
| **Net income** | | **$10,536,000** |

*\*Costo AI se reduce significativamente con fine-tuning y reglas*

**CAC Year 3:** $40,000 (referrals + inbound dominante)
**ARR growth:** 3.3x

### Resumen de Proyecciones

| Métrica | Year 1 | Year 2 | Year 3 |
|---------|--------|--------|--------|
| Clientes activos | 15 | 45 | 120 |
| Revenue | $1.5M | $7.5M | $24M |
| Costos | $3.3M | $6.5M | $13.5M |
| Net income | ($1.8M) | $0.95M | $10.5M |
| Gross margin | 35% | 62% | 73% |
| CAC | $240K | $64K | $40K |
| LTV | $480K | $576K | $640K |
| LTV/CAC | 2.0x | 9.0x | 16.0x |

---

## 4. Unit Economics

### CAC (Customer Acquisition Cost)

| Componente | Year 1 | Year 2 | Year 3 |
|------------|--------|--------|--------|
| Marketing (ads, content) | $8,000 | $5,000 | $3,000 |
| Sales (comisión + tiempo) | $12,000 | $8,000 | $5,000 |
| Onboarding (setup, training) | $4,000 | $2,500 | $1,500 |
| **Total CAC** | **$24,000** | **$15,500** | **$9,500** |

*Nota: Los números anteriores incluyen overhead de equipo分配. El CAC directo es menor.*

### LTV (Lifetime Value)

| Métrica | Year 1 | Year 2 | Year 3 |
|---------|--------|--------|--------|
| ARPU mensual | $16,400 | $16,000 | $20,000 |
| Churn mensual | 5.0% | 3.5% | 2.5% |
| Lifespan (meses) | 20 | 29 | 40 |
| **LTV** | **$328,000** | **$464,000** | **$800,000** |

### Ratios Clave

| Ratio | Year 1 | Year 2 | Year 3 | Target |
|-------|--------|--------|--------|--------|
| **LTV/CAC** | 13.7x | 30.0x | 84.2x | >3x ✓ |
| **CAC Payback** | 1.5 meses | 1.0 meses | 0.5 meses | <12 meses ✓ |
| **Gross Margin** | 35% | 62% | 73% | >60% (Y2+) ✓ |
| **Net Margin** | -118% | 13% | 44% | >20% (Y3) ✓ |
| **Magic Number** | 0.3 | 0.8 | 1.2 | >0.75 (Y2+) ✓ |

### Costo Marginal por CFDI

| Componente | Costo/CFDI |
|------------|-----------|
| PAC timbrado | $4.00 |
| AI API | $0.80 |
| WhatsApp | $0.05 |
| Infraestructura (allocated) | $0.10 |
| **Total marginal** | **$4.95** |
| **Revenue promedio por CFDI** | **$5.47** ($16,400 / 3,000 CFDIs avg) |
| **Gross margin por CFDI** | **9.5%** |

*El margen por CFDI es bajo porque el PAC es un costo compartido con el SAT.
El valor real está en la automatización + compliance + ahorro de tiempo del contador.*

---

## 5. Funding Ask

### Monto: $3,000,000 MXN (~$150,000 USD)

### Uso de fondos

| Categoría | % | Monto (MXN) | Detalle |
|-----------|---|-------------|---------|
| **Producto / Engineering** | 40% | $1,200,000 | 6 meses de runway para equipo técnico (2 engineers + CTO) |
| **Sales / Marketing** | 30% | $900,000 | Ads, contenido, eventos contables, primer sales hire |
| **Operaciones** | 20% | $600,000 | Infraestructura, PAC, legal, contabilidad, oficina |
| **Reserva** | 10% | $300,000 | Buffer para oportunidades o imprevistos |

### Runway

| Métrica | Valor |
|---------|-------|
| **Runway mensual** | $272,500 (burn rate Y1) |
| **Runway total** | ~11 meses |
| **Break-even esperado** | Mes 14-16 (Q2 Year 2) |
| **Objetivo al acabar runway** | 25+ clientes activos, $400K+ MRR |

### Hitos esperados con el funding

| Hito | Timeline | Métrica |
|------|----------|---------|
| MVP → Beta | Mes 1-3 | 5 clientes beta, NPS >40 |
| Beta → GA | Mes 4-6 | 10 clientes pagando, $160K MRR |
| Growth | Mes 7-11 | 20 clientes, $320K MRR |
| Seed+ / Revenue | Mes 12-15 | 35+ clientes, $560K MRR, break-even |

---

## 6. Sensitivity Analysis

### Escenarios

| Escenario | Clientes Y1 | Revenue Y1 | Break-even |
|-----------|-------------|------------|------------|
| **Bear** (pessimista) | 8 | $800K | Mes 20+ |
| **Base** (conservador) | 15 | $1.5M | Mes 14-16 |
| **Bull** (optimista) | 25 | $2.5M | Mes 10-12 |

### Key Risks

| Riesgo | Impacto | Mitigación |
|--------|---------|-----------|
| **Adopción lenta** | Alto | Free tier limitado, pilot gratuito 30 días |
| **Churn alto** | Alto | Onboarding dedicado, QBR con clientes |
| **Costo PAC sube** | Medio | Negociar volumen, alternativas (Finkok vs PACiFico) |
| **Regulación SAT cambia** | Medio | Equipo de compliance, monitoreo constante |
| **Competencia** | Medio | Moat: integración deep con ERPs + WhatsApp |
| **AI costs suben** | Bajo | Fine-tuning, fallback a reglas, DeepSeek como alternativa |

---

## 7. Notas Metodológicas

- **Todos los costos son pre-impuestos** (no incluyen ISR, IVA operativo)
- **Equipo:** Los co-founders NO cuentan como gasto de nómina (compensados con equity)
- **PAC costs:** El timbrado es un costo variable directo — se escala linealmente con CFDIs
- **AI costs:** Se reducen con fine-tuning + reglas (fallback), no escala linealmente
- **Churn:** Se reduce con éxito del producto (de 5% a 2.5% en 3 años)
- **Revenue:** No incluye upsell ni expansión dentro de clientes existentes
- **Currency:** Todos los montos en MXN. Tipo de cambio referencial: 1 USD = 20 MXN

---

## 8. Benchmark — SaaS B2B México

| Métrica | Likida (proyección) | Benchmark SaaS B2B MX |
|---------|--------------------|-----------------------|
| ARPU mensual | $16,400 | $10,000 - $50,000 |
| CAC | $24,000 (Y1) | $15,000 - $50,000 |
| LTV/CAC | 13.7x (Y1) | 3x - 5x (healthy) |
| Payback | 1.5 meses | 6 - 18 meses |
| Gross margin | 35% → 73% | 60% - 80% (mature) |
| Net retention | 110%+ | 100% - 130% |

*Las métricas de Likida son agresivas pero alcanzables dado el ticket alto y la alta retención del sector contable/fiscal.*

---

*Documento generado como parte del paquete de fundraising Seed A.*
*Última actualización: Agosto 2026*
