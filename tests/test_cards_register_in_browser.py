"""Every shipped first-party card must end up in the registry HA looks in.

WHY THIS TEST IS NOT A STRING ASSERTION
---------------------------------------
Measured in a real browser on a freshly flashed canary (2026-09-15): every
first-party card file was fetched, served 200, and contained its
``customElements.define(...)`` — while ``customElements.get()`` returned nothing
for all of them and the dashboard showed Home Assistant's red "Custom element
doesn't exist" box. Every file-content check in ``tests/`` was green in exactly
that state, so none of them can be the gate. This one drives a headless Chromium
through the load order ``index.html`` produces and asks the browser.

WHAT IT PROVES
--------------
``tests/browser/cards-register.mjs`` reproduces the page: injected
``extra_modules`` execute, then the app bundle installs the REAL
``@webcomponents/scoped-custom-element-registry`` polyfill (which replaces
``window.customElements`` with an empty registry), then Lovelace resources load.
The split between the first and the last phase is not invented here — it is the
integration's own ``delivery_plan()`` decision.

COVERAGE, NOT EXIT CODE
-----------------------
The asset list comes from scanning ``first_party/``; the element names come from
RUNNING each asset in a pristine page and recording what it defines. A card added
later is therefore covered with nobody remembering to add it. Zero assets, zero
discovered elements, or a missing must-cover element all fail.

NO SILENT SKIP
--------------
Like ``tests/test_rendered_output.py``, this fails — never skips — when its
runtime is missing. Run ``npm ci`` (or ``npm install``) in ``tests/browser`` and
``npx playwright install chromium`` once.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile

import pytest
from conftest import PKG, REPO

FIRST_PARTY = PKG / "first_party"
BROWSER_DIR = REPO / "tests" / "browser"
HARNESS = BROWSER_DIR / "cards-register.mjs"

# Must-cover floor: pinned here, never derived from the tree under test, so that
# deleting a card cannot quietly shrink what this test covers.
MUST_COVER_ELEMENTS = frozenset(
    {
        "ga-heating-card",
        "ga-thermostat-card",
        "ga-master-card",
        "ll-strategy-dashboard-ga-home",
    }
)


def _load_first_party() -> list[dict[str, str]]:
    """Scan the shipped tree with the integration's own loader."""
    sys.path.insert(0, str(PKG.parent))
    import importlib.util

    spec = importlib.util.spec_from_file_location("ga_fb_bundle_b", PKG / "bundle.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    spec_c = importlib.util.spec_from_file_location("ga_fb_const_b", PKG / "const.py")
    assert spec_c and spec_c.loader
    const = importlib.util.module_from_spec(spec_c)
    spec_c.loader.exec_module(const)

    cards = mod.load_cards(FIRST_PARTY)
    inject, resource = mod.delivery_plan(cards, const.EARLY_INJECT_ASSET_IDS)
    return cards, inject, resource


def _run_harness() -> dict:
    cards, inject, resource = _load_first_party()
    if not cards:
        pytest.fail(
            f"no first-party assets found under {FIRST_PARTY} — this test inspected "
            "nothing, which is a failure, not a pass"
        )
    if shutil.which("node") is None:
        pytest.fail("node is required for the browser card-registration proof")
    if not (BROWSER_DIR / "node_modules").is_dir():
        pytest.fail(
            f"{BROWSER_DIR}/node_modules missing — run `npm ci` there "
            "(and `npx playwright install chromium` once)"
        )

    plan = {
        "root": str(FIRST_PARTY),
        "version": json.loads((PKG / "manifest.json").read_text())["version"],
        "inject": inject,
        "resource": resource,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(plan, fh)
        plan_path = fh.name

    proc = subprocess.run(
        ["node", str(HARNESS), plan_path],
        capture_output=True,
        text=True,
        cwd=str(BROWSER_DIR),
        timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"browser harness exited {proc.returncode}\n--- stderr ---\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


_RESULT: dict | None = None


def result() -> dict:
    global _RESULT
    if _RESULT is None:
        _RESULT = _run_harness()
    return _RESULT


def _discovered_elements() -> list[tuple[str, str]]:
    """(element tag, owning asset id) for everything the shipped assets define."""
    res = result()
    return sorted((tag, owner) for tag, owner in res["tagOwner"].items())


# Collection-time discovery: one named test per shipped element, so a mutation
# to one card turns exactly that card's test red.
try:
    _ELEMENTS = _discovered_elements()
    _DISCOVERY_ERROR = None
except BaseException as err:  # noqa: BLE001 - surfaced as a failing test below
    _ELEMENTS = []
    _DISCOVERY_ERROR = err


def test_harness_ran():
    if _DISCOVERY_ERROR is not None:
        raise AssertionError(f"browser harness did not run: {_DISCOVERY_ERROR!r}")
    res = result()
    assert res["appLoaded"], (
        "the app bundle did not replace window.customElements — the harness was not "
        "reproducing Home Assistant's load order, so its verdict means nothing"
    )
    assert not res["errors"], f"assets raised while loading: {res['errors']}"
    assert not res.get("importFailures"), (
        f"a shipped asset failed to import: {res['importFailures']}"
    )


def test_every_shipped_asset_was_inspected():
    """Fail closed: zero assets or zero discovered elements is a failure."""
    if _DISCOVERY_ERROR is not None:
        pytest.skip("covered by test_harness_ran")
    res = result()
    assert res["defines"], "no first-party assets were executed"
    tags = {t for tags in res["defines"].values() for t in tags}
    assert tags, "not a single custom element was discovered — nothing was tested"
    missing = MUST_COVER_ELEMENTS - tags
    assert not missing, (
        f"must-cover elements are no longer shipped or no longer register at all: "
        f"{sorted(missing)}"
    )


@pytest.mark.parametrize(
    ("element", "owner"), _ELEMENTS, ids=[f"{t}" for t, _ in _ELEMENTS]
)
def test_element_is_in_the_live_registry(element: str, owner: str):
    """The card is visible to `customElements.get()` after HA's registry swap.

    Red on the shipped state of 2026-09-15: the card was injected via
    `add_extra_js_url`, defined into the pre-swap registry, and Home Assistant
    rendered "Custom element doesn't exist".
    """
    res = result()
    assert res["live"].get(element) is True, (
        f"{owner} defines <{element}> but it is NOT in the live custom-element "
        "registry after Home Assistant's bootstrap — HA will render "
        f'"Custom element doesn\'t exist: {element}". Deliver the asset as a '
        "Lovelace resource instead of injecting it with add_extra_js_url."
    )


# ─── the guard must be loud, and must not cry wolf ────────────────────────


def test_guard_flags_an_element_that_lost_the_registry_swap():
    """MUST-FLAG fixture: a card registered before the swap has to produce a
    console error. Nothing in the stack said anything on the canary; that
    silence is the reason the defect survived three operator complaints."""
    res = result()
    guard = res["guard"]
    assert guard["present"], (
        "no registry guard is delivered — a card that cannot register would be "
        "silent again"
    )
    assert guard["flaggedLostFixture"], (
        "the guard stayed silent about an element defined before the registry "
        f"swap. console errors seen: {guard['consoleErrors']}"
    )


def test_guard_stays_quiet_about_a_correctly_delivered_element():
    """MUST-NOT-FLAG fixture: a guard that flags healthy cards gets ignored,
    which is a slower way of having no guard."""
    guard = result()["guard"]
    assert not guard["flaggedLateFixture"], (
        "the guard flagged an element that was delivered correctly (after the "
        f"swap): {guard['consoleErrors']}"
    )
