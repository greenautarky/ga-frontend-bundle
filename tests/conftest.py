"""Shared test fixtures / paths for ga-frontend-bundle."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "custom_components" / "ga_frontend_bundle"
COMMUNITY = PKG / "community"
LOCK = REPO / "bundle.lock.yaml"
MANIFEST = PKG / "manifest.json"


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture(scope="session")
def lock() -> dict:
    return yaml.safe_load(LOCK.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def bundle_module() -> ModuleType:
    """Load bundle.py standalone (it's stdlib-only) without importing the
    package __init__ (which would pull in homeassistant)."""
    spec = importlib.util.spec_from_file_location("ga_fb_bundle", PKG / "bundle.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
