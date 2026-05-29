"""Checks on the integration manifest.json."""

from __future__ import annotations

import json

from conftest import MANIFEST


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_domain():
    assert _manifest()["domain"] == "ga_frontend_bundle"


def test_no_config_flow():
    # Stateless integration: must NOT be a config_flow integration. Converge
    # activates it via the configuration.yaml enable-list instead.
    m = _manifest()
    assert m.get("config_flow", False) is False


def test_dependencies_include_http_and_frontend():
    deps = _manifest().get("dependencies", [])
    assert "http" in deps and "frontend" in deps


def test_version_matches_bundle_version(lock):
    assert _manifest()["version"] == lock["bundle_version"]


def test_codeowner():
    assert _manifest().get("codeowners") == ["@greenautarky"]
