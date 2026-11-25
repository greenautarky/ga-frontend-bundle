"""Odoo #1905 contract v1, display side: the shipped card functions, run in node."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import PKG
from test_rendered_output import run_js

CARD = PKG / "first_party" / "ga-master-card" / "ga-master-card.js"
MAINT = PKG / "first_party" / "ga-maintenance-card" / "ga-maintenance-card.js"
FIXTURE = Path(__file__).parent / "fixtures" / "zigbee_labels.v1.json"
LABELS = json.loads(FIXTURE.read_text())["request"]["labels"]


def _html(**kw):
    d = {"device_id": "d", "name": "Thermostat 1", "area": "Flur", "battery": 80, "lqi": 90, **kw}
    return run_js(CARD, "renderZigbeeDevices(" + json.dumps([d]) + ")")


def test_fixture_is_the_contract():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "364ff5a60831f699f554beb03282969d42115f485e4baed985396ad5681137eb"


@pytest.mark.parametrize("ieee,name,shown", [
    ("0xaaaaaaaaaaaaaaa1", "Thermostat 1", "Thermostat (TRV-SON-12)"),
    ("0xaaaaaaaaaaaaaaa2", "Temperatur 2", "Temperatur (THD-SON-327)"),
    ("0xaaaaaaaaaaaaaaa3", "Relais", "Relais (REN-GIR-5)"),
])
def test_every_device_class_shows_its_label(ieee, name, shown):
    html = _html(name=name, label=LABELS[ieee])
    assert f'<td class="zb-name">{shown}</td>' in html


@pytest.mark.parametrize("label", [None, "", "Papas Zimmer"])
def test_without_a_label_the_name_is_unchanged(label):
    assert '<td class="zb-name">Thermostat 1</td>' in _html(label=label)


def test_an_older_server_without_the_field_looks_as_before():
    assert '<td class="zb-name">Thermostat 1</td>' in _html()
    assert run_js(CARD, "zigbeeLabelNote(undefined)") == ""


def test_missing_and_unreadable_labels_are_said():
    assert "noch nicht übertragen" in run_js(CARD, 'zigbeeLabelNote({status: "missing"})')
    assert "nicht lesbar" in run_js(CARD, 'zigbeeLabelNote({status: "unreadable"})')
    assert run_js(CARD, 'zigbeeLabelNote({status: "ok"})') == ""


def test_a_labelled_name_is_still_escaped():
    html = _html(name="<b>x</b> 1", label="TRV-SON-00000012")
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt; (TRV-SON-12)" in html


def test_the_label_rule_is_the_maintenance_cards():
    for t in ("THD-SON-00000202", "TRV-SON-00000007", "Thermostat 1", "", "TRV-SON-", "REN-GIR-00000100"):
        e = f"gaLabel({json.dumps(t)})"
        assert run_js(CARD, f"JSON.stringify({e})") == run_js(MAINT, f"JSON.stringify({e})"), t
