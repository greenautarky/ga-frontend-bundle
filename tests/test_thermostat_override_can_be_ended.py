"""A running boost can be ended from the room it is running in.

Asked for on 2026-10-05: "when boost is active we should have here the option to
stop the boost and bring the thermostat to the previous state".

The row already said a boost was running and how long it had left, and offered
no way out of it. The only escape was to press KI or AUS — and that is not the
same thing, which is the point of these tests:

  AN OVERRIDE NEVER REPLACED THE ROOM'S DECISION. `_overrides` wins over the
  stored mode while it runs; the mode is still sitting there. So cancelling the
  override puts the room back exactly as it was, with nothing to restore — and
  THAT is "the previous state". Pressing KI instead writes a new decision over
  the old one, so a room that was AUS before the boost comes back heating.

  A WINDOW IS NOT AN OVERRIDE SOMEONE CHOSE. It ends when the contact closes. A
  Beenden button on it would promise something the card cannot do.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"


def _row(override: dict) -> str:
    """`_overrideRow` for a room publishing this `override` attribute."""
    return run_js(
        CARD,
        "Object.create(GaThermostatCard.prototype)._overrideRow("
        f'{{state: "heat", attributes: {json.dumps({"override": override})}}})',
    )


def _running(kind: str, minutes: int = 20) -> dict:
    return {kind: {"active": True, "until": "2099-01-01T00:00:00+00:00"}}


# ── the way out is on screen ─────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["boost", "absence"])
def test_an_override_someone_asked_for_offers_a_way_out(kind):
    """THE RED ONE: the row was read-only, so a boost could only be waited out."""
    row = _row(_running(kind))
    assert "Beenden" in row, row
    assert f'data-end="{kind}"' in row, row


def test_an_open_window_offers_none():
    """Must-not-flag. It ends when the window closes; a button saying otherwise
    is a lie about a contact, and pressing it would do nothing."""
    row = _row({"window": {"active": True}})
    assert "Fenster offen" in row
    assert "Beenden" not in row
    assert "endov" not in row


def test_an_open_window_outranks_whatever_else_is_recorded():
    """The row returns the FIRST active entry, so the list order has to be
    ga_heating's precedence — window > ichb > boost > absence.

    The window used to be LAST, which nothing noticed until a balancing run made
    it visible (CI, 2026-10-06). ga_heating shuts the valves for an open window
    whatever else is in force, so naming the boost here put "Boost" on a room
    that was not heating — and offered a Beenden button for an override whose
    cancellation would change nothing on the wall.
    """
    for other in ("boost", "absence", "ichb"):
        row = _row({"window": {"active": True}, other: _running(other)[other]})
        assert "Fenster offen" in row, other
        assert "Beenden" not in row, other


def test_a_room_with_nothing_running_grows_no_button():
    assert _row({}).strip() == ""
    assert _row({"boost": {"active": False, "until": "2099-01-01T00:00:00+00:00"}}).strip() == ""


def test_the_button_says_what_it_restores():
    """"Beenden" alone leaves "ends into what?" unanswered — the hover says it."""
    assert "vorherigen Zustand" in _row(_running("boost"))


def test_the_countdown_is_still_there_beside_it():
    """The button must not have cost the row its sentence: a resident deciding
    whether to cancel wants to know how much is left to cancel."""
    row = _row({"boost": {"active": True,
                          "until": "2099-01-01T00:00:00+00:00"}})
    assert "Boost" in row
    assert "noch" in row


# ── what the press actually sends ────────────────────────────────────────────


def _sent(kind: str):
    """The one service call `_endOverride` makes, recorded."""
    return json.loads(run_js(CARD, f"""
      (() => {{
        const calls = [];
        const card = Object.create(GaThermostatCard.prototype);
        card._config = {{ entity: "climate.bad" }};
        card._hass = {{
          callService: (d, s, data) => calls.push({{ domain: d, service: s, data }}),
          callApi: (m, p, data) => calls.push({{ api: m + " " + p, data }}),
        }};
        card._endOverride({json.dumps(kind)});
        return JSON.stringify(calls);
      }})()
    """))


def test_ending_a_boost_cancels_the_boost_and_nothing_else():
    """One call. A second one setting a mode is the defect this test exists for:
    it would write a new decision over the one being restored."""
    assert _sent("boost") == [{
        "domain": "ga_heating", "service": "cancel_boost",
        "data": {"entity_id": "climate.bad"},
    }]


def test_ending_a_sonderplan_cancels_the_absence():
    assert _sent("absence") == [{
        "domain": "ga_heating", "service": "cancel_absence",
        "data": {"entity_id": "climate.bad"},
    }]


def test_no_mode_is_sent_with_either():
    """The room's stored mode IS the previous state. Touching `climate` here
    would turn a room that was AUS before the boost into a heating one."""
    for kind in ("boost", "absence"):
        assert not any(c.get("domain") == "climate" for c in _sent(kind)), kind


def test_it_acts_on_this_room_only():
    """The actions card ends a Sonderplan everywhere; this button is inside one
    room's card and must not quietly mean the flat."""
    for kind in ("boost", "absence"):
        for call in _sent(kind):
            assert call["data"] == {"entity_id": "climate.bad"}


def test_a_kind_with_no_cancel_sends_nothing():
    """`window` reaches here only through a bug, and a bug must not become a
    service call with an undefined name."""
    assert _sent("window") == []
    assert _sent("") == []


# ── the press is wired, by name and not by position ──────────────────────────


def test_the_click_handler_reaches_the_button():
    src = CARD.read_text(encoding="utf-8")
    sel = re.search(r'closest\(\s*\n?\s*"([^"]+)"\s*\)', src)
    assert sel, "the delegated click selector moved"
    assert ".endov" in sel.group(1), sel.group(1)


def test_the_handler_reads_the_kind_off_the_button():
    """Same rule as the mode row: the element carries what it means. A handler
    that inferred the kind from the row's position would cancel a Sonderplan
    when a boost was showing."""
    src = CARD.read_text(encoding="utf-8")
    assert "target.dataset.end" in src
