"""Tests for the ga-home dashboard strategy (room-scoped per-user dashboards).

The strategy is the render half of the room feature: the onboarding component says
WHICH rooms the logged-in user may see, and this turns that into views. It ships
like any other first-party asset — drop it into ``first_party/`` and it is served +
injected on every dashboard.

The guards asserted below are the ones that keep a fleet device from going dark, so
they are checked against the shipped source instead of trusted.
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

    base = _const().FIRST_PARTY_URL_BASE

    assert await async_setup_component(hass, "ga_frontend_bundle", {})
    await hass.async_block_till_done()

    extra = hass.data.get("frontend_extra_module_url", set())
    assert f"{base}/ga-home-strategy/ga-home-strategy.js" in extra


# ─── the 5-second race: a strategy MUST be a Lovelace resource ────────────


def _const():
    """Load const.py standalone — importing the package would pull in homeassistant."""
    spec = importlib.util.spec_from_file_location("ga_fb_const", PKG / "const.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_strategy_is_declared_as_a_strategy_asset():
    """Injection alone loses HA's 5 s registration race — see const.STRATEGY_ASSET_IDS."""
    assert "ga-home-strategy" in _const().STRATEGY_ASSET_IDS


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _HAS_HA_TEST_HARNESS,
    reason="needs pytest-homeassistant-custom-component (HA test harness); not in CI",
)
async def test_strategy_is_registered_as_a_lovelace_resource(hass, enable_custom_integrations):
    """The regression guard for the K0 failure (2026-07-13).

    The module WAS being fetched, but `add_extra_js_url` races the app bootstrap and
    HA only waits 5 s for the element: non-admin sessions on the canary got
    "Timeout waiting for strategy element ll-strategy-dashboard-ga-home". The panel
    loads its RESOURCES before resolving `strategy:`, so the strategy must be one.
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.setup import async_setup_component

    base = _const().FIRST_PARTY_URL_BASE

    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, "ga_frontend_bundle", {})
    hass.bus.async_fire("homeassistant_started")
    await hass.async_block_till_done()

    resources = hass.data[LOVELACE_DATA].resources
    urls = {item["url"] for item in resources.async_items()}
    assert f"{base}/ga-home-strategy/ga-home-strategy.js" in urls

    # …and only the strategy: cards resolve lazily and must not bloat the resources.
    assert not any("ga-master-card" in u for u in urls)


# ─── 1.2.0 — MyVibe look options (KIB-SON-00000050 pilot, 2026-07-21) ─────


def test_options_have_safe_defaults():
    """Options are read defensively; absent config must not throw."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert "function gaOptions(config)" in src
    assert "const c = config || {};" in src
    # new-look defaults ON, view-hiding OFF
    assert "textTabs: c.text_tabs !== false" in src
    assert "singleThermostat: c.single_thermostat !== false" in src
    assert "hideHousehold: !!c.hide_household" in src
    assert "hideRoomless: !!c.hide_roomless" in src


def test_coupled_trvs_render_one_control():
    """TRVs in one room mirror each other — one Steuerung, one Heizplan."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert "opt.singleThermostat ? climateAll.slice(0, 1) : climateAll" in src


def test_myvibe_thermostat_card_is_the_default():
    """The Steuerung card is the FIRST-PARTY ga-thermostat-card (Odoo #518),
    which replaced the vendored community simple-thermostat. The "core" style
    (HA thermostat dial) stays available as an option.
    """
    src = STRATEGY.read_text(encoding="utf-8")
    assert '"custom:ga-thermostat-card"' in src
    assert '"custom:simple-thermostat"' not in src
    assert 'c.thermostat_style === "core" ? "core" : "myvibe"' in src


def test_text_tabs_drop_view_icons():
    """With text_tabs (default) a view carries NO icon, so HA renders the title."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert "...(opt.textTabs ? {} : { icon: ROOM_ICON })" in src
    assert "...(opt.textTabs ? {} : { icon: HOUSE_ICON })" in src


def test_household_and_roomless_views_are_hidable():
    src = STRATEGY.read_text(encoding="utf-8")
    assert "if (!opt.hideHousehold) views.unshift({" in src
    assert "if (!opt.hideRoomless && roomless.length)" in src
