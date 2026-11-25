"""A room can be boosted from its own card, in one tap.

Asked for on 2026-11-17: "i need to make the boost per room as well".

It was already possible and nobody could find it. `ga_heating.boost` has always
taken an `entity_id`, and the whole-home card can boost a selection of rooms --
but behind a room picker, on a card whose own header calls it "the whole-home
heating controls". Meanwhile the room's own card had shown a RUNNING boost since
2026-10-05, with a `Beenden` button beside it. A resident who found the stop had
nowhere to look for the start.

WHERE IT GOES, AND THE TWO RULES THAT DECIDED IT
------------------------------------------------
NOT in the mode row. KI / MANUEL / AUS come from `hvac_modes` and are states a
room can be left in; a boost runs OVER whichever is chosen and hands the room
back. In that row it would read as a fourth state, and `s.state === m` has no
truth to highlight for it.

NOT inside the manual/override row either, which is the tempting place because
`Beenden` lives there. That row renders NOTHING for a room following its plan,
deliberately, so such a room grows no empty timer -- `test_no_override_renders_
nothing` in test_thermostat_manual_timer.py pins it. Reaching the common case
from in there would have meant breaking that rule, so the button gets a row of
its own directly below.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"
HOUSE = PKG / "first_party" / "ga-heating-actions-card" / "ga-heating-actions-card.js"

#: A room with a thermostat, nothing overriding it.
PLAIN = {
    "current_temperature": 19.0, "temperature": 21.0,
    "hvac_modes": ["auto", "heat", "off"], "min_temp": 5, "max_temp": 30,
}


def _state(override=None, **attrs):
    base = dict(PLAIN)
    if override is not None:
        base["override"] = override
    base.update(attrs)
    return f'{{state: "heat", attributes: {json.dumps(base)}}}'


def _card():
    """A card with a real `setConfig`, so the duration is the shipped default."""
    return 'Object.assign(Object.create(GaThermostatCard.prototype), {})'


def _row(expr_state, config='{entity: "climate.x"}'):
    return run_js(
        CARD,
        f"(() => {{ const c = {_card()};"
        f" c.setConfig({config}); return c._boostRow({expr_state}); }})()",
    )


def _running(kind):
    return {kind: {"active": True, "until": "2099-01-01T00:00:00+00:00"}}


# ── the button is there, and in the right place ─────────────────────────────


def test_a_room_on_its_plan_offers_a_boost():
    """THE RED ONE. There was no way to START a boost for one room from the UI."""
    row = _row(_state())
    assert "boostrow" in row, row
    assert 'data-boost="1"' in row, row
    assert "Boost" in row, row


def test_the_button_says_how_long_it_will_run():
    """One tap commits the resident to a duration, so the duration is on the
    control rather than somewhere they have to have read first."""
    row = _row(_state())
    assert "15 Minuten" in row, row
    assert "Plan" in row, "and what happens when it is over"


def test_the_button_sits_outside_the_mode_row():
    """MUST-NOT-FLAG. Inside `.modes` it would read as a fourth state, and the
    mode row's own highlight logic has nothing true to say about a boost."""
    mode_row = run_js(
        CARD,
        f"(() => {{ const c = {_card()};"
        f' c.setConfig({{entity: "climate.x"}}); return c._modeRow({_state()}); }})()',
    )
    assert 'data-boost="1"' in mode_row, "it still has to be rendered"
    modes_div = mode_row.split("</div>")[0]
    assert "data-boost" not in modes_div, modes_div


def test_every_variant_renders_it():
    """classic, setpoint and dial all compose through `_modeRow`, which is why
    the button hangs off that and not off one layout."""
    src = CARD.read_text(encoding="utf-8")
    body = src.split("_modeRow(s) {")[1].split("\n  }")[0]
    assert "_boostRow" in body, "the button must ride along with the mode row"


def test_the_timer_row_is_untouched_for_a_room_on_its_plan():
    """MUST-NOT-FLAG, and the reason this button got a row of its own: the
    manual/override row still renders nothing at all here."""
    row = run_js(CARD, f"Object.create(GaThermostatCard.prototype)._manualRow({_state()})")
    assert row.strip() == "", row


# ── hidden exactly when a press could not win ───────────────────────────────
# ga_heating resolves window > ichb > boost > absence > slot.


def test_a_running_boost_offers_beenden_and_not_a_second_start():
    """The row above is the control while it runs. A second press here would
    only restart the clock, next to a button that says Beenden."""
    assert _row(_state(_running("boost"))) == ""
    override = run_js(
        CARD,
        f'Object.create(GaThermostatCard.prototype)._overrideRow({_state(_running("boost"))})',
    )
    assert "Beenden" in override, override


@pytest.mark.parametrize("kind", ["window", "ichb"])
def test_something_that_outranks_a_boost_hides_it(kind):
    """MUST-NOT-FLAG. A window open means the valves are already shut and a
    balancing run owns them for the hour: the service would accept the press and
    the room would not move. That is the same lie as a Beenden on a window."""
    assert _row(_state(_running(kind))) == ""


def test_an_urlaub_keeps_it():
    """A boost outranks an absence, so "I am home early, warm this room" does
    what it says — and this is the case that proves the rule above is about
    precedence and not about "any override at all"."""
    assert 'data-boost="1"' in _row(_state(_running("absence")))


def test_an_override_attribute_that_is_absent_or_junk_still_offers_the_button():
    """A room that publishes no `override` is the normal case, not an error."""
    assert 'data-boost="1"' in _row(_state())
    assert 'data-boost="1"' in _row(_state(override={}))
    assert 'data-boost="1"' in _row(_state(override={"boost": {"active": False}}))


# ── what the press actually sends ───────────────────────────────────────────

HARNESS = """
  const calls = [];
  const hass = {
    states: { "climate.x": { state: "auto", attributes: {
      temperature: 21, current_temperature: 19, min_temp: 5, max_temp: 28,
      hvac_modes: ["auto","heat","off"] } },
      "climate.other": { state: "auto", attributes: { max_temp: 30 } } },
    callService: (d, s, data) => calls.push([d, s, data]),
  };
  const card = Object.create(GaThermostatCard.prototype);
  card._hass = hass;
"""


def _press(body, config='{entity: "climate.x"}'):
    return json.loads(run_js(
        CARD,
        f"(async () => {{{HARNESS} card.setConfig({config}); {body}"
        " return JSON.stringify(calls); })()",
    ))


def test_the_press_boosts_this_room_and_only_this_room():
    calls = _press("await card._boost();")
    assert len(calls) == 1, calls
    domain, service, data = calls[0]
    assert (domain, service) == ("ga_heating", "boost")
    assert data["entity_id"] == "climate.x"
    assert data["minutes"] == 15


def _boost_temp(attrs):
    """The temperature a press sends for a room with exactly these attributes."""
    calls = json.loads(run_js(
        CARD,
        "(async () => {"
        "  const calls = [];"
        '  const hass = { states: { "climate.x": { state: "auto", attributes: '
        f"   {json.dumps(attrs)} }} }},"
        "    callService: (d, s, data) => calls.push([d, s, data]) };"
        "  const card = Object.create(GaThermostatCard.prototype);"
        '  card._hass = hass; card.setConfig({entity: "climate.x"});'
        "  await card._boost();"
        "  return JSON.stringify(calls); })()",
    ))
    return calls[0][2]["temperature"]


def test_the_temperature_sent_is_three_degrees_above_the_room():
    """CHANGED 2026-11-18. This test used to pin the room's own `max_temp`, which
    emulated "open the valves 100 %" — and it did open them, after which every
    room card read `30.0`, because a room reports the setpoint its RADIATORS are
    on, not what its plan intends ("30 is not accurate, we dont want to reach
    30").

    3 °C is ga_heating's own `BOOST_STEP`, the step the service picks when no
    temperature is sent. A TRV calls for heat on the gap between its setpoint and
    what it reads, and a room does not climb 3 K in fifteen minutes, so for a run
    this short the valve stays open exactly as it did at 30 — while nothing is
    asked for that could be overshot into if the run is ever extended."""
    data = _press("await card._boost();")[0][2]
    assert data["temperature"] == 24, "setpoint 21 over a room at 19, capped at 28"


def test_a_room_that_is_off_is_boosted_above_the_ROOM_not_above_its_frost_value():
    """THE RED ONE for `_boostTarget`. An AUS room's radiators sit at their frost
    value, so `setpoint + 3` is 11 °C in a room at 19 — a press that sent that
    would be a button that did nothing, which is the failure the `max_temp`
    version avoided BY ACCIDENT. Taking the warmer of the room and the setpoint
    is what makes it deliberate, and it costs nothing in the ordinary case."""
    assert _boost_temp(
        {"temperature": 8.0, "current_temperature": 19.0, "max_temp": 28}) == 22


def test_the_ask_is_capped_at_what_the_room_accepts():
    """A room already held at its maximum gets its maximum — a press that changes
    nothing, rather than a service call ga_heating rejects. K55's Schlafzimmer was
    in MANUELL at 30 the day this was written."""
    assert _boost_temp(
        {"temperature": 30.0, "current_temperature": 19.0, "max_temp": 30}) == 30
    # And the cap applies to the room-temperature branch too.
    assert _boost_temp(
        {"temperature": 19.0, "current_temperature": 29.0, "max_temp": 30}) == 30


def test_the_value_sent_carries_one_decimal_not_the_sensors_own():
    """`current_temperature` arrives with whatever decimals the sensor reports, and
    this takes the room when the room is the warmer of the two. Unrounded, a room
    reading 19.37 asks its valve for 22.37 and logs it."""
    assert _boost_temp(
        {"temperature": 8.0, "current_temperature": 19.37, "max_temp": 28}) == 22.4


def test_the_room_and_the_house_ask_for_the_same_step():
    """The two cards share no module — nothing in first_party/ imports anything —
    so the rule is written twice and pinned here, exactly as the duration is."""
    def step(path):
        m = re.search(r"const BOOST_STEP = (\d+);", path.read_text(encoding="utf-8"))
        assert m, f"BOOST_STEP not found in {path.name}"
        return int(m.group(1))

    assert step(CARD) == step(HOUSE) == 3


def test_the_temperature_is_always_sent():
    """MUST-NOT-FLAG. Omitting it makes the service fall back to plan + 3 °C and
    raise a ServiceValidationError on a room with no plan — which Home
    Assistant's /api/services returns as a bare 500 with no body, so the reason
    reaches the log and the resident gets a button that did nothing."""
    for attrs in ("{}", '{max_temp: "warm"}', "{max_temp: null}"):
        calls = json.loads(run_js(
            CARD,
            "(async () => {"
            "  const calls = [];"
            '  const hass = { states: { "climate.x": { state: "auto", attributes: '
            f"   {attrs} }} }},"
            "    callService: (d, s, data) => calls.push([d, s, data]) };"
            "  const card = Object.create(GaThermostatCard.prototype);"
            '  card._hass = hass; card.setConfig({entity: "climate.x"});'
            "  await card._boost();"
            "  return JSON.stringify(calls); })()",
        ))
        sent = calls[0][2]["temperature"]
        assert isinstance(sent, (int, float)), (attrs, sent)
        assert sent == 30, (attrs, sent)


def test_a_room_with_no_state_sends_nothing():
    """Pressing a card whose entity has gone away must not throw inside the
    click handler, where there is nobody to catch it."""
    calls = _press("await card._boost();", config='{entity: "climate.gone"}')
    assert calls == []


# ── the duration ────────────────────────────────────────────────────────────


def test_a_dashboard_can_ask_for_a_different_duration():
    data = _press("await card._boost();",
                  config='{entity: "climate.x", boost_minutes: 45}')[0][2]
    assert data["minutes"] == 45


@pytest.mark.parametrize("given,expected", [
    (9999, 240),   # ga_heating's own ceiling
    (0, 15), (-5, 15), ("abc", 15), (None, 15),
])
def test_an_unusable_duration_falls_back_instead_of_failing_the_call(given, expected):
    """A typo in a hand-written dashboard should be a short boost, not a service
    call ga_heating rejects — which the resident sees as a dead button."""
    cfg = f'{{entity: "climate.x", boost_minutes: {json.dumps(given)}}}'
    assert _press("await card._boost();", config=cfg)[0][2]["minutes"] == expected


def test_the_room_and_the_house_ask_for_the_same_duration():
    """Two buttons that both say "Boost" must not mean two different things. The
    house card went 5 -> 15 on 2026-10-27 because five minutes is shorter than a
    TRV takes to open; this is the same number, pinned so they move together."""
    def minutes(path):
        m = re.search(r"const BOOST_MINUTES = (\d+);", path.read_text(encoding="utf-8"))
        assert m, f"BOOST_MINUTES not found in {path.name}"
        return int(m.group(1))

    assert minutes(CARD) == minutes(HOUSE)


# ── and the press reaches it ─────────────────────────────────────────────────


def test_the_press_is_routed_through_the_one_root_listener():
    """THE RED ONE for the wiring. The card routes every click through a single
    listener on the root, because `_render()` rebuilds with `innerHTML` and a
    per-button binding loses the press to a detached node. A new button that is
    not in that selector is simply dead."""
    out = json.loads(run_js(
        CARD,
        "(async () => {"
        "  const calls = [];"
        '  const hass = { states: { "climate.x": { state: "auto", attributes: '
        "   { max_temp: 28 } } },"
        "    callService: (d, s, data) => calls.push([d, s, data]) };"
        "  const card = Object.create(GaThermostatCard.prototype);"
        '  card._hass = hass; card.setConfig({entity: "climate.x"});'
        "  let handler = null;"
        "  card._root = { addEventListener: (ev, fn) => { if (ev === 'click') handler = fn; },"
        "                 contains: () => true };"
        "  card._wireCommon();"
        "  const btn = { dataset: { boost: '1' } };"
        "  btn.closest = (sel) => sel.includes('.boostrow .boost') ? btn : null;"
        "  handler({ target: btn });"
        "  await new Promise((r) => setTimeout(r, 0));"
        "  return JSON.stringify({ wired: handler !== null, calls }); })()",
    ))
    assert out["wired"], "no click listener was bound to the root"
    assert len(out["calls"]) == 1, out
    assert out["calls"][0][1] == "boost", out["calls"]


def test_the_selector_names_the_button():
    """The selector is read as one string literal by
    test_thermostat_override_can_be_ended.py; keep it that way."""
    src = CARD.read_text(encoding="utf-8")
    sel = re.search(r'closest\(\s*\n?\s*"([^"]+)"\s*\)', src)
    assert sel, "the delegated click selector moved or was split up"
    assert ".boostrow .boost" in sel.group(1), sel.group(1)


# ── and what the card SHOWS while one runs ──────────────────────────────────
#
# The other half of 2026-11-18. With `max_temp` gone the number is honest again,
# but it is still the OVERRIDE's number and not the room's own decision: `24.0`
# on a room somebody set to 21 invites the same question `30.0` did. So for the
# fifteen minutes a boost runs, the slot says WHAT IS HAPPENING instead of to
# what — and the controls that cannot move it while it runs go with it.

#: A room whose plan says 21, sitting at 19, with a boost in force.
BOOSTING = '{ boost: { active: true, until: "2099-01-01T00:00:00+00:00" } }'


def _js_state(override=None):
    attrs = dict(PLAIN)
    base = f'{{ state: "heat", attributes: Object.assign({json.dumps(attrs)}'
    return base + (f", {{ override: {override} }}" if override else "") + ") }"


def _rendered(variant, show_current=False, override=None):
    """The markup one variant really produces, from the shipped bytes."""
    method = {"classic": "_renderClassic", "setpoint": "_renderSetpoint"}[variant]
    cfg = {"entity": "climate.x", "variant": variant, "show_current": show_current}
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        f" c.setConfig({json.dumps(cfg)});"
        " c._root = { innerHTML: '' };"
        f" c.{method}({_js_state(override)}, 'Wohnzimmer');"
        " return c._root.innerHTML; })()",
    )


def _dial(override=None):
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        " c.setConfig({ entity: 'climate.x', variant: 'dial' });"
        f" return c._dialSVG({_js_state(override)}); }})()",
    )


@pytest.mark.parametrize("show_current", [False, True])
def test_classic_says_boost_where_the_number_was(show_current):
    """THE RED ONE for the display. The slot read `24.0` — the override's
    setpoint, correct and unanswerable."""
    html = _rendered("classic", show_current, BOOSTING)
    assert "Boost" in html, html
    assert "24.0" not in html and "21.0" not in html, html


def test_classic_keeps_the_measurement_it_was_configured_to_show():
    """A boost hides the TARGET, not the room temperature: `show_current` is the
    dashboard's choice and a boost is not an excuse to overrule it."""
    assert "19.0" in _rendered("classic", True, BOOSTING)


@pytest.mark.parametrize("show_current", [False, True])
def test_classic_drops_its_plus_and_minus_while_a_boost_runs(show_current):
    """Those buttons provably cannot move the number: `target_temperature` reports
    what the radiators are set to, and `_apply` keeps writing the override's value
    to them for as long as the boost outranks the room's stored decision. A press
    lands, is kept for afterwards, and shows nothing meanwhile — which is the
    "button that did nothing" this card keeps paying to avoid. `Beenden` in the
    row above is the way out, and these come back with it."""
    html = _rendered("classic", show_current, BOOSTING)
    assert "data-delta" not in html, html
    # And they are there the moment nothing is overriding the room.
    assert "data-delta" in _rendered("classic", show_current)


def test_setpoint_says_boost_and_drops_its_buttons_too():
    html = _rendered("setpoint", False, BOOSTING)
    assert "Boost" in html and "data-delta" not in html, html
    assert "21.0" not in html, html


def test_the_ziel_caption_goes_with_the_number():
    """"ZIEL / Boost" reads as a target called Boost. The word is not a target —
    the row beneath it says what it is and how long it has left."""
    for variant in ("classic", "setpoint"):
        html = _rendered(variant, False, BOOSTING)
        assert "Ziel" not in html, (variant, html)
        assert "Ziel" in _rendered(variant, False), variant


def test_the_dial_says_boost_inside_its_ring():
    """THE VARIANT THE CANARY RENDERS. The first version of the `show_current`
    change fixed classic and setpoint and left the dial showing the wrong thing,
    and only a browser said so — so the dial is tested first-class here."""
    svg = _dial(BOOSTING)
    assert ">Boost</text>" in svg, svg
    assert "21.0" not in svg, svg
    assert 'class="d-tgt"' in _dial(), "the number must still be there otherwise"


def test_the_dial_cannot_be_dragged_while_a_boost_runs():
    """Same reason the − / + go: `live()` would paint a number over the word, and
    the commit would not reach the valves until the boost ended. `_wireDial` runs
    on every render, so the gesture returns when the boost does."""
    out = json.loads(run_js(
        CARD,
        "(() => {"
        "  const wire = (st) => {"
        "    const bound = [];"
        "    const el = { addEventListener: (n) => bound.push(n),"
        "      setPointerCapture() {}, querySelector: () => ({ setAttribute() {} }),"
        "      getBoundingClientRect: () => ({ left: 0, top: 0, width: 200 }) };"
        "    const c = Object.create(GaThermostatCard.prototype);"
        "    c.setConfig({ entity: 'climate.x', variant: 'dial' });"
        "    c._root = { querySelector: () => el };"
        "    c._wireDial(st); return bound.length; };"
        f"  return JSON.stringify({{ plain: wire({_js_state()}),"
        f"    boosting: wire({_js_state(BOOSTING)}) }}); }})()",
    ))
    assert out["plain"] > 0, "the drag was never wired, so this proves nothing"
    assert out["boosting"] == 0, out


@pytest.mark.parametrize("show_current", [False, True])
def test_exactly_one_element_still_carries_the_target_class(show_current):
    """`_showPending` finds the number by this class, and
    test_thermostat_target_only.py pins the same invariant for a room that is not
    being boosted. Two of them, or none, breaks the optimistic press without
    breaking anything else a test would see."""
    html = _rendered("classic", show_current, BOOSTING)
    assert html.count("target boosting") == 1, html


def test_a_pending_press_is_not_painted_over_the_word():
    """`set hass` calls `_showPending` on every push, and a TRV reports every few
    seconds. A value pending from before the boost began would be written straight
    back into the slot that now holds the word."""
    out = run_js(
        CARD,
        "(() => {"
        "  const el = { innerHTML: 'Boost', classList: { contains: () => true } };"
        "  const c = Object.create(GaThermostatCard.prototype);"
        "  c.setConfig({ entity: 'climate.x' }); c._pending = 22.5;"
        f"  c._hass = {{ states: {{ 'climate.x': {_js_state(BOOSTING)} }} }};"
        "  c._root = { querySelector: () => el };"
        "  c._showPending();"
        "  return el.innerHTML; })()",
    )
    assert out == "Boost", out


def test_the_number_comes_back_when_the_boost_ends():
    """MUST-NOT-FLAG: the word is tied to the override being ACTIVE, not to its
    key existing. An expired boost ga_heating has not yet swept would otherwise
    leave the room with no readable target at all."""
    expired = '{ boost: { active: false, until: "2000-01-01T00:00:00+00:00" } }'
    html = _rendered("classic", False, expired)
    # "Boost" is in the markup either way -- the row that STARTS one is back.
    assert "21.0" in html, html
    assert "boosting" not in html, html
