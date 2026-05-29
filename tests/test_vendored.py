"""Verify the on-disk vendored files match the lock (independent of vendor.py).

This is the integrity gate: every pinned card is present with the exact bytes
the lock commits to, cards.json is consistent, and there are no orphan dirs.
"""

from __future__ import annotations

import hashlib
import json

from conftest import COMMUNITY


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_card_present_and_hash_matches(lock):
    for card in lock["cards"]:
        path = COMMUNITY / card["id"] / card["file"]
        assert path.is_file(), f"missing vendored file: {path}"
        assert _sha256(path) == card["sha256"], f"sha mismatch for {card['id']}"


def test_cards_json_matches_lock(lock):
    index = json.loads((COMMUNITY / "cards.json").read_text(encoding="utf-8"))
    assert index["bundle_version"] == lock["bundle_version"]
    assert [c["id"] for c in index["cards"]] == [c["id"] for c in lock["cards"]]
    assert [c["file"] for c in index["cards"]] == [c["file"] for c in lock["cards"]]


def test_no_orphan_card_dirs(lock):
    lock_ids = {c["id"] for c in lock["cards"]}
    on_disk = {p.name for p in COMMUNITY.iterdir() if p.is_dir()}
    assert on_disk == lock_ids, f"community/ dirs {on_disk ^ lock_ids} not in lock"
