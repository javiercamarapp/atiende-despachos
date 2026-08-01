# -*- coding: utf-8 -*-
"""Tests for b2b_ai/features/models.py — FeatureFlag dataclass."""
import pytest
from b2b_ai.features.models import FeatureFlag


class TestFeatureFlag:
    def test_defaults(self):
        ff = FeatureFlag()
        assert ff.id is None
        assert ff.name == ""
        assert ff.enabled is False
        assert ff.rollout_percentage == 100

    def test_to_dict(self):
        ff = FeatureFlag(id=1, name="test", enabled=True, rollout_percentage=50)
        d = ff.to_dict()
        assert d["id"] == 1
        assert d["name"] == "test"
        assert d["enabled"] is True
        assert d["rollout_percentage"] == 50

    def test_from_row(self):
        class FakeRow:
            def __init__(self, data):
                self._data = data
            def __getitem__(self, key):
                return self._data[key]
            def __contains__(self, key):
                return key in self._data
            def keys(self):
                return self._data.keys()
        row = FakeRow({
            "id": 1, "name": "test", "tenant_id": 10,
            "enabled": 1, "rollout_percentage": 75,
            "default_enabled": 0, "created_at": "2026-07-01",
        })
        ff = FeatureFlag.from_row(row)
        assert ff.id == 1
        assert ff.name == "test"
        assert ff.enabled is True
        assert ff.rollout_percentage == 75

    def test_from_row_minimal(self):
        class FakeRow:
            def __init__(self, data):
                self._data = data
            def __getitem__(self, key):
                return self._data[key]
            def __contains__(self, key):
                return key in self._data
            def keys(self):
                return self._data.keys()
        row = FakeRow({"id": 2, "name": "minimal", "tenant_id": None,
                        "enabled": 0, "rollout_percentage": 0})
        ff = FeatureFlag.from_row(row)
        assert ff.id == 2
        assert ff.enabled is False
        assert ff.default_enabled is False
