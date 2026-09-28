"""Both Danger Zone actions of ga-master-card must reach the network.

WHAT BROKE
----------
Every release from 1.9.0 to 1.20.0: opening either Danger Zone dialog cleared its
message line with ``el.className = "dlg-msg " + kind``. That assignment also
dropped ``hh-msg`` / ``site-msg`` — the class ``_dlgMsg`` uses to find the line.
The button click then looked the line up, got ``null`` and threw
``Cannot set properties of null (setting 'className')`` before the request was
built: "Nutzer zurücksetzen" and "Alles löschen" did nothing, and the button
stayed disabled. Reproduced on a canary on 2026-09-28.

WHY THE NETWORK IS THE ASSERTION
--------------------------------
Everything a person sees up to the click was correct in the broken state, so no
rendering or source check can tell the two apart. ``tests/browser/
master-card-danger-zone.mjs`` mounts the SHIPPED card file in Chromium, drives
each dialog (open, type, click) and records the POSTs that leave the page. Only
``hass.callApi`` is replaced, by a ``fetch`` with Home Assistant's contract.

Like the other browser test, this FAILS (never skips) without its runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import PKG, REPO

CARD = PKG / "first_party" / "ga-master-card" / "ga-master-card.js"
BROWSER_DIR = REPO / "tests" / "browser"
HARNESS = BROWSER_DIR / "master-card-danger-zone.mjs"

HH = "/api/greenautarky_site/household/reset"
SITE = "/api/greenautarky_site/site_reset/request"

# Pinned expectations — never derived from the card under test.
EXPECTED = {
    "household_reset_sends": [(HH, {"confirm": "LÖSCHEN"})],
    "household_reset_retry_after_failure_sends": [
        (HH, {"confirm": "LÖSCHEN"}),
        (HH, {"confirm": "LÖSCHEN"}),
    ],
    "household_reset_reopened_dialog_sends": [(HH, {"confirm": "LÖSCHEN"})],
    "site_reset_sends": [
        (SITE, {"pin": "123-456", "confirm": "LÖSCHEN", "wipe_zigbee_pairing": True}),
    ],
    "site_reset_retry_after_failure_sends": [
        (SITE, {"pin": "123456", "confirm": "löschen", "wipe_zigbee_pairing": False}),
        (SITE, {"pin": "123456", "confirm": "löschen", "wipe_zigbee_pairing": False}),
    ],
}

_RESULT: dict | None = None


def _result() -> dict:
    global _RESULT
    if _RESULT is not None:
        return _RESULT
    if not CARD.is_file():
        pytest.fail(f"{CARD} is missing — nothing to test is a failure, not a pass")
    if shutil.which("node") is None:
        pytest.fail("node is required for the Danger Zone browser proof")
    if not (BROWSER_DIR / "node_modules").is_dir():
        pytest.fail(
            f"{BROWSER_DIR}/node_modules missing — run `npm ci` there "
            "(and `npx playwright install chromium` once)"
        )
    proc = subprocess.run(
        ["node", str(HARNESS), str(CARD)],
        capture_output=True,
        text=True,
        cwd=str(BROWSER_DIR),
        timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness exited {proc.returncode}\n--- stderr ---\n{proc.stderr}")
    _RESULT = json.loads(proc.stdout)
    return _RESULT


def test_every_scenario_ran():
    """Coverage, not exit code: every pinned scenario must come back."""
    got = set(_result()["scenarios"])
    assert got == set(EXPECTED), f"scenarios run {sorted(got)} != pinned {sorted(EXPECTED)}"


@pytest.mark.parametrize("scenario", sorted(EXPECTED))
def test_danger_zone_click_sends_the_request(scenario: str):
    res = _result()["scenarios"][scenario]
    sent = [(p["path"], p["body"]) for p in res["posts"]]
    assert not res["errors"], f"the card threw in the page: {res['errors']}"
    assert res["stepError"] is None, f"a user step could not complete: {res['stepError']}"
    assert sent == EXPECTED[scenario], (
        f"requests that left the page: {sent}\nexpected: {EXPECTED[scenario]}"
    )
