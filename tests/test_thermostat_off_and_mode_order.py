"""AUS sits first, and an off room says what still protects it.

Asked for on 2026-09-30, on 100.126.209.15.

Two things, and the second is the one with teeth:

  the ORDER    AUS ... MANUEL ... KI, left to right — least heating to most,
               so the row reads as one scale. This is PRESENTATION ONLY: every
               button carries its own `data-mode` and the click handler reads
               that, never a position. The test below pins that, because a
               handler that ever read an index would send the wrong service
               to the wrong room while looking perfectly correct on screen.

  the OFF BODY "Heizung aus" told a resident nothing about whether their flat
               can freeze. A TRVZB's `off` IS its anti-freeze state: the valve
               keeps its own `frost_protection_temperature` and opens at it. So
               the card shows THAT number — read from this room's valves, never
               assumed. Measured on the device: three valves, all 7 °C, not the
               5 °C the vendor documents as the default.

               With no valve reporting one, the card must NOT promise frost
               protection it has not read. It falls back to "Heizung aus".

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"

IEEE = ["0xc4d8c8fffe48c786", "0xd44867fffe1155d9"]
METHODS = {"classic": "_renderClassic", "setpoint": "_renderSetpoint"}


def _off_state(valves):
    return {
        "state": "off",
        "attributes": {
            "current_temperature": 18.4,
            "temperature": 21.5,
            "hvac_modes": ["off", "heat", "auto"],
            "hvac_action": "off",
            "min_temp": 5,
            "max_temp": 30,
            "valves": [f"climate.{i}" for i in valves],
        },
    }


def _states(frost):
    """`frost` maps an IEEE to the state its frost `number` entity reports."""
    st = {}
    for ieee, val in frost.items():
        st[f"number.{ieee}_frost_protection_temperature"] = {"state": val}
    return st


def render_off(variant, valves, frost):
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        f" c._variant = {variant!r};"
        " c._showCurrent = false;"
        " c._config = { entity: 'climate.schlafzimmer' };"
        f" c._hass = {{ states: {json.dumps(_states(frost))} }};"
        " c._root = { innerHTML: '' };"
        f" c.{METHODS[variant]}({json.dumps(_off_state(valves))}, '');"
        " return c._root.innerHTML; })()",
    )


# ── the order ───────────────────────────────────────────────────────────────


def test_the_row_reads_aus_manuel_ki():
    src = CARD.read_text(encoding="utf-8")
    labels = re.findall(r'\["(off|heat|auto)", "(AUS|MANUEL|KI)"', src)
    assert labels == [("off", "AUS"), ("heat", "MANUEL"), ("auto", "KI")]


def test_each_button_still_carries_its_own_mode():
    """The backend seam: order is presentation, `data-mode` is the instruction."""
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaThermostatCard.prototype);"
        " c._manualRow = () => '';"
        " return c._modeRow({ state: 'auto', attributes:"
        " { hvac_modes: ['off','heat','auto'] } }); })()",
    )
    assert re.findall(r'data-mode="([a-z]+)"', html) == ["off", "heat", "auto"]
    # the active mode is still marked by STATE, not by position
    assert re.search(r'class="m on [^"]*" data-mode="auto"', html)


def test_the_click_handler_reads_the_mode_off_the_button_not_an_index():
    src = CARD.read_text(encoding="utf-8")
    assert "this._setMode(target.dataset.mode);" in src
    assert 'hvac_mode: mode' in src


# ── the off body ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_an_off_room_shows_the_frost_setpoint_its_valves_hold(variant):
    html = render_off(variant, IEEE, {IEEE[0]: "7", IEEE[1]: "7"})
    assert "Frostschutz" in html
    assert "7" in html and "°C" in html
    assert "Heizung aus" not in html


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_valves_that_disagree_are_both_named(variant):
    html = render_off(variant, IEEE, {IEEE[0]: "7", IEEE[1]: "8"})
    assert "7 / 8" in html


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_no_valve_reports_a_setpoint_means_no_promise(variant):
    html = render_off(variant, IEEE, {})
    assert "Frostschutz" not in html
    assert "Heizung aus" in html


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_an_unreadable_setpoint_is_dropped_rather_than_shown_as_nan(variant):
    html = render_off(variant, IEEE, {IEEE[0]: "unavailable", IEEE[1]: "7"})
    assert "NaN" not in html
    assert "7" in html


def test_only_this_rooms_valves_are_asked():
    """A global sweep would show the neighbour's valve in this room's card."""
    html = render_off(
        "setpoint", [IEEE[0]], {IEEE[0]: "7", "0xf84477fffe0f93e9": "12"}
    )
    assert "12" not in html
    assert "7" in html


def test_a_room_without_a_valves_attribute_does_not_crash():
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaThermostatCard.prototype);"
        " c._hass = { states: {} };"
        " return JSON.stringify(c._frostSetpoints({ attributes: {} })); })()",
    )
    assert json.loads(html) == []


def test_a_heating_room_still_shows_its_target():
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaThermostatCard.prototype);"
        " c._variant = 'setpoint'; c._showCurrent = false;"
        " c._config = { entity: 'climate.schlafzimmer' };"
        " c._hass = { states: {} }; c._root = { innerHTML: '' };"
        " c._renderSetpoint({ state: 'heat', attributes: { temperature: 21.5,"
        " current_temperature: 18.4, hvac_modes: ['off','heat','auto'] } }, '');"
        " return c._root.innerHTML; })()",
    )
    assert "21.5" in html
    assert "Frostschutz" not in html
