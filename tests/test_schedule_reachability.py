"""Can this slot actually be reached, and when does pre-heating start?

A plan can ask for something the room cannot do. Six degrees by 06:00 is a wish
if the previous slot ends at 05:00 and the room climbs a degree every two hours,
and nothing on the schedule screen said so -- the resident found out by being
cold (asked for 2026-11-19).

THE NUMBER THIS RESTS ON IS THE DANGEROUS PART. The rate the stack would
otherwise reach for is `heating_rate()` in the hmvapp add-on, which is a 0.5 h/K
DEFAULT for all but eight rooms on the fleet while the measured reality is nearer
2.2. A card built on that tells a resident "comfortably" about a room needing
four times longer. So these tests are mostly about what the card must NOT do:

  * never compute from a rate the room has not measured -- say "unknown"
  * never disagree with the thing that actually pre-heats
  * never annotate a slot that is not a heat-up

These run the SHIPPED bytes in a VM (tests/js/eval.mjs), not a copy of the logic.
"""

from __future__ import annotations

import json

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-card" / "ga-heating-card.js"


def reach(slots, i, rate):
    """`reachability()` on the shipped bytes; None comes back as JSON null."""
    r = "null" if rate is None else repr(rate)
    return json.loads(run_js(
        CARD, f"JSON.stringify(reachability({json.dumps(slots)}, {i}, {r}))"
    ))


def html(slots, i, rate, samples=7, provisional=False):
    """`reachHtml` takes `{value, provisional}` — a measured rate or a stand-in."""
    flag = "true" if provisional else "false"
    r = "null" if rate is None else f"{{value: {rate!r}, provisional: {flag}}}"
    return run_js(
        CARD, f"reachHtml({json.dumps(slots)}, {i}, {r}, {samples})"
    )


#: 18 °C overnight, 21 °C from 06:00 — the ordinary morning heat-up.
MORNING = [{"time": "00:00", "temp": 18.0}, {"time": "06:00", "temp": 21.0}]


# ── which slots get a note at all ───────────────────────────────────────────


def test_a_slot_that_holds_or_drops_says_nothing():
    """Only a rise has a pre-heat to plan. Annotating the 22:00 drop would be
    noise on every row of every plan.

    THE RATE-LESS CASE IS THE ONE THAT MATTERS. With a rate, the noise floor
    below would swallow a drop anyway (a negative need is never >= 10 min), so
    this guard looks redundant until a room has not measured yet -- and then it
    is the only thing between a resident and "Aufheizdauer noch unbekannt"
    printed against every falling slot in the week.
    """
    drop = [{"time": "06:00", "temp": 21.0}, {"time": "22:00", "temp": 17.0}]
    hold = [{"time": "06:00", "temp": 21.0}, {"time": "12:00", "temp": 21.0}]
    for rate in (2.0, None):
        assert reach(drop, 1, rate) is None, rate
        assert reach(hold, 1, rate) is None, rate


def test_a_rise_too_small_to_matter_is_not_annotated():
    """Under a quarter hour of pre-heating the plan is comfortable. The floor is
    about significance, not resolution — it stays at 15 while times are shown to
    five. 0.1 K needs 2 minutes; 0.2 K needs 14, still under it."""
    assert reach([{"time": "00:00", "temp": 18.0},
                  {"time": "06:00", "temp": 18.2}], 1, 2.0) is None
    assert reach([{"time": "00:00", "temp": 18.0},
                  {"time": "06:00", "temp": 18.3}], 1, 2.0) is None


def test_the_suggested_time_is_one_the_resident_can_actually_set():
    """THE RED ONE for usability. Slots snap to `SNAP_MINUTES` (30) and the time
    input ships `step=1800`, so a suggestion of 12:45 names a time the form will
    not take. The earliest-workable time rounds up onto that grid."""
    snap = int(run_js(CARD, "String(SNAP_MINUTES)"))
    r = reach([{"time": "05:00", "temp": 17.0},
               {"time": "06:00", "temp": 21.0}], 1, 2.0)
    hh, mm = r["earliest"].split(":")
    assert (int(hh) * 60 + int(mm)) % snap == 0, r["earliest"]


def test_the_two_roundings_both_err_away_from_a_broken_promise():
    """THE RED ONE for direction. A pre-heat start rounds DOWN: starting a
    quarter hour early costs a little heat, starting late misses the slot. An
    earliest-workable time rounds UP: it is a minimum, so rounding it down names
    a time that still does not work."""
    ok = reach(MORNING, 1, 2.0)                      # true start 00:22
    assert ok["preheat"] == "00:20"
    assert ok["need"] == 338.0, "the underlying maths is NOT rounded"

    tight = reach([{"time": "05:00", "temp": 17.0},
                   {"time": "06:00", "temp": 21.0}], 1, 2.0)   # true 12:38
    assert tight["earliest"] == "13:00"


# ── the arithmetic, which must be hmvapp's ──────────────────────────────────


def test_a_rising_slot_says_when_pre_heating_starts():
    r = reach(MORNING, 1, 2.0)
    assert r["kind"] == "ok"
    assert r["preheat"] == "00:20", "00:22, rounded down to five minutes"


def test_the_arithmetic_is_the_one_that_actually_pre_heats():
    """THE RED ONE for agreement. hmvapp computes
    `(target - current - 0.1) * rate` and then adds 10 minutes back in
    `latest_start_time`. Both are quirks of that code; a card that tidied them
    away would print a time the device does not act on.

    18 -> 21 at 2 h/K: (3 - 0.1) * 2 h = 5.8 h, less 10 min = 5 h 38, so
    pre-heating starts at 00:22 for an 06:00 slot.
    """
    assert reach(MORNING, 1, 2.0)["need"] == 338.0


def test_a_faster_room_starts_later():
    """The whole point of a per-room rate: the same plan is comfortable in one
    room and impossible in another."""
    assert reach(MORNING, 1, 1.0)["preheat"] == "03:15"
    assert reach(MORNING, 1, 2.0)["preheat"] == "00:20"


# ── too tight ───────────────────────────────────────────────────────────────


def test_too_tight_warns_and_names_the_earliest_time_that_works():
    """17 -> 21 in the hour between 05:00 and 06:00, at 2 h/K, needs 7 h 38.
    Pre-heating cannot begin before 05:00 -- until then the room is held lower
    still -- so the earliest this target is reachable is 12:38."""
    r = reach([{"time": "05:00", "temp": 17.0},
               {"time": "06:00", "temp": 21.0}], 1, 2.0)
    assert r["kind"] == "tight"
    assert r["earliest"] == "13:00", "12:38 up onto the 30-minute slot grid"


def test_the_first_slot_of_the_day_is_measured_from_the_last_one():
    """Midnight wraps: the slot before 00:00 is the end of the same day, which
    is how `tempAt` and the curve already read a plan."""
    r = reach([{"time": "00:00", "temp": 21.0},
               {"time": "22:00", "temp": 17.0}], 0, 2.0)
    assert r["kind"] == "tight", "two hours is not enough for four degrees"


# ── and what it must not do without a rate ──────────────────────────────────


def test_without_a_measured_rate_it_says_so_instead_of_guessing():
    """MUST-NOT-FLAG, and the reason the whole feature was built this way: a
    confident wrong time is worse than an honest blank. The fleet default this
    would otherwise borrow is optimistic by about four times."""
    r = reach(MORNING, 1, None)
    assert r == {"kind": "unknown"}

    markup = html(MORNING, 1, None)
    assert "unbekannt" in markup
    assert ":" not in markup.split("title=")[0].split(">")[-1], markup


def test_a_rate_of_zero_or_nonsense_is_the_same_as_none():
    for bad in (0, -1):
        assert reach(MORNING, 1, bad) == {"kind": "unknown"}


def test_a_room_that_has_measured_its_own_rate_uses_it():
    out = json.loads(run_js(CARD, """JSON.stringify((() => {
      const c = Object.create(GaHeatingCard.prototype);
      c._config = { entity: 'climate.x' };
      c._hass = { states: { 'climate.x': { attributes: { valves: ['climate.v'],
        heating_rate: { hours_per_degree: 2.2, samples: 9 } } } } };
      return [c._rate(), c._rateSamples()]; })())"""))
    assert out[0] == {"value": 2.2, "provisional": False}
    assert out[1] == 9


@pytest.mark.parametrize("published", ["0", "-1", "null", '"fast"'])
def test_a_nonsense_published_rate_is_not_a_measurement(published):
    """A room publishing 0 h/K would otherwise read as infinitely fast and every
    slot as comfortable — the direction of error that matters here."""
    out = json.loads(run_js(CARD, """JSON.stringify((() => {
      const c = Object.create(GaHeatingCard.prototype);
      c._config = { entity: 'climate.x' };
      c._hass = { states: { 'climate.x': { attributes: { valves: [],
        heating_rate: { hours_per_degree: __V__, samples: 4 } } } } };
      return c._rate(); })())""".replace("__V__", published)))
    assert out["provisional"] is True, published


def test_a_room_still_learning_borrows_the_rooms_next_door():
    """Rates do not generalise ACROSS flats — one Potsdam flat measured about
    twice as slow as everywhere else — but rooms inside one home share a boiler,
    a flow temperature and a building. The median of the siblings that HAVE
    measured is the best stand-in available."""
    out = json.loads(run_js(CARD, """JSON.stringify((() => {
      const room = (hpd) => ({ attributes: { valves: ['climate.v'],
        heating_rate: { hours_per_degree: hpd, samples: hpd ? 5 : 0 } } });
      const c = Object.create(GaHeatingCard.prototype);
      c._config = { entity: 'climate.x' };
      c._hass = { states: {
        'climate.x': room(null),
        'climate.a': room(1.8), 'climate.b': room(3.0), 'climate.c': room(2.4),
        'climate.v': { attributes: { current_temperature: 20 } },  // a raw TRV
      } };
      return c._rate(); })())"""))
    assert out == {"value": 2.4, "provisional": True}, "median of 1.8, 2.4, 3.0"


def test_a_flat_where_nothing_has_learned_falls_back_to_the_constant():
    out = json.loads(run_js(CARD, """JSON.stringify((() => {
      const c = Object.create(GaHeatingCard.prototype);
      c._config = { entity: 'climate.x' };
      c._hass = { states: { 'climate.x': { attributes: { valves: [] } } } };
      return c._rate(); })())"""))
    assert out["provisional"] is True
    assert out["value"] >= 2.0


def test_the_stand_in_never_drifts_back_to_the_optimistic_default():
    """THE RED ONE for the direction of error. 0.5 h/K is what the hmvapp add-on
    falls back to and it is optimistic by about four times: on it, a slot that
    cannot be reached reads as comfortable. A provisional number has to fail
    towards "zu knapp" — a false warning can be looked at, false comfort is
    found out about by being cold."""
    value = float(run_js(CARD, "String(FLEET_HOURS_PER_K)"))
    assert value >= 2.0, "at or above the measured fleet reality, never 0.5"


def test_a_provisional_note_says_so_on_its_face():
    """A caveat only in a tooltip is a caveat nobody reads."""
    prov = html(MORNING, 1, 2.0, provisional=True)
    assert "wird noch gelernt" in prov
    assert "geschätzt" in prov

    measured = html(MORNING, 1, 2.0)
    assert "wird noch gelernt" not in measured
    assert "Gemessen an 7" in measured


def test_every_time_is_presented_as_approximate():
    """Quarter hours and "ca." on both states and both kinds of rate. The rate
    is a median over a handful of heat-ups and the starting point is the plan's
    value rather than the room's, so a to-the-minute time claims a precision
    none of it has."""
    assert "ab ca. 00:20 vorheizen" in html(MORNING, 1, 2.0)
    assert "ab ca. 00:20 vorheizen" in html(MORNING, 1, 2.0, provisional=True)
    tight = html([{"time": "05:00", "temp": 17.0},
                  {"time": "06:00", "temp": 21.0}], 1, 2.0)
    assert "frühestens ca. 13:00" in tight


# ── the seam the resident actually reads ────────────────────────────────────


def test_only_the_tight_slot_is_coloured():
    """A plan that is fine should look calm. Colour is reserved for the one
    state somebody has to act on."""
    assert 'class="reach ok"' in html(MORNING, 1, 2.0)
    tight = html([{"time": "05:00", "temp": 17.0},
                  {"time": "06:00", "temp": 21.0}], 1, 2.0)
    assert 'class="reach tight"' in tight and "mdi:alert-outline" in tight


def test_the_note_reaches_the_rendered_row():
    """THE SEAM. Everything above calls the helpers; a note that never reaches
    the markup passes all of it and shows a resident nothing."""
    markup = run_js(CARD, """(() => {
      const seen = {};
      const stub = (name) => ({
        addEventListener() {}, querySelectorAll() { return []; },
        insertAdjacentHTML() {}, textContent: "",
        classList: { toggle() {}, add() {}, remove() {} },
        set innerHTML(v) { seen[name] = v; }, get innerHTML() { return seen[name] || ""; },
      });
      const c = Object.create(GaHeatingCard.prototype);
      c._config = { entity: 'climate.x' };
      c._day = 'monday';
      c._week = { monday: [{ time: '00:00', temp: 18 }, { time: '06:00', temp: 21 }] };
      c._saved = {};
      c._hass = { states: { 'climate.x': { attributes: {
        heating_rate: { hours_per_degree: 2.0, samples: 7 } } } } };
      c.querySelector = (sel) => stub(sel);
      c.querySelectorAll = () => [];
      c._build();
      c._render();
      return seen['.slots'] || ''; })()""")
    assert "vorheizen" in markup, markup[:400]
    assert "ca. 00:20" in markup, markup[:400]
