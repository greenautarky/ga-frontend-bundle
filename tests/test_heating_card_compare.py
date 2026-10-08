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
import re

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


# ── the two plans are drawn on ONE scale ────────────────────────────────────
#
# THE DEFECT THESE EXIST FOR, reported 2026-10-08: "the difference between
# current and new is not clear in the plot down".
#
# It was not a styling problem. The "jetzt" line was an <i> nested INSIDE the
# bar with `height: <saved>%`, so its percentage was of the BAR, not of the
# chart. It therefore sat too low in every case, and could never rise above the
# bar top — so turning an hour DOWN drew the old plan BELOW the new one, which
# is the exact comparison the drawing exists to make.
#
# Measured against the reported screenshot (TMIN 5, TMAX 30, chart 56px): with
# new 24 °C over saved 16 °C the line was 5.9px low; with new 16 °C over saved
# 24 °C it was 24px low and on the wrong side of the bar.
#
# Both are now placed in a full-height column, so each is a share of the same
# scale and the comparison can be read off the picture.


def _col(new_t, saved_t):
    return run_js(
        CARD,
        f'curveHtml({json.dumps([{"time": "00:00", "temp": new_t}])},'
        f' {json.dumps([{"time": "00:00", "temp": saved_t}])})',
    ).split("</div>")[0]


def _pct(style, prop):
    m = re.search(rf"{prop}:\s*([0-9.]+)%", style)
    return float(m.group(1)) if m else None


def test_the_now_line_is_placed_against_the_chart_not_against_the_bar():
    """THE RED ONE. 16 °C on a 5–30 scale is 44% of the CHART, wherever the new
    bar happens to end. Nested, it came out as 44% of the bar."""
    col = _col(24, 16)
    assert 'bottom:44%' in col.replace(" ", ""), col


def test_a_lower_new_value_puts_the_old_plan_ABOVE_the_bar():
    """The case that read backwards: the line could not leave the bar, so an hour
    turned down showed its old value underneath the new one."""
    col = _col(16, 24)
    bar = _pct(col.split("<b ")[1].split(">")[0], "height")
    line = _pct(col.split("<i ")[1].split(">")[0], "bottom")
    assert line > bar, f"old plan drawn at {line}% under a bar of {bar}%"


def test_the_band_is_the_size_of_the_change():
    """The difference as an area: two levels say they differ, the band says how
    much without reading either number."""
    col = _col(24, 16)
    style = col.split("<u ")[1].split(">")[0]
    assert _pct(style, "bottom") == 44.0, style
    assert _pct(style, "height") == 32.0, style        # 76% - 44%


def test_the_band_says_which_way_it_went():
    assert 'class="up"' in _col(24, 16), "warmer"
    assert 'class="down"' in _col(16, 24), "colder"


def test_an_unchanged_hour_has_neither_band_nor_line():
    """MUST-NOT-FLAG: the comparison is only drawn where there is one to make."""
    html = run_js(CARD, f"curveHtml({json.dumps(SAVED)}, {json.dumps(SAVED)})")
    assert "<u " not in html and "<i " not in html
    assert "moved" not in html


def test_a_changed_hour_is_marked_so_it_can_be_coloured():
    """Every bar used to look the same, so "which hours did I touch" meant
    scanning 24 near-identical shapes."""
    assert "col moved" in _col(24, 16)
    assert "col moved" not in run_js(CARD, f"curveHtml({json.dumps(SAVED)}, {json.dumps(SAVED)})")


def test_the_old_value_rides_along_for_the_readout():
    """Tapping a changed hour shows "16 → 24 °C" rather than just the new number,
    which needs the old one on the element."""
    assert 'data-was="16"' in _col(24, 16)
    assert "data-was" not in run_js(CARD, f"curveHtml({json.dumps(SAVED)}, {json.dumps(SAVED)})")


def test_the_legend_cannot_be_left_on_screen_by_its_own_stylesheet():
    """`hidden` is set on the legend when no hour differs — and did nothing,
    because the card's own `display:flex` rule outranks the browser default that
    makes `hidden` work. The legend stayed up on untouched days (2026-10-08).

    Asserted on the stylesheet because that IS the mechanism: the attribute and
    the rule have to exist together or the element does not hide."""
    src = CARD.read_text(encoding="utf-8")
    assert "ga-heating-card .legend[hidden]" in src, (
        "without this rule the hidden attribute is overridden by display:flex"
    )
