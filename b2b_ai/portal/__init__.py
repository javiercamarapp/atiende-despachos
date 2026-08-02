# -*- coding: utf-8 -*-
"""Portal del cliente (server-rendered).

Portal web para que los clientes del despacho contable consulten sus
facturas y reportes desde el navegador, sin API key. Páginas HTML servidas
con Jinja2 desde `b2b_ai/portal/templates/`, autenticación por sesión
(cookie HttpOnly) ligada a `client_users` (multi-tenant: cada usuario solo
ve su tenant).

Este paquete convive con `b2b_ai/api/portal.py` (la API JSON del SPA):
ambos se montan bajo `/portal`. Las rutas JSON de subida/auth quedan en
`api/portal.py`; las páginas HTML viven aquí.
"""
from b2b_ai.portal.routes import build_portal_pages_router

__all__ = ["build_portal_pages_router"]
