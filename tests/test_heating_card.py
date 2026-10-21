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
STRATEGY = FIRST_PARTY / "ga-home-strategy" / "ga-home-strategy.js"


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


def test_card_is_not_early_injected():
    """A card must NOT be on the add_extra_js_url path.

    This used to assert the opposite belief ("cards resolve lazily, so they keep
    the injection path"). That belief was wrong and it is what broke every
    first-party card on a freshly flashed canary (2026-09-15): an injected module
    can register before HA replaces `window.customElements`, and everything in
    the pre-swap registry is invisible to `customElements.get()` afterwards.
    Lazily resolved or not, a card is resolved against the post-swap registry."""
    assert "ga-heating-card" not in _const().EARLY_INJECT_ASSET_IDS


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _HAS_HA_TEST_HARNESS,
    reason="needs pytest-homeassistant-custom-component (HA test harness); not in CI",
)
async def test_card_is_delivered_as_a_resource_and_never_injected(
    hass, enable_custom_integrations
):
    from homeassistant.setup import async_setup_component

    base = _const().FIRST_PARTY_URL_BASE
    assert await async_setup_component(hass, "ga_frontend_bundle", {})
    await hass.async_block_till_done()

    extra = hass.data.get("frontend_extra_module_url", set())
    assert not [u for u in extra if u.startswith(f"{base}/ga-heating-card/")], (
        "the heating card is on the early-injection path again — it will register "
        "into the pre-swap registry and render as \"Custom element doesn't exist\""
    )
    assert "ga-heating-card" in hass.data["ga_frontend_bundle"]["first_party_resources"]


# ── the header (2026-09-30) ─────────────────────────────────────────────────


def test_the_strategy_passes_no_room_name_to_the_heating_card():
    """The "Heizplan" heading is directly above it and the tab is the room, so a
    room-name header inside the card was the same thing said a third time.

    Asserted on the card object alone: `title: room.name` also spells the VIEW's
    tab title a few lines away, and a bare "not in src" flagged that instead —
    green logic, red build (CI, 2026-09-30).
    """
    src = STRATEGY.read_text(encoding="utf-8")
    assert '{ type: "custom:ga-heating-card", entity },' in src
    assert '{ type: "custom:ga-heating-card", entity, title' not in src


def test_the_card_ships_no_header_by_default():
    """Defaulting to "Heizplan" only moved the duplication one line up."""
    src = CARD.read_text(encoding="utf-8")
    assert 'const title = this._config.title ?? "";' in src
    assert '"Heizplan"' not in src.split("_header()")[1][:200]
    assert 'return title ? ` header="${esc(title)}"` : "";' in src


# ── the holiday's own plan (2026-10-21) ────────────────────────────────────
# A holiday no longer sits on top of the plan as an override — it REPLACES it,
# so the radiators can run it in their own `auto` and their displays say `auto`
# instead of "Manual 15". ga_heating holds the resident's real plan while it
# runs and puts it back afterwards.
#
# Which means this card shows seven identical days during a holiday. Without
# the notice that is indistinguishable from a plan that has been wiped.


def test_the_card_says_when_a_holiday_plan_is_running():
    """ONE FACT ON THE LINE: what is running and until when. No temperature —
    every row of the week below already shows it, and the banner repeating it
    says the same number twice."""
    src = CARD.read_text(encoding="utf-8")
    assert "Urlaubsplan aktiv" in src
    assert "fmtTemp" not in src, "the banner should not restate the setpoint"


def test_the_rest_is_behind_an_i_like_the_services_card():
    """The page is for the plan, not for paragraphs about it — the same shape
    the Services section already uses."""
    src = CARD.read_text(encoding="utf-8")
    assert 'class="infobtn"' in src
    assert 'aria-expanded' in src
    # The two things a resident needs from it: it comes back, and how to change
    # it now. Whitespace-normalised because the sentence wraps in the template,
    # and a substring check against the raw source fails on correct markup.
    flat = " ".join(src.split())
    assert "gilt wieder, sobald der Urlaub vorbei ist" in flat
    assert "beenden Sie den Urlaub" in flat


def test_the_explanation_starts_closed():
    """A panel open on arrival is the extra text the "i" exists to remove."""
    src = CARD.read_text(encoding="utf-8")
    assert '<div class="urlaubtip" hidden>' in src


def test_the_week_is_read_only_while_it_runs():
    """The week on screen is the holiday's, not the resident's. Saving an edit
    to it would be overwritten when the holiday ended, and the edit would
    vanish without ever being wrong enough to report."""
    src = CARD.read_text(encoding="utf-8")
    assert 'classList.toggle("locked"' in src
    style = src[src.index("<style>"):src.index("</style>")]
    assert "ga-heating-card.locked .actions button" in style
    assert "pointer-events:none" in style


def test_the_controls_stay_visible_rather_than_disappearing():
    """Hiding them would read as the feature having been removed."""
    style = CARD.read_text(encoding="utf-8")
    locked = style[style.index("ga-heating-card.locked"):]
    locked = locked[:locked.index("}") + 1]
    assert "display:none" not in locked, locked


def test_the_plan_is_reloaded_when_a_holiday_starts_or_ends():
    """The plan under this card is swapped by the ENGINE, not by the card:
    without a reload a holiday starting leaves the resident's week on screen,
    and one ending leaves the flat one."""
    src = CARD.read_text(encoding="utf-8")
    sync = src[src.index("_syncUrlaub() {"):]
    sync = sync[:sync.index(chr(10) + "  }")]
    assert "this._load()" in sync, sync
    # …but not on the very first pass, where the builder has just loaded
    assert "first" in sync


def test_an_off_holiday_does_not_claim_a_plan():
    """"Aus · Frostschutz" has no temperature to build a week from, so the
    engine leaves the plan alone — and so must the notice."""
    src = CARD.read_text(encoding="utf-8")
    u = src[src.index("_urlaub() {"):]
    u = u[:u.index(chr(10) + "  }")]
    assert "a.off" in u, u
