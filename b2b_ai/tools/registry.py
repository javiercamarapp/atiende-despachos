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


def call_tool(name, **kwargs):
    """Llama una tool registrada. Lanza KeyError si no existe."""
    tdef = get_tool(name)
    if tdef is None:
        raise KeyError(f"Tool no registrada: {name}")
    return tdef(**kwargs)
