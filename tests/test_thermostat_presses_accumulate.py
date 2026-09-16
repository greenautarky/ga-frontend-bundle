"""Presses on the setpoint must accumulate. None may be lost.

THE DEFECT THIS FILE EXISTS FOR, measured on a bench device on 2026-09-16:
nine presses of + produced seven steps, read back from Core's own API. Not a
stuck button — the presses on either side of a lost one worked.

Two independent causes, and fixing either alone still loses presses:

  the STALE READ   every press read `attributes.temperature`, the value the
                   BACKEND last confirmed, and wrote that plus one step. Two
                   presses inside one round trip both read 19.5 and both wrote
                   20.0. The faster a resident presses, the more they lose.
  the LOST NODE    every state update rebuilt the card with `innerHTML`, so a
                   press could land on a button that had already been detached
                   ("Element is not attached to the DOM").

These drive the SHIPPED bytes in a VM with a fake `hass`, so what is asserted
is the sequence of service calls the card actually makes.
"""
import json

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"

#: A card wired to a fake hass that records every service call, with the
#: backend state deliberately FROZEN at 19.5 — a real backend does not answer
#: inside a burst of presses either.
HARNESS = """
  const calls = [];
  const hass = {
    states: { "climate.x": { state: "heat", attributes: {
      temperature: 19.5, current_temperature: 21, target_temp_step: 0.5,
      min_temp: 5, max_temp: 30, hvac_modes: ["auto","heat","off"] } } },
    callService: (d, s, data) => calls.push([d, s, data.temperature]),
  };
  const card = Object.create(GaThermostatCard.prototype);
  card._config = { entity: "climate.x" };
  card._variant = "setpoint";
  card._root = null;
  card._hass = hass;
"""


def _run(body):
    return json.loads(run_js(CARD, f"(() => {{{HARNESS}{body}}})()"))


def test_six_rapid_presses_move_six_steps():
    """THE RED ONE for the stale read. The backend never answers during the
    burst — exactly the case the old code lost."""
    out = _run("""
      for (let i = 0; i < 6; i++) card._setTemp(1);
      card._flushTemp();
      return JSON.stringify({ pending: card._pending, calls });
    """)
    assert out["pending"] == 19.5 + 6 * 0.5, out
    assert out["calls"][-1][2] == 22.5, out["calls"]


def test_a_burst_is_one_command_not_one_per_press():
    """A Zigbee valve asked six times in two seconds obeys the last answer
    anyway; six commands only fill the radio."""
    out = _run("""
      for (let i = 0; i < 6; i++) card._setTemp(1);
      card._flushTemp();
      return JSON.stringify({ calls: calls.length });
    """)
    assert out["calls"] == 1, f"expected one command, got {out['calls']}"


def test_down_and_up_cancel_out():
    out = _run("""
      card._setTemp(1); card._setTemp(1); card._setTemp(-1);
      card._flushTemp();
      return JSON.stringify({ pending: card._pending, last: calls[calls.length-1][2] });
    """)
    assert out["pending"] == 20.0
    assert out["last"] == 20.0


def test_the_pending_value_survives_an_unrelated_state_update():
    """A TRV reports its local temperature every few seconds. If an update
    that does not confirm the setpoint dropped the intent, a resident's
    presses would be erased by the device's own chatter."""
    out = _run("""
      card._setTemp(1); card._setTemp(1);           // intent: 20.5
      const s = hass.states["climate.x"];
      s.attributes.current_temperature = 21.4;      // unrelated change
      card.hass = hass;
      return JSON.stringify({ pending: card._pending });
    """)
    assert out["pending"] == 20.5


def test_the_pending_value_clears_once_the_backend_confirms_it():
    """And it must clear, or the card would show the resident's intent for
    ever and never follow the device again."""
    out = _run("""
      card._setTemp(1);                             // intent: 20.0
      hass.states["climate.x"].attributes.temperature = 20.0;
      card._reconcilePending(hass.states["climate.x"]);
      return JSON.stringify({ pending: card._pending });
    """)
    assert out["pending"] is None


def test_a_clamped_press_does_not_walk_past_the_maximum():
    out = _run("""
      for (let i = 0; i < 40; i++) card._setTemp(1);
      card._flushTemp();
      return JSON.stringify({ pending: card._pending, last: calls[calls.length-1][2] });
    """)
    assert out["pending"] == 30
    assert out["last"] == 30


def test_the_listener_is_bound_to_the_root_and_only_once():
    """THE RED ONE for the lost node. Binding per button per render means the
    element a press is travelling to can be replaced before it lands; the root
    survives every re-render."""
    src = CARD.read_text(encoding="utf-8")
    body = src.split("_wireCommon() {")[1].split("\n  }")[0]
    assert "this._root.addEventListener" in body, (
        "the handler must sit on the root, which re-rendering does not replace"
    )
    assert "querySelectorAll" not in body, (
        "per-button binding is what loses a press to a detached node"
    )
    assert "this._wired" in body, "and it must not be bound again on every render"


# ── intent that is never honoured must expire (measured on a device) ─────────
#
# MEASURED ON K31 / rc38, 2026-09-16, and it is a defect introduced by the fix
# above. In `auto` mode the heating plan owns the setpoint: a
# `climate.set_temperature` is accepted with HTTP 200 and changes nothing. The
# pending value was therefore never confirmed, the `set hass` early-return fired
# on every state update for ever, and the card stopped following the device
# entirely — no current temperature, no mode, no running state, just a number
# the device did not have.
#
# A card frozen on a wrong number is worse than the lost press the optimism was
# built to fix. Intent expires now.


def test_intent_the_device_never_honours_expires():
    """THE RED ONE for the freeze. The backend keeps answering with its own
    value; after the TTL the card must follow the device again."""
    out = _run("""
      card._setTemp(1);                       // intent: 20.0
      card._pendingSince = Date.now() - 9000;  // ... nine seconds ago
      card._reconcilePending(hass.states["climate.x"]);
      return JSON.stringify({ pending: card._pending });
    """)
    assert out["pending"] is None


def test_intent_is_kept_while_it_is_still_young():
    """Must-not-flag: expiring immediately would reintroduce the lost press,
    because a Zigbee round trip is slower than a render."""
    out = _run("""
      card._setTemp(1);
      card._reconcilePending(hass.states["climate.x"]);
      return JSON.stringify({ pending: card._pending });
    """)
    assert out["pending"] == 20.0


def test_a_confirmed_value_still_clears_immediately():
    """Confirmation must not have to wait for the timeout."""
    out = _run("""
      card._setTemp(1);
      hass.states["climate.x"].attributes.temperature = 20.0;
      card._reconcilePending(hass.states["climate.x"]);
      return JSON.stringify({ pending: card._pending });
    """)
    assert out["pending"] is None
