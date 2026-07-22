"""Pure (stdlib-only) helpers for the GA frontend bundle.

Deliberately free of any ``homeassistant`` imports so the bundle-loading logic
is unit-testable without a full HA test harness (CI stays fast).
"""

from __future__ import annotations

import json
from pathlib import Path

CARDS_INDEX = "cards.json"


def load_cards(community_dir: Path) -> list[dict[str, str]]:
    """Return the vendored cards as ``{"id", "file"}`` dicts.

    Prefers the generated ``cards.json`` (written by ``scripts/vendor.py``);
    falls back to scanning each subdir for its single ``.js`` so a hand-placed
    card still loads. Only entries whose file actually exists on disk are
    returned, so a partial vendor can never inject a 404 module.
    """
    community_dir = Path(community_dir)
    cards: list[dict[str, str]] = []

    index = community_dir / CARDS_INDEX
    if index.is_file():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            cards = [
                {"id": str(c["id"]), "file": str(c["file"])}
                for c in data.get("cards", [])
                if "id" in c and "file" in c
            ]
        except (ValueError, OSError, TypeError):
            cards = []

    if not cards and community_dir.is_dir():
        for sub in sorted(p for p in community_dir.iterdir() if p.is_dir()):
            js = sorted(sub.glob("*.js"))
            if js:
                cards.append({"id": sub.name, "file": js[0].name})

    return [c for c in cards if (community_dir / c["id"] / c["file"]).is_file()]


def card_url(base: str, card: dict[str, str], version: str | None = None) -> str:
    """Served URL for a card under the static base path.

    A ``?v=<version>`` cache-buster is appended when ``version`` is given so a
    browser picks up a new card build after a bundle update instead of running
    the long-cached old module (which otherwise wins the ``customElements.define``
    race and pins residents to the previous card — verified on K0, 2026-07-22).
    """
    url = f"{base}/{card['id']}/{card['file']}"
    return f"{url}?v={version}" if version else url


def bundle_version(pkg_dir: Path) -> str | None:
    """Read the integration manifest version (synced to bundle.lock by vendor.py).

    Used as the cache-buster for served card/strategy URLs. Returns None if the
    manifest is missing/unreadable (then URLs are served un-busted, as before).
    """
    try:
        data = json.loads((Path(pkg_dir) / "manifest.json").read_text(encoding="utf-8"))
        v = data.get("version")
        return str(v) if v else None
    except (ValueError, OSError, TypeError, KeyError):
        return None
