# -*- coding: utf-8 -*-
"""b2b_ai.middleware — Capa de middleware de seguridad de la API.

Contiene:

- ``rate_limiter``  : rate limiter por token bucket, Redis-backed con
                      fallback en memoria, configurable por clase de endpoint
                      (auth / api / webhooks).
- ``request_validator`` : validación de peticiones: Content-Type, tamaño
                      máximo (10 MB), detección básica de SQL injection y XSS.
"""
