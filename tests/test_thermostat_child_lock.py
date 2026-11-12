"""A locked thermostat ignores its own dial — the card has to say so.

THE DEFECT THIS FILE EXISTS FOR. A TRV with `child_lock` on does not respond to
the ring on the radiator at all: the resident turns it, nothing happens, and the
radiator gets reported as broken. Nothing on the wall or on the screen said the
lock was on, and the buttons on THIS card kept working, because they go over the
network rather than through the ring — so the card contradicted the radiator.

Read from the model, never matched on a title: the room names its thermostats in
`attributes.valves`, and Zigbee2MQTT names each one's switch after the same IEEE,
so the entity is DERIVED. A fleet device calls both of a room's valves
"Thermostat 1 Child lock" and "Thermostat 2 Child lock" — names that are neither
unique nor stable, which is exactly why they are not what this keys on.

Asserted through `_hdr`, the rendered header line, not through the helper that
builds the chip: a padlock that exists in the file and never reaches the markup
passes every string check ever written about it.
"""

import json

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"

ROOM = "climate.wohnzimmer"
A = "0x449fdafffe7c694c"          # Thermostat 1
B = "0x983268fffe05a176"          # Thermostat 2
TIP = "zum Deaktivieren 3 Sekunden auf das Thermostat drücken"


def _hdr(valves, locks, entity=ROOM, header="Wohnzimmer"):
    """The header line exactly as the card writes it.

    `locks` maps IEEE -> ("on"/"off", friendly_name).
    """
    states = {
        f"switch.{ieee}_child_lock": {"state": st,
                                      "attributes": {"friendly_name": name}}
        for ieee, (st, name) in locks.items()
    }
    s = {"state": "heat",
         "attributes": {"current_temperature": 21.0, "temperature": 22.0,
                        "hvac_modes": ["auto", "heat", "off"],
                        "min_temp": 5, "max_temp": 30,
                        "valves": [f"climate.{v}" for v in valves]}}
    card = ("Object.assign(Object.create(GaThermostatCard.prototype), {"
            f"_hass: {{states: {json.dumps(states)}}},"
            f"_config: {{entity: {json.dumps(entity)}}}}})")
    return run_js(CARD, f"{card}._hdr({json.dumps(s)}, {json.dumps(header)})")


# ── the mark ────────────────────────────────────────────────────────────────


def test_a_locked_thermostat_puts_a_padlock_after_the_room_name():
    """THE RED ONE. The lock follows the name it belongs to, and says in words
    what to do about it — the gesture is on the radiator, not on this screen."""
    got = _hdr([A], {A: ("on", "Thermostat 1 Child lock")})

    assert "mdi:lock" in got, got
    assert TIP in got, got
    assert got.index("Wohnzimmer") < got.index("mdi:lock"), (
        "the padlock must follow the room name, not precede it"
    )


def test_an_unlocked_room_gets_no_padlock():
    """MUST-NOT-FLAG. An unlocked thermostat is the normal case, and a padlock
    on every card would stop meaning anything."""
    got = _hdr([A], {A: ("off", "Thermostat 1 Child lock")})

    assert "mdi:lock" not in got, got
    assert "Wohnzimmer" in got


def test_a_room_with_no_child_lock_entity_is_not_marked():
    """MUST-NOT-FLAG. A valve from another integration has no such switch, and
    "I cannot tell" must not render as "it is locked"."""
    assert "mdi:lock" not in _hdr([A], {})


# ── which thermostat ────────────────────────────────────────────────────────


def test_one_locked_radiator_of_two_is_named():
    """A room with two radiators where one ignores its dial is the case this
    exists for, so the tooltip says WHICH — nobody should have to try both."""
    got = _hdr([A, B], {A: ("off", "Thermostat 1 Child lock"),
                        B: ("on", "Thermostat 2 Child lock")})

    assert "mdi:lock" in got, got
    assert "Thermostat 2" in got, got
    # The suffix is the entity's, not the device's, and repeating it would read
    # as "Kindersicherung an Thermostat 2 Child lock aktiv".
    assert "Child lock" not in got, got


def test_a_single_radiator_room_does_not_name_it():
    """"Thermostat 1" in a one-radiator room is the radiator they are already
    looking at: a longer sentence that adds nothing is a worse sentence."""
    got = _hdr([A], {A: ("on", "Thermostat 1 Child lock")})

    assert "Kindersicherung aktiv" in got, got
    assert "Thermostat 1" not in got, got


# ── where the address comes from ────────────────────────────────────────────


def test_a_card_bound_straight_to_a_trv_reads_its_own_address():
    """No room, no `valves` — the card's own entity carries the IEEE, so the
    same rule covers one device instead of a room."""
    got = _hdr([], {A: ("on", "Thermostat 1 Child lock")},
               entity=f"climate.{A}", header="Heizkörper")

    assert "mdi:lock" in got, got


def test_another_rooms_lock_never_reaches_this_room():
    """THE GUARD on deriving rather than matching. B is locked and B is not this
    room's radiator; a resident must never be told their working thermostat is
    locked because a different one is."""
    got = _hdr([A], {A: ("off", "Thermostat 1 Child lock"),
                     B: ("on", "Thermostat 1 Child lock")})

    assert "mdi:lock" not in got, got


# ── which thermostat, when more than one is locked ──────────────────────────
#
# K181's Wohnzimmer is the live case: two valves, and on 2026-11-03 both of them
# were child-locked at once. Before this, that room's tooltip LOST the name it
# had when only one was locked and fell back to "Kindersicherung aktiv" — the
# message got vaguer as more of the room stopped responding.


def test_both_locked_radiators_are_named():
    """THE RED ONE for this half. Two locked radiators are two walks to two
    rings; naming only one, or neither, sends the resident to guess."""
    got = _hdr([A, B], {A: ("on", "Thermostat 1 Child lock"),
                        B: ("on", "Thermostat 2 Child lock")})

    assert "Thermostat 1" in got, got
    assert "Thermostat 2" in got, got
    assert "Thermostat 1 und Thermostat 2" in got, (
        "a German list, not a joined array", got)


def test_three_locked_radiators_read_as_a_list():
    """The joiner is a list, so the third one does not arrive as "a und b und c"."""
    c = "0x1122334455667788"
    got = _hdr([A, B, c], {A: ("on", "Thermostat 1 Child lock"),
                           B: ("on", "Thermostat 2 Child lock"),
                           c: ("on", "Thermostat 3 Child lock")})

    assert "Thermostat 1, Thermostat 2 und Thermostat 3" in got, got


# ── the count on the chip ───────────────────────────────────────────────────
#
# A tooltip is a desktop luxury: `title` has no hover on a phone, which is how
# residents actually read this card. The count is the one fact that survives
# without a pointer.


def test_a_multi_radiator_room_carries_locked_over_total():
    """One of two locked, stated as a ratio."""
    got = _hdr([A, B], {A: ("on", "Thermostat 1 Child lock"),
                        B: ("off", "Thermostat 2 Child lock")})

    assert "1/2" in got, got


def test_the_count_climbs_when_the_second_one_locks():
    got = _hdr([A, B], {A: ("on", "Thermostat 1 Child lock"),
                        B: ("on", "Thermostat 2 Child lock")})

    assert "2/2" in got, got


def test_a_single_radiator_room_carries_no_count():
    """MUST-NOT-FLAG, and the explicit rule: the count exists to tell two
    radiators apart, so a room with one radiator must not wear "1/1"."""
    got = _hdr([A], {A: ("on", "Thermostat 1 Child lock")})

    assert "mdi:lock" in got, got
    assert "1/1" not in got, got
    assert "lkn" not in got, ("no count element at all in a one-valve room", got)


def test_a_bare_trv_card_carries_no_count():
    """MUST-NOT-FLAG. A card bound straight to one TRV is one radiator by
    definition, however it found its address."""
    got = _hdr([], {A: ("on", "Thermostat 1 Child lock")},
               entity=f"climate.{A}", header="Heizkörper")

    assert "mdi:lock" in got, got
    assert "lkn" not in got, got


def test_the_count_sits_inside_the_padlock_chip():
    """STRUCTURAL. Inside the chip the tooltip covers the number too, and the
    number cannot drift away from the lock it counts."""
    got = _hdr([A, B], {A: ("on", "Thermostat 1 Child lock"),
                        B: ("on", "Thermostat 2 Child lock")})

    chip = got[got.index('class="lk"'):]
    chip = chip[:chip.index("</span>", chip.index("2/2"))]
    assert "2/2" in chip, got
    assert TIP in chip, ("the chip's own title must still cover the count", got)


def test_the_names_read_in_order_whatever_order_the_valves_arrive_in():
    """LIVE CASE. K181's Wohnzimmer lists its valves [Thermostat 2, Thermostat 1],
    so the unsorted map reads "Thermostat 2 und Thermostat 1" — right facts,
    wrong order, and the resident has to re-read it to be sure."""
    got = _hdr([B, A], {B: ("on", "Thermostat 2 Child lock"),
                        A: ("on", "Thermostat 1 Child lock")})

    assert "Thermostat 1 und Thermostat 2" in got, got


def test_the_tenth_thermostat_sorts_after_the_ninth():
    """Numeric collation, not lexical: "Thermostat 10" is not between 1 and 2."""
    i, j = "0xaaaaaaaaaaaaaaa9", "0xbbbbbbbbbbbbbb10"
    got = _hdr([A, i, j], {A: ("on", "Thermostat 1 Child lock"),
                           i: ("on", "Thermostat 9 Child lock"),
                           j: ("on", "Thermostat 10 Child lock")})

    assert "Thermostat 1, Thermostat 9 und Thermostat 10" in got, got


# ── the GA label wins ───────────────────────────────────────────────────────
#
# The label is a sticker on the radiator, so it is the one name a person can
# check against the thing in front of them. "Thermostat 1" is unique only inside
# its own room, because that is how Zigbee2MQTT numbers them. ga_database holds
# 86 labelled TRVs (TRV-SON-000000NN) against 114 with a real IEEE, read
# 2026-11-03 — so this chain has real data waiting for it, and nothing publishes
# the attribute yet.


def _hdr_labelled(valves, locks, labels=None):
    """Like `_hdr`, plus `climate.<ieee>` entities that may carry `ga_label`."""
    states = {
        f"switch.{ieee}_child_lock": {"state": st,
                                      "attributes": {"friendly_name": name}}
        for ieee, (st, name) in locks.items()
    }
    for ieee, label in (labels or {}).items():
        states[f"climate.{ieee}"] = {"state": "heat",
                                     "attributes": {"ga_label": label}}
    s = {"state": "heat",
         "attributes": {"current_temperature": 21.0, "temperature": 22.0,
                        "hvac_modes": ["auto", "heat", "off"],
                        "min_temp": 5, "max_temp": 30,
                        "valves": [f"climate.{v}" for v in valves]}}
    card = ("Object.assign(Object.create(GaThermostatCard.prototype), {"
            f"_hass: {{states: {json.dumps(states)}}},"
            f"_config: {{entity: {json.dumps(ROOM)}}}}})")
    return run_js(CARD, f"{card}._hdr({json.dumps(s)}, \"Wohnzimmer\")")


def test_a_labelled_thermostat_is_named_by_its_label_alone():
    """THE RED ONE. "only TRV-SON-15" — the z2m name is not appended to it."""
    got = _hdr_labelled([A, B],
                        {A: ("on", "Thermostat 1 Child lock"),
                         B: ("off", "Thermostat 2 Child lock")},
                        labels={A: "TRV-SON-00000015"})

    assert "TRV-SON-15" in got, got
    assert "Thermostat 1" not in got, ("the label replaces the name, not joins it", got)


def test_the_padded_label_renders_short_exactly_as_a_maintenance_row_does():
    """THE GUARD on the second copy of `gaLabel`. The padded form is the one
    thing the maintenance card was asked to stop showing (2026-10-05); the two
    copies must not drift."""
    got = _hdr_labelled([A, B], {A: ("on", "Thermostat 1 Child lock"),
                                 B: ("off", "Thermostat 2 Child lock")},
                        labels={A: "TRV-SON-00000015"})

    assert "TRV-SON-00000015" not in got, got


def test_an_unlabelled_thermostat_keeps_its_z2m_name():
    """MUST-NOT-REGRESS. No device on the fleet publishes `ga_label` yet, so
    this is every room today — the chain has to fall through, not go blank."""
    got = _hdr_labelled([A, B], {A: ("on", "Thermostat 1 Child lock"),
                                 B: ("on", "Thermostat 2 Child lock")})

    assert "Thermostat 1 und Thermostat 2" in got, got


def test_a_z2m_name_that_is_already_a_label_counts_as_one():
    """Some fleet devices are named `TRV-SON-000000NN` in z2m outright, with no
    attribute anywhere — the short form must still win."""
    got = _hdr_labelled([A, B], {A: ("on", "TRV-SON-00000015 Child lock"),
                                 B: ("off", "Thermostat 2 Child lock")})

    assert "TRV-SON-15" in got, got


def test_one_labelled_and_one_not_read_as_a_list():
    """A half-synced room is the normal case while a rollout is in progress."""
    got = _hdr_labelled([A, B], {A: ("on", "Thermostat 1 Child lock"),
                                 B: ("on", "Thermostat 2 Child lock")},
                        labels={B: "TRV-SON-00000016"})

    assert "Thermostat 1 und TRV-SON-16" in got, got
