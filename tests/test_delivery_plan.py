"""How a first-party asset reaches the browser decides whether it works.

The pure half of the 2026-09-15 fix: `add_extra_js_url` injection is an
ALLOW-LIST, so anything added to `first_party/` later is a Lovelace resource by
default — which is the answer that works for every asset that defines a custom
element. The browser proof lives in `test_cards_register_in_browser.py`.
"""

from __future__ import annotations

import importlib.util
import re

from conftest import PKG

FIRST_PARTY = PKG / "first_party"
GUARD = FIRST_PARTY / "ga-registry-guard" / "ga-registry-guard.js"
# A known-positive for the comment-stripping above: this one really does define.
CARD = FIRST_PARTY / "ga-heating-card" / "ga-heating-card.js"


def _const():
    spec = importlib.util.spec_from_file_location("ga_fb_const_dp", PKG / "const.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_unknown_asset_defaults_to_the_lovelace_resource_path(bundle_module):
    """The safe default. A card added next month must not be injected just
    because nobody remembered to add it to a list."""
    cards = [{"id": "ga-brand-new-card", "file": "x.js"}]
    inject, resource = bundle_module.delivery_plan(cards, _const().EARLY_INJECT_ASSET_IDS)
    assert inject == []
    assert resource == cards


def test_no_shipped_card_is_on_the_early_injection_path(bundle_module):
    """Fail closed: enumerate what is actually shipped, not a hand-kept list."""
    cards = bundle_module.load_cards(FIRST_PARTY)
    assert cards, f"no first-party assets found under {FIRST_PARTY}"
    inject, resource = bundle_module.delivery_plan(cards, _const().EARLY_INJECT_ASSET_IDS)
    assert resource, "not one asset is delivered as a Lovelace resource"
    assert {c["id"] for c in inject} == {"ga-registry-guard", "ga-sidebar-default"}, (
        "only assets that define NO custom element may be injected early; "
        f"got {[c['id'] for c in inject]}"
    )


def test_the_registry_guard_ships_and_defines_no_element_of_its_own():
    """A watchdog that can itself be lost to the registry swap is no watchdog.
    The guard registers nothing, so it is immune to what it watches."""
    # Strip comments first: the guard EXPLAINS the failure it watches, and prose
    # naming `customElements.define` is not a call (the `# shellcheck`-in-a-
    # docstring trap, one repo over).
    src = re.sub(r"/\*.*?\*/", "", GUARD.read_text(encoding="utf-8"), flags=re.S)
    src = re.sub(r"//.*", "", src)
    assert "customElements.define" not in src
    # ...and the check must be able to see a real call, or it proves nothing.
    assert "customElements.define" in re.sub(
        r"//.*", "", re.sub(r"/\*.*?\*/", "", CARD.read_text(encoding="utf-8"), flags=re.S)
    )
    assert "ga-registry-guard" in _const().EARLY_INJECT_ASSET_IDS
