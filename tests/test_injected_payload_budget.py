"""What we inject has a byte budget, and the budget is small on purpose.

Every injected module is fetched before the app can start our own cards, on
every dashboard load, on a device that usually reaches the resident over a mesh
link. So the size of that set is a product decision, not an implementation
detail — and until 2026-09-22 nobody could see it: thirteen vendored cards were
injected, 5.92 MB of them, and the two our strategy places are 148 KB.

A byte budget is the sharp half of that measurement. It is deterministic — no
browser, no network, no flake — so it can fail a pull request, which a
wall-clock threshold on a mesh-linked device cannot do without being ignored
after the second false red. The time this buys is measured separately, on a
real device, in the e2e lane.

The budget is deliberately close to today's number. A limit ten times the
current value is not a limit; it is a note that something once cared.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from conftest import PKG

COMMUNITY = PKG / "community"
FIRST_PARTY = PKG / "first_party"
CONST = PKG / "const.py"

# 148 KB community + 7 KB first-party today. 256 KB leaves room for a card to
# grow or for one more small module, and refuses another megabyte.
BUDGET_BYTES = 256 * 1024


def _const(name: str) -> tuple[str, ...]:
    tree = ast.parse(CONST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found in {CONST} — failing rather than measuring nothing")


def _bytes_of(root: pathlib.Path, ids: tuple[str, ...]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for asset_id in ids:
        directory = root / asset_id
        assert directory.is_dir(), f"allow-listed asset {asset_id!r} is not vendored at {directory}"
        sizes[asset_id] = sum(f.stat().st_size for f in directory.rglob("*.js"))
    return sizes


def test_the_injected_set_fits_the_budget():
    community = _bytes_of(COMMUNITY, _const("COMMUNITY_INJECT_ASSET_IDS"))
    first_party = _bytes_of(FIRST_PARTY, _const("EARLY_INJECT_ASSET_IDS"))
    total = sum(community.values()) + sum(first_party.values())
    breakdown = " ".join(
        f"{k}={v / 1024:.0f}KB" for k, v in sorted({**community, **first_party}.items())
    )
    print(f"\ninjected payload: {total / 1024:.0f} KB  ({breakdown})")
    assert total <= BUDGET_BYTES, (
        f"injected assets are {total / 1024:.0f} KB, budget {BUDGET_BYTES / 1024:.0f} KB.\n"
        f"  {breakdown}\n"
        "Every one of these is downloaded before the browser starts our cards, on "
        "every dashboard load. If the new asset is really needed on every page, "
        "raise the budget IN THIS COMMIT and say what it buys; if it is needed on "
        "one dashboard, deliver it as a Lovelace resource instead."
    )


def test_the_budget_could_be_exceeded():
    """Rule 45: a budget that cannot be exceeded measures nothing. The heaviest
    vendored card alone is far over it — which is exactly the state this file
    was written for."""
    heavy = max(
        (sum(f.stat().st_size for f in d.rglob("*.js")), d.name)
        for d in COMMUNITY.iterdir()
        if d.is_dir()
    )
    assert heavy[0] > BUDGET_BYTES, (
        f"the largest vendored card ({heavy[1]}, {heavy[0] / 1024:.0f} KB) is under "
        "the budget, so nothing in the repository could ever trip it — either the "
        "bundle changed completely or the budget is meaningless"
    )


@pytest.mark.parametrize("asset_id", ["plotly-graph-card", "apexcharts-card", "mushroom"])
def test_the_cards_this_was_written_for_stay_out(asset_id):
    """Not a style rule: these three are 5.4 MB of the 5.92 MB that were injected,
    and none is referenced anywhere. If one comes back, it must come back with a
    reason in the diff — and it will fail the budget above as well."""
    assert asset_id not in _const("COMMUNITY_INJECT_ASSET_IDS")
