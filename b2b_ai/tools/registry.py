# -*- coding: utf-8 -*-
"""
registry.py — Sistema de registro de tools con decorator `@tool`.

Cada tool queda registrada con un nombre, descripción, parámetros (schema) y
la función ejecutable. El router y el orquestador usan el registro para
descubrir y llamar tools de forma dinámica (tool calling).

Ejemplo:
    @tool(name="parse_cfdi", description="Extrae datos de un CFDI XML",
          parameters=[{"name": "xml_path", "type": "string", "required": True}])
    def parse_cfdi_tool(xml_path):
        return {...}
"""
from __future__ import annotations

import inspect

_TOOLS = {}


class ToolDefinition:
    __slots__ = ("name", "fn", "description", "category", "parameters")

    def __init__(self, name, fn, description, category, parameters):
        self.name = name
        self.fn = fn
        self.description = description
        self.category = category
        self.parameters = parameters

    def __call__(self, **kwargs):
        return self.fn(**kwargs)

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": self.parameters,
        }


def tool(name=None, description="", category="general", parameters=None):
    """Decorator que registra una función como tool invocable por el agente."""
    def decorator(fn):
        tname = name or fn.__name__
        params = parameters or _infer_parameters(fn)
        if tname in _TOOLS:
            raise ValueError(f"Tool '{tname}' ya registrada.")
        _TOOLS[tname] = ToolDefinition(
            name=tname, fn=fn, description=description,
            category=category, parameters=params)
        return fn
    return decorator


def _infer_parameters(fn):
    """Deriva el schema de parámetros de la firma de la función."""
    params = []
    sig = inspect.signature(fn)
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls", "kwargs", "args"):
            continue
        ann = param.annotation
        if ann is inspect.Parameter.empty:
            ptype = "string"
        elif isinstance(ann, type) and ann is int:
            ptype = "integer"
        elif isinstance(ann, type) and ann is float:
            ptype = "number"
        elif isinstance(ann, type) and ann is bool:
            ptype = "boolean"
        else:
            ptype = "string"
        params.append({
            "name": pname,
            "type": ptype,
            "required": param.default is inspect.Parameter.empty,
        })
    return params


def get_tool(name):
    return _TOOLS.get(name)


def all_tools():
    return list(_TOOLS.values())


class ToolValidationError(ValueError):
    """Faltan parámetros requeridos por el schema de la tool.

    Subclase de ValueError a propósito: infrastructure/retry.py trata
    ValueError como no-retryable por defecto, así que un error de
    validación NUNCA dispara reintentos (reintentar una llamada con un
    parámetro faltante no la arregla).
    """

    def __init__(self, tool_name, missing):
        self.tool_name = tool_name
        self.missing = list(missing)
        super().__init__(
            f"Tool '{tool_name}' llamada sin parámetro(s) requerido(s): "
            f"{', '.join(self.missing)}."
        )


def _validate_required_params(tdef, kwargs):
    """Fail-closed: si falta un parámetro requerido del schema, rechaza la
    llamada en vez de invocar la tool y dejar que falle de forma más
    oscura (o, peor, que un default silencioso de la función enmascare el
    dato faltante). No adivina valores ni completa nada — sólo verifica
    presencia de la llave en `kwargs`.
    """
    missing = [
        p["name"] for p in (tdef.parameters or [])
        if p.get("required") and p["name"] not in kwargs
    ]
    if missing:
        raise ToolValidationError(tdef.name, missing)


def call_tool(name, **kwargs):
    """Llama una tool registrada.

    Lanza KeyError si la tool no existe, o ToolValidationError (fail-closed)
    si falta algún parámetro marcado `required=True` en su schema.
    """
    tdef = get_tool(name)
    if tdef is None:
        raise KeyError(f"Tool no registrada: {name}")
    _validate_required_params(tdef, kwargs)
    return tdef(**kwargs)
