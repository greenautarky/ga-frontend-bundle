"""Names and texts from Home Assistant render as text in every first-party card.

The cards build their markup as strings and assign it with ``innerHTML``. Every
value that comes from Home Assistant — an entity's ``friendly_name``, a room
name, a user name, an attribute, a stored heating plan, a configured title —
goes through the card's ``esc()`` helper on its way in, so a name containing
``<`` or ``"`` shows exactly as written.

WHAT IS ASSERTED, PER CARD
--------------------------
``tests/browser/cards-render-text.mjs`` mounts the SHIPPED card file in
Chromium and hands it a ``hass`` whose names contain markup (``PROBE``). Then:

  * no element was created from that markup (``[data-probe]`` count is 0),
  * the card's text contains the markup literally — which also proves the
    text site was reached at all, so a card that rendered nothing cannot pass,
  * pinned attributes carry the value back unchanged.

A single helper, copied per card: the cards are independent Lovelace modules
with no shared module between them, so ``test_every_card_carries_the_same_helper``
keeps the copies identical instead.

Like the other browser tests, this FAILS (never skips) without its runtime.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import PKG, REPO

FIRST_PARTY = PKG / "first_party"
BROWSER_DIR = REPO / "tests" / "browser"
HARNESS = BROWSER_DIR / "cards-render-text.mjs"

# Pinned here, never read from the harness or the cards under test.
PROBE = '"><i data-probe="1">x</i>'
EXPECTED_ATTRS = {
    "maintenance": {},
    "heating_log": {},
    "thermostat": {},
    "heating_schedule": {
        "ha-card@header": PROBE,
        "input.t@value": PROBE,
        "input.v@value": PROBE,
    },
    "heating_actions": {},
    "master": {
        "select.area-sel option@value": PROBE,
        "button.tgl@data-uid": PROBE,
        "button.rm@data-name": PROBE,
    },
}

# Every first-party card that assigns markup as a string. Pinned, so a card
# that stops being covered is a failure rather than a smaller loop.
CARDS_WITH_STRING_MARKUP = frozenset(
    {
        "ga-heating-actions-card",
        "ga-heating-card",
        "ga-heating-log-card",
        "ga-maintenance-card",
        "ga-master-card",
        "ga-thermostat-card",
    }
)

HELPER = '''function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}'''

_RESULT: dict | None = None


def _result() -> dict:
    global _RESULT
    if _RESULT is not None:
        return _RESULT
    if shutil.which("node") is None:
        pytest.fail("node is required for the card rendering proof")
    if not (BROWSER_DIR / "node_modules").is_dir():
        pytest.fail(
            f"{BROWSER_DIR}/node_modules missing — run `npm ci` there "
            "(and `npx playwright install chromium` once)"
        )
    proc = subprocess.run(
        ["node", str(HARNESS), str(FIRST_PARTY)],
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
    """Coverage, not exit code: every pinned card scenario must come back."""
    got = set(_result()["scenarios"])
    assert got == set(EXPECTED_ATTRS), f"ran {sorted(got)} != pinned {sorted(EXPECTED_ATTRS)}"
    assert _result()["probe"] == PROBE


@pytest.mark.parametrize("scenario", sorted(EXPECTED_ATTRS))
def test_a_name_containing_markup_renders_as_text(scenario: str):
    res = _result()["scenarios"][scenario]
    assert not res["errors"], f"the card threw in the page: {res['errors']}"
    assert res["probeElements"] == 0, (
        f"{scenario}: markup in a name became {res['probeElements']} element(s)"
    )
    assert PROBE in res["text"], f"{scenario}: the name is not shown as written"
    assert res["attrs"] == EXPECTED_ATTRS[scenario]


def test_every_card_carries_the_same_helper():
    """One helper, identical everywhere it is copied."""
    with_markup = {
        p.parent.name
        for p in FIRST_PARTY.glob("*/*.js")
        if re.search(r"\.innerHTML\s*=|insertAdjacentHTML", p.read_text(encoding="utf-8"))
    }
    assert with_markup == CARDS_WITH_STRING_MARKUP, (
        f"cards assigning string markup changed: {sorted(with_markup ^ CARDS_WITH_STRING_MARKUP)}"
    )
    for name in sorted(with_markup):
        src = (FIRST_PARTY / name / f"{name}.js").read_text(encoding="utf-8")
        assert src.count(HELPER) == 1, f"{name}: esc() missing or differs from the shared copy"
