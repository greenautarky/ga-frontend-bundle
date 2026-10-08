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
    assert g["entities"] == [{"entity": "sensor.wz_t", "name": "Raum Temperatur"}]


def test_the_title_says_letzte_24h():
    assert _temp_graph(_ROOM, _VALVE_STATES)["title"] == "Temperatur letzte 24h"


def test_a_room_whose_only_thermometer_is_the_valve_keeps_it_unrenamed():
    """One honest curve under its own name beats an empty card — and "Raum
    Temperatur" on a sensor screwed to the radiator would contradict itself."""
    room = ('{ name: "WZ", climate: ["climate.wz"],'
            ' temps: ["sensor.0xdead_local_temperature"],'
            ' hums: [], batts: [], lights: [], switches: [] }')
    g = _temp_graph(room, _VALVE_STATES)
    assert g["entities"] == ["sensor.0xdead_local_temperature"]


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
    assert _temp_graph(room, states)["entities"] == ["sensor.wz_t", "sensor.wz_t2"]


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
    assert g["entities"] == [{"entity": "sensor.wz_h", "name": "Raum Luftfeuchtigkeit"}]
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
        .map(c => [c.title, (c.card_mod || {{}}).style || ""]);
    }})()""")
    assert cards, "no graph built — the test would be vacuous"
    for title, style in cards:
        assert title, "the title belongs on the card"
        assert "a { display: none; }" in style, (
            f"{title!r} would show HA's history chevron"
        )
        # that header is an <h1>, styled for a page title; it sits under two
        # headings on a room view and must not shout over them
        assert "font-size: 16px" in style, f"{title!r} keeps HA's page-title size"


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


def test_without_the_option_nothing_extra_is_drawn():
    """Most devices have no weather integration at all — a GA device has no
    `default_config`, so nothing adds one by itself.

    This is also the proof that the entity is NAMED and never sniffed for: the
    states above DO contain `sensor.aussentemperatur`, and with no option naming
    it the chart must still draw one curve. Guessing at `sensor.aussen*` would
    break the day somebody renames a sensor, and on a device with several weather
    sources it would draw a stranger's thermometer on a resident's wall.
    """
    got = _graph_series("{}")
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


def test_the_heading_is_the_room_name():
    assert _heading(_ROOM, _STATES)["heading"] == "Wohnzimmer"


def test_the_heading_carries_no_icon():
    """A room name is already specific; an icon beside it decorates rather than
    distinguishes, and a room named after a person cannot be given a true one."""
    assert "icon" not in _heading(_ROOM, _STATES), _heading(_ROOM, _STATES)


def test_a_room_with_no_name_still_has_a_heading():
    """MUST-NOT-FLAG: the area id is a poor title but an empty one is worse."""
    room = _ROOM.replace('name: "Wohnzimmer"', 'name: ""')
    assert _heading(room, _STATES)["heading"] == "wohnzimmer"


def test_aktuell_labels_the_readings_and_comes_first():
    b = _badges(_ROOM, _STATES)
    assert [x["name"] for x in b] == ["Aktuell", "Temperatur", "Luftfeuchtigkeit"], b
    assert b[0]["state_content"] == "name", "without this the badge shows a value"
    assert b[0]["icon"] == "mdi:home-thermometer-outline"
    assert b[0]["entity"] == "climate.wz"


def test_the_label_is_dropped_when_there_is_no_room_entity():
    """It is bound to the climate entity the other badges report on; with none
    there is nothing to label."""
    room = _ROOM.replace('climate: ["climate.wz"]', "climate: []")
    assert [x["name"] for x in _badges(room, _STATES)] != ["Aktuell"]
