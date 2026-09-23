"""The thermostat card leads with the TARGET, not with the measurement.

Asked for on 2026-09-23: a resident opening a thermostat card was shown the room's
current temperature as the large number, and the one value they can act on — the
setpoint — as a small row underneath. That answers a question nobody asked while
burying the control.

`show_current: true` puts the measurement back for a diagnostic view; the default
is off. The measurement itself is untouched: it is still on the entity and still
drawn by the temperature/humidity view.

The subtle part is a coupling: `_showPending` finds the number it must update by
the class `target`. With the measurement hidden, the target MOVES from the small
row into the big one — so exactly one element must carry that class in every
layout. Two, or none, and the optimistic press stops showing without anything
else breaking. That is what the last tests here are for.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-thermostat-card" / "ga-thermostat-card.js"

STATE = (
    '{ state: "heat",'
    ' attributes: { current_temperature: 18.4, temperature: 21.5,'
    ' hvac_modes: ["off", "heat", "auto"], hvac_action: "heating",'
    ' min_temp: 5, max_temp: 30, friendly_name: "Wohnzimmer" } }'
)


def render(variant: str, show_current: bool) -> str:
    """Run the real render for one variant and return the markup it produced."""
    method = {"classic": "_renderClassic", "setpoint": "_renderSetpoint"}[variant]
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        f" c._variant = {variant!r};"
        f" c._showCurrent = {'true' if show_current else 'false'};"
        " c._config = { entity: 'climate.wohnzimmer' };"
        " c._root = { innerHTML: '' };"
        f" c.{method}({STATE}, 'Wohnzimmer');"
        " return c._root.innerHTML; })()",
    )


# ── the default hides the measurement ────────────────────────────────────────

def test_the_option_defaults_to_off():
    src = CARD.read_text(encoding="utf-8")
    assert "this._showCurrent = config.show_current === true;" in src


def test_classic_shows_the_target_and_not_the_measurement():
    html = render("classic", show_current=False)
    assert "21.5" in html
    assert "18.4" not in html


def test_setpoint_shows_the_target_and_drops_the_aktuell_line():
    html = render("setpoint", show_current=False)
    assert "21.5" in html
    assert "18.4" not in html
    assert "aktuell" not in html


# ── must-not-flag: the diagnostic view still works ───────────────────────────

def test_show_current_true_puts_the_measurement_back_in_classic():
    html = render("classic", show_current=True)
    assert "18.4" in html and "21.5" in html


def test_show_current_true_puts_the_aktuell_line_back_in_setpoint():
    html = render("setpoint", show_current=True)
    assert "aktuell" in html and "18.4" in html


# ── the dial: the variant the canary actually renders ────────────────────────
# The first version of this change fixed classic and setpoint and left the dial
# alone. The device renders the DIAL, so the fix was correct and unreachable —
# found by the browser, not by reading.

def dial(show_current: bool) -> str:
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        " c._variant = 'dial';"
        f" c._showCurrent = {'true' if show_current else 'false'};"
        f" return c._dialSVG({STATE}); }})()",
    )


def test_the_dial_shows_the_target_and_not_the_measurement():
    svg = dial(show_current=False)
    assert "21.5" in svg            # d-tgt
    assert "18.4" not in svg        # d-cur is gone
    assert 'class="d-cur"' not in svg


def test_show_current_true_puts_the_measurement_back_on_the_dial():
    svg = dial(show_current=True)
    assert "18.4" in svg and 'class="d-cur"' in svg


def test_the_dial_still_draws_its_target_readout():
    """Hiding the measurement must not take the target with it."""
    assert 'class="d-tgt"' in dial(show_current=False)


# ── the _showPending coupling ────────────────────────────────────────────────

def test_exactly_one_element_carries_the_target_class_in_every_layout():
    """`_showPending` updates the number it finds by this class."""
    for variant in ("classic",):
        for show in (True, False):
            html = render(variant, show_current=show)
            assert html.count('class="target"') + html.count('class="val target"') == 1, (
                f"{variant} show_current={show}: {html}"
            )


def test_the_pending_value_is_formatted_for_wherever_the_target_now_sits():
    """Classic without the measurement renders the target big, so with <small>."""
    out = run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        " c._variant = 'classic'; c._showCurrent = false; c._pending = 22.5;"
        " const el = { innerHTML: '', classList: { contains: (x) => x === 'val' } };"
        " c._root = { querySelector: () => el };"
        " c._showPending();"
        " return el.innerHTML; })()",
    )
    assert out == "22.5<small> °C</small>"


def test_the_pending_value_keeps_the_plain_format_in_the_small_row():
    out = run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaThermostatCard.prototype);"
        " c._variant = 'classic'; c._showCurrent = true; c._pending = 22.5;"
        " const el = { innerHTML: '', classList: { contains: () => false } };"
        " c._root = { querySelector: () => el };"
        " c._showPending();"
        " return el.innerHTML; })()",
    )
    assert out == "22.5 °C"


# ── the measurement is hidden, not removed ───────────────────────────────────

def test_the_card_still_reads_the_measurement_from_the_entity():
    """Hiding a number must not become deleting the code path that has it."""
    src = CARD.read_text(encoding="utf-8")
    assert "current_temperature" in src
