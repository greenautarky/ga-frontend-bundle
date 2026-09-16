"""The card must say whether the room is being heated — and READ it, not guess.

THE DEFECT THIS FILE EXISTS FOR, measured on a bench device on 2026-09-16.

A thermostat was heating: `hvac_action: heating`, valve 100 % open. The card
showed the current temperature, the target and the mode — and nothing at all
about the heating running. Twelve seconds earlier it had looked identical with
the valve shut.

Two independent halves, and fixing either alone leaves a defect:

  the SILENCE   the running state was rendered in the `dial` variant only,
                while the device ships `setpoint`
  the GUESS     even there it was inferred from `target > current`, which is
                not the same question. A valve holds `idle` with a target
                above the room when a window contact is open, and reports
                `heating` at equal temperatures while it catches up.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs) rather than grepping
the source: a badge that exists in the file and never reaches the markup
passes every string check ever written about it, which is exactly how the
first half survived.
"""

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"


def _state(**attrs):
    st = attrs.pop("state", "heat")
    base = {"current_temperature": 21.0, "temperature": 22.0,
            "hvac_modes": ["auto", "heat", "off"], "min_temp": 5, "max_temp": 30}
    base.update(attrs)
    import json
    return f'{{state: {json.dumps(st)}, attributes: {json.dumps(base)}}}'


def _action(**attrs):
    card = "Object.create(GaThermostatCard.prototype)"
    return run_js(CARD, f'JSON.stringify({card}._action({_state(**attrs)}))')


def _badge(**attrs):
    card = "Object.create(GaThermostatCard.prototype)"
    return run_js(CARD, f'{card}._actionBadge({_state(**attrs)})')


# ── the reading ─────────────────────────────────────────────────────────────


def test_a_heating_valve_is_reported_as_heating():
    import json
    a = json.loads(_action(hvac_action="heating"))
    assert a["label"] == "Heizt"
    assert a["inferred"] is False, "hvac_action is a reading, not an inference"


def test_an_idle_valve_is_not_called_heating_just_because_the_target_is_higher():
    """THE RED ONE for the guess. Target 22 over a room at 21 — the old code
    called this "Heizt". The thermostat says `idle`, and it is right: this is
    what an open window or a closed valve looks like."""
    import json
    a = json.loads(_action(hvac_action="idle", current_temperature=21.0, temperature=22.0))
    assert a["label"] == "Bereit"
    assert a["key"] == "idle"
    assert a["inferred"] is False


def test_heating_at_equal_temperatures_is_still_heating():
    """The other direction the comparison gets wrong."""
    import json
    a = json.loads(_action(hvac_action="heating", current_temperature=22.0, temperature=22.0))
    assert a["label"] == "Heizt"


def test_off_is_off_whatever_the_temperatures_say():
    import json
    a = json.loads(_action(state="off", hvac_action="heating"))
    assert a["key"] == "off"
    assert a["label"] == "Aus"


# ── the fallback, honestly labelled ─────────────────────────────────────────


def test_a_thermostat_without_hvac_action_still_gets_an_answer():
    """Not every thermostat publishes it. Falling back is right; pretending
    the fallback is a reading is not."""
    import json
    a = json.loads(_action(current_temperature=21.0, temperature=22.0))
    assert a["label"] == "Heizt"
    assert a["inferred"] is True


def test_an_inferred_answer_says_so_in_the_markup():
    assert "abgeleitet" in _badge(current_temperature=21.0, temperature=22.0)
    assert "abgeleitet" not in _badge(hvac_action="heating")


# ── the silence ─────────────────────────────────────────────────────────────


def test_every_variant_renders_the_badge():
    """THE RED ONE for the silence. The badge lived in `dial` alone while the
    device shipped `setpoint`, so on the real screen it did not exist."""
    import re

    src = CARD.read_text(encoding="utf-8")
    bodies = dict(
        re.findall(r"\n  (_render(?:Classic|Setpoint|Dial))\(s, header\) \{(.*?)\n  \}", src, re.S)
    )
    assert set(bodies) == {"_renderClassic", "_renderSetpoint", "_renderDial"}, (
        f"could not read every variant's body — found {sorted(bodies)}. "
        "Failing rather than skipping: a test that inspected nothing would be "
        "green on a card that renders nothing."
    )
    for variant, body in bodies.items():
        assert "_actionBadge" in body, f"{variant} renders no running state"


def test_the_badge_carries_a_word_and_not_only_a_colour():
    """A state rendered as colour alone is not rendered for everyone."""
    assert "Heizt" in _badge(hvac_action="heating")
    assert "Bereit" in _badge(hvac_action="idle")
