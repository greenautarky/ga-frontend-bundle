"""The room's measured temperature is back as a heading badge (2026-09-25).

Thomas asked on 2026-09-25 for the measured room temperature to be shown again
"da wo auch die Luftfeuchtigkeit angezeigt wird" — the badges of the room view's
"Heizung" heading. This reverses, FOR THE BADGE ONLY, the Odoo #1060 decision of
2026-09-23 that had dropped it. The thermostat card stays setpoint-only
(tests/test_thermostat_target_only.py still pins that).

Source (decision 2026-09-25): the ga_heating room entity's `current_temperature`
(ga_heating picks room sensor first, valve fallback); else `room.temps[0]`;
else no badge, never a null one.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

from test_rendered_output import STRATEGY, run_js


def _badges(room: str, states: str = "{}") -> list:
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      const secs = roomSections({room}, gaOptions({{}}), hass);
      // THE FIRST HEADING, not one matched by its text. It used to be found by
      // `heading === "Heizung"`, and every test in this file went vacuous the day
      // that heading became the room name (CI, 2026-10-08) — the helper returned
      // null and the assertions fell over somewhere else entirely.
      const h = secs.flatMap(s => s.cards || []).find(c => c.type === "heading");
      return h ? h.badges : null;
    }})()"""
    return run_js(STRATEGY, expr)



def _readings(room: str, states: str = "{}") -> list:
    """The badges that carry a VALUE. "Aktuell" is a label for the pair, not a
    reading, so tests about which sensor a reading comes from skip it — rather
    than every one of them renumbering around a word (2026-10-08)."""
    return [b for b in (_badges(room, states) or []) if b.get("name") != "Aktuell"]


_STATES = """{
  "climate.wz": { state: "heat", attributes: { current_temperature: 19.5, temperature: 21 } },
  "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "48", attributes: { device_class: "humidity" } },
  "sensor.wz_b": { state: "80", attributes: { device_class: "battery" } }
}"""


def test_temperature_badge_comes_first_then_humidity():
    """Room with temp + humidity sensors -> badges = [Temperatur, Luftfeuchtigkeit].

    THE BATTERY BADGE IS GONE from this row (2026-10-05). It was
    `batts.slice(0, 1)`: one percentage for a room that may hold three battery
    devices, with nothing saying which one it came from. The reading moved to
    the Wartung section, which appears only when a battery needs a person and
    names the device — see test_maintenance_card.py.

    The room below still HAS a battery sensor, so this also pins that removing
    the badge did not quietly take the humidity one with it."""
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: ["sensor.wz_h"], batts: ["sensor.wz_b"], lights: [], switches: [] }',
                _STATES)
    assert b is not None, "no heading built — the test would be vacuous"
    # "Aktuell" labels the pair (2026-10-08); the ORDER of the two readings after
    # it is what this test is about and is unchanged.
    assert [x["name"] for x in b] == ["Aktuell", "Temperatur", "Luftfeuchtigkeit"], b
    assert b[2]["entity"] == "sensor.wz_h"


# -- a room with no hygrometer of its own ------------------------------------
#
# Asked for on 2026-10-06, together with the temperature: a sensorless room shows
# the house figure rather than nothing. ga_heating computes it (there is no third
# fallback -- a TRV does not measure humidity) and publishes it as
# `current_humidity`; the badge binds to the climate entity for it, exactly as the
# temperature badge does for `current_temperature`.

_NO_HYGRO = """{
  "climate.flur": { state: "heat", attributes: { current_temperature: 20.6,
    current_humidity: 44.5, temperature_source: "house_average",
    humidity_source: "house_average" } }
}"""


def test_a_room_without_a_hygrometer_shows_the_house_figure():
    b = _readings('{ name: "Flur", climate: ["climate.flur"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', _NO_HYGRO)
    assert b is not None
    assert [x["name"] for x in b] == ["Temperatur", "Luftfeuchtigkeit"], b
    hum = b[1]
    assert hum["entity"] == "climate.flur"
    assert hum["state_content"] == "current_humidity", (
        "bound to the climate entity without this, the badge shows the entity STATE "
        "- 'Heat' where a percentage belongs"
    )
    assert hum["icon"] == "mdi:water-percent", "else it takes the thermostat glyph"


def test_a_room_with_its_own_hygrometer_still_uses_it():
    """Must-not-flag: the fallback must not capture rooms that can measure."""
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }', _STATES)
    assert b[1]["entity"] == "sensor.wz_h"
    assert "state_content" not in b[1], "a sensor's own state IS the reading"


def test_no_hygrometer_anywhere_means_no_humidity_badge():
    """A house with no hygrometers at all: ga_heating publishes no
    `current_humidity`, and an empty badge is worse than none."""
    states = """{
      "climate.flur": { state: "heat", attributes: { current_temperature: 20.6 } }
    }"""
    b = _readings('{ name: "Flur", climate: ["climate.flur"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', states)
    assert [x["name"] for x in b] == ["Temperatur"], b


def test_no_temperature_source_means_no_temperature_badge_and_no_null():
    """Room without a temperature sensor and without a usable current_temperature."""
    states = '{ "climate.wz": { state: "heat", attributes: { temperature: 21 } } }'
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: ["sensor.wz_h"],'
                ' batts: [], lights: [], switches: [] }', states)
    assert b is not None
    assert [x["name"] for x in b] == ["Luftfeuchtigkeit"], b
    for x in b:
        assert x is not None and x.get("entity"), f"empty/null badge: {x}"


def test_without_a_sensor_the_thermostat_measurement_is_the_fallback():
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', _STATES)
    assert b == [{"type": "entity", "entity": "climate.wz", "name": "Temperatur",
                  "icon": "mdi:thermometer",
                  "state_content": "current_temperature"}], b


def test_a_room_climate_entity_wins_over_temps():
    """ga_heating's room entity decides (room sensor first, valve fallback), so
    its current_temperature (19.5) must beat temps[0] (20.1)."""
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: [], batts: [], lights: [], switches: [] }', _STATES)
    assert b[0] == {"type": "entity", "entity": "climate.wz", "name": "Temperatur",
                    "icon": "mdi:thermometer",
                    "state_content": "current_temperature"}, b


def test_temps_is_the_fallback_when_the_climate_has_no_measurement():
    """Badges live on the Heizung heading, which exists only with a climate
    entity — so a room with NO thermostat shows no badges at all (unchanged).
    temps[0] is reached when the climate entity carries no numeric reading."""
    states = """{
      "climate.wz": { state: "heat", attributes: { temperature: 21 } },
      "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } }
    }"""
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: [], batts: [], lights: [], switches: [] }', states)
    assert b == [{"type": "entity", "entity": "sensor.wz_t", "name": "Temperatur",
                  "icon": "mdi:thermometer"}], b


def test_the_temperature_badge_carries_a_thermometer_from_either_source():
    """Read off a climate entity, the badge inherits the THERMOSTAT icon — the
    dial, which is the control, not the reading. Stated on both branches, so the
    badge looks the same whichever source answers."""
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', _STATES)
    assert b is not None, "no heading built — the test would be vacuous"
    assert b[0]["icon"] == "mdi:thermometer"

    # The sensor branch needs a climate entity to exist (the badges live on the
    # Heizung heading) but carry no numeric reading — same setup as the fallback
    # test above. A room with `climate: []` builds no heading at all, so asking
    # for its badges would test nothing.
    states = """{
      "climate.wz": { state: "heat", attributes: { temperature: 21 } },
      "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } }
    }"""
    b2 = _readings('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                 ' hums: [], batts: [], lights: [], switches: [] }', states)
    assert b2 is not None, "no heading built — the test would be vacuous"
    assert b2[0]["entity"] == "sensor.wz_t"
    assert b2[0]["icon"] == "mdi:thermometer"


# ── the 24 h curve (2026-09-30) ─────────────────────────────────────────────


def _temp_graph(room: str, states: str):
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      const secs = roomSections({room}, gaOptions({{}}), hass);
      return secs.flatMap(s => s.cards || [])
        .find(c => c.type === "statistics-graph" && /Temperatur/.test(c.title)) || null;
    }})()"""
    return run_js(STRATEGY, expr)


_VALVE_STATES = """{
  "climate.wz": { state: "heat", attributes: { current_temperature: 19.5, temperature: 21,
                  valves: ["climate.0xdead"] } },
  "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } },
  "sensor.0xdead_local_temperature": { state: "23.6",
                  attributes: { device_class: "temperature" } }
}"""

_ROOM = ('{ name: "WZ", climate: ["climate.wz"],'
         ' temps: ["sensor.wz_t", "sensor.0xdead_local_temperature"],'
         ' hums: [], batts: [], lights: [], switches: [] }')


def test_the_valves_own_thermometer_is_not_a_second_curve():
    """It reads the radiator, not the room — the reason calibration.py exists."""
    g = _temp_graph(_ROOM, _VALVE_STATES)
    assert g is not None, "no temperature graph built — the test would be vacuous"
    assert g["entities"] == [
        {"entity": "sensor.wz_t", "name": "Raum Temperatur", "color": "blue"}]


def test_the_title_says_letzte_24h():
    assert _temp_graph(_ROOM, _VALVE_STATES)["title"] == "Temperatur letzte 24h"


def test_a_room_whose_only_thermometer_is_the_valve_keeps_it_unrenamed():
    """One honest curve under its own name beats an empty card — and "Raum
    Temperatur" on a sensor screwed to the radiator would contradict itself."""
    room = ('{ name: "WZ", climate: ["climate.wz"],'
            ' temps: ["sensor.0xdead_local_temperature"],'
            ' hums: [], batts: [], lights: [], switches: [] }')
    g = _temp_graph(room, _VALVE_STATES)
    # No `name` — that is the point of the test. It is an object rather than a
    # bare id only because every series carries a colour now.
    assert g["entities"] == [
        {"entity": "sensor.0xdead_local_temperature", "color": "blue"}]


def test_two_real_room_sensors_are_both_drawn_and_keep_their_names():
    """Renaming both "Raum Temperatur" would repeat the #22 defect: a legend
    that names the same thing twice reads like one sensor drawn twice."""
    states = """{
      "climate.wz": { state: "heat", attributes: { current_temperature: 19.5,
                      temperature: 21, valves: ["climate.0xdead"] } },
      "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } },
      "sensor.wz_t2": { state: "20.4", attributes: { device_class: "temperature" } }
    }"""
    room = ('{ name: "WZ", climate: ["climate.wz"],'
            ' temps: ["sensor.wz_t", "sensor.wz_t2"],'
            ' hums: [], batts: [], lights: [], switches: [] }')
    # Two colours, not one repeated: a legend with two identical swatches names
    # the same thing twice as surely as two identical labels would.
    assert _temp_graph(room, states)["entities"] == [
        {"entity": "sensor.wz_t", "color": "blue"},
        {"entity": "sensor.wz_t2", "color": "deep-purple"},
    ]


def test_the_humidity_curve_is_named_too_so_no_mean_suffix_leaks():
    """Left to itself the card labelled the series "… Luftfeuchtigkeit (mean)" —
    the card's own arithmetic in a resident's legend."""
    states = """{
      "climate.wz": { state: "heat", attributes: { current_temperature: 19.5,
                      temperature: 21, valves: [] } },
      "sensor.wz_h": { state: "48", attributes: { device_class: "humidity" } }
    }"""
    room = ('{ name: "WZ", climate: ["climate.wz"], temps: [],'
            ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }')
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      const secs = roomSections({room}, gaOptions({{}}), hass);
      return secs.flatMap(s => s.cards || [])
        .find(c => c.type === "statistics-graph") || null;
    }})()"""
    g = run_js(STRATEGY, expr)
    assert g is not None, "no humidity graph built — the test would be vacuous"
    assert g["entities"] == [
        {"entity": "sensor.wz_h", "name": "Raum Luftfeuchtigkeit", "color": "blue"}]
    assert g["title"] == "Luftfeuchtigkeit letzte 24h"


# ── the badge reads the sensor ga_heating named (2026-10-01) ────────────────


_SOURCED = """{
  "climate.wz": { state: "heat", attributes: { current_temperature: 19.5, temperature: 21,
                  temperature_source: "sensor.wz_t" } },
  "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "48", attributes: { device_class: "humidity" } }
}"""

_ROOM_SRC = ('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
             ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }')


def test_the_badge_is_the_sensor_ga_heating_named():
    """THE RED ONE for "Heat" where a temperature belongs.

    An entity badge on a climate entity reads `current_temperature` and falls
    back to the ENTITY'S STATE when that attribute is missing — so a room whose
    thermometer has not reported shows its hvac mode next to a thermometer icon
    (seen during boot on a device 2026-10-01; it would sit there for as long as a
    sensor stayed offline, not only while booting).

    `temperature_source` is ga_heating's own answer to which thermometer is this
    room's, so reading it keeps the one-place rule AND gives the badge an entity
    whose state IS the temperature.
    """
    b = _readings(_ROOM_SRC, _SOURCED)
    assert b is not None, "no heading built — the test would be vacuous"
    assert b[0] == {"type": "entity", "entity": "sensor.wz_t", "name": "Temperatur",
                    "icon": "mdi:thermometer"}, b
    assert "state_content" not in b[0], (
        "a sensor's own state is the temperature; asking for an attribute would "
        "reintroduce the fallback this fixes"
    )


def test_a_room_reading_its_valve_keeps_the_climate_entity():
    """ga_heating reports `temperature_source: "valve"` — not an entity id, so
    there is no sensor to point at. The climate entity still carries the number
    ga_heating decided on, which beats picking a sensor ourselves and disagreeing
    with the heating."""
    states = """{
      "climate.wz": { state: "heat", attributes: { current_temperature: 23.9,
                      temperature: 21, temperature_source: "valve" } },
      "sensor.wz_h": { state: "48", attributes: { device_class: "humidity" } }
    }"""
    room = ('{ name: "WZ", climate: ["climate.wz"], temps: [],'
            ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }')
    b = _readings(room, states)
    assert b[0]["entity"] == "climate.wz"
    assert b[0]["state_content"] == "current_temperature"


def test_an_older_ga_heating_without_the_attribute_still_gets_a_badge():
    """The attribute is not guaranteed; a device one release behind must not lose
    its temperature badge over it."""
    b = _readings('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', _STATES)
    assert b[0]["entity"] == "climate.wz"
    assert b[0]["icon"] == "mdi:thermometer"


def test_every_graph_card_styles_away_HAs_history_chevron():
    """A graph card with a `title` gets a header, and inside it a chevron linking
    to the History panel filtered to those entities: `hui-history-graph-card`
    renders that `<a>` whenever a title exists, with no way to turn it off. It is
    a one-way door from a resident's room view into an admin-shaped page.

    The title belongs on the card, so the LINK is what goes. card-mod is already
    injected on every GA dashboard for exactly this class of problem.
    """
    cards = run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_SOURCED} }};
      return roomSections({_ROOM_SRC}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => c.type === "statistics-graph")
        .map(c => {{
          const st = (c.card_mod || {{}}).style || {{}};
          const nested = (st["statistics-chart$"] || {{}})["ha-chart-base$"] || "";
          return [c.title, st["."] || "", nested];
        }});
    }})()""")
    assert cards, "no graph built — the test would be vacuous"
    for title, style, legend in cards:
        assert title, "the title belongs on the card"
        assert "a { display: none; }" in style, (
            f"{title!r} would show HA's history chevron"
        )
        # that header is an <h1>, styled for a page title; it sits under two
        # headings on a room view and must not shout over them
        assert "font-size: 16px" in style, f"{title!r} keeps HA's page-title size"
        # THE LEGEND SWATCH, and the PATH TO IT. The card renders
        # <statistics-chart>, which renders <ha-chart-base>, which draws the
        # legend — three roots. The first attempt stopped at `ha-chart-base$`
        # from the card and silently did nothing, because card-mod drops a
        # selector that matches nothing: a wrong path and a working one that
        # had no effect look identical on screen. So the NESTED key is what is
        # asserted here, not merely that the CSS exists somewhere.
        assert "background: currentColor" in legend, (
            f"{title!r}: the legend CSS is not under "
            '"statistics-chart$" -> "ha-chart-base$", so it reaches nothing'
        )
        # A hidden series must stay tellable from a shown one: the swatch is
        # the button that toggles its curve, and HA draws that state as an
        # outline we leave alone.
        assert "li.hidden" in legend, f"{title!r} hides nothing visibly"


# ── the outdoor series (2026-10-02) ─────────────────────────────────────────


_OUT_STATES = """{
  "climate.wz": { state: "auto", attributes: { current_temperature: 19.5, temperature: 21,
                  valves: [], temperature_source: "sensor.wz_t" } },
  "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "48", attributes: { device_class: "humidity" } },
  "sensor.aussentemperatur": { state: "17.7", attributes: {} },
  "sensor.aussenluftfeuchtigkeit": { state: "72", attributes: {} }
}"""

_OUT_ROOM = ('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
             ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }')


def _graph_series(cfg: str):
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_OUT_STATES} }};
      return roomSections({_OUT_ROOM}, gaOptions({cfg}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => c.type === "statistics-graph")
        .map(c => c.entities.map(e => e.name || e));
    }})()"""
    return run_js(STRATEGY, expr)


def test_a_named_outdoor_entity_is_drawn_beside_the_rooms_own():
    """Two series answer "is it cold outside or is the heating failing", which
    one series cannot."""
    got = _graph_series('{ outdoor_temperature: "sensor.aussentemperatur",'
                        ' outdoor_humidity: "sensor.aussenluftfeuchtigkeit" }')
    assert got[0] == ["Raum Temperatur", "Außentemperatur"]
    assert got[1] == ["Raum Luftfeuchtigkeit", "Außenluftfeuchtigkeit"]


def test_without_the_option_the_provisioned_sensors_are_drawn():
    """REVERSED on 2026-10-27, and deliberately: this used to assert that no
    option meant no curve, which made the feature reach one device in the fleet,
    because nothing writes the ga-home dashboard.

    ga_manager 0.263.0 provisions `sensor.aussentemperatur` /
    `sensor.aussenluftfeuchtigkeit` (greenautarky/ga_manager#371) and the
    strategy now defaults to them.
    """
    got = _graph_series("{}")
    assert got[0] == ["Raum Temperatur", "Außentemperatur"]
    assert got[1] == ["Raum Luftfeuchtigkeit", "Außenluftfeuchtigkeit"]


def test_the_default_is_still_not_a_guess():
    """WHAT THE REVERSED TEST ABOVE USED TO PROVE, kept, because it is the thing
    that could quietly go wrong.

    Defaulting names two ids another repo commits to writing. SNIFFING would
    match `sensor.aussen*` — it breaks the day somebody renames a sensor, and on
    a device with several weather sources it draws a stranger's thermometer on a
    resident's wall. A sensor that merely LOOKS like an outdoor one must be
    ignored."""
    states = _OUT_STATES.replace("sensor.aussentemperatur", "sensor.aussen_garten")
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      return roomSections({_OUT_ROOM}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => c.type === "statistics-graph")
        .map(c => c.entities.map(e => e.name || e));
    }})()"""
    got = run_js(STRATEGY, expr)
    assert got[0] == ["Raum Temperatur"], got


def test_a_dashboard_can_still_say_no():
    """`false` turns it off, for a dashboard that does not want the sensor. The
    point of a default is that it is overridable in both directions."""
    got = _graph_series("{ outdoor_temperature: false, outdoor_humidity: false }")
    assert got[0] == ["Raum Temperatur"]
    assert got[1] == ["Raum Luftfeuchtigkeit"]


def test_a_named_entity_that_does_not_exist_is_not_charted():
    """A typo or a deleted sensor must leave one honest curve, not an empty
    legend entry."""
    got = _graph_series('{ outdoor_temperature: "sensor.tippfehler" }')
    assert got[0] == ["Raum Temperatur"]


# ── the heading names the room, and the badges are labelled ────────────────
#
# Asked for 2026-10-08. "Heizung" was the same word in every room; the name is
# what tells one view from another. And the two readings had no label at all, so
# "Aktuell" joins them as a badge rather than as a second copy of the numbers
# inside the thermostat card — which is where it went first, and was wrong.


def _heading(room: str, states: str = "{}"):
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      return roomSections({room}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .find(c => c.type === "heading") || null;
    }})()"""
    return run_js(STRATEGY, expr)


_ROOM = ('{ name: "Wohnzimmer", area_id: "wohnzimmer", climate: ["climate.wz"],'
         ' temps: ["sensor.wz_t"], hums: ["sensor.wz_h"], batts: [],'
         ' lights: [], switches: [] }')


def test_the_heading_carries_no_title_any_more():
    """The room name moved INTO the thermostat card on 2026-10-21, where it
    took the place the running state had. A heading repeating it would be the
    third telling of one word on one screen — the tab says it too."""
    assert _heading(_ROOM, _STATES)["heading"] == ""


def test_the_room_name_is_on_the_thermostat_card_instead():
    """Where it went, asserted here so the two halves cannot drift apart: a
    heading that lost its title and a card that never gained one would leave
    the room unnamed on its own view."""
    cards = run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_STATES} }};
      return roomSections({_ROOM}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => String(c.type).includes("thermostat"))
        .map(c => c.header);
    }})()""")
    assert cards and all(h == "Wohnzimmer" for h in cards), cards


def test_the_heading_carries_no_icon():
    """A room name is already specific; an icon beside it decorates rather than
    distinguishes, and a room named after a person cannot be given a true one."""
    assert "icon" not in _heading(_ROOM, _STATES), _heading(_ROOM, _STATES)


def test_a_room_with_no_name_falls_back_to_its_area_id_on_the_CARD():
    """MUST-NOT-FLAG: the area id is a poor name but an unnamed room is worse,
    and the fallback moved to the card with the name."""
    room = _ROOM.replace('name: "Wohnzimmer"', 'name: ""')
    got = run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_STATES} }};
      return roomSections({room}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => String(c.type).includes("thermostat"))
        .map(c => c.header);
    }})()""")
    assert got == ["wohnzimmer"], got


def test_aktuell_labels_the_readings_and_comes_first():
    b = _badges(_ROOM, _STATES)
    assert [x["name"] for x in b] == ["Aktuell", "Temperatur", "Luftfeuchtigkeit"], b
    # AN ICON, NO TEXT (2026-10-23). `show_state: false` is what drops the word;
    # `show_icon` is stated beside it rather than left to its default, because a
    # badge with neither renders as nothing at all. Without one of the two this
    # badge would print a VALUE — the hvac mode — where the label belongs.
    assert b[0]["show_state"] is False, "without this the badge shows a value"
    assert b[0]["show_icon"] is True, "an icon-only badge needs its icon"
    assert "state_content" not in b[0], "it has no text to choose the content of"
    assert b[0]["icon"] == "mdi:home-import-outline"
    assert b[0]["entity"] == "climate.wz"
    # The word survives as the badge's `title`: unprinted, not gone.
    assert b[0]["name"] == "Aktuell"


def test_the_label_is_dropped_when_there_is_no_room_entity():
    """It is bound to the climate entity the other badges report on.

    A room with no climate entity builds no heating section at all — the first
    heading it has is "Verlauf", which carries no badges — so the question is not
    "what is in the badge row" but "does anything anywhere claim to show this
    room's current readings". Asked that way it does not depend on which heading
    happens to come first (CI, 2026-10-08)."""
    room = _ROOM.replace('climate: ["climate.wz"]', "climate: []")
    names = run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_STATES} }};
      return roomSections({room}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => c.type === "heading")
        .flatMap(h => (h.badges || []).map(b => b.name));
    }})()""")
    assert "Aktuell" not in names, names


# ── the outdoor curve is told apart by COLOUR (2026-10-21) ─────────────────
# "check what possibilities do we have to differetiate the ausser temp using
# the same card type from ha that we originally have".
#
# Read off HA 2026.8.2.1's own editor schema: per card it takes chart_type,
# days_to_show, period, unit, stat_types, title, hide_legend, expand_legend,
# min/max_y_axis, fit_y_data, logarithmic_scale; per ENTITY it takes entity,
# name and COLOR. There is no per-series line style and no way to reach one —
# the card's chunk carries no `lineStyle` and the chart is a canvas, where no
# CSS can dash a line. So colour is the lever, and these pin it.


def _graph_colors(cfg: str):
    expr = f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_OUT_STATES} }};
      return roomSections({_OUT_ROOM}, gaOptions({cfg}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => c.type === "statistics-graph")
        .map(c => c.entities.map(e => [e.name || e.entity, e.color]));
    }})()"""
    return run_js(STRATEGY, expr)


_BOTH = ('{ outdoor_temperature: "sensor.aussentemperatur",'
         ' outdoor_humidity: "sensor.aussenluftfeuchtigkeit" }')


def test_the_outdoor_curve_carries_its_own_colour():
    for chart in _graph_colors(_BOTH):
        assert chart[-1][1] == "deep-orange", chart


def test_the_rooms_curve_is_never_the_outdoor_colour():
    """Left to itself the card colours by POSITION, so the room's own curve
    could land on whatever the outdoor one has."""
    for chart in _graph_colors(_BOTH):
        for name, color in chart[:-1]:
            assert color != "deep-orange", (name, color)


def test_the_colour_belongs_to_the_entity_not_its_position():
    """THE RULE. A room that gains a second thermometer must not hand the
    outdoor curve a new colour — "the orange one is outside" has to hold in
    every room and after every change."""
    one = _graph_colors(_BOTH)
    assert one[0][0][1] == "blue", one[0]
    assert one[0][-1][1] == "deep-orange", one[0]


def test_a_second_thermometer_gets_a_colour_safe_against_both_others():
    """MEASURED, not picked. The second room colour was teal until 2026-10-21:
    fine for protan/deutan at ΔE 11.9, but 7.0 under tritan — below the ≥8
    target. Deep-purple holds 17.3 CVD and 24.0 tritan against both blue and
    deep-orange, on all pairs, on both card surfaces."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'const ROOM_COLORS = ["blue", "deep-purple"' in src, (
        "the second room curve must be the colour that survives tritanopia")


def test_the_outdoor_colour_is_not_a_status_colour():
    """Red clears every measurable gate and is still wrong: on a heating
    dashboard red reads as a fault, and the weather outside is not one."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'const OUTDOOR_COLOR = "deep-orange"' in src


def test_a_chart_without_an_outdoor_entity_still_colours_the_room():
    for chart in _graph_colors("{}"):
        assert all(c for _, c in chart), chart


# ── a room with no hygrometer draws the house mean (2026-10-27) ────────────
# "in the rooms that dont have t&h sensor add a mean of other humidity similar to
# whats done for temperature".
#
# The asymmetry this fixes: a sensorless room already draws a TEMPERATURE curve,
# because its valve measures one. A TRV does not measure humidity, so that room
# had a blank where the second chart belongs — while its badge showed the house
# figure, which made the gap read as a fault rather than a missing sensor.

_HOUSE_HUM = "sensor.ga_luftfeuchtigkeit_haus"

_WC_STATES = """{
  "climate.wc": { state: "auto", attributes: { current_temperature: 21, valves: [],
                  temperature_source: "sensor.wz_t", %s } },
  "sensor.wz_t": { state: "21", attributes: { device_class: "temperature" } },
  "%s": { state: "47.5", attributes: { device_class: "humidity" } }
}"""

_WC_ROOM = ('{ name: "WC", climate: ["climate.wc"], temps: ["sensor.wz_t"],'
            ' hums: [], batts: [], lights: [], switches: [] }')


def _charts(room, states):
    return json.loads(run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      return JSON.stringify(roomSections({room}, gaOptions({{}}), hass)
        .flatMap(s => s.cards || [])
        .filter(c => c.type === "statistics-graph")
        .map(c => c.title + " :: " + c.entities.map(e => e.name || e.entity).join(", ")));
    }})()"""))


def test_a_room_with_no_hygrometer_draws_the_house_mean():
    states = _WC_STATES % (f'house_humidity_entity: "{_HOUSE_HUM}"', _HOUSE_HUM)
    out = _charts(_WC_ROOM, states)
    assert "Luftfeuchtigkeit letzte 24h :: Ø Luftfeuchtigkeit (Haus)" in out, out


def test_an_engine_that_names_no_mean_leaves_the_room_as_it_was():
    """A device still on the older ga_heating publishes no `house_humidity_entity`,
    and there the room keeps its blank rather than guessing an entity_id."""
    out = _charts(_WC_ROOM, _WC_STATES % ("", _HOUSE_HUM))
    assert not any("Luftfeuchtigkeit" in c for c in out), out


def test_a_named_mean_that_does_not_resolve_draws_nothing():
    """Same rule as the outdoor series: a name in a config that no longer exists
    must leave the room with one honest chart, not an empty legend."""
    states = _WC_STATES % ('house_humidity_entity: "sensor.gone"', _HOUSE_HUM)
    assert not any("Luftfeuchtigkeit" in c for c in _charts(_WC_ROOM, states)), states


def test_a_room_with_its_own_hygrometer_is_untouched():
    """MUST-NOT-FLAG. The mean is a fallback, never a replacement — a room that
    measures its own humidity must keep drawing its own."""
    room = ('{ name: "WZ", climate: ["climate.wc"], temps: ["sensor.wz_t"],'
            ' hums: ["sensor.wz_h"], batts: [], lights: [], switches: [] }')
    states = (_WC_STATES % (f'house_humidity_entity: "{_HOUSE_HUM}"', _HOUSE_HUM)
              ).replace('"sensor.wz_t": {', '"sensor.wz_h": { state: "48",'
                        ' attributes: { device_class: "humidity" } },\n  "sensor.wz_t": {')
    out = _charts(room, states)
    assert "Luftfeuchtigkeit letzte 24h :: Raum Luftfeuchtigkeit" in out, out


# ── the two groups (2026-10-21, reordered and un-worded 2026-10-23) ─────────
# "i need to show the current outdoor temperature as well", then "add aussen
# like we have aktuell before it. also add outdoor humidity", then "instead
# aussen and aktuell can we just place an icon that indicates aussen and raum or
# indoor. then place the indoor data first in the line".
#
# The row is two groups of the same shape, an ICON then its numbers, the room
# first:
#
#     [house] 21,5 °C 49 %            [sun] 12,3 °C 79 %
#
# split left/right by one card_mod rule, because HA pins every badge right.


_OUT_CFG = ('{ outdoor_temperature: "sensor.aussentemperatur",'
            ' outdoor_humidity: "sensor.aussenluftfeuchtigkeit" }')

_OUT_STATES2 = """{
  "climate.wz": { state: "auto", attributes: { current_temperature: 21.5,
                  current_humidity: 49, temperature: 21, valves: [],
                  temperature_source: "sensor.wz_t" } },
  "sensor.wz_t": { state: "21.5", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "49", attributes: { device_class: "humidity" } },
  "sensor.aussentemperatur": { state: "12.3", attributes: { device_class: "temperature" } },
  "sensor.aussenluftfeuchtigkeit": { state: "79", attributes: { device_class: "humidity" } }
}"""


_NO_HUMIDITY_STATES = """{
  "climate.wz": { state: "auto", attributes: { current_temperature: 21.5,
                  temperature: 21, valves: [],
                  temperature_source: "sensor.wz_t" } },
  "sensor.wz_t": { state: "21.5", attributes: { device_class: "temperature" } },
  "sensor.aussentemperatur": { state: "12.3", attributes: { device_class: "temperature" } },
  "sensor.aussenluftfeuchtigkeit": { state: "79", attributes: { device_class: "humidity" } }
}"""


#: A room with NO humidity anywhere — no hygrometer of its own, and a climate
#: entity that reports none either. SPELLED OUT rather than reusing `_ROOM`:
#: that name is bound TWICE in this file, and the later binding — a room that
#: DOES have a hygrometer — is the one every helper down here actually gets.
#: A fixture built by deleting `current_humidity` from the states therefore
#: changed nothing at all, because the badge was coming from `hums[0]`.
_ROOM_NO_HUM = ('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: [], batts: [], lights: [], switches: [] }')


def _head(cfg: str, states: str = _OUT_STATES2, room: str | None = None):
    return json.loads(run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {states} }};
      const h = roomSections({room or _ROOM}, gaOptions({cfg}), hass)
        .flatMap(s => s.cards || []).find(c => c.type === "heading");
      return JSON.stringify({{ names: h.badges.map(b => b.name),
        labels: h.badges.filter(b => b.show_state === false).map(b => b.name),
        style: (h.card_mod || {{}}).style || "" }});
    }})()"""))


def test_the_rooms_own_readings_come_first_and_outside_follows():
    """"place the indoor data first in the line" (2026-10-23). It was the other
    way round for two days: outside opened the row, which put the number a
    resident came to read second."""
    got = _head(_OUT_CFG)
    assert got["names"] == ["Aktuell", "Temperatur", "Luftfeuchtigkeit",
                            "Außen", "Temperatur", "Luftfeuchtigkeit"], got


def test_both_groups_open_with_an_icon_and_no_number():
    """Each group is opened by a badge that prints no state at all — the icon is
    the whole label now. Without it the row would read as four numbers with
    nothing saying which two are outside.

    The order is the groups' order: the house first, the sun after it."""
    assert _head(_OUT_CFG)["labels"] == ["Aktuell", "Außen"], _head(_OUT_CFG)


def test_the_split_follows_the_size_of_the_rooms_own_group():
    """HA pins every badge right, so one rule pushes the row apart: the LAST
    badge of the room's group takes `margin-right: auto`. The index is counted,
    never assumed — a room without a hygrometer has one reading and not two, and
    a hard-coded index would push the wrong badge.

    It no longer follows the OUTDOOR group, which is what it counted while
    outside came first."""
    # Aktuell + temperature + humidity.
    assert "nth-child(3)" in _head(_OUT_CFG)["style"]
    # Aktuell + temperature: this room reports no humidity anywhere, so the
    # group is one badge shorter and the split has to move with it.
    shorter = _head(_OUT_CFG, _NO_HUMIDITY_STATES, _ROOM_NO_HUM)
    assert shorter["names"] == ["Aktuell", "Temperatur",
                                "Außen", "Temperatur", "Luftfeuchtigkeit"], shorter
    assert "nth-child(2)" in shorter["style"], shorter


def test_the_split_does_not_follow_the_outdoor_group_any_more():
    """Must-not-flag, and the bug this would be: the outdoor group's size and
    the room's are both 3 in the fixture above, so a rule still counting the
    wrong one would pass it. A room configured with outdoor temperature ALONE
    has a 2-badge outdoor group and a 3-badge room group, and only one of those
    is the right answer."""
    style = _head('{ outdoor_temperature: "sensor.aussentemperatur" }')["style"]
    assert "nth-child(3)" in style, style


def test_no_outdoor_entities_means_no_group_and_no_rule():
    """MUST-NOT-FLAG. With nothing to push right, the rule would strand the
    room's own readings on the left, away from the edge they belong on.

    Asked with the sensors OPTED OUT rather than merely unconfigured: since
    2026-10-27 "unconfigured" means the provisioned pair, so the no-group case
    has to be reached deliberately. A device whose converge has not written them
    yet reaches it the other way, by the entities not resolving — which is the
    test below."""
    got = _head("{ outdoor_temperature: false, outdoor_humidity: false }")
    assert got["names"] == ["Aktuell", "Temperatur", "Luftfeuchtigkeit"], got
    assert got["style"] == "", got


def test_an_outdoor_entity_that_does_not_exist_is_left_out():
    """A name in a config that no longer resolves must leave the row with the
    room's own readings rather than a badge reading "unknown"."""
    got = _head('{ outdoor_temperature: "sensor.gone", outdoor_humidity: "sensor.also_gone" }')
    assert got["names"] == ["Aktuell", "Temperatur", "Luftfeuchtigkeit"], got
    assert got["style"] == "", got


def test_the_two_groups_differ_only_by_their_label_icon():
    """The readings ARE the same two measurements, so they take the same
    thermometer and droplet; the sun against the house is what says which side
    of the wall they were taken on."""
    icons = json.loads(run_js(STRATEGY, f"""(() => {{
      const hass = {{ config: {{ components: ["history"] }}, states: {_OUT_STATES2} }};
      const h = roomSections({_ROOM}, gaOptions({_OUT_CFG}), hass)
        .flatMap(s => s.cards || []).find(c => c.type === "heading");
      return JSON.stringify(h.badges.map(b => b.icon || null));
    }})()"""))
    # IN AND OUT, as a pair of arrows through a wall (2026-10-27). The two
    # thermometer glyphs they replaced each carried a second thermometer, right
    # beside the thermometer badge they label.
    assert icons[0] == "mdi:home-import-outline", icons
    assert icons[3] == "mdi:home-export-outline", icons
    assert icons[1] == icons[4] == "mdi:thermometer", icons
