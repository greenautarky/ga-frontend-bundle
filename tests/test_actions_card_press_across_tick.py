"""A press on a room chip must survive the boost countdown's tick.

WHAT BROKE
----------
ga-heating-actions-card counts a running boost (and a balancing run) down once a
second. The first version ran its whole ``_render`` on every tick, always, and
``_render`` rebuilt the room chips with ``innerHTML``. A mouse press held across
a tick went down on one button and came up over its replacement, so the browser
fired no click: the room was not toggled and nothing said why.

The fix: the clock runs only while something is counting down, a tick updates
the countdown text and nothing else, and the chips are rebuilt only when what
they show changes.

``tests/browser/actions-card-tick.mjs`` mounts the SHIPPED card in Chromium,
holds a real mouse press on a chip for longer than a tick and reports the chip
states. Like the other browser tests, this FAILS (never skips) without its
runtime.
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

SCENARIOS = {"press_across_tick", "chip_survives_tick", "chip_survives_hass_push",
             "idle_has_no_ticker"}

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


def test_a_press_held_across_a_tick_still_toggles_the_room():
    """THE RED ONE. All rooms start lit; a press on Badezimmer turns it off."""
    res = _result()["scenarios"]["press_across_tick"]
    assert res["before"]["climate.bad"] == "true", res
    assert res["after"]["climate.bad"] == "false", res
    assert res["after"]["climate.wohnzimmer"] == "true", res
    assert res["after"]["alle"] == "false", res


def test_the_countdown_still_ticks_meanwhile():
    """Must-pass the other way: the fix must not stop the clock to save the chips."""
    res = _result()["scenarios"]["press_across_tick"]
    assert "Boost läuft" in res["statusBefore"], res
    assert res["statusAfter"] != res["statusBefore"], res


def test_the_chip_element_survives_a_tick():
    assert _result()["scenarios"]["chip_survives_tick"]["survived"] is True


def test_the_chip_element_survives_a_state_push_that_changes_nothing_it_shows():
    assert _result()["scenarios"]["chip_survives_hass_push"]["survived"] is True


def test_no_clock_runs_while_nothing_counts_down():
    assert _result()["scenarios"]["idle_has_no_ticker"]["ticker"] is False
