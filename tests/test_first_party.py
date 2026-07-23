"""Tests for the first-party GA cards (ga-master-card, ADR-0006).

First-party cards live in custom_components/ga_frontend_bundle/first_party/ —
separate from the vendored community/ tree so the bundle lock/integrity checks
never touch them, but loaded/served/injected by the same mechanism.
"""

from __future__ import annotations

import json

import pytest
from conftest import PKG

# test_first_party_injected needs the Home Assistant test harness (the ``hass`` +
# ``enable_custom_integrations`` fixtures). CI installs only pytest/PyYAML/ruff,
# and fixtures resolve BEFORE the function body — so an in-body importorskip is
# too late (errors as "fixture 'hass' not found"). Skip that ONE test when the
# harness is absent; the pure-asset tests still run.
try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HAS_HA_TEST_HARNESS = True
except ImportError:
    _HAS_HA_TEST_HARNESS = False

FIRST_PARTY = PKG / "first_party"
MASTER_CARD = FIRST_PARTY / "ga-master-card" / "ga-master-card.js"


# ─── the card asset itself ────────────────────────────────────────────────


def test_master_card_file_present():
    assert MASTER_CARD.is_file()


def test_master_card_defines_element_and_registers():
    src = MASTER_CARD.read_text(encoding="utf-8")
    assert 'customElements.define("ga-master-card"' in src
    assert "window.customCards" in src
    # thin client → talks only to the in-Core endpoints
    assert "greenautarky_site/sub_user" in src


# ─── pure loader picks it up ──────────────────────────────────────────────


def test_load_cards_finds_first_party(bundle_module):
    cards = bundle_module.load_cards(FIRST_PARTY)
    assert {"id": "ga-master-card", "file": "ga-master-card.js"} in cards


# ─── HA integration: served + injected without touching community count ───


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _HAS_HA_TEST_HARNESS,
    reason="needs pytest-homeassistant-custom-component (HA test harness); not in CI",
)
async def test_first_party_injected(hass, enable_custom_integrations):
    from homeassistant.setup import async_setup_component

    from custom_components.ga_frontend_bundle.const import (
        COMMUNITY_DIRNAME,
        FIRST_PARTY_URL_BASE,
    )

    assert await async_setup_component(
        hass, "ga_frontend_bundle", {"ga_frontend_bundle": {}}
    )
    await hass.async_block_till_done()

    data = hass.data["ga_frontend_bundle"]
    # community count is reported separately and is unchanged by first-party
    community_count = len(
        json.loads((PKG / COMMUNITY_DIRNAME / "cards.json").read_text())["cards"]
    )
    assert data["injected"] == community_count

    # first-party card injected exactly once at its own URL base
    assert data["first_party_injected"] == 1
    fp_ids = [c["id"] for c in data["first_party_cards"]]
    assert "ga-master-card" in fp_ids

    extra = hass.data.get("frontend_extra_module_url", set())
    assert f"{FIRST_PARTY_URL_BASE}/ga-master-card/ga-master-card.js" in extra
