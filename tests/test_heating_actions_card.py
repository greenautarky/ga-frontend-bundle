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


def test_valves_that_disagree_are_all_named():
    s = states(**{
        "number.0xaaa_frost_protection_temperature": {"state": "7"},
        "number.0xbbb_frost_protection_temperature": {"state": "5"},
    })
    assert call(f"frostSetpoints({json.dumps(s)})") == [5, 7]
    assert "5 / 7" in call(f"frostText({json.dumps(s)})")


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


def test_the_profile_view_is_named_for_the_place_that_already_existed():
    """The previous system's view was called `Profil`, and residents look there.

    Read in ha-dashboard-automation/templates/profile_view_template.j2 on
    2026-09-23: `title: Profil`, grid `"boost override" / "schedule override"`.
    """
    v = run_js(STRATEGY, "(() => heatingProfileView({ textTabs: true }))()")
    assert v["title"] == "Profil" and v["path"] == "profil"
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
    b = {"boost": {"until": "2026-10-01T09:05:00", "temp": 30.0,
                   "active": True, "remaining_s": 252}}
    s = call(f"boostStatus({json.dumps(st_with([b] * 2))}, {json.dumps(ROOM_IDS)})")
    assert "4:12" in s and "2 Raum/Räumen" in s
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
