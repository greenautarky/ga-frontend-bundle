"""Schema + sanity checks on bundle.lock.yaml (no network, no on-disk files)."""

from __future__ import annotations

REQUIRED = ("id", "repo", "version", "license", "source", "url", "file", "sha256")


def test_top_level_keys(lock):
    assert "bundle_version" in lock
    assert isinstance(lock["bundle_version"], str), (
        "bundle_version must be a quoted string — an unquoted 2-part version "
        "like 1.0 would be parsed as a YAML float"
    )
    assert isinstance(lock.get("cards"), list) and lock["cards"]


def test_each_card_has_required_fields(lock):
    for i, card in enumerate(lock["cards"]):
        for key in REQUIRED:
            assert key in card, f"card #{i} missing '{key}'"
            assert card[key] != "", f"card {card.get('id', i)} has empty '{key}'"


def test_versions_are_strings(lock):
    # Guards against an unquoted version like `1.0` becoming a float.
    for card in lock["cards"]:
        assert isinstance(card["version"], str), f"{card['id']}: version must be a string"


def test_ids_unique(lock):
    ids = [c["id"] for c in lock["cards"]]
    assert len(ids) == len(set(ids)), "duplicate card ids"


def test_source_enum_and_url_shape(lock):
    for card in lock["cards"]:
        assert card["source"] in ("release", "raw"), card["id"]
        assert card["url"].startswith("https://"), card["id"]
        if card["source"] == "release":
            assert "/releases/download/" in card["url"], card["id"]
        else:
            assert card["url"].startswith("https://raw.githubusercontent.com/"), card["id"]


def test_sha256_hex(lock):
    for card in lock["cards"]:
        h = card["sha256"]
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h), card["id"]


def test_file_matches_url_basename(lock):
    for card in lock["cards"]:
        assert card["url"].rsplit("/", 1)[-1] == card["file"], (
            f"{card['id']}: 'file' should equal the URL basename"
        )
