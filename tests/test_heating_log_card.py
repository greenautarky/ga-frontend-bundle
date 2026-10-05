"""The last few changes to a room, with timestamps.

Asked for on 2026-09-30. The core logbook card cannot answer this on a GA
device, for two independent reasons measured on 100.126.209.15:

  the 404    `ga_packages/ga_integrations.yaml` loads `history:` and NOT
             `logbook:` (a GA device has no `default_config`), so
             `/api/logbook` answers 404 there.
  the HALF   even loaded, the logbook records STATE changes. A room's setpoint
             is an ATTRIBUTE, so "21 → 23 °C" — the thing a resident actually
             did — would never appear in it.

So the card reads `history/period` and diffs the points itself. What it must
NOT do is claim a reason: history knows THAT the setpoint moved, never whether
it was the resident, the plan, a boost or a window. The entries are
observations, and the tests below pin that wording.

These run the SHIPPED bytes in a VM (tests/js/eval.mjs).
"""

from __future__ import annotations

import json

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-heating-log-card" / "ga-heating-log-card.js"
STRATEGY = PKG / "first_party" / "ga-home-strategy" / "ga-home-strategy.js"


def _point(ts, state, target, current=20.0):
    return {
        "entity_id": "climate.wz",
        "state": state,
        "last_changed": ts,
        "last_updated": ts,
        "attributes": {"temperature": target, "current_temperature": current},
    }


def changes(points):
    return run_js(CARD, f"JSON.stringify(changesFrom({json.dumps(points)}))")


# ── which points are a change at all ────────────────────────────────────────


def test_a_setpoint_move_is_logged():
    c = json.loads(changes([
        _point("2026-09-30T08:00:00+02:00", "auto", 21.0),
        _point("2026-09-30T09:30:00+02:00", "auto", 23.0),
    ]))
    assert c == [{"when": "2026-09-30T09:30:00+02:00", "kind": "target",
                  "from": 21.0, "to": 23.0}]


def test_a_mode_change_is_logged():
    c = json.loads(changes([
        _point("2026-09-30T08:00:00+02:00", "auto", 21.0),
        _point("2026-09-30T09:30:00+02:00", "heat", 21.0),
    ]))
    assert [x["kind"] for x in c] == ["mode"]
    assert c[0]["from"] == "auto" and c[0]["to"] == "heat"


def test_the_measured_temperature_moving_is_not_a_change():
    """History carries a point per update; on a quiet room almost all of them
    are the room thermometer drifting a tenth. A log that listed those would
    bury the one line a resident came for."""
    c = json.loads(changes([
        _point("2026-09-30T08:00:00+02:00", "auto", 21.0, current=20.0),
        _point("2026-09-30T08:05:00+02:00", "auto", 21.0, current=20.1),
        _point("2026-09-30T08:10:00+02:00", "auto", 21.0, current=20.2),
    ]))
    assert c == []


def test_switching_a_room_off_is_one_entry_not_two():
    """AUS takes the target with it; two lines for one press reads like the
    heating did something twice."""
    c = json.loads(changes([
        _point("2026-09-30T08:00:00+02:00", "auto", 21.0),
        _point("2026-09-30T09:00:00+02:00", "off", 7.0),
    ]))
    assert [x["kind"] for x in c] == ["mode"]


def test_the_first_point_seeds_the_diff_and_is_not_itself_a_change():
    assert json.loads(changes([_point("2026-09-30T08:00:00+02:00", "auto", 21.0)])) == []


def test_a_broken_point_is_skipped_rather_than_crashing_the_card():
    c = json.loads(changes([
        _point("2026-09-30T08:00:00+02:00", "auto", 21.0),
        {"state": None},
        {"junk": True},
        _point("2026-09-30T09:00:00+02:00", "auto", 22.0),
    ]))
    assert [x["kind"] for x in c] == ["target"]


def test_an_unknown_setpoint_never_renders_as_nan():
    c = json.loads(changes([
        _point("2026-09-30T08:00:00+02:00", "auto", None),
        _point("2026-09-30T09:00:00+02:00", "auto", 21.0),
    ]))
    text = run_js(CARD, f"JSON.stringify(describe({json.dumps(c[0])}))")
    assert "NaN" not in text
    assert "–" in json.loads(text)["text"]


# ── the words ───────────────────────────────────────────────────────────────


def test_modes_are_named_as_the_resident_knows_them():
    d = json.loads(run_js(
        CARD,
        'JSON.stringify(describe({kind:"mode", from:"auto", to:"heat"}))',
    ))
    assert d["text"] == "KI → MANUEL"


def test_a_setpoint_entry_reads_as_an_observation_not_an_attribution():
    """History knows THAT it moved, never who moved it — so no "Du hast …"."""
    d = json.loads(run_js(
        CARD,
        'JSON.stringify(describe({kind:"target", from:21, to:23}))',
    ))
    assert d["text"] == "Soll 21,0 → 23,0 °C"


def test_german_decimal_comma():
    assert json.loads(run_js(CARD, 'JSON.stringify(temp(21.5))')) == "21,5"


# ── the timestamps ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "when, now, expected",
    [
        ("2026-09-30T14:32:00", "2026-09-30T18:00:00", "Heute 14:32"),
        ("2026-09-29T09:15:00", "2026-09-30T18:00:00", "Gestern 09:15"),
        ("2026-09-28T07:00:00", "2026-09-30T18:00:00", "Mo 07:00"),
        ("2026-09-01T07:00:00", "2026-09-30T18:00:00", "01.09. 07:00"),
    ],
)
def test_the_time_says_which_day_without_spelling_out_today(when, now, expected):
    """A bare clock is ambiguous the moment an entry is older than today; a full
    date on something an hour old is noise."""
    out = run_js(
        CARD,
        f'JSON.stringify(formatWhen("{when}", new Date("{now}")))',
    )
    assert json.loads(out) == expected


def test_a_broken_timestamp_is_dropped_rather_than_shown_as_invalid_date():
    assert json.loads(run_js(CARD, 'JSON.stringify(formatWhen("not a date", new Date()))')) == ""


# ── the card ────────────────────────────────────────────────────────────────


def test_the_element_is_defined_and_advertised():
    src = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("ga-heating-log-card"' in src
    assert 'type: "ga-heating-log-card"' in src


def test_it_refuses_anything_but_a_climate_entity():
    out = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingLogCard.prototype);"
        " try { c.setConfig({ entity: 'sensor.x' }); return 'accepted'; }"
        " catch (e) { return 'refused'; } })()",
    )
    assert out == "refused"


def test_nothing_to_report_and_nothing_readable_are_different_sentences():
    """A card that renders a failed read as "keine Änderungen" lies about one."""
    empty = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingLogCard.prototype);"
        " c._entries = []; c._hours = 72; return c._listHtml(); })()",
    )
    broken = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingLogCard.prototype);"
        " c._entries = null; c._error = 'boom'; return c._listHtml(); })()",
    )
    assert "Keine Änderungen" in empty
    assert "nicht verfügbar" in broken
    assert empty != broken


def test_only_the_first_n_are_rendered():
    """`_entries` is NEWEST FIRST whichever source filled it — the component's
    attribute already is, and the history diff reverses. So the card takes the
    HEAD of the list, and a card that took the tail would show the three oldest
    changes under a heading promising the last three."""
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingLogCard.prototype);"
        " c._count = 3; c._hours = 72; c._config = {};"
        " c._entries = [5,4,3,2,1].map(i => ({ when: `2026-09-30T0${i}:00:00`,"
        " kind: 'target', from: 20, to: 20 + i }));"
        " return c._listHtml(); })()",
    )
    assert html.count("<li>") == 3
    assert html.index("25,0") < html.index("24,0") < html.index("23,0")
    assert "21,0" not in html and "22,0" not in html


def test_the_history_diff_is_reversed_into_the_same_order():
    src = CARD.read_text(encoding="utf-8")
    assert "changesFrom(points).reverse()" in src


# ── the strategy ────────────────────────────────────────────────────────────


def test_the_strategy_places_it_under_the_thermostat_behind_an_option():
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'cards.push({ type: "custom:ga-heating-log-card", entity, title: "Aktivität" });' in src
    assert "changeLog: c.change_log === true," in src, "must default OFF while new"


def test_the_title_is_home_assistants_own_german_for_this():
    """HA's translation maps `panel.logbook` to "Aktivität" (it rebuilt the
    Logbook as the Activity view); `panel.history` is "Verlauf", which is already
    the heading over the 24 h charts. Taking HA's word means this card and a stock
    HA page never call the same thing by two names — the reason the thermostat
    card says "Leerlauf"."""
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'title: "Aktivität"' in src
    assert 'title: "Verlauf"' not in src, "that is HA's word for the history panel"


# ── the component's own entries win (ga_heating 0.12.0) ─────────────────────


PUBLISHED = [
    {"at": "2026-10-01T12:45:37", "kind": "mode", "from": "off", "to": "auto",
     "source": "resident"},
    {"at": "2026-10-01T09:00:00", "kind": "target", "from": 21, "to": 19,
     "source": "plan"},
]


def test_the_attribute_is_rendered_with_its_reason():
    """The one thing the recorder cannot supply. A boost and a resident pressing
    + are the same two numbers in history; only ga_heating knows which."""
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingLogCard.prototype);"
        f" c._entries = fromAttribute({json.dumps(PUBLISHED)});"
        " c._count = 3; c._hours = 72; c._config = {};"
        " return c._listHtml(); })()",
    )
    assert "AUS → KI" in html and "Bedienung" in html
    assert "Soll 21,0 → 19,0 °C" in html and "Heizplan" in html


def test_a_source_we_do_not_know_is_rendered_as_nothing_not_as_its_key():
    """A newer component inventing a reason must not put "window_contact_2" on
    someone's wall."""
    why = json.loads(run_js(
        CARD,
        'JSON.stringify(describe({kind:"mode", from:"auto", to:"heat",'
        ' source:"window_contact_2"}).why)',
    ))
    assert why == ""


def test_no_attribute_means_fall_back_to_history():
    """An older device still gets a log — just without the reasons."""
    assert json.loads(run_js(CARD, "JSON.stringify(fromAttribute(undefined))")) is None
    assert json.loads(run_js(CARD, "JSON.stringify(fromAttribute(null))")) is None


def test_junk_in_the_attribute_is_filtered_rather_than_rendered():
    out = json.loads(run_js(
        CARD,
        'JSON.stringify(fromAttribute([{kind:"mode",at:"x",from:"a",to:"b"},'
        ' null, {kind:"colour"}, "nonsense"]))',
    ))
    assert [e["kind"] for e in out] == ["mode"]


def test_the_attribute_path_makes_no_request():
    """A card that fetched anyway would read the recorder on every room view —
    the cost this attribute exists to remove."""
    src = CARD.read_text(encoding="utf-8")
    body = src.split("set hass(hass)")[1].split("async _load")[0]
    assert "this._render();\n      return;" in body, "the published path must return early"


# ── the timestamp is an instant ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tz", "expected"),
    [("Europe/Berlin", "Heute 14:32"), ("UTC", "Heute 12:32"), ("America/New_York", "Heute 08:32")],
)
def test_an_entry_with_an_offset_is_shown_in_the_viewers_clock(monkeypatch, tz, expected):
    """ga_heating >= 0.12.0 stamps entries WITH their offset. The card renders
    the same instant in whatever zone the browser is in — not the device's wall
    clock re-read as local, which is what a naive timestamp did."""
    monkeypatch.setenv("TZ", tz)
    out = run_js(
        CARD,
        "formatWhen(fromAttribute([{ at: '2026-10-05T14:32:00+02:00', kind: 'target',"
        " from: 20, to: 21, source: 'resident' }])[0].when,"
        " new Date('2026-10-05T16:00:00Z'))",
    )
    assert out == expected
