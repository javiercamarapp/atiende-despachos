# -*- coding: utf-8 -*-
"""
__init__.py — Módulo de Integraciones del B2B AI Platform.

Integraciones para SAT, ERPs, Bancos, Nómina, Google, Microsoft,
Gobierno, Social, Calendario, Compliance y más.

Lazy imports to avoid cascading failures when one adapter has missing deps.
"""

__all__ = [
    "hub", "sat", "erp", "bancos", "nomina", "pagos",
    "comunicacion", "crm", "storage", "microsoft", "social",
    "firmas", "calendario", "monitoreo",
]


def __getattr__(name: str):
    """Lazy module imports — prevents cascading import failures."""
    _lazy = {
        "hub": "b2b_ai.integrations.hub",
        "sat": "b2b_ai.integrations.sat",
        "erp": "b2b_ai.integrations.erp",
        "bancos": "b2b_ai.integrations.bancos",
        "nomina": "b2b_ai.integrations.nomina",
        "pagos": "b2b_ai.integrations.pagos",
        "comunicacion": "b2b_ai.integrations.comunicacion",
        "crm": "b2b_ai.integrations.crm",
        "storage": "b2b_ai.integrations.storage",
        "microsoft": "b2b_ai.integrations.microsoft",
        "social": "b2b_ai.integrations.social",
        "firmas": "b2b_ai.integrations.firmas",
        "calendario": "b2b_ai.integrations.calendario",
        "monitoreo": "b2b_ai.integrations.monitoreo",
    }
    if name in _lazy:
        import importlib
        try:
            mod = importlib.import_module(_lazy[name])
            globals()[name] = mod
            return mod
        except ImportError:
            # Adapter has missing deps — return a stub module
            import types
            stub = types.ModuleType(f"b2b_ai.integrations.{name}")
            stub.__dict__["_import_error"] = True
            globals()[name] = stub
            return stub
    raise AttributeError(f"module 'b2b_ai.integrations' has no attribute {name!r}")
