"""Working the card must survive the boost countdown's tick.

WHAT BROKE
----------
ga-heating-actions-card counts a running boost (and a balancing run) down once a
second. The first version ran its whole ``_render`` on every tick, always, and
``_render`` rebuilt its controls with ``innerHTML``. A mouse press held across a
tick went down on one button and came up over its replacement, so the browser
fired no click: nothing happened and nothing said why.

The fix: the clock runs only while something is counting down, a tick updates
the countdown text and nothing else, and a block is rebuilt only when the markup
it would produce changes.

WHAT THIS WATCHES, AND WHY IT MOVED
-----------------------------------
It watched the room chips, the control most exposed to the defect. The row of
chips was removed on 2026-10-20 ("remove room choice section, whatever thez
click is automaticallz applied to everzthing") and the hazard outlived it: the
Urlaub form is now OPEN on arrival, so two date inputs and two selects are what
a stray rebuild can now eat — along with whatever a resident had half-typed into
them. The scenarios moved onto the form and onto the Boost button.

``tests/browser/actions-card-tick.mjs`` mounts the SHIPPED card in Chromium,
holds a real mouse press for longer than a tick and types into the form across
one. Like the other browser tests, this FAILS (never skips) without its runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import PKG, REPO

CARD = PKG / "first_party" / "ga-heating-actions-card" / "ga-heating-actions-card.js"
BROWSER_DIR = REPO / "tests" / "browser"
HARNESS = BROWSER_DIR / "actions-card-tick.mjs"

SCENARIOS = {"press_across_tick", "field_survives_tick", "field_survives_hass_push",
             "fields_survive_their_own_change", "idle_has_no_ticker"}

_RESULT: dict | None = None


def _result() -> dict:
    global _RESULT
    if _RESULT is not None:
        return _RESULT
    if not CARD.is_file():
        pytest.fail(f"{CARD} is missing — nothing to test is a failure, not a pass")
    if shutil.which("node") is None:
        pytest.fail("node is required for the actions-card browser proof")
    if not (BROWSER_DIR / "node_modules").is_dir():
        pytest.fail(
            f"{BROWSER_DIR}/node_modules missing — run `npm ci` there "
            "(and `npx playwright install chromium` once)"
        )
    proc = subprocess.run(
        ["node", str(HARNESS), str(CARD)],
        capture_output=True, text=True, cwd=str(BROWSER_DIR), timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness exited {proc.returncode}\n--- stderr ---\n{proc.stderr}")
    _RESULT = json.loads(proc.stdout)
    return _RESULT


def test_every_scenario_ran_and_nothing_threw():
    res = _result()
    assert set(res["scenarios"]) == SCENARIOS
    assert res["errors"] == [], res["errors"]


def test_a_press_held_across_a_tick_still_presses_the_button():
    """THE RED ONE. The press lands on Boost, which asks for one per room."""
    res = _result()["scenarios"]["press_across_tick"]
    assert res["calls"], res
    assert all(c == "ga_heating.boost" for c in res["calls"]), res


def test_the_countdown_still_ticks_meanwhile():
    """Must-pass the other way: the fix must not stop the clock to save the chips."""
    res = _result()["scenarios"]["press_across_tick"]
    assert "Boost läuft" in res["statusBefore"], res
    assert res["statusAfter"] != res["statusBefore"], res


def test_the_field_element_survives_a_tick():
    """A replaced input drops the caret as well as the value, so this asserts the
    ELEMENT is the same one — a rebuild that happens to restore the text would
    still have thrown somebody out of the field they were typing in."""
    res = _result()["scenarios"]["field_survives_tick"]
    assert res["survived"] is True, res
    assert res["value"] == "2026-12-24", res


def test_the_field_survives_a_state_push_that_changes_nothing_it_shows():
    res = _result()["scenarios"]["field_survives_hass_push"]
    assert res["survived"] is True, res
    assert res["value"] == "2026-12-24", res


def test_no_clock_runs_while_nothing_counts_down():
    assert _result()["scenarios"]["idle_has_no_ticker"]["ticker"] is False


# ── the year bug ────────────────────────────────────────────────────────────
# "i can enter day and month but year isnt working" (2026-10-20). Typing a date
# goes day -> month -> year, and the input fires `change` as soon as the first
# two parse. The card re-rendered on that change and rebuilt the fields block
# from markup that carried the values — so the element being typed into was
# replaced, and the year landed in a node that was no longer on the page.
#
# The values moved onto the elements; the markup is now fixed for a given kind.


def _change():
    return _result()["scenarios"]["fields_survive_their_own_change"]


def test_the_field_being_typed_into_survives_its_own_change_event():
    """THE RED ONE. Verified against the shipped predecessor first: there both
    date inputs were replaced and the focus was lost."""
    res = _change()
    assert res["startSurvived"] is True, res
    assert res["stillFocused"] is True, res


def test_the_other_fields_survive_it_too():
    """The rebuild took the whole block, so the field a resident was heading to
    next was replaced before they got there."""
    res = _change()
    assert res["endSurvived"] is True, res
    assert res["tempSurvived"] is True, res


def test_what_was_entered_is_still_there():
    assert _change()["startValue"] == "2026-12-24", _change()


def test_the_end_calendar_cannot_offer_a_day_before_the_start():
    """`absenceBody` still refuses a holiday that runs backwards, but a refusal
    after pressing Aktivieren is a lesson; a greyed-out day is an answer."""
    assert _change()["endMin"] == "2026-12-24", _change()
