"""The weekly plan is never an empty form — and padding never invents a value.

The scheduler used to come back with no slots and offer "+ Zeit hinzufügen" as the
only way in: a resident opening a fresh flat saw an empty week, a blank curve, and
had to invent a plan before the card could show one. Decided 2026-09-23: exactly
five slots per day, always present.

The dangerous half is the padding. A temperature the card made up is
indistinguishable on screen from one the resident chose — and on the same day an
invented default table reached a converge step before it was caught. So these
tests are mostly about what the card must NOT do:

  * never invent a temperature: a padded slot takes the one already in force
  * never drop a slot: a day with more than five is returned untouched
  * never pad out of thin air: with nothing to derive from, the day stays empty

These run the SHIPPED bytes in a VM (tests/js/eval.mjs), not a copy of the logic.
"""

from __future__ import annotations

import json

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-card" / "ga-heating-card.js"

#: Runs the REAL `_build()` and hands back the markup it produced. `_build` also
#: wires listeners, so the DOM lookups it makes are stubbed — the markup is not.
BUILD_MARKUP = (
    "(() => {"
    " const c = Object.create(GaHeatingCard.prototype);"
    " c._config = {};"
    " const stub = { addEventListener() {}, querySelectorAll() { return []; } };"
    " c.querySelector = () => stub;"
    " c.querySelectorAll = () => [];"
    " c._build();"
    " return c.innerHTML; })()"
)


def pad(slots, fallback):
    fb = "null" if fallback is None else repr(fallback)
    return run_js(CARD, f"padDay({json.dumps(slots)}, {fb})")


def temp_at(slots, hhmm):
    return run_js(CARD, f"tempAt({json.dumps(slots)}, {json.dumps(hhmm)})")


# ── the harness reaches the real functions ───────────────────────────────────

def test_the_shipped_file_defines_both_helpers():
    assert run_js(CARD, "typeof padDay") == "function"
    assert run_js(CARD, "typeof tempAt") == "function"
    assert run_js(CARD, "SLOTS_PER_DAY") == 5


# ── tempAt: the value in force, wrapping midnight ────────────────────────────

def test_temp_at_returns_the_slot_in_force():
    day = [
        {"time": "00:00", "temp": 17},
        {"time": "09:00", "temp": 19},
        {"time": "18:00", "temp": 20},
    ]
    assert temp_at(day, "10:00") == 19
    assert temp_at(day, "23:59") == 20


def test_temp_at_wraps_midnight_from_the_last_slot():
    """Before the day's first slot the plan wraps — the same rule the curve uses."""
    day = [{"time": "06:00", "temp": 18}, {"time": "22:00", "temp": 16}]
    assert temp_at(day, "03:00") == 16


def test_temp_at_has_nothing_to_say_about_an_empty_day():
    assert temp_at([], "12:00") is None


# ── padDay: grow to five, invent nothing ─────────────────────────────────────

def test_an_empty_day_is_grown_to_five_using_the_given_fallback():
    out = pad([], 20)
    assert len(out) == 5
    assert [s["time"] for s in out] == ["00:00", "06:00", "09:00", "18:00", "22:00"]
    assert {s["temp"] for s in out} == {20}


def test_a_padded_slot_takes_the_temperature_ALREADY_IN_FORCE_not_the_fallback():
    """The whole point. 99 would be visible immediately if the fallback leaked in."""
    day = [{"time": "00:00", "temp": 17}, {"time": "09:00", "temp": 21}]
    out = pad(day, 99)
    assert len(out) == 5
    by_time = {s["time"]: s["temp"] for s in out}
    assert by_time["06:00"] == 17      # in force from 00:00
    assert by_time["18:00"] == 21      # in force from 09:00
    assert by_time["22:00"] == 21
    assert 99 not in by_time.values()


def test_padding_does_not_duplicate_a_time_the_day_already_has():
    day = [{"time": "06:00", "temp": 18}]
    out = pad(day, 20)
    assert len([s for s in out if s["time"] == "06:00"]) == 1


def test_a_day_that_already_has_five_is_returned_untouched():
    day = [{"time": t, "temp": v} for t, v in
           [("00:00", 17), ("09:00", 19), ("18:00", 20), ("22:00", 17), ("23:00", 17)]]
    assert pad(day, 99) == day


def test_a_day_with_MORE_than_five_loses_nothing():
    """Trimming would be a silent loss of the resident's plan, dressed up as tidying."""
    day = [{"time": t, "temp": 20} for t in
           ["00:00", "05:00", "09:00", "13:00", "18:00", "22:00"]]
    out = pad(day, 99)
    assert len(out) == 6
    assert [s["time"] for s in out] == [s["time"] for s in day]


def test_the_result_is_sorted_by_time():
    out = pad([{"time": "18:00", "temp": 20}], 19)
    assert [s["time"] for s in out] == sorted(s["time"] for s in out)


# ── the card no longer offers a way to add or remove a slot ──────────────────

def test_the_card_ships_no_add_or_remove_control():
    """Asserted on the markup the card BUILDS, not on the file.

    The first version of this test grepped the source and failed on the comment
    that documents the removal — a check that reads prose instead of behaviour.
    """
    markup = run_js(CARD, BUILD_MARKUP)
    assert "Zeit hinzufügen" not in markup
    assert 'class="rm"' not in markup
    # the buttons that remain are the ones a five-slot week still needs
    for kept in ("copy-week", "copy-all", "save"):
        assert kept in markup, kept


def test_the_handlers_are_deleted_rather_than_left_unreachable():
    """A method with no caller is a half-built control: wire, prove, or delete."""
    assert run_js(CARD, "typeof GaHeatingCard.prototype._add") == "undefined"
    assert run_js(CARD, "typeof GaHeatingCard.prototype._remove") == "undefined"


def test_the_five_are_announced_as_a_proposal_until_saved():
    """A padded plan must not look like a saved one — and must not arm Save."""
    src = CARD.read_text(encoding="utf-8")
    assert "Vorschlag" in src
    assert "this._padded = this._normalise();" in src
    # padding is not an edit: _dirty stays false right after it
    i = src.index("this._padded = this._normalise();")
    assert "this._dirty = false;" in src[i:i + 500]
