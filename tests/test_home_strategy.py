"""Tests for the ga-home dashboard strategy (room-scoped per-user dashboards).

Since 1.6.0 (#569) the strategy is PURE PRESENTATION: the onboarding component
computes a ready, already-scoped, states-validated model server-side and this file
only renders it. The tests below therefore pin two things:

1. the SEAM — the exact field names the strategy reads out of the
   ``/api/greenautarky_site/home_model`` response. A field rename on the
   server must fail a test here, not silently blank a resident's board
   (feedback_seam_test_at_boundary). The matching producer-side assertion lives in
   greenautarky-site ``tests/test_rooms.py`` (``test_home_model_*``); together
   they lock the contract from both ends.
2. the load-bearing render guards that keep a fleet device from going dark.

They are checked against the shipped source instead of trusted.
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


def _src() -> str:
    return STRATEGY.read_text(encoding="utf-8")


# ─── the asset itself ─────────────────────────────────────────────────────


def test_strategy_file_present():
    assert STRATEGY.is_file()


def test_registers_modern_strategy_element():
    """HA resolves `custom:ga-home` to exactly this tag (frontend get-strategy.ts)."""
    src = _src()
    assert 'customElements.define("ll-strategy-dashboard-ga-home"' in src
    assert "static async generate(config, hass)" in src


# ─── the seam: the model comes from the server, rendered field-for-field ──


def test_model_comes_from_the_component_not_the_client():
    """The client must never decide who may see what — it fetches the ready model.

    Since #569 that is the server-computed home_model, NOT my_rooms + a client-side
    registry re-derivation (which crashed for scoped sub-users on null states).
    """
    src = _src()
    assert 'hass.callApi("get", "greenautarky_site/home_model")' in src


def test_strategy_never_re_derives_from_the_registries():
    """The crash class #569 removed: the strategy must NOT pull the device/entity
    registries or re-apply scope client-side. The server hands a ready model."""
    src = _src()
    assert "config/entity_registry/list" not in src
    assert "config/device_registry/list" not in src
    assert "__gaCat" not in src


def test_seam_room_fields_are_read_verbatim():
    """The per-room contract the server emits — a rename here or there breaks a board.

    Producer side: greenautarky-site ``_build_home_model`` returns each room as
    ``{area_id, name, climate, lights, switches, temps, hums, batts}``. This is the
    consumer side reading the SAME keys. Keep the two in lockstep.
    """
    src = _src()
    for field in ("room.climate", "room.lights", "room.switches",
                  "room.temps", "room.hums", "room.batts", "room.name"):
        assert field in src, field


def test_seam_top_level_fields_are_read_verbatim():
    """The top-level model contract: scope / rooms / roomless / is_master / user_name."""
    src = _src()
    for field in ("model.scope", "model.rooms", "model.roomless",
                  "model.is_master", "model.user_name", "model.reason"):
        assert field in src, field


# ─── the render guards that keep a device from going dark ─────────────────


def test_missing_component_fails_open():
    """404 = device was never put into household mode → show the house.

    A blank dashboard is only ever correct for a real sub-user who was granted
    nothing. Drop this guard and every device without the component renders empty.
    """
    src = _src()
    assert 'if (status === 404) return { scope: "nocomponent"' in src
    assert 'model.scope === "nocomponent"' in src
    assert "function flatFallbackView(name, hass)" in src


def test_real_error_does_not_open_the_house():
    """A 500 must produce an error view, not silently reveal every room."""
    src = _src()
    assert 'return { scope: "error"' in src
    assert 'if (model.scope === "error")' in src


def test_sub_user_without_rooms_gets_an_empty_state():
    """A real sub-user granted nothing gets an honest empty state — NOT the house."""
    src = _src()
    assert "if (scoped && !rooms.length)" in src
    assert "emptyView(userName)" in src


def test_device_without_rooms_still_renders_its_house():
    """No HA areas (today's fleet): the server puts everything in `roomless` and the
    strategy renders it flat, never an empty room list."""
    src = _src()
    assert "if (!scoped && !rooms.length)" in src
    assert "noRoomsView(userName, model)" in src


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


# ─── options + card looks (KIB-SON-00000050 pilot, 2026-07-21) ────────────


def test_options_have_safe_defaults():
    """Options are read defensively; absent config must not throw."""
    src = _src()
    assert "function gaOptions(config)" in src
    assert "const c = config || {};" in src
    # new-look defaults ON, view-hiding OFF
    assert "textTabs: c.text_tabs !== false" in src
    assert "singleThermostat: c.single_thermostat !== false" in src
    assert "hideHousehold: !!c.hide_household" in src
    assert "hideRoomless: !!c.hide_roomless" in src


def test_coupled_trvs_render_one_control():
    """TRVs in one room mirror each other — one Steuerung, one Heizplan."""
    src = _src()
    assert "opt.singleThermostat ? climateAll.slice(0, 1) : climateAll" in src


def test_classic_thermostat_card_is_the_default():
    """The default Steuerung card is the FIRST-PARTY ga-thermostat-card (Odoo
    #518), variant "classic". "dial"/"setpoint" are the other looks of the SAME
    card; "core" (HA dial) and "simple" (vendored fallback) also stay.
    """
    src = _src()
    assert '"custom:ga-thermostat-card"' in src
    # unknown / "myvibe" resolve to classic (the default)
    assert 'c.thermostat_style === "myvibe" ? "classic" : c.thermostat_style' in src
    assert '["classic", "dial", "setpoint", "core", "simple"].includes(v) ? v : "classic"' in src
    # the three first-party looks are one branch that passes `variant`
    assert '["classic", "dial", "setpoint"].includes(style)' in src
    assert "variant: style" in src


def test_all_four_thermostat_styles_reachable():
    """classic/dial/setpoint (our card) + core (HA) + simple (fallback)."""
    src = _src()
    for token in ('"classic"', '"dial"', '"setpoint"', '"simple"'):
        assert token in src, token
    # core = built-in HA thermostat card, renameable title = room name
    assert 'type: "thermostat"' in src and "name: roomName" in src


def test_simple_thermostat_kept_as_fallback():
    """Coexistence (1.4.0): the vendored community simple-thermostat is still in
    the bundle so hand-built dashboards referencing it keep working, and it is a
    fallback while the first-party card matures — selectable via "simple"."""
    src = _src()
    assert 'style === "simple"' in src
    assert '"custom:simple-thermostat"' in src


def test_text_tabs_drop_view_icons():
    """With text_tabs (default) a view carries NO icon, so HA renders the title."""
    src = _src()
    assert "...(opt.textTabs ? {} : { icon: ROOM_ICON })" in src
    assert "...(opt.textTabs ? {} : { icon: HOUSE_ICON })" in src


def test_household_and_roomless_views_are_hidable():
    src = _src()
    assert "if (!opt.hideHousehold) views.unshift(householdOverview(" in src
    assert "if (!opt.hideRoomless && model.roomless)" in src
    # master-only management view is generated only for the master
    assert "if (model.is_master) views.push(manageView(opt))" in src
