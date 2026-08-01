#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
b2b_ai — Agente IA enterprise para despachos contables (B&B AI).

Expansión enterprise del MVP: tool calling, integraciones (ERP CONTPAQi
simulada, facturación CFDI, notificaciones), base multi-tenant, API dashboard
y CLI.

Diseño rector (de `04-leyes-fiscales.md`): la máquina prepara y valida; el
profesional determina y firma. Cada salida con efecto fiscal lleva referencia
legal + supuesto + flag `requires_human_review`.
"""
from b2b_ai import cfdi, tools, erp, db, notifications, services, api, computer_use, monitoring

__version__ = "1.0.0"

__all__ = ["cfdi", "tools", "erp", "db", "notifications", "services", "api",
           "computer_use", "monitoring", "__version__"]
