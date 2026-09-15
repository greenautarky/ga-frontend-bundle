"""What the resident's dashboard actually RENDERS — not what the source says.

Every other test in this repo reads the JS as text. That answers "is the line
there", never "does the code do it", and the three defects below were all
invisible to a string check:

  * a device listed by its raw radio address — the tile carried no ``name`` at
    all, so HA fell back to the entity's ``friendly_name``, which on a fleet
    device is the Zigbee IEEE address;
  * a heating plan with no time axis — the hour existed, in a ``title``
    attribute, i.e. a hover tooltip, i.e. nothing at all on the phone the
    resident actually uses;
  * a tile that announces its own absence — the 24 h curve card rendered
    "Verlauf-Integration deaktiviert" where a graph belongs.

So these tests RUN the shipped file (Node's `vm`, no npm, no bundler — see
``tests/js/eval.mjs``) and assert on the values it produces.

Node is required, not optional: a missing runtime FAILS here rather than
skipping. A check that quietly stops running is worse than one that was never
written, because the colour stays green.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import PKG, REPO

FIRST_PARTY = PKG / "first_party"
STRATEGY = FIRST_PARTY / "ga-home-strategy" / "ga-home-strategy.js"
HEATING_CARD = FIRST_PARTY / "ga-heating-card" / "ga-heating-card.js"
EVAL = REPO / "tests" / "js" / "eval.mjs"

# A Zigbee IEEE address as z2m names an unrenamed device. Pinned as a literal:
# an audit may not take its expected value from the artifact it audits.
IEEE = "0x00124b00294cf4a1"


def _node() -> str:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH. These tests execute the shipped first-party JS; "
        "without a runtime they prove nothing, so this fails rather than skips. "
        "CI installs it via actions/setup-node."
    )
    return node


def run_js(script, expression: str):
    """Evaluate ``expression`` inside ``script`` and return the parsed result."""
    proc = subprocess.run(
        [_node(), str(EVAL), str(script), expression],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


# ─────────────────────────────────────────────────────────────────────────────
# Harness self-test — a harness that cannot fail proves nothing about the code
# ─────────────────────────────────────────────────────────────────────────────


def test_the_harness_really_runs_the_shipped_file():
    """It must reach a function defined in the file, not a stub of one."""
    assert run_js(STRATEGY, "typeof roomSections") == "function"
    assert run_js(STRATEGY, "typeof gaOptions") == "function"


def test_the_harness_reports_a_javascript_error_instead_of_swallowing_it():
    with pytest.raises(AssertionError, match="node exited"):
        run_js(STRATEGY, "thisIdentifierDoesNotExist()")


# ─────────────────────────────────────────────────────────────────────────────
# 1. A device must not be listed by its radio address
# ─────────────────────────────────────────────────────────────────────────────

_HASS = """{
  config: { components: ["history", "recorder", "lovelace"] },
  states: {
    "light.IEEE": { attributes: { friendly_name: "IEEE" } },
    "switch.IEEE_l1": { attributes: { friendly_name: "IEEE l1" } },
    "light.stehlampe": { attributes: { friendly_name: "Stehlampe" } },
    "light.decke": { attributes: { friendly_name: "Küchen-Decke_2" } },
    "sensor.IEEE_temperature": {
      attributes: { friendly_name: "IEEE temperature", device_class: "temperature" }
    }
  }
}""".replace("IEEE", IEEE)

_ROOM = """{
  area_id: "wohnzimmer", name: "Wohnzimmer",
  climate: [], temps: ["sensor.IEEE_temperature"], hums: [], batts: [],
  lights: ["light.IEEE", "light.stehlampe", "light.decke"],
  switches: ["switch.IEEE_l1"]
}""".replace("IEEE", IEEE)


def _device_tiles(hass: str = _HASS, room: str = _ROOM):
    """Every card in the room's "Geräte" section."""
    expr = f"""(() => {{
      const secs = roomSections({room}, gaOptions({{}}), {hass});
      const geraete = secs.find(s =>
        (s.cards || []).some(c => c.type === "heading" && c.heading === "Geräte"));
      return geraete ? geraete.cards.filter(c => c.type === "tile") : [];
    }})()"""
    return run_js(STRATEGY, expr)


def test_no_device_is_labelled_with_a_raw_radio_address():
    tiles = _device_tiles()
    assert tiles, "no device tiles built — the fixture or the strategy changed"

    unnamed = [t for t in tiles if not (t.get("name") or "").strip()]
    assert unnamed == [], (
        "these tiles carry no name, so Home Assistant falls back to the "
        "entity's friendly_name — which on a fleet device is the Zigbee IEEE "
        f"address, i.e. a serial number where a name belongs: {unnamed}"
    )

    with_address = [t for t in tiles if IEEE in (t.get("name") or "")]
    assert with_address == [], f"tiles still showing the radio address: {with_address}"


def test_a_device_that_has_a_real_name_keeps_it_verbatim():
    """Must-not-flag. A cleaner that renames everything is worse than the bug.

    ``Küchen-Decke_2`` is here because the first version of this test used only
    ``Stehlampe`` — and a counter-check then showed that deleting the
    "already human, hand it back untouched" branch changed nothing, because the
    fallback path happened to reconstruct that one name exactly. A name
    carrying a hyphen or an underscore is what tells the two apart: the
    fallback would tidy it into ``Küchen Decke 2``. Without such a name the
    must-not-flag fixture could not fail, which is the same as not having one.
    """
    tiles = _device_tiles()
    by_entity = {t["entity"]: t.get("name") for t in tiles}
    assert by_entity[f"light.{IEEE}"] != "Stehlampe"
    assert by_entity["light.stehlampe"] == "Stehlampe"
    assert by_entity["light.decke"] == "Küchen-Decke_2", (
        "a device somebody actually named came back rewritten — the naming "
        "helper must hand a human name back verbatim, not re-derive it"
    )


def test_an_address_with_a_human_suffix_keeps_the_suffix():
    """``0x… l1`` is a named endpoint on an unnamed device — keep the endpoint."""
    tiles = _device_tiles()
    by_entity = {t["entity"]: (t.get("name") or "") for t in tiles}
    name = by_entity[f"switch.{IEEE}_l1"]
    assert IEEE not in name
    assert "l1" in name.lower(), f"the endpoint suffix was thrown away too: {name!r}"


def test_the_roomless_house_view_is_named_too():
    """The flat view a device with no HA areas gets — today's fleet.

    Also the behavioural half of ``test_home_strategy.py``'s
    ``test_device_without_rooms_still_renders_its_house``, which can only pin
    the call site as a string.
    """
    model = (
        '{ scope: "all", user_name: "Anna", roomless: { climate: [], temps: [], '
        'hums: [], batts: [], lights: ["light.IEEE"], switches: [] } }'
    ).replace("IEEE", IEEE)
    view = run_js(STRATEGY, f"noRoomsView('Anna', {model}, {_HASS})")
    rows = [
        row
        for card in view["cards"]
        for row in (card.get("entities") or [])
        if isinstance(row, dict)
    ]
    assert rows, f"the flat view rendered no device rows: {view}"
    assert all(IEEE not in (r.get("name") or "") for r in rows), rows
    assert all((r.get("name") or "").strip() for r in rows), rows


def test_an_entity_with_no_usable_name_at_all_still_gets_one():
    """Stripping the address must never leave an EMPTY label."""
    hass = (
        '{ config: { components: [] }, states: { "light.IEEE": '
        '{ attributes: { friendly_name: "IEEE" } } } }'
    ).replace("IEEE", IEEE)
    room = (
        '{ area_id: "k", name: "Küche", climate: [], temps: [], hums: [], '
        'batts: [], lights: ["light.IEEE"], switches: [] }'
    ).replace("IEEE", IEEE)
    tiles = _device_tiles(hass, room)
    assert tiles[0].get("name"), "stripping the address left the tile nameless"


# ─────────────────────────────────────────────────────────────────────────────
# 2. A card must not be rendered only to announce that it cannot render
# ─────────────────────────────────────────────────────────────────────────────


def _headings(hass: str = _HASS, room: str = _ROOM):
    expr = f"""(() => {{
      const secs = roomSections({room}, gaOptions({{}}), {hass});
      return secs.flatMap(s => (s.cards || [])
        .filter(c => c.type === "heading").map(c => c.heading));
    }})()"""
    return run_js(STRATEGY, expr)


def test_the_history_section_is_omitted_when_history_is_not_loaded():
    """"Verlauf-Integration deaktiviert" is a complaint, not a card.

    ``statistics-graph`` renders that warning when the ``history`` integration
    is not loaded. The strategy knows whether it is — ``hass.config.components``
    — and must simply not build the section rather than hand the resident a
    tile whose entire content is the reason it is empty.
    """
    hass = _HASS.replace('["history", "recorder", "lovelace"]', '["lovelace"]')
    assert "Verlauf" not in _headings(hass)


def test_the_history_section_is_there_when_history_is_loaded():
    """Must-not-flag: the normal device still gets its 24 h curves."""
    assert "Verlauf" in _headings()


def test_omitting_history_does_not_take_the_rest_of_the_room_with_it():
    hass = _HASS.replace('["history", "recorder", "lovelace"]', '["lovelace"]')
    assert "Geräte" in _headings(hass)


# ─────────────────────────────────────────────────────────────────────────────
# 3. The heating plan needs a time axis a phone can read
# ─────────────────────────────────────────────────────────────────────────────

_SLOTS = '[{time:"06:00",temp:21},{time:"09:00",temp:18},{time:"17:30",temp:22}]'


def test_the_day_curve_carries_hour_labels_as_text():
    """The hour must be TEXT on the page, not a ``title`` attribute.

    It used to be exactly one thing: ``title="06:00 · 21 °C"`` on each bar —
    a hover tooltip. There is no hover on a phone, so on the device residents
    actually use, the time axis did not exist.
    """
    labels = run_js(HEATING_CARD, f"curveAxisLabels({_SLOTS})")
    assert [str(x) for x in labels] == ["0", "6", "12", "18", "24"], (
        f"the day curve has no readable time axis: {labels!r}"
    )


def test_the_axis_labels_are_rendered_as_element_text_not_as_attributes():
    """The whole curve block, exactly as `_render` assembles it onto the page."""
    html = run_js(HEATING_CARD, f"curveHtml({_SLOTS}) + curveAxisHtml({_SLOTS})")
    for hour in ("0", "6", "12", "18", "24"):
        assert f">{hour}<" in html, (
            f"hour {hour} is not element text in the rendered markup — a value "
            f"that only lives in an attribute is unreachable on a touch device."
            f"\n{html}"
        )


def test_the_axis_is_empty_when_the_day_has_no_slots():
    """Must-not-flag: no plan, no axis — not an axis floating over nothing."""
    assert run_js(HEATING_CARD, "curveAxisHtml([])") == ""


def test_every_bar_carries_its_value_for_the_tap_readout():
    """Tap needs the value in the DOM; a tooltip cannot be tapped open."""
    html = run_js(HEATING_CARD, f"curveHtml({_SLOTS})")
    assert html.count("data-h=") == 24, "expected 24 hourly bars"
    assert html.count("data-t=") == 24, "every bar must carry its setpoint"


def test_the_curve_is_empty_when_the_day_has_no_slots():
    """Must-not-flag: no plan, no axis — not an axis over nothing."""
    assert run_js(HEATING_CARD, "curveHtml([])") == ""


def test_the_bar_heights_still_track_the_setpoint():
    """Must-not-flag: adding an axis may not disturb the curve itself."""
    bars = run_js(HEATING_CARD, f"curveModel({_SLOTS})")
    assert len(bars) == 24
    by_hour = {b["h"]: b["t"] for b in bars}
    assert by_hour[7] == 21
    assert by_hour[10] == 18
    assert by_hour[18] == 22
    # Before the first slot the plan wraps from the previous day's last value.
    assert by_hour[3] == 22
