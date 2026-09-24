""""Einstellungen" carries what a resident manages, not the rooms again.

Seen on a canary on 2026-09-24 (Thomas, as a resident): the
Einstellungen tab showed Home Assistant's stock ``area`` card for every room —
the rooms the resident already has as their own tabs — while the things a
resident actually manages (users, room access, invite links) sat on a
separate "Verwalten" tab. Asked for: those things IN Einstellungen, not the
room cards.

Runs the SHIPPED strategy function through tests/js/eval.mjs, like
test_rendered_output.py: an assertion about what the function returns, not
about whether a line of text is present.
"""

from __future__ import annotations

import json

from test_rendered_output import STRATEGY, run_js

ROOMS = [{"area_id": "office", "name": "Office"},
         {"area_id": "wohnzimmer", "name": "Wohnzimmer"}]


def _overview(is_master: bool):
    expr = ("householdOverview('Canary', " + json.dumps({"is_master": is_master})
            + ", " + json.dumps(ROOMS) + ", {})")
    return run_js(STRATEGY, expr)


def _types(view) -> list[str]:
    return [c.get("type") for c in view.get("cards", [])]


def test_settings_has_no_stock_room_cards():
    for master in (True, False):
        types = _types(_overview(master))
        assert "area" not in types, (
            f"is_master={master}: Einstellungen repeats the rooms as stock area "
            f"cards: {types}"
        )


def test_a_master_manages_the_household_in_settings():
    types = _types(_overview(True))
    assert "custom:ga-master-card" in types, types


def test_a_resident_who_is_not_master_gets_no_management_card():
    """The card is gated server-side too; the tab must not offer what it refuses."""
    assert "custom:ga-master-card" not in _types(_overview(False))


def test_there_is_no_second_management_tab():
    """One place to manage the household. The separate tab is gone."""
    assert run_js(STRATEGY, "typeof manageView") == "undefined", (
        "manageView still exists — Verwalten would be a second tab with the same card"
    )
