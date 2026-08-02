# -*- coding: utf-8 -*-
"""
tenants.py — Gestión multi-tenant (FASE 4).

Cada cliente (despacho) es un `tenant` con su propia configuración: RFC,
ERP destino, plantilla contable y canal de notificación. Toda la data de
facturas se aísla por `tenant_id` (las lecturas del servicio SIEMPRE filtran
por tenant — ver db.py).

Este módulo añade la capa de negocio por encima de la DB:

    - onboard_tenant()   : flujo de onboarding de un nuevo cliente.
    - get_config()/set   : configuración por cliente con defaults.
    - erp_factory()      : ERP concreto según la config del tenant
                           (CONTPAQi mock, CSV...), con inyección posible.
    - scoped_*()         : helpers de aislamiento (una factura / listado).

Convención: TODA llamada de servicio que toque datos de un tenant recibe un
`tenant_id` y usa los helpers scoped_* (o filtra por tenant_id en db.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import logging
import os

from b2b_ai.db.db import Database
from b2b_ai.erp.base import ERPInterface
from b2b_ai.erp.contpaqi import MockCONTPAQi
from b2b_ai.erp.csv_erp import CSVErp

logger = logging.getLogger(__name__)

# Defaults de configuración por tenant. Los valores almacenados en la tabla
# tenant_config sobreescriben estos.
CONFIG_DEFAULTS: Dict[str, str] = {
    "erp_type": "contpaqi",       # 'contpaqi' | 'csv' | 'aspel'
    "plantilla_contable": "SAT",  # plantilla de póliza contable
    "notif_channel": "email",     # canal de notificación del agente
    "notif_recipient": os.environ.get("B2B_DEFAULT_EMAIL", ""),
    "webhook_url": "",            # URL a la que se notifican los resultados
    "policy_human_review": "hold",  # 'hold' | 'auto_register'
}


class TenantNotFoundError(Exception):
    """Se lanza al operar sobre un tenant que no existe (o no autorizado)."""


def _ensure_db(db: Optional[Database] = None) -> Database:
    return db or Database()


def _default_config() -> Dict[str, str]:
    return dict(CONFIG_DEFAULTS)


class TenantManager:
    """Operaciones de ciclo de vida y configuración de tenants."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = _ensure_db(db)

    # ---- Onboarding -------------------------------------------------------
    def onboard_tenant(self, name: str, rfc: str = "", erp_type: str = "contpaqi",
                       plantilla_contable: str = "SAT", notif_channel: str = "email",
                       notif_recipient: str = "", webhook_url: str = "",
                       user_name: Optional[str] = None,
                       user_email: str = "", user_role: str = "admin",
                       policy_human_review: str = "hold") -> Dict[str, Any]:
        """
        Flujo de onboarding de un cliente:

            1. Crea el tenant (RFC).
            2. Persiste su configuración (ERP, plantilla, notificación).
            3. Crea un usuario admin por defecto.
            4. Crea una API key para el tenant.

        Devuelve dict con {id, name, rfc, config, user_id, api_key}.
        """
        tenant_id = self.db.create_tenant(name, rfc)
        # Feature flags: materializa los defaults del tenant nuevo (portal,
        # cobranza, contabilidad electrónica, billing, etc.) para que cada
        # tenant tenga su propio registro editable/auditable.
        from b2b_ai.features.flags import FeatureFlags
        FeatureFlags(self.db).seed_defaults(tenant_id)
        cfg = {
            "erp_type": erp_type,
            "plantilla_contable": plantilla_contable,
            "notif_channel": notif_channel,
            "notif_recipient": (notif_recipient
                                or CONFIG_DEFAULTS["notif_recipient"]),
            "policy_human_review": policy_human_review,
        }
        if webhook_url:
            cfg["webhook_url"] = webhook_url
        for k, v in cfg.items():
            self.db.set_tenant_config(tenant_id, k, v)

        # SECURITY FIX [1]: ALWAYS create an admin user so that
        # has_tenant_users() returns True and the bootstrap door in
        # POST /api/v1/auth/register closes immediately.
        if not user_name:
            user_name = "admin"
        if not user_email:
            user_email = f"admin@tenant-{tenant_id}.local"
        user_id = self.db.create_user(
            tenant_id, user_name, user_email, user_role or "admin")

        api_key = self._issue_api_key(tenant_id)

        return {
            "id": tenant_id,
            "name": name,
            "rfc": rfc,
            "config": self.get_config(tenant_id),
            "user_id": user_id,
            "api_key": api_key,
        }

    def _issue_api_key(self, tenant_id: int, name: str = "onboarding") -> str:
        import secrets
        key = secrets.token_hex(20)
        self.db.create_api_key(tenant_id, name, key)
        return key

    # ---- Lectura / validación (aislamiento) ------------------------------
    def get_tenant(self, tenant_id: int) -> Dict[str, Any]:
        """Devuelve el tenant o lanza TenantNotFoundError (validación de scope)."""
        row = self._find_tenant(tenant_id)
        if row is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} no existe.")
        return row

    def _find_tenant(self, tenant_id: int) -> Optional[Dict[str, Any]]:
        for t in self.db.list_tenants():
            if t["id"] == tenant_id:
                return t
        return None

    def exists(self, tenant_id: int) -> bool:
        return self._find_tenant(tenant_id) is not None

    def get_config(self, tenant_id: int) -> Dict[str, Any]:
        """Config del tenant mezclada con defaults."""
        self.get_tenant(tenant_id)  # valida existencia
        stored = self.db.get_all_tenant_config(tenant_id)
        cfg = _default_config()
        cfg.update(stored)
        return cfg

    def set_config(self, tenant_id: int, **kwargs: Any) -> Dict[str, Any]:
        self.get_tenant(tenant_id)
        for k, v in kwargs.items():
            self.db.set_tenant_config(tenant_id, k, v)
        return self.get_config(tenant_id)

    # ---- ERP por tenant ---------------------------------------------------
    def erp_factory(self, tenant_id: int,
                    erp: Optional[ERPInterface] = None) -> ERPInterface:
        """
        Devuelve un ERPInterface según la config del tenant. Si se pasa `erp`
        explícito, se usa ese (inyección para tests/override). Sino, intenta
        crear un ComputerUseDriver real (playwright/mock) vía la factory; si
        no está configurado o falla, cae en MockCONTPAQi con WARNING.
        """
        if erp is not None:
            return erp
        cfg = self.get_config(tenant_id)
        erp_type = (cfg.get("erp_type") or "contpaqi").lower()
        if erp_type == "csv":
            return CSVErp()

        # Try Computer Use real driver
        try:
            from b2b_ai.computer_use.factory import ComputerUseDriverFactory
            from b2b_ai.computer_use.config import ComputerUseConfig
            cu_config = ComputerUseConfig.from_env()
            if cu_config.mode != "disabled":
                driver = ComputerUseDriverFactory.create(
                    provider=erp_type,
                    mode=cu_config.mode,
                    tenant_id=tenant_id,
                    config=cu_config,
                )
                return _ComputerUseERPAdapter(driver, credentials={
                    "usuario": os.environ.get(
                        "CONTPAQI_USERNAME"
                        if erp_type == "contpaqi" else "ASPEL_USERNAME", ""),
                    "password": os.environ.get(
                        "CONTPAQI_PASSWORD"
                        if erp_type == "contpaqi" else "ASPEL_PASSWORD", ""),
                })
        except Exception as e:
            # FAIL-HARD in production: do NOT silently fall back to mock
            if os.environ.get("B2B_ENV") == "production":
                logger.error(
                    "erp_factory: Computer Use FAILED in production — "
                    "refusing silent fallback to mock. Error: %s", e)
                raise
            logger.warning(
                "erp_factory: Computer Use unavailable in dev, "
                "falling back to mock: %s", e)

        return MockCONTPAQi()

    # ---- Aislamiento de datos --------------------------------------------
    def scoped_invoice(self, tenant_id: int, invoice_id: int) -> Optional[Dict[str, Any]]:
        """Una factura de un tenant, o None si no es de ese tenant."""
        self.get_tenant(tenant_id)
        return self.db.get_invoice(invoice_id, tenant_id=tenant_id)

    def scoped_invoices(self, tenant_id: int, **filters: Any) -> List[Dict[str, Any]]:
        self.get_tenant(tenant_id)
        return self.db.list_invoices(tenant_id=tenant_id, **filters)

    def scoped_stats(self, tenant_id: int) -> Dict[str, Any]:
        self.get_tenant(tenant_id)
        return self.db.invoice_stats(tenant_id=tenant_id)

    def tenant_health(self, tenant_id: int) -> Dict[str, Any]:
        """Health del ERP del tenant (para el dashboard)."""
        self.get_tenant(tenant_id)
        return self.erp_factory(tenant_id).health()


def onboard_tenant(db: Optional[Database] = None, **kwargs: Any) -> Dict[str, Any]:
    """Atajo funcional: crear cliente + config + usuario + API key."""
    return TenantManager(db).onboard_tenant(**kwargs)


def get_config(db: Database, tenant_id: int) -> Dict[str, Any]:
    return TenantManager(db).get_config(tenant_id)


def set_config(db: Database, tenant_id: int, **kwargs: Any) -> Dict[str, Any]:
    return TenantManager(db).set_config(tenant_id, **kwargs)


def erp_factory(db: Database, tenant_id: int,
                erp: Optional[ERPInterface] = None) -> ERPInterface:
    return TenantManager(db).erp_factory(tenant_id, erp=erp)


class _ComputerUseERPAdapter(ERPInterface):
    """Adapts the async ComputerUseDriver to the sync ERPInterface contract.

    Lifecycle: on first use it ensures connect() → login(credentials) →
    verify session, then registers. Runs async driver methods through the
    driver's shared event loop (async → sync bridge).
    """

    def __init__(self, driver, credentials: Optional[dict] = None) -> None:
        self._driver = driver
        self._credentials = credentials or {}
        self._session_ready = False

    def _run_async(self, coro):
        """Bridge async driver method to sync via the driver's loop."""
        run_sync = getattr(self._driver, "_run_sync", None)
        if run_sync is not None:
            return run_sync(coro)
        # Fallback: run in a fresh event loop
        import asyncio
        try:
            asyncio.get_running_loop()
            return asyncio.new_event_loop().run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def _ensure_session(self) -> None:
        """Ensure the driver is connected and authenticated before any op."""
        if self._session_ready:
            return

        # connect()
        conn = self._run_async(self._driver.connect())
        if not (isinstance(conn, dict) and conn.get("ok", False)):
            raise RuntimeError(
                "Computer Use: connect() failed — "
                f"{conn.get('message') if isinstance(conn, dict) else conn}")

        # login()
        if not self._credentials:
            raise RuntimeError(
                "Computer Use: no credentials provided for login(). "
                "Configure CONTPAQI_USERNAME/CONTPAQI_PASSWORD "
                "or ASPEL_USERNAME/ASPEL_PASSWORD.")
        login = self._run_async(self._driver.login(self._credentials))
        if not (isinstance(login, dict) and login.get("ok", False)):
            raise RuntimeError(
                "Computer Use: login() failed — "
                f"{login.get('message') if isinstance(login, dict) else login}")

        self._session_ready = True

    def register_invoice(self, invoice: dict) -> dict:
        # Ensure authenticated session before registering (never silent)
        self._ensure_session()
        result = self._run_async(self._driver.register_invoice(invoice))
        return result.to_dict() if hasattr(result, "to_dict") else result

    def get_invoice(self, folio_fiscal: str) -> dict | None:
        self._ensure_session()
        result = self._run_async(
            self._driver.verify_invoice_registered(folio_fiscal))
        return result.to_dict() if hasattr(result, "to_dict") else result

    def health(self) -> dict:
        result = self._driver.health()
        return result.to_dict() if hasattr(result, "to_dict") else result
