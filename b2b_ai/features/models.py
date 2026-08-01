# -*- coding: utf-8 -*-
"""models.py — Modelo de feature flags.

`FeatureFlag` es un dataclass que refleja una fila de `feature_flags`:

  - id                  : PK.
  - name                : nombre de la feature (clave lógica).
  - tenant_id           : tenant (NULL = override global).
  - enabled             : activa o no.
  - rollout_percentage  : porcentaje de rollout gradual (0-100).
  - default_enabled     : valor por defecto del código.
  - created_at          : cuándo se creó.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FeatureFlag:
    """Una entrada de feature flags (equivalente a una fila de feature_flags)."""

    id: Optional[int] = None
    name: str = ""
    tenant_id: Optional[int] = None
    enabled: bool = False
    rollout_percentage: int = 100
    default_enabled: bool = False
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialización a dict."""
        return {
            "id": self.id,
            "name": self.name,
            "tenant_id": self.tenant_id,
            "enabled": self.enabled,
            "rollout_percentage": self.rollout_percentage,
            "default_enabled": self.default_enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> "FeatureFlag":
        """Construye un flag a partir de una fila (dict-like) de la DB."""
        return cls(
            id=row["id"] if "id" in row.keys() else None,
            name=row["name"],
            tenant_id=row["tenant_id"],
            enabled=bool(row["enabled"]),
            rollout_percentage=int(row["rollout_percentage"] or 0),
            default_enabled=bool(row["default_enabled"]) if "default_enabled" in row.keys() else False,
            created_at=row["created_at"] if "created_at" in row.keys() else None,
        )
