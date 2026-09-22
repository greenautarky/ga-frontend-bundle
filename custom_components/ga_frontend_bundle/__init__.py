"""GA frontend card bundle — the de-HACS Lovelace card set.

A stateless integration that replaces HACS for delivering GreenAutarky's curated
Lovelace cards. On setup it:

1. serves the vendored card ``.js`` files as a static directory, and
2. injects each as a frontend JS module via ``add_extra_js_url`` so the
   ``custom:*`` elements (``custom:button-card``, ``custom:mushroom-*`` …)
   resolve on every dashboard.

No GitHub access, no HACS, no per-device Lovelace-resource registration. The
cards are pinned in ``bundle.lock.yaml`` and vendored at build time
(``scripts/vendor.py``).

No ``config_flow`` and no HA ``Store`` — the integration holds no persistent
state. It is activated by ``ga_frontend_bundle:`` in ``configuration.yaml``,
which converge maintains via its enable-list. See
``ga-ihost-docs/VENDORED-INTEGRATION-DELIVERY.md`` and ``docs/CONVERGE-HANDOFF.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .bundle import bundle_version, card_url, delivery_plan, load_cards
from .const import (
    COMMUNITY_DIRNAME,
    COMMUNITY_INJECT_ASSET_IDS,
    DOMAIN,
    EARLY_INJECT_ASSET_IDS,
    FIRST_PARTY_DIRNAME,
    FIRST_PARTY_URL_BASE,
    STATIC_URL_BASE,
)

_LOGGER = logging.getLogger(__name__)

# HA Core 2025.11.x silently skips async_setup for yaml-only integrations
# that don't declare a CONFIG_SCHEMA (= introduced quietly in 2024.x).
# The sibling integration greenautarky_site doesn't trip this
# because its manifest sets "config_flow": true (different code path).
# `cv.empty_config_schema(DOMAIN)` is the HA-canonical "I accept the bare
# `<domain>:` form, no other keys" pattern — matches every yaml-only
# integration in HA Core itself (cf. core's system_log, etc.).
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def _serve_inject(
    hass: HomeAssistant,
    directory: Path,
    url_base: str,
    version: str | None = None,
    inject_ids: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, str]], int]:
    """Load cards from ``directory``, serve them statically at ``url_base``, and
    inject the ones in ``inject_ids`` as frontend JS modules. Returns
    ``(cards, injected)``. ``inject_ids=None`` injects every card.

    NEVER inject anything that calls ``customElements.define()``. Injected
    modules are started by an inline ``<script>import(...)</script>`` in
    ``index.html``, side by side with the import of the app bundle — and the app
    bundle's FIRST line installs the scoped custom-element registry polyfill,
    which replaces ``window.customElements`` with a new, empty registry. A small
    injected file regularly finishes first, so its ``define()`` lands in the
    pre-swap registry: the call succeeds, nothing throws, and
    ``customElements.get()`` returns nothing forever after. HA then renders
    "Timeout waiting for strategy element" (strategy; K0, 2026-07-13: defined at
    t=101 ms, invisible thereafter) or "Custom element doesn't exist" (card;
    every first-party card on a freshly flashed canary, 2026-09-15).

    Lovelace RESOURCES are imported by the panel, long after the swap — which is
    why HA's docs say strategies must be loaded as resources, and why cards need
    exactly the same treatment. See ``bundle.delivery_plan``.

    Blocking dir scan runs in the executor. Missing dir → ``([], 0)``.
    """
    # iterdir()/glob()/is_file() are blocking — run the scan in the executor.
    cards = await hass.async_add_executor_job(load_cards, directory)
    if not cards:
        return [], 0

    await hass.http.async_register_static_paths(
        [StaticPathConfig(url_base, str(directory), True)]
    )

    injected = 0
    for card in cards:
        if inject_ids is not None and card["id"] not in inject_ids:
            continue
        try:
            add_extra_js_url(hass, card_url(url_base, card, version))
        except KeyError:
            # add_extra_js_url indexes hass.data["frontend_extra_module_url"],
            # which only exists once `frontend` has set up. We declare frontend
            # as a dependency so this should not happen on a real device; stay
            # defensive for minimal/test setups.
            _LOGGER.warning(
                "%s: frontend not ready — card %s not injected", DOMAIN, card["id"]
            )
            continue
        injected += 1
    return cards, injected


async def _register_resource_assets(
    hass: HomeAssistant, assets: list[dict[str, str]], version: str | None = None
) -> int:
    """Register first-party assets as Lovelace RESOURCES (never injected modules).

    This is the ONLY delivery path that works for anything defining a custom
    element. Injection via ``add_extra_js_url`` races the app bootstrap, and the
    app bundle's first line swaps ``window.customElements`` for the scoped
    custom-element registry polyfill: whatever registered before that swap is
    invisible to ``customElements.get()`` forever, with no error anywhere.

    The Lovelace panel, by contrast, loads its **resources** and only then
    resolves the dashboard — long after the swap. A strategy shipped as a
    resource is defined before HA looks for it (HA waits just 5 s and then
    renders "Timeout waiting for strategy element …"; that race was lost
    regularly on K0, 2026-07-13). A CARD shipped as a resource is the fix for
    "Custom element doesn't exist", which is what every first-party card
    rendered on a freshly flashed canary on 2026-09-15 — the belief that "cards
    do not care because they resolve lazily" was wrong: lazily resolved or not,
    they are resolved against the post-swap registry.

    Same URL whichever path pulled it in, so the browser's ES-module registry
    executes the file exactly once. Idempotent.
    """
    if not assets:
        return 0

    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
    except ImportError:  # pragma: no cover - lovelace is always there on GA OS
        _LOGGER.error(
            "%s: lovelace is not available — %d first-party asset(s) cannot be "
            "delivered and every card among them will render \"Custom element "
            "doesn\'t exist\": %s",
            DOMAIN,
            len(assets),
            ", ".join(a["id"] for a in assets),
        )
        return 0

    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    if resources is None:
        _LOGGER.error(
            "%s: lovelace resource store unavailable — %d first-party asset(s) "
            "are NOT delivered: %s. Cards will render \"Custom element doesn\'t "
            "exist\" and the dashboard strategy will time out.",
            DOMAIN,
            len(assets),
            ", ".join(a["id"] for a in assets),
        )
        hass.data.setdefault(DOMAIN, {})["resource_error"] = "lovelace-unavailable"
        return 0

    if not resources.loaded:
        await resources.async_load()

    items = list(resources.async_items())
    added = 0
    present = 0
    for card in assets:
        path = card_url(FIRST_PARTY_URL_BASE, card)  # unversioned base path
        url = card_url(FIRST_PARTY_URL_BASE, card, version)  # cache-busted target

        # Drop stale versioned copies of this asset (same path, different ?v),
        # otherwise every release leaves an old resource behind and the panel
        # loads TWO modules — the old one can still win the define race.
        for item in items:
            iu = item.get("url") or ""
            if iu.split("?", 1)[0] == path and iu != url:
                try:
                    await resources.async_delete_item(item["id"])
                    _LOGGER.info("%s: removed stale strategy resource %s", DOMAIN, iu)
                except Exception as err:  # noqa: BLE001 - never break HA start
                    _LOGGER.warning(
                        "%s: could not remove stale resource %s: %r", DOMAIN, iu, err
                    )

        if any((item.get("url") == url) for item in items):
            present += 1
            continue
        try:
            await resources.async_create_item({"res_type": "module", "url": url})
        except Exception as err:  # a broken resource store must not break HA start
            _LOGGER.error(
                "%s: could not register resource %s — <%s> will not exist in the "
                "browser: %r",
                DOMAIN,
                url,
                card["id"],
                err,
            )
            continue
        added += 1
        _LOGGER.info("%s: registered first-party resource %s", DOMAIN, url)

    if added + present != len(assets):
        # Loud on purpose: a partial delivery is the state the operator meets as
        # "the card just shows a red error box", and until now it was silent.
        _LOGGER.error(
            "%s: only %d of %d first-party asset(s) are delivered as Lovelace "
            "resources — the rest will not exist in the browser",
            DOMAIN,
            added + present,
            len(assets),
        )
        hass.data.setdefault(DOMAIN, {})["resource_error"] = "partial"
    return added


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the GA frontend bundle (yaml-activated, idempotent)."""
    if DOMAIN in hass.data:
        return True
    hass.data[DOMAIN] = {}

    pkg = Path(__file__).parent

    # Cache-buster for every served card/strategy URL: the bundle version (synced
    # to the integration manifest by scripts/vendor.py). Changing it on each
    # release forces browsers to fetch the new module instead of the long-cached
    # old one (K0, 2026-07-22).
    version = await hass.async_add_executor_job(bundle_version, pkg)

    # Vendored community cards (the de-HACS set, pinned in bundle.lock.yaml).
    community_dir = pkg / COMMUNITY_DIRNAME
    cards, injected = await _serve_inject(
        hass,
        community_dir,
        STATIC_URL_BASE,
        version,
        inject_ids=COMMUNITY_INJECT_ASSET_IDS,
    )
    if not cards:
        _LOGGER.error(
            "%s: no vendored cards under %s — bundle is empty. Did "
            "scripts/vendor.py run before packaging? Not blocking HA start.",
            DOMAIN,
            community_dir,
        )

    # First-party GA assets (authored here: ga-master-card, ga-home-strategy).
    # Separate dir + URL base so the vendor lock/integrity checks never touch them.
    first_party_dir = pkg / FIRST_PARTY_DIRNAME
    fp_cards, fp_injected = await _serve_inject(
        hass,
        first_party_dir,
        FIRST_PARTY_URL_BASE,
        version,
        inject_ids=EARLY_INJECT_ASSET_IDS,
    )

    # Everything else first-party is delivered as a Lovelace RESOURCE — the only
    # path that survives HA's custom-element registry swap (see delivery_plan).
    # Deferred to EVENT_HOMEASSISTANT_STARTED: lovelace sets up after us.
    _fp_inject, fp_resources = delivery_plan(fp_cards, EARLY_INJECT_ASSET_IDS)

    async def _resources_started(_event: Event | None = None) -> None:
        await _register_resource_assets(hass, fp_resources, version)

    if hass.state is CoreState.running:
        hass.async_create_task(_resources_started())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _resources_started)

    hass.data[DOMAIN] = {
        "cards": cards,
        "injected": injected,
        "first_party_cards": fp_cards,
        "first_party_injected": fp_injected,
        "first_party_resources": [c["id"] for c in fp_resources],
    }
    if fp_cards and not fp_resources:
        _LOGGER.error(
            "%s: not one first-party asset is delivered as a Lovelace resource — "
            "if any of them defines a custom element it will not exist in the "
            "browser",
            DOMAIN,
        )
    _LOGGER.info(
        "%s: community %d cards (injected %d) at %s; first-party %d at %s "
        "(injected early: %s; Lovelace resources: %s)",
        DOMAIN,
        len(cards),
        injected,
        STATIC_URL_BASE,
        len(fp_cards),
        FIRST_PARTY_URL_BASE,
        ", ".join(c["id"] for c in _fp_inject) or "none",
        ", ".join(c["id"] for c in fp_resources) or "none",
    )
    return True
