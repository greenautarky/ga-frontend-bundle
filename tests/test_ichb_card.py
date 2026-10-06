"""The hydraulic-balancing controls, and the warm-room warning in front of them.

Asked for on 2026-10-06, in two parts. First the button and the backend
("did you add the hydrulic balancomg button and backend?? if niot add it"), then
the warning, after an hour was spent on a flat too warm to measure:

  "if the room temperature is quiet high ... show a mesage when abgleich is
  started that to get the best result the room most be below 21 degrees"

WHY TWO LIMITS AND NOT ONE. A warm room spoils the hour in two different ways,
and a resident can act on them differently:

  CANNOT MEASURE (26 degrees, = 30 target minus 4 K headroom). The room reaches
  the target partway through and the radiator throttles for the rest of the
  window; it contributes no rate at all. Hard limit, red.
  SHOULD NOT MEASURE (21 degrees). A radiator gives up less heat into a warm room
  than a cool one, so rates measured across warm rooms compress together and the
  differences the balance is looking for shrink into the noise. A recommendation,
  not a refusal - the run still starts.

Measured on a resident test device: three rooms just above 25 degrees against
the old 25 degree target produced no rate for any radiator.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-actions-card" / "ga-heating-actions-card.js"
THERMO = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"


def _room(name, temp, area):
    attrs = {"valves": ["climate.0x" + area], "area_id": area,
             "friendly_name": name, "max_temp": 30}
    if temp is not None:
        attrs["current_temperature"] = temp
    return {"attributes": attrs}


def _too_warm(states):
    return json.loads(run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({});"
        " c._hass = { states: " + json.dumps(states) + " };"
        " return JSON.stringify(c._tooWarmRooms()); })()",
    ))


def warm_rooms(*rooms):
    """`_tooWarmRooms()` over a flat with these (name, temperature) rooms."""
    states = {}
    for i, (name, temp) in enumerate(rooms):
        states["climate." + name.lower()] = _room(name, temp, f"a{i}")
    return _too_warm(states)


# -- which rooms are named, and under which heading --------------------------


def test_a_cool_flat_raises_nothing():
    assert warm_rooms(("Bad", 19.0), ("Buero", 20.5)) == {"blocking": [], "warm": []}


def test_a_room_over_the_ideal_is_a_recommendation_not_a_refusal():
    """21-26 degrees: the hour still runs, it is just less sharp."""
    assert warm_rooms(("Bad", 19.0), ("Kueche", 22.5)) == {
        "blocking": [], "warm": ["Kueche"]}


def test_a_room_with_no_headroom_blocks_instead():
    assert warm_rooms(("Bad", 19.0), ("Kueche", 27.0)) == {
        "blocking": ["Kueche"], "warm": []}


def test_a_blocking_room_is_not_also_listed_as_merely_warm():
    """THE RED ONE this split was written for: 27 degrees is over BOTH limits,
    and naming the same room in both halves of one sentence reads as two separate
    problems with it."""
    out = warm_rooms(("Bad", 19.0), ("Kueche", 27.0), ("Flur", 22.0))
    assert out == {"blocking": ["Kueche"], "warm": ["Flur"]}
    assert "Kueche" not in out["warm"]


def test_the_boundary_is_above_not_at():
    """A flat sitting exactly at the recommendation is not warned about - a
    warning that fires at the number it recommends cannot be acted on."""
    assert warm_rooms(("Bad", 21.0))["warm"] == []
    assert warm_rooms(("Bad", 21.1))["warm"] == ["Bad"]
    assert warm_rooms(("Bad", 26.0))["blocking"] == []
    assert warm_rooms(("Bad", 26.1))["blocking"] == ["Bad"]


def test_the_limits_are_the_target_minus_the_headroom_not_a_second_constant():
    """26 is 30 minus 4. Hardcoding it would drift the day the target moves,
    which it just did (25 -> 30)."""
    assert json.loads(run_js(
        CARD,
        "JSON.stringify([ICHB_TARGET, ICHB_MIN_HEADROOM,"
        " ICHB_MAX_ROOM_TEMP, ICHB_IDEAL_ROOM_TEMP])",
    )) == [30, 4, 26, 21]


def test_a_room_that_reports_no_temperature_is_not_guessed_at():
    """Must-not-flag: `undefined > 21` is false, but `Number(null)` is 0 and an
    empty string is 0 too - a room with no thermometer must simply not appear."""
    assert _too_warm({"climate.bad": _room("Bad", None, "bad")}) == {
        "blocking": [], "warm": []}


# -- the controls are on the card -------------------------------------------

BUILD = (
    "(() => {"
    " const c = Object.create(GaHeatingActionsCard.prototype);"
    " c.setConfig({}); c._hass = { states: {} };"
    " const stub = { addEventListener() {}, querySelector: () => null,"
    "   querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} },"
    "   removeAttribute() {}, setAttribute() {}, textContent: '', innerHTML: '',"
    "   hidden: false };"
    " c.querySelector = () => stub;"
    " c.querySelectorAll = () => [];"
    " c._build();"
    " return c.innerHTML; })()"
)


def test_the_card_offers_a_balancing_run_and_a_way_out_of_it():
    html = run_js(CARD, BUILD)
    assert "Hydraulischer Abgleich" in html
    assert "ichb-start" in html
    assert "ichb-cancel" in html


def test_the_cancel_button_starts_hidden():
    """It is only honest while a run is going; `_render` unhides it then."""
    html = run_js(CARD, BUILD)
    at = html.index("ichb-cancel")
    assert "hidden" in html[at:at + 120], html[at:at + 120]


# -- and the room card names a run it did not start -------------------------


def _row(override):
    return run_js(
        THERMO,
        "Object.create(GaThermostatCard.prototype)._overrideRow("
        '{state: "heat", attributes: '
        + json.dumps({"override": override}) + "})",
    )


RUNNING = {"active": True, "until": "2099-01-01T00:00:00+00:00"}


def test_a_running_balance_is_named_in_the_room_it_is_running_in():
    """Before this the row said nothing and the room showed a setpoint nobody in
    the flat had chosen."""
    assert "Abgleich" in _row({"ichb": dict(RUNNING)})


def test_the_room_card_offers_no_way_out_of_a_flat_wide_run():
    """Must-not-flag. `cancel_ichb` ends the hour for EVERY room - it only means
    anything if they are all measured at once - so a Beenden button inside one
    room's card would silently stop all six. It is cancelled from the Profil
    card, where the scope is stated."""
    row = _row({"ichb": dict(RUNNING)})
    assert "Beenden" not in row
    assert 'data-end="ichb"' not in row


def test_a_run_outranks_a_boost_in_the_row_as_well_as_in_the_engine():
    """ga_heating ranks window > ichb > boost, so when both records are present
    the row has to name the one actually driving the radiators."""
    row = _row({"ichb": dict(RUNNING), "boost": dict(RUNNING)})
    assert "Abgleich" in row
    if "Boost" in row:
        assert row.index("Abgleich") < row.index("Boost")


def test_a_window_still_beats_a_run():
    """An open window invalidates the measurement anyway, and the radiators are
    off - saying "Abgleich laeuft" over a cold room would be the wrong fact."""
    assert "Fenster offen" in _row({"window": {"active": True}, "ichb": dict(RUNNING)})
