# -*- coding: utf-8 -*-
"""
models.py — Esquema de base de datos multi-tenant.

PostgreSQL-ready: usa tipos estándar (INTEGER, TEXT, NUMERIC, TIMESTAMP,
BOOLEAN) y claves foráneas explícitas. Para desarrollo se ejecuta sobre
SQLite (que soporta el mismo subset). Las migraciones versionan el esquema.

Tablas:
  - tenants           : despachos/clientes.
  - users             : usuarios dentro de un tenant.
  - invoices          : CFDI procesados (el registro central).
  - classifications   : clasificaciones por factura (historial/auditoría).
  - audit_log         : bitácora de TODAS las llamadas a tools.
  - notifications     : notificaciones enviadas/en cola.
  - schema_version    : versión del esquema (control de migraciones).

Aislamiento multi-tenant: TODA tabla de datos tiene `tenant_id` y las
consultas del servicio filtran SIEMPRE por tenant_id (ver db.py).
"""
from __future__ import annotations

MIGRATIONS = [
    {
        "version": 1,
        "name": "initial_schema",
        "sql": """
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            rfc TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            name TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'contador',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            folio_fiscal TEXT,
            archivo TEXT NOT NULL,
            fecha TEXT,
            tipo TEXT,
            serie TEXT,
            folio TEXT,
            emisor_rfc TEXT,
            emisor_nombre TEXT,
            receptor_rfc TEXT,
            subtotal TEXT,
            iva TEXT,
            total TEXT,
            moneda TEXT DEFAULT 'MXN',
            descripcion TEXT,
            categoria TEXT,
            confianza REAL,
            razon_clasificacion TEXT,
            valido INTEGER DEFAULT 0,
            requires_human_review INTEGER DEFAULT 1,
            issues TEXT,
            erp_poliza TEXT,
            erp_status TEXT,
            status TEXT DEFAULT 'procesado',
            procesado_en TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, folio_fiscal)
        );
        CREATE INDEX IF NOT EXISTS idx_invoices_tenant ON invoices(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_invoices_fecha ON invoices(fecha);

        CREATE TABLE IF NOT EXISTS classifications (
            id INTEGER PRIMARY KEY,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id),
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            categoria TEXT,
            confianza REAL,
            razon TEXT,
            method TEXT DEFAULT 'rules',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            tool_name TEXT NOT NULL,
            action TEXT,
            entity TEXT,
            entity_id TEXT,
            payload TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log(tool_name);
        CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            type TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT,
            subject TEXT,
            body TEXT,
            status TEXT DEFAULT 'queued',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
    },
    {
        "version": 2,
        "name": "api_keys_and_leads",
        "sql": """
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id),
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);

        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            despacho TEXT,
            email TEXT NOT NULL,
            facturas TEXT,
            mensaje TEXT,
            status TEXT DEFAULT 'nuevo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
    },
    {
        "version": 3,
        "name": "tenant_config_reviews_webhooks",
        "sql": """
        -- Configuración por cliente (multi-tenant FASE 4): RFC, ERP, plantilla
        -- contable, canal de notificación, webhooks. Formato clave/valor para
        -- flexibilidad (PostgreSQL-ready con TEXT).
        CREATE TABLE IF NOT EXISTS tenant_config (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            config_key TEXT NOT NULL,
            config_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, config_key)
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_config_tenant ON tenant_config(tenant_id);

        -- Cola de revisión humana (human-in-the-loop). Cada factura que el
        -- agente decide escalar queda aquí hasta que un humano resuelve.
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            invoice_id INTEGER REFERENCES invoices(id),
            reason TEXT,
            decision TEXT,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            resolved_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_reviews_tenant ON reviews(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);

        -- Bitácora de entregas de webhook (resultado → URL del cliente) con
        -- conteo de reintentos para la retry logic.
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            event TEXT,
            url TEXT,
            payload TEXT,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            last_status TEXT,
            last_error TEXT,
            next_retry_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_tenant ON webhook_deliveries(tenant_id);
        """,
    },
    {
        "version": 4,
        "name": "collections_agent",
        "sql": """
        -- Cobranza automatizada (FASE 3). Cada intento de contacto (recordatorio,
        -- escalamiento) se registra como evento para auditoría y para alimentar el
        -- score de cobrabilidad. `respuesta` guarda la reacción del deudor
        -- (p. ej. 'pagado', 'promesa_pago', 'sin_respuesta') cuando se reporta.
        CREATE TABLE IF NOT EXISTS collection_events (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            factura_id TEXT NOT NULL,
            tipo_recordatorio TEXT NOT NULL,
            canal TEXT NOT NULL DEFAULT 'email',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            respuesta TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_collection_events_factura
            ON collection_events(factura_id);
        CREATE INDEX IF NOT EXISTS idx_collection_events_tenant
            ON collection_events(tenant_id);

        -- Cartera de cuentas por cobrar pendientes. `dias_vencido` se recalcula
        -- en cada análisis; `score` es la probabilidad de cobro (0..1) calculada
        -- por el agente a partir de antigüedad e historial.
        CREATE TABLE IF NOT EXISTS outstanding_invoices (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            factura_id TEXT NOT NULL,
            monto REAL NOT NULL,
            fecha_vencimiento TEXT NOT NULL,
            dias_vencido INTEGER DEFAULT 0,
            score REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_outstanding_invoices_tenant
            ON outstanding_invoices(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_outstanding_invoices_due
            ON outstanding_invoices(fecha_vencimiento);
        """,
    },
    {
        "version": 5,
        "name": "enterprise_multitenant",
        "sql": """
        -- Bloqueo de tenants (tenant admin). Un tenant bloqueado no puede
        -- autenticarse: la dependency de auth lo rechaza con 403.
        ALTER TABLE tenants ADD COLUMN blocked INTEGER DEFAULT 0;

        -- Uso por tenant (usage tracking): contadores de llamadas API y
        -- facturas procesadas. Se incrementa en los endpoints /api/v2/*.
        CREATE TABLE IF NOT EXISTS tenant_usage (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            api_calls INTEGER DEFAULT 0,
            invoices_processed INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id)
        );
        CREATE INDEX IF NOT EXISTS idx_usage_tenant ON tenant_usage(tenant_id);

        -- Suscripciones de webhook por evento (API v2). Un tenant registra
        -- varias URLs, cada una para uno o más eventos.
        CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            event TEXT NOT NULL,
            url TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, event, url)
        );
        CREATE INDEX IF NOT EXISTS idx_wh_sub_tenant ON webhook_subscriptions(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_wh_sub_event ON webhook_subscriptions(event);
        """,
    },
    {
        "version": 6,
        "name": "contabilidad_electronica",
        "sql": """
        -- Contabilidad electrónica (FASE 3): catálogo de cuentas del SAT,
        -- asientos contables y balanzas mensuales. Todo aislado por tenant.
        CREATE TABLE IF NOT EXISTS cuentas_contables (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            codigo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            nivel INTEGER NOT NULL DEFAULT 3,
            naturaleza TEXT NOT NULL DEFAULT 'D',
            grupo TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, codigo)
        );
        CREATE INDEX IF NOT EXISTS idx_cuentas_tenant ON cuentas_contables(tenant_id);

        CREATE TABLE IF NOT EXISTS asientos_contables (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            fecha TEXT NOT NULL,
            cuenta_debito TEXT NOT NULL,
            cuenta_credito TEXT NOT NULL,
            monto TEXT NOT NULL,
            descripcion TEXT,
            factura_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_asientos_tenant ON asientos_contables(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_asientos_fecha ON asientos_contables(fecha);

        CREATE TABLE IF NOT EXISTS balanzas_mensuales (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            periodo TEXT NOT NULL,
            cuenta_id INTEGER REFERENCES cuentas_contables(id),
            saldo_inicial TEXT DEFAULT '0.00',
            debe TEXT DEFAULT '0.00',
            haber TEXT DEFAULT '0.00',
            saldo_final TEXT DEFAULT '0.00',
            UNIQUE (tenant_id, periodo, cuenta_id)
        );
        CREATE INDEX IF NOT EXISTS idx_balanzas_tenant ON balanzas_mensuales(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_balanzas_periodo ON balanzas_mensuales(periodo);

        -- Paquete de contabilidad electrónica generado (control de estados:
        -- borrador -> listo_para_timbrar -> timbrado -> enviado).
        CREATE TABLE IF NOT EXISTS paquetes_contabilidad (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            periodo TEXT NOT NULL,
            rfc TEXT,
            estado TEXT DEFAULT 'borrador',
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_paquetes_tenant ON paquetes_contabilidad(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_paquetes_periodo ON paquetes_contabilidad(periodo);
        """,
    },
    {
        "version": 7,
        "name": "client_portal",
        "sql": """
        -- Portal del cliente (FASE 5): usuarios que suben facturas CFDI desde
        -- el navegador. Multi-tenant: cada usuario pertenece a un tenant y solo
        -- ve las facturas de ese tenant. Un mismo email puede existir en varios
        -- tenants (por eso NO hay UNIQUE global en email; se desambigua con
        -- tenant_id en el login si hay colisión).
        CREATE TABLE IF NOT EXISTS client_users (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            role TEXT DEFAULT 'cliente',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, email)
        );
        CREATE INDEX IF NOT EXISTS idx_client_users_tenant
            ON client_users(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_client_users_email
            ON client_users(email);

        -- Sesiones del portal. `token` es opaco y se guarda hashado
        -- (sha256) para que un robo de la DB no exponga sesiones activas.
        -- `expires_at` controla la caducidad (por defecto 30 días).
        CREATE TABLE IF NOT EXISTS portal_sessions (
            id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES client_users(id),
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_portal_sessions_user
            ON portal_sessions(user_id);
        """,
    },
    {
        "version": 8,
        "name": "performance_indexes",
        "sql": """
        -- Índices compuestos para las consultas de lectura frecuentes (FASE perf).
        -- 1) list_invoices filtra por tenant_id + categoria (+ valido/fecha) y
        --    ordena por id DESC: el compuesto (tenant_id, categoria) cubre el
        --    caso más común sin hacer un scan completo del tenant.
        CREATE INDEX IF NOT EXISTS idx_invoices_tenant_categoria
            ON invoices(tenant_id, categoria);
        -- 2) invoice_stats agrupa por categoria dentro de un tenant: el mismo
        --    compuesto sirve para el GROUP BY.
        -- 3) Listado por rango de fechas dentro de un tenant (dashboard): el
        --    compuesto (tenant_id, fecha) evita scan por tenant.
        CREATE INDEX IF NOT EXISTS idx_invoices_tenant_fecha
            ON invoices(tenant_id, fecha);
        -- 4) El detalle por id de un tenant es el PK (id) + filtro por tenant;
        --    el índice único (tenant_id, folio_fiscal) ya cubre la búsqueda por
        --    folio dentro de tenant en insert_invoice (dedupe).
        """,
    },
    {
        "version": 9,
        "name": "outstanding_unique_upsert",
        "sql": """
        -- Índice único (tenant_id, factura_id) en la cartera: permite que el
        -- upsert de cobranza use `ON CONFLICT(tenant_id, factura_id)` de forma
        -- portable entre SQLite y PostgreSQL (requisito de la migración PG).
        CREATE UNIQUE INDEX IF NOT EXISTS idx_outstanding_unique
            ON outstanding_invoices(tenant_id, factura_id);
        """,
    },
    {
        "version": 10,
        "name": "billing",
        "sql": """
        -- Cobros (FASE billing): clientes, suscripciones, facturas y métodos
        -- de pago. Multi-tenant (tenant_id) y agnósticos del proveedor
        -- (stripe | conekta). `provider_*` guarda la referencia opaca que
        -- devuelve el proveedor (cus_..., sub_..., inv_...).
        CREATE TABLE IF NOT EXISTS billing_customers (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'stripe',
            provider_customer_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, email)
        );
        CREATE INDEX IF NOT EXISTS idx_billing_customers_tenant
            ON billing_customers(tenant_id);

        CREATE TABLE IF NOT EXISTS billing_subscriptions (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
            plan TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'stripe',
            provider_subscription_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            current_period_start TEXT,
            current_period_end TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_billing_subs_tenant
            ON billing_subscriptions(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_billing_subs_customer
            ON billing_subscriptions(customer_id);

        CREATE TABLE IF NOT EXISTS billing_invoices (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'MXN',
            status TEXT NOT NULL DEFAULT 'open',
            provider TEXT NOT NULL DEFAULT 'stripe',
            provider_invoice_id TEXT,
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_billing_invoices_tenant
            ON billing_invoices(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_billing_invoices_customer
            ON billing_invoices(customer_id);

        CREATE TABLE IF NOT EXISTS billing_payment_methods (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
            type TEXT NOT NULL DEFAULT 'card',
            provider TEXT NOT NULL DEFAULT 'stripe',
            provider_payment_method_id TEXT,
            last4 TEXT,
            exp_month INTEGER,
            exp_year INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_billing_pm_tenant
            ON billing_payment_methods(tenant_id);
        """,
    },
    {
        "version": 11,
        "name": "audit_trail_and_feature_flags",
        "sql": """
        -- Audit trail enterprise: bitácora de acciones con contexto de
        -- usuario y request. Tabla SEPARADA de audit_log (que audita tools
        -- internas) porque el contrato es distinto: user_id, resource,
        -- resource_id, details (JSON), ip. Aislada por tenant_id.
        CREATE TABLE IF NOT EXISTS audit_entries (
            id INTEGER PRIMARY KEY,
            user_id TEXT,
            tenant_id INTEGER,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            resource_id TEXT,
            details TEXT,
            ip TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_audit_entries_tenant
            ON audit_entries(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_audit_entries_tenant_ts
            ON audit_entries(tenant_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_entries_resource
            ON audit_entries(resource);

        -- Feature flags por tenant. `tenant_id` NULL = flag GLOBAL (aplica a
        -- todos los tenants sin override propio). `rollout_percentage` (0-100)
        -- permite un rollout gradual cuando `enabled` está activo. Los
        -- defaults para tenants nuevos viven en b2b_ai.features.flags.
        CREATE TABLE IF NOT EXISTS feature_flags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            tenant_id INTEGER,
            enabled INTEGER DEFAULT 0,
            rollout_percentage INTEGER DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_feature_flags_tenant
            ON feature_flags(tenant_id);
        """,
    },
    {
        "version": 12,
        "name": "outreach_email_campaigns",
        "sql": """
        -- Outreach de adquisición (outbound emails): campañas, leads por
        -- campaña (snapshot + estado en la secuencia), correos enviados y
        -- eventos de tracking (open/click). Multi-tenant: toda lectura filtra
        -- por tenant_id.
        CREATE TABLE IF NOT EXISTS outreach_campaigns (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            sequence_id INTEGER NOT NULL DEFAULT 1,
            status TEXT DEFAULT 'active',
            sender_email TEXT,
            reply_to TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            launched_at TIMESTAMP,
            paused_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_outreach_campaigns_tenant
            ON outreach_campaigns(tenant_id);

        -- Un lead dentro de una campaña. `stage` = paso de la secuencia
        -- (1..5), `status` = estado de contacto, `next_send_at` = cuándo toca
        -- el siguiente envío (para followups espaciados en el tiempo).
        CREATE TABLE IF NOT EXISTS outreach_campaign_leads (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL REFERENCES outreach_campaigns(id),
            tenant_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            company TEXT,
            role TEXT,
            industry TEXT,
            stage INTEGER DEFAULT 1,
            status TEXT DEFAULT 'queued',
            next_send_at TIMESTAMP,
            emails_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_outreach_leads_campaign
            ON outreach_campaign_leads(campaign_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_leads_tenant
            ON outreach_campaign_leads(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_leads_campaign_status
            ON outreach_campaign_leads(campaign_id, status);

        CREATE TABLE IF NOT EXISTS outreach_emails (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER,
            lead_id INTEGER REFERENCES outreach_campaign_leads(id),
            tenant_id INTEGER NOT NULL,
            template TEXT,
            subject TEXT,
            body TEXT,
            status TEXT DEFAULT 'sent',
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            opened_at TIMESTAMP,
            first_clicked_at TIMESTAMP,
            opened_count INTEGER DEFAULT 0,
            click_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_outreach_emails_lead
            ON outreach_emails(lead_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_emails_campaign
            ON outreach_emails(campaign_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_emails_tenant
            ON outreach_emails(tenant_id);

        -- Eventos de tracking (píxel de open / redirect de click).
        CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            email_id INTEGER REFERENCES outreach_emails(id),
            lead_id INTEGER,
            event_type TEXT NOT NULL,
            link_id TEXT,
            occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_outreach_events_tenant
            ON outreach_events(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_events_email
            ON outreach_events(email_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_events_lead
            ON outreach_events(lead_id);
        """,
    },
    {
        "version": 13,
        "name": "bank_reconciliation_state",
        "sql": """
        -- Estado de conciliación bancaria, persistido por tenant.
        --
        -- Antes vivía en un diccionario a nivel de módulo (_SESSIONS en
        -- api/reconciliation.py). Eso lo hacía inservible con más de un worker
        -- —la subida caía en un proceso y el reporte se pedía a otro—, crecía
        -- en RAM sin techo y se perdía en cada reinicio.
        --
        -- Solo se persiste lo que NO es derivable: los movimientos subidos y
        -- las confirmaciones manuales. Las facturas ya salen de `invoices` y
        -- los cruces se recalculan en cada petición.
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            tx_id TEXT NOT NULL,
            banco TEXT,
            filename TEXT,
            data TEXT NOT NULL,          -- movimiento normalizado (JSON)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        -- Un mismo movimiento no se duplica al resubir el estado de cuenta.
        -- COALESCE porque en SQLite dos NULL no colisionan en un UNIQUE, y el
        -- tenant nulo (key de servicio) es un caso real.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_tx_unico
            ON bank_transactions(COALESCE(tenant_id, -1), tx_id);
        CREATE INDEX IF NOT EXISTS idx_bank_tx_tenant
            ON bank_transactions(tenant_id);

        CREATE TABLE IF NOT EXISTS bank_confirmations (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            tx_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_conf_unico
            ON bank_confirmations(COALESCE(tenant_id, -1), tx_id);
        CREATE INDEX IF NOT EXISTS idx_bank_conf_tenant
            ON bank_confirmations(tenant_id);
        """,
    },
    {
        "version": 14,
        "name": "collections_module",
        "sql": """
        -- Log de pagos recibidos vía webhook (módulo de cobranza).
        -- Cada confirmación de pago se registra aquí para trazabilidad.
        CREATE TABLE IF NOT EXISTS collection_payments (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            factura_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            amount REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'MXN',
            reference TEXT,
            provider TEXT DEFAULT 'manual',
            paid_at TIMESTAMP,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_coll_pay_tenant
            ON collection_payments(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_coll_pay_factura
            ON collection_payments(factura_id);
        CREATE INDEX IF NOT EXISTS idx_coll_pay_tenant_factura
            ON collection_payments(tenant_id, factura_id);

        -- Configuración de cobranza por tenant (días de gracia, canales,
        -- umbrales de escalamiento, etc.). Formato clave/valor.
        CREATE TABLE IF NOT EXISTS collection_config (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            config_key TEXT NOT NULL,
            config_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, config_key)
        );
        CREATE INDEX IF NOT EXISTS idx_coll_config_tenant
            ON collection_config(tenant_id);
        """,
    },
    {
        "version": 15,
        "name": "privacy_consent",
        "sql": """
        -- LFPDPPP Art. 8: Consentimiento de privacidad. Registra cuándo el
        -- titular aceptó el aviso de privacidad. Columna nullable para
        -- migrar usuarios existentes sin romper reads.
        ALTER TABLE client_users ADD COLUMN accepted_privacy_at TIMESTAMP;
        """,
    },
    {
        "version": 16,
        "name": "reconciliation_jobs",
        "sql": """
        CREATE TABLE IF NOT EXISTS reconciliation_jobs (
            id INTEGER PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE,
            tenant_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            progress REAL DEFAULT 0.0,
            result_json TEXT,
            bank TEXT DEFAULT 'generic',
            format TEXT DEFAULT 'csv',
            filename TEXT DEFAULT '',
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_recon_jobs_tenant ON reconciliation_jobs(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_recon_jobs_status ON reconciliation_jobs(status);
        """,
    },
    {
        "version": 17,
        "name": "job_queue",
        "sql": """
        CREATE TABLE IF NOT EXISTS job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            job_type TEXT NOT NULL DEFAULT 'process_cfdi',
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );
        CREATE INDEX IF NOT EXISTS idx_job_queue_tenant ON job_queue(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue(status);
        CREATE INDEX IF NOT EXISTS idx_job_queue_pending ON job_queue(status, priority DESC, id ASC);
        """,
    },
    {
        "version": 18,
        "name": "conciliation_sessions",
        "sql": """
        CREATE TABLE IF NOT EXISTS conciliation_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            user_id TEXT,
            criteria TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'proposed',
            total_matches INTEGER NOT NULL DEFAULT 0,
            total_unmatched INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            confirmed_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        );
        """,
    },
    {
        "version": 19,
        "name": "conciliation_matches",
        "sql": """
        CREATE TABLE IF NOT EXISTS conciliation_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            bank_transaction_id TEXT NOT NULL,
            poliza_id TEXT,
            cfdi_folio TEXT,
            amount REAL NOT NULL,
            match_score REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'proposed',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            reverted_at TEXT,
            FOREIGN KEY (session_id) REFERENCES conciliation_sessions(id)
        );
        """,
    },
]


def current_version():
    return max(m["version"] for m in MIGRATIONS)


# --------------------------------------------------------------------------
# PostgreSQL (producción)
# --------------------------------------------------------------------------
# El esquema de producción NO se deriva de MIGRATIONS (que es SQLite-flavored:
# INTEGER PRIMARY KEY autoi, TIMESTAMP sin tz). En PostgreSQL la fuente de
# verdad es Alembic (migrations/) y usa tipos nativos de PG:
#
#   * PKs: BIGINT GENERATED ALWAYS AS IDENTITY (equivalente al INTEGER
#     PRIMARY KEY AUTOINCREMENT de SQLite; el código de db.py sigue usando
#     ids enteros y lastrowid, así que NO se cambia a UUID para no romper la
#     capa de datos).
#   * Timestamps: TIMESTAMP WITH TIME ZONE (timestamptz) en created_at /
#     updated_at / resolved_at / expires_at / next_retry_at / completed_at.
#   * JSONB en columnas que guardan documentos: audit_log.payload,
#     webhook_deliveries.payload, paquetes_contabilidad.payload.
#   * Índices compuestos para las lecturas de dashboard (ver 0002_indexes).
#
# Nota: db.py y los servicios siguen tratando los valores monetarios y de
# fecha como TEXT (igual que en SQLite) para no alterar el contrato de la API;
# migrar esos campos a NUMERIC/TIMESTAMP es un cambio de contrato separado.
#
# Las tablas y columnas son idénticas entre SQLite y PG; lo que cambia es el
# DDL (Alembic vs MIGRATIONS). Esto permite que el MISMO código db.py corra
# contra ambos backends seleccionando el DSN (B2B_DB_URL / B2B_DB_PATH).

