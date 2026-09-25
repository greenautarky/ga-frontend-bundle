"""The room's measured temperature is back as a heading badge (2026-09-25).

Thomas asked on 2026-09-25 for the measured room temperature to be shown again
"da wo auch die Luftfeuchtigkeit angezeigt wird" — the badges of the room view's
"Heizung" heading. This reverses, FOR THE BADGE ONLY, the Odoo #1060 decision of
2026-09-23 that had dropped it. The thermostat card stays setpoint-only
(tests/test_thermostat_target_only.py still pins that).

Source: `room.temps[0]`. The model from greenautarky_site does not distinguish a
dedicated room sensor from a valve's own thermometer — `temps` is every
temperature sensor in the area — so the first one is used. Without any
temperature sensor the badge falls back to the room thermostat's
`current_temperature` attribute (a heading entity badge with `state_content`),
and only when that attribute actually carries a number. Otherwise: no badge,
never a null one.

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
                  "state_content": "current_temperature"}], b


def test_a_room_climate_entity_wins_over_temps():
    """ga_heating's room entity decides (room sensor first, valve fallback), so
    its current_temperature (19.5) must beat temps[0] (20.1)."""
    b = _badges('{ name: "WZ", climate: ["climate.wz"], temps: ["sensor.wz_t"],'
                ' hums: [], batts: [], lights: [], switches: [] }', _STATES)
    assert b[0] == {"type": "entity", "entity": "climate.wz", "name": "Temperatur",
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
    assert b == [{"type": "entity", "entity": "sensor.wz_t", "name": "Temperatur"}], b
