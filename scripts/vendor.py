#!/usr/bin/env python3
"""Vendor the pinned Lovelace cards from ``bundle.lock.yaml`` into the integration.

For each card in the lockfile this downloads its pinned URL into
``custom_components/ga_frontend_bundle/community/<id>/<file>``, manages its
``sha256``, then regenerates ``community/cards.json`` and syncs the integration
manifest ``version`` to ``bundle_version``.

Modes
-----
(default, no flag)
    Download every card, verify its sha256 against the lock (FAIL on mismatch,
    or on an empty lock hash — run ``--update`` first), write the files, and
    regenerate ``cards.json`` + manifest version. Use to (re)materialise the
    vendored tree from a trusted lock.

``--update``
    Download every card and (re)write its sha256 into the lock. Use when adding
    a card or bumping a version. Also regenerates ``cards.json`` + manifest.

``--check``
    OFFLINE. Verify the on-disk vendored files against the lock without
    downloading. FAIL on any missing file, empty lock hash, or sha mismatch.
    This is the fast integrity gate CI runs.

Dependencies: PyYAML (dev/CI only). Networking uses stdlib ``urllib``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "bundle.lock.yaml"
PKG = ROOT / "custom_components" / "ga_frontend_bundle"
COMMUNITY = PKG / "community"
MANIFEST = PKG / "manifest.json"
CARDS_INDEX = COMMUNITY / "cards.json"

USER_AGENT = "ga-frontend-bundle-vendor/1.0 (+https://github.com/greenautarky/ga-frontend-bundle)"
TIMEOUT_S = 60


def _load_lock() -> dict:
    with LOCK.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _lock_header() -> str:
    """Preserve the leading comment block of the lockfile verbatim."""
    header = []
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line.strip() == "" or line.lstrip().startswith("#"):
            header.append(line)
        else:
            break
    return "\n".join(header).rstrip() + "\n\n"


def _write_lock(data: dict) -> None:
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=4096)
    LOCK.write_text(_lock_header() + body, encoding="utf-8")


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (pinned https)
        return resp.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _card_path(card: dict) -> Path:
    return COMMUNITY / card["id"] / card["file"]


def _validate_card(card: dict, idx: int) -> None:
    for key in ("id", "repo", "version", "source", "url", "file"):
        if not card.get(key):
            raise SystemExit(f"card #{idx}: missing required field '{key}'")
    if card["source"] not in ("release", "raw"):
        raise SystemExit(f"card {card['id']}: source must be 'release' or 'raw'")
    if not card["url"].startswith("https://"):
        raise SystemExit(f"card {card['id']}: url must be https")


def _regen_index(data: dict) -> None:
    index = {
        "bundle_version": data["bundle_version"],
        "cards": [{"id": c["id"], "file": c["file"]} for c in data["cards"]],
    }
    CARDS_INDEX.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def _sync_manifest(data: dict) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("version") != data["bundle_version"]:
        manifest["version"] = data["bundle_version"]
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"  synced manifest version -> {data['bundle_version']}")


def cmd_check(data: dict) -> int:
    errors = 0
    for i, card in enumerate(data["cards"]):
        _validate_card(card, i)
        path = _card_path(card)
        if not path.is_file():
            print(f"  MISSING  {card['id']}: {path.relative_to(ROOT)}")
            errors += 1
            continue
        if not card.get("sha256"):
            print(f"  NO-HASH  {card['id']}: lock has empty sha256 (run --update)")
            errors += 1
            continue
        actual = _sha256(path.read_bytes())
        if actual != card["sha256"]:
            print(f"  MISMATCH {card['id']}: lock={card['sha256'][:12]} disk={actual[:12]}")
            errors += 1
        else:
            print(f"  ok       {card['id']}  {card['version']}")
    # cards.json must be consistent with the lock
    if CARDS_INDEX.is_file():
        idx = json.loads(CARDS_INDEX.read_text(encoding="utf-8"))
        idx_ids = [c["id"] for c in idx.get("cards", [])]
        lock_ids = [c["id"] for c in data["cards"]]
        if idx_ids != lock_ids:
            print("  DRIFT    cards.json ids != lock ids")
            errors += 1
    else:
        print("  MISSING  cards.json")
        errors += 1
    print(f"\n{'FAIL' if errors else 'OK'}: {len(data['cards'])} cards, {errors} error(s)")
    return 1 if errors else 0


def cmd_fetch(data: dict, *, update: bool) -> int:
    errors = 0
    for i, card in enumerate(data["cards"]):
        _validate_card(card, i)
        try:
            blob = _download(card["url"])
        except Exception as exc:  # noqa: BLE001 — report + continue
            print(f"  ERROR    {card['id']}: download failed: {exc}")
            errors += 1
            continue
        digest = _sha256(blob)
        if update:
            card["sha256"] = digest
            note = "updated"
        else:
            if not card.get("sha256"):
                print(f"  NO-HASH  {card['id']}: lock empty — run --update first")
                errors += 1
                continue
            if digest != card["sha256"]:
                print(f"  MISMATCH {card['id']}: lock={card['sha256'][:12]} got={digest[:12]}")
                errors += 1
                continue
            note = "verified"
        path = _card_path(card)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        print(f"  ok       {card['id']:<24} {card['version']:<10} {len(blob):>8}B  {note}")

    if errors and not update:
        print(f"\nFAIL: {errors} error(s) — nothing regenerated")
        return 1

    if update:
        _write_lock(data)
        print("  wrote bundle.lock.yaml")
    _regen_index(data)
    print("  wrote community/cards.json")
    _sync_manifest(data)
    print(f"\n{'FAIL' if errors else 'OK'}: {len(data['cards'])} cards, {errors} error(s)")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true", help="download + rewrite sha256 into the lock")
    g.add_argument("--check", action="store_true", help="offline integrity check against the lock")
    args = ap.parse_args()

    data = _load_lock()
    if not data or "cards" not in data or "bundle_version" not in data:
        raise SystemExit("bundle.lock.yaml: missing 'bundle_version' or 'cards'")

    if args.check:
        return cmd_check(data)
    return cmd_fetch(data, update=args.update)


if __name__ == "__main__":
    sys.exit(main())
