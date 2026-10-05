"""Wartung — what in a room needs a person.

Asked for on 2026-10-05: "currently no matter how many thermostats do we have we
only show the value of one battery at top of the thermostat widget… on bottom of
aktivitat create a new section called wartung where we add if any sensor
including temp sensor has low battery with its label if possible".

The badge was `batts.slice(0, 1)`: one percentage for a room that may hold three
battery devices, with nothing saying which one it came from — so a healthy valve
beside a dying thermometer showed 100 %. It is now a statement that appears only
when something needs doing, and names the device.

The two rules worth more than the feature:

  WHOSE BATTERIES   Only the room's own valves and thermometers, taken from the
                    devices rather than from "every battery entity in this
                    area". The first device this ran against had
                    `sensor.nokhtari_battery_level` at 15 % — a person's phone.
  WHAT A NAME IS    A GA label where one exists, with its padding removed, then
                    the name a person gave the device — never the radio address,
                    which cannot help anybody standing at the radiator.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-maintenance-card" / "ga-maintenance-card.js"
STRATEGY = PKG / "first_party" / "ga-home-strategy" / "ga-home-strategy.js"


def name_for(friendly, **attrs):
    a = {"friendly_name": friendly, **attrs}
    return json.loads(run_js(CARD, f"JSON.stringify(deviceName({{attributes: {json.dumps(a)}}}))"))


def rows(entities):
    """`maintenanceRows` over `{id: {state, attributes}}`, as names + details."""
    return json.loads(run_js(
        CARD,
        f"JSON.stringify(maintenanceRows({json.dumps(entities)}, "
        f"{json.dumps(list(entities))}).map(r => r.name + '|' + r.detail))"))


def batt(pct, friendly="Thermostat 1 Batterie"):
    return {"state": str(pct), "attributes": {"friendly_name": friendly}}


# ── naming ───────────────────────────────────────────────────────────────────


def test_a_ga_label_loses_its_padding():
    """"skip the zeros". They are padding for a database key, and reading them
    off a sticker to compare with a screen is work the screen should do."""
    assert json.loads(run_js(CARD, 'JSON.stringify(gaLabel("THD-SON-00000202"))')) == "THD-SON-202"


def test_the_label_is_found_behind_the_sensor_suffix():
    """THE RED ONE (caught in a browser, 2026-10-05). A battery sensor is named
    after its device plus " Batterie", so the label shape never matched and the
    card fell through to the raw name — the padded form, which is the one thing
    this was asked to stop showing."""
    assert name_for("THD-SON-00000202 Batterie") == "THD-SON-202"
    assert name_for("THD-SON-00000045 Battery") == "THD-SON-45"


def test_an_explicit_label_attribute_wins_over_the_name():
    """The day a device publishes one, it is used without another change here."""
    assert name_for("Thermostat 2 Batterie", ga_label="TRV-SON-00000007") == "TRV-SON-7"


def test_a_device_without_a_label_keeps_the_name_a_person_gave_it():
    """No device on the fleet carries a label yet (checked 2026-10-05: no label
    registry, devices named "Thermostat 1"). The card has to be useful now."""
    assert name_for("Klimasensor 1 Batterie") == "Klimasensor 1"


def test_something_that_is_not_a_label_is_not_mangled_into_one():
    assert json.loads(run_js(CARD, 'JSON.stringify(gaLabel("Thermostat 1"))')) is None


def test_a_nameless_sensor_gets_no_invented_name():
    """Returning the entity id here would put a radio address on screen, which
    is the one answer that helps nobody."""
    assert json.loads(run_js(CARD, "JSON.stringify(deviceName({attributes: {}}))")) is None


# ── what counts as needing a person ──────────────────────────────────────────


def test_a_healthy_battery_says_nothing():
    assert rows({"a": batt(96)}) == []


def test_a_low_battery_names_the_device_and_its_class():
    assert rows({"a": batt(8, "THD-SON-00000202 Batterie")}) == [
        "THD-SON-202|Batterie fast leer"]


def test_no_percentage_ever_reaches_the_screen():
    """THE ASK: "i want to have classes and not show numbers". The reading on
    screen the day that was said was 46 % — is that fine? Worth a trip to the
    shop? Nobody can know, which is why the number is the card's working and not
    its answer. It stays only as the sort key."""
    for pct in (0, 5, 19, 20, 25, 30):
        for line in rows({"a": batt(pct)}):
            assert "%" not in line, line
            assert str(pct) not in line.split("|")[1], line


def test_the_two_bands_are_30_and_20():
    """Decided by the product owner on 2026-10-05, over a wider critical gap."""
    assert rows({"a": batt(31)}) == []
    assert rows({"a": batt(30)}) == ["Thermostat 1|Batterie niedrig"]
    assert rows({"a": batt(21)}) == ["Thermostat 1|Batterie niedrig"]
    assert rows({"a": batt(20)}) == ["Thermostat 1|Batterie fast leer"]
    assert rows({"a": batt(0)}) == ["Thermostat 1|Batterie fast leer"]


def test_each_band_includes_its_own_edge():
    """An off-by-one here is a battery that is never called low until 29 %, or a
    critical one still described as merely niedrig."""
    assert rows({"a": batt(30)})[0].endswith("niedrig")
    assert rows({"a": batt(20)})[0].endswith("fast leer")


def test_the_emptiest_is_named_first():
    """A resident reads the first line, so the worst device has to be on it —
    and within one band the percentage still decides, even though it is never
    shown."""
    got = rows({"a": batt(28, "A Batterie"), "b": batt(5, "B Batterie"),
                "c": batt(24, "C Batterie")})
    assert got == ["B|Batterie fast leer", "C|Batterie niedrig", "A|Batterie niedrig"]


def test_the_bands_carry_their_own_colour_class():
    """The colour says the same thing as the word, so the two are told apart
    before either is read. A row that rendered without its class would look
    identical to the calmer band."""
    assert "critical" in run_js(CARD, 'JSON.stringify(batteryBand(5))')
    assert "low" in run_js(CARD, 'JSON.stringify(batteryBand(25))')
    assert run_js(CARD, "JSON.stringify(batteryBand(80))") == "null"


def test_a_sensor_that_has_not_reported_is_not_a_flat_battery():
    """Must-not-flag: `Number("unavailable")` is NaN, and rendering it as 0 %
    would send somebody to a radiator that is fine. A device that has genuinely
    stopped answering is a MALFUNCTION — the next thing this section learns."""
    for state in ("unavailable", "unknown", "", "   ", None):
        assert rows({"a": {"state": state,
                           "attributes": {"friendly_name": "A Batterie"}}}) == [], state


def test_an_empty_reading_is_not_a_flat_battery():
    """`Number("")` is 0, and so are `Number(null)` and `Number("   ")` — all
    finite, all rendering "Batterie 0 %" for a sensor that said nothing (caught
    in a browser, 2026-10-05; the same shape as the missing setpoint that once
    logged "Soll 0,0 °C"). A real "0" is a reading and must still count."""
    assert rows({"a": {"state": "", "attributes": {"friendly_name": "A Batterie"}}}) == []
    assert rows({"a": batt(0, "A Batterie")}) == ["A|Batterie fast leer"]


def test_an_entity_that_does_not_exist_is_skipped_not_guessed():
    assert json.loads(run_js(
        CARD, 'JSON.stringify(maintenanceRows({}, ["sensor.gone"]).length)')) == 0


# ── the card says both things out loud ───────────────────────────────────────


def _render(entities, batteries):
    return run_js(CARD, f"""
      (() => {{
        const el = Object.create(GaMaintenanceCard.prototype);
        el.setConfig({{ batteries: {json.dumps(batteries)} }});
        let html = "";
        Object.defineProperty(el, "innerHTML", {{
          get: () => html, set: (v) => {{ html = v; }}, configurable: true }});
        el._hass = {{ states: {json.dumps(entities)} }};
        el._render();
        return html;
      }})()
    """)


def test_nothing_to_do_is_said_rather_than_left_blank():
    """A card that renders empty reads as one that failed to load — the
    difference between "we checked" and "nobody is checking"."""
    out = _render({"a": batt(96)}, ["a"])
    assert "Keine Auffälligkeiten" in out


def test_the_section_is_called_wartung():
    out = _render({"a": batt(96)}, ["a"])
    assert "Wartung" in out


def test_a_low_battery_is_rendered_with_its_name_and_class():
    out = _render({"a": batt(8, "Klimasensor 1 Batterie")}, ["a"])
    assert "Klimasensor 1" in out
    assert "Batterie fast leer" in out
    assert "8 %" not in out and "8%" not in out


def test_no_radio_address_reaches_the_screen():
    """The fleet names every z2m entity after its IEEE. A card that fell back to
    the entity id would print one."""
    out = _render({"sensor.0x0ceff6fffe76aca7_battery":
                   {"state": "5", "attributes": {"friendly_name": "Thermostat 1 Batterie"}}},
                  ["sensor.0x0ceff6fffe76aca7_battery"])
    assert "0x0ceff6" not in out


# ── whose batteries: the strategy's scoping ──────────────────────────────────


def scoped(valves, temps=(), hums=(), extra=()):
    states = {f"sensor.{v.split('.')[-1]}_battery": {"state": "50"} for v in valves}
    for t in list(temps) + list(hums):
        key = t.split(".")[-1].split("_")[0]
        states[f"sensor.{key}_battery"] = {"state": "50"}
    for e in extra:
        states[e] = {"state": "15"}
    clim = {"attributes": {"valves": list(valves)}}
    return json.loads(run_js(
        STRATEGY,
        f"JSON.stringify(roomBatteries({{temps: {json.dumps(list(temps))}, "
        f"hums: {json.dumps(list(hums))}}}, {json.dumps(clim)}, "
        f"{{states: {json.dumps(states)}}}))"))


def test_a_rooms_valves_bring_their_batteries():
    assert scoped(["climate.0xaaa1"]) == ["sensor.0xaaa1_battery"]


def test_both_valves_of_a_two_radiator_room_are_covered():
    """The badge showed one. A room with two radiators has two batteries."""
    assert scoped(["climate.0xaaa1", "climate.0xbbb2"]) == [
        "sensor.0xaaa1_battery", "sensor.0xbbb2_battery"]


def test_the_rooms_thermometer_counts_too():
    """"including temp sensor" — a dead thermometer stops the room heating
    correctly just as surely as a dead valve."""
    assert scoped(["climate.0xaaa1"], temps=["sensor.0xccc3_temperature"]) == [
        "sensor.0xaaa1_battery", "sensor.0xccc3_battery"]


def test_a_phone_in_the_same_area_is_not_a_heating_device():
    """THE MUST-NOT-FLAG. `room.batts` is every battery sensor in the area, and
    on the first device this ran against that was `sensor.nokhtari_battery_level`
    at 15 % — somebody's phone. Telling a resident the heating needs maintenance
    because a phone is flat is worse than saying nothing."""
    got = scoped(["climate.0xaaa1"], extra=["sensor.nokhtari_battery_level"])
    assert got == ["sensor.0xaaa1_battery"]


def test_a_device_with_no_battery_sensor_adds_no_line():
    """Mains-powered, or a sensor that was never created. Asking for a state
    that is not there must not produce an entry for it."""
    assert json.loads(run_js(
        STRATEGY,
        'JSON.stringify(roomBatteries({temps: [], hums: []}, '
        '{attributes: {valves: ["climate.0xaaa1"]}}, {states: {}}))')) == []


# ── where it sits ────────────────────────────────────────────────────────────


#: The heating section of a built room view, as the strategy produces it.
#:
#: Asserted on the BUILT sections rather than on the source. The first version
#: of the two tests below grepped for `batts.slice(0, 1)` — and matched the
#: comment that explains why the badge was removed, so it failed against correct
#: code. That is the third time in one day a string check in this repo measured
#: its own prose; the rule it keeps re-teaching is the one this file follows.
ROOM_VIEW = """
  (() => {
    const room = { name: "Flur", area_id: "flur", climate: ["climate.flur"],
      temps: ["sensor.0xccc3_temperature"], hums: [],
      batts: ["sensor.0xaaa1_battery"], lights: [], switches: [] };
    const hass = { states: {
      "climate.flur": { state: "auto", attributes: { valves: ["climate.0xaaa1"],
        current_temperature: 21, temperature_source: "sensor.0xccc3_temperature" } },
      "sensor.0xccc3_temperature": { state: "21", attributes: {} },
      "sensor.0xaaa1_battery": { state: "50", attributes: { device_class: "battery" } },
    } };
    const secs = roomSections(room, { changeLog: true, singleThermostat: true }, hass);
    const cards = (secs[0] && secs[0].cards) || [];
    return JSON.stringify({
      badges: (cards[0] && cards[0].badges || []).map((b) => b.name + "|" + (b.entity || "")),
      types: cards.map((c) => c.type),
      batteries: cards.filter((c) => c.type === "custom:ga-maintenance-card")
                      .map((c) => c.batteries),
    });
  })()
"""


def room_view():
    return json.loads(run_js(STRATEGY, ROOM_VIEW))


def test_the_battery_badge_is_gone_from_the_top_of_the_room():
    """THE ASK: "remove this value from the top"."""
    badges = room_view()["badges"]
    assert not any("Batterie" in b or "_battery" in b for b in badges), badges


def test_the_temperature_badge_is_untouched():
    """Must-not-flag: removing one badge must not take the row with it."""
    assert room_view()["badges"] == ["Temperatur|sensor.0xccc3_temperature"]


def test_wartung_sits_under_aktivitaet():
    """"on bottom of aktivitat" — and it reads as the next question: that is
    what happened, this is what needs doing."""
    types = room_view()["types"]
    assert types.index("custom:ga-heating-log-card") < types.index("custom:ga-maintenance-card")


def test_the_section_is_handed_the_rooms_own_batteries():
    """The card finds nothing itself — the strategy, which knows the room's
    devices, decides. That is what keeps a phone out of it."""
    assert room_view()["batteries"] == [["sensor.0xaaa1_battery"]]


def test_the_card_is_registered_like_every_other_first_party_card():
    src = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("ga-maintenance-card"' in src
    assert "window.customCards" in src
    assert 'type: "ga-maintenance-card"' in src


def test_the_title_is_set_like_the_activity_card_above_it():
    """The two cards sit one under the other in the same room view, so a title
    in the browser's default h2 beside one at body size read as a different
    level of heading entirely ("make the font and size of wartung similar to
    aktivitat", 2026-10-05).

    Pinned against the OTHER card's stylesheet rather than against copied
    numbers, so the pair cannot drift apart one edit at a time.
    """
    log = (PKG / "first_party" / "ga-heating-log-card" / "ga-heating-log-card.js").read_text(
        encoding="utf-8")
    mine = CARD.read_text(encoding="utf-8")

    def hdr_rule(src, element):
        start = src.index(f"{element} .hdr {{")
        return src[start:src.index("}", start)]

    theirs = hdr_rule(log, "ga-heating-log-card")
    ours = hdr_rule(mine, "ga-maintenance-card")
    for prop in ("font-weight: 600", "opacity: .8"):
        assert prop in theirs, f"the activity card changed its header: {theirs}"
        assert prop in ours, f"ours no longer matches it: {ours}"
    assert "font-size" not in ours, "a size here is what made it a different heading"


def test_the_title_renders_inside_the_padded_body():
    """Outside it, the title sat hard against the card edge while the activity
    card's sat in from it."""
    out = _render({"a": batt(96)}, ["a"])
    assert out.index('class="card-content"') < out.index("Wartung")
