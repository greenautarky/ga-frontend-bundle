"""While the plan is paused, the card says for how long.

MEASURED ON K31 on 2026-09-16. ga_heating 0.5.0 caps a manual override and hands
the room back to `auto` when it runs out — the room entity carries
`manual_until`, an ISO timestamp, the whole time. None of it reached the screen:
the card highlighted MANUEL and said nothing about how long that would last, so
"why did my temperature change back?" had no answer anywhere a resident looks.

BOTH numbers are rendered on purpose. The remaining time answers "how long have
I got"; the wall-clock answers "when does it end", which is what someone leaving
the house plans around. One without the other sends the reader to do arithmetic.
"""
import json
import re

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"


def _state(manual_until=None, **attrs):
    base = {"current_temperature": 21.0, "temperature": 22.0,
            "hvac_modes": ["auto", "heat", "off"], "min_temp": 5, "max_temp": 30}
    if manual_until is not None:
        base["manual_until"] = manual_until
    base.update(attrs)
    return f'{{state: "heat", attributes: {json.dumps(base)}}}'


def _card():
    return "Object.create(GaThermostatCard.prototype)"


def _remaining(expr_state):
    return run_js(CARD, f'JSON.stringify({_card()}._manualRemaining({expr_state}))')


def _row(expr_state):
    return run_js(CARD, f'{_card()}._manualRow({expr_state})')


#: Times are built in the JS so the test and the code share one clock — a
#: Python-side timestamp would drift against the runtime's `Date.now()`.
def _in(minutes):
    attrs = json.dumps({
        "current_temperature": 21.0, "temperature": 22.0,
        "hvac_modes": ["auto", "heat", "off"], "min_temp": 5, "max_temp": 30,
    })
    until = f"new Date(Date.now() + {minutes}*60000).toISOString()"
    return f'{{state: "heat", attributes: Object.assign({attrs}, {{manual_until: {until}}})}}'


def test_a_running_override_is_reported_with_both_numbers():
    """THE RED ONE: nothing was rendered at all before this."""
    r = json.loads(_remaining(_in(134)))
    assert r is not None
    assert r["left"] == "2 h 14 min", r
    assert re.fullmatch(r"\d{2}:\d{2}", r["clock"]), r


def test_under_an_hour_is_minutes_alone():
    """"0 h 07 min" is how a clock talks, not a person."""
    r = json.loads(_remaining(_in(7)))
    assert r["left"] == "7 min", r


def test_no_override_renders_nothing():
    """Must-not-flag: a room on the plan must not grow an empty timer row."""
    assert _remaining(_state()) == "null"
    assert _row(_state()).strip() == ""


def test_an_expired_override_renders_nothing():
    """ga_heating clears the attribute on its next tick. Until then, saying
    nothing beats counting backwards at a resident."""
    assert _remaining(_in(-5)) == "null"
    assert _row(_in(-5)).strip() == ""


def test_a_broken_timestamp_is_ignored_rather_than_shown():
    """A card that renders `NaN min` is worse than one that renders nothing."""
    assert _remaining(_state(manual_until="not-a-date")) == "null"


def test_the_row_carries_words_and_says_what_happens_next():
    row = _row(_in(90))
    assert "Manuell noch" in row
    assert "1 h 30 min" in row
    assert "Heizplan" in row, "the row must say what takes over, not just count down"


def test_the_row_is_rendered_under_the_modes():
    """It is a statement ABOUT the active mode, so it belongs with the modes —
    and the mode row is the one piece every variant renders."""
    src = CARD.read_text(encoding="utf-8")
    body = src.split("_modeRow(s) {")[1].split("\n  }")[0]
    assert "_manualRow" in body, "the timer must ride along with the mode row"
