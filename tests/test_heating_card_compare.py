"""Editing the plan without losing sight of the plan.

Asked for on 2026-10-02: "if I change any value of the Heizplan I can't compare
to what I have currently". The card let a resident overwrite a number and then
asked them to remember it.

So every render now answers two questions at once — what the plan WILL be, and
what it IS — in three places:

  THE ROW     an edited field is marked, and carries "jetzt 18 °C": the value
              still on the thermostat, beside the one about to replace it.
  THE CURVE   the hour's current setpoint as a dashed line behind the new bar.
              "Warmer or colder than now" is the actual question, and two
              heights in one column answer it better than two numbers in a list.
  THE WEEK    Speichern writes the WHOLE week, so a line names every day that
              carries unsaved edits — the day on screen cannot answer that.

And `Verwerfen`, because showing a diff without a way back is half the job.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-card" / "ga-heating-card.js"

SAVED = [
    {"time": "06:00", "temp": 18},
    {"time": "12:00", "temp": 17},
    {"time": "18:00", "temp": 17},
    {"time": "22:00", "temp": 17},
]


def diff(now, saved=SAVED):
    return json.loads(
        run_js(CARD, f"JSON.stringify(dayDiff({json.dumps(now)}, {json.dumps(saved)}))")
    )


# ── what changed ────────────────────────────────────────────────────────────


def test_an_untouched_day_reports_nothing():
    d = diff(SAVED)
    assert d["removed"] == 0
    assert all(not r["added"] and r["time"] is None and r["temp"] is None
               for r in d["rows"])


def test_a_changed_temperature_carries_the_one_it_replaces():
    d = diff([{"time": "06:00", "temp": 21}, *SAVED[1:]])
    assert d["rows"][0]["temp"] == 18
    assert d["rows"][0]["time"] is None


def test_a_changed_time_carries_the_one_it_replaces():
    d = diff([{"time": "07:00", "temp": 18}, *SAVED[1:]])
    assert d["rows"][0]["time"] == "06:00"
    assert d["rows"][0]["temp"] is None


def test_a_row_the_saved_day_does_not_have_is_new_not_changed():
    d = diff([*SAVED, {"time": "23:00", "temp": 16}])
    assert d["rows"][-1]["added"] is True


def test_rows_that_will_disappear_are_counted():
    """Nothing else on screen would mention them — they are gone from the list
    being edited, and only Save would reveal it."""
    assert diff(SAVED[:2])["removed"] == 2


def test_a_day_is_compared_by_position_not_by_nearest_time():
    """A row whose time moved past its neighbour reports as two changes rather
    than a reorder. Correct enough, and the alternative guesses at an intent
    nobody expressed — the third row is the third row, which is how a resident
    reads them."""
    d = diff([{"time": "13:00", "temp": 18}, {"time": "06:00", "temp": 17}, *SAVED[2:]])
    assert d["rows"][0]["time"] == "06:00"
    assert d["rows"][1]["time"] == "12:00"


# ── which days are pending ──────────────────────────────────────────────────


def test_changed_days_names_every_day_with_unsaved_edits():
    week = {"monday": SAVED, "tuesday": [{"time": "06:00", "temp": 21}]}
    saved = {"monday": SAVED, "tuesday": [{"time": "06:00", "temp": 18}]}
    got = json.loads(run_js(
        CARD, f"JSON.stringify(changedDays({json.dumps(week)}, {json.dumps(saved)}))"))
    assert got == ["tuesday"]


def test_an_untouched_week_names_no_days():
    week = {"monday": SAVED}
    got = json.loads(run_js(
        CARD, f"JSON.stringify(changedDays({json.dumps(week)}, {json.dumps(week)}))"))
    assert got == []


# ── the curve carries the plan as it stands ─────────────────────────────────


def test_an_hour_that_changed_gets_the_current_setpoint_behind_it():
    html = run_js(
        CARD,
        f'curveHtml({json.dumps([{"time": "00:00", "temp": 20}])},'
        f' {json.dumps([{"time": "00:00", "temp": 17}])})',
    )
    assert html.count("<i ") == 24, "every hour differs, so every hour has a ghost"
    assert "jetzt 17 °C" in html


def test_an_hour_that_did_not_change_gets_no_ghost():
    html = run_js(CARD, f"curveHtml({json.dumps(SAVED)}, {json.dumps(SAVED)})")
    assert "<i " not in html


def test_without_a_saved_day_the_curve_is_just_the_curve():
    """A card that has not loaded yet, or a day the saved week does not have."""
    assert "<i " not in run_js(CARD, f"curveHtml({json.dumps(SAVED)})")


# ── times sit on the half hour ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("06:00", "06:00"),
        ("06:14", "06:00"),
        ("06:15", "06:30"),
        ("06:44", "06:30"),
        ("06:45", "07:00"),
        ("00:10", "00:00"),
        ("7:05", "07:00"),
    ],
)
def test_a_time_is_snapped_to_the_grid(typed, expected):
    """`step` moves the picker, but a resident can still type 06:14 and a phone's
    own picker ignores step entirely — so the value is snapped where every edit
    passes, not trusted from the input."""
    assert json.loads(run_js(CARD, f'JSON.stringify(snapTime("{typed}"))')) == expected


def test_the_last_half_hour_of_the_day_rounds_down():
    """23:45 rounds UP to tomorrow. Rounding it there would move the slot to the
    start of this day and reorder the plan under the resident's hands."""
    for typed in ("23:44", "23:45", "23:59"):
        assert json.loads(run_js(CARD, f'JSON.stringify(snapTime("{typed}"))')) == "23:30"


@pytest.mark.parametrize("junk", ["", "nonsense", "25:00", "06:99"])
def test_something_that_is_not_a_time_is_refused(junk):
    assert json.loads(run_js(CARD, f'JSON.stringify(snapTime("{junk}"))')) is None


def test_the_input_asks_the_picker_for_half_hours_too():
    src = CARD.read_text(encoding="utf-8")
    assert 'step="${SNAP_MINUTES * 60}"' in src
    assert "const SNAP_MINUTES = 30;" in src
