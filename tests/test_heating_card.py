"""Tests for the ga-heating-card (weekly heating plan).

The card is the resident's half of the heating plan; ga_heating (in Core) is the other
half. The assertions below are about the CONTRACT between them, and about the rule the
whole design rests on:

    the card never speaks a device's language — it speaks ours.

A card that writes `text.<trv>_weekly_schedule_<day>` directly would work for exactly
one thermostat model and would have to know that the Sonoff TRV wants six transitions
starting at 00:00. That knowledge belongs in ga_heating's device adapter, nowhere else.
"""

from __future__ import annotations

import importlib.util

import pytest
from conftest import PKG

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HAS_HA_TEST_HARNESS = True
except ImportError:
    _HAS_HA_TEST_HARNESS = False

FIRST_PARTY = PKG / "first_party"
CARD = FIRST_PARTY / "ga-heating-card" / "ga-heating-card.js"


def _const():
    spec = importlib.util.spec_from_file_location("ga_fb_const", PKG / "const.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_card_file_present():
    assert CARD.is_file()


def test_registers_the_element_and_advertises_itself():
    src = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("ga-heating-card"' in src
    assert "window.customCards" in src


def _code_only(src: str) -> str:
    """The source with comments stripped — the guards below are about what the card
    DOES, not about what it explains. (This test first fired on the card's own comment
    describing the device format it deliberately avoids.)"""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("/*", i):
            i = src.find("*/", i) + 2
        elif src.startswith("//", i):
            i = src.find("\n", i)
            if i == -1:
                break
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def test_card_talks_to_our_component_only():
    """The whole point: our API, never a device's own schedule format.

    A card that wrote `text.<trv>_weekly_schedule_<day>` itself would work for exactly
    one thermostat model — and would have to know that this one wants six transitions
    starting at 00:00. That knowledge lives in ga_heating's device adapter.
    """
    code = _code_only(CARD.read_text(encoding="utf-8"))

    assert "ga_heating/schedule" in code
    assert "weekly_schedule" not in code
    assert "text.set_value" not in code
    assert "mqtt" not in code.lower(), "no MQTT topics in a card, ever"


def test_card_requires_a_climate_entity():
    src = CARD.read_text(encoding="utf-8")
    assert 'config.entity.startsWith("climate.")' in src


def test_card_offers_the_copy_shortcuts_that_replaced_the_old_scripts():
    """'Auf Mo–Fr übernehmen' used to be script.set_weekdays_mode_<room> — a service
    per room. It is now three lines of client-side logic."""
    src = CARD.read_text(encoding="utf-8")
    assert "WEEKDAYS" in src
    assert "_copyTo" in src


def test_card_is_discovered_as_first_party(bundle_module):
    cards = bundle_module.load_cards(FIRST_PARTY)
    assert {"id": "ga-heating-card", "file": "ga-heating-card.js"} in cards


def test_card_is_not_a_strategy():
    """Cards resolve lazily, so they keep the injection path — only strategies must be
    Lovelace resources (see the registry-swap fix)."""
    assert "ga-heating-card" not in _const().STRATEGY_ASSET_IDS


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _HAS_HA_TEST_HARNESS,
    reason="needs pytest-homeassistant-custom-component (HA test harness); not in CI",
)
async def test_card_is_injected(hass, enable_custom_integrations):
    from homeassistant.setup import async_setup_component

    base = _const().FIRST_PARTY_URL_BASE
    assert await async_setup_component(hass, "ga_frontend_bundle", {})
    await hass.async_block_till_done()

    extra = hass.data.get("frontend_extra_module_url", set())
    assert f"{base}/ga-heating-card/ga-heating-card.js" in extra
