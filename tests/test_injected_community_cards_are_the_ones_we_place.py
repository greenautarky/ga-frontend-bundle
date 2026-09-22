"""The injected community cards are exactly the ones something places.

Injection is not free: every card in `add_extra_js_url` is fetched on every
dashboard load, before the app can start ours. Measured on a device on
2026-09-22: all thirteen vendored cards meant 6.1 MB ahead of our own 13–23 KB
assets — plotly-graph-card alone is 3.1 MB and took 10.2 s, and the heating
card only appeared at 11.3 s (28 s in a second run). Not one of the three
heaviest is referenced anywhere; they are named only in ga-home-strategy's
comment recording that HA core replaced them.

So this reads the LIVE first-party sources — never a copy of the list — and
compares both directions:

  * placed but NOT injected  → a dashboard that renders an error card
  * injected but NOT placed  → the defect above, coming back

A new vendored card is therefore not injected until something places it, and
adding a `custom:` type to a card builder fails this test until the id is
allow-listed. Neither half can rot quietly.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import ast

from conftest import PKG

FIRST_PARTY = PKG / "first_party"
COMMUNITY = PKG / "community"
_CONST = PKG / "const.py"


def _allow_list() -> tuple[str, ...]:
    """Read COMMUNITY_INJECT_ASSET_IDS out of the LIVE const.py.

    Not imported: importing the package pulls in Home Assistant, which is not a
    test dependency here. Not re-declared either — a gate that carries its own
    copy of the list tests the copy and stays green while the real one rots.
    """
    tree = ast.parse(_CONST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "COMMUNITY_INJECT_ASSET_IDS" for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(
        f"COMMUNITY_INJECT_ASSET_IDS not found in {_CONST} — the definition moved "
        "or was renamed. Failing rather than checking nothing."
    )

# `type: "custom:<id>"` — how a card is placed.
_CUSTOM_TYPE = re.compile(r'type:\s*"custom:([a-z0-9-]+)"')
# `card_mod:` — a style key, not a type, and the module must still be loaded.
_CARD_MOD = re.compile(r"\bcard_mod\s*:")


def _vendored_ids() -> set[str]:
    ids = {p.name for p in COMMUNITY.iterdir() if p.is_dir()}
    assert len(ids) >= 5, (
        f"only {len(ids)} vendored card dirs under {COMMUNITY} — the bundle is "
        "not vendored, or the layout changed. Failing rather than comparing "
        "against nothing."
    )
    return ids


def _placed_ids() -> set[str]:
    """Community card ids the first-party sources actually place."""
    sources = sorted(FIRST_PARTY.rglob("*.js"))
    assert sources, f"no first-party sources under {FIRST_PARTY} — cannot tell what is placed"
    vendored = _vendored_ids()
    placed: set[str] = set()
    for path in sources:
        text = path.read_text(encoding="utf-8")
        # A comment naming a card it was REPLACED by must not count as a use;
        # only a real `type: "custom:…"` does. That distinction is the whole
        # reason mushroom/apexcharts looked used for months.
        for cid in _CUSTOM_TYPE.findall(text):
            if cid in vendored:
                placed.add(cid)
        if _CARD_MOD.search(text):
            placed.add("card-mod")
    return placed


def test_the_extraction_finds_something():
    """Rule 51c: if the discriminator stops matching, FAIL — never pass over an
    empty result, which is what a broken regex and a clean codebase look like
    from the outside."""
    placed = _placed_ids()
    assert placed, (
        "no community card placement found in the first-party sources. Either "
        "nothing places one (then empty the allow-list deliberately) or the "
        "patterns stopped matching."
    )


def test_every_placed_card_is_injected():
    missing = sorted(_placed_ids() - set(_allow_list()))
    assert not missing, (
        "placed but not injected — these render as an error card on a real "
        f"dashboard: {missing}. Add them to COMMUNITY_INJECT_ASSET_IDS."
    )


def test_every_injected_card_is_placed():
    extra = sorted(set(_allow_list()) - _placed_ids())
    assert not extra, (
        "injected but placed nowhere — these are downloaded on every dashboard "
        f"load for nothing: {extra}. Remove them from COMMUNITY_INJECT_ASSET_IDS "
        "(they stay vendored and served, so a Lovelace resource can still load "
        "one)."
    )


def test_the_allow_list_is_a_real_subset_of_what_is_vendored():
    unknown = sorted(set(_allow_list()) - _vendored_ids())
    assert not unknown, f"allow-listed but not vendored: {unknown}"


@pytest.mark.parametrize(
    "snippet, expect",
    [
        ('type: "custom:simple-thermostat",', {"simple-thermostat"}),
        ("card_mod: { style: \"x\" },", {"card-mod"}),
        # The comment shape that fooled a human reader for months.
        (" *   mushroom chips  -> `heading` card badges", set()),
        (" *   apexcharts daily range -> core `statistics-graph`", set()),
    ],
)
def test_the_discriminator_separates_use_from_mention(tmp_path, snippet, expect, monkeypatch):
    """The gate is only worth having if a MENTION does not count as a USE."""
    fake = tmp_path / "first_party" / "x"
    fake.mkdir(parents=True)
    (fake / "x.js").write_text(snippet, encoding="utf-8")
    monkeypatch.setattr(
        __import__(__name__), "FIRST_PARTY", tmp_path / "first_party", raising=True
    )
    monkeypatch.setattr(
        __import__(__name__), "_vendored_ids", lambda: {"simple-thermostat", "mushroom", "apexcharts-card"}
    )
    assert _placed_ids() == expect
