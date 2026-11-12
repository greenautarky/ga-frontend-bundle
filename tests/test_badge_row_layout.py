"""The heading badge row: where the two groups sit, which number is bold, and
what a phone is told when it taps one.

WHY THESE PIN THE SELECTOR AND NOT JUST THE EFFECT
--------------------------------------------------
Every bug this file guards was a rule that READ correctly and matched nothing,
which is the failure mode card-mod has: a selector that matches nothing looks
exactly like a selector with no work to do. All four were measured on K55 on
2026-11-11, against Home Assistant 2026.8.2:

  * `.badges > *:nth-child(n)` matched only HA's inner `.badges-row` wrapper, so
    the room-left/outside-right split had been dead on the fleet since that
    wrapper appeared. Every badge read `margin-right: 0px` with the rule live.
  * a bare `.badges` ties with HA's own `flex: 0 1 auto` and loses, so the
    container never grew and `margin-right: auto` had no width to push into.
  * `font-weight` on a badge never reaches the number: `ha-heading-badge` prints
    it with `font-weight: var(--ha-heading-badge-font-weight, 400)`.
  * the tap label was drawn correctly and painted into nothing, because
    `.badges` is `overflow: auto` and the box hangs below it.

So these assert the exact text that goes to the browser. A looser test ("the
style mentions the badges") would have passed on all four.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

from test_rendered_output import STRATEGY, run_js

_OUT_T = "sensor.aussentemperatur"
_OUT_H = "sensor.aussenluftfeuchtigkeit"

_STATES = """{
  "climate.wz": { state: "heat", attributes: { current_temperature: 19.8,
                  current_humidity: 56.8, temperature_source: "sensor.wz_t",
                  humidity_source: "sensor.wz_h", valves: ["climate.0xaaa"] } },
  "sensor.wz_t": { state: "19.8", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "56.8", attributes: { device_class: "humidity" } },
  "sensor.aussentemperatur": { state: "3.2",
                  attributes: { device_class: "temperature" } },
  "sensor.aussenluftfeuchtigkeit": { state: "85",
                  attributes: { device_class: "humidity" } }
}"""

_INDOOR_ONLY = """{
  "climate.wz": { state: "heat", attributes: { current_temperature: 19.8,
                  current_humidity: 56.8, temperature_source: "sensor.wz_t",
                  humidity_source: "sensor.wz_h", valves: ["climate.0xaaa"] } },
  "sensor.wz_t": { state: "19.8", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "56.8", attributes: { device_class: "humidity" } }
}"""

_ROOM = ('{ name: "Wohnzimmer", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
         ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }')


def _heading(room: str = _ROOM, states: str = _STATES) -> dict:
    """The room view's first heading card: its badges and its card-mod style."""
    return json.loads(run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      const h = roomSections({room}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .find(c => c.type === "heading");
      return JSON.stringify({{
        names: (h.badges || []).map(b => b.name),
        style: (h.card_mod || {{}}).style || "",
      }});
    }})()"""))


# ── where the two groups sit ────────────────────────────────────────────────

def test_the_split_targets_the_row_ha_actually_renders():
    """THE RED ONE. `.badges > *` matches HA's single `.badges-row` wrapper and
    never a badge, which is how this went unnoticed for releases."""
    style = _heading()["style"]
    assert ".badges-row > *:nth-child(3) { margin-right: auto; }" in style, style
    assert ".badges > *:nth-child" not in style, style


def test_the_container_outranks_home_assistants_own_flex():
    """A bare `.badges` ties with HA's `flex: 0 1 auto` and loses on source
    order, leaving no spare width for `margin-right: auto` to push into."""
    style = _heading()["style"]
    assert "div.badges { flex: 1 1 auto; }" in style, style
    assert "div.badges-row { flex: 1 1 auto; }" in style, style


def test_a_room_with_no_outdoor_pair_is_not_split_at_all():
    """MUST-NOT-FLAG. With one group, every badge pinned right is already the
    answer — growing the container would shove them left for nothing."""
    style = _heading(states=_INDOOR_ONLY)["style"]
    assert "margin-right: auto" not in style, style
    # `div.badges { flex`, not `div.badges {`: the tooltip block below carries a
    # `div.badges { overflow: visible; }` of its own, which a looser assertion
    # matches — it caught this test out the first time it was written.
    assert "div.badges { flex" not in style, style


# ── which number is bold ────────────────────────────────────────────────────

def test_the_rooms_own_temperature_is_bold_through_the_variable():
    """`font-weight` on the badge never reaches the number — `ha-heading-badge`
    prints it with `font-weight: var(--ha-heading-badge-font-weight, 400)`."""
    style = _heading()["style"]
    assert "--ha-heading-badge-font-weight: 700" in style, style
    assert "nth-child(2) { --ha-heading-badge-font-weight" in style, style


def test_the_weight_is_one_roboto_actually_ships():
    """600 is synthesised to something indistinguishable from regular at 14 px,
    which is how the first attempt shipped looking unchanged. Roboto has
    400/500/700."""
    assert "font-weight: 600" not in _heading()["style"]


def test_the_bold_survives_a_room_with_no_outdoor_pair():
    """It is about the room's own reading, not about the split."""
    assert "--ha-heading-badge-font-weight: 700" in _heading(states=_INDOOR_ONLY)["style"]


# ── what a phone is told ────────────────────────────────────────────────────

def test_each_badge_names_itself_for_a_screen_that_cannot_hover():
    """The badge `name` is only a `title`: a laptop shows it on hover, a touch
    screen cannot show it at all. The words are the chart's — "Raum Temperatur"
    rather than "Temperatur" — because the question being asked is which side of
    the wall the number came from."""
    style = _heading()["style"]
    for n, text in enumerate(
        ["Innen", "Raum Temperatur", "Raum Luftfeuchtigkeit",
         "Außen", "Außentemperatur", "Außenluftfeuchtigkeit"], start=1
    ):
        assert f'.badges-row > *:nth-child({n}):hover::after {{ content: "{text}"; }}' \
            in style, (n, text, style)


def test_the_label_is_touch_only_so_a_laptop_shows_one_tooltip_not_two():
    style = _heading()["style"]
    assert "@media (hover: none) {" in style, style
    # the hover rules must live INSIDE that query
    inside = style.split("@media (hover: none) {", 1)[1]
    assert ':hover::after { content: "Raum Temperatur"; }' in inside, inside


def test_the_label_is_not_clipped_away_by_the_rows_own_overflow():
    """`.badges` is `overflow: auto` — HA scrolls the row when it does not fit —
    which clips a box hanging below the badge. The first build drew the label
    correctly and painted it into nothing."""
    inside = _heading()["style"].split("@media (hover: none) {", 1)[1]
    assert "div.badges { overflow: visible; }" in inside, inside
    assert ".badges-row > * { position: relative; }" in inside, inside
