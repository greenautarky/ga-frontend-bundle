"""Tests for the ga-home dashboard strategy (room-scoped per-user dashboards).

The strategy is the render half of the room feature: the onboarding component says
WHICH rooms the logged-in user may see, and this turns that into views. It ships
like any other first-party asset — drop it into ``first_party/`` and it is served +
injected on every dashboard.

The guards asserted below are the ones that keep a fleet device from going dark, so
they are checked against the shipped source instead of trusted.
"""

from __future__ import annotations

import pytest
from conftest import PKG

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HAS_HA_TEST_HARNESS = True
except ImportError:
    _HAS_HA_TEST_HARNESS = False

FIRST_PARTY = PKG / "first_party"
STRATEGY = FIRST_PARTY / "ga-home-strategy" / "ga-home-strategy.js"


# ─── the asset itself ─────────────────────────────────────────────────────


def test_strategy_file_present():
    assert STRATEGY.is_file()


def test_registers_modern_strategy_element():
    """HA resolves `custom:ga-home` to exactly this tag (frontend get-strategy.ts)."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'customElements.define("ll-strategy-dashboard-ga-home"' in src
    assert "static async generate(config, hass)" in src


def test_scope_comes_from_the_component_not_the_client():
    """The client must never decide who may see what."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'hass.callApi("get", "greenautarky_onboarding/my_rooms")' in src


def test_missing_component_fails_open():
    """404 = device was never put into household mode → show the house.

    A blank dashboard is only ever correct for a real sub-user who was granted
    nothing. Drop this guard and every device without the component — i.e. most of
    the fleet today — renders an empty page.
    """
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'if (status === 404) return { scope: "all", reason: "no-component"' in src


def test_real_error_does_not_open_the_house():
    """A 500 must produce an error view, not silently reveal every room."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'return { scope: "error"' in src


def test_sub_user_without_rooms_gets_an_empty_state():
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'if (me.scope === "rooms" && !me.areas.length)' in src


def test_device_without_rooms_still_renders_its_house():
    """No HA areas (today's fleet) → group by device class, never an empty list."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert "if (!scoped && !rooms.length)" in src


# ─── the loader picks it up ───────────────────────────────────────────────


def test_load_cards_finds_the_strategy(bundle_module):
    cards = bundle_module.load_cards(FIRST_PARTY)
    assert {"id": "ga-home-strategy", "file": "ga-home-strategy.js"} in cards


# ─── HA integration: it is actually injected (else it never loads) ────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _HAS_HA_TEST_HARNESS,
    reason="needs pytest-homeassistant-custom-component (HA test harness); not in CI",
)
async def test_strategy_is_injected(hass, enable_custom_integrations):
    from homeassistant.setup import async_setup_component

    from custom_components.ga_frontend_bundle.const import FIRST_PARTY_URL_BASE

    assert await async_setup_component(hass, "ga_frontend_bundle", {})
    await hass.async_block_till_done()

    extra = hass.data.get("frontend_extra_module_url", set())
    assert f"{FIRST_PARTY_URL_BASE}/ga-home-strategy/ga-home-strategy.js" in extra
