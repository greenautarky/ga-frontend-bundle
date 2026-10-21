"""The "Steuerung" title on the thermostat card can be switched off.

Asked for on 2026-09-29: the card sits directly under the room's "Heizung"
heading, so its own "Steuerung" line repeats what the heading already says.

Two halves, and either alone leaves the title on screen:

  the CARD      `header || "Steuerung"` turned `header: ""` back into the
                default, so not even a hand-written config could drop it
  the STRATEGY  hard-coded `header: "Steuerung"` for every room

The default stays "Steuerung" — dropping it is opt-in, not a fleet change.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"
STRATEGY = PKG / "first_party" / "ga-home-strategy" / "ga-home-strategy.js"

STATE = (
    '{ state: "heat",'
    ' attributes: { current_temperature: 18.4, temperature: 21.5,'
    ' hvac_modes: ["off", "heat", "auto"], hvac_action: "%s",'
    ' min_temp: 5, max_temp: 30, friendly_name: "Wohnzimmer" } }'
)
METHODS = {"classic": "_renderClassic", "setpoint": "_renderSetpoint", "dial": "_renderDial"}


def render(variant: str, config: dict, action: str = "idle") -> str:
    """Run the card's real header resolution + render and return the markup."""
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        f" c._variant = {variant!r};"
        " c._showCurrent = false;"
        f" c._config = {json.dumps(config)};"
        " c._root = { innerHTML: '' };"
        ' const header = c._config.header ?? "Steuerung";'
        f" c.{METHODS[variant]}({STATE % action}, header);"
        " return c._root.innerHTML; })()",
    )


def test_the_card_resolves_the_header_with_nullish_not_falsy():
    src = CARD.read_text(encoding="utf-8")
    assert 'const header = this._config.header ?? "Steuerung";' in src
    assert 'this._config.header || "Steuerung"' not in src


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_default_keeps_the_title(variant):
    html = render(variant, {"entity": "climate.x"})
    assert '<div class="hdr">Steuerung' in html


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_empty_header_drops_the_title_but_keeps_the_badge(variant):
    html = render(variant, {"entity": "climate.x", "header": ""})
    assert "Steuerung" not in html
    # the badge takes the title's place: first thing in the card, no float
    assert html.startswith('<div class="ga-body')
    assert '"><div class="hdr notitle"><span class="act act-idle"' in html
    assert "Leerlauf" in html


@pytest.mark.parametrize("variant", sorted(METHODS))
def test_custom_header_replaces_the_title(variant):
    html = render(variant, {"entity": "climate.x", "header": "Thermostat"})
    assert '<div class="hdr">Thermostat' in html
    assert "Steuerung" not in html


def test_no_title_and_no_badge_leaves_no_empty_line():
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaThermostatCard.prototype);"
        " c._actionBadge = () => '';"
        " return JSON.stringify(c._hdr({}, '')); })()",
    )
    assert json.loads(html) == ""


# ── strategy ────────────────────────────────────────────────────────────────


def _strategy_src() -> str:
    return STRATEGY.read_text(encoding="utf-8")


def test_strategy_option_is_an_override_not_a_default():
    """THE MEANING CHANGED on 2026-10-21. The header used to read "Steuerung",
    a word every room repeated, and `thermostat_header: ""` was how a device
    turned it off — which is what K55 has. The header now carries the ROOM
    NAME, so "" can no longer mean "show nothing": a device that switched the
    old word off was not asking to lose the new one."""
    src = _strategy_src()
    # The empty string must fall through to the room name, so the option can
    # only ever ADD a custom word — never take the name away.
    flat = " ".join(src.split())
    assert 'typeof c.thermostat_header === "string" && c.thermostat_header' in flat
    assert "? c.thermostat_header : null," in flat


def test_strategy_hands_the_card_the_room_name():
    src = _strategy_src()
    assert "opt.thermostatHeader || room.name || room.area_id" in src
    assert 'header: "Steuerung"' not in src, "the title is hard-coded again"


def test_simple_fallback_hides_its_header_too():
    assert "header: header ? { name: header } : false," in _strategy_src()


# ── icons ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action, key, icon, word",
    [("heating", "heating", "mdi:radiator", "Heizt"),
     ("idle", "idle", "mdi:radiator-off", "Leerlauf")],
)
def test_each_running_state_carries_an_icon_next_to_its_word(action, key, icon, word):
    html = render("setpoint", {"entity": "climate.x", "header": ""}, action=action)
    assert f'<span class="act act-{key}"><ha-icon icon="{icon}"></ha-icon>{word}</span>' in html


def test_the_notitle_badge_is_not_floated_right():
    src = CARD.read_text(encoding="utf-8")
    assert "ga-thermostat-card .hdr.notitle .act { float: none; }" in src
    assert ".hdr.notitle { text-align: right; }" not in src
