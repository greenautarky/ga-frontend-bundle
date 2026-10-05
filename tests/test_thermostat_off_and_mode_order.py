"""AUS sits first, and an off room looks exactly like a heating one.

Asked for on 2026-09-30, on a resident test device.

  the ORDER    AUS ... MANUEL ... KI, left to right — least heating to most,
               so the row reads as one scale. This is PRESENTATION ONLY: every
               button carries its own `data-mode` and the click handler reads
               that, never a position. The test below pins that, because a
               handler that ever read an index would send the wrong service
               to the wrong room while looking perfectly correct on screen.

  the OFF BODY An off room used to lose its whole body: no value, no −/+, just
               "Heizung aus". The card jumped every time someone pressed AUS.
               Now there is ONE body for every state — same big value, same
               −/+, nothing added and nothing taken away.

               A press on −/+ while off is a setpoint like any other, so
               ga_heating takes the room out of AUS and heats. Chosen
               deliberately; the test below pins that the buttons are really
               there, because "off" and "cannot be changed" are not the same
               statement and the card must not quietly make them one.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"

METHODS = {"classic": "_renderClassic", "setpoint": "_renderSetpoint"}

ATTRS = {
    "hvac_modes": ["off", "heat", "auto"],
    "temperature": 21.5,
    "current_temperature": 18.4,
    "min_temp": 5,
    "max_temp": 30,
}


def render(variant, state, hvac_action):
    st = {"state": state, "attributes": {**ATTRS, "hvac_action": hvac_action}}
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        f" c._variant = {variant!r};"
        " c._showCurrent = false;"
        " c._config = { entity: 'climate.badezimmer' };"
        " c._hass = { states: {} };"
        " c._root = { innerHTML: '' };"
        f" c.{METHODS[variant]}({json.dumps(st)}, '');"
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
    assert "hvac_mode: mode" in src


# ── one body for every state ────────────────────────────────────────────────


def _normalise(html: str) -> str:
    """Everything an off room is ALLOWED to differ in, removed.

    Two things legitimately differ and nothing else may: the running-state badge
    ("Aus" vs "Heizt"), and which mode button is marked active. Both are read off
    the entity's state, which is the point. Normalising exactly these two is what
    makes the rest an equality — a weaker strip would pass on a card that dropped
    the value or the buttons again (it did, on the first attempt at this test).
    """
    html = re.sub(r'<span class="act[^>]*>.*?</span>', "", html, flags=re.S)
    return re.sub(r'class="m[^"]*"', 'class="m"', html)


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_an_off_room_renders_exactly_like_a_heating_one(variant):
    """THE RED ONE for the jump."""
    assert _normalise(render(variant, "off", "off")) == _normalise(
        render(variant, "heat", "heating")
    )


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_an_off_room_keeps_its_value_and_both_buttons(variant):
    html = render(variant, "off", "off")
    assert "21.5" in html
    assert 'data-delta="-1"' in html and 'data-delta="1"' in html


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_nothing_is_added_to_an_off_room(variant):
    """The frost line lived here for one afternoon (2026-09-30) and was dropped."""
    html = render(variant, "off", "off")
    assert "Frostschutz" not in html
    assert "frostline" not in html
    assert "Heizung aus" not in html


def test_the_badge_is_the_only_difference():
    assert 'act-off' in render("setpoint", "off", "off")
    assert 'act-heating' in render("setpoint", "heat", "heating")


def test_the_off_button_is_a_neutral_not_the_brand_colour():
    """Painted in the theme's primary like KI, "off" reads as a state somebody is
    pleased about. A dark neutral says only that the room is off."""
    src = CARD.read_text(encoding="utf-8")
    assert "ga-thermostat-card .modes .m.on.off { background: var(--ga-off, #616161); }" in src
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaThermostatCard.prototype);"
        " c._manualRow = () => '';"
        " return c._modeRow({ state: 'off', attributes:"
        " { hvac_modes: ['off','heat','auto'] } }); })()",
    )
    assert 'class="m on off" data-mode="off"' in html
    # …and the other two keep their own classes
    assert 'class="m  heat" data-mode="heat"' in html
    assert 'class="m  " data-mode="auto"' in html


# ── the seam with ga_heating ────────────────────────────────────────────────


def test_a_press_on_an_off_room_sends_a_setpoint_and_nothing_else():
    """What + on an off room puts on the wire: ONE `climate.set_temperature`,
    no `set_hvac_mode`. The card leaves the mode change to the backend, so this
    is only correct against ga_heating >= 0.12.0, which turns an OFF room on in
    MANUEL for a setpoint. ga_heating 0.11.x drives the valves to `heat` and
    leaves the room "off" — a radiator heating under an AUS label. The bundle
    has no mechanism to declare that minimum; it is stated in CHANGELOG 1.22.0
    and must be honoured by the OS pin (ship both in the same release)."""
    calls = run_js(
        CARD,
        "(() => { const calls = [];"
        " const c = Object.create(GaThermostatCard.prototype);"
        " c._config = { entity: 'climate.badezimmer' };"
        " c._hass = { callService: (d, s, data) => calls.push([d, s, data]),"
        "   states: { 'climate.badezimmer': { state: 'off', attributes: "
        + json.dumps(ATTRS) + " } } };"
        " c._root = null;"
        " c._setTemp(1); clearTimeout(c._commitTimer); c._flushTemp();"
        " return calls; })()",
    )
    assert calls == [
        ["climate", "set_temperature", {"entity_id": "climate.badezimmer", "temperature": 22}]
    ]
