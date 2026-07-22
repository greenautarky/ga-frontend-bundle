"""Unit tests for the pure bundle-loading logic (bundle.py, stdlib-only)."""

from __future__ import annotations

import json

from conftest import COMMUNITY


def test_load_cards_reads_real_index(bundle_module, lock):
    cards = bundle_module.load_cards(COMMUNITY)
    assert [c["id"] for c in cards] == [c["id"] for c in lock["cards"]]
    # every returned entry must point at a file that exists
    for c in cards:
        assert (COMMUNITY / c["id"] / c["file"]).is_file()


def test_card_url(bundle_module):
    url = bundle_module.card_url("/base", {"id": "button-card", "file": "button-card.js"})
    assert url == "/base/button-card/button-card.js"


def test_load_cards_prefers_index(bundle_module, tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "alpha.js").write_text("//x")
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "beta.js").write_text("//y")
    # index intentionally lists only alpha -> beta must be ignored
    (tmp_path / "cards.json").write_text(
        json.dumps({"bundle_version": "9", "cards": [{"id": "alpha", "file": "alpha.js"}]})
    )
    cards = bundle_module.load_cards(tmp_path)
    assert cards == [{"id": "alpha", "file": "alpha.js"}]


def test_load_cards_fallback_scan_without_index(bundle_module, tmp_path):
    (tmp_path / "gamma").mkdir()
    (tmp_path / "gamma" / "gamma.js").write_text("//z")
    cards = bundle_module.load_cards(tmp_path)
    assert cards == [{"id": "gamma", "file": "gamma.js"}]


def test_load_cards_drops_missing_file(bundle_module, tmp_path):
    # index references a file that does not exist -> filtered out
    (tmp_path / "cards.json").write_text(
        json.dumps({"bundle_version": "9", "cards": [{"id": "ghost", "file": "ghost.js"}]})
    )
    assert bundle_module.load_cards(tmp_path) == []


def test_load_cards_empty_dir(bundle_module, tmp_path):
    assert bundle_module.load_cards(tmp_path) == []


def test_card_url_cache_busts_with_version(bundle_module):
    card = {"id": "ga-thermostat-card", "file": "ga-thermostat-card.js"}
    assert bundle_module.card_url("/base", card) == "/base/ga-thermostat-card/ga-thermostat-card.js"
    assert bundle_module.card_url("/base", card, "1.5.1") == (
        "/base/ga-thermostat-card/ga-thermostat-card.js?v=1.5.1"
    )


def test_bundle_version_reads_manifest(bundle_module, tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "1.5.1"}))
    assert bundle_module.bundle_version(tmp_path) == "1.5.1"
    assert bundle_module.bundle_version(tmp_path / "nope") is None
