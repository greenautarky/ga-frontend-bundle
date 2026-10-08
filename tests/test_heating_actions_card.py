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


def test_holiday_with_heating_off_sends_switch_off_not_a_temperature():
    """NOT `off`: YAML 1.1 reads a bare `off` key as False, which is why
    ga_heating's schema names the field `switch_off`."""
    out = body({"kind": "holiday", "start": "2026-10-01", "end": "2026-10-08",
                "off": True, "temperature": 16})
    assert out["switch_off"] is True
    assert "temperature" not in out


def test_a_range_that_runs_backwards_is_refused_here():
    out = body({"kind": "holiday", "start": "2026-10-08", "end": "2026-10-01",
                "temperature": 16})
    assert isinstance(out, str) and "Ende" in out


def test_neither_a_temperature_nor_off_is_refused_here():
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


def test_the_times_are_quarter_hours_and_literal_24h():
    opts = call("TIME_OPTIONS")
    assert len(opts) == 96
    assert opts[0] == "00:00" and opts[-1] == "23:45"
    assert not any("AM" in o or "PM" in o for o in opts)


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
    assert "Sonderplan aktiv" in s and "16 °C" in s and "alle Räume" in s
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


def test_the_form_starts_closed_and_the_status_does_not():
    flags = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); return [c._openForm, c._openRooms]; })()")
    assert flags == [False, False]


# ── sickness has no off-switch ───────────────────────────────────────────────
# Someone in bed wants the room WARMER. An off-switch on that form is an offer
# nobody wants and a mis-tap with a cold night behind it. (Thomas, 2026-09-23.)

def test_the_sickness_form_offers_no_off_switch():
    assert "Aus · Frostschutz" not in rendered_fields("sick")
    assert 'class="off"' not in rendered_fields("sick")


def test_the_holiday_form_still_offers_it():
    assert "Aus · Frostschutz" in rendered_fields("holiday")


def test_a_sickness_body_carries_a_temperature_even_if_off_was_left_set():
    """Switching type from holiday to sickness must not smuggle `off` across."""
    out = body({"kind": "sick", "hours": 6, "temperature": 22, "off": True})
    assert "switch_off" not in out
    assert out["temperature"] == 22


# ── the labels are Ahmad's, verbatim ────────────────────────────────────────
# Taken from ha-dashboard-automation/templates/profile_view_template.j2, read
# 2026-09-23. Residents of the previous system read these words; inventing new
# ones would have been a second vocabulary for the same three actions.

def test_the_three_buttons_carry_the_old_labels():
    markup = run_js(CARD, BUILD_MARKUP)
    for label in ("Boost setzen", "Alle → KI", "Alle AUS"):
        assert label in markup, label


def test_the_form_toggle_and_actions_carry_the_old_labels():
    markup = run_js(CARD, BUILD_MARKUP)
    assert "Aktivieren" in markup and "Deaktivieren" in markup
    assert "Sonderpläne (Krankheit und Urlaub)" in markup
    toggle = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingActionsCard.prototype);"
        " c.setConfig({}); c._built = true; c._hass = { states: {} };"
        " let t = '';"
        " const mk = (setter) => ({ addEventListener() {}, querySelector: () => null,"
        "   querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} },"
        "   removeAttribute() {}, setAttribute() {},"
        "   set innerHTML(v) {}, get innerHTML() { return ''; },"
        "   set textContent(v) { setter(v); }, get textContent() { return ''; } });"
        " c.querySelector = (sel) =>"
        "   sel === '.toggle-form' ? mk(v => { t = v; }) : mk(() => {});"
        " c.querySelectorAll = () => [];"
        " c._render(); return t; })()")
    assert toggle == "Bearbeiten"


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
    assert got["said"] == [{"kind": "ok", "text": "Sonderplan in 2 von 2 Räumen beendet."}]


def test_end_absence_with_nothing_running_sends_nothing():
    got = json.loads(run_js(CARD, END_ABSENCE % json.dumps(_absent())))
    assert got["sent"] == []
    assert got["said"] == [{"kind": "ok", "text": "Kein Sonderplan aktiv."}]


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


# ── which rooms an action will touch, in words ───────────────────────────────
# "maybe a dropdown list?" (2026-10-05). The list stays a disclosure; what was
# missing is WHICH rooms are in scope while it is closed — see scopeLabel.

def scope(selected, all_rooms=False, open_=False):
    f = {"allRooms": all_rooms, "rooms": selected}
    rooms = ["climate.wohnzimmer", "climate.bad", "climate.schlaf"]
    return run_js(CARD, f"scopeLabel({json.dumps(_boosting())}, {json.dumps(rooms)}, "
                        f"{json.dumps(f)}, {json.dumps(open_)})")


def test_the_closed_row_names_the_rooms_it_will_act_on():
    """A count is the one thing a resident already knows — they just ticked them.
    What they cannot see with the list closed is WHICH."""
    assert scope(["climate.bad"]) == "▸ Räume: Badezimmer"


def test_two_names_then_a_number():
    """The row sits beside a checkbox on a phone."""
    got = scope(["climate.wohnzimmer", "climate.bad", "climate.schlaf"])
    assert got == "▸ Räume: Wohnzimmer, Badezimmer +1"


def test_all_rooms_says_so_rather_than_listing_the_flat():
    assert scope([], all_rooms=True) == "▸ Räume: alle"


def test_an_empty_selection_says_so():
    """Must-not-flag: "0 gewählt" and "Räume: " both read as a loading state.
    This is the one case where a resident presses Boost and nothing happens."""
    assert scope([]) == "▸ Kein Raum gewählt"


def test_the_caret_follows_the_disclosure():
    assert scope(["climate.bad"], open_=True).startswith("▾")


def test_a_room_is_named_never_identified():
    """The old profile view listed entity ids when an area had no name. A radio
    address in a room picker is the bug `roomName` exists to prevent."""
    assert "climate." not in scope(["climate.bad"])


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


# --- picking rooms -----------------------------------------------------------
# "when choosing the rooms thats the best way to list them. maybe a dropdow
# list?" (2026-10-05). It stayed a list of toggles and became ONE row: a
# checkbox, a summary button and a collapsed list of checkboxes were three
# controls for one job, and with "Alle Räume" ticked the room boxes were checked
# AND disabled — which looks exactly like selected.
#
# A dropdown was the other candidate and is worse where this is used:
# `<select multiple>` is a wheel on iOS that cannot express multi-select, a
# modal on Android that no theme reaches, and ctrl-click on desktop.
#
# The rule the row promises: FILLED MEANS THIS ROOM WILL BE TOUCHED. These tests
# are that promise — the chip state and `_selected()` are the same answer.

ROOMS = ["climate.a", "climate.b", "climate.c"]


def toggle(form, room_id, rooms=None):
    return json.loads(run_js(
        CARD,
        f"JSON.stringify(toggleRoom({json.dumps(rooms or ROOMS)}, "
        f"{json.dumps(form)}, {json.dumps(room_id)}))"))


ALL = {"allRooms": True, "rooms": []}


def test_tapping_a_lit_room_turns_that_one_off():
    """It is lit, so it is in scope, so tapping it takes it out. The old row
    could not express this at all: with "Alle" ticked the room boxes were
    disabled."""
    assert toggle(ALL, "climate.b") == {"allRooms": False,
                                        "rooms": ["climate.a", "climate.c"]}


def test_turning_one_off_leaves_the_rest_in_their_own_order():
    """The row is read left to right; a selection that reorders itself as it is
    edited makes the names move under the finger."""
    out = toggle({"allRooms": False, "rooms": ["climate.c", "climate.a", "climate.b"]},
                 "climate.a")
    assert out["rooms"] == ["climate.b", "climate.c"]


def test_tapping_a_dark_room_adds_it():
    assert toggle({"allRooms": False, "rooms": ["climate.a"]}, "climate.b") == {
        "allRooms": False, "rooms": ["climate.a", "climate.b"]}


def test_selecting_the_last_one_becomes_alle():
    """Otherwise the row shows every room lit beside a dark `Alle` — a difference
    with no meaning behind it. It also matters later: an explicit list of every
    room silently excludes a room added afterwards, and `alle` does not."""
    assert toggle({"allRooms": False, "rooms": ["climate.a", "climate.b"]},
                  "climate.c") == ALL


def test_the_last_lit_room_can_be_turned_off():
    """Nothing selected is a state a resident can reach, so the actions have to
    answer for it — see the refusals below."""
    assert toggle({"allRooms": False, "rooms": ["climate.c"]}, "climate.c") == {
        "allRooms": False, "rooms": []}


def test_a_single_room_flat_still_toggles():
    one = ["climate.only"]
    assert toggle(ALL, "climate.only", rooms=one) == {"allRooms": False, "rooms": []}
    assert toggle({"allRooms": False, "rooms": []}, "climate.only", rooms=one) == {
        "allRooms": True, "rooms": []}


def test_the_row_collapses_only_when_it_would_not_fit():
    """A flat with twelve rooms is a wall of chips above the button somebody came
    here to press. Three is one line and hiding it would cost a tap to answer
    "which rooms" — the question the row exists for."""
    assert int(run_js(CARD, "MAX_CHIPS")) >= 3
    src = CARD.read_text(encoding="utf-8")
    assert "rooms.length <= MAX_CHIPS || this._openRooms" in src


def test_a_chip_carries_its_own_state_for_a_screen_reader():
    src = CARD.read_text(encoding="utf-8")
    assert 'aria-pressed="${on}"' in src


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


def test_boost_acts_on_the_rooms_that_are_lit():
    """THE RED ONE, and it predates the chips: the picker sat directly above
    "Boost setzen" and the button ignored it — pick one room, press it, and the
    whole flat went to 30 °C. It went unnoticed because the picker was collapsed
    behind a disclosure and defaulted to "alle", so the two agreed in the only
    case anybody exercised."""
    got = _run({"allRooms": False, "rooms": ["climate.b"]}, "_boostAll")
    assert got["sent"] == ["boost:climate.b"]


def test_boost_with_nothing_lit_refuses_rather_than_doing_the_flat():
    """Nothing selected is one tap away now. Falling back to every room would be
    the same defect with a friendlier face."""
    got = _run({"allRooms": False, "rooms": []}, "_boostAll")
    assert got["sent"] == []
    assert got["said"] == [{"kind": "err", "text": "Kein Raum ausgewählt."}]


def test_boost_by_default_still_means_the_whole_home():
    got = _run({"allRooms": True, "rooms": []}, "_boostAll")
    assert [s.split(":")[1] for s in got["sent"]] == ROOMS


def test_alle_aus_ignores_the_picker():
    """Must-not-flag. The label says "Alle AUS" — Ahmad's own words from the
    previous system — and a button that says what it does is allowed to say it.
    Scoping it to the selection would make a labelled promise false."""
    got = _run({"allRooms": False, "rooms": ["climate.b"]}, "_offAll")
    assert [s.split(":")[1] for s in got["sent"]] == ROOMS


def test_alle_ki_ignores_it_too():
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
# and the room picker under it governs the first and deliberately not the other
# two. A reader had to KNOW that. It is why "Boost setzen ignores the picker"
# went unnoticed for so long: nothing on screen claimed otherwise, and nothing
# claimed it either.
#
# So the layout carries it: the picker and Boost in one block, the two whole-home
# buttons in another under a heading that states their scope. These tests are the
# ORDER, because order is the whole mechanism — every label here is unchanged.


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


def test_boost_and_the_room_picker_are_one_block():
    """The picker must come after the Boost heading and before Boost setzen, or
    it is a control floating between two scopes again."""
    m = _markup()
    # Anchored on the heading's OPENING tag: its text now carries the bracketed
    # explanation, so ">Boost</h4>" stopped existing the day that moved onto the
    # same line and this test failed on correct markup (CI, 2026-10-06).
    assert _at(m, "<h4>Boost ") < _at(m, 'class="rooms"') < _at(m, ">Boost setzen<")


def test_the_whole_home_buttons_sit_under_their_own_heading():
    """THE RED ONE: they were under "Boost", which is not what they do."""
    m = _markup()
    head = _at(m, ">Ganze Wohnung<")
    assert _at(m, ">Boost setzen<") < head, "Boost belongs above the split"
    assert head < _at(m, ">Alle → KI<") < _at(m, ">Alle AUS<")


def test_the_room_picker_is_not_inside_the_whole_home_block():
    """It does not govern those two buttons, so it must not look as though it
    does — that mismatch is the defect this layout exists to make impossible."""
    m = _markup()
    assert _at(m, 'class="rooms"') < _at(m, ">Ganze Wohnung<")


def test_ending_a_boost_stays_with_the_boost():
    m = _markup()
    assert _at(m, ">Boost beenden<") < _at(m, ">Ganze Wohnung<")


def test_the_frost_line_sits_under_the_button_it_explains():
    """It is about what AUS leaves behind, and it sat under a row where two of
    three buttons were not AUS."""
    m = _markup()
    assert _at(m, ">Alle AUS<") < _at(m, "frosthint")


def test_every_block_after_the_first_is_ruled_off():
    """The blocks are what says which buttons share a scope, so they have to look
    separate. A heading alone reads as a label on the row above it."""
    m = _markup()
    for head in ("Ganze Wohnung", "Sonderpläne (Krankheit und Urlaub)"):
        before = m[max(0, _at(m, ">" + head + "<") - 120):_at(m, ">" + head + "<")]
        assert "rule" in before, head


def test_the_labels_are_untouched_by_the_regrouping():
    """Must-not-flag. Moving buttons is not licence to rename them — these are
    Ahmad's words from the previous system and residents read them there."""
    m = _markup()
    for label in ("Boost setzen", "Alle → KI", "Alle AUS"):
        assert label in m, label


# --- the section says what it is, on one line --------------------------------
# "the explanation of boost put in parentheses same line as boost not below,
# and add a small sentence before the rooms area to choose the room to boost"
# (2026-10-05).


def test_the_explanation_rides_on_the_boost_heading():
    """THE ASK. It was a line of its own under the heading; now the heading and
    what it means are one line."""
    m = _markup()
    h4 = m[m.index(">Boost "):m.index("</h4>")]
    assert 'class="sub boosthint"' in h4, h4
    assert "<div class=\"hint boosthint\"" not in m, "the old standalone line is gone"


def test_the_explanation_escapes_the_headings_shouting():
    """The heading is uppercased by CSS. A parenthetical inherited that and read
    as BOOST (VENTILE KURZZEITIG GANZ OEFFNEN)."""
    src = CARD.read_text(encoding="utf-8")
    style = src[src.index("<style>"):src.index("</style>")]
    sub = style[style.index("h4 .sub"):]
    assert "text-transform: none" in sub.split("}")[0]


def test_the_room_label_comes_before_the_panel():
    """"a small sentence before the rooms area to choose the room to boost"."""
    m = _markup()
    assert "Räume wählen" in m
    assert m.index("Räume wählen") < m.index('class="rooms"')


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


def test_the_idle_explanation_is_bracketed():
    assert _hint({}) == "(Ventile kurzzeitig ganz öffnen)"


def test_the_running_explanation_does_not_say_boost_twice():
    """It sits directly after a heading that already says BOOST, so
    "BOOST (2 Räume im Boost ...)" says it twice. And after "in" the plural
    takes the dative."""
    live = _boosting("climate.bad", "climate.schlaf")
    got = _hint(live)
    assert got.startswith("(") and got.endswith(")"), got
    assert "im Boost" not in got, got
    assert "2 Räumen" in got, got


def test_one_boosted_room_still_declines():
    got = _hint(_boosting("climate.bad"))
    assert "1 Raum " in got or got.count("1 Raum") == 1, got
    assert "Räumen" not in got, got
