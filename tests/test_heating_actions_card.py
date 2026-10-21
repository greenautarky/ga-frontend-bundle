"""The whole-home heating controls: boost, all-off, and the Sonderplan.

Asked for on 2026-09-23 (Odoo #1062, #1063, #1064, #1065, #1066). The card owns
no heating logic — every button calls something ga_heating already had — so these
tests are about the two things a card CAN get wrong on its own:

  * the body it sends, including the refusals it must catch BEFORE a round trip,
  * what it tells the resident afterwards, in particular the frost-protection
    number, which it must READ and never assume.

The frost line is the load-bearing one. ga_heating's own OFF is deliberately not
a low setpoint — "a frost setpoint keeps the valve working against an open
window" — so when this card switches a flat off, the protection comes from the
VALVE. On a SONOFF TRVZB `system_mode: off` is the anti-freeze state and the
valve holds its own `frost_protection_temperature`. Measured on
KIB-SON-00000031 on 2026-09-23: all four valves hold **7 °C**, not the 5 °C the
vendor documents as the default. A card that hardcoded 5 would have told the
resident a number their flat does not use.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json
import re

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-actions-card" / "ga-heating-actions-card.js"

#: Runs the REAL `_build()` and hands back the markup it produced. `_build` also
#: wires listeners, so the DOM lookups it makes are stubbed — the markup is not.
BUILD_MARKUP = (
    "(() => {"
    " const c = Object.create(GaHeatingActionsCard.prototype);"
    " c.setConfig({});"
    " const stub = { addEventListener() {}, querySelectorAll() { return []; },"
    "                querySelector() { return null; } };"
    " c.querySelector = () => stub;"
    " c.querySelectorAll = () => [];"
    " c._build();"
    " return c.innerHTML; })()"
)

ROOM = {"attributes": {"valves": ["climate.0xaaa"], "area_id": "wohnzimmer",
                       "friendly_name": "Wohnzimmer", "max_temp": 30}}
VALVE = {"attributes": {"local_temperature": 21.0}}


def states(**extra):
    base = {"climate.wohnzimmer": ROOM, "climate.0xaaa": VALVE,
            "sensor.irrelevant": {"attributes": {}}}
    base.update(extra)
    return base


def call(expr):
    return run_js(CARD, expr)


# ── the card is defined, and it is DELIVERED ─────────────────────────────────

def test_the_element_is_defined_and_advertised():
    assert call("typeof GaHeatingActionsCard") == "function"
    src = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("ga-heating-actions-card"' in src


def test_the_card_is_in_the_delivery_plan_as_a_lovelace_resource():
    """A card nobody delivers is a file, not a feature.

    Everything under first_party/ is a Lovelace resource unless it is named in
    EARLY_INJECT_ASSET_IDS — and it must NOT be named there: an injected module
    regularly defines its element against the pre-swap registry, where Home
    Assistant can never see it.
    """
    import importlib.util

    from conftest import PKG as pkg

    spec = importlib.util.spec_from_file_location("ga_fb_bundle", pkg / "bundle.py")
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    spec2 = importlib.util.spec_from_file_location("ga_fb_const", pkg / "const.py")
    const = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(const)

    assert "ga-heating-actions-card" not in const.EARLY_INJECT_ASSET_IDS
    cards = [{"id": p.name, "file": f"{p.name}.js"}
             for p in sorted((pkg / "first_party").iterdir()) if p.is_dir()]
    early, resources = bundle.delivery_plan(cards, const.EARLY_INJECT_ASSET_IDS)
    assert "ga-heating-actions-card" in [c["id"] for c in resources]


# ── which entities are rooms ─────────────────────────────────────────────────

def test_only_room_entities_count_as_rooms():
    """A room carries `valves`; a raw TRV carries neither valves nor area_id."""
    assert call(f"roomEntities({json.dumps(states())})") == ["climate.wohnzimmer"]


def test_no_states_at_all_is_not_a_crash():
    assert call("roomEntities(null)") == []


# ── the frost line: READ, never assumed ──────────────────────────────────────

def test_the_frost_setpoint_is_read_from_the_valves():
    s = states(**{
        "number.0xaaa_frost_protection_temperature": {"state": "7"},
        "number.0xbbb_frost_protection_temperature": {"state": "7"},
    })
    assert call(f"frostSetpoints({json.dumps(s)})") == [7]
    assert "7 °C" in call(f"frostText({json.dumps(s)})")


def test_valves_that_disagree_report_the_lowest_not_both():
    """They do not have to agree — one flat read 7 and 8 — and the line used to
    print every value, "bei 7 / 8 °C", which asks a resident to work out which
    radiator is which ("just say 7 not 8", 2026-10-05).

    THE LOWEST, specifically. A valve set to 8 opens EARLIER than one set to 7,
    so 7 is the coldest any room is let get; naming the warmer number would
    promise more protection than the flat actually gives.
    """
    s = states(**{
        "number.0xaaa_frost_protection_temperature": {"state": "7"},
        "number.0xbbb_frost_protection_temperature": {"state": "5"},
    })
    text = call(f"frostText({json.dumps(s)})")
    assert "5 °C" in text, text
    assert "7" not in text, text
    assert "/" not in text, text


def test_the_frost_line_says_it_is_about_AUS():
    """It sat under a row of buttons and read as a fact about the heating in
    general; it is only about what AUS leaves behind."""
    s = states(**{"number.0xaaa_frost_protection_temperature": {"state": "7"}})
    assert call(f"frostText({json.dumps(s)})").startswith("Bei AUS")


def test_no_valve_reports_a_setpoint_means_no_promise():
    """Silence must not render as a guarantee."""
    assert call(f"frostText({json.dumps(states())})") == ""


def test_an_unreadable_setpoint_is_dropped_rather_than_shown_as_nan():
    s = states(**{"number.0xaaa_frost_protection_temperature": {"state": "unknown"}})
    assert call(f"frostSetpoints({json.dumps(s)})") == []


# ── the absence body, and the refusals it catches first ──────────────────────

def body(form):
    return call(f"absenceBody('climate.wohnzimmer', {json.dumps(form)})")


def test_sickness_starts_now_and_ends_after_the_chosen_hours():
    out = body({"kind": "sick", "hours": 6, "temperature": 20,
                "now": "2026-09-23T10:00:00"})
    assert out["start"] == "2026-09-23T10:00:00"
    assert out["end"] == "2026-09-23T16:00:00"
    assert out["temperature"] == 20


def test_the_timestamps_are_LOCAL_time_not_utc():
    """The engine compares against datetime.now(), which is local.

    A UTC stamp here ends the override at the wrong hour — visibly wrong twice a
    year and subtly wrong the rest of the time.
    """
    out = body({"kind": "sick", "hours": 1, "temperature": 20,
                "now": "2026-09-23T23:30:00"})
    assert out["start"] == "2026-09-23T23:30:00"
    assert out["end"] == "2026-09-24T00:30:00"
    assert "Z" not in out["end"] and "+" not in out["end"]


def test_sickness_refuses_a_duration_over_48_hours_before_any_request():
    out = body({"kind": "sick", "hours": 72, "temperature": 20})
    assert isinstance(out, str) and "48" in out


def test_holiday_starts_at_midnight_by_default():
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-08",
                "temperature": 16})
    assert out["start"] == "2026-10-01T00:00:00"


def test_a_holiday_never_switches_the_heating_off_any_more():
    """THE REMOVAL ("remove the Aus - Frostschutz option and only keep the
    option to set the temp", 2026-10-20). A holiday that switches the heating
    off was one mis-tap away from a frozen flat, and "Alle AUS" already does it
    deliberately, with the frost line beside it saying what it leaves behind.

    Asserted on the BODY, not on the markup: removing the checkbox while
    `absenceBody` still honoured a stale `off` would leave a flat switched off
    with nothing on screen that could have done it."""
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-08",
                "off": True, "temperature": 16})
    assert "switch_off" not in out
    assert out["temperature"] == 16


def test_a_range_that_runs_backwards_is_refused_here():
    out = body({"kind": "holiday", "start": "2026-10-08", "end": "2026-10-01",
                "temperature": 16})
    assert isinstance(out, str) and "Ende" in out


def test_a_holiday_without_a_temperature_is_refused_here():
    """ga_heating DROPS such an override: it would be stored and never apply —
    the resident books a holiday, the UI says saved, the heating runs as usual.
    Refusing in the card means the reason appears next to the wrong field."""
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-08",
                "temperature": ""})
    assert isinstance(out, str) and "Temperatur" in out


def test_a_temperature_outside_the_accepted_range_is_refused_here():
    out = body({"kind": "sick", "hours": 6, "temperature": 45})
    assert isinstance(out, str)


# ── what the card promises after acting ──────────────────────────────────────

def test_the_boost_hint_never_claims_a_valve_position():
    """"100 % open" is what was asked for; a setpoint is what the stack sends.

    Asserted on the text the card BUILDS. The first version of this grepped the
    file and failed on the comment explaining the emulation — a check that reads
    prose instead of behaviour, which is exactly the habit these tests replace.
    """
    hint = run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); c._built = true; c._hass = { states: {} };"
        " let hintText = '';"
        " const mk = (setter) => ({ addEventListener() {}, querySelector: () => null,"
        "   querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} },"
        "   removeAttribute() {}, setAttribute() {},"
        "   set innerHTML(v) {}, get innerHTML() { return ''; },"
        "   set textContent(v) { setter(v); }, get textContent() { return ''; } });"
        " c.querySelector = (sel) =>"
        "   sel === '.boosthint' ? mk(v => { hintText = v; }) : mk(() => {});"
        " c.querySelectorAll = () => [];"
        " c._render();"
        " return hintText; })()",
    )
    assert "100" not in hint
    assert "Ventile kurzzeitig ganz öffnen" in hint


def test_switching_everything_off_offers_a_way_back():
    """An 'all off' with no obvious way back to the plan is a one-way street."""
    assert call("typeof GaHeatingActionsCard.prototype._planAll") == "function"
    assert call("typeof GaHeatingActionsCard.prototype._offAll") == "function"


# ── the strategy actually PLACES it ──────────────────────────────────────────
# A card nobody places is a file. These drive the real strategy in the VM.

STRATEGY = PKG / "first_party" / "ga-home-strategy" / "ga-home-strategy.js"

_HASS_WITH_ROOM = (
    "{ states: { 'climate.wohnzimmer': { attributes: { valves: ['climate.0xaaa'],"
    " area_id: 'wohnzimmer', friendly_name: 'Wohnzimmer' } } } }"
)
_HASS_NO_ROOM = "{ states: { 'light.flur': { attributes: {} } } }"


def test_the_profile_view_keeps_the_path_residents_already_have():
    """THE PATH is the part that must not move. The previous system's view was
    called `Profil` and lives at `/profil` — read in
    ha-dashboard-automation/templates/profile_view_template.j2 on 2026-09-23 —
    and that path is in bookmarks and in any dashboard link pointing here.

    The TITLE is "Services" since 2026-10-08: "Profil" said nothing about Boost,
    the whole flat on or off, the balancing run and the Sonderpläne. A label can
    be read afresh; a path breaks silently.
    """
    v = run_js(STRATEGY, "(() => heatingProfileView({ textTabs: true }))()")
    assert v["path"] == "profil", "a bookmark would 404"
    assert v["title"] == "Services"
    assert "icon" not in v, "a view with an icon shows only the icon in the tab bar"
    assert [c["type"] for c in v["cards"]] == ["custom:ga-heating-actions-card"]


def test_the_view_is_generated_only_where_a_thermostat_exists():
    """The gate is the room entity's `valves` list, read from hass."""
    assert run_js(STRATEGY, f"(() => hasAnyRoomThermostat({_HASS_WITH_ROOM}))()") is True
    assert run_js(STRATEGY, f"(() => hasAnyRoomThermostat({_HASS_NO_ROOM}))()") is False


def test_it_is_the_second_to_last_tab_and_behind_the_not_scoped_gate():
    """Rooms first, then Profil, then Einstellungen (Thomas, 2026-09-23).

    The first version appended it FIRST, on the reasoning that "alles aus" is
    looked for before leaving the flat. Thomas put the daily rooms first
    instead — this pins his order, and the not-scoped gate, which must never let
    "alle Räume aus" reach someone who holds two of the flat's six rooms.
    """
    src = STRATEGY.read_text(encoding="utf-8")
    i = src.index("if (!scoped) {")
    j = src.index("heatingProfileView(opt)", i)
    assert j > i
    assert "views.push(heatingProfileView(opt))" in src
    assert src.index("views.push(heatingProfileView(opt))") < src.index(
        "views.push(householdOverview(")


def test_the_household_view_no_longer_carries_the_card():
    """It was the first attempt and it reached nobody: hide_household defaults to
    true, so that view exists on no device."""
    src = STRATEGY.read_text(encoding="utf-8")
    k = src.index("function householdOverview")
    end = src.index("function heatingProfileView")
    assert "ga-heating-actions-card" not in src[k:end]


def test_a_scoped_sub_user_never_reaches_this_view():
    """"Alle Räume aus" must not be offered to someone who owns two of six rooms.

    The guard is that householdOverview is only unshifted when the dashboard is
    not scoped — asserted on the strategy's own source line, because the branch
    is in generate() and driving that needs the whole HA model.
    """
    src = STRATEGY.read_text(encoding="utf-8")
    assert "if (!scoped) {" in src
    i = src.index("if (!scoped) {")
    j = src.index("householdOverview(userName", i)
    assert j > i


# ── the end carries a TIME — taken from the old system, with its reason ──────
# generate_yaml_new.py built override_start_time / override_end_time as literal
# 15-minute dropdowns: "option text is literal, so locale-independent - no
# native 12h/AM-PM picker". Dropping the field would have been a regression
# nobody would have called one: ending at 23:59 leaves the flat on holiday
# temperature all through the day the resident comes home.

def test_the_holiday_end_carries_the_chosen_time():
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-08",
                "startTime": "09:00", "endTime": "14:30", "temperature": 16})
    assert out["start"] == "2026-10-01T09:00:00"
    assert out["end"] == "2026-10-08T14:30:00"


def test_a_holiday_without_times_still_works_and_ends_at_midday():
    """The default must not be 23:59 — that is the cold-flat-on-return case."""
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-08",
                "temperature": 16})
    assert out["end"] == "2026-10-08T12:00:00"
    assert not out["end"].endswith("23:59:59")


def test_a_same_day_holiday_that_ends_before_it_starts_is_refused():
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-01",
                "startTime": "14:00", "endTime": "09:00", "temperature": 16})
    assert isinstance(out, str) and "Ende" in out


def test_the_times_are_whole_hours_and_literal_24h():
    """Was every quarter hour, 96 entries — the old generator's resolution for a
    weekday plan, carried onto a holiday where nobody leaves at 07:45. The
    literal 24h strings stay: a native time input would render "02:00 PM" where
    the rest of the card says 14:00."""
    opts = call("TIME_OPTIONS")
    assert len(opts) == 24
    assert opts[0] == "00:00" and opts[-1] == "23:00"
    assert all(o.endswith(":00") for o in opts), opts
    assert not any("AM" in o or "PM" in o for o in opts)


def test_both_default_times_are_still_on_the_list():
    """A default that is not an option renders as a blank select, and the
    holiday then starts at whatever the resident scrolls to by accident."""
    opts = call("TIME_OPTIONS")
    form = call("(() => { const c = Object.create(GaHeatingActionsCard.prototype);"
                " c.setConfig({}); return [c._form.startTime, c._form.endTime]; })()")
    for t in form:
        assert t in opts, (t, opts)


def rendered_fields(kind: str) -> str:
    """The markup `_render` actually produces for the Sonderplan fields.

    Three tests in this file were first written against the FILE and failed on
    the comments explaining the very thing they asserted. A check that reads
    prose is not a check. This drives the real render with the DOM it touches
    stubbed, and hands back what the resident would get.
    """
    return run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({});"
        " c._built = true;"   # _render returns early otherwise — the empty string
        f" c._form.kind = {kind!r};"
        " c._hass = { states: {} };"
        " let fields = '';"
        " const mk = (setter) => ({ addEventListener() {}, querySelector: () => null,"
        "   querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} },"
        "   removeAttribute() {}, setAttribute() {},"
        "   set innerHTML(v) { setter(v); }, get innerHTML() { return ''; },"
        "   set textContent(v) {}, get textContent() { return ''; } });"
        " c.querySelector = (sel) => sel === '.fields' ? mk(v => { fields = v; }) : mk(() => {});"
        " c.querySelectorAll = () => [];"
        " c._render();"
        " return fields; })()",
    )


def test_the_holiday_form_uses_a_select_not_a_native_time_input():
    """A native <input type=time> renders in the browser's locale; a resident
    reading "02:00 PM" where the rest of the card says 14:00 files a bug."""
    markup = rendered_fields("holiday")
    assert 'type="time"' not in markup
    assert 'class="endtime"' in markup and 'class="starttime"' in markup
    assert '<option value="14:30"' in markup


def test_the_sickness_form_asks_for_hours_not_for_dates():
    markup = rendered_fields("sick")
    assert 'class="hours"' in markup
    assert 'type="date"' not in markup


# ── the four things the old Profil view had and this card did not ───────────
# Measured in ha-dashboard-automation on 2026-09-23: the status is always
# visible, the form sits behind a toggle, `Alle Räume` is its own switch, and the
# boost shows a countdown from a real timer. ADR-0033, amendment 2026-09-23.

ABS = {"start": "2026-10-01T09:00:00", "end": "2026-10-08T14:30:00",
       "temp": 16.0, "off": False, "active": True}


def st_with(override, n=3):
    """n rooms; the first `len(override)` of them carry the given override."""
    out = {}
    names = ["wohnzimmer", "schlafzimmer", "office"][:n]
    for i, nm in enumerate(names):
        attrs = {"valves": [f"climate.0x{i}"], "area_id": nm,
                 "friendly_name": nm.title(), "max_temp": 30, "temperature": 16.0}
        if i < len(override):
            attrs["override"] = override[i]
        out[f"climate.{nm}"] = {"state": "heat", "attributes": attrs}
    return out


def status(states, rooms):
    return call(f"overrideStatus({json.dumps(states)}, {json.dumps(rooms)})")


ROOM_IDS = ["climate.wohnzimmer", "climate.schlafzimmer", "climate.office"]


def test_a_holiday_in_every_room_says_ALL_rooms():
    s = status(st_with([{"absence": ABS}] * 3), ROOM_IDS)
    assert "Urlaub aktiv" in s and "16 °C" in s and "alle Räume" in s
    assert "bis 08.10. 14:30" in s


def test_a_holiday_in_some_rooms_says_how_many_of_how_many():
    """"3 von 3" answers "is my flat on holiday"; a bare list does not."""
    s = status(st_with([{"absence": ABS}]), ROOM_IDS)
    assert "1 von 3 Räumen" in s


def test_an_off_holiday_says_frost_protection_not_a_temperature():
    off = dict(ABS, off=True, temp=None)
    assert "Aus (Frostschutz)" in status(st_with([{"absence": off}] * 3), ROOM_IDS)


def test_a_holiday_that_is_stored_but_not_active_is_not_announced_as_running():
    later = dict(ABS, active=False)
    assert status(st_with([{"absence": later}] * 3), ROOM_IDS) == ""


def test_nothing_overriding_gives_an_empty_string_so_the_card_can_say_so():
    assert status(st_with([]), ROOM_IDS) == ""


def test_the_boost_countdown_is_shown_and_never_negative():
    """The deadline is built in the JS so the test and the code share one clock.

    It used to be a literal — 2026-10-01T09:05 with `remaining_s: 252` beside it
    — and that was fine only while the card trusted `remaining_s`. Counting from
    `until` is what fixed the countdown that would not tick, and it turned this
    test into a time bomb: the timestamp went into the past, a boost that ended
    four days ago correctly renders as nothing, and the test failed on the code
    being right (CI, 2026-10-05)."""
    b = {"boost": {"until": "@@UNTIL@@", "temp": 30.0,
                   "active": True, "remaining_s": 252}}
    expr = (f"boostStatus({json.dumps(st_with([b] * 2))}, {json.dumps(ROOM_IDS)})"
            .replace('"@@UNTIL@@"', "new Date(Date.now() + 252000).toISOString()"))
    s = call(expr)
    assert "4:1" in s, s          # 4:12, or 4:11 if the second ticked over
    assert "2 Räumen" in s, s
    assert call("mmss(-99)") == "0:00"


def test_the_status_block_is_rendered_even_when_nothing_is_overriding():
    """Blank reads as "not loaded". It has to say that the plan is running."""
    out = run_js(
        CARD,
        "(() => {"
        " const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); c._built = true;"
        f" c._hass = {{ states: {json.dumps(st_with([]))} }};"
        " let status = '';"
        " const mk = (setter) => ({ addEventListener() {}, querySelector: () => null,"
        "   querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} },"
        "   removeAttribute() {}, setAttribute() {},"
        "   set innerHTML(v) { setter(v); }, get innerHTML() { return ''; },"
        "   set textContent(v) {}, get textContent() { return ''; } });"
        " c.querySelector = (sel) => sel === '.status' ? mk(v => { status = v; }) : mk(() => {});"
        " c.querySelectorAll = () => [];"
        " c._render();"
        " return status; })()",
    )
    assert "Wochenplan" in out


def test_all_rooms_is_an_explicit_flag_not_an_empty_list():
    """"Nothing ticked = all" reads as "none" — the trap the first version had."""
    src = CARD.read_text(encoding="utf-8")
    assert "allRooms: true" in src
    flag = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); return [c._form.allRooms, c._form.rooms.length]; })()")
    assert flag == [True, 0]


def test_the_urlaub_form_starts_open_because_it_is_the_section():
    """It used to open behind "Bearbeiten". That button is gone ("dont show
    bearbeiten", 2026-10-20) and the box is the section, so a closed form would
    be a section with nothing in it and no way to open it."""
    assert run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); return c._openForm; })()") is True


# ── the fields are picked, not typed ─────────────────────────────────────────
# "i want to change it in a way that we a pick a date from the calendar"
# (2026-10-20). These two are the mechanism; the rendered proof that an input
# survives being typed into lives in tests/test_actions_card_press_across_tick.py,
# because it needs a real DOM.


def test_the_field_markup_carries_no_values():
    """THE CAUSE OF THE YEAR BUG, asserted where it can be seen without a
    browser. While the values were interpolated into the markup, the markup
    changed whenever a value did — and the guard in `_renderFields` then let
    `innerHTML` replace the block a resident was typing into."""
    for kind in ("sick", "holiday"):
        markup = rendered_fields(kind)
        # The <option>s keep their values — those are the choices, not a state.
        # It is the INPUTS that must come out of the template bare.
        for tag in re.findall(r"<input[^>]*>", markup):
            assert "value=" not in tag, (kind, tag)
        assert "selected" not in markup, (kind, markup)


def test_the_values_are_written_onto_the_elements_instead():
    src = CARD.read_text(encoding="utf-8")
    assert "_syncFieldValues()" in src
    # And never onto the one with focus: assigning .value to a date input
    # restarts it at its first segment, which is the same bug from the far side.
    sync = src[src.index("  _syncFieldValues() {"):]
    assert "activeElement" in sync[:900], sync[:900]


def test_the_whole_date_field_opens_the_calendar():
    """A date input opens its picker only from the small icon at its end, which
    leaves typing as the obvious path on a phone — and typing is what broke."""
    src = CARD.read_text(encoding="utf-8")
    assert "showPicker" in src
    i = src.index("showPicker")
    guarded = src[max(0, i - 400):i + 200]
    # It throws without a user gesture and is absent in older browsers; either
    # way the field must still type normally rather than the card throwing.
    assert "try {" in guarded and "catch" in guarded, guarded


# ── no form has an off-switch ───────────────────────────────────────────────
# Sickness never had one: someone in bed wants the room WARMER, so it was an
# offer nobody wants and a mis-tap with a cold night behind it (Thomas,
# 2026-09-23). The holiday form had one until 2026-10-20, when it went for the
# same reason over a longer absence.

def test_no_form_offers_an_off_switch():
    for kind in ("sick", "holiday"):
        markup = rendered_fields(kind)
        assert "Aus · Frostschutz" not in markup, kind
        assert 'class="off"' not in markup, kind


def test_a_temperature_is_the_only_thing_a_holiday_can_set():
    markup = rendered_fields("holiday")
    assert 'class="temp"' in markup
    assert "Zieltemp." in markup


def test_a_body_carries_a_temperature_even_if_off_was_left_set():
    """Must-not-flag. `off` is gone from the form, but an older card's stored
    value could still reach `absenceBody` through a config or a replay."""
    for kind, extra in (("sick", {"hours": 6}), ("holiday", {"start": "2026-10-01",
                                                             "end": "2026-10-08"})):
        out = body(dict({"kind": kind, "temperature": 22, "off": True}, **extra))
        assert "switch_off" not in out, kind
        assert out["temperature"] == 22, kind


# ── the labels are Ahmad's, verbatim ────────────────────────────────────────
# Taken from ha-dashboard-automation/templates/profile_view_template.j2, read
# 2026-09-23. Residents of the previous system read these words; inventing new
# ones would have been a second vocabulary for the same three actions.

def test_the_three_buttons_carry_the_old_labels():
    """"Boost setzen" lost its verb ("rename to just boost not boost setzen",
    2026-10-20); the other two are untouched."""
    markup = run_js(CARD, BUILD_MARKUP)
    for label in (">Boost<", "Alle → KI", "Alle AUS"):
        assert label in markup, label


def test_the_form_actions_carry_the_old_labels():
    markup = run_js(CARD, BUILD_MARKUP)
    assert "Aktivieren" in markup and "Deaktivieren" in markup
    assert ">Urlaub " in markup


def test_the_field_labels_are_his_too():
    assert "⏱️ Dauer ab jetzt" in rendered_fields("sick")
    assert "🌡️ Zieltemp." in rendered_fields("sick")


def test_alle_ki_also_ends_a_running_boost():
    """His layout had three buttons, not four. A resident who wants the plan back
    does not care which override is in the way — so "Alle → KI" cancels the boost
    too, or "back to the plan" leaves one running for another four minutes."""
    src = CARD.read_text(encoding="utf-8")
    i = src.index("async _planAll()")
    body_src = src[i:i + 900]
    assert "cancel_boost" in body_src
    assert 'hvac_mode: "auto"' in body_src


# ── a running boost can be ended from here too ───────────────────────────────
# Asked for on 2026-10-05: "we also need a beenden button in the profil to stop
# boost for all selected rooms". The card could start a boost in every room and
# offered no way out of one; the only escape was "Alle → KI", which also
# overwrites the stored decision of every room that was not boosting.

#: Runs `_endBoost` against a stubbed hass and reports what it sent.
END_BOOST = """
(() => {
  const sent = [];
  const said = [];
  const c = Object.create(GaHeatingActionsCard.prototype);
  c.setConfig({});
  c._hass = {
    states: %s,
    callService: (d, s, data) => {
      sent.push({ domain: d, service: s, data });
      return Promise.resolve();
    },
  };
  c._say = (kind, text) => said.push({ kind, text });
  // AWAITED: `_endBoost` suspends on its first service call, and without this
  // the harness read the list after one room and before the summary line.
  return c._endBoost().then(() => JSON.stringify({ sent, said }));
})()
"""


def _boosting(*room_ids):
    """States where the named rooms have a boost running, plus one that has not."""
    out = {
        "climate.wohnzimmer": {"attributes": {"friendly_name": "Wohnzimmer",
                                              "valves": [], "max_temp": 30}},
        "climate.bad": {"attributes": {"friendly_name": "Badezimmer",
                                       "valves": [], "max_temp": 30}},
        "climate.schlaf": {"attributes": {"friendly_name": "Schlafzimmer",
                                          "valves": [], "max_temp": 30}},
    }
    for rid in room_ids:
        out[rid]["attributes"]["override"] = {
            "boost": {"active": True, "until": "2099-01-01T00:00:00", "temp": 30}}
    return out


def end_boost(states_obj):
    return json.loads(run_js(CARD, END_BOOST % json.dumps(states_obj)))


def test_the_button_ends_every_room_that_is_boosting():
    """THE RED ONE: there was no way out of a whole-home boost."""
    got = end_boost(_boosting("climate.bad", "climate.schlaf"))
    assert {c["service"] for c in got["sent"]} == {"cancel_boost"}
    assert {c["data"]["entity_id"] for c in got["sent"]} == {"climate.bad", "climate.schlaf"}


def test_a_room_without_a_boost_is_left_alone():
    """The defect this avoids is the one "Alle → KI" has: it would put a room
    that chose AUS back on the plan on its way past."""
    got = end_boost(_boosting("climate.bad"))
    assert [c["data"]["entity_id"] for c in got["sent"]] == ["climate.bad"]


def test_nothing_running_says_so_instead_of_reporting_success():
    got = end_boost(_boosting())
    assert got["sent"] == []
    assert got["said"] == [{"kind": "ok", "text": "Kein Boost aktiv."}]


def test_it_reports_how_many_rooms_it_reached():
    got = end_boost(_boosting("climate.bad", "climate.schlaf"))
    assert got["said"] == [{"kind": "ok", "text": "Boost in 2 Räumen beendet."}]


def test_one_room_is_one_room_not_one_of_one():
    """The toast said "1 von 1 Räumen" for the commonest case there is."""
    got = end_boost(_boosting("climate.bad"))
    assert got["said"] == [{"kind": "ok", "text": "Boost in 1 Raum beendet."}]


def test_a_partial_failure_counts_and_names_what_it_did_not_reach():
    """The real counts, and which room is still boosting."""
    expr = (END_BOOST % json.dumps(_boosting("climate.bad", "climate.schlaf"))).replace(
        "return Promise.resolve();",
        "return data.entity_id === 'climate.schlaf'"
        " ? Promise.reject(new Error('x')) : Promise.resolve();")
    got = json.loads(run_js(CARD, expr))
    assert got["said"] == [{"kind": "err", "text":
                            "Boost in 1 von 2 Räumen beendet — nicht erreicht: Schlafzimmer."}]


# ── "Sonderplan beenden" ends what the status line describes ────────────────
# A review changed `_endAbsence` to a wrong route and the suite stayed green.
# The route is pinned here; ga_heating answers DELETE /api/ga_heating/absence.

END_ABSENCE = """
(() => {
  const sent = [];
  const said = [];
  const c = Object.create(GaHeatingActionsCard.prototype);
  c.setConfig({});
  c._hass = {
    states: %s,
    callApi: (method, path, data) => {
      sent.push({ method, path, data });
      return Promise.resolve({});
    },
    callService: (d, s, data) => {
      sent.push({ service: d + "." + s, data });
      return Promise.resolve();
    },
  };
  c._say = (kind, text) => said.push({ kind, text });
  return c._endAbsence().then(() => JSON.stringify({ sent, said }));
})()
"""


def _absent(*room_ids):
    out = _boosting()
    for rid in room_ids:
        out[rid]["attributes"]["override"] = {"absence": {
            "active": True, "start": "2026-10-01T00:00:00", "end": "2026-10-08T12:00:00",
            "temp": 16, "off": False}}
    return out


def test_end_absence_deletes_over_the_absence_route_for_each_running_room():
    got = json.loads(run_js(CARD, END_ABSENCE % json.dumps(_absent("climate.bad",
                                                                   "climate.schlaf"))))
    assert got["sent"] == [
        {"method": "delete", "path": "ga_heating/absence", "data": {"entity_id": "climate.bad"}},
        {"method": "delete", "path": "ga_heating/absence",
         "data": {"entity_id": "climate.schlaf"}},
    ]
    assert got["said"] == [{"kind": "ok", "text": "Urlaub in 2 von 2 Räumen beendet."}]


def test_end_absence_with_nothing_running_sends_nothing():
    got = json.loads(run_js(CARD, END_ABSENCE % json.dumps(_absent())))
    assert got["sent"] == []
    assert got["said"] == [{"kind": "ok", "text": "Kein Urlaub aktiv."}]


def test_no_mode_is_sent_with_it():
    """Dropping the boost IS the way back — it never replaced a room's stored
    decision. A `set_hvac_mode` here would turn a room that was AUS before the
    boost into a heating one."""
    got = end_boost(_boosting("climate.bad"))
    assert not any(c["domain"] == "climate" for c in got["sent"])


def test_the_button_is_hidden_until_a_boost_is_running():
    """A permanent "Boost beenden" beside "Boost setzen" reads as the other half
    of a pair of settings rather than as a way out of something in progress."""
    markup = run_js(CARD, BUILD_MARKUP)
    assert "Boost beenden" in markup
    i = markup.index("Boost beenden")
    assert "hidden" in markup[max(0, i - 120):i], markup[max(0, i - 120):i]


def test_german_declines_and_so_does_the_card():
    """"1 Räume im Boost" and "in 1 Raum/Räumen" were both on screen. A dashboard
    that cannot count in the language it speaks reads like a machine."""
    assert run_js(CARD, "nRooms(1)") == "1 Raum"
    assert run_js(CARD, "nRooms(3)") == "3 Räume"
    one = _boosting("climate.bad")
    line = run_js(CARD, f"boostStatus({json.dumps(one)}, {json.dumps(list(one))})")
    assert "1 Raum" in line and "Räume" not in line, line


def test_the_plural_after_in_takes_the_dative():
    """Both status lines sit after "in", where the plural takes -n. A helper
    without the case just moves the error from "1 Räume" to "in 2 Räume"."""
    assert run_js(CARD, "nRooms(2, true)") == "2 Räumen"
    assert run_js(CARD, "nRooms(1, true)") == "1 Raum"
    two = _boosting("climate.bad", "climate.schlaf")
    line = run_js(CARD, f"boostStatus({json.dumps(two)}, {json.dumps(list(two))})")
    assert line.endswith("in 2 Räumen"), line


# --- and the actions use it --------------------------------------------------


def _card_with(form):
    """A card whose form is `form`, over a three-room flat."""
    states = {r: {"attributes": {"friendly_name": r[-1].upper(), "valves": ["climate.v"],
                                 "area_id": r[-1], "max_temp": 30}} for r in ROOMS}
    states["climate.v"] = {"attributes": {"local_temperature": 21}}
    return (
        " const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({});"
        f" Object.assign(c._form, {json.dumps(form)});"
        " const sent = [], said = [];"
        f" c._hass = {{ states: {json.dumps(states)},"
        "   callService: (d, s, data) => { sent.push(s + ':' + data.entity_id);"
        "     return Promise.resolve(); },"
        "   callApi: () => Promise.resolve() };"
        " c._say = (k, t) => said.push({ kind: k, text: t });"
    )


def _run(form, method):
    return json.loads(run_js(CARD, "(() => {" + _card_with(form)
                             + f" return c.{method}().then(() =>"
                             + " JSON.stringify({ sent, said })); })()"))


def test_boost_acts_on_every_room_with_no_picker_to_get_wrong():
    """THE ONE THE PICKER EXISTED FOR, from the other side. The row of chips sat
    above this button and the button ignored it — pick one room, press it, the
    whole flat went to 30 °C. The row is gone ("whatever thez click is
    automaticallz applied to everzthing", 2026-10-20), so the scope the card
    ships with has to BE the flat: the defect is now impossible rather than
    merely absent."""
    got = _run({}, "_boostAll")
    assert [c.split(":")[1] for c in got["sent"]] == ROOMS
    assert got["said"] == []


def test_boost_with_no_rooms_at_all_refuses_rather_than_reporting_success():
    """Not reachable by tapping any more — a flat with no thermostat reaches it.
    `_selected()` answers with an empty list there, and a success message over
    zero requests is the lie this refusal exists to prevent."""
    got = _run({"allRooms": False, "rooms": []}, "_boostAll")
    assert got["sent"] == []
    assert got["said"] == [{"kind": "err", "text": "Kein Raum ausgewählt."}]


def test_boost_by_default_still_means_the_whole_home():
    got = _run({"allRooms": True, "rooms": []}, "_boostAll")
    assert [s.split(":")[1] for s in got["sent"]] == ROOMS


def test_alle_aus_is_the_whole_flat_whatever_the_form_says():
    """Must-not-flag. The label says "Alle AUS" — Ahmad's own words from the
    previous system — and a button that says what it does is allowed to say it.
    Kept pinned after the picker went: the form still carries a scope that the
    Urlaub box writes to, and these two buttons must stay deaf to it."""
    got = _run({"allRooms": False, "rooms": ["climate.b"]}, "_offAll")
    assert [s.split(":")[1] for s in got["sent"]] == ROOMS


def test_alle_ki_is_deaf_to_it_too():
    got = _run({"allRooms": False, "rooms": ["climate.b"]}, "_planAll")
    assert {s.split(":")[1] for s in got["sent"]} == set(ROOMS)


def test_ending_a_sonderplan_on_nothing_does_not_report_zero_of_zero():
    """"Sonderplan in 0 von 0 Räumen aufgehoben" is a lie with a number in it."""
    got = _run({"allRooms": False, "rooms": []}, "_cancelAbsence")
    assert got["said"] == [{"kind": "err", "text": "Kein Raum ausgewählt."}]


# --- the blocks say which buttons share a scope ------------------------------
# "here at the beginneing we have boost and we explain it but this section isnt
# only about boost and teh boost button is down along alle ki and..."
# (2026-10-05).
#
# One heading said "Boost" over three actions, two of which are not a boost —
# and the room picker under it governed the first and deliberately not the other
# two. A reader had to KNOW that, so the layout was split: picker + Boost in one
# block, the two whole-home buttons under a heading of their own.
#
# THE SPLIT IS GONE because what it was explaining is gone. With no picker all
# three buttons have the same scope, so they are one row ("place all 3 buttons
# next to each other", 2026-10-20) and the "Ganze Wohnung" heading would be a
# label on nothing. These tests are the row.


def _markup():
    return run_js(CARD, BUILD_MARKUP)


def _at(markup, needle):
    """Where an ELEMENT is, not where its words are.

    Anchored on the tag boundary because the first version of these tests was
    not: a `<!-- … -->` in the template explaining why "Boost setzen ignores the
    picker" was a defect sat earlier in the markup than the button, and the test
    measured the prose. HTML comments are DOM.
    """
    i = markup.index(needle)
    assert markup.count(needle) == 1, f"{needle!r} is not unique in the markup"
    return i


#: The row the three actions live in, markup only.
def _quick_row(markup):
    a = markup.index('<div class="quick">')
    return markup[a:markup.index("</div>", a)]


def test_the_three_actions_are_one_row():
    """THE ASK. They were a row of one and a row of two under separate headings;
    with one scope between them that split says something untrue."""
    row = _quick_row(_markup())
    assert _at(row, ">Boost<") < _at(row, ">Alle → KI<") < _at(row, ">Alle AUS<")


def test_the_three_actions_stay_a_row_on_a_phone():
    """THE ONE THAT ALMOST SHIPPED WRONG. The row was a grid with a 460px
    breakpoint that gave it one column — which is every phone this runs on, so
    "next to each other" was true in the markup and false on the device.

    Asserted on the CSS because the stacking was never in the markup: the
    browser harness mounts the card at 375px and checks the rendered row."""
    src = CARD.read_text(encoding="utf-8")
    style = src[src.index("<style>"):src.index("</style>")]
    quick = style[style.index(".quick {"):]
    quick = quick[:quick.index("}") + 1]
    assert "display: flex" in quick, quick
    # And no media query puts it back: that is exactly how it stacked before.
    for block in style.split("@media")[1:]:
        rule = block[:block.index("}") + 1] if "}" in block else block
        assert ".quick {" not in rule, rule


def test_ending_a_boost_stays_with_the_boost():
    """A way out of something running belongs beside the thing that started it,
    not under a heading of its own."""
    assert ">Boost beenden<" in _quick_row(_markup())


def test_there_is_no_heading_left_over_from_the_split():
    """"Ganze Wohnung" named the scope the other two had and Boost did not. All
    three have it now, so the heading would be a label on nothing — and a
    heading over a single row reads as a claim that the row is special."""
    assert "Ganze Wohnung" not in _markup()


def test_the_frost_line_sits_in_the_boost_explanation():
    """It is about what AUS leaves behind. It was a line under the button row;
    the page carries no loose prose any more, so it moved into the panel the
    "i" opens — the one place a resident goes to ask what these buttons do."""
    m = _markup()
    tip = m[m.index('class="tip boosttip"'):]
    tip = tip[:tip.index("</div>")]
    assert "frosthint" in tip, tip


def test_every_block_after_the_first_is_ruled_off():
    """The blocks are what says which buttons share a scope, so they have to look
    separate. A heading alone reads as a label on the row above it."""
    m = _markup()
    before = m[max(0, _at(m, ">Urlaub ") - 120):_at(m, ">Urlaub ")]
    assert "rule" in before, before


def test_the_labels_are_untouched_by_the_regrouping():
    """Must-not-flag. Moving buttons is not licence to rename them — these are
    Ahmad's words from the previous system and residents read them there. Only
    "Boost setzen" changed, and he asked for that one by name."""
    m = _markup()
    for label in (">Boost<", "Alle → KI", "Alle AUS"):
        assert label in m, label


# --- the explanations live behind an "i" ------------------------------------
# "keep all explanation in a tooltip or i icon that shows the text, we dont want
# extra text in the page" (2026-10-20).
#
# They were on the heading line, in brackets, which was the previous ask
# ("explanation of boost put in parentheses same line as boost not below",
# 2026-10-05). On a phone that line wrapped under the heading anyway, so the
# page still read as prose with controls in it. Now each heading carries one
# round button and the sentence is in a panel it opens.


def test_each_section_heading_carries_an_i_button():
    m = _markup()
    for tip in ("boost", "urlaub"):
        assert 'data-tip="%s"' % tip in m, tip


def test_the_explanation_starts_hidden_because_that_is_the_point():
    """A panel that is open on arrival is the extra text he asked us to remove,
    with a button added."""
    m = _markup()
    for cls in ("tip boosttip", "tip urlaubtip"):
        i = m.index('class="%s"' % cls)
        assert "hidden" in m[i:m.index(">", i)], cls


def test_the_i_button_says_whether_it_is_open():
    """It is the only thing on screen that says a panel exists, so a screen
    reader has to get the state from it."""
    src = CARD.read_text(encoding="utf-8")
    assert 'aria-expanded="false"' in src
    assert 'el.setAttribute("aria-expanded", String(open))' in src


def test_the_boost_explanation_moved_into_its_panel():
    """THE ASK, structurally: the sentence is no longer a child of the heading."""
    m = _markup()
    h4 = m[m.index(">Boost "):m.index("</h4>")]
    assert "boosthint" not in h4, h4
    tip = m[m.index('class="tip boosttip"'):]
    assert "boosthint" in tip[:tip.index("</div>")]


def test_the_page_carries_no_loose_paragraph_of_prose():
    """"we dont want extra text in the page". A `<p class="hint wide">` under a
    form is exactly that, and the Urlaub form had one."""
    src = CARD.read_text(encoding="utf-8")
    holiday = src[src.index("const fieldsHtml"):src.index("if (fieldsHtml ===")]
    tail = holiday[holiday.index(": `<label>Von"):]
    assert "hint wide" not in tail, tail


def test_the_explanation_escapes_the_headings_shouting():
    """Headings are uppercased by CSS, and the hints inside the panel were
    styled as part of a heading line before this moved. Uninherited, they read
    as VENTILE KURZZEITIG GANZ OEFFNEN."""
    src = CARD.read_text(encoding="utf-8")
    style = src[src.index("<style>"):src.index("</style>")]
    rule = style[style.index(".tip .sub"):]
    assert "text-transform: none" in rule.split("}")[0]


def _hint(states):
    """The text `_render` puts in the boost explanation, for these states."""
    return run_js(CARD, """
      (() => {
        const c = Object.create(GaHeatingActionsCard.prototype);
        c.setConfig({}); c._built = true; c._hass = { states: __STATES__ };
        let hintText = '';
        const mk = (setter) => ({ addEventListener() {}, querySelector: () => null,
          querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} },
          removeAttribute() {}, setAttribute() {},
          set innerHTML(v) {}, get innerHTML() { return ''; },
          set textContent(v) { setter(v); }, get textContent() { return ''; } });
        c.querySelector = (sel) =>
          sel === '.boosthint' ? mk(v => { hintText = v; }) : mk(() => {});
        c.querySelectorAll = () => [];
        c._render();
        return hintText;
      })()
    """.replace("__STATES__", json.dumps(states)))


def test_the_idle_explanation_is_a_sentence_now_that_it_has_a_panel():
    """The brackets were there because it rode on the heading line. In a panel
    of its own a bracketed fragment reads like a footnote to nothing."""
    assert _hint({}) == "Öffnet die Ventile kurzzeitig ganz."


def test_the_running_explanation_does_not_say_boost_twice():
    """The panel opens from a heading that already says BOOST, so "Boost läuft
    in 2 Räumen" says it twice. And after "in" the plural takes the dative."""
    live = _boosting("climate.bad", "climate.schlaf")
    got = _hint(live)
    assert "im Boost" not in got, got
    assert "2 Räumen" in got, got
    assert "2 Räumen" in got, got


def test_one_boosted_room_still_declines():
    got = _hint(_boosting("climate.bad"))
    assert "1 Raum " in got or got.count("1 Raum") == 1, got
    assert "Räumen" not in got, got


# --- what the resident no longer sees ---------------------------------------
# A batch of removals, 2026-10-20. Each one is here because the markup is the
# only thing that decides it: the code behind every one of these still exists
# and still works, so nothing else would notice if a block came back.


def test_there_is_no_room_picker_anywhere_in_the_markup():
    """"remove room choice section, whatever thez click is automaticallz applied
    to everzthing". The scope machinery stays — `_selected()`, `allRooms`, the
    Urlaub box's own reach — so a row of chips is one template line away."""
    m = _markup()
    for gone in ('class="rooms"', "Räume wählen", 'class="chip', "data-all="):
        assert gone not in m, gone


def test_the_card_offers_no_sickness_plan():
    """"remove krankheit". `absenceBody` still accepts `kind: "sick"` — it is
    how the hours form is specified and tested — but nothing on screen asks for
    one, so the only kind a resident can set is a holiday."""
    m = _markup()
    assert "Krankheit" not in m
    assert 'data-kind="sick"' not in m
    assert run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); return c._form.kind; })()") == "holiday"


def test_there_is_no_bearbeiten_button():
    """"dont show bearbeiten". It was the only way into the Urlaub form, which
    is why the form now starts open."""
    m = _markup()
    assert "Bearbeiten" not in m
    assert "toggle-form" not in m


def test_removing_that_button_did_not_leave_a_listener_on_it():
    """THE RED ONE this batch could have shipped: the listener was unguarded, so
    with the button gone the card threw on its first render and the whole
    section rendered as nothing."""
    src = CARD.read_text(encoding="utf-8")
    i = src.index('querySelector(".toggle-form")')
    head = src[max(0, i - 200):i]
    assert "const tfBtn" in head or "if (" in head, src[max(0, i - 200):i + 80]
    assert 'this.querySelector(".toggle-form").addEventListener' not in src


def test_hydraulic_balancing_is_not_offered_to_residents():
    """"remove hydraulic balancing section, keep as an internal feature that only
    we can trigger but not the user". The service existing was the whole gate
    before, and every device that runs ga_heating 0.13+ has it."""
    src = CARD.read_text(encoding="utf-8")
    i = src.index("const offered =")
    gate = src[i:src.index(";", i)]
    assert "show_ichb" in gate, gate


# ── ending a holiday hands the rooms back to KI (2026-10-21) ────────────────
# "what happens when we deactivate the urlaub schedue? it should set all
# thermostat back to KI".
#
# Deleting the override alone does not do it. An absence is a LAYER on top of
# the room's mode, never a change to it — ga_heating writes the stored mode in
# exactly three places (a press on the room, a hand on the radiator, a takeover
# into manual) and ending a holiday is none of them. So the delete only reveals
# what was underneath: KI comes back by itself, MANUELL and AUS do not.

_ABS = {"active": True, "temp": 16, "end": "2026-11-01T12:00:00"}

END_ABSENCE = """
(() => {
  const c = Object.create(GaHeatingActionsCard.prototype);
  c.setConfig({});
  const calls = [], said = [];
  c._hass = { states: %s,
    callApi: (m, path, data) => { calls.push(m + " " + path + " " + data.entity_id);
      return %s ? Promise.reject(new Error("held")) : Promise.resolve({}); },
    callService: (d, s, data) => { calls.push(d + "." + s + " " + data.entity_id
      + " " + (data.hvac_mode || "")); return Promise.resolve(); } };
  c._say = (k, t) => said.push({ kind: k, text: t });
  return c._endAbsence().then(() => JSON.stringify({ calls, said }));
})()
"""


def _on_holiday(*room_ids):
    out = {
        "climate.bad": {"attributes": {"friendly_name": "Badezimmer",
                                       "valves": [], "max_temp": 30}},
        "climate.schlaf": {"attributes": {"friendly_name": "Schlafzimmer",
                                          "valves": [], "max_temp": 30}},
    }
    for rid in room_ids:
        out[rid]["attributes"]["override"] = {"absence": dict(_ABS)}
    return out


def end_absence(states_obj, reject="false"):
    return json.loads(run_js(CARD, END_ABSENCE % (json.dumps(states_obj), reject)))


def test_ending_a_holiday_also_puts_the_room_back_on_the_plan():
    """THE ASK. Without the second call a room that was MANUELL or AUS when the
    holiday was booked comes back heating to a dial setting from a fortnight
    ago — or not heating at all — with nothing on screen to explain why."""
    got = end_absence(_on_holiday("climate.bad"))
    assert got["calls"] == [
        "delete ga_heating/absence climate.bad",
        "climate.set_hvac_mode climate.bad auto",
    ], got


def test_the_delete_goes_first():
    """ORDER MATTERS: while the override is still stored it outranks the room's
    own mode, so an `auto` sent before it would be overwritten by the next
    tick."""
    calls = end_absence(_on_holiday("climate.bad", "climate.schlaf"))["calls"]
    for i in range(0, len(calls), 2):
        assert calls[i].startswith("delete "), calls
        assert calls[i + 1].startswith("climate.set_hvac_mode"), calls


def test_every_room_on_holiday_is_handed_back():
    got = end_absence(_on_holiday("climate.bad", "climate.schlaf"))
    modes = [c for c in got["calls"] if c.startswith("climate.set_hvac_mode")]
    assert sorted(modes) == ["climate.set_hvac_mode climate.bad auto",
                             "climate.set_hvac_mode climate.schlaf auto"], got


def test_a_room_with_no_holiday_is_left_alone():
    """Scoped to the rooms the holiday covered. One the resident deliberately
    left out of it is not ours to switch on because somebody came home."""
    got = end_absence(_on_holiday("climate.bad"))
    assert "climate.schlaf" not in " ".join(got["calls"]), got


def test_a_room_whose_holiday_could_not_be_dropped_is_not_set_to_KI():
    """MUST-NOT-FLAG. The override is still stored and still outranks the mode,
    so an `auto` here would change the room's stored mode for later while
    changing nothing now — and the toast would claim it is back on plan."""
    got = end_absence(_on_holiday("climate.bad"), reject="true")
    assert not any(c.startswith("climate.set_hvac_mode") for c in got["calls"]), got
    assert got["said"][0]["kind"] == "err", got


def test_nothing_on_holiday_says_so_instead_of_touching_anything():
    got = end_absence(_on_holiday())
    assert got["calls"] == []
    assert got["said"] == [{"kind": "ok", "text": "Kein Urlaub aktiv."}]


def test_the_toast_says_the_rooms_are_back_on_the_plan():
    """The resident pressed one button and two things happened; a message that
    mentions only the holiday leaves the second one invisible."""
    got = end_absence(_on_holiday("climate.bad"))
    assert "Wochenplan" in got["said"][0]["text"], got


# ── activating a holiday normalises the room first (2026-10-21) ────────────
# "i activated urlaub on all rooms, now each room shows different mode and
# tempertaure". A holiday does NOT change the room's mode — ga_heating's
# `_HEAT_NOW` is only a boost and the balancing run — so it layers over
# whatever each room happens to be in. Booked while two rooms were on MANUELL
# and one on KI, the flat read as three different things for the whole
# holiday, with stale manual periods counting down underneath.
#
# The mirror of what ending one already does.

APPLY_ABSENCE = """
(() => {
  const c = Object.create(GaHeatingActionsCard.prototype);
  c.setConfig({});
  const calls = [], said = [];
  c._hass = { states: %s,
    callApi: (m, path, data) => { calls.push(m + " " + path + " " + data.entity_id);
      return %s ? Promise.reject(new Error("nope")) : Promise.resolve({}); },
    callService: (d, s, data) => { calls.push(d + "." + s + " " + data.entity_id
      + " " + (data.hvac_mode || "")); return Promise.resolve(); } };
  c._say = (k, t) => said.push({ kind: k, text: t });
  Object.assign(c._form, { start: "2026-12-20", end: "2026-12-27", temperature: 13 });
  return c._applyAbsence().then(() => JSON.stringify({ calls, said }));
})()
"""


def _apply_absence(reject="false"):
    states = {
        "climate.bad": {"attributes": {"friendly_name": "Badezimmer",
                                       "valves": [], "max_temp": 30}},
        "climate.schlaf": {"attributes": {"friendly_name": "Schlafzimmer",
                                          "valves": [], "max_temp": 30}},
    }
    return json.loads(run_js(CARD, APPLY_ABSENCE % (json.dumps(states), reject)))


def test_booking_a_holiday_puts_every_room_on_KI_first():
    """THE ORDER IS THE TEST. A press on the room ends what somebody asked for
    earlier — `_end_requested_overrides` pops an ACTIVE absence — so a KI sent
    AFTER the POST would delete the holiday just written, in the one case that
    matters most: a holiday starting now."""
    calls = _apply_absence()["calls"]
    for room in ("climate.bad", "climate.schlaf"):
        ki = calls.index(f"climate.set_hvac_mode {room} auto")
        post = calls.index(f"post ga_heating/absence {room}")
        assert ki < post, (room, calls)


def test_every_selected_room_is_normalised_not_just_the_first():
    calls = _apply_absence()["calls"]
    modes = [c for c in calls if c.startswith("climate.set_hvac_mode")]
    assert sorted(modes) == ["climate.set_hvac_mode climate.bad auto",
                             "climate.set_hvac_mode climate.schlaf auto"], calls


def test_a_refused_holiday_still_reports_the_refusal():
    """MUST-NOT-FLAG: normalising first must not swallow the route's 400. The
    room is on KI either way, which is where a room without a holiday belongs."""
    got = _apply_absence(reject="true")
    assert got["said"][0]["kind"] == "err", got
    assert "abgelehnt" in got["said"][0]["text"], got
