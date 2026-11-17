"""The owner's limits, as the resident's schedule card renders them.

The building's owner can bound what a weekly plan may be set to — a whole-day
range (Werkseinstellungen) and a time window (Nachtabsenkung). ``ga_heating``
enforces both on save. The card's job is that the resident never meets a
stepper which simply refuses to move: it bounds each row to the limits for THAT
row's time, and says once, above the rows, who decided and what they decided.

THE SEAM THAT MATTERS. The card clamps on input so the resident sees the number
that will be stored. If the card's idea of the bounds ever differs from the
component's, the save silently changes a temperature the resident chose — the
exact failure the on-screen notice exists to prevent. ``boundsAt`` here mirrors
``limits_at`` in ``ga_heating/__init__.py``; the cases below walk the midnight
wrap and both boundary minutes, which is where a hand-rolled range check goes
wrong.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-card" / "ga-heating-card.js"

WIDE = {"min": 7, "max": 28}
NIGHT = [{"from": "22:00", "to": "06:00", "min": 16, "max": 20}]
BOTH = [
    {"from": "22:00", "to": "06:00", "min": 16, "max": 20},
    {"from": "06:00", "to": "22:00", "min": 17, "max": 24},
]


def bounds(time, limits=WIDE, windows=NIGHT):
    return run_js(
        CARD,
        f"boundsAt({json.dumps(time)}, {json.dumps(limits)}, {json.dumps(windows)})")


# ── the window, including the two minutes a hand-rolled check gets wrong ──


@pytest.mark.parametrize("time,lo,hi", [
    ("23:00", 16, 20),   # inside, before midnight
    ("02:00", 16, 20),   # inside, after midnight — the wrap
    ("22:00", 16, 20),   # the opening minute IS inside
    ("05:59", 16, 20),   # the last minute inside
])
def test_a_time_in_the_night_window_takes_the_window(time, lo, hi):
    b = bounds(time)
    assert (b["min"], b["max"]) == (lo, hi)
    assert b["window"] is not None


@pytest.mark.parametrize("time", ["06:00", "13:00", "21:59"])
def test_a_time_outside_it_takes_the_whole_day_range(time):
    b = bounds(time)
    assert (b["min"], b["max"]) == (7, 28)
    assert b["window"] is None


def test_the_closing_minute_is_day_again():
    """06:00 is where the night window ENDS. Treating the end as inclusive
    would cap the resident's morning slot at the night ceiling."""
    assert bounds("06:00")["window"] is None


def test_the_day_window_applies_when_one_is_set():
    b = bounds("09:30", windows=BOTH)
    assert (b["min"], b["max"]) == (17, 24)


def test_with_no_windows_the_whole_day_range_applies_everywhere():
    for time in ("00:00", "06:00", "13:00", "23:30"):
        b = bounds(time, windows=[])
        assert (b["min"], b["max"]) == (7, 28)


def test_an_unreadable_time_falls_back_to_the_wide_range():
    """A row mid-edit can hold anything. Falling back wide is right: the
    component is the one that enforces, and it will clamp on save."""
    b = bounds("not a time")
    assert (b["min"], b["max"]) == (7, 28)


def test_without_limits_from_the_component_the_card_uses_its_own_envelope():
    """An older ga_heating sends no `limits`, and the card must still work."""
    b = run_js(CARD, "boundsAt('13:00', null, [])")
    assert (b["min"], b["max"]) == (5, 30)


# ── what the resident is told ────────────────────────────────────────────


def notice(limits=WIDE, windows=NIGHT):
    return run_js(
        CARD, f"limitNotice({json.dumps(limits)}, {json.dumps(windows)})")


def test_the_notice_names_the_hours_and_the_temperatures():
    text = notice()
    assert "22:00" in text and "06:00" in text
    assert "16" in text and "20" in text


def test_the_notice_says_who_decided():
    """A limit with no author reads as a fault in the card. The resident needs
    to know it is a setting, and whose."""
    assert "Eigentümer" in notice()


def test_the_notice_says_what_happens_to_a_value_outside_it():
    """Otherwise a resident types 22, sees 20 after saving, and has no way to
    know that was deliberate."""
    assert "gesetzt" in notice()
    assert "keine Störung" in notice()


def test_a_building_that_set_nothing_gets_no_notice():
    """Silence is right here: there is no rule to explain."""
    assert notice(limits={"min": 5, "max": 30}, windows=[]) == ""
    assert notice(limits=None, windows=[]) == ""


def test_whole_day_limits_alone_still_explain_themselves():
    text = notice(limits={"min": 7, "max": 28}, windows=[])
    assert "7" in text and "28" in text


def test_every_window_gets_its_own_sentence():
    text = notice(windows=BOTH)
    assert text.count("festgelegt") == 2


def test_the_formatter_does_not_reuse_the_banner_helper_name():
    """`test_heating_card` greps the whole card for that name as a proxy for
    "the holiday banner does not restate the setpoint". Loosening that guard to
    make this change pass would have traded a real check for a rename — and the
    comment explaining it must not spell the name out either."""
    assert "fmt" + "Temp" not in CARD.read_text(encoding="utf-8")


def test_a_whole_number_is_not_shown_with_a_decimal():
    """`20.0 °C` on a resident's card is a number that came from a machine."""
    text = notice(windows=[{"from": "22:00", "to": "06:00", "min": 16, "max": 20}])
    assert "20.0" not in text
    assert "bis 20" in text


def test_a_half_degree_is_kept():
    text = notice(windows=[{"from": "22:00", "to": "06:00",
                            "min": 16.5, "max": 20}])
    assert "16.5" in text
