"""The last few changes to a room, with timestamps.

Asked for on 2026-09-30. The core logbook card cannot answer this on a GA
device, for two independent reasons measured on a resident test device:

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


def test_the_strategy_places_it_under_the_thermostat():
    src = STRATEGY.read_text(encoding="utf-8")
    assert 'cards.push({ type: "custom:ga-heating-log-card", entity, title: "Aktivität" });' in src


@pytest.mark.parametrize(
    "config, expected",
    [
        ("{}", True),                       # what greenautarky_site writes: no options
        ("{change_log: true}", True),
        ("{change_log: false}", False),     # an explicit opt-out still works
    ],
)
def test_the_change_log_is_shown_unless_switched_off(config, expected):
    """DEFAULT ON since 1.23.1 (Thomas, 2026-10-06). It was off "while new", and
    a device test on BOSv1.4.0-rc6 found the result: greenautarky_site writes the
    strategy with no options, so "Aktivität" was on no room view of any device.
    Since ga_heating 0.12.0 the card reads the room entity first and the recorder
    only as a fallback, so the per-view cost that justified OFF is mostly gone."""
    got = json.loads(run_js(STRATEGY, f"JSON.stringify(gaOptions({config}).changeLog)"))
    assert got is expected


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
    assert "AUS → KI" in html and "Benutzer" in html
    assert "Soll 21,0 → 19,0 °C" in html and "System · Heizplan" in html


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


# ── who did it, then why (2026-10-04) ───────────────────────────────────────


@pytest.mark.parametrize(
    "source, expected",
    [
        ("resident", "Benutzer"),
        ("valve", "Benutzer"),
        ("boost", "Benutzer · Boost"),
        ("absence", "Benutzer · Urlaub"),
        ("plan", "System · Heizplan"),
        ("window", "System · Fenster"),
        ("expiry", "System · Zeit abgelaufen"),
        # ga_heating 0.13.0: the balancing hour (ICHB). Started by the operator at
        # commissioning, not by the resident, so it sits on the System side.
        ("balancing", "System · Einregulierung"),
    ],
)
def test_each_source_says_who_first_then_why(source, expected):
    """"Was that me, or did the heating do it?" is the question a resident asks
    of a log, so it is the first thing each line answers. A boost and a holiday
    sit on the Benutzer side: somebody asked for them, even though the system
    carried them out at a moment nobody picked."""
    why = json.loads(run_js(
        CARD,
        f'JSON.stringify(describe({{kind:"mode", from:"auto", to:"heat",'
        f' source:"{source}"}}).why)',
    ))
    assert why == expected


def test_the_user_side_does_not_restate_itself():
    """"Benutzer · Bedienung" says the same thing twice, and a hand on the
    radiator is still the user — so neither carries a reason."""
    for source in ("resident", "valve"):
        why = json.loads(run_js(
            CARD,
            f'JSON.stringify(describe({{kind:"mode", from:"auto", to:"heat",'
            f' source:"{source}"}}).why)',
        ))
        assert why == "Benutzer", why


def test_manuell_is_not_used_for_the_user_side():
    """MANUEL is a MODE on the thermostat card beside this one; a log saying
    "Manuell" about a press that chose KI would read as a contradiction.

    Asserted on the WORDS the card renders, not on the file: the comment above
    `SOURCE_WORDS` explains this choice and therefore contains the word, which a
    plain substring check reads as the defect it is there to prevent.
    """
    words = run_js(
        CARD,
        "JSON.stringify(Object.values(SOURCE_WORDS)"
        ".flatMap(s => [s.who, s.why]).filter(Boolean))",
    )
    assert "Manuell" not in json.loads(words)


# ── a balancing run, named ──────────────────────────────────────────────────
#
# ga_heating 0.13.6 records the run itself as a `kind: "event"` entry. The
# setpoints it writes were always logged, but "Soll 19 -> 30" and an hour later
# "30 -> 19" only reads as a balancing run to somebody who knows what one is
# (asked for 2026-10-08).


def _said(entry):
    return json.loads(run_js(CARD, f"JSON.stringify(describe({json.dumps(entry)}))"))


def _event(to, source="balancing"):
    return {"when": "2026-10-08T12:00:00+02:00", "kind": "event",
            "from": None, "to": to, "source": source}


def test_a_run_start_is_said_in_words():
    assert _said(_event("ichb_started"))["text"] == "Hydraulischer Abgleich gestartet"


def test_an_end_and_a_cancel_are_different_lines():
    """A resident coming home to a cold flat needs to tell "it ran" from
    "somebody stopped it"."""
    assert _said(_event("ichb_ended"))["text"] == "Hydraulischer Abgleich beendet"
    assert _said(_event("ichb_cancelled"))["text"] == "Hydraulischer Abgleich abgebrochen"


def test_the_reason_is_not_repeated_after_the_line_that_already_says_it():
    """It read "Hydraulischer Abgleich abgebrochen · System · Einregulierung" —
    the same thing twice in two vocabularies (seen on a device, 2026-10-08). The
    actor stays; the reason goes, exactly as it does for a resident at a button."""
    said = _said(_event("ichb_cancelled"))
    assert said["why"] == "System"
    assert "Einregulierung" not in said["why"]


def test_an_event_nobody_has_taught_this_card_still_renders():
    """A line a resident cannot read beats a line that silently disappears — and
    a newer ga_heating may well record something this bundle has not learned."""
    said = _said(_event("ichb_paused"))
    assert said["text"] == "ichb_paused"
    assert said["icon"]


def test_a_value_change_is_untouched_by_any_of_this():
    """MUST-NOT-FLAG: the ordinary entries keep their actor AND their reason."""
    said = _said({"when": "2026-10-08T12:00:00+02:00", "kind": "target",
                  "from": 19, "to": 21, "source": "plan"})
    assert said["why"] == "System · Heizplan"


def test_events_survive_the_attribute_reader():
    """`fromAttribute` filters by kind, so an unlisted kind is dropped before it
    is ever described — which is how a new entry type silently vanishes."""
    got = json.loads(run_js(
        CARD,
        "JSON.stringify(fromAttribute(" + json.dumps([
            {"at": "2026-10-08T12:00:00+02:00", "kind": "event",
             "from": None, "to": "ichb_started", "source": "balancing"}]) + "))"))
    assert len(got) == 1 and got[0]["to"] == "ichb_started", got


# ── five kept, three shown ──────────────────────────────────────────────────


def test_five_entries_are_kept():
    """A balancing run alone writes four lines into a room (started, the setpoint
    up, the setpoint back, ended); three would hide everything before it. The
    list is capped at the height of three and scrolls (asked for 2026-10-08)."""
    assert json.loads(run_js(CARD, "JSON.stringify(DEFAULT_COUNT)")) == 5


def test_the_list_is_capped_rather_than_grown_into():
    src = CARD.read_text(encoding="utf-8")
    assert "max-height" in src and "overflow-y: auto" in src


# ── the title can carry an icon ─────────────────────────────────────────────


def test_a_configured_icon_reaches_the_header():
    html = run_js(
        CARD,
        "(() => { const c = Object.create(GaHeatingLogCard.prototype);"
        " c.setConfig({ entity: 'climate.x', title: 'Aktivität', icon: 'mdi:history' });"
        " return c._headerHtml(); })()",
    )
    assert 'icon="mdi:history"' in html, html
    assert "Aktivität" in html


def test_an_icon_that_is_not_an_icon_is_refused():
    """The icon is CONFIG that lands in an HTML attribute, so it cannot be escaped
    as text: a quote would close the attribute and the rest would parse as markup.
    Only a plain mdi name is let through."""
    src = CARD.read_text(encoding="utf-8")
    assert "SAFE_ICON" in src
    for bad in ('mdi:x" onload="alert(1)', "javascript:alert(1)", "<img src=x>"):
        assert not json.loads(run_js(CARD, f"JSON.stringify(SAFE_ICON.test({json.dumps(bad)}))"))
    assert json.loads(run_js(CARD, 'JSON.stringify(SAFE_ICON.test("mdi:history"))'))
