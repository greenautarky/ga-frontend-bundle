"""The resident's Einstellungen page, 1.23.11 (Odoo #2144, #2145, #2146).

Three requests from the K31 hand test of BOSv1.6.1-rc1 (2026-11-16, Thomas):

* #2144 — a card listing every Zigbee device with room, battery and LQI, before
  the Gefahrenbereich; weak values highlighted; no room = "ohne Raum";
* #2145 — a software tile: the release bundle as headline, every component
  underneath, shown as the device reports it (no cached value);
* #2146 — no search and no Assist for a resident; the admin view unchanged.

Pure rendering is checked by running the SHIPPED functions (tests/js/eval.mjs);
the card and the asset themselves are mounted in Chromium
(tests/browser/master-card-facts.mjs, resident-chrome.mjs). Like the other
browser tests, these FAIL (never skip) without their runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import PKG, REPO
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-master-card" / "ga-master-card.js"
CHROME = PKG / "first_party" / "ga-resident-chrome" / "ga-resident-chrome.js"
BROWSER_DIR = REPO / "tests" / "browser"

_CACHE: dict[str, dict] = {}


def _browser(script: str, target) -> dict:
    if script in _CACHE:
        return _CACHE[script]
    if not target.is_file():
        pytest.fail(f"{target} is missing — nothing to test is a failure, not a pass")
    if shutil.which("node") is None:
        pytest.fail("node is required for the resident-settings browser proof")
    if not (BROWSER_DIR / "node_modules").is_dir():
        pytest.fail(f"{BROWSER_DIR}/node_modules missing — run `npm ci` there")
    proc = subprocess.run(
        ["node", str(BROWSER_DIR / script), str(target)],
        capture_output=True, text=True, cwd=str(BROWSER_DIR), timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(f"{script} exited {proc.returncode}\n{proc.stderr}")
    _CACHE[script] = json.loads(proc.stdout)
    return _CACHE[script]


def _facts() -> dict:
    return _browser("master-card-facts.mjs", CARD)["scenarios"]


def _chrome() -> dict:
    return _browser("resident-chrome.mjs", CHROME)["scenarios"]


# ─── #2144 Zigbee list ───────────────────────────────────────────────────────


def test_a_device_without_a_room_says_ohne_raum_and_is_listed():
    """THE RED ONE: 'ohne Raum', not missing."""
    html = run_js(CARD, "renderZigbeeDevices(" + json.dumps(
        [{"device_id": "d", "name": "Steckdose", "area": None, "battery": None, "lqi": 90}]) + ")")
    assert "ohne Raum" in html
    assert "Steckdose" in html


def test_weak_lqi_and_low_battery_are_marked_with_text_and_class():
    html = run_js(CARD, "renderZigbeeDevices(" + json.dumps([
        {"device_id": "a", "name": "A", "area": "K", "battery": 20, "lqi": 49},
        {"device_id": "b", "name": "B", "area": "K", "battery": 21, "lqi": 50},
    ]) + ")")
    row_a, row_b = html.split('<tr class="zb-row"')[1:]
    # Boundaries pinned: battery <= 20 is low, LQI < 50 is weak.
    assert "niedrig" in row_a and "schwach" in row_a
    assert "niedrig" not in row_b and "schwach" not in row_b
    assert 'class="lvl bad"' in row_a and 'class="lvl bad"' not in row_b


def test_a_mains_device_shows_no_battery_and_no_lqi_shows_a_dash():
    html = run_js(CARD, "renderZigbeeDevices(" + json.dumps(
        [{"device_id": "d", "name": "S", "area": "Flur", "battery": None, "lqi": None}]) + ")")
    assert html.count("–") == 2
    assert "%" not in html


def test_device_names_are_escaped():
    html = run_js(CARD, "renderZigbeeDevices(" + json.dumps(
        [{"device_id": "d", "name": "<img src=x onerror=alert(1)>", "area": "R",
          "battery": 1, "lqi": 1}]) + ")")
    assert "<img" not in html and "&lt;img" in html


def test_the_empty_list_says_so():
    assert "Keine Zigbee-Geräte" in run_js(CARD, "renderZigbeeDevices([])")


def test_the_card_renders_rows_before_the_danger_zone():
    r = _facts()["renders"]
    assert not r["errors"], r["errors"]
    assert r["rows"] == [
        {"name": "Thermostat Küche", "room": "Küche", "batt": "9 % niedrig", "battBad": True,
         "lqi": "21 schwach", "lqiBad": True},
        {"name": "Thermostat Wohnzimmer", "room": "Wohnzimmer", "batt": "88 %", "battBad": False,
         "lqi": "120", "lqiBad": False},
        {"name": "Steckdose Flur", "room": "ohne Raum", "batt": "–", "battBad": False,
         "lqi": "200", "lqiBad": False},
    ]
    o = r["order"]
    assert -1 < o["zigbee"] < o["software"] < o["danger"], o
    assert r["dangerZonePresent"] is True


# ─── #2145 version tile ──────────────────────────────────────────────────────


def test_the_headline_is_the_release_and_every_group_is_listed():
    r = _facts()["renders"]
    assert r["headline"] == "BOSv1.6.1-rc2"
    assert r["subVersions"] == [
        ["Betriebssystem (OS)", "17.1.ga1"],
        ["Home Assistant Core", "2026.10.4"],
        ["GA Manager", "0.277.6"],
        ["GA Heating", "0.16.1"],
    ]


def test_the_tile_is_expandable_and_starts_collapsed():
    r = _facts()["renders"]
    assert r["tileOpenAtStart"] is False
    assert r["tileOpenAfterClick"] is True


def test_a_changed_version_is_shown_as_it_is_not_a_stale_one():
    """THE RED ONE of #2145."""
    s = _facts()["no_stale_version"]
    assert (s["first"], s["second"], s["core"]) == ("BOSv1.6.1-rc1", "BOSv1.6.1-rc2", "2026.10.4")


def test_a_missing_release_is_said_not_defaulted():
    html = run_js(CARD, 'renderVersions({"status":"missing","bundle":null,"components":[]})')
    assert "Release nicht gemeldet" in html
    assert "BOSv" not in html


def test_one_failing_block_does_not_take_the_others_down():
    s = _facts()["isolated_failures"]
    assert "boom-zb" in s["zb"]
    assert s["headline"] == "Release nicht gemeldet"
    assert s["dangerZonePresent"] and s["householdButton"]


# ─── #2146 no search, no Assist for a resident ───────────────────────────────


def test_a_resident_loses_both_buttons_and_the_overflow_entry():
    r = _chrome()["resident"]
    assert not r["errors"], r["errors"]
    assert r["searchVisible"] is False
    assert r["assistVisible"] is False
    assert r["menuSearchVisible"] is False


def test_buttons_added_later_and_a_changed_icon_are_still_hidden():
    r = _chrome()["resident"]
    assert r["lateSearchVisible"] is False, "a re-render brought the button back"
    assert r["assistRelabelledVisible"] is False, "an icon change defeated the hide"


def test_an_unrelated_button_is_left_alone():
    assert _chrome()["resident"]["refreshVisible"] is True


@pytest.mark.parametrize("label", ["a", "e", "ctrl-k"])
def test_the_shortcuts_open_nothing_for_a_resident(label):
    assert _chrome()["resident"]["keys"][label]["opened"] == []


def test_a_resident_can_still_type_the_letter_a():
    k = _chrome()["resident"]["keys"]["typing-a-in-a-field"]
    assert k["value"] == "a" and k["opened"] == []


def test_the_admin_view_is_unchanged():
    adm = _chrome()["admin"]
    shown = (adm["searchVisible"], adm["assistVisible"], adm["menuSearchVisible"])
    assert shown == (True, True, True)
    assert adm["lateSearchVisible"] is True and adm["assistRelabelledVisible"] is True
    assert adm["keys"]["a"]["opened"] == ["assist"]
    assert adm["keys"]["e"]["opened"] == ["quickbar"]
    assert adm["keys"]["ctrl-k"]["opened"] == ["search-ctrlk"]


def test_the_asset_defines_no_custom_element():
    """It is injected early; an element defined there is lost to the registry swap."""
    import re

    src = re.sub(r"/\*.*?\*/", "", CHROME.read_text(encoding="utf-8"), flags=re.S)
    src = re.sub(r"//.*", "", src)
    assert "customElements.define" not in src
