"""End-to-end-ish test of the integration inside a real Home Assistant.

Skipped unless `homeassistant` + `pytest-homeassistant-custom-component` are
installed (they are heavy, so light CI skips this and relies on the unit tests;
run `pip install -e .[ha]` or on a dev/HA box to exercise it).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from conftest import COMMUNITY  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402

from custom_components.ga_frontend_bundle.const import STATIC_URL_BASE  # noqa: E402

CARD_COUNT = len(json.loads((COMMUNITY / "cards.json").read_text())["cards"])


async def test_setup_injects_all_cards(hass, enable_custom_integrations):
    assert await async_setup_component(hass, "ga_frontend_bundle", {"ga_frontend_bundle": {}})
    await hass.async_block_till_done()

    data = hass.data["ga_frontend_bundle"]
    assert data["injected"] == CARD_COUNT
    assert len(data["cards"]) == CARD_COUNT

    # Every card got registered as a frontend extra-module URL.
    extra = hass.data.get("frontend_extra_module_url", set())
    for card in data["cards"]:
        url = f"{STATIC_URL_BASE}/{card['id']}/{card['file']}"
        assert url in extra, f"{card['id']} not injected as frontend module"


async def test_setup_idempotent(hass, enable_custom_integrations):
    assert await async_setup_component(hass, "ga_frontend_bundle", {"ga_frontend_bundle": {}})
    await hass.async_block_till_done()
    # Re-running setup must be a no-op (DOMAIN already in hass.data), not raise.
    from custom_components.ga_frontend_bundle import async_setup

    assert await async_setup(hass, {})
