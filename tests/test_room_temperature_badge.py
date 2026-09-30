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
      const h = secs.flatMap(s => s.cards || [])
        .find(c => c.type === "heading" && c.heading === "Heizung");
      return h ? h.badges : null;
    }})()"""
    return run_js(STRATEGY, expr)


_STATES = """{
  "climate.wz": { state: "heat", attributes: { current_temperature: 19.5, temperature: 21 } },
  "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } },
  "sensor.wz_h": { state: "48", attributes: { device_class: "humidity" } },
  "sensor.wz_b": { state: "80", attributes: { device_class: "battery" } }
}"""


def test_temperature_badge_comes_first_then_humidity():
    """Room with temp + humidity sensors -> badges = [Temperatur, Luftfeuchtigkeit, ...]."""
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: ["sensor.wz_h"], batts: ["sensor.wz_b"], lights: [], switches: [] }',
                _STATES)
    assert b is not None, "no Heizung heading built — the test would be vacuous"
    assert [x["name"] for x in b] == ["Temperatur", "Luftfeuchtigkeit", "Batterie"], b
    assert b[1]["entity"] == "sensor.wz_h"


def test_no_temperature_source_means_no_temperature_badge_and_no_null():
    """Room without a temperature sensor and without a usable current_temperature."""
    states = '{ "climate.wz": { state: "heat", attributes: { temperature: 21 } } }'
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: ["sensor.wz_h"],'
                ' batts: [], lights: [], switches: [] }', states)
    assert b is not None
    assert [x["name"] for x in b] == ["Luftfeuchtigkeit"], b
    for x in b:
        assert x is not None and x.get("entity"), f"empty/null badge: {x}"


def test_without_a_sensor_the_thermostat_measurement_is_the_fallback():
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', _STATES)
    assert b == [{"type": "entity", "entity": "climate.wz", "name": "Temperatur",
                  "icon": "mdi:thermometer",
                  "state_content": "current_temperature"}], b


def test_a_room_climate_entity_wins_over_temps():
    """ga_heating's room entity decides (room sensor first, valve fallback), so
    its current_temperature (19.5) must beat temps[0] (20.1)."""
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
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
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: [], batts: [], lights: [], switches: [] }', states)
    assert b == [{"type": "entity", "entity": "sensor.wz_t", "name": "Temperatur",
                  "icon": "mdi:thermometer"}], b


def test_the_temperature_badge_carries_a_thermometer_from_either_source():
    """Read off a climate entity, the badge inherits the THERMOSTAT icon — the
    dial, which is the control, not the reading. Stated on both branches, so the
    badge looks the same whichever source answers."""
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: [], hums: [],'
                ' batts: [], lights: [], switches: [] }', _STATES)
    assert b is not None, "no Heizung heading built — the test would be vacuous"
    assert b[0]["icon"] == "mdi:thermometer"

    # The sensor branch needs a climate entity to exist (the badges live on the
    # Heizung heading) but carry no numeric reading — same setup as the fallback
    # test above. A room with `climate: []` builds no heading at all, so asking
    # for its badges would test nothing.
    states = """{
      "climate.wz": { state: "heat", attributes: { temperature: 21 } },
      "sensor.wz_t": { state: "20.1", attributes: { device_class: "temperature" } }
    }"""
    b2 = _badges('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                 ' hums: [], batts: [], lights: [], switches: [] }', states)
    assert b2 is not None, "no Heizung heading built — the test would be vacuous"
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
